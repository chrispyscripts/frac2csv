"""Per-stage coverage and peak of one channel, one payload against another.

    python3 ab_coverage.py before.json after.json "WH Prop Conc"

Prints the tree each payload records so an identical result cannot hide a
run on the wrong code — the stash trap in HANDOFF. Used to show 7b70f0c did
NOT cause #638: 36 of 42 stages byte-identical, the six that moved were the
698.29 rule leaving.
"""
import json
import sys

import numpy as np


def cov(payload, key):
    out = {}
    for st in payload["stages"]:
        ch = next((c for c in st["channels"] if c["key"] == key), None)
        if ch:
            a = np.array([np.nan if v is None else v for v in ch["values"]], float)
            out[str(st["meta"].get("stage"))] = (
                float(np.isfinite(a).mean()),
                float(np.nanmax(a)) if np.isfinite(a).any() else None)
    return out


def main(before_path, after_path, key):
    before, after = json.load(open(before_path)), json.load(open(after_path))
    print("before:", before.get("tree", before.get("file")), "| after:", after.get("tree", after.get("file")))
    b, a = cov(before, key), cov(after, key)
    rows = [(s, b[s][0], a[s][0], b[s][1], a[s][1]) for s in a if s in b]
    same = sum(1 for r in rows if abs(r[1] - r[2]) < 1e-6)
    print(f"{key}: {len(rows)} stages compared, {same} unchanged")
    print("  stage   filled before -> after     peak before -> after")
    for s, fb, fa, pb, pa in rows:
        if abs(fb - fa) < 0.005 and (pb == pa):
            continue
        flag = "  <-- lost" if fa < fb - 0.1 else ("  <-- gained" if fa > fb + 0.1 else "")
        print(f"  {s:>5}   {fb * 100:5.0f}% -> {fa * 100:4.0f}%          {pb!s:>8} -> {pa!s:<8}{flag}")
    if rows:
        print(f"  mean filled: before {np.mean([r[1] for r in rows]) * 100:.0f}%  "
              f"after {np.mean([r[2] for r in rows]) * 100:.0f}%")


if __name__ == "__main__":
    main(*sys.argv[1:4])
