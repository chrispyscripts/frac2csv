"""Ground-motion monitoring reports (GMMR) filed with the BCER, as data.

    python3 web/scripts/build_gmmr.py [--folder DIR ...]

Where a pad is fracked inside the BCER's seismic monitoring areas the operator
runs accelerometers at the pad and files a ground-motion monitoring report per
well (eLibrary file kind GMMR: a PDF, sometimes a CSV and the triggering
waveform as miniSEED). Two vendors write them here:

  Spectraseis (ESG) -- stimulation window, felt reports (often naming the well
    and stage being pumped), and every trigger: station, UTC time, Mw and peak
    acceleration on N/E/Z, repeated on a page per trigger.
  Nanometrics -- deployment location, monitoring period, data availability,
    trigger counts against the BCER threshold, the largest real triggers.

Peak ground acceleration is compared with the BCER reporting threshold
(0.008 g = 0.8 %g). A trigger with a time is matched to the stage pumping on
that pad then, with build_seismic.py's stage windows.

Writes web/public/data/seismic/gmmr.json: {WA: report}.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta

import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_seismic as bs  # noqa: E402

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "data")
THRESHOLD_PCT_G = 0.8


def text_of(path):
    return "\n".join(p.get_text() for p in fitz.open(path))


def spectraseis(t):
    flat = re.sub(r"\s+", " ", t)
    rep = {"vendor": "Spectraseis (ESG)"}
    m = re.search(r"Stimulation took place from (\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)", flat)
    if m:
        rep["window"] = [m.group(1), m.group(2)]
    m = re.search(r"(\d+) events? (?:were|was) reported by NRCan", flat)
    if m:
        rep["nrcan_events"] = int(m.group(1))
    felt = [s.strip(" −-") for s in re.split(r"−", flat) if "felt" in s.lower()]
    rep["felt"] = [s for s in felt if s and not s.lower().startswith("0 events yielded")][:4]
    trig = []
    for m in re.finditer(r"(FBA\d+)?\s*\d*\s*Mw:\s*([^\s]+)\s*(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC\s*"
                         r"Max %g = ([\d.]+)\s*Max %g = ([\d.]+)\s*Max %g = ([\d.]+)", flat):
        trig.append({"station": m.group(1) or "FBA", "t": m.group(3).replace(" ", "T") + "Z",
                     "mw": None if m.group(2).upper() in ("N/A", "NA") else m.group(2),
                     "pga_pct_g": max(float(m.group(4)), float(m.group(5)), float(m.group(6)))})
    rep["triggers"] = trig
    return rep


def nanometrics(t):
    flat = re.sub(r"[\u200b\s]+", " ", t)
    rep = {"vendor": "Nanometrics"}
    m = re.search(r"Monitoring period: (\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)", flat)
    if m:
        rep["window"] = [m.group(1), m.group(2)]
    m = re.search(r"Location: ([\d.]+)°N, ([\d.]+)°W", flat)
    if m:
        rep["sensor"] = [float(m.group(1)), -float(m.group(2))]
    for key, pat in (("availability_pct", r"Data availability on all channels: (\d+)%"),
                     ("n_triggers", r"Number of triggers above the configured threshold: (\d+)"),
                     ("over_threshold", r"Number of real (?:events|triggers) exceeding BCOGC threshold of 0\.008g: (\d+)")):
        m = re.search(pat, flat)
        if m:
            rep[key] = int(m.group(1))
    rep["largest_pga_pct_g"] = [round(float(x) * 100, 4) for x in re.findall(r"Real event with a PGA of ([\d.]+)g", flat)]
    rep["triggers"] = []
    rep["felt"] = []
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--folder", action="append")
    a = ap.parse_args()
    folders = a.folder or [os.path.join(_DATA, "..", "..", "..", "..", "exports", "bc-gundy-cluster"),
                           os.path.expanduser("~/BCER-eLibrary")]
    files = sorted({f for d in folders for f in glob.glob(os.path.join(d, "**", "*_GMMR_*.[Pp][Dd][Ff]"), recursive=True)})
    stages = bs.stage_windows()
    by_wa = {}
    for s in stages:
        by_wa.setdefault(s[2], []).append(s)
    pads = {}
    for p in json.load(open(os.path.join(_DATA, "region", "index.json")))["pads"]:
        for w in json.load(open(os.path.join(_DATA, "region", "pads", f"{p['id']}.json")))["wells"]:
            pads[str(w["well"]["wa"]).zfill(5)] = p["id"]
    pad_wells = {}
    for wa, pid in pads.items():
        pad_wells.setdefault(pid, []).append(wa)
    out, seen = {}, set()
    for f in files:
        wa = re.match(r"(\d{5})_", os.path.basename(f)).group(1)
        t = text_of(f)
        rep = spectraseis(t) if "Spectraseis" in t else nanometrics(t) if "Nanometrics" in t else \
            {"vendor": "unstated", "triggers": [], "felt": [re.sub(r"\s+", " ", t).strip()[:240]]}
        rep["file"] = os.path.basename(f)
        rep["same_as"] = None
        h = hashlib.md5(json.dumps({k: rep.get(k) for k in ("window", "triggers")}, sort_keys=True).encode()).hexdigest()
        rep["pad_report"] = h          # wells on one pad file the same report: the UI shows it once
        peak = max([x["pga_pct_g"] for x in rep["triggers"]] + rep.get("largest_pga_pct_g", []) or [0])
        rep["peak_pct_g"] = peak or None
        rep["over_threshold"] = rep.get("over_threshold", sum(1 for x in rep["triggers"] if x["pga_pct_g"] >= THRESHOLD_PCT_G))
        # which stage on this pad was pumping when each trigger fired
        cands = [s for w in pad_wells.get(pads.get(wa), [wa]) for s in by_wa.get(w, [])]
        for x in rep["triggers"]:
            ti = datetime.strptime(x["t"], "%Y-%m-%dT%H:%M:%SZ")
            live = [s for s in cands if s[0] <= ti <= s[1]]
            near = [s for s in cands if s[1] < ti <= s[1] + timedelta(hours=bs.TAIL_H)]
            x["pumping"] = [[s[2], s[3]] for s in live][:3]
            if not live and near:
                s = max(near, key=lambda s: s[1])
                x["after"] = [s[2], s[3], round((ti - s[1]).total_seconds() / 60)]
        out[wa] = rep
        seen.add(h)
    json.dump(out, open(os.path.join(_DATA, "seismic", "gmmr.json"), "w"), separators=(",", ":"))
    trig = {json.dumps(x["t"]) + r["pad_report"] for r in out.values() for x in r["triggers"]}
    over = sum(1 for r in out.values() if r["over_threshold"])
    print(f"{len(out)} wells with a GMMR ({len(seen)} distinct reports); {len(trig)} distinct triggers; "
          f"{over} reports with a trigger over {THRESHOLD_PCT_G} %g; "
          f"{sum(1 for r in out.values() for x in r['triggers'] if x.get('pumping'))} triggers during a stage")


if __name__ == "__main__":
    main()
