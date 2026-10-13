# Sovereign Overwatch

Local-first mission control: tactical map, traffic cams, ADS-B, scanner feeds,
and OwnTracks-style phone telemetry — **zero SaaS**, **zero app-store tracking**,
reachable only over your **Tailscale** mesh.

```
sovereign-overwatch/
├── docker-compose.yml
├── .env.example
├── capacitor.config.ts      # Native Android/iOS wrapper
├── package.json             # Capacitor + mobile shell build
├── backend/                 # FastAPI core + /api/telemetry
├── frontend/                # Nginx + PWA dashboard
├── mobile/                  # Capacitor companion (WebView + GPS node)
└── docs/MOBILE.md           # Android APK + iOS sideload / PWA guide
```

## Quick start (server)

```bash
cp .env.example .env
# Set ALERT_TOKEN and TELEMETRY_ENCRYPTION_KEY before starting.
docker compose up -d --build
```

Published ports bind to `127.0.0.1` so the stack does not take host port 80.
Put a reverse proxy or Tailscale Serve in front of them if other machines
need access. Defaults are in `.env.example`.

| Service | URL |
| --- | --- |
| Dashboard (PWA) | `http://127.0.0.1:3012/` |
| API | `http://127.0.0.1:8001/` |
| Health | `http://127.0.0.1:8001/health` |

## Authentication

- `TELEMETRY_REQUIRE_KEY` defaults to true. `POST /api/telemetry` accepts only
  a `sovereign-aes-gcm-v1` envelope. Plaintext is rejected. If the server has
  no key, the envelope is rejected and nothing is stored.
- `ALERT_TOKEN` is required. Send it as `X-Overwatch-Token` on `POST /api/alert`
  and on `GET /api/telemetry/latest`, `/api/pois`, `/api/cameras`, `/api/adsb`,
  and `/api/scanner`.
- The dashboard has token and key fields. A one-time visit to
  `https://<dashboard>/#key=<base64>` stores the telemetry key and strips the
  hash. The mobile shell has the same two fields and sends the token header.
- Clients do not fall back to plaintext when encryption fails.
- `CORS_ORIGINS` must list the exact dashboard origin (the example is
  `http://127.0.0.1:3012`). Do not use `*`.

SQLite lives on the named volume `overwatch-data` (`/app/data/overwatch.db`),
with WAL, a busy timeout, and `PRAGMA user_version` migrations. A daily task
drops telemetry older than `TELEMETRY_RETENTION_DAYS` (365), drops POI cache
rows older than `POI_CACHE_DAYS` (30), and writes `./backups/overwatch-YYYYMMDD.db`,
keeping `BACKUP_KEEP` (14) files.

To move an older bind-mounted database into the named volume:

```bash
docker compose up -d overwatch-backend
docker compose cp backend/data/overwatch.db overwatch-backend:/app/data/overwatch.db
docker compose restart overwatch-backend
```

## Mobile companion

1. **PWA (Android Chrome):** open the dashboard → Install / Add to Home Screen.
   Arm the telemetry node in the side panel.
2. **APK (Capacitor):** see [docs/MOBILE.md](docs/MOBILE.md) for permissions,
   `AndroidManifest` merge, and sideload steps.
3. **iOS:** Safari Add to Home Screen for viewing; Xcode/AltStore for a native
   shell — background GPS limits are documented in `docs/MOBILE.md`.

Telemetry contract: `POST /api/telemetry` (AES-GCM envelope). See [docs/MOBILE.md](docs/MOBILE.md).

## Sovereign D

- No Play Store / App Store gatekeepers required (PWA or sideloaded APK/IPA).
- No third-party analytics, crash reporters, or map SaaS SDKs.
- `TELEMETRY_ENCRYPTION_KEY` is required for ingest. `ALERT_TOKEN` guards alerts and reads.
