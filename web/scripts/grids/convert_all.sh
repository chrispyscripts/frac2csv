#!/usr/bin/env bash
# Shapefiles -> newline-delimited GeoJSON, one file per survey level.
#
#   convert_all.sh <unzipped-shapefile-dir> <out-dir>
#
# Source: _BC-NE-DLS-NTS-Nad83-ESPG-4269.zip, EPSG:4269 (NAD83 geographic), so
# the coordinates are already lon/lat degrees and nothing reprojects.  There is
# no GDAL/ogr2ogr/geopandas on this machine and none is needed: shp2ndjson.py is
# a stdlib+numpy reader that streams, which matters because NTSQTR is 1.6M
# polygons / ~420 MB of JSON and nothing may hold it all at once.
#
# Budget ~20 minutes, most of it nts_qtr.
set -euo pipefail
SRC="${1:?usage: convert_all.sh <unzipped-shapefile-dir> <out-dir>}"
OUT="${2:?usage: convert_all.sh <unzipped-shapefile-dir> <out-dir>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"

N="$SRC/_BC_NE-NTS-Nad83-ESPG-4269/_province-BC-NE_"
D="$SRC/_BC-NE-DLS-Nad83-ESPG-4269/_province-BC-NE_"
S="-Nad83-ESPG-4269.shp"

run () { echo "--- $2"; python3 "$HERE/shp2ndjson.py" "$1" "$OUT/$2.geojsonl" "$2"; }
run "${N}NTSPRI-Nad83-ESPG4269.shp" nts_pri
run "${N}NTSLTR$S"  nts_ltr
run "${N}NTSSIX$S"  nts_six
run "${N}NTSBLK$S"  nts_blk
run "${D}DLSTWP$S"  dls_twp
run "${D}DLSSEC$S"  dls_sec
run "${D}DLSLSD$S"  dls_lsd
run "${N}NTSUNIT$S" nts_unit
run "${N}NTSQTR$S"  nts_qtr

# The shapefiles number only the CORNER cells of each block/section, so fill in
# the rest before tiling -- see label_infill.py.
python3 "$HERE/label_infill.py" "$OUT"
ls -la "$OUT"
