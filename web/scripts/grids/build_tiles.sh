#!/usr/bin/env bash
# Newline-delimited GeoJSON -> one pmtiles archive per survey level.
#
#   build_tiles.sh <ndjson-dir> [out-dir]
#
# Each level is tiled only over the zooms where it is legible, and each layer's
# display minzoom in grids.js matches the -Z here.  A survey grid has to be
# COMPLETE wherever it is drawn, so there are deliberately no --drop-densest or
# other dropping flags: a gap in a survey grid is a lie.  The zoom bands are what
# keep tile density sane instead.  MapLibre overzooms past -z, so a level stays
# drawn when you zoom past its maximum.
#
# The three finest levels are single-zoom on purpose: each extra zoom level is
# another full copy of the layer, and overzoomed rectangles are indistinguishable
# from natively-tiled ones.  nts_qtr is 1.6M polygons and is the whole size
# budget -- tiled z12-15 it comes to 333 MB, which GitHub refuses outright
# (100 MB per file); z14 alone is 77 MB.  nts_unit is 85 MB over z12-14 and
# 14 MB at z12 alone.  Lowering -d below 12 saves nothing measurable, so
# coordinate precision is kept.  Whole set: 104 MB.
set -euo pipefail
IN="${1:?usage: build_tiles.sh <ndjson-dir> [out-dir]}"
OUT="${2:-$(cd "$(dirname "$0")/../../public/data/grids" && pwd)}"
mkdir -p "$OUT"

tile () { # level minzoom maxzoom
  echo "--- $1  Z$2-z$3"
  tippecanoe -o "$OUT/$1.pmtiles" -l "$1" -n "$1" -Z"$2" -z"$3" \
    --no-tile-size-limit --no-feature-limit --detect-shared-borders \
    --simplification=2 --force "$IN/$1.geojsonl"
}
tile nts_pri   4  8
tile nts_ltr   5  9
tile nts_six   6  10
tile nts_blk   8  12
tile nts_unit  12 12
tile nts_qtr   14 14
tile dls_twp   6  10
tile dls_sec   9  13
tile dls_lsd   13 13

ls -la "$OUT"
# Every archive must start with the PMTiles magic. A .pmtiles that begins
# "SQLite f" is an MBTiles file under the wrong extension and will fail in the
# browser with "Wrong magic number for PMTiles archive".
for f in "$OUT"/*.pmtiles; do
  head -c 7 "$f" | grep -q PMTiles || { echo "NOT A PMTILES ARCHIVE: $f" >&2; exit 1; }
done
echo "all archives carry the PMTiles magic"
