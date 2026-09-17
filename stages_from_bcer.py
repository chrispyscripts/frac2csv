"""Stratum's stage skeleton from BCER's public completion table.

    python3 stages_from_bcer.py --depths ../exports/bc-gundy-cluster/gundy-cluster-stage-depths.csv \
        --cluster ../batch-lists/bc-cluster-2026-09-16.tsv

BCER's IRIS COMPL_WO table (drill_csv.zip) holds one FRAC row per stage the
operator uploaded electronically: the sleeve/port depth (top and base a
tenth of a metre apart on these open-hole ball-drop completions), the
date and the completion type. For a well with no Lab export yet this
writes those as `stages` with empty `series`, so the well view shows the
completion layout at its real depths; a later Lab export replaces them
(stages_from_csv.py) and keeps these depths where the report printed none.
Stage numbering: deepest port = stage 1, as the treatment reports number them.
"""
import argparse
import csv
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--depths", required=True)
    ap.add_argument("--cluster", required=True)
    a = ap.parse_args()
    by = {}
    for r in csv.DictReader(open(a.depths)):
        by.setdefault(str(r["WA"]).zfill(5), []).append(r)
    done = 0
    for c in csv.DictReader(open(a.cluster), delimiter="\t"):
        wa = str(c["WA"]).zfill(5)
        rows = sorted(by.get(wa, []), key=lambda r: int(r["STAGE_BY_DEPTH"]))
        if not rows:
            continue
        path_w = os.path.join(_HERE, "web", "public", "data", "wells", f"{wa}.json")
        if not os.path.exists(path_w):
            continue
        doc = json.load(open(path_w))
        have = {s.get("label"): s for s in doc.get("stages", []) if s.get("series")}
        stages = []
        for r in rows:
            n = int(r["STAGE_BY_DEPTH"]); label = str(n)
            top, base = float(r["TOP_MD_M"]), float(r["BASE_MD_M"] or r["TOP_MD_M"])
            d = r["DATE"]; date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""
            if label in have:                    # the Lab's stage stays; only a missing depth is filled
                s = have[label]
                if s.get("placed"):
                    s.update(top_m=top, base_m=base, placed=False)
                    s.setdefault("notes", []).append("depth from BCER's completion table (the report printed none)")
                stages.append(s)
                continue
            stages.append({"n": n, "label": label, "top_m": top, "base_m": base, "placed": False,
                           "date": date, "start": "", "clock_chart": False, "minutes": 0, "step_s": 0,
                           "page": None, "source": "BCER completion table (no treatment curves yet)",
                           "series": {}, "peaks": {}, "notes": [f"port depth and date from BCER COMPL_WO ({r['COMPLETION_TYPE']}); treatment curves await the Lab export"]})
        doc["stages"] = stages
        json.dump(doc, open(path_w, "w"), separators=(",", ":"))
        done += 1
    print(f"{done} wells given a stage skeleton from BCER depths")


if __name__ == "__main__":
    main()
