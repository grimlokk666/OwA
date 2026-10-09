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
docker compose up -d --build
```

| Service | URL |
| --- | --- |
| Dashboard (PWA) | `http://<host>/` |
| API | `http://<host>:8000/` |
| Health | `http://<host>:8000/health` |

Point Tailscale MagicDNS at the host. Phones join the same tailnet — **no
public router ports**.

## Mobile companion

1. **PWA (Android Chrome):** open the dashboard → Install / Add to Home Screen.
   Arm the telemetry node in the side panel.
2. **APK (Capacitor):** see [docs/MOBILE.md](docs/MOBILE.md) for permissions,
   `AndroidManifest` merge, and sideload steps.
3. **iOS:** Safari Add to Home Screen for viewing; Xcode/AltStore for a native
   shell — background GPS limits are documented in `docs/MOBILE.md`.

Telemetry contract: `POST /api/telemetry` (plaintext JSON or AES-GCM envelope).

## Sovereign D

- No Play Store / App Store gatekeepers required (PWA or sideloaded APK/IPA).
- No third-party analytics, crash reporters, or map SaaS SDKs.
- Optional `TELEMETRY_ENCRYPTION_KEY` for defense-in-depth over WireGuard.
