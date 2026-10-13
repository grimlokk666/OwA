#!/bin/sh
# Monthly refresh: new Geofabrik extracts, a new PMTiles file, and a Valhalla rebuild.
# Nominatim is reimported only when NAV_REIMPORT_NOMINATIM=1 (the sample cron sets this).
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA=${NAV_DATA_DIR:-$ROOT/nav-data}
cd "$ROOT"

dry=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$DATA"
lock="$DATA/.refresh.lock"
if [ "$dry" -eq 0 ]; then
  exec 9>"$lock"
  if ! flock -n 9; then
    echo "A nav refresh is already running."
    exit 0
  fi
fi

if [ "$dry" -eq 1 ]; then
  "$ROOT/scripts/nav-download.sh" --dry-run --force
  "$ROOT/scripts/nav-build.sh" --dry-run
  echo "Would drop Valhalla tile archives and restart the nav profile."
  if [ "${NAV_REIMPORT_NOMINATIM:-0}" = 1 ]; then
    echo "Would move nominatim-pg aside and reimport."
  fi
  exit 0
fi

"$ROOT/scripts/nav-download.sh" --force
"$ROOT/scripts/nav-build.sh"

# Force the scripted Valhalla image to rebuild from the replaced PBF.
rm -f \
  "$DATA/valhalla/valhalla_tiles.tar" \
  "$DATA/valhalla/.file_hashes.txt"
rm -rf "$DATA/valhalla/valhalla_tiles"

if [ "${NAV_REIMPORT_NOMINATIM:-0}" = 1 ]; then
  docker compose --profile nav stop overwatch-nominatim || true
  rm -rf "$DATA/nominatim-pg.prev"
  if [ -d "$DATA/nominatim-pg" ]; then
    mv "$DATA/nominatim-pg" "$DATA/nominatim-pg.prev"
  fi
  mkdir -p "$DATA/nominatim-pg"
fi

if [ "${NAV_RESTART:-1}" = 1 ]; then
  docker compose --profile nav up -d
fi

echo "Refresh submitted. Valhalla and, if requested, Nominatim rebuild on startup."
echo "The previous Nominatim database, if any, is in $DATA/nominatim-pg.prev."
