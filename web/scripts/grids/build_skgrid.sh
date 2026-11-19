#!/usr/bin/env bash
# Saskatchewan survey grid (ISC SaskGrid 2015) -> one pmtiles archive per level,
# written OUTSIDE this repository.
#
#   build_skgrid.sh <saskgrid-dir> [out-dir [level ...]]
#
# <saskgrid-dir> holds the four SaskGrid_2015_<LEVEL>/ folders as ISC ships them;
# out-dir defaults to ~/dev/fracview-skgrid; naming levels (sk_twp sk_sec sk_qtr
# sk_lsd) rebuilds just those.  Budget ~15 minutes for all four, most of it
# sk_lsd (4M polygons); peak extra disk is tippecanoe's temp files, well under
# 1 GB.  Sizes: sk_twp 2 MB, sk_sec 64 MB, sk_qtr 40 MB, sk_lsd 161 MB.
#
# LICENCE: the SaskGrid end-user licence does not allow the data to be published
# or embedded in an application without ISC's written permission, and this repo
# is public and deploys to the live site.  So the archives never go into
# web/public: this script refuses an out-dir inside the repo, the local server
# mounts the folder (scripts/serve.py --mount /data/skgrid=<out-dir>), and
# grids.js draws the SK levels only where they load.  Wherever the grid is drawn
# the map carries ISC's source notice (grids.js).
#
# Each level is piped from sk_grid.py straight into tippecanoe, so no
# intermediate GeoJSON is written (sk_lsd alone would be ~1 GB of it).  The zoom
# bands are the BC DLS ones (build_tiles.sh) but start where grids.js starts
# drawing each level (township z8, section z11): MapLibre fetches no tiles for a
# source below its layers' minzoom, and SaskGrid's 249k sections at z9-10 were
# 13.5 MB nobody would ever load.  The quarter section -- a level BC does not
# have -- is tiled at the single zoom between section and LSD.  As in BC, no
# dropping flags: a survey grid has to be complete wherever it is drawn, and
# MapLibre overzooms each level past its -z.
set -euo pipefail
SRC="${1:?usage: build_skgrid.sh <saskgrid-dir> [out-dir [level ...]]}"
OUT="${2:-$HOME/dev/fracview-skgrid}"
ONLY=" ${*:3} "
HERE="$(cd "$(dirname "$0")" && pwd -P)"
REPO="$(cd "$HERE/../../.." && pwd -P)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd -P)"
case "$OUT/" in
  "$REPO/"*) echo "refusing to write SaskGrid tiles inside the repo ($OUT)" >&2; exit 1 ;;
esac
TMP="$OUT/.tmp"
mkdir -p "$TMP"
trap 'rm -rf -- "${TMP:?}"' EXIT
NOTICE="Source: Information Services Corporation, SaskGrid Township Fabric Map."

shp () { # the NAD83 (EPSG:4269) shapefile of one level; ISC spells it two ways
  local f
  for f in "$SRC/SaskGrid_2015_$1/SaskGrid_2015_$1"-Nad83-*4269.shp; do
    [ -f "$f" ] && { echo "$f"; return; }
  done
  echo "no NAD83 shapefile for $1 under $SRC" >&2; exit 1
}

tile () { # level LEVELNAME minzoom maxzoom
  [ "$ONLY" = "  " ] || [[ "$ONLY" == *" $1 "* ]] || return 0
  local src; src="$(shp "$2")"
  echo "--- $1  Z$3-z$4  ($(basename "$src"))"
  python3 "$HERE/sk_grid.py" "$1" "$src" - |
    tippecanoe -o "$OUT/$1.pmtiles" -l "$1" -n "$1" -A "$NOTICE" -Z"$3" -z"$4" -t "$TMP" \
      --no-tile-size-limit --no-feature-limit --detect-shared-borders \
      --simplification=2 --force --quiet
}
tile sk_twp TOWNSHIP          8  10
tile sk_sec SECTION           11 13
tile sk_qtr QUARTERSECTION    12 12
tile sk_lsd LEGALSUBDIVISION  13 13

ls -la "$OUT"
# Every archive must start with the PMTiles magic (see build_tiles.sh).
for f in "$OUT"/sk_*.pmtiles; do
  head -c 7 "$f" | grep -q PMTiles || { echo "NOT A PMTILES ARCHIVE: $f" >&2; exit 1; }
done
echo "all archives carry the PMTiles magic"
