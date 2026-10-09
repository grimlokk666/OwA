/**
 * Optional AES-256-GCM envelope for POST /api/telemetry.
 * Key stays on-device (Preferences / localStorage) — never sent to SaaS.
 */

import type { EncryptedTelemetryEnvelope, TelemetryPoint } from '../types/telemetry';

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToB64(bytes: Uint8Array): string {
  let s = '';
  bytes.forEach((b) => {
    s += String.fromCharCode(b);
  });
  return btoa(s);
}

export async function encryptPoint(
  point: TelemetryPoint,
  keyBase64: string
): Promise<TelemetryPoint | EncryptedTelemetryEnvelope> {
  if (!keyBase64.trim()) return point;

  const keyBytes = b64ToBytes(keyBase64.trim());
  if (keyBytes.byteLength !== 32) {
    console.warn('Encryption key must be 32 bytes base64; sending plaintext');
    return point;
  }

  const key = await crypto.subtle.importKey(
    'raw',
    keyBytes.buffer.slice(
      keyBytes.byteOffset,
      keyBytes.byteOffset + keyBytes.byteLength
    ) as ArrayBuffer,
    { name: 'AES-GCM' },
    false,
    ['encrypt']
  );
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(JSON.stringify(point));
  const cipherBuf = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);

  return {
    v: 'sovereign-aes-gcm-v1',
    deviceId: point.deviceId,
    callsign: point.callsign,
    iv: bytesToB64(iv),
    ciphertext: bytesToB64(new Uint8Array(cipherBuf)),
    ts: point.ts,
  };
}
