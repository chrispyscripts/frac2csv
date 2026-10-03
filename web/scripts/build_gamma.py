"""Gamma ray along every Gundy wellbore, binned by measured depth, for the
underground view's "colour by gamma" mode.

    python3 web/scripts/build_gamma.py [--folder ../exports/bc-gundy-cluster]

Reads the BCER eLibrary LAS files in <folder>/pad-NN/<WA>/ for each well in
web/public/data/underground.json and writes web/public/data/gamma.json:

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
import glob
import json
import os
import re
import statistics
import sys

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_WEB))
from logs_from_las import index_kind, read_las  # noqa: E402

BIN_M = 5.0
GAMMA = re.compile(r"^(GR([_0-9].*)?|GAM|MWD_GAMMA|MG1C)$")
API = re.compile(r"API", re.I)
DEPTH = ("DEPT", "DEPTH", "MD")


def gamma_runs(path):
    """Every gamma curve in one LAS file -> [(mnemonic, md[], v[])]."""
    curves, rows, _null = read_las(path)
    names = [c[0] for c in curves]
    di = next((i for i, n in enumerate(names) if n in DEPTH), 0)
    out = []
    for ci, (mn, unit) in enumerate(curves):
        if ci == di or not GAMMA.match(mn) or not API.search(unit):
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
    runs.sort(key=lambda r: (-round(r["span"]), r["step"]))
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--folder", default=os.path.join(_WEB, "..", "..", "exports", "bc-gundy-cluster"))
    a = ap.parse_args()
    ug = json.load(open(os.path.join(_WEB, "public", "data", "underground.json")))
    wells, missing = {}, {}
    for pad in ug["pads"]:
        for w in pad["wells"]:
            wa = str(w["well"]["wa"]).zfill(5)
            files = sorted(f for f in glob.glob(os.path.join(a.folder, "pad-*", wa, "*"))
                           if f.lower().endswith(".las"))
            g = well_gamma(files) if files else None
            if g:
                wells[wa] = g
            else:
                missing[wa] = "LAS without a gamma curve" if files else "no LAS filed"
    # The colour scale spans the laterals, P2..P98 rounded out to tens: that is
    # where the wells are landed and where a difference between them matters.
    # Above the heel the log runs down to 15 API, and spending the ramp on that
    # would flatten every lateral into the same mid tone; those values clamp.
    heel = {str(w["well"]["wa"]).zfill(5): w["well"].get("heel_md") or 0
            for pad in ug["pads"] for w in pad["wells"]}
    values = sorted(x for wa, g in wells.items() for i, x in enumerate(g["v"])
                    if x is not None and g["md0"] + i * BIN_M >= heel[wa])
    q = lambda f: values[int(f * (len(values) - 1))]
    out = {"source": "BCER eLibrary LAS (files.bc-er.ca/WellData), gamma ray median per bin of measured depth",
           "bin_m": BIN_M, "unit": "API",
           "scale": {"lo": int(q(0.02) // 10 * 10), "p50": round(q(0.5)), "hi": int(-(-q(0.98) // 10) * 10)},
           "wells": wells, "missing": missing}
    path = os.path.join(_WEB, "public", "data", "gamma.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"{len(wells)} wells with gamma, {len(missing)} without "
          f"({sum(1 for r in missing.values() if r == 'no LAS filed')} with no LAS filed); "
          f"lateral scale {out['scale']['lo']}-{out['scale']['hi']} API (median {out['scale']['p50']}); "
          f"{os.path.getsize(path) / 1024:.0f} KB -> {os.path.relpath(path)}")
    for wa, g in sorted(wells.items()):
        print(f"  {wa} {g['md0']:6.0f}-{g['md0'] + len(g['v']) * BIN_M:6.0f} m  "
              + " + ".join(f"{r['mnemonic']}:{r['file'][6:]} {r['top_m']:.0f}-{r['base_m']:.0f}" for r in g["runs"]))


if __name__ == "__main__":
    main()
