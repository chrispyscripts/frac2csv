"""The website's per-well file: stages along the lateral, each with its
traces, from a Lab payload.

    python3 well_json.py <payload.json> --wa 30209 -o web/public/data/wells/30209.json
    python3 well_json.py <payload.json> --wa 30209 --index web/public/data/wells/index.json

The Lab gathers the data; the site is what a customer sees. Its well view
draws the wellbore left to right by measured depth and stands each
stage's pressure, rate and concentration traces over the interval the
report printed for it — the shape of a "geology with completions" slide.
Everything the page needs is in this one file:

  well     the record the map already carries (name, WA, UWI, total depth,
           lateral length, year) so the lateral can be drawn to scale
  stages   one per treatment chart, ordered by stage number:
             n, label, top_m, base_m, placed (True when the report printed
             no depth and the stage is stood by order), date, start,
             minutes, series {press, rate, wh_conc, bh_conc, bh_press}
             each thinned to at most POINTS values (None where the chart
             drew nothing), peaks per series
  logs     [] — reserved for the well logs (LAS: gamma ray, resistivity)
           that will colour the wellbore; the page draws the track only
           when one is here
  notes    the file's own notes, as the Lab shows them

Thinning keeps the mean of each bin so a spike survives as a bump and a
gap stays a gap; the full-rate samples stay in the Lab export.
"""
import argparse
import json
import math
import os
import re

import numpy as np

POINTS = 360
SERIES = {"press": ("Tr Press", "MPa"), "rate": ("Slurry Rate", "m3/min"),
          "wh_conc": ("WH Prop Conc", "kg/m3"), "bh_conc": ("BH Prop Conc", "kg/m3"),
          "bh_press": ("BH Pressure", "MPa")}

_HERE = os.path.dirname(os.path.abspath(__file__))
WELL_FILES = (os.path.join(_HERE, "web", "public", "data", "bc-wells.json"),
              os.path.join(_HERE, "web", "public", "data", "ab-wells.json"))


def stage_num(label):
    m = re.match(r"\s*(\d+)", str(label or ""))
    return int(m.group(1)) if m else 10 ** 9


def thin(values, points=POINTS):
    """-> (list of floats/None, step in samples). The mean of each bin."""
    a = np.asarray([np.nan if v is None else v for v in values], float)
    n = len(a)
    if n == 0:
        return [], 1
    step = max(1, int(math.ceil(n / float(points))))
    out = []
    for i in range(0, n, step):
        seg = a[i:i + step]
        fin = seg[np.isfinite(seg)]
        out.append(None if not fin.size else round(float(fin.mean()), 3))
    return out, step


def find_well(wa=None, uwis=()):
    """The map's record for this well, by WA (BC) or by UWI in either
    province file. -> dict or {}."""
    uwis = {re.sub(r"[^0-9A-Z]", "", str(u).upper()) for u in uwis if u}
    for path in WELL_FILES:
        if not os.path.exists(path):
            continue
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        for r in d.get("wells", []):
            if wa and str(r.get("wa", "")).lstrip("0") == str(wa).lstrip("0"):
                return dict(r, prov="BC" if "bc-wells" in path else "AB")
            for u in r.get("u", []):
                if re.sub(r"[^0-9A-Z]", "", str(u).upper()) in uwis:
                    return dict(r, prov="BC" if "bc-wells" in path else "AB")
    return {}


def build(payload, wa=None, source_file=""):
    stages = []
    uwis = set()
    for s in payload.get("stages", []):
        m = s.get("meta") or {}
        if m.get("continuous") or not str(m.get("stage") or "").strip():
            continue
        if m.get("uwi"):
            uwis.add(m["uwi"])
        chans = {c["key"]: c for c in s.get("channels", [])}
        series, peaks = {}, {}
        for key, (label, _unit) in SERIES.items():
            c = chans.get(label)
            if c is None:
                continue
            vals, step = thin(c.get("values") or [])
            if not any(v is not None for v in vals):
                continue
            series[key] = vals
            fin = [v for v in (c.get("values") or []) if v is not None]
            peaks[key] = round(max(fin), 3) if fin else None
        if not series:
            continue
        n = int(s.get("n") or 0)
        sec = float(s.get("sample_sec") or 1.0)
        step = max(1, int(math.ceil(n / float(POINTS))))
        top, base = m.get("top_m"), m.get("base_m")
        stages.append({
            "n": stage_num(m.get("stage")), "label": str(m.get("stage")),
            "top_m": top, "base_m": base, "placed": top is None and base is None,
            "date": m.get("date") or "", "start": m.get("start_time") or "",
            "clock_chart": bool(m.get("clock_chart")),
            "minutes": round(n * sec / 60.0, 1), "step_s": step * sec,
            "page": s.get("page"), "source": s.get("source", ""),
            "series": series, "peaks": peaks,
            "notes": [w for w in (m.get("warnings") or [])],
        })
    stages.sort(key=lambda x: x["n"])
    well = find_well(wa, uwis)
    return {
        "v": 1,
        "well": {"wa": well.get("wa") or (str(wa) if wa else ""), "name": well.get("n", ""),
                 "uwi": (well.get("u") or [next(iter(uwis), "")])[0], "prov": well.get("prov", ""),
                 "td_m": well.get("td"), "tvd_m": well.get("tvd"), "lateral_m": well.get("ll"),
                 "year": well.get("yr"), "stages_filed": well.get("st"),
                 "lat": well.get("la"), "lon": well.get("lo")},
        "file": source_file or payload.get("file", ""),
        "units": {k: u for k, (_l, u) in SERIES.items()},
        "stages": stages,
        "logs": [],
        "notes": list(payload.get("notes") or []),
    }


def update_index(index_path, entry):
    idx = []
    if os.path.exists(index_path):
        try:
            idx = json.load(open(index_path)).get("wells", [])
        except (OSError, ValueError):
            idx = []
    idx = [w for w in idx if w.get("wa") != entry["wa"]] + [entry]
    idx.sort(key=lambda w: (w.get("prov", ""), str(w.get("wa", ""))))
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    json.dump({"v": 1, "wells": idx}, open(index_path, "w"), separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("payload")
    ap.add_argument("--wa", help="the well's WA number (BC) to look up on the map")
    ap.add_argument("--file", default="", help="the report's file name, for the page")
    ap.add_argument("-o", "--out", help="where to write the well JSON")
    ap.add_argument("--index", help="the wells index to add this well to")
    a = ap.parse_args()
    payload = json.load(open(a.payload))
    doc = build(payload, a.wa, a.file)
    out = a.out or os.path.join(_HERE, "web", "public", "data", "wells",
                                f"{doc['well']['wa'] or 'well'}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(doc, open(out, "w"), separators=(",", ":"))
    measured = sum(1 for s in doc["stages"] if not s["placed"])
    print(f"{out}: {len(doc['stages'])} stages, {measured} with a printed depth, "
          f"{os.path.getsize(out) / 1024:.0f} KB")
    if a.index:
        update_index(a.index, {"wa": doc["well"]["wa"], "name": doc["well"]["name"],
                               "uwi": doc["well"]["uwi"], "prov": doc["well"]["prov"],
                               "stages": len(doc["stages"]), "measured": measured,
                               "year": doc["well"]["year"], "file": doc["file"]})
        print(f"indexed in {a.index}")


if __name__ == "__main__":
    main()
