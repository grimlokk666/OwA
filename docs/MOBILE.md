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
3. Open the dashboard. Compose publishes it on `http://127.0.0.1:3012/`
   (API on `http://127.0.0.1:8001/`). From a phone, point Tailscale Serve or
   another HTTPS proxy at those localhost ports — the Android app allows HTTPS
   only.
4. Chrome → **Install app** / **Add to Home screen**.
5. In the side panel set **Callsign**, **API token** (`ALERT_TOKEN`, sent as
   `X-Overwatch-Token`), and **AES key** (or open the dashboard once as
   `/#key=<base64>`; the hash is stored and then removed). **Arm Node** posts
   an encrypted fix every 60s. IndexedDB queues while offline and encrypts
   again on flush. Encryption failure does not send plaintext.

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
# HTTPS only — the template sets cleartextTrafficPermitted=false
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
2. Open Overwatch → enter the HTTPS base URL of the dashboard.
3. Paste the same `TELEMETRY_ENCRYPTION_KEY` base64 from `.env`, and the
   `ALERT_TOKEN` (sent as `X-Overwatch-Token` on telemetry posts).
4. **Arm Telemetry** — posts an encrypted envelope every 60 seconds.
   A missing or bad key is not sent as plaintext.

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

`POST /api/telemetry` requires a `sovereign-aes-gcm-v1` envelope when
`TELEMETRY_REQUIRE_KEY` is true (the default). Plaintext JSON is rejected.
If the server has no `TELEMETRY_ENCRYPTION_KEY`, the envelope is rejected
instead of being stored at latitude/longitude `0,0`.

The ciphertext is `JSON.stringify` of the point:

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

Envelope:

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

Offline replay posts one envelope at a time (the queue stores the point
locally and encrypts it on flush). A plaintext batch is only accepted when
`TELEMETRY_REQUIRE_KEY=false`, and it is capped at 500 points.

`GET /api/telemetry/latest`, `/api/pois`, `/api/cameras`, `/api/geocode`,
`/api/adsb`, and `/api/scanner`, plus `POST /api/route`, require the header
`X-Overwatch-Token: <ALERT_TOKEN>`.
`POST /api/alert` uses the same header. `/health` stays open for the
container healthcheck.

## 5. Android release signing

The debug APK from Android Studio is enough for a personal sideload. A release
APK needs a keystore you control. **Back up the keystore and both passwords
offline.** Losing them means you cannot install an update over the existing
app; you would have to uninstall and lose the app's local data. This repository
is public: never commit `*.jks`, `*.keystore`, or `keystore.properties`.

Generate a keystore (run this outside the repo, or in a gitignored path):

```bash
keytool -genkeypair -v \
  -keystore overwatch-release.keystore \
  -alias overwatch \
  -keyalg RSA -keysize 2048 -validity 10000
```

Wire Gradle from environment variables or from `android/keystore.properties`
(copy `mobile/android-template/keystore.properties.example`). The signing
block to merge is `mobile/android-template/release-signing.gradle`.

```bash
export OVERWATCH_KEYSTORE_PATH="$HOME/keys/overwatch-release.keystore"
export OVERWATCH_KEYSTORE_PASSWORD="..."
export OVERWATCH_KEY_ALIAS="overwatch"
export OVERWATCH_KEY_PASSWORD="..."
cd android && ./gradlew assembleRelease
```

`keystore.properties` (gitignored), same keys as the example file:

```
storeFile=/absolute/or/project-relative/overwatch-release.keystore
storePassword=...
keyAlias=overwatch
keyPassword=...
```

Environment variables win over the properties file when both are set.
Inside `android/app/build.gradle`, add `signingConfig signingConfigs.release`
to `buildTypes.release` after pasting the snippet.

---

## 6. iPhone background tracking (OwnTracks)

Safari and a home-screen PWA cannot hold a reliable GPS watch in the background.
For an iPhone that should keep reporting while the screen is off, use the
OwnTracks app in HTTP mode. Setup, the URL, and Basic versus Bearer auth are
in [OWNTRACKS.md](OWNTRACKS.md).

The dashboard's Follow button is separate: it uses the browser Geolocation API
and the Web Speech API for turn-by-turn while the page is open.

---

## 7. Why this respects Sovereign D

- Binaries and PWA assets are **yours** — sideload / Add to Home Screen.
- No Play Billing, no ATT, no store analytics SDKs.
- Reachability is **Tailscale mesh**, not a public router port.
- AES-GCM envelopes and the `X-Overwatch-Token` header stay on your mesh.
  The Android app allows HTTPS only.
