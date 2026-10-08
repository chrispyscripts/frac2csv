"""What changed in FracView's data, for the watch list (watch.js, api/digest.js).

    python3 web/scripts/build_updates.py

Run after the rebuild (build_discover.py, build_production.py). Compares the
region as built now with the last run's data/updates.json and dates what is new:

  charts       a well whose treatment charts came in (dated the run they appeared)
  prodSeen     a well with production through a later month than last time
               (prodThrough: that month)

The first run dates nothing (`baseline`): everything there already counts as
old, so the watch list only reports what arrives afterwards.
"""
import json
import os
from datetime import date

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "data")


def main():
    path = os.path.join(DATA, "updates.json")
    old = json.load(open(path)) if os.path.exists(path) else None
    today = date.today().isoformat()
    w = json.load(open(os.path.join(DATA, "discover", "wells.json")))
    ci = {c: i for i, c in enumerate(w["columns"])}
    prod = json.load(open(os.path.join(DATA, "prod", "wells.json")))["wells"]

    def through(wa):
        p = prod.get(wa.zfill(5))
        if not p:
            return None
        y, m = (int(x) for x in p["f"].split("-"))
        k = y * 12 + m - 1 + len(p["g"]) - 1
        return f"{k // 12}-{k % 12 + 1:02d}"

    baseline = old["baseline"] if old else today
    prev = old["wells"] if old else {}
    wells, new_charts, new_prod = {}, 0, 0
    for r in w["rows"]:
        wa = str(r[ci["wa"]])
        e = dict(prev.get(wa) or {})
        charted = bool(r[ci["curves"]] or r[ci["chartedStages"]])
        if charted and not e.get("charts"):
            e["charts"] = baseline if not old else today
            new_charts += bool(old)
        t = through(wa)
        if t and t != e.get("prodThrough"):
            if e.get("prodThrough") and old:
                e["prodSeen"] = today
                new_prod += 1
            elif not e.get("prodSeen"):
                e["prodSeen"] = baseline
            e["prodThrough"] = t
        if e:
            wells[wa] = e
    json.dump({"v": 1, "built": today, "baseline": baseline, "wells": wells}, open(path, "w"), separators=(",", ":"))
    print(f"{len(wells)} wells dated; {new_charts} newly charted and {new_prod} with new production since the last run"
          + ("" if old else f" (first run: baseline {baseline})"))


if __name__ == "__main__":
    main()
