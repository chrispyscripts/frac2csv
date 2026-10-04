"""Stratum's region: every fractured, surveyed BC well within a radius, as pads.

    python3 web/scripts/build_region.py [--radius 100] [--lat 56.794 --lon -122.115]

Everything here is the BC Energy Regulator's public bulk data (IRIS, Open
Government Licence) -- no PDFs, no Lab run:

  wells_and_attribute_data   surface location, operator, field, formation, KB
  dir_survey                 the directional survey (the deepest drilling event)
  hydraulic_fracture         one row per frac stage: interval, pressures, rate,
                             fluid and proppant, as filed

A well is in the region when its surface is within the radius and it has both a
survey and frac stages. Wells are grouped into pads by surface location (heads
within PAD_LINK_M of each other). The Gundy cluster keeps its own eight pads and
the richer files built for it (Lab summaries, gamma); every other well is pad
`region-<lowest WA on the pad>`.

Writes, under web/public/data/:
  region/index.json        the pad list the 3D view chooses an area from
  region/pads/<id>.json    one pad in the underground view's shape
  pads/region.json         the map's pad set (plan-view paths), Gundy included
  wells/<WA>.json          for wells that have none yet: identity, pad and the
                           BCER stage summaries (curves come later, from the
                           Lab's CSVs via stages_from_csv.py)
"""
import argparse
import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_WEB, "public", "data")
_IRIS = os.path.join(_WEB, "..", "..", "bcer-iris-2026-09-10")
PAD_LINK_M = 80          # wellheads on one pad sit metres apart; separate pads, hundreds
TRAJ_POINTS = 120        # survey stations kept per well for the 3D view
PATH_POINTS = 24         # plan-view vertices per well for the map
HEEL_INC = 80.0          # first station at or past this inclination is the heel


def km_from(lat0, lon0):
    c = math.cos(math.radians(lat0))
    return lambda la, lo: math.hypot((la - lat0) * 111.32, (lo - lon0) * 111.32 * c)


def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def iris_date(s):
    """'16-FEB-19' -> '2019-02-16'."""
    try:
        return datetime.strptime(s.strip(), "%d-%b-%y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def thin(seq, n):
    if len(seq) <= n:
        return list(seq)
    step = (len(seq) - 1) / float(n - 1)
    return [seq[round(i * step)] for i in range(n)]


def compact_loc(s):
    """'C-059-A/094-B-16' -> 'C-59-A/94-B-16'; DLS kept as filed."""
    return "/".join("-".join(p.lstrip("0") or "0" for p in part.split("-")) for part in (s or "").split("/"))


def read_wells(lat0, lon0, radius):
    dist = km_from(lat0, lon0)
    out = {}
    with open(os.path.join(_IRIS, "wells_and_attribute_data-New-BC.csv"), errors="ignore") as f:
        for r in csv.DictReader(f):
            wa = (r.get("license_id") or "").strip()
            la, lo = num(r.get("surface_latitude")), num(r.get("surface_longitude"))
            if not wa.isdigit() or la is None or lo is None or dist(la, lo) > radius:
                continue
            out[wa.zfill(5)] = r
    return out


def read_surveys(was):
    by = defaultdict(lambda: defaultdict(list))
    with open(os.path.join(_IRIS, "dir_survey.csv"), errors="ignore") as f:
        next(f)                                   # the "DIR_SURVEY FILE" banner
        for r in csv.DictReader(f):
            wa = r["WA NUM"].strip().zfill(5)
            if wa in was:
                by[wa][r["Drilling Event"].strip()].append(r)
    out = {}
    for wa, events in by.items():
        rows = max(events.values(), key=lambda rs: max(num(x["Measured Depth (m)"]) or 0 for x in rs))
        st = []
        for x in rows:
            md = num(x["Measured Depth (m)"])
            if md is None:
                continue
            st.append((md, num(x["Inclination (deg)"]) or 0.0, num(x["TV Depth (m)"]),
                       num(x["North South (m)"]), num(x["East West (m)"])))
        st.sort()
        clean = [(md, inc, tvd if tvd is not None else (md if md == 0 else None),
                  ns if ns is not None else 0.0, ew if ew is not None else 0.0) for md, inc, tvd, ns, ew in st]
        clean = [s for s in clean if s[2] is not None]
        if len(clean) >= 5:
            out[wa] = clean
    return out


def read_fracs(was):
    by = defaultdict(lambda: defaultdict(dict))
    with open(os.path.join(_IRIS, "hydraulic_fracture.csv"), errors="ignore") as f:
        for r in csv.DictReader(f):
            wa = r["WA NUM"].strip().zfill(5)
            if wa not in was:
                continue
            ev = (r["DRILLNG EVENT"].strip(), r["COMPLTN EVENT"].strip())
            n = r["FRAC STAGE NUM"].strip()
            by[wa][ev].setdefault(n, r)
    out = {}
    for wa, events in by.items():
        ev, rows = max(events.items(), key=lambda kv: len(kv[1]))
        stages = []
        for n, r in rows.items():
            prop = [num(r.get(f"PROPPANT TYPE{i} PLACED (t)")) or num(r.get(f"PROPPANT TYPE{i} PUMPED (t)")) for i in range(1, 5)]
            types = [r.get(f"PROPPANT TYPE{i}", "").strip() for i in range(1, 5)]
            stages.append({
                "n": int(num(n) or 0), "label": n, "date": iris_date(r["COMPLTN DATE"]),
                "start": (r.get("FRAC START TIME") or "").strip()[:8],    # local, as filed
                "top_m": num(r["COMPLTN TOP DEPTH (m)"]), "base_m": num(r["COMPLTN BASE DEPTH (m)"]),
                "proppant_t": round(sum(p for p in prop if p), 2) if any(prop) else None,
                "proppant_types": ", ".join(t for t, p in zip(types, prop) if t and p) or None,
                "avg_rate_m3_min": num(r["AVG RATE (m3/min)"]),
                "avg_pressure_mpa": num(r["AVG TREATING PRESSURE (MPa)"]),
                "max_pressure_mpa": num(r["MAX TREATING PRESSURE (MPa)"]),
                "breakdown_mpa": num(r["BREAK DOWN PRESSURE (MPa)"]),
                "isip_mpa": num(r["INST SHUT IN PRESSURE (MPa)"]),
                "fluid_m3": num(r["TOTAL FLUID PUMPED (m3)"]),
                "base_fluid": r["BASE FLUID"].strip() or None,
                "source": "BCER hydraulic fracture"})
        stages.sort(key=lambda s: (s["n"], s["label"]))
        out[wa] = {"stages": stages, "events": len(events)}
    return out


def pads_by_surface(wells):
    """Single-link groups of wellheads within PAD_LINK_M."""
    cell = PAD_LINK_M / 111320.0
    grid = defaultdict(list)
    for wa, w in wells.items():
        grid[(int(w["lat"] / cell), int(w["lon"] / (cell * 2)))].append(wa)
    parent = {wa: wa for wa in wells}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for (gy, gx), members in grid.items():
        near = [b for dy in (-1, 0, 1) for dx in (-1, 0, 1) for b in grid.get((gy + dy, gx + dx), [])]
        for a in members:
            wa_ = wells[a]
            for b in near:
                if a < b:
                    wb = wells[b]
                    d = math.hypot((wa_["lat"] - wb["lat"]) * 111320,
                                   (wa_["lon"] - wb["lon"]) * 111320 * math.cos(math.radians(wa_["lat"])))
                    if d <= PAD_LINK_M:
                        parent[find(a)] = find(b)
    groups = defaultdict(list)
    for wa in wells:
        groups[find(wa)].append(wa)
    return list(groups.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lat", type=float, default=56.794)
    ap.add_argument("--lon", type=float, default=-122.115)
    ap.add_argument("--radius", type=float, default=100.0, help="km")
    a = ap.parse_args()

    attrs = read_wells(a.lat, a.lon, a.radius)
    surveys = read_surveys(set(attrs))
    fracs = read_fracs(set(attrs))
    keep = sorted(set(surveys) & set(fracs))
    print(f"{len(attrs)} wells within {a.radius:g} km; {len(keep)} with a survey and frac stages")

    ug = json.load(open(os.path.join(_DATA, "underground.json")))
    gundy_pad = {str(w["well"]["wa"]).zfill(5): p for p in ug["pads"] for w in p["wells"]}
    gundy_set = json.load(open(os.path.join(_DATA, "pads", "gundy.json")))

    wells = {}
    for wa in keep:
        r, st, fr = attrs[wa], surveys[wa], fracs[wa]
        heel = next((s[0] for s in st if s[1] >= HEEL_INC), None)
        td = max(num(r.get("well_total_depth")) or 0, st[-1][0])
        years = [s["date"][:4] for s in fr["stages"] if s["date"]]
        lic = (r.get("licensee") or r.get("operator") or "").strip()
        wells[wa] = {
            "wa": wa, "name": " ".join(r["well_name"].split()), "uwi": r.get("wellbore_uwi", ""), "prov": "BC",
            "td_m": round(td, 1), "tvd_m": round(max(s[2] for s in st), 1),
            "lateral_m": round(td - heel) if heel else None, "heel_md": round(heel, 1) if heel else None,
            "year": int(min(years)) if years else None, "stages_filed": len(fr["stages"]),
            "lat": num(r["surface_latitude"]), "lon": num(r["surface_longitude"]),
            "elev_m": num(r.get("kb_elevation")) or num(r.get("ground_elevation")),
            "surface_loc": r.get("surface_uwi", ""), "field": (r.get("field_name") or "").title(),
            "formation": r.get("formation") or r.get("projected_formation") or "", "operator": lic,
            "status": r.get("well_status", ""), "cum_gas_e3m3": num(r.get("cum_gas_volume")),
            "refracs": fr["events"] - 1}

    # pads: Gundy's eight as built, everything else grouped by surface
    others = {wa: w for wa, w in wells.items() if wa not in gundy_pad}
    pads = []
    for members in pads_by_surface(others):
        members.sort()
        ws = [others[m] for m in members]
        lead = ws[0]
        pid = f"region-{members[0]}"
        name = " ".join(x for x in (lead["field"], compact_loc(lead["surface_loc"])) if x) or f"Pad {members[0]}"
        pads.append({"id": pid, "name": name, "set": "region",
                     "lat": sum(w["lat"] for w in ws) / len(ws), "lon": sum(w["lon"] for w in ws) / len(ws),
                     "members": members})

    # two pads in one legal subdivision would share a name: number the later ones
    seen = defaultdict(int)
    for p in sorted(pads, key=lambda p: p["id"]):
        seen[p["name"]] += 1
        if seen[p["name"]] > 1:
            p["name"] = f"{p['name']} ({seen[p['name']]})"

    os.makedirs(os.path.join(_DATA, "region", "pads"), exist_ok=True)
    index, map_pads, made = [], [], 0
    have_well_file = {f[:-5] for f in os.listdir(os.path.join(_DATA, "wells")) if f[:-5].isdigit()}

    def curves_in(wa):
        if wa not in have_well_file:
            return 0
        try:
            d = json.load(open(os.path.join(_DATA, "wells", f"{wa}.json")))
        except ValueError:
            return 0
        return sum(1 for s in d.get("stages") or [] if s.get("series"))

    def plan_path(w, t):
        c = math.cos(math.radians(w["lat"]))
        pts = list(zip(t["ns"], t["ew"]))
        return [[round(w["lon"] + ew / (111320.0 * c), 6), round(w["lat"] + ns / 111320.0, 6)] for ns, ew in thin(pts, PATH_POINTS)]

    for p in pads:
        rows = []
        for wa in p["members"]:
            w, st, fr = wells[wa], surveys[wa], fracs[wa]
            kept = thin(st, TRAJ_POINTS)
            t = {"md": [round(s[0], 1) for s in kept], "tvd": [round(s[2], 1) for s in kept],
                 "ns": [round(s[3], 1) for s in kept], "ew": [round(s[4], 1) for s in kept]}
            intervals = [{"n": s["n"], "top_m": s["top_m"], "base_m": s["base_m"], "date": s["date"],
                          "source": "BCER hydraulic fracture"} for s in fr["stages"] if s["top_m"] is not None]
            rows.append({"well": w, "trajectory": t, "stages": fr["stages"], "depth_intervals": intervals})
            curves = curves_in(wa)
            map_w = {"wa": wa, "name": w["name"], "uwi": w["uwi"], "td": w["td_m"], "tvd": w["tvd_m"],
                     "lateral": w["lateral_m"], "lat": w["lat"], "lon": w["lon"], "stations": len(st),
                     "path": plan_path(w, t), "stages": curves, "ports": len(intervals), "logs": 0,
                     "depth_intervals": len(intervals), "summaries": len(fr["stages"]), "file": None}
            p.setdefault("map_wells", []).append(map_w)
            # a light well file for wells the Lab has not reached; existing files
            # keep their curves and only learn which pad they now belong to
            path_w = os.path.join(_DATA, "wells", f"{wa}.json")
            if wa in have_well_file:
                doc = json.load(open(path_w))
                doc["pad"] = {"id": p["id"], "name": p["name"], "lat": p["lat"], "lon": p["lon"]}
                doc["well"] = {**w, **{k: v for k, v in (doc.get("well") or {}).items() if v is not None}}
            else:
                doc = {"v": 2, "well": w, "pad": {"id": p["id"], "name": p["name"], "lat": p["lat"], "lon": p["lon"]},
                       "file": None, "units": {}, "stages": [], "logs": [], "notes": [],
                       "bcer_stages": [{"start": "", **s, "placed": False, "clock_chart": False, "minutes": 0,
                                        "step_s": 0, "page": None, "series": {}, "peaks": {},
                                        "notes": ["filed with the BCER; treatment curves await the Lab export"]}
                                       for s in fr["stages"]]}
                made += 1
            json.dump(doc, open(path_w, "w"), separators=(",", ":"))
        json.dump({"id": p["id"], "name": p["name"], "set": "region", "lat": p["lat"], "lon": p["lon"], "wells": rows},
                  open(os.path.join(_DATA, "region", "pads", f"{p['id']}.json"), "w"), separators=(",", ":"))
        ws = [wells[m] for m in p["members"]]
        years = [w["year"] for w in ws if w["year"]]
        index.append({"id": p["id"], "name": p["name"], "set": "region", "lat": round(p["lat"], 6), "lon": round(p["lon"], 6),
                      "wells": len(ws), "field": ws[0]["field"], "operator": ws[0]["operator"],
                      "years": [min(years), max(years)] if years else None,
                      "curves": sum(1 for m in p["map_wells"] if m["stages"])})
        map_pads.append({"id": p["id"], "name": p["name"], "lat": p["lat"], "lon": p["lon"], "wells": p["map_wells"]})

    # Gundy's pads: the underground file split per pad, and its map entries as built
    for gp in ug["pads"]:
        json.dump({**gp, "set": "gundy"}, open(os.path.join(_DATA, "region", "pads", f"{gp['id']}.json"), "w"), separators=(",", ":"))
        ws = [x["well"] for x in gp["wells"]]
        sp = next(p for p in gundy_set["pads"] if p["id"] == gp["id"])
        index.append({"id": gp["id"], "name": gp["name"], "set": "gundy", "lat": gp["lat"], "lon": gp["lon"],
                      "wells": len(ws), "field": "Gundy", "operator": "Tourmaline Oil Corp.",
                      "years": [min(w["year"] for w in ws), max(w["year"] for w in ws)],
                      "curves": sum(1 for w in sp["wells"] if w.get("stages"))})
        map_pads.append(sp)

    index.sort(key=lambda p: (p["lat"], p["lon"]))
    json.dump({"v": 1, "center": [a.lat, a.lon], "radius_km": a.radius, "wells": len(wells),
               "source": "BCER IRIS bulk tables (dir_survey, hydraulic_fracture, wells_and_attribute_data), 2026-09-10",
               "pads": index}, open(os.path.join(_DATA, "region", "index.json"), "w"), separators=(",", ":"))
    json.dump({"v": 1, "set": "region", "pads": map_pads},
              open(os.path.join(_DATA, "pads", "region.json"), "w"), separators=(",", ":"))
    sizes = sorted(len(p["members"]) for p in pads)
    print(f"{len(pads)} region pads + {len(ug['pads'])} Gundy pads; wells per pad median {sizes[len(sizes) // 2]}, "
          f"max {sizes[-1]}; {made} new well files; "
          f"{sum(p['curves'] for p in index)} wells with treatment curves")


if __name__ == "__main__":
    main()
