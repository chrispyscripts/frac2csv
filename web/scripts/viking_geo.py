"""The Viking set's newest wells and its wellsite geologists' comments
(build_viking.py --newpha --surveys --reports --descriptions).

  add_new_wells   the wells of a Photon export with no survey of its own (the
                  newest, 2024-2026), placed by its surface coordinates, their
                  paths from their survey reports read by the Lab's Directional
                  Survey tool (survey_tool), north and east of the surface as
                  the reports give them (true north)
  attach_comments each well's comments: the sample descriptions of its
                  geologist's report (geology_tool), its landing point and
                  bottom hole, and what the geologist wrote along its mud-log
                  printouts (mudlog_pdf parts={"descriptions"}): {top, base,
                  text, kind ("description" | "note"), rocks, from ("report" |
                  "printout"), file}, by MD
  rocks_from_comments  a well with no rock type from a log's legend gets one
                  from its descriptions: in each bin, the rock the description
                  there names most of

None of this is public data: it reads files outside the repo and goes into
the set build_sk.write() makes outside it. A file is matched to its well by
the licence in its name (as the province files them).
"""
import glob
import json
import math
import os
import re
from collections import Counter

import build_sk
from build_viking import lic_key, num, parse_pha, uwi_text, utm_to_latlon

LIC_IN_NAME = re.compile(r"^\d+[.-]\w{16}_(\w+?)_SK\d+_")


def _lic_of(fn):
    m = LIC_IN_NAME.match(os.path.basename(fn))
    return lic_key(m.group(1)) if m else None


def _load(folder):
    out = {}
    for f in sorted(glob.glob(os.path.join(folder, "*.json"))):
        r = json.load(open(f))
        lic = _lic_of(r.get("file") or f)
        if r.get("ok") and lic:
            out.setdefault(lic, []).append(r)
    return out


# ---------------------------------------------------------------- the newest wells

def add_new_wells(wells, newpha, surveys_dir, rep):
    """the export's wells with a survey report, added to wells (build_sk's form)"""
    _, pha = parse_pha(newpha)
    surveys = _load(surveys_dir)
    have = {lic_key(w["key"]) for w in wells if w.get("key")}
    for p in pha:
        lic = lic_key(p.get("LICENSE"))
        if lic in have:
            rep["new export: already in the set"] += 1
            continue
        zone, e0, n0 = int(num(p.get("UTMZONE")) or 13), num(p.get("UTMX")), num(p.get("UTMY"))
        sv = [s for s in surveys.get(lic, []) if len(s.get("stations") or []) >= 2]
        if e0 is None or n0 is None or not sv:
            rep["new export: no survey report (left out)"] += 1
            continue
        s = max(sv, key=lambda s: (bool(s.get("final")), len(s["stations"])))
        lat0, lon0 = utm_to_latlon(e0, n0, zone)
        k = math.cos(math.radians(lat0))
        st = sorted(s["stations"], key=lambda x: x["md"])
        traj = {"md": [round(x["md"], 1) for x in st], "inc": [round(x["inc"], 2) for x in st],
                "az": [round(x["azi"] % 360, 2) for x in st], "tvd": [round(x["tvd"], 1) for x in st],
                "ns": [round(x["ns"], 1) for x in st], "ew": [round(x["ew"], 1) for x in st],
                "lat": [round(lat0 + x["ns"] / 111320, 6) for x in st],
                "lon": [round(lon0 + x["ew"] / (111320 * k), 6) for x in st]}
        tup = [(m, t) for m, t in zip(traj["md"], traj["tvd"])]
        heel = build_sk.heel_of(tup)
        td = max(num(p.get("TD")) or 0, traj["md"][-1])
        tops = [[r[4] or r[2], num(r[1])] for r in p["_sec"].get("WELTOPS_MD") or [] if len(r) >= 5 and num(r[1]) is not None]
        w = {"key": lic, "lat": round(lat0, 6), "lon": round(lon0, 6), "types": {}, "rock_names": {}, "notes": [],
             "logs": None, "stages": [], "depth_intervals": [], "trajectory": traj,
             "well": {"name": p.get("WELLNAME") or s.get("well") or lic, "licence": lic, "uwi": uwi_text(p.get("WELLID")) or s.get("uwi"),
                      "prov": "SK", "operator": p.get("COMPANY") or "", "formation": p.get("FORMATION") or "",
                      "status": p.get("STATUS") or "", "fluid": p.get("WELLFLUID") or "", "pool": p.get("POOL") or "",
                      "field": p.get("FIELD") or "", "spud": p.get("SPUDDATE") or "", "rig_release": p.get("RRDATE") or "",
                      "drilling_company": p.get("DRILLINGCOMPANY") or "", "tops": tops, "curves": 0, "logs": 0,
                      "vertical": False, "lat": round(lat0, 6), "lon": round(lon0, 6), "td_m": round(td, 1),
                      "tvd_m": round(max(traj["tvd"]), 1), "lateral_m": round(traj["md"][-1] - heel) if heel is not None else 0,
                      "heel_md": round(heel, 1) if heel is not None else None,
                      "year": build_sk.year_of(p.get("SPUDDATE"), p.get("RRDATE")),
                      "elev_m": num(p.get("KB")), "ground_m": num(p.get("GRD")),
                      "surface_loc": (p.get("SURFACE_UWI") or "").strip(),
                      "placed_by": "the Photon export's surface coordinates (NAD83 UTM %d)" % zone,
                      "path_from": "survey report (PDF), read by the Directional Survey tool", "path_estimated": False,
                      "stages_filed": 0}}
        wells.append(w)
        have.add(lic)
        rep["new export wells added, their paths from survey reports"] += 1
    return wells


# ---------------------------------------------------------------- comments

def _lab():
    import read_printouts
    build_sk.use_lab(read_printouts.LAB)


def _mix(text):
    _lab()
    import mudlog_pdf as M
    return M.lith_mix(text)


def attach_comments(wells, reports_dir=None, descriptions_dir=None, rep=None):
    by = {lic_key(w["key"]): w for w in wells if w.get("key")}
    if reports_dir:
        for lic, rs in _load(reports_dir).items():
            w = by.get(lic)
            if not w:
                rep["geologist's reports with no well in the set"] += len(rs)
                continue
            for r in rs:
                cm = w.setdefault("comments", [])
                for s in r.get("samples") or []:
                    if s.get("top") is None or s.get("base") is None or not s.get("text"):
                        continue
                    cm.append({"top": s["top"], "base": s["base"], "text": s["text"], "kind": "description",
                               "rocks": _mix(s["text"]), "at": "range", "from": "report", "file": r["file"]})
                for m in r.get("markers") or []:
                    if m.get("md") is None:
                        continue
                    bits = ["%s: %.1f m MD" % (m["name"], m["md"])]
                    if m.get("tvd") is not None:
                        bits.append("%.1f m TVD" % m["tvd"])
                    if m.get("ss") is not None:
                        bits.append("%.1f m SS" % m["ss"])
                    cm.append({"top": m["md"], "base": m["md"], "text": ", ".join(bits), "kind": "note",
                               "rocks": {}, "at": "range", "from": "report", "file": r["file"]})
                if not w["well"].get("tops") and r.get("tops"):
                    w["well"]["tops"] = [[t["name"], t["md"]] for t in r["tops"] if t.get("md") is not None]
                rep["wells given a geologist's report's comments"] += 1
    if descriptions_dir:
        for f in sorted(glob.glob(os.path.join(descriptions_dir, "*.json"))):
            r = json.load(open(f))
            if not r.get("ok"):
                continue
            import read_printouts
            info = read_printouts.parse_name(r["file"]) or {}
            w = by.get(lic_key(info.get("licence")))
            if not w:
                continue
            _lab()
            import mudlog_pdf as M
            # each piece sorted again by the reader as it is now (a reading made
            # before it learned a header field or a share written first)
            ds = []
            for d in r.get("descriptions") or []:
                got = M.classify_comment(d["text"])
                if got:
                    ds.append(dict(d, kind=got[0], rocks=got[1]))
            if not ds:
                continue
            w.setdefault("comments", []).extend(
                {"top": d["top"], "base": d["base"], "text": d["text"], "kind": d["kind"], "rocks": d["rocks"],
                 "at": d.get("at"), "from": "printout", "file": r["file"]} for d in ds)
            rep["wells given their printouts' comments"] += 1
    for w in wells:
        if w.get("comments"):
            w["comments"].sort(key=lambda c: (c["top"], c["base"]))
            w["well"]["comments"] = len(w["comments"])
    return wells


# ---------------------------------------------------------------- rock type from the descriptions

def _main_rock(mix):
    _lab()
    import mudlog_pdf as M
    return M.main_rock(mix)


def rocks_from_comments(wells, rep, bin_m=build_sk.BIN):
    for w in wells:
        L = w.get("logs")
        if L and (L.get("types") or {}).get("rock"):
            continue                              # a log's legend named its rocks
        des = [c for c in w.get("comments") or [] if c["kind"] == "description" and c["rocks"] and c["base"] > c["top"]]
        if not des:
            continue
        # written ranges before descriptions placed by where they sit; the report's before a printout's
        des.sort(key=lambda c: (c["from"] != "report", c.get("at") != "range", c["top"]))
        bins = {}
        for c in des:
            r = _main_rock(c["rocks"])
            if not r:
                continue
            for b in range(int(math.floor(c["top"] / bin_m)), int(math.ceil(c["base"] / bin_m))):
                bins.setdefault(b, r)
        if not bins:
            continue
        lo, hi = min(bins), max(bins)
        if L:
            l0 = int(round(L["md0"] / L["bin"]))
            n = L["n"]
            lo2, hi2 = min(lo, l0), max(hi, l0 + n - 1)
            pad_l, pad_r = l0 - lo2, hi2 - (l0 + n - 1)
            for k in list(L["types"]):
                L["types"][k] = [None] * pad_l + L["types"][k] + [None] * pad_r
            L["md0"], L["n"] = lo2 * bin_m, hi2 - lo2 + 1
            L["types"]["rock"] = [bins.get(b) for b in range(lo2, hi2 + 1)]
        else:
            w["logs"] = L = {"bin": bin_m, "md0": lo * bin_m, "n": hi - lo + 1, "src": [],
                             "types": {"rock": [bins.get(b) for b in range(lo, hi + 1)]}}
        L.setdefault("src", []).append({"log": "descriptions", "from": lo * bin_m, "to": (hi + 1) * bin_m, "lith": True})
        w.setdefault("rock_names", {}).update({r: r.capitalize() for r in set(bins.values())})
        w.setdefault("notes", []).append("rock type from the written sample descriptions: in each stretch, the rock its description names most of")
        rep["wells given a rock type from their descriptions"] += 1
    return wells
