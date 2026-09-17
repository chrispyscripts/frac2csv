"""Stratum's stages from the Lab's own CSV exports.

    python3 stages_from_csv.py --folder /Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023 \
        --cluster ../batch-lists/bc-cluster-2026-09-16.tsv

For every well in the cluster, finds the Lab's `<report>-seconds.csv`
(and the `<report>-*summary*.csv` / `-stages-table.csv` beside it, for
depths), thins each stage's channels to well_json.POINTS values, and
writes them into web/public/data/wells/<WA>.json as `stages`, the shape
well.html draws. The Lab's seconds layout: a header row (UWI, STAGE,
DATETIME, ELAPSED, TIMESTAMP, LABEL, Tr Press, Slurry Rate, WH Prop Conc,
BH Prop Conc, ...), a units row, then one row per second, with blank
channels on the first and last row of each stage (pen-up).
"""
import argparse
import csv
import glob
import json
import os
import re

import well_json

_HERE = os.path.dirname(os.path.abspath(__file__))
CHANNELS = {"Tr Press": "press", "Slurry Rate": "rate", "WH Prop Conc": "wh_conc",
            "BH Prop Conc": "bh_conc", "BH Pressure": "bh_press"}
_DEPTH_TOP = re.compile(r"top|interval\s*top|perf\s*top|depth\s*\(?m", re.I)
_DEPTH_BASE = re.compile(r"bottom|base", re.I)


def read_seconds(path):
    """-> {label: {"rows": [...], "stage": seq}} in file order."""
    stages, order = {}, []
    with open(path, newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        next(rd, None)                                       # the units row
        col = {h: i for i, h in enumerate(head)}
        for row in rd:
            if len(row) < 6:
                continue
            label = row[col["LABEL"]] or row[col["STAGE"]]
            if label not in stages:
                stages[label] = {"rows": [], "seq": row[col["STAGE"]], "uwi": row[col["UWI"]]}
                order.append(label)
            stages[label]["rows"].append(row)
    return head, col, [(k, stages[k]) for k in order]


def depths_from_tables(folder, base):
    """Stage -> (top, base) from whatever stage table the Lab wrote beside the seconds file."""
    out = {}
    for path in glob.glob(os.path.join(folder, base + "-*.csv")):
        if path.endswith("-seconds.csv"):
            continue
        try:
            with open(path, newline="") as f:
                rows = list(csv.reader(f))
        except OSError:
            continue
        if not rows:
            continue
        head = rows[0]
        si = next((i for i, h in enumerate(head) if re.fullmatch(r"\s*(stage|zone|interval)\s*#?\s*", str(h), re.I)), None)
        ti = next((i for i, h in enumerate(head) if _DEPTH_TOP.search(str(h)) and not _DEPTH_BASE.search(str(h))), None)
        bi = next((i for i, h in enumerate(head) if _DEPTH_BASE.search(str(h)) and re.search(r"depth|\(m", str(h), re.I)), None)
        if si is None or ti is None:
            continue
        for r in rows[1:]:
            if max(si, ti) >= len(r):
                continue
            try:
                top = float(str(r[ti]).replace(",", ""))
                base_m = float(str(r[bi]).replace(",", "")) if bi is not None and bi < len(r) and r[bi] else None
            except ValueError:
                continue
            key = str(r[si]).strip()
            if key:
                out.setdefault(key, (top, base_m))
                out.setdefault(str(well_json.stage_num(key)), (top, base_m))
    return out


def build_stages(seconds_path, folder, base, source_file):
    head, col, groups = read_seconds(seconds_path)
    depths = depths_from_tables(folder, base)
    stages = []
    for label, g in groups:
        rows = g["rows"]
        n = len(rows)
        series, peaks = {}, {}
        for name, key in CHANNELS.items():
            if name not in col:
                continue
            vals = []
            for r in rows:
                v = r[col[name]] if col[name] < len(r) else ""
                vals.append(float(v) if v not in ("", None) else None)
            thinned, _step = well_json.thin(vals)
            if not any(v is not None for v in thinned):
                continue
            series[key] = thinned
            fin = [v for v in vals if v is not None]
            peaks[key] = round(max(fin), 3) if fin else None
        if not series:
            continue
        dt = rows[0][col["DATETIME"]] if "DATETIME" in col else ""
        date, start = (dt.split(" ") + ["", ""])[:2]
        top, base_m = depths.get(label) or depths.get(str(well_json.stage_num(label))) or (None, None)
        step = max(1, -(-n // well_json.POINTS))
        stages.append({"n": well_json.stage_num(label), "label": well_json._label(label),
                       "top_m": top, "base_m": base_m, "placed": top is None,
                       "date": date if date and not date.startswith("2000-01-01") else "",
                       "start": start if date and not date.startswith("2000-01-01") else "",
                       "clock_chart": False, "minutes": round(n / 60.0, 1), "step_s": step,
                       "page": None, "source": "Lab CSV export", "series": series, "peaks": peaks,
                       "notes": []})
    stages.sort(key=lambda s: s["n"])
    return stages


def merge_bcer(doc, stages):
    """The Lab's stages over the BCER port skeleton stages_from_bcer wrote.

    A treatment chart rarely prints its interval (Trican's never does), so a
    Lab stage without a depth takes the port depth BCER filed for the same
    stage number; a port the Lab has no chart for stays as a depth-only row,
    so the well's stage count is still the completion's. The skeleton is kept
    under `bcer_stages` so a later run can merge again."""
    bcer = doc.get("bcer_stages") or [s for s in doc.get("stages", [])
                                      if str(s.get("source", "")).startswith("BCER")]
    doc["bcer_stages"] = bcer
    by_n = {s["n"]: s for s in bcer}
    for s in stages:
        b = by_n.get(s["n"])
        if not b:
            continue
        if s["top_m"] is None and b.get("top_m") is not None:
            s.update(top_m=b["top_m"], base_m=b.get("base_m"), placed=False)
            s["notes"].append("interval from the BCER completion table, matched by stage number")
        if not s["date"] and b.get("date"):
            s["date"] = b["date"]
    have = {s["n"] for s in stages}
    out = stages + [dict(b) for n, b in by_n.items() if n not in have]
    out.sort(key=lambda s: s["n"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--folder", required=True, help="where the Lab wrote its CSVs")
    ap.add_argument("--cluster", required=True)
    a = ap.parse_args()
    done = missing = 0
    for r in csv.DictReader(open(a.cluster), delimiter="\t"):
        wa = str(r["WA"]).zfill(5)
        base = re.sub(r"\.pdf$", "", r["FILE"], flags=re.I)
        cands = glob.glob(os.path.join(a.folder, "**", base + "-seconds.csv"), recursive=True)
        if not cands:
            missing += 1
            continue
        folder = os.path.dirname(cands[0])
        stages = build_stages(cands[0], folder, base, r["FILE"])
        path_w = os.path.join(_HERE, "web", "public", "data", "wells", f"{wa}.json")
        doc = json.load(open(path_w)) if os.path.exists(path_w) else {"v": 2, "well": {"wa": wa, "name": r["WELL"]}, "units": {}, "stages": [], "logs": [], "notes": []}
        doc["stages"] = merge_bcer(doc, stages)
        doc["units"] = {k: u for k, (_l, u) in well_json.SERIES.items()}
        doc["file"] = r["FILE"]
        json.dump(doc, open(path_w, "w"), separators=(",", ":"))
        measured = sum(1 for s in stages if not s["placed"])
        print(f"{wa} {r['WELL'][:36]:36} {len(stages):3d} stages, {measured:3d} at depth  <- {os.path.basename(cands[0])}")
        done += 1
    print(f"{done} wells with Lab exports, {missing} without")


if __name__ == "__main__":
    main()
