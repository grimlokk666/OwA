# Self-hosted navigation (Ohio and neighbors)

Optional compose profile `nav`. The dashboard map reads tiles from this profile.
It does not request public OpenStreetMap tile servers.

Coverage is the Geofabrik extracts for:

- Ohio
- Indiana
- Michigan
- Kentucky
- West Virginia
- Pennsylvania

| Piece | Image | What it does |
| --- | --- | --- |
| Routing | `ghcr.io/valhalla/valhalla-scripted:3.9.1` | auto, bicycle, and pedestrian turn-by-turn |
| Geocoding | `mediagis/nominatim:5.3.2` | address search (`IMPORT_STYLE=address`) |
| Tiles | `maptiler/tileserver-gl:v5.6.0` | raster PNG from a local PMTiles archive |

Published ports bind to `127.0.0.1` only:

| Service | Host URL |
| --- | --- |
| Valhalla | `http://127.0.0.1:8002/` |
| Nominatim | `http://127.0.0.1:8089/` |
| TileServer GL | `http://127.0.0.1:8090/` |

The dashboard proxies tiles at `/tiles/` and the API proxies search and routing:

- `GET /api/geocode?q=` requires `X-Overwatch-Token`
- `POST /api/route` requires `X-Overwatch-Token`

Both return 503 until the matching container is up. No tailnet hostname is baked into the compose file.

## Disk, RAM, and first-build time

These are planning numbers for the six extracts together, not a benchmark of your machine.

| Item | Size |
| --- | --- |
| Geofabrik PBF files | about 1.5–2.2 GB |
| Merged `region.osm.pbf` | about the same again while both copies exist |
| Valhalla graph | about 5–10 GB |
| PMTiles basemap | about 1–3 GB |
| Nominatim (address style) | about 20–40 GB |
| Previous Nominatim dir kept by a monthly reimport | another 20–40 GB until you delete `nav-data/nominatim-pg.prev` |

Leave **60 GB free** before the first build. 40 GB is tight once Nominatim and Valhalla are both on disk.

| Phase | RAM | Time |
| --- | --- | --- |
| Download | negligible | 15–60 minutes, depending on the link to Geofabrik |
| Planetiler PMTiles (`PLANETILER_XMX`, default 6g) | 8 GB comfortable, 12 GB safer | 20–60 minutes |
| Valhalla first start (2 threads) | 4–8 GB | 45–120 minutes |
| Nominatim first import (4 threads, 1 GB shared buffers, 2 GB maintenance memory) | **16 GB recommended**. Do not run this at the same time as Planetiler | 2–8 hours |

After the import, the three nav containers together want about **4–8 GB** resident, on top of the existing backend and frontend. A host with 16 GB can build if you run one heavy step at a time. A host with 32 GB can raise `NOMINATIM_THREADS` and `PLANETILER_XMX`.

Nominatim's Postgres port is not published. The image keeps its own database password inside the container.

## First build

```bash
cp .env.example .env
# ALERT_TOKEN and TELEMETRY_ENCRYPTION_KEY are still required.
./scripts/nav-download.sh
./scripts/nav-build.sh
docker compose --profile nav up -d
```

`nav-download.sh` fetches the six PBFs and merges them with osmium inside `debian:bookworm-20251229-slim`. The merge is copied to `nav-data/valhalla/region.osm.pbf` (Valhalla) and left at `nav-data/pbf/region.osm.pbf` (Nominatim).

`nav-build.sh` runs `ghcr.io/onthegomap/planetiler:0.10.2` and writes `nav-data/tiles/region.pmtiles`. Planetiler's `--download` fetches Natural Earth and water polygons. It does not download a second copy of the planet; the OSM input is the merged extract.

Then start the profile. Valhalla builds its graph on first start. Nominatim imports on first start because `nav-data/nominatim-pg` is empty. TileServer GL serves `/styles/basic-preview/{z}/{x}/{y}.png` from the PMTiles file. The frontend nginx proxies that under `/tiles/`.

Open `http://127.0.0.1:3012/`, enter the API token, and search. Tap the map to pin a destination. Follow uses the browser GPS. Speak uses the Web Speech API (`speechSynthesis`). Some browsers synthesize speech on the device; others send the phrase to the browser vendor's voice service. Reroute runs when Follow is on and the fix stays more than about 60 m off the line.

`nav-data/` is gitignored. Do not commit extracts, tiles, or the Nominatim data directory.

## Monthly refresh

```bash
# routing tiles + PMTiles, keep the current Nominatim database
./scripts/nav-refresh.sh

# also reimport Nominatim (the sample cron and systemd timer do this)
NAV_REIMPORT_NOMINATIM=1 ./scripts/nav-refresh.sh
```

The cron example is `deploy/overwatch-nav-refresh.cron` (03:15 UTC on the 1st). The systemd pair is `deploy/overwatch-nav-refresh.service` and `deploy/overwatch-nav-refresh.timer`. Both assume the checkout lives at `/opt/owa`. Change that path before installing. A `flock` on `nav-data/.refresh.lock` skips a second run if one is still going.

A Nominatim reimport moves the old database to `nav-data/nominatim-pg.prev`. Delete that directory after the new import is healthy (`/status` on port 8089) or the next refresh will replace it and the disk spike is only one extra copy.

## If a build is killed

Valhalla: delete `nav-data/valhalla/valhalla_tiles.tar` and `nav-data/valhalla/valhalla_tiles`, leave `region.osm.pbf`, and restart the container.

Nominatim: stop the container, remove `nav-data/nominatim-pg`, start it again. The import starts over.

Planetiler: rerun `./scripts/nav-build.sh`. `--force` replaces `region.pmtiles`.
