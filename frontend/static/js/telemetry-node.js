/**
 * Sovereign Overwatch — background telemetry node (browser / PWA)
 *
 * OwnTracks/Traccar-style loop:
 *  - Geolocation every 60s
 *  - POST encrypted or plaintext JSON to /api/telemetry
 *  - IndexedDB queue when Tailscale/VPN/cellular is down; flush on reconnect
 *
 * Note: browsers (esp. iOS Safari) suspend background tabs aggressively.
 * For true background tracking on Android, prefer the Capacitor APK wrapper
 * (see /mobile and docs/MOBILE.md).
 */
(function (global) {
  const DB_NAME = 'sovereign-overwatch-telemetry';
  const STORE = 'outbox';
  const INTERVAL_MS = 60_000;
  const ENDPOINT = '/api/telemetry';

  /** @type {number|null} */
  let timerId = null;
  /** @type {((s: object) => void)|null} */
  let statusCb = null;
  let callsign = localStorage.getItem('sovereign.callsign') || 'ALPHA-1';
  let deviceId = localStorage.getItem('sovereign.deviceId') || '';
  let lastFix = null;
  let state = 'disarmed';

  function ensureDeviceId() {
    if (!deviceId) {
      deviceId =
        crypto.randomUUID?.() ||
        `dev-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem('sovereign.deviceId', deviceId);
    }
    return deviceId;
  }

  function emit() {
    if (statusCb) {
      statusCb({ state, lastFix, queueDepth: pendingCount });
    }
  }

  let pendingCount = 0;
  let dbPromise = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }

  async function enqueue(point) {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).add({ point, queuedAt: Date.now() });
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    pendingCount += 1;
    emit();
  }

  async function refreshQueueCount() {
    const db = await openDb();
    pendingCount = await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).count();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    emit();
  }

  async function flushQueue() {
    const db = await openDb();
    const rows = await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
    if (!rows.length) return;

    const batch = rows.map((r) => r.point);
    const ok = await postTelemetry(batch);
    if (!ok) return;

    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      const store = tx.objectStore(STORE);
      for (const row of rows) store.delete(row.id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    pendingCount = 0;
    emit();
  }

  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64(bytes) {
    let s = '';
    bytes.forEach((b) => {
      s += String.fromCharCode(b);
    });
    return btoa(s);
  }

  async function maybeEncrypt(point) {
    const keyB64 = localStorage.getItem('sovereign.telemetryKey') || '';
    if (!keyB64) return point;
    try {
      const keyBytes = b64ToBytes(keyB64);
      if (keyBytes.byteLength !== 32) return point;
      const key = await crypto.subtle.importKey(
        'raw',
        keyBytes,
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
    } catch (e) {
      console.warn('Encrypt failed; sending plaintext over mesh TLS', e);
      return point;
    }
  }

  async function postTelemetry(body) {
    try {
      const res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        keepalive: true,
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  function readBattery() {
    return new Promise((resolve) => {
      if (!navigator.getBattery) {
        resolve({ battery: null, charging: null });
        return;
      }
      navigator
        .getBattery()
        .then((b) =>
          resolve({
            battery: Math.round(b.level * 100),
            charging: !!b.charging,
          })
        )
        .catch(() => resolve({ battery: null, charging: null }));
    });
  }

  function getPosition() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error('Geolocation unavailable'));
        return;
      }
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        maximumAge: 15_000,
        timeout: 20_000,
      });
    });
  }

  async function tick() {
    state = 'tracking';
    emit();
    try {
      const [pos, batt] = await Promise.all([getPosition(), readBattery()]);
      const point = {
        ts: new Date().toISOString(),
        deviceId: ensureDeviceId(),
        callsign,
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        alt: pos.coords.altitude,
        accuracy: pos.coords.accuracy,
        heading: pos.coords.heading,
        speed: pos.coords.speed,
        battery: batt.battery,
        charging: batt.charging,
        source: 'geolocation',
      };
      lastFix = `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)} @ ${point.ts}`;
      emit();

      const payload = await maybeEncrypt(point);
      const ok = await postTelemetry(payload);
      if (!ok) {
        await enqueue(point);
        state = 'queued';
      } else {
        await flushQueue();
        state = 'tracking';
      }
      emit();
    } catch (e) {
      console.warn('Telemetry tick failed', e);
      state = 'error';
      emit();
    }
  }

  async function start() {
    ensureDeviceId();
    await refreshQueueCount();
    if (timerId != null) return;
    state = 'tracking';
    emit();
    await tick();
    timerId = window.setInterval(tick, INTERVAL_MS);
    window.addEventListener('online', flushQueue);
  }

  async function stop() {
    if (timerId != null) {
      clearInterval(timerId);
      timerId = null;
    }
    window.removeEventListener('online', flushQueue);
    state = 'disarmed';
    emit();
  }

  global.SovereignTelemetry = {
    start,
    stop,
    isRunning: () => timerId != null,
    setCallsign: (c) => {
      callsign = c || 'ALPHA-1';
      localStorage.setItem('sovereign.callsign', callsign);
    },
    onStatus: (cb) => {
      statusCb = cb;
      emit();
    },
    flushQueue,
  };
})(window);
