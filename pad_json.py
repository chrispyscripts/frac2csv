"""Stratum's pad files: a pad's wells with their real trajectories.

    python3 pad_json.py --cluster ../batch-lists/bc-cluster-2026-09-16.tsv \
        --surveys ../exports/bc-gundy-cluster/gundy-cluster-trajectories.csv \
        --surface ../exports/bc-gundy-cluster/surface.csv --pad-set gundy

Writes web/public/data/pads/<set>.json (the pads, each well's surface
location and a thinned plan-view path for the map) and, for every well,
web/public/data/wells/<WA>.json in well_json's shape with two additions:

  pad         {id, name, lat, lon}
  trajectory  {md, inc, az, tvd, ns, ew, lat, lon} — the directional survey
              stations (BCER IRIS DIR_SURVEY), at most TRAJ_POINTS of them,
              with each station's latitude/longitude from the surface
              location and the north/east offsets

`stages` and `logs` are left as they are when the well file already exists
(the Lab's CSVs fill stages; logs_from_las.py fills logs), so this can be
re-run after either.
"""
import argparse
import csv
import json
import math
import os
import re

import well_json

_HERE = os.path.dirname(os.path.abspath(__file__))
TRAJ_POINTS = 400
PATH_POINTS = 60


def dms(raw):
    """BCER's 'DDMMSSss' -> decimal degrees ('56475958' -> 56.7998...)."""
    s = str(raw or "").strip()
    if not s.isdigit() or len(s) < 7:
        return None
    s = s.zfill(9) if len(s) > 8 else s.zfill(8)
    d, m, sec = int(s[:-6]), int(s[-6:-4]), int(s[-4:]) / 100.0
    return d + m / 60.0 + sec / 3600.0


def thin(rows, n):
    if len(rows) <= n:
        return rows
    step = len(rows) / float(n)
    picked = [rows[int(i * step)] for i in range(n)]
    if picked[-1] is not rows[-1]:
        picked.append(rows[-1])
    return picked


def latlon(lat0, lon0, ns, ew):
    return (lat0 + ns / 111320.0,
            lon0 + ew / (111320.0 * math.cos(math.radians(lat0))))


def build(cluster, surveys, surface, pad_set, set_name=None):
    label = set_name or pad_set.title()
    pads = {}
    wells = {}
    for r in cluster:
        wa = str(r["WA"]).zfill(5)
        pid = f"{pad_set}-{int(r['PAD']):02d}"
        pads.setdefault(pid, {"id": pid, "name": f"{label} pad {int(r['PAD'])}",
                              "lat": float(r["PAD_LAT"]), "lon": float(r["PAD_LON"]), "wells": []})
        wells[wa] = {"pad": pid, "row": r}
    stations = {}
    for s in surveys:
        wa = str(s["WA"]).zfill(5)
        if wa in wells:
            stations.setdefault(wa, []).append(s)
    out_wells = []
    for wa, w in wells.items():
        r = w["row"]
        sf = surface.get(wa, {})
        lat0 = dms(sf.get("lat_raw")) or float(r["PAD_LAT"])
        lon0 = dms(sf.get("lon_raw"))
        lon0 = -lon0 if lon0 else float(r["PAD_LON"])          # west
        st = sorted(stations.get(wa, []), key=lambda s: (s["DRILLING_EVENT"], float(s["MD_M"] or 0)))
        # the deepest drilling event is the well as it is today
        if st:
            last = max(s["DRILLING_EVENT"] for s in st)
            st = [s for s in st if s["DRILLING_EVENT"] == last]
        st = thin(st, TRAJ_POINTS)
        traj = {"md": [], "inc": [], "az": [], "tvd": [], "ns": [], "ew": [], "lat": [], "lon": []}
        for s in st:
            try:
                md, inc, az = float(s["MD_M"]), float(s["INC_DEG"] or 0), float(s["AZ_DEG"] or 0)
                tvd = float(s["TVD_M"]) if s["TVD_M"] else None
                ns = float(s["NS_M"]) if s["NS_M"] else 0.0
                ew = float(s["EW_M"]) if s["EW_M"] else 0.0
            except ValueError:
                continue
            la, lo = latlon(lat0, lon0, ns, ew)
            traj["md"].append(round(md, 1)); traj["inc"].append(round(inc, 2)); traj["az"].append(round(az, 2))
            traj["tvd"].append(None if tvd is None else round(tvd, 1)); traj["ns"].append(round(ns, 1)); traj["ew"].append(round(ew, 1))
            traj["lat"].append(round(la, 6)); traj["lon"].append(round(lo, 6))
        path = [[lo, la] for la, lo in thin(list(zip(traj["lat"], traj["lon"])), PATH_POINTS)]
        rec = well_json.find_well(wa, [r.get("UWI")])
        td = float(r["TD_M"]) if r.get("TD_M") else (traj["md"][-1] if traj["md"] else None)
        tvd_m = max((v for v in traj["tvd"] if v is not None), default=None) or rec.get("tvd")
        # lateral length: measured depth beyond the point where inclination passes 80 degrees
        heel_md = next((m for m, i in zip(traj["md"], traj["inc"]) if i >= 80), None)
        lateral = round(td - heel_md) if (td and heel_md) else rec.get("ll") or (r.get("LATERAL_M") or None)
        well = {"wa": wa, "name": r["WELL"], "uwi": r.get("UWI", ""), "prov": "BC",
                "td_m": td, "tvd_m": tvd_m, "lateral_m": lateral, "heel_md": heel_md,
                "year": rec.get("yr"), "stages_filed": rec.get("st"),
                "lat": lat0, "lon": lon0, "elev_m": float(sf["elev"]) if sf.get("elev") else None,
                "surface_loc": sf.get("loc", "")}
        path_w = os.path.join(_HERE, "web", "public", "data", "wells", f"{wa}.json")
        existing = {}
        if os.path.exists(path_w):
            try:
                existing = json.load(open(path_w))
            except (OSError, ValueError):
                existing = {}
        # everything another builder put here (stages, logs, engineering
        # tables) survives; this one owns the well record and the trajectory
        doc = dict(existing)
        doc.update({"v": 2, "well": well, "pad": {k: pads[w["pad"]][k] for k in ("id", "name", "lat", "lon")},
                    "file": r.get("FILE", ""), "units": existing.get("units") or {k: u for k, (_l, u) in well_json.SERIES.items()},
                    "trajectory": traj, "stages": existing.get("stages", []), "logs": existing.get("logs", []),
                    "notes": existing.get("notes", [])})
        os.makedirs(os.path.dirname(path_w), exist_ok=True)
        json.dump(doc, open(path_w, "w"), separators=(",", ":"))
        pads[w["pad"]]["wells"].append({"wa": wa, "name": r["WELL"], "uwi": r.get("UWI", ""), "td": td,
                                        "tvd": tvd_m, "lateral": lateral, "lat": lat0, "lon": lon0,
                                        "stations": len(traj["md"]), "path": path,
                                        # stages with treatment curves; the BCER skeleton (depths only) is counted apart
                                        "stages": sum(1 for s in existing.get("stages", []) if s.get("series")),
                                        "ports": len(existing.get("stages", [])), "logs": len(existing.get("logs", [])),
                                        # the BCER completion intervals the engineering import puts on the well
                                        "depth_intervals": len(existing.get("depth_intervals") or []),
                                        "summaries": len(existing.get("engineering_stages") or []),
                                        "file": r.get("FILE", "")})
        out_wells.append(wa)
        well_json.update_index(os.path.join(_HERE, "web", "public", "data", "wells", "index.json"),
                               {"wa": wa, "name": r["WELL"], "uwi": r.get("UWI", ""), "prov": "BC",
                                "stages": sum(1 for s in existing.get("stages", []) if s.get("series")),
                                "ports": len(existing.get("stages", [])),
                                "measured": sum(1 for s in existing.get("stages", []) if not s.get("placed")),
                                "year": rec.get("yr"), "file": r.get("FILE", ""), "pad": w["pad"], "trajectory": True})
    for p in pads.values():
        p["wells"].sort(key=lambda x: x["name"])
    return {"v": 1, "set": pad_set, "pads": sorted(pads.values(), key=lambda p: p["id"])}, out_wells


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cluster", required=True, help="the pad/well TSV (PAD, WA, WELL, UWI, TD_M, PAD_LAT, PAD_LON, FILE, PATH)")
    ap.add_argument("--surveys", required=True, help="the survey stations CSV (PAD, WA, ..., MD_M, INC_DEG, AZ_DEG, TVD_M, NS_M, EW_M)")
    ap.add_argument("--surface", help="CSV of WA, lat_raw, lon_raw, elev, loc (BCER wells table extract)")
    ap.add_argument("--pad-set", default="pads")
    ap.add_argument("--set-name", help="how the set reads on the site (default: the pad-set, title-cased)")
    a = ap.parse_args()
    cluster = list(csv.DictReader(open(a.cluster), delimiter="\t"))
    surveys = list(csv.DictReader(open(a.surveys)))
    surface = {}
    if a.surface and os.path.exists(a.surface):
        surface = {str(r["WA"]).zfill(5): r for r in csv.DictReader(open(a.surface))}
    doc, wells = build(cluster, surveys, surface, a.pad_set, a.set_name)
    out = os.path.join(_HERE, "web", "public", "data", "pads", f"{a.pad_set}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(doc, open(out, "w"), separators=(",", ":"))
    # the sets the site knows about, for the map and the pad page
    idx_path = os.path.join(os.path.dirname(out), "index.json")
    try:
        idx = json.load(open(idx_path)).get("sets", [])
    except (OSError, ValueError):
        idx = []
    idx = [x for x in idx if x.get("set") != a.pad_set]
    idx.append({"set": a.pad_set, "file": f"{a.pad_set}.json", "pads": len(doc["pads"]), "wells": len(wells),
                "lat": sum(p["lat"] for p in doc["pads"]) / len(doc["pads"]),
                "lon": sum(p["lon"] for p in doc["pads"]) / len(doc["pads"]),
                "name": f"{a.set_name or a.pad_set.title()} cluster"})
    json.dump({"v": 1, "sets": sorted(idx, key=lambda x: x["set"])}, open(idx_path, "w"), separators=(",", ":"))
    print(f"{out}: {len(doc['pads'])} pads, {len(wells)} wells; well files in web/public/data/wells/")


if __name__ == "__main__":
    main()
