#!/usr/bin/env python3
"""Fill in the unit / LSD numbers the source shapefiles leave blank.

BC-NE-DLS-NTS labels only the CORNER cells of each parent: an NTS block carries
LABELTEXT on units 1, 10, 91 and 100 only (4% of features), and a DLS section on
LSDs 1, 4, 13 and 16 only (25%).  That is plat convention -- a surveyor counts
from a corner -- but it leaves the other 96% / 75% with no number, so the map
cannot compose a fully-qualified location (A-038-L/094-H-05) for most cells.

This adds an `n` property (the integer cell number) to every feature.  `label` is
left exactly as the shapefile wrote it, so rendering stays plat-faithful and only
the hover readout uses the derived value.

Both numbering rules below were fitted to the corner labels and then checked
against every one of them -- see verify() -- and they are NOT the same rule:

  NTS unit  1..100 in a block, 10x10, ROW-MAJOR, every row running east->west,
            rows increasing north.  1=SE 10=SW 91=NE 100=NW.
            (Serpentine was tested and fails on half the corners.)
  DLS LSD   1..16 in a section, 4x4, SERPENTINE: row 0 east->west, row 1
            west->east, ...  1=SE 4=SW 13=NW 16=NE.

NTS is a graticule anchored on integer degrees, so a unit number is a pure
function of the centroid.  DLS is a ground survey with correction lines and
partial sections on the block edge, so LSDs are grouped into their section and
indexed by clustering the centroids, anchored by whatever corner labels the
section does carry -- bbox-quartering is wrong for the 24 sections that the
Peace River Block boundary truncates to a single column.

Usage:  label_infill.py <ndjson-dir>      # rewrites nts_unit/dls_lsd in place
"""
import json, math, os, sys, collections

BW, BH = 0.125, 1.0 / 12.0          # NTS block, degrees
UW, UH = BW / 10.0, BH / 10.0       # NTS unit, degrees


def nts_unit_no(cx, cy):
    """Unit 1..100 from a centroid. Row-major, east->west, rows north."""
    W = -cx                                             # degrees west, positive
    c = int(math.floor((W - math.floor(W / BW) * BW) / UW + 1e-7))   # 0 = east
    r = int(math.floor((cy - math.floor(cy / BH) * BH) / UH + 1e-7))  # 0 = south
    return min(max(r, 0), 9) * 10 + min(max(c, 0), 9) + 1


def dls_lsd_no(col, row):
    """LSD 1..16 from 0-based col (0=east) and row (0=south). Serpentine."""
    return row * 4 + col + 1 if row % 2 == 0 else row * 4 + (4 - col)


def read(path):
    with open(path) as f:
        return [json.loads(l) for l in f]


def bbox(geom):
    pts = []
    def walk(x):
        if isinstance(x[0], (int, float)):
            pts.append(x)
        else:
            for y in x:
                walk(y)
    walk(geom["coordinates"])
    xs = [a for a, b in pts]; ys = [b for a, b in pts]
    return min(xs), min(ys), max(xs), max(ys)


def columns(vals, tol):
    """Distinct column positions, east first. Column spacing within a section is
    even, so a gap wider than `tol` starts a new column."""
    out = []
    for v in sorted(vals):
        if not out or v - out[-1][-1] > tol:
            out.append([v])
        else:
            out[-1].append(v)
    return [sum(g) / len(g) for g in out][::-1]


def lsd_colrow(n):
    """Inverse of dls_lsd_no: LSD number -> (col from east, row from south)."""
    row = (n - 1) // 4
    col = (n - 1) % 4 if row % 2 == 0 else 4 - (n - row * 4)
    return col, row


def axis_index(coords, anchors, n=4):
    """Map a section's local 0..k-1 ranks along one axis onto true 0..n-1 indices.

    `coords` is the representative position of each local rank, ordered so it
    increases with the true index; `anchors` maps a local rank to the true index
    a corner label proves it has.  Two cases have to be told apart:

      - a section clipped at its edge keeps consecutive cells, so the ranks are
        simply offset (the Peace River Block truncates 24 sections to one column);
      - a section missing an interior column has a hole, so ranks are NOT
        consecutive and only the geometry says which index each one is (8
        sections keep columns 0, 1 and 3).

    Anchors that span exactly as many ranks as indices mean no hole, so rank and
    offset; otherwise interpolate each rank's position between the two anchors.
    Row heights are uneven at a correction line, which is why position is used
    only when a hole forces it.
    """
    k = len(coords)
    rng = range(k)
    if not anchors:
        return {i: min(i, n - 1) for i in rng}
    clamp = lambda t: min(max(t, 0), n - 1)
    if len(anchors) == 1:
        (li, ti), = anchors.items()
        return {i: clamp(i + ti - li) for i in rng}
    lo, hi = min(anchors), max(anchors)
    if anchors[hi] - anchors[lo] == hi - lo:
        off = anchors[lo] - lo
        return {i: clamp(i + off) for i in rng}
    ca, cb = coords[lo], coords[hi]
    ta, tb = anchors[lo], anchors[hi]
    span = (cb - ca) or 1e-12
    return {i: clamp(int(round(ta + (coords[i] - ca) / span * (tb - ta)))) for i in rng}


def infill_nts_unit(d):
    feats = read(os.path.join(d, "nts_unit.geojsonl"))
    for f in feats:
        p = f["properties"]
        p["n"] = nts_unit_no(p["cx"], p["cy"])
    bad = sum(1 for f in feats if f["properties"]["label"]
              and int(f["properties"]["label"]) != f["properties"]["n"])
    checked = sum(1 for f in feats if f["properties"]["label"])
    return feats, checked, bad


def infill_dls_lsd(d):
    secs = []
    for f in read(os.path.join(d, "dls_sec.geojsonl")):
        if "cx" not in f["properties"]:
            continue                      # one zero-area sliver on the block edge
        secs.append(bbox(f["geometry"]))
    grid = collections.defaultdict(list)
    for i, bb in enumerate(secs):
        for gx in range(int(bb[0] // .05), int(bb[2] // .05) + 1):
            for gy in range(int(bb[1] // .05), int(bb[3] // .05) + 1):
                grid[(gx, gy)].append(i)

    feats = read(os.path.join(d, "dls_lsd.geojsonl"))
    bysec = collections.defaultdict(list)
    orphan = 0
    for f in feats:
        p = f["properties"]; cx, cy = p["cx"], p["cy"]
        hit = None
        for i in grid.get((int(cx // .05), int(cy // .05)), []):
            bb = secs[i]
            if bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
                hit = i; break
        if hit is None:
            orphan += 1
        else:
            bysec[hit].append(f)

    for i, group in bysec.items():
        bb = secs[i]
        cols = columns([f["properties"]["cx"] for f in group], (bb[2] - bb[0]) / 8.0 or 1e-9)
        bycol = collections.defaultdict(list)
        for f in group:
            c = min(range(len(cols)), key=lambda k: abs(cols[k] - f["properties"]["cx"]))
            bycol[c].append(f)
        # Every column holds one cell per row, so ranking inside a column survives
        # the uneven row heights a correction line leaves in sections 31-36.
        loc = {}
        rowy = collections.defaultdict(list)
        for c, col in bycol.items():
            for r, f in enumerate(sorted(col, key=lambda f: f["properties"]["cy"])):
                loc[id(f)] = (c, r)
                rowy[r].append(f["properties"]["cy"])
        ca = collections.defaultdict(collections.Counter)
        ra = collections.defaultdict(collections.Counter)
        for f in group:
            lab = f["properties"]["label"]
            if not lab:
                continue
            tc, tr = lsd_colrow(int(lab))
            c, r = loc[id(f)]
            ca[c][tc] += 1
            ra[r][tr] += 1
        colmap = axis_index([-x for x in cols],
                            {c: v.most_common(1)[0][0] for c, v in ca.items()})
        rowmap = axis_index([sum(rowy[r]) / len(rowy[r]) for r in sorted(rowy)],
                            {r: v.most_common(1)[0][0] for r, v in ra.items()})
        for f in group:
            c, r = loc[id(f)]
            f["properties"]["n"] = dls_lsd_no(colmap[c], rowmap[r])

    bad = sum(1 for f in feats if f["properties"].get("label")
              and f["properties"].get("n") != int(f["properties"]["label"]))
    checked = sum(1 for f in feats if f["properties"].get("label"))
    return feats, checked, bad, orphan


def write(path, feats):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for x in feats:
            f.write(json.dumps(x, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


if __name__ == "__main__":
    d = sys.argv[1]
    feats, checked, bad = infill_nts_unit(d)
    print("nts_unit: %d features, %d carry a source label, %d disagree" % (len(feats), checked, bad))
    assert bad == 0, "nts_unit numbering contradicts the shapefile"
    write(os.path.join(d, "nts_unit.geojsonl"), feats)

    feats, checked, bad, orphan = infill_dls_lsd(d)
    print("dls_lsd:  %d features, %d carry a source label, %d disagree, %d outside any section"
          % (len(feats), checked, bad, orphan))
    assert bad == 0, "dls_lsd numbering contradicts the shapefile"
    assert orphan == 0, "some LSDs fell outside every section"
    write(os.path.join(d, "dls_lsd.geojsonl"), feats)
    print("ok - both layers rewritten with an `n` property")
