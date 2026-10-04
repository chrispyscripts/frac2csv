"""Gamma ray along every region wellbore that has a LAS log, binned by measured
depth, for the underground view's "colour by gamma" mode.

    python3 web/scripts/build_gamma.py [--folder DIR ...]

For each well in web/public/data/region/ (index.json and its pad files), reads
the BCER eLibrary LAS files found in any --folder, laid out either as
<folder>/pad-NN/<WA>/ (the Gundy export) or <folder>/<WA>/ (fetch_elibrary.py),
and writes web/public/data/gamma.json:

  {bin_m, unit, scale: {lo, hi, p50}, wells: {WA: {md0, v: [API|null, ...],
   runs: [{file, mnemonic, top_m, base_m}]}}, missing: {WA: reason}}

v[i] is the median gamma over [md0 + i*bin_m, md0 + (i+1)*bin_m).

The vendors name the curve four ways: GR (with a tool suffix on Phoenix's
GR_HRM1), GAM on the 2018 EM-memory runs, MWD_GAMMA and MG1C on the 2022
MWD files. logs_from_las.py only knows GR, which is why its per-well tracks
miss eight of these wells; this reads all four.

A well logged more than once keeps every MD-indexed run: each bin takes the
run that covers the most of the wellbore, and a shorter run only fills where
that one has no samples (28744 and 34713 have a wireline pass down the
vertical and a memory-gamma run along the lateral). TVD-indexed copies and
repeat passes are skipped -- a TVD index would put the reading at the wrong
place along the path.
"""
import argparse
import bisect
import glob
import math
import json
import os
import re
import statistics
import sys

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_WEB))
from logs_from_las import index_kind, read_las  # noqa: E402

BIN_M = 5.0
# Total gamma ray as each vendor names it. Raw counts (MG1, CPS) and spectral
# components (KTH, POTA...) are not in the list; near-bit "apparent" gamma
# (GBAM, GBAX) is, behind any GR run that covers the same depth.
GAMMA = re.compile(r"^(GR([_0-9].*)?|GAM|GAMMA(_.*)?|MWD_GAMMA|MG1C|GRGM|GRAX|GRMEM|GRSL|GBAM|GBAX)$")
API = re.compile(r"API", re.I)
UNITLESS_OK = re.compile(r"^(GR|GAMMA)")   # a blank unit is taken only on an unmistakable name
DEPTH = ("DEPT", "DEPTH", "MD")


def gamma_runs(path):
    """Every gamma curve in one LAS file -> [(mnemonic, md[], v[])]."""
    curves, rows, _null = read_las(path)
    names = [c[0] for c in curves]
    di = next((i for i, n in enumerate(names) if n in DEPTH), 0)
    out = []
    for ci, (mn, unit) in enumerate(curves):
        if ci == di or not GAMMA.match(mn) or not (API.search(unit) or (not unit and UNITLESS_OK.match(mn))):
            continue
        md, v = [], []
        for r in rows:
            if ci < len(r) and di < len(r) and r[di] is not None and r[ci] is not None and 0 <= r[ci] <= 2000:
                md.append(r[di]); v.append(r[ci])
        if len(md) >= 20:
            out.append((mn, md, v))
    return out


def bin_run(md, v):
    bins = {}
    for m, x in zip(md, v):
        bins.setdefault(int(m // BIN_M), []).append(x)
    return {k: statistics.median(xs) for k, xs in bins.items()}


def well_gamma(files):
    runs = []
    for p in files:
        name = os.path.basename(p).upper()
        if "REPEAT" in name or index_kind(p)[0]:
            continue
        for mn, md, v in gamma_runs(p):
            runs.append({"file": os.path.basename(p), "mnemonic": mn, "md": md, "v": v,
                         "span": max(md) - min(md), "step": (max(md) - min(md)) / len(md)})
    if not runs:
        return None
    # widest coverage first; between identical copies (0.2 m and 1 m), the finer
    runs.sort(key=lambda r: (r["mnemonic"] in ("GBAM", "GBAX"), -round(r["span"]), r["step"]))
    merged, used = {}, []
    for r in runs:
        added = 0
        for k, x in bin_run(r["md"], r["v"]).items():
            if k not in merged:
                merged[k] = x; added += 1
        if added:
            used.append({"file": r["file"], "mnemonic": r["mnemonic"],
                         "top_m": round(min(r["md"]), 1), "base_m": round(max(r["md"]), 1)})
    k0, k1 = min(merged), max(merged)
    return {"md0": k0 * BIN_M,
            "v": [round(merged[k]) if k in merged else None for k in range(k0, k1 + 1)],
            "runs": used}


# ---------- offset estimates ----------
# A well that filed no gamma log takes it from logged wells nearby, read at the
# same depth below sea level: within a few km the Montney's beds are near flat,
# so the gamma a neighbour recorded at a given subsea depth is the best guess for
# the same subsea depth here. Up to EST_K neighbours within EST_KM of the lateral,
# inverse-distance weighted. Each estimate says which wells it came from, and the
# method is scored by estimating logged wells from their neighbours (leave one out).
EST_KM, EST_K, EST_TOL_M = 3.0, 3, 3.0
EST_SMOOTH = 10          # bins each side (50 m): the level is what an estimate can carry, not the detail


def _interp(xs, ys, x):
    if not xs or x < xs[0] or x > xs[-1]:
        return None
    i = bisect.bisect_left(xs, x)
    if i == 0:
        return ys[0]
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / ((x1 - x0) or 1)


def _well_geom(w):
    t, well = w["trajectory"], w["well"]
    md, tvd = list(t["md"]), list(t["tvd"])
    i = int(len(md) * 0.75)
    lat = well["lat"] + t["ns"][i] / 111320.0
    lon = well["lon"] + t["ew"][i] / (111320.0 * math.cos(math.radians(well["lat"])))
    return {"md": md, "tvd": tvd, "elev": well.get("elev_m") or 0, "lat": lat, "lon": lon,
            "td": md[-1], "pad": None}


def _subsea_log(g, geom):
    """A logged well's gamma as (subsea depth, API) pairs, sorted by depth."""
    pts = []
    for i, v in enumerate(g["v"]):
        if v is None:
            continue
        tvd = _interp(geom["md"], geom["tvd"], g["md0"] + (i + 0.5) * BIN_M)
        if tvd is not None:
            pts.append((tvd - geom["elev"], v))
    pts.sort()
    return [p[0] for p in pts], [p[1] for p in pts]


def _at_depth(log, z):
    zs, vs = log
    i = bisect.bisect_left(zs, z)
    near = [vs[j] for j in range(max(0, i - 3), min(len(zs), i + 3)) if abs(zs[j] - z) <= EST_TOL_M]
    return statistics.median(near) if near else None


def _estimate_one(geom, offsets):
    """offsets: [(distance_km, wa, subsea log)] -> (md0, values)"""
    n = int(geom["td"] // BIN_M) + 1
    vals = []
    for i in range(n):
        tvd = _interp(geom["md"], geom["tvd"], (i + 0.5) * BIN_M)
        if tvd is None:
            vals.append(None)
            continue
        z, num, den = tvd - geom["elev"], 0.0, 0.0
        for d, _wa, log in offsets:
            v = _at_depth(log, z)
            if v is not None:
                wgt = 1.0 / max(d, 0.1)
                num += wgt * v
                den += wgt
        vals.append(num / den if den else None)
    # Scored on logged wells, the estimate tracks each lateral's level (which bed
    # it sits in) but not its bed-to-bed wiggle, so the wiggle is smoothed away
    # rather than drawn as detail nobody measured.
    out = []
    for i in range(len(vals)):
        win = [v for v in vals[max(0, i - EST_SMOOTH):i + EST_SMOOTH + 1] if v is not None]
        out.append(round(statistics.median(win)) if vals[i] is not None and win else None)
    return 0, out


def _pearson(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    sa = math.sqrt(sum((x - ma) ** 2 for x in a)); sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else None


def estimate(pads, wells, missing, areas_path):
    areas = json.load(open(areas_path))["areas"]
    want = {pid for a in areas for pid in a["pads"]}
    rows = {str(w["well"]["wa"]).zfill(5): (p["id"], w) for p in pads for w in p["wells"]}
    geom = {wa: _well_geom(w) for wa, (_pid, w) in rows.items()}
    logs = {wa: _subsea_log(g, geom[wa]) for wa, g in wells.items() if wa in geom}

    def neighbours(wa, exclude=()):
        g0 = geom[wa]
        c = math.cos(math.radians(g0["lat"]))
        near = []
        for o, log in logs.items():
            if o == wa or o in exclude or not log[0]:
                continue
            d = math.hypot((geom[o]["lat"] - g0["lat"]) * 111.32, (geom[o]["lon"] - g0["lon"]) * 111.32 * c)
            if d <= EST_KM:
                near.append((d, o, log))
        return sorted(near)[:EST_K]

    # score the method by estimating every logged well in the same areas from its
    # neighbours and comparing lateral medians: the level is what gets drawn
    act, est_l = [], []
    for wa, (pid, w) in rows.items():
        if pid not in want or wa not in wells:
            continue
        offs = neighbours(wa)
        if not offs:
            continue
        _md0, est = _estimate_one(geom[wa], offs)
        g, heel = wells[wa], w["well"].get("heel_md") or 0
        a_ = [v for i, v in enumerate(g["v"]) if v is not None and g["md0"] + i * BIN_M >= heel]
        b_ = [v for i, v in enumerate(est) if v is not None and i * BIN_M >= heel]
        if len(a_) > 30 and len(b_) > 30:
            act.append(statistics.median(a_)); est_l.append(statistics.median(b_))

    made = 0
    for wa, (pid, w) in rows.items():
        if pid not in want or wa in wells:
            continue
        offs = neighbours(wa)
        if not offs:
            missing[wa] = "no log filed, no logged well within %g km" % EST_KM
            continue
        md0, vals = _estimate_one(geom[wa], offs)
        if not any(v is not None for v in vals):
            continue
        wells[wa] = {"md0": md0, "v": vals, "runs": [], "estimated": True,
                     "from": [{"wa": o, "km": round(d, 2)} for d, o, _l in offs]}
        missing.pop(wa, None)
        made += 1
    return {"wells": made, "method": f"offset logs at the same subsea depth, up to {EST_K} wells within {EST_KM:g} km, inverse-distance weighted",
            "tested": len(act), "level_r": round(_pearson(act, est_l), 2) if len(act) > 2 else None,
            "level_mae": round(statistics.mean(abs(x - y) for x, y in zip(act, est_l)), 1) if act else None,
            "level_spread": round(statistics.pstdev(act), 1) if len(act) > 1 else None,
            "smoothed_m": 2 * EST_SMOOTH * BIN_M}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--estimate", default=os.path.join(_WEB, "public", "data", "region", "featured.json"),
                    help="areas file whose wells without a log get an offset estimate ('' for none)")
    ap.add_argument("--folder", action="append",
                    help="where LAS files live (repeatable); default: the Gundy export and ~/BCER-eLibrary")
    a = ap.parse_args()
    folders = a.folder or [os.path.join(_WEB, "..", "..", "exports", "bc-gundy-cluster"),
                           os.path.expanduser("~/BCER-eLibrary")]
    data = os.path.join(_WEB, "public", "data", "region")
    pads = [json.load(open(os.path.join(data, "pads", f"{p['id']}.json")))
            for p in json.load(open(os.path.join(data, "index.json")))["pads"]]
    wells, missing = {}, {}
    for pad in pads:
        for w in pad["wells"]:
            wa = str(w["well"]["wa"]).zfill(5)
            files = sorted(f for d in folders for f in glob.glob(os.path.join(d, "pad-*", wa, "*")) +
                           glob.glob(os.path.join(d, wa, "*")) if f.lower().endswith(".las"))
            g = well_gamma(files) if files else None
            if g:
                wells[wa] = g
            else:
                missing[wa] = "LAS without a gamma curve" if files else "no LAS on hand"
    measured = set(wells)
    est_stats = estimate(pads, wells, missing, a.estimate) if a.estimate else None

    # The colour scale spans the laterals, P2..P98 rounded out to tens: that is
    # where the wells are landed and where a difference between them matters.
    # Above the heel the log runs down to 15 API, and spending the ramp on that
    # would flatten every lateral into the same mid tone; those values clamp.
    heel = {str(w["well"]["wa"]).zfill(5): w["well"].get("heel_md") or 0
            for pad in pads for w in pad["wells"]}
    values = sorted(x for wa, g in wells.items() if wa in measured for i, x in enumerate(g["v"])
                    if x is not None and g["md0"] + i * BIN_M >= heel[wa])
    q = lambda f: values[int(f * (len(values) - 1))]
    out = {"source": "BCER eLibrary LAS (files.bc-er.ca/WellData), gamma ray median per bin of measured depth",
           "bin_m": BIN_M, "unit": "API",
           "scale": {"lo": int(q(0.02) // 10 * 10), "p50": round(q(0.5)), "hi": int(-(-q(0.98) // 10) * 10)},
           "wells": wells, "missing": missing,
           "estimate": est_stats}
    path = os.path.join(_WEB, "public", "data", "gamma.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    if est_stats:
        print(f"estimated {est_stats['wells']} wells from offset logs; tested on {est_stats['tested']} logged "
              f"wells: lateral level r {est_stats['level_r']}, mean abs error {est_stats['level_mae']} API "
              f"(well-to-well spread {est_stats['level_spread']} API)")
    print(f"{len(wells)} wells with gamma, {len(missing)} without "
          f"({sum(1 for r in missing.values() if r == 'no LAS on hand')} with no LAS on hand); "
          f"lateral scale {out['scale']['lo']}-{out['scale']['hi']} API (median {out['scale']['p50']}); "
          f"{os.path.getsize(path) / 1024:.0f} KB -> {os.path.relpath(path)}")
    for wa, g in sorted(wells.items()):
        print(f"  {wa} {g['md0']:6.0f}-{g['md0'] + len(g['v']) * BIN_M:6.0f} m  "
              + " + ".join(f"{r['mnemonic']}:{r['file'][6:]} {r['top_m']:.0f}-{r['base_m']:.0f}" for r in g["runs"]))


if __name__ == "__main__":
    main()
