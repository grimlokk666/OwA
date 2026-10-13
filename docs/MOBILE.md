# Sovereign Overwatch — Mobile Companion

Local-first mobile client for the self-hosted tactical dashboard.

**Sovereign D rules:** no Play Store / App Store distribution required, no SaaS
SDKs, no third-party telemetry. Phone ↔ home server over **Tailscale** only.

Two layers ship together:

| Layer | Role |
| --- | --- |
| **PWA** (`frontend/static`) | Install dashboard to Android home screen via Chrome; optional browser GPS node |
| **Capacitor APK** (`mobile/` + `capacitor.config.ts`) | Native WebView + background-friendly location permissions |

---

## 1. Progressive Web App (Android Chrome)

1. Bring up the stack on a host joined to your Tailscale tailnet:
   ```bash
   cp .env.example .env
   docker compose up -d --build
   ```
2. On the phone, install **Tailscale** and join the same tailnet.
3. Open `http://<tailscale-ip-or-magicdns>/` (frontend on port 80).
4. Chrome → **Install app** / **Add to Home screen**.
5. Optional: open the side panel → set **Callsign** → **Arm Node** to POST
   GPS every 60s to `/api/telemetry` (IndexedDB queues while offline).

Files:

- `frontend/static/manifest.json`
- `frontend/static/sw.js`
- `frontend/static/js/telemetry-node.js`

---

## 2. Capacitor Android APK (sideload)

### Prerequisites

- Node.js 20+
- Android Studio / SDK / JDK 17
- Phone with **Install unknown apps** allowed for your file manager

### Build

```bash
npm install
npm run build
npx cap add android          # first time only
# Merge permissions from mobile/android-template/ into android/app/src/main/
cp mobile/android-template/network_security_config.xml \
   android/app/src/main/res/xml/network_security_config.xml
# Merge uses-permission entries from mobile/android-template/AndroidManifest.xml
npm run cap:sync
npx cap open android
# In Android Studio: Build → Build APK(s)  (or)
npm run android:build
```

Debug APK path (Gradle):

`android/app/build/outputs/apk/debug/app-debug.apk`

Copy the APK over Tailscale/SCP/USB. No Google account required.

### Runtime config

1. Ensure Tailscale is connected on the phone.
2. Open Overwatch → enter MagicDNS URL (e.g. `https://overwatch.tailnet.ts.net`
   or `http://100.x.y.z`).
3. Optional: paste the same `TELEMETRY_ENCRYPTION_KEY` base64 from `.env`.
4. **Arm Telemetry** — posts every 60 seconds.

### Permissions to grant on device

- Location → **Allow all the time** (background)
- Notifications (Android 13+) if using a foreground service later
- Disable battery optimization for Overwatch on aggressive OEMs (Samsung/Xiaomi)

---

## 3. iOS pathway (Safari PWA or Capacitor sideload)

Apple restricts background geolocation for PWAs and unsigned apps. Choose one:

### A. Safari “Add to Home Screen” (simplest)

1. Join the iPhone to Tailscale.
2. Safari → your Overwatch MagicDNS URL.
3. Share → **Add to Home Screen**.
4. Arm the telemetry node while the PWA is **in the foreground**.

**Limitation:** iOS suspends JavaScript timers within ~30s of backgrounding.
Expect sparse fixes unless the PWA stays open. Use this mode for viewing the
dashboard; rely on a dedicated tracker (OwnTracks iOS / Traccar Client) for
hardcore background tracks if needed — both can still POST into your mesh.

### B. Capacitor + Xcode (Apple Developer account or AltStore)

```bash
npm install
npm run build
npx cap add ios
npm run cap:sync
npx cap open ios
```

In Xcode:

1. Signing & Capabilities → your Team (paid) **or** free provisioning /
   AltStore / Sideloadly for 7-day certs.
2. Add capabilities: **Background Modes** → Location updates.
3. `Info.plist` keys (Capacitor Geolocation usually injects these):
   - `NSLocationWhenInUseUsageDescription`
   - `NSLocationAlwaysAndWhenInUseUsageDescription`
   - `UIBackgroundModes` → `location`
4. Product → Run on a physical device (Simulator GPS is fine for testing).

**Still limited:** continuous background GPS on iOS requires the native
location manager + blue status bar; pure WebView timers remain throttled.
The Capacitor `@capacitor/geolocation` plugin helps while the app is active;
for OwnTracks-parity always-on tracking, prefer a native location foreground
service on Android and OwnTracks/Traccar Client on iOS pointing at the same
`/api/telemetry` (or Traccar protocol bridge).

### C. AltStore / Sideloadly (no App Store)

1. Build an IPA via Xcode Archive (Ad Hoc / Development).
2. Install with [AltStore](https://altstore.io) or Sideloadly over USB on your LAN.
3. Refresh signing every 7 days on free Apple IDs.

---

## 4. Telemetry contract

`POST /api/telemetry`

Plaintext:

```json
{
  "ts": "2026-10-09T15:00:00.000Z",
  "deviceId": "uuid",
  "callsign": "ALPHA-1",
  "lat": 40.5,
  "lon": -84.5,
  "alt": 250.0,
  "accuracy": 8.0,
  "heading": 180.0,
  "speed": 0.0,
  "battery": 87,
  "charging": false,
  "source": "capacitor"
}
```

Encrypted envelope (`TELEMETRY_ENCRYPTION_KEY` set on both ends):

```json
{
  "v": "sovereign-aes-gcm-v1",
  "deviceId": "uuid",
  "callsign": "ALPHA-1",
  "iv": "<base64 12 bytes>",
  "ciphertext": "<base64>",
  "ts": "2026-10-09T15:00:00.000Z"
}
```

Batch replay (IndexedDB flush): `TelemetryPoint[]`.

Inspect tracks: `GET /api/telemetry/latest?limit=50`.

---

## 5. Why this respects Sovereign D

- Binaries and PWA assets are **yours** — sideload / Add to Home Screen.
- No Play Billing, no ATT, no store analytics SDKs.
- Reachability is **Tailscale mesh**, not a public router port.
- Optional AES-GCM is defense-in-depth on top of WireGuard.
