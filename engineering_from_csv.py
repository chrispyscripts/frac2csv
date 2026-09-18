"""Stratum's per-stage engineering summaries from the Lab's stage tables.

    python3 engineering_from_csv.py --folder ../exports/bc-gundy-cluster/lab-seconds \
        --cluster ../batch-lists/bc-cluster-2026-09-16.tsv

Beside each `<report>-seconds.csv` the Lab writes a per-stage table: what the
treatment actually did, as reported, rather than the traces. This reads it into
web/public/data/wells/<WA>.json as `engineering_stages`, the list well.html
already draws its "extracted stage summaries" table from.

The tables are NOT one format. Across a single cluster there are a dozen-odd
column sets: whether breakdown and ISIP pressures were recorded at all, which
chemicals and proppant meshes the job used (each gets its own named column),
and an older, sparser layout whose pressure columns are empty. So columns are
matched by name through ALIASES rather than by position, every field is
optional, and anything absent stays null instead of being guessed at.

Two vocabularies are deliberately kept apart rather than merged:

  water_m3 / clean_vol_m3     water pumped vs total clean fluid -- not the
                              same measurement, so not the same field
  prop_*_t  /  chem_*_l       per-job proppant meshes and chemicals, collected
                              into `proppants` and `chemicals` under the
                              column's own name, since a job's product names
                              are not a fixed vocabulary
"""
import argparse
import csv
import glob
import json
import os
import re

import well_json

_HERE = os.path.dirname(os.path.abspath(__file__))


def key(name):
    """A column heading -> a comparable key ('Average Rate (m³/min)' -> 'average_rate_m_min')."""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


ALIASES = {
    "top_m":            ("interval_top_m", "depth_m"),
    "base_m":           ("interval_base_m",),
    "minutes":          ("total_time_min", "pumping_min", "elapsed_min"),
    "breakdown_mpa":    ("breakdown_mpa",),
    "isip_mpa":         ("isip_mpa",),
    "avg_pressure_mpa": ("avg_mpa", "average_pressure_mpa"),
    "max_pressure_mpa": ("max_mpa", "max_pressure_mpa"),
    "min_pressure_mpa": ("min_mpa", "minimum_pressure_mpa"),
    "avg_rate_m3_min":  ("rate_avg_m3min", "average_rate_m_min"),
    "max_rate_m3_min":  ("rate_max_m3min",),
    "avg_conc_kg_m3":   ("conc_avg_kgm3",),
    "max_conc_kg_m3":   ("conc_max_kgm3",),
    "pad_vol_m3":       ("pad_vol_m3",),
    "slurry_vol_m3":    ("prop_vol_m3", "slurry_vol_m3"),
    "water_m3":         ("water_m3",),
    "clean_vol_m3":     ("clean_vol_m3",),
    "hole_vol_m3":      ("hole_vol_m3",),
    # downhole proppant is what was placed; surface is what was metered out
    "proppant_t":       ("proppant_t", "proppant_dh_t", "proppant_surface_t",
                         "total_proppant_placed_tonne"),
}
TEXT = {"label": ("stage_label",), "proppant_types": ("proppant_types",),
        "interval_type": ("interval_type",)}
DATE = ("date", "date_time")
STAGE = ("stage", "stage_number")


def num(v):
    s = str(v or "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pick(row, names):
    for n in names:
        if n in row and str(row[n]).strip() != "":
            return row[n]
    return None


def read_table(path):
    """-> [stage dicts], or [] if the file is not a per-stage table."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    # some exports carry a well banner line above the real header
    hi = next((i for i, r in enumerate(rows[:4]) if r and key(r[0]) == "uwi"), None)
    if hi is None:
        return []
    head = [key(h) for h in rows[hi]]
    out = []
    for raw in rows[hi + 1:]:
        if not raw or not any(str(c).strip() for c in raw):
            continue
        row = {h: (raw[i] if i < len(raw) else "") for i, h in enumerate(head)}
        label = pick(row, TEXT["label"]) or pick(row, STAGE) or ""
        rec = {"n": well_json.stage_num(label), "label": well_json._label(label),
               "date": (str(pick(row, DATE) or "").split(" ")[0] or ""),
               "source": os.path.basename(path)}
        for canon, names in ALIASES.items():
            rec[canon] = num(pick(row, names))
        for canon, names in TEXT.items():
            if canon == "label":
                continue
            v = pick(row, names)
            rec[canon] = str(v).strip() if v is not None else None
        # per-job products: the column name is the product
        rec["proppants"] = {h[5:-2]: num(row[h]) for h in head
                            if h.startswith("prop_") and h.endswith("_t") and num(row[h]) is not None}
        rec["chemicals"] = {h[5:-2]: num(row[h]) for h in head
                            if h.startswith("chem_") and h.endswith("_l") and num(row[h]) is not None}
        if rec["n"] is None and not rec["label"]:
            continue
        out.append(rec)
    out.sort(key=lambda s: (s["n"] if s["n"] is not None else 0))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--folder", required=True, help="where the Lab wrote its CSVs")
    ap.add_argument("--cluster", required=True)
    a = ap.parse_args()
    done = stages = missing = 0
    filled = {k: 0 for k in ALIASES}
    for r in csv.DictReader(open(a.cluster), delimiter="\t"):
        wa = str(r["WA"]).zfill(5)
        base = re.sub(r"\.pdf$", "", r["FILE"], flags=re.I)
        cands = [p for p in glob.glob(os.path.join(a.folder, "**", base + "-*.csv"), recursive=True)
                 if not p.endswith("-seconds.csv")]
        rows = []
        for p in sorted(cands):
            rows = read_table(p)
            if rows:
                break
        if not rows:
            missing += 1
            print(f"{wa} {r['WELL'][:40]:40} no per-stage table")
            continue
        path_w = os.path.join(_HERE, "web", "public", "data", "wells", f"{wa}.json")
        if not os.path.exists(path_w):
            missing += 1
            continue
        doc = json.load(open(path_w))
        doc["engineering_stages"] = rows
        json.dump(doc, open(path_w, "w"), separators=(",", ":"))
        for k in filled:
            filled[k] += sum(1 for s in rows if s.get(k) is not None)
        done += 1
        stages += len(rows)
        got = [k for k in ("breakdown_mpa", "isip_mpa", "avg_pressure_mpa", "proppant_t")
               if any(s.get(k) is not None for s in rows)]
        print(f"{wa} {r['WELL'][:40]:40} {len(rows):3d} stages  <- {os.path.basename(rows[0]['source'])[:48]}  [{', '.join(got)}]")
    print(f"\n{done} wells, {stages} stage summaries, {missing} without a table")
    print("field coverage (stages with a value):")
    for k in sorted(filled, key=lambda k: -filled[k]):
        print(f"   {k:20s} {filled[k]:5d}  {100.0 * filled[k] / max(stages, 1):5.1f}%")


if __name__ == "__main__":
    main()
