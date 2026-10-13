/**
 * Background GPS telemetry loop — Capacitor Geolocation with HTML5 fallback.
 * Interval default: 60 seconds. Offline → IndexedDB → flush on reconnect.
 */

import { Geolocation } from '@capacitor/geolocation';
import { Network } from '@capacitor/network';
import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';

import type { TelemetryConfig, TelemetryPoint } from '../types/telemetry';
import { DEFAULT_TELEMETRY_CONFIG } from '../types/telemetry';
import { encryptPoint } from './crypto';
import {
  countQueued,
  deleteQueued,
  enqueuePoint,
  listQueued,
} from './outbox';

export type TelemetryStatus = {
  state: 'disarmed' | 'tracking' | 'queued' | 'error';
  lastFix: string | null;
  queueDepth: number;
};

type StatusListener = (s: TelemetryStatus) => void;

const CONFIG_KEY = 'sovereign.telemetry.config';

export class TelemetryService {
  private timer: ReturnType<typeof setInterval> | null = null;
  private config: TelemetryConfig | null = null;
  private listeners = new Set<StatusListener>();
  private status: TelemetryStatus = {
    state: 'disarmed',
    lastFix: null,
    queueDepth: 0,
  };
  private networkUnsub: (() => void) | null = null;

  onStatus(cb: StatusListener): () => void {
    this.listeners.add(cb);
    cb(this.status);
    return () => this.listeners.delete(cb);
  }

  private emit(partial: Partial<TelemetryStatus>) {
    this.status = { ...this.status, ...partial };
    for (const cb of this.listeners) cb(this.status);
  }

  async loadConfig(): Promise<TelemetryConfig> {
    const { value } = await Preferences.get({ key: CONFIG_KEY });
    if (value) {
      this.config = { ...DEFAULT_TELEMETRY_CONFIG, ...JSON.parse(value) } as TelemetryConfig;
      return this.config;
    }
    const deviceId = crypto.randomUUID();
    this.config = {
      ...DEFAULT_TELEMETRY_CONFIG,
      deviceId,
      callsign: 'ALPHA-1',
      backendBaseUrl: '',
      dashboardUrl: '',
    };
    await this.saveConfig(this.config);
    return this.config;
  }

  async saveConfig(partial: Partial<TelemetryConfig>): Promise<TelemetryConfig> {
    const current = this.config ?? (await this.loadConfig());
    this.config = { ...current, ...partial };
    await Preferences.set({
      key: CONFIG_KEY,
      value: JSON.stringify(this.config),
    });
    return this.config;
  }

  isRunning(): boolean {
    return this.timer != null;
  }

  async start(): Promise<void> {
    const cfg = await this.loadConfig();
    if (!cfg.backendBaseUrl && !cfg.dashboardUrl) {
      // Same-origin relative /api when served from Overwatch frontend
      await this.saveConfig({ backendBaseUrl: '' });
    }
    if (this.timer) return;

    this.emit({ state: 'tracking', queueDepth: await countQueued() });
    await this.tick();
    this.timer = setInterval(() => void this.tick(), cfg.intervalMs || 60_000);

    const handle = await Network.addListener('networkStatusChange', (s) => {
      if (s.connected) void this.flush();
    });
    this.networkUnsub = () => handle.remove();
  }

  async stop(): Promise<void> {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.networkUnsub?.();
    this.networkUnsub = null;
    this.emit({ state: 'disarmed' });
  }

  private endpoint(): string {
    const cfg = this.config!;
    const base = (cfg.backendBaseUrl || '').replace(/\/$/, '');
    const path = cfg.telemetryPath || '/api/telemetry';
    return `${base}${path.startsWith('/') ? path : `/${path}`}`;
  }

  private async getFix(): Promise<TelemetryPoint> {
    const cfg = this.config!;
    let coords: {
      latitude: number;
      longitude: number;
      altitude: number | null;
      accuracy: number | null;
      heading: number | null;
      speed: number | null;
    };
    let source: TelemetryPoint['source'] = 'geolocation';

    if (Capacitor.isNativePlatform()) {
      const perm = await Geolocation.requestPermissions();
      if (perm.location === 'denied') {
        throw new Error('Location permission denied');
      }
      const pos = await Geolocation.getCurrentPosition({
        enableHighAccuracy: true,
        timeout: 20_000,
        maximumAge: 15_000,
      });
      coords = {
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        altitude: pos.coords.altitude,
        accuracy: pos.coords.accuracy,
        heading: pos.coords.heading,
        speed: pos.coords.speed,
      };
      source = 'capacitor';
    } else {
      const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 20_000,
          maximumAge: 15_000,
        });
      });
      coords = {
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        altitude: pos.coords.altitude,
        accuracy: pos.coords.accuracy,
        heading: pos.coords.heading,
        speed: pos.coords.speed,
      };
    }

    const batt = await this.readBattery();

    return {
      ts: new Date().toISOString(),
      deviceId: cfg.deviceId,
      callsign: cfg.callsign,
      lat: coords.latitude,
      lon: coords.longitude,
      alt: coords.altitude,
      accuracy: coords.accuracy,
      heading: coords.heading,
      speed: coords.speed,
      battery: batt.level,
      charging: batt.charging,
      source,
    };
  }

  private async readBattery(): Promise<{
    level: number | null;
    charging: boolean | null;
  }> {
    try {
      // Battery Status API (Chromium); unavailable on many iOS builds
      const nav = navigator as Navigator & {
        getBattery?: () => Promise<{ level: number; charging: boolean }>;
      };
      if (!nav.getBattery) return { level: null, charging: null };
      const b = await nav.getBattery();
      return { level: Math.round(b.level * 100), charging: b.charging };
    } catch {
      return { level: null, charging: null };
    }
  }

  private requestHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const token = this.config?.apiToken?.trim();
    if (token) headers['X-Overwatch-Token'] = token;
    return headers;
  }

  private async post(body: unknown): Promise<boolean> {
    try {
      const res = await fetch(this.endpoint(), {
        method: 'POST',
        headers: this.requestHeaders(),
        body: JSON.stringify(body),
        keepalive: true,
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  async tick(): Promise<void> {
    try {
      const point = await this.getFix();
      this.emit({
        lastFix: `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)} @ ${point.ts}`,
      });

      let payload;
      try {
        payload = await encryptPoint(point, this.config!.encryptionKeyBase64);
      } catch (encryptError) {
        console.warn('Encryption failed; plaintext was not sent', encryptError);
        this.emit({ state: 'error', queueDepth: await countQueued() });
        return;
      }
      const ok = await this.post(payload);
      if (!ok) {
        await enqueuePoint(point);
        this.emit({ state: 'queued', queueDepth: await countQueued() });
        return;
      }
      await this.flush();
      this.emit({ state: 'tracking', queueDepth: await countQueued() });
    } catch (e) {
      console.warn('Telemetry tick error', e);
      this.emit({ state: 'error' });
    }
  }

  async flush(): Promise<void> {
    const queued = await listQueued();
    if (!queued.length) return;
    for (const row of queued) {
      let payload;
      try {
        payload = await encryptPoint(row.point, this.config!.encryptionKeyBase64);
      } catch (encryptError) {
        console.warn('Encryption failed; queued point kept locally', encryptError);
        this.emit({ state: 'error', queueDepth: await countQueued() });
        return;
      }
      const ok = await this.post(payload);
      if (!ok) {
        this.emit({ state: 'queued', queueDepth: await countQueued() });
        return;
      }
      await deleteQueued(row.id);
    }
    this.emit({ state: 'tracking', queueDepth: await countQueued() });
  }
}

export const telemetryService = new TelemetryService();
