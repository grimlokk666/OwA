#!/bin/sh
# Build a regional PMTiles archive from the merged Geofabrik extract.
# Valhalla and Nominatim build their own data the first time the nav profile starts.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA=${NAV_DATA_DIR:-$ROOT/nav-data}
PBF=$DATA/pbf/region.osm.pbf
PLANETILER_IMAGE=${PLANETILER_IMAGE:-ghcr.io/onthegomap/planetiler:0.10.2}
PLANETILER_XMX=${PLANETILER_XMX:-6g}

dry=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -s "$PBF" ] && [ "$dry" -eq 0 ]; then
  echo "Missing $PBF — running download first."
  "$ROOT/scripts/nav-download.sh"
fi

mkdir -p "$DATA/tiles"
chmod 0777 "$DATA/tiles" 2>/dev/null || true

echo "IMAGE $PLANETILER_IMAGE"
echo "HEAP $PLANETILER_XMX"
echo "OUT $DATA/tiles/region.pmtiles"
if [ "$dry" -eq 1 ]; then
  exit 0
fi

# --download fetches Natural Earth and water polygons. The OSM file is local.
docker run --rm \
  -e "JAVA_TOOL_OPTIONS=-Xmx${PLANETILER_XMX}" \
  -v "$DATA:/data" \
  "$PLANETILER_IMAGE" \
  --osm-path=/data/pbf/region.osm.pbf \
  --output=/data/tiles/region.pmtiles \
  --download \
  --force

echo "PMTiles ready. Start routing and search with:"
echo "  docker compose --profile nav up -d"
