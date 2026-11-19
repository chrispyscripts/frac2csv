#!/usr/bin/env python3
"""Saskatchewan survey grid (ISC SaskGrid 2015) -> newline-delimited GeoJSON.

  sk_grid.py <level> <shapefile.shp> <out.geojsonl | ->

  level   sk_twp | sk_sec | sk_qtr | sk_lsd
  -       write to stdout, so build_skgrid.sh can pipe straight into tippecanoe
          and no intermediate GeoJSON ever touches the disk (sk_lsd alone would
          be ~1 GB of it)

LICENCE: SaskGrid is ISC data under an end-user licence that does not allow it
to be published or embedded in an application without ISC's written
permission.  Nothing this script writes may go into this repository or onto the
live site -- build_skgrid.sh writes it to a folder outside the repo, which only
the local server mounts (scripts/serve.py --mount /data/skgrid=...).  grids.js
draws the levels where they load and carries on without them where they don't.

The output has the same shape as shp2ndjson.py's BC DLS output, so grids.js
treats both alike:  `label` in the BC style for the same level (township
"TWP-RGEW<mer>", section number, LSD number) and cx/cy, the cell's centroid.
LSDs also carry `n`, the integer LSD number, as the BC LSDs do.  Quarter
sections are a level BC does not have; their label is the quarter (NE/NW/SE/SW).

Unlike BC-NE-DLS, SaskGrid numbers every cell, so nothing needs infilling.  The
source is EPSG:4269 (NAD83 lon/lat), so nothing reprojects.
"""
import json, re, sys

from shp2ndjson import dbf_reader, shp_reader, to_feature


def num(s):
    """Strip the zero padding off a survey number, keeping any letter suffix
    (a lone zero stays); a value that is not a number passes through."""
    m = re.match(r"0*(\d+)(\D*)$", s)
    return m.group(1) + m.group(2) if m else s


def twp_label(a):
    # Townships in the special surveys carry no meridian; their own
    # township-range-meridian code is the only name they have.
    if a["MER"] in ("1", "2", "3"):
        return "%s-%sW%s" % (num(a["TWP"]), num(a["RGE"]), a["MER"])
    return a["TRM"]


LEVELS = {
    "sk_twp": ({"TWP", "RGE", "MER", "TRM"}, twp_label),
    "sk_sec": ({"SECT"}, lambda a: num(a["SECT"])),
    "sk_qtr": ({"QSECT"}, lambda a: a["QSECT"]),
    "sk_lsd": ({"LSD"}, lambda a: num(a["LSD"])),
}


def convert(level, shp_path, out):
    fields, label = LEVELS[level]
    n = blank = 0
    for rings, attrs in zip(shp_reader(shp_path), dbf_reader(shp_path[:-4] + ".dbf", fields)):
        if not rings:
            continue
        lab = label(attrs)
        props = {"label": lab, "level": level}
        f = to_feature(rings, props)
        if f is None:
            continue
        if level == "sk_lsd" and lab.isdigit():
            props["n"] = int(lab)        # after cx/cy, the key order BC's LSDs have
        blank += not lab
        out.write(json.dumps(f, separators=(",", ":")) + "\n")
        n += 1
        if n % 500000 == 0:
            print("  %s: %d" % (level, n), file=sys.stderr)
    return n, blank


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in LEVELS:
        sys.exit(__doc__)
    level, shp, dest = sys.argv[1:]
    if dest == "-":
        n, blank = convert(level, shp, sys.stdout)
        sys.stdout.flush()
    else:
        with open(dest, "w") as out:
            n, blank = convert(level, shp, out)
    print("%s: %d features, %d without a label" % (level, n, blank), file=sys.stderr)
