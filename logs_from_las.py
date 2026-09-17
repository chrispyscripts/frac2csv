"""Stratum's log tracks from BCER LAS files (gamma ray along the wellbore).

    python3 logs_from_las.py --folder ../exports/bc-gundy-cluster --cluster ../batch-lists/bc-cluster-2026-09-16.tsv

For each cluster well, reads the LAS files in <folder>/pad-NN/<WA>/, takes
the curves worth drawing (GR first; DT, NPSS/DPSS, RHOB/DRHO, PEF, CALI,
ROP when present), thins them to LOG_POINTS values, and writes them into
web/public/data/wells/<WA>.json as
  logs: [{name, mnemonic, unit, md: [...], v: [...], file}]
which is the slot well.html reserved for the LAS track.
"""
import argparse
import csv
import glob
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_POINTS = 1500
WANT = ["GR", "ROP", "DT", "NPSS", "DPSS", "NPDL", "DRHO", "RHOB", "PEF", "CALI"]
NAMES = {"GR": "Gamma ray", "ROP": "Rate of penetration", "DT": "Sonic", "NPSS": "Neutron porosity",
         "DPSS": "Density porosity", "NPDL": "Neutron porosity", "DRHO": "Density correction",
         "RHOB": "Bulk density", "PEF": "Photoelectric", "CALI": "Caliper"}


def read_las(path):
    """-> (curves [(mnemonic, unit)], rows [[float|None, ...]], null)."""
    curves, rows, null, sec = [], [], -999.25, ""
    with open(path, errors="ignore") as f:
        for line in f:
            if line.startswith("~"):
                sec = line[1:2].upper()
                continue
            if line.startswith("#") or not line.strip():
                continue
            if sec == "W" and line.strip().upper().startswith("NULL"):
                m = re.search(r"\.\s*(-?[\d.]+)", line)
                if m:
                    null = float(m.group(1))
            elif sec == "C":
                m = re.match(r"\s*([A-Za-z0-9_:\-]+)\s*\.([A-Za-z0-9/%]*)", line)
                if m:
                    curves.append((m.group(1).upper(), m.group(2)))
            elif sec == "A":
                vals = []
                for t in line.split():
                    try:
                        v = float(t)
                        vals.append(None if v == null else v)
                    except ValueError:
                        vals.append(None)
                if vals:
                    rows.append(vals)
    return curves, rows, null


_STOP = re.compile(r"^\s*STOP\s*\.\s*\S*\s+(-?[\d.]+)", re.I)
_DEPTH_CURVE = re.compile(r"^\s*(DEPT|DEPTH|MD)\b", re.I)


def index_kind(path):
    """(is_tvd, -stop) -- an MD-indexed log sorts before a TVD copy of the same
    well, and the deeper of two MD logs first.  Phoenix writes one LAS over the
    build section indexed on TRUE VERTICAL DEPTH and another over the whole
    wellbore indexed on measured depth; the filename says which only by its
    depth range, so the header has to be read."""
    tvd, stop = "TVD" in path.upper(), 0.0
    with open(path, errors="ignore") as f:
        sec = ""
        for line in f:
            if line.startswith("~"):
                sec = line[1:2].upper()
                if sec == "A":
                    break
                continue
            if sec == "W":
                m = _STOP.match(line)
                if m:
                    try:
                        stop = float(m.group(1))
                    except ValueError:
                        pass
            elif sec == "C" and _DEPTH_CURVE.match(line) and "TRUE VERTICAL" in line.upper():
                tvd = True
    return (tvd, -stop)


def curve_index(names, mn):
    """The curve for a wanted mnemonic, allowing a tool suffix: BCER LAS files
    from Phoenix write GR_HRM1 / ROP_HRM rather than a bare GR / ROP."""
    if mn in names:
        return names.index(mn)
    for i, n in enumerate(names):
        if re.fullmatch(mn + r"[_0-9].*", n):
            return i
    return None


def thin(md, v, n):
    if len(md) <= n:
        return md, v
    step = len(md) / float(n)
    idx = [int(i * step) for i in range(n)] + [len(md) - 1]
    return [md[i] for i in idx], [v[i] for i in idx]


def tracks(path):
    curves, rows, _null = read_las(path)
    if not curves or not rows:
        return []
    names = [c[0] for c in curves]
    di = next((i for i, n in enumerate(names) if n in ("DEPT", "DEPTH", "MD")), 0)
    out = []
    for mn in WANT:
        ci = curve_index(names, mn)
        if ci is None:
            continue
        md, v = [], []
        for r in rows:
            if ci < len(r) and di < len(r) and r[di] is not None and r[ci] is not None:
                md.append(r[di]); v.append(r[ci])
        if len(md) < 20:
            continue
        md, v = thin(md, v, LOG_POINTS)
        out.append({"name": NAMES.get(mn, mn), "mnemonic": mn, "unit": curves[ci][1],
                    "md": [round(x, 1) for x in md], "v": [round(x, 3) for x in v],
                    "file": os.path.basename(path)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--folder", required=True)
    ap.add_argument("--cluster", required=True)
    a = ap.parse_args()
    done = 0
    for r in csv.DictReader(open(a.cluster), delimiter="\t"):
        wa = str(r["WA"]).zfill(5)
        files = sorted(glob.glob(os.path.join(a.folder, f"pad-{int(r['PAD']):02d}", wa, "*.LAS"))
                       + glob.glob(os.path.join(a.folder, f"pad-{int(r['PAD']):02d}", wa, "*.las")))
        logs, seen = [], set()
        # the main log first, repeat passes and TVD-indexed copies after
        files.sort(key=lambda p: ("REPEAT" in p.upper(), index_kind(p), p))
        for p in files:
            for t in tracks(p):
                if t["mnemonic"] in seen:
                    continue
                seen.add(t["mnemonic"]); logs.append(t)
        if not logs:
            continue
        path_w = os.path.join(_HERE, "web", "public", "data", "wells", f"{wa}.json")
        if not os.path.exists(path_w):
            continue
        doc = json.load(open(path_w)); doc["logs"] = logs
        json.dump(doc, open(path_w, "w"), separators=(",", ":"))
        gr = next((t for t in logs if t["mnemonic"] == "GR"), None)
        print(f"{wa} {r['WELL'][:34]:34} {len(logs)} tracks {[t['mnemonic'] for t in logs]}" + (f"  GR {gr['md'][0]:.0f}-{gr['md'][-1]:.0f} m" if gr else ""))
        done += 1
    print(f"{done} wells with log tracks")


if __name__ == "__main__":
    main()
