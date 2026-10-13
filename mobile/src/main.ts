/**
 * Sovereign Overwatch mobile companion shell.
 * - Loads self-hosted dashboard over Tailscale
 * - Runs local telemetry node (Capacitor / PWA)
 */

import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { telemetryService } from './telemetry/service';

const dashboardFrame = document.getElementById('dashboard') as HTMLIFrameElement | null;
const statusEl = document.getElementById('status');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const inputUrl = document.getElementById('backend-url') as HTMLInputElement | null;
const inputCallsign = document.getElementById('callsign') as HTMLInputElement | null;
const inputKey = document.getElementById('enc-key') as HTMLInputElement | null;
const inputToken = document.getElementById('api-token') as HTMLInputElement | null;

function setStatus(text: string) {
  if (statusEl) statusEl.textContent = text;
}

async function boot() {
  const cfg = await telemetryService.loadConfig();
  if (inputUrl) inputUrl.value = cfg.backendBaseUrl || cfg.dashboardUrl || '';
  if (inputCallsign) inputCallsign.value = cfg.callsign;
  if (inputKey) inputKey.value = cfg.encryptionKeyBase64;
  if (inputToken) inputToken.value = cfg.apiToken || '';

  const dash =
    cfg.dashboardUrl ||
    cfg.backendBaseUrl ||
    (Capacitor.isNativePlatform() ? '' : window.location.origin);

  if (dashboardFrame && dash) {
    dashboardFrame.src = dash;
  }

  telemetryService.onStatus((s) => {
    setStatus(
      `${s.state.toUpperCase()} | fix: ${s.lastFix ?? '—'} | queue: ${s.queueDepth}`
    );
  });

  btnStart?.addEventListener('click', async () => {
    await telemetryService.saveConfig({
      backendBaseUrl: inputUrl?.value.trim() || '',
      dashboardUrl: inputUrl?.value.trim() || '',
      callsign: inputCallsign?.value.trim() || 'ALPHA-1',
      encryptionKeyBase64: inputKey?.value.trim() || '',
      apiToken: inputToken?.value.trim() || '',
      enabled: true,
      intervalMs: 60_000,
      telemetryPath: '/api/telemetry',
    });
    if (dashboardFrame && inputUrl?.value.trim()) {
      dashboardFrame.src = inputUrl.value.trim();
    }
    await telemetryService.start();
  });

  btnStop?.addEventListener('click', () => void telemetryService.stop());

  if (Capacitor.isNativePlatform()) {
    App.addListener('appStateChange', ({ isActive }) => {
      // Android: keep interval alive while app is backgrounded when possible.
      // iOS: OS will freeze JS — see docs/MOBILE.md for limitations.
      if (isActive) void telemetryService.flush();
    });
  }

  // Auto-arm if previously enabled
  if (cfg.enabled) {
    await telemetryService.start();
  }
}

void boot();
