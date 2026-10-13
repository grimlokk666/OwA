#!/bin/sh
# Download Geofabrik extracts for Ohio and its neighbors, then merge them.
# Pins: debian:bookworm-20251229-slim (osmium-tool is installed inside that image).
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA=${NAV_DATA_DIR:-$ROOT/nav-data}
PBF_DIR=$DATA/pbf
STATES=${NAV_STATES:-ohio indiana michigan kentucky west-virginia pennsylvania}
OSMIUM_IMAGE=${OSMIUM_IMAGE:-debian:bookworm-20251229-slim}
BASE=https://download.geofabrik.de/north-america/us

dry=0
force=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    --force) force=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

echo "States: $STATES"
echo "Destination: $PBF_DIR"
mkdir -p "$PBF_DIR" "$DATA/valhalla" "$DATA/tiles"
chmod 0777 "$DATA/valhalla" "$DATA/tiles" 2>/dev/null || true

files=""
for state in $STATES; do
  url="$BASE/${state}-latest.osm.pbf"
  dest="$PBF_DIR/${state}-latest.osm.pbf"
  echo "GET $url"
  files="$files /data/${state}-latest.osm.pbf"
  if [ "$dry" -eq 1 ]; then
    continue
  fi
  if [ -s "$dest" ] && [ "$force" -eq 0 ]; then
    echo "Keeping existing $dest (pass --force to replace)"
    continue
  fi
  tmp="$dest.partial"
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$url"
  mv "$tmp" "$dest"
done

echo "MERGE osmium -> $PBF_DIR/region.osm.pbf"
echo "IMAGE $OSMIUM_IMAGE"
if [ "$dry" -eq 1 ]; then
  exit 0
fi

docker run --rm \
  -v "$PBF_DIR:/data" \
  "$OSMIUM_IMAGE" \
  bash -lc "apt-get update && apt-get install -y --no-install-recommends osmium-tool ca-certificates && osmium merge --overwrite -o /data/region.osm.pbf $files"

cp -f "$PBF_DIR/region.osm.pbf" "$DATA/valhalla/region.osm.pbf"
echo "Merged extract is in $PBF_DIR/region.osm.pbf and $DATA/valhalla/region.osm.pbf"
