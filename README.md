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
├── scripts/                 # Geofabrik download, PMTiles build, monthly refresh
├── nav/                     # TileServer GL config (no tile data)
├── docs/MOBILE.md           # Android APK + iOS sideload / PWA guide
├── docs/NAVIGATION.md       # Valhalla, Nominatim, tiles, disk and time
└── docs/OWNTRACKS.md        # iPhone HTTP background tracking
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
  and `POST /api/route`, and on `GET /api/telemetry/latest`, `/api/pois`,
  `/api/cameras`, `/api/cameras/{id}/snap`, `/api/geocode`, `/api/adsb`, and
  `/api/scanner`.
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

## Navigation, cameras, and OwnTracks

Map tiles come from the optional `nav` profile (TileServer GL reading a local PMTiles file). The dashboard does not call public OSM tile hosts. Search is Nominatim. Routing is Valhalla for auto, bicycle, and pedestrian, with a line, a step list, browser GPS follow, Web Speech prompts, and a reroute when Follow is on and the fix leaves the line.

```bash
./scripts/nav-download.sh
./scripts/nav-build.sh
docker compose --profile nav up -d
```

Plan on **60 GB free disk** and **16 GB RAM** for the first build. Download is about 15–60 minutes, the PMTiles build about 20–60 minutes, Valhalla's first start about 45–120 minutes, and the Nominatim import about 2–8 hours. Day-to-day the nav containers want about 4–8 GB. Details, the monthly cron, and the systemd timer are in [docs/NAVIGATION.md](docs/NAVIGATION.md).

Ohio traffic cameras use `OHGO_API_KEY` when set. The catalog is cached 120 seconds. Snapshots are proxied at `/api/cameras/{id}/snap` (same API token) so the page does not hotlink the upstream JPEG. With no key the panel says the key is unset and the API returns an empty list.

`POST /api/tracking/owntracks` takes `OWNTRACKS_TOKEN` as `Authorization: Bearer` or as the HTTP Basic password. The OwnTracks `tid` is the callsign in the telemetry table. iPhone HTTP setup is in [docs/OWNTRACKS.md](docs/OWNTRACKS.md).

Leave `DUMP1090_URL` empty if you have no dump1090/readsb. The ADS-B panel then shows **no receiver configured** and `/api/adsb` returns 200. A URL that does not answer returns `configured: true` and `status: offline`, still 200.

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
- Navigation data stays on disk under `nav-data/` (gitignored). Images for Valhalla, Nominatim, and TileServer GL are pinned. Their ports bind to `127.0.0.1`.

## Redeploy

Existing token auth, pinned core images, and localhost port bindings stay in place.

1. Pull this revision. Keep `ALERT_TOKEN` and `TELEMETRY_ENCRYPTION_KEY`. Add `OHGO_API_KEY` and `OWNTRACKS_TOKEN` only if you want cameras or iPhone ingest. Set `DUMP1090_URL` if you have a receiver; an empty value is quiet instead of an error.
2. Rebuild the core stack. Host ports stay `127.0.0.1:3012` (dashboard) and `127.0.0.1:8001` (API).

   ```bash
   docker compose up -d --build
   ```

3. For maps and routing, run `./scripts/nav-download.sh`, then `./scripts/nav-build.sh`, then `docker compose --profile nav up -d`. The first Nominatim import and Valhalla tile build run inside those containers and can take hours. See [docs/NAVIGATION.md](docs/NAVIGATION.md) for disk and RAM.
4. Reload the dashboard, enter the API token, and hard-refresh so the service worker picks up the new shell. Follow and Speak need a user gesture (the Follow button).
5. Point an iPhone OwnTracks HTTP URL at `https://owntracks:TOKEN@YOUR_DASHBOARD_HOST/api/tracking/owntracks`. Steps are in [docs/OWNTRACKS.md](docs/OWNTRACKS.md).
6. Optional monthly refresh: install `deploy/overwatch-nav-refresh.cron` or the systemd timer after editing the `/opt/owa` path.
