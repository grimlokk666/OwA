# iPhone background tracking with OwnTracks

Safari drops GPS when the screen locks. OwnTracks, in HTTP mode, is the background tracker for an iPhone. Posts land in the same `telemetry` table as the dashboard node. The device tracker id (`tid`) is stored as the callsign.

The ingest is `POST /api/tracking/owntracks`. It does not use the AES telemetry envelope. OwnTracks cannot build that envelope. Protect the hop with HTTPS (Tailscale Serve or another proxy in front of `127.0.0.1:3012`) and with `OWNTRACKS_TOKEN`.

Generate a URL-safe token so it can sit in the iPhone URL:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in `.env` as `OWNTRACKS_TOKEN` and recreate the backend. Do not commit the token. Do not put a tailnet hostname in the repo; use the host you already open for the dashboard.

## What the server accepts

- `Authorization: Bearer <OWNTRACKS_TOKEN>`
- HTTP Basic, where the password is `OWNTRACKS_TOKEN` and the username can be anything

A correct post returns `200` and `[]`. OwnTracks treats a JSON array as optional friend locations. An empty array means "stored, nothing to send back." An empty body is ignored. Waypoints and encrypted blobs are ignored. A location with `lat`/`lon` is stored. `_type: location` is the normal case.

`X-Limit-D` (OwnTracks device name) becomes `deviceId` when it is present. Otherwise the id is `owntracks-<tid>`.

## iPhone setup

1. Install OwnTracks from the App Store on the phone you want to track.
2. iOS Settings → OwnTracks → Location → **Always**, and allow precise location.
3. In the app, set the connection mode to **HTTP**.
4. URL:

   ```text
   https://owntracks:TOKEN@YOUR_DASHBOARD_HOST/api/tracking/owntracks
   ```

   `owntracks` is only the Basic username. `TOKEN` is `OWNTRACKS_TOKEN`. `YOUR_DASHBOARD_HOST` is the HTTPS name you already use for the dashboard (the nginx `/api/` proxy). From the host itself you can test the API port instead: `http://127.0.0.1:8001/api/tracking/owntracks`.
5. Identification:
   - **Device ID**: a short name, sent as `X-Limit-D` (this becomes `deviceId`).
   - **Tracker ID**: two characters, for example `K7`. This is the callsign on the map.
6. Turn on background / significant-change tracking in the app. OwnTracks posts when iOS delivers a location. It does not hold its own always-on socket. If the server is unreachable, the app queues and retries.
7. Publish once while the phone is unlocked. The dashboard map should show the callsign after the next telemetry refresh (about 20 seconds). The point is plaintext in SQLite, same as a decrypted fix, with `source` `owntracks`.

## Check from the server

```bash
curl -sS -X POST http://127.0.0.1:8001/api/tracking/owntracks \
  -H "Authorization: Bearer $OWNTRACKS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"_type":"location","tid":"K7","lat":39.96,"lon":-82.99,"tst":1760000000,"batt":80}'
```

Expect `[]`. Then, with the API token:

```bash
curl -sS http://127.0.0.1:8001/api/telemetry/latest \
  -H "X-Overwatch-Token: $ALERT_TOKEN"
```

The new row has `"callsign": "K7"` and `"source": "owntracks"`.

If the token is missing or wrong, the response is 401 and nothing is stored. There is no open ingest.
