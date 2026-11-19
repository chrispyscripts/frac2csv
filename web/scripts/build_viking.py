#!/usr/bin/env python3
"""Viking wells for FracView's Saskatchewan set, from a Photon well export and
the province's frac data.

Like build_sk.py, none of this is public data: it reads files outside the repo
and writes to a folder outside it (default ~/dev/fracview-sk), which the local
server mounts at /data/sk/ (scripts/serve.py --mount).

Reads
  SK        the Saskatchewan set build_sk.py made from the WellSight logs
            (default ~/dev/fracview-sk-wellsight)
  PHA       a Photon Systems ASCII export (.pha): one WELL line per wellbore
            (licence, UWI, operator, KB, TD, NAD83 UTM and lat/lon of the
            surface and the bottom hole, status, dates ...), then its sections:
            DIR_XYZ (the survey: east and north offsets from the surface in
            metres, TVD, inclination, azimuth), WELTOPS_MD (tops by MD) and
            STAGES (frac stage depths)
  FRAC      the frac data, one row per stage (UWI, stage, top MD, start and end,
            breakdown, ISIP, treating pressures, rate, fluid, N2, proppants);
            its second row holds the units
  PRINTOUTS (optional) printout readings, one JSON per log, made by
            read_printouts.py: curves and rocks read off a log's PDF

Writes OUT/ as build_sk.py does (index.json, pads.json, pads/, wells/).

A well in the export with a survey joins the set. Where the WellSight set has
the same licence, the export's survey and surface replace the path build_sk.py
drew (some of them estimated from the depths the log states) and the well keeps
its logs. Each well's path is the export's stations: their offsets and TVD as
given, and the measured depth between two stations the minimum-curvature arc
through them. Its stages are the frac data's, each at its top MD.

Usage:
  python3 -I web/scripts/build_viking.py --pha EXPORT.pha --frac FRAC.csv
"""
import argparse
import csv
import glob
import json
import math
import os
import re
import shlex
import shutil
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_sk  # noqa: E402

HOME = os.path.expanduser("~")
DEFAULTS = {
    "sk": os.path.join(HOME, "dev", "fracview-sk-wellsight"),
    "pha": "",
    "frac": "",
    "printouts": "",
    "newpha": "",          # an export of the newest wells, with no surveys of their own
    "surveys": "",         # their survey reports, read by the Directional Survey tool (JSON per report)
    "reports": "",         # geologist's reports, read by the Geology tool (JSON per report)
    "descriptions": "",    # printouts' descriptions, read by mudlog_pdf parts={"descriptions"} (JSON per printout)
    "out": os.path.join(HOME, "dev", "fracview-sk"),
}


# ---------------------------------------------------------------- the export

def parse_pha(path):
    """(structs, wells): structs {name: [field, ...]}; each well its WELL
    fields by name plus "_sec" {section: [row, ...]} (rows as lists of strings)"""
    lines = open(path, errors="replace").read().replace("\r", "").split("\n")
    structs, i = {}, 0
    while i < len(lines):
        m = re.match(r"struct\s+(\w+)(\[\s*N\s*\])?\s*\{", lines[i])
        if m:
            fields = []
            i += 1
            while i < len(lines) and not lines[i].startswith("}"):
                if lines[i].strip():
                    fields.append(lines[i].strip())
                i += 1
            structs[m.group(1)] = fields
        elif lines[i].startswith("WELL "):
            break
        i += 1
    if "WELL" not in structs:
        raise ValueError("%s: not a Photon export (no struct WELL)" % path)
    wells, cur = [], None
    while i < len(lines):
        line = lines[i]
        if line.startswith("WELL "):
            cur = dict(zip(structs["WELL"], shlex.split(line[5:])))
            cur["_sec"] = {}
            wells.append(cur)
            i += 1
            continue
        m = re.match(r"^([A-Z_]+)\s+(\d+)\s*$", line)
        if m and m.group(1) in structs and cur is not None:
            n = int(m.group(2))
            cur["_sec"][m.group(1)] = [shlex.split(r) for r in lines[i + 1:i + 1 + n]]
            i += n + 1
            continue
        i += 1
    return structs, wells


def num(s):
    try:
        v = float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def lic_key(lic):
    """a licence as the province writes it: 0999901 -> 999901, 099Z901 -> 99Z901"""
    s = re.sub(r"\s", "", str(lic or "")).upper()
    if s.isdigit():
        return s.lstrip("0") or "0"
    m = re.match(r"^0*(\d+)([A-Z])(\d+)$", s)
    if m:
        return "%02d%s%s" % (int(m.group(1)), m.group(2), m.group(3))
    return s


def uwi_key(u):
    return re.sub(r"[^0-9A-Z]", "", str(u or "").upper())


def uwi_text(u):
    """101011100109W400 -> 101/01-11-001-09W4/00"""
    u = uwi_key(u)
    if not re.match(r"^\d{12}W\d\d\d$", u):
        return u
    return "%s/%s-%s-%s-%s%s/%s" % (u[0:3], u[3:5], u[5:7], u[7:10], u[10:12], u[12:14], u[14:16])


# NAD83 UTM -> lat/lon (GRS80; Snyder's series, well under a centimetre here)
_A, _F, _K0 = 6378137.0, 1 / 298.257222101, 0.9996


def utm_to_latlon(e, n, zone):
    e2 = _F * (2 - _F)
    ep2 = e2 / (1 - e2)
    m = n / _K0
    mu = m / (_A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(p1), math.cos(p1), math.tan(p1)
    c1, t1 = ep2 * c * c, t * t
    n1 = _A / math.sqrt(1 - e2 * s * s)
    r1 = _A * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = (e - 500000.0) / (n1 * _K0)
    lat = p1 - (n1 * t / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
                                + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / c
    return math.degrees(lat), (zone - 1) * 6 - 180 + 3 + math.degrees(lon)


def arc(a, b):
    """measured depth between two stations (x, y, z, inc, az): the minimum-
    curvature arc through them, from the chord and the dogleg"""
    chord = math.dist(a[:3], b[:3])
    i1, i2 = math.radians(a[3]), math.radians(b[3])
    cosb = math.cos(i2 - i1) - math.sin(i1) * math.sin(i2) * (1 - math.cos(math.radians(b[4] - a[4])))
    beta = math.acos(max(-1.0, min(1.0, cosb)))
    return chord if beta < 1e-7 else chord * (beta / 2) / math.sin(beta / 2)


def pha_trajectory(w):
    """(traj tuples (md, tvd, ns, ew, inc, az), lat, lon, how) from DIR_XYZ,
    or None. ns/ew are true north/east metres from the surface, as build_sk
    writes them; lat/lon come from the stations' UTM coordinates."""
    rows = w["_sec"].get("DIR_XYZ") or []
    zone = int(num(w.get("UTMZONE")) or 13)
    e0, n0 = num(w.get("UTMX")), num(w.get("UTMY"))
    if not rows or e0 is None or n0 is None:
        return None
    st = []
    for r in rows:
        if len(r) < 7:
            continue
        x, y, z, inc, az = (num(v) for v in r[2:7])
        if None in (x, y, z, inc, az):
            continue
        st.append((x, y, z, inc, az))
    if len(st) < 2:
        return None
    lat0, lon0 = utm_to_latlon(e0, n0, zone)
    k = math.cos(math.radians(lat0))
    md = st[0][2]
    traj, lats, lons = [], [], []
    for j, s in enumerate(st):
        if j:
            md += arc(st[j - 1], s)
        la, lo = utm_to_latlon(e0 + s[0], n0 + s[1], zone)
        traj.append((md, s[2], (la - lat0) * 111320, (lo - lon0) * 111320 * k, s[3], s[4] % 360))
        lats.append(la)
        lons.append(lo)
    return traj, lat0, lon0, lats, lons


def trajectory_dict(traj, lats, lons):
    return {"md": [round(t[0], 1) for t in traj], "inc": [round(t[4], 2) for t in traj], "az": [round(t[5], 2) for t in traj],
            "tvd": [round(t[1], 1) for t in traj], "ns": [round(t[2], 1) for t in traj], "ew": [round(t[3], 1) for t in traj],
            "lat": [round(v, 6) for v in lats], "lon": [round(v, 6) for v in lons]}


# ---------------------------------------------------------------- the frac data

FRAC_SOURCE = "Saskatchewan frac data"


def frac_stages(path):
    """{uwi key: [stage, ...]} in FracView's stage form, and the units row"""
    out = defaultdict(list)
    with open(path, newline="", errors="replace") as f:
        rd = csv.reader(f)
        head = [h.strip() for h in next(rd)]
        units = next(rd, [])
        col = {h: i for i, h in enumerate(head)}
        get = lambda row, h: row[col[h]].strip() if h in col and col[h] < len(row) else ""
        for row in rd:
            u = uwi_key(get(row, "UWI"))
            n = num(get(row, "Stage"))
            if not u or n is None:
                continue
            day = lambda d: d.replace("/", "-") if re.match(r"^\d{4}/\d\d/\d\d$", d) else (d or None)
            props, placed_t, pumped_t = [], 0.0, 0.0
            for i in range(1, 5):
                name = get(row, "PROP %d" % i)
                pu, pl = num(get(row, "PROP %d PUMPED" % i)), num(get(row, "PROP %d PLACED" % i))
                if name or pu or pl:
                    props.append({"name": name, "pumped_t": pu, "placed_t": pl})
                    placed_t += pl if pl is not None else (pu or 0.0)
                    pumped_t += pu or 0.0
            top = num(get(row, "COMPLTNxTOP"))
            start = day(get(row, "START DATE"))
            out[u].append({
                "n": int(n), "label": str(int(n)), "date": start, "source": FRAC_SOURCE,
                "top_m": top, "base_m": top,
                "start": " ".join(x for x in (start, get(row, "START TIME")) if x) or None,
                "end": " ".join(x for x in (day(get(row, "END DATE")), get(row, "END TIME")) if x) or None,
                "breakdown_mpa": num(get(row, "BREAK DOWN")), "isip_mpa": num(get(row, "ISIP")),
                "max_pressure_mpa": num(get(row, "MAX TREATING")), "avg_pressure_mpa": num(get(row, "AVERAGE TREATING")),
                "min_pressure_mpa": None, "avg_rate_m3_min": num(get(row, "AVERAGE RATE")),
                "frac_gradient_kpa_m": num(get(row, "FRAC GRADIENT")), "fluid_m3": num(get(row, "FLUID PUMPED")),
                "n2_scm": num(get(row, "N2 PUMPED")), "proppant_t": round(placed_t, 2) if props else None,
                "proppant_pumped_t": round(pumped_t, 2) if props else None, "proppants": props})
    for u in out:
        out[u].sort(key=lambda s: s["n"])
    return out, dict(zip(head, units))


def depth_intervals(stages):
    return [{"n": s["n"], "top_m": s["top_m"], "base_m": s["base_m"], "date": (s["date"] or "").replace("-", ""),
             "completion_type": "FRACTURED", "source": FRAC_SOURCE} for s in stages if s["top_m"] is not None]


# ---------------------------------------------------------------- the WellSight set

def load_set(folder):
    """the wells of a set build_sk.py wrote, back in the form write() takes"""
    index = json.load(open(os.path.join(folder, "index.json")))
    rocks = [r[0] for r in index.get("rocks") or []]
    labels = {r[0]: r[1] for r in index.get("rocks") or []}
    tdefs = index.get("types") or {}
    wells = []
    for pf in sorted(glob.glob(os.path.join(folder, "pads", "*.json"))):
        pad = json.load(open(pf))
        for e in pad["wells"]:
            well = e["well"]
            notes = []
            wf = os.path.join(folder, "wells", "%s.json" % well["wa"])
            if os.path.exists(wf):
                notes = json.load(open(wf)).get("log_notes") or []
            logs = e.get("logs")
            names = {}
            if logs and logs.get("types", {}).get("rock"):
                logs["types"]["rock"] = [rocks[i] if i is not None and i < len(rocks) else None for i in logs["types"]["rock"]]
                names = {r: labels.get(r, r) for r in logs["types"]["rock"] if r}
            types = {k: {"t": tdefs[k]["t"], "u": tdefs[k]["u"]} for k in (logs or {}).get("types", {})
                     if k in tdefs and k not in ("rock", "por", "show")}
            key = well.get("licence") or re.sub(r"-\d+$", "", well["wa"][2:])
            wells.append({"key": key, "lat": well["lat"], "lon": well["lon"], "types": types, "rock_names": names,
                          "notes": notes, "well": well, "trajectory": e["trajectory"], "stages": e.get("stages") or [],
                          "depth_intervals": e.get("depth_intervals") or [], "logs": logs})
    return wells, index.get("left_out") or {}


# ---------------------------------------------------------------- the merge

def merge(wells, skipped, pha_path, frac_path, printouts=None):
    """wells (build_sk's form) with the export's wells added and its surveys
    put in; returns (wells, skipped, report)"""
    _, pha = parse_pha(pha_path)
    stages, _units = frac_stages(frac_path) if frac_path else ({}, {})
    by_lic = {lic_key(w["key"]): w for w in wells if w["key"] and not w["key"].startswith("~")}
    rep = Counter()
    skipped = dict(skipped)
    seen = set()
    for p in pha:
        lic = lic_key(p.get("LICENSE"))
        got = pha_trajectory(p)
        if not got:
            rep["export wells with no survey (left out)"] += 1
            continue
        leg = lic in seen                      # a second leg under one licence: its own well
        seen.add(lic)
        traj, lat0, lon0, lats, lons = got
        st = stages.get(uwi_key(p.get("WELLID")), [])
        tops = [[r[2], num(r[1])] for r in p["_sec"].get("WELTOPS_MD") or [] if len(r) >= 3 and num(r[1]) is not None]
        heel = build_sk.heel_of(traj)
        td = max(num(p.get("TD")) or 0, traj[-1][0])
        info = {"status": p.get("STATUS") or "", "fluid": p.get("WELLFLUID") or "", "pool": p.get("POOL") or "",
                "field": p.get("FIELD") or "", "spud": p.get("SPUDDATE") or "", "rig_release": p.get("RRDATE") or "",
                "cum_oil_m3": num(p.get("CUM_OIL_VOL")), "cum_gas_e3m3": num(p.get("CUM_GAS_VOL")),
                "cum_water_m3": num(p.get("CUM_WAT_VOL")), "cum_hours": num(p.get("CUM_PRD_HOUR")),
                "drilling_company": p.get("DRILLINGCOMPANY") or "", "tops": tops}
        old = None if leg else by_lic.get(lic)
        if old:
            w = old
            w["well"].update(info)
            rep["WellSight wells given the export's survey" + (" (their path was estimated)" if w["well"].get("path_estimated") else "")] += 1
        else:
            w = {"key": lic, "types": {}, "rock_names": {}, "notes": [], "logs": None, "stages": [], "depth_intervals": [],
                 "well": {"name": p.get("WELLNAME") or lic, "licence": lic, "uwi": uwi_text(p.get("WELLID")), "prov": "SK",
                          "operator": p.get("COMPANY") or "", "formation": p.get("FORMATION") or "",
                          "curves": 0, "logs": 0, "vertical": False, **info}}
            wells.append(w)
            rep["export wells added"] += 1
        w["lat"], w["lon"] = round(lat0, 6), round(lon0, 6)
        w["trajectory"] = trajectory_dict(traj, lats, lons)
        w["well"].update({"lat": w["lat"], "lon": w["lon"], "td_m": round(td, 1), "tvd_m": round(max(t[1] for t in traj), 1),
                          "lateral_m": round(traj[-1][0] - heel) if heel is not None else 0,
                          "heel_md": round(heel, 1) if heel is not None else None,
                          "year": build_sk.year_of(p.get("SPUDDATE"), p.get("RRDATE")) or w["well"].get("year"),
                          "elev_m": num(p.get("KB")) or w["well"].get("elev_m"), "ground_m": num(p.get("GRD")) or w["well"].get("ground_m"),
                          "surface_loc": (p.get("SURFACE_UWI") or "").strip() or w["well"].get("surface_loc") or "",
                          "placed_by": "the Photon export's surface coordinates (NAD83 UTM)",
                          "path_from": "survey (Photon export)", "path_estimated": False,
                          "stages_filed": len(st)})
        if st:
            w["stages"] = st
            w["depth_intervals"] = depth_intervals(st)
            rep["wells with frac stages"] += 1
    if printouts:
        import read_printouts  # noqa: F401  (task 2 adds the printout logs)
        read_printouts.attach(wells, printouts, rep)
    for k, v in rep.items():
        if "left out" in k:
            skipped["Photon export: " + k.replace(" (left out)", "")] = v
    return wells, skipped, rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k, default=v)
    args = ap.parse_args(argv)
    for k in DEFAULTS:
        setattr(args, k, os.path.expanduser(getattr(args, k)))
    if not args.pha:
        ap.error("--pha is needed")
    if os.path.abspath(args.sk) == os.path.abspath(args.out):
        ap.error("--out must not be the WellSight set it reads (--sk)")
    wells, skipped = load_set(args.sk)
    print("WellSight set: %d wells" % len(wells), file=sys.stderr)
    wells, skipped, rep = merge(wells, skipped, args.pha, args.frac, args.printouts or None)
    if args.newpha or args.reports or args.descriptions:
        import viking_geo
        if args.newpha and args.surveys:
            viking_geo.add_new_wells(wells, args.newpha, args.surveys, rep)
        viking_geo.attach_comments(wells, args.reports or None, args.descriptions or None, rep)
        viking_geo.rocks_from_comments(wells, rep)
        for k, v in rep.items():
            if "left out" in k and k.startswith("new export"):
                skipped["Photon export (newest wells): " + k.replace(" (left out)", "")] = v
    for k, v in sorted(rep.items()):
        print("  %6d  %s" % (v, k), file=sys.stderr)
    for sub in ("pads", "wells"):                 # a fresh set: no pad left over from the last build
        shutil.rmtree(os.path.join(args.out, sub), ignore_errors=True)
    build_sk.write(args.out, wells, skipped, name="Saskatchewan",
                   source="WellSight mud logs, a Photon well export and the province's frac data (private, local only)")


if __name__ == "__main__":
    main()
