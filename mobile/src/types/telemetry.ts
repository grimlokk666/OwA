/** Payload posted to self-hosted POST /api/telemetry */

export interface TelemetryPoint {
  /** ISO-8601 timestamp from the device clock */
  ts: string;
  /** Stable device id (local UUID, never a vendor ID) */
  deviceId: string;
  /** Operator-chosen callsign / node name */
  callsign: string;
  lat: number;
  lon: number;
  /** Meters above WGS84 ellipsoid when available */
  alt?: number | null;
  /** Accuracy radius in meters */
  accuracy?: number | null;
  /** Degrees from true north when available */
  heading?: number | null;
  /** m/s when available */
  speed?: number | null;
  /** 0–100; null if unknown */
  battery?: number | null;
  /** Whether the device is charging */
  charging?: boolean | null;
  /** Source of the fix */
  source: 'capacitor' | 'geolocation' | 'cached';
}

export interface EncryptedTelemetryEnvelope {
  /** Always "sovereign-aes-gcm-v1" for this client */
  v: 'sovereign-aes-gcm-v1';
  deviceId: string;
  callsign: string;
  /** Base64 IV (12 bytes) */
  iv: string;
  /** Base64 ciphertext of JSON.stringify(TelemetryPoint) */
  ciphertext: string;
  /** Plaintext timestamp for server-side ordering without decrypt */
  ts: string;
}

export interface TelemetryConfig {
  /** Base URL of self-hosted Overwatch (Tailscale MagicDNS or mesh IP) */
  backendBaseUrl: string;
  /** Full path; default /api/telemetry */
  telemetryPath: string;
  /** Interval between fixes in ms (default 60000) */
  intervalMs: number;
  callsign: string;
  deviceId: string;
  /**
   * AES-GCM key as base64 (32 raw bytes). Required.
   * Encryption failure does not fall back to plaintext.
   */
  encryptionKeyBase64: string;
  /** Shared API token sent as the X-Overwatch-Token header. */
  apiToken: string;
  /** Dashboard URL loaded in the operational viewer iframe/WebView */
  dashboardUrl: string;
  enabled: boolean;
}

export const DEFAULT_TELEMETRY_CONFIG: Omit<
  TelemetryConfig,
  'deviceId' | 'callsign'
> = {
  backendBaseUrl: '',
  telemetryPath: '/api/telemetry',
  intervalMs: 60_000,
  encryptionKeyBase64: '',
  apiToken: '',
  dashboardUrl: '',
  enabled: false,
};
