#!/usr/bin/env python3
"""Build the BC well-map dataset from BCER's open bulk drilling CSVs.

Input:  drill_csv.zip from https://iris.bcogc.ca/download/drill_csv.zip
        (wells.csv = surface locations; drill_ev.csv = UWI/TD/bottomhole)
Output: public/data/bc-wells.json  — compact array the map page renders.

Coordinates in the CSVs are packed DMS (e.g. "49085314" = 49 deg 08' 53.14").
"""
import csv
import json
import os
import sys
from collections import defaultdict

SRC = sys.argv[1] if len(sys.argv) > 1 else "/tmp/drill_csv"
FRAC = sys.argv[2] if len(sys.argv) > 2 else "/tmp/frac_csv/hydraulic_fracture.csv"
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "data", "bc-wells.json")


def frac_aggregates(path):
    """Per-WA completion metrics from BCER's per-stage frac summary CSV."""
    import math
    agg = defaultdict(lambda: {"stages": set(), "prop": 0.0, "fluid": 0.0,
                               "isip": [], "bd": [], "fg": [], "yr": 0})
    if not os.path.exists(path):
        print("frac csv missing; skipping completion metrics")
        return {}
    with open(path, newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f):
            wa = (row.get("WA NUM") or "").strip()
            if not wa:
                continue
            a = agg[wa]
            a["stages"].add((row.get("COMPLTN EVENT"), row.get("FRAC STAGE NUM")))
            for i in (1, 2, 3, 4):
                v = row.get(f"PROPPANT TYPE{i} PLACED (t)") or \
                    row.get(f"PROPPANT TYPE{i} PUMPED (t)")
                try:
                    a["prop"] += float(v)
                except (TypeError, ValueError):
                    pass
            try:
                a["fluid"] += float(row.get("TOTAL FLUID PUMPED (m3)") or 0)
            except ValueError:
                pass
            for key, col in (("isip", "INST SHUT IN PRESSURE (MPa)"),
                             ("bd", "BREAK DOWN PRESSURE (MPa)"),
                             ("fg", "FRAC GRADIENT (KPa/m)")):
                try:
                    a[key].append(float(row.get(col)))
                except (TypeError, ValueError):
                    pass
            d = (row.get("COMPLTN DATE") or "").strip()
            if len(d) >= 9:
                try:
                    yr = int(d[-2:])
                    yr += 2000 if yr < 50 else 1900
                    a["yr"] = max(a["yr"], yr)
                except ValueError:
                    pass
    out = {}
    for wa, a in agg.items():
        rec = {"st": len(a["stages"])}
        if a["prop"]:
            rec["pt"] = round(a["prop"], 1)
        if a["fluid"]:
            rec["fl"] = round(a["fluid"], 1)
        if a["yr"]:
            rec["yr"] = a["yr"]
        for key, name in (("isip", "isip"), ("bd", "bd"), ("fg", "fg")):
            vals = a[key]
            if vals:
                rec[name] = round(sum(vals) / len(vals), 1)
        out[wa] = rec
    print(f"frac metrics for {len(out):,} WAs")
    return out


def dms(packed, negate=False):
    """Packed DMS 'DDMMSSss' / 'DDDMMSSss' -> decimal degrees."""
    p = (packed or "").strip()
    if not p or not p.replace(".", "").isdigit():
        return None
    p = p.replace(".", "")
    if len(p) < 7:
        return None
    ss = p[-4:]
    mm = p[-6:-4]
    dd = p[:-6]
    try:
        val = int(dd) + int(mm) / 60 + (int(ss) / 100) / 3600
    except ValueError:
        return None
    if not (0 < val < 180):
        return None
    return round(-val if negate else val, 5)


def utm_to_latlon(zone, northing, easting):
    """UTM (NAD83/WGS84 ellipsoid) -> lat/lon. Standard inverse series."""
    import math
    a = 6378137.0
    f = 1 / 298.257222101
    e2 = f * (2 - f)
    k0 = 0.9996
    x = easting - 500000.0
    y = northing
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
           + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
           + (151 * e1 ** 3 / 96) * math.sin(6 * mu))
    sin_p, cos_p, tan_p = math.sin(phi), math.cos(phi), math.tan(phi)
    ep2 = e2 / (1 - e2)
    c1 = ep2 * cos_p ** 2
    t1 = tan_p ** 2
    n1 = a / math.sqrt(1 - e2 * sin_p ** 2)
    r1 = a * (1 - e2) / (1 - e2 * sin_p ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi - (n1 * tan_p / r1) * (
        d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / cos_p
    lon0 = math.radians((int(zone) - 1) * 6 - 180 + 3)
    return round(math.degrees(lat), 5), round(math.degrees(lon) + math.degrees(lon0), 5)


def read_rows(path):
    with open(path, newline="", encoding="latin-1") as f:
        rows = list(csv.reader(f))
    header = rows[1]
    return [dict(zip(header, r)) for r in rows[2:] if len(r) > 3]


def main():
    import math
    wells = read_rows(os.path.join(SRC, "wells.csv"))
    events = read_rows(os.path.join(SRC, "drill_ev.csv"))
    fracs = frac_aggregates(FRAC)

    ev_by_wa = defaultdict(list)
    for e in events:
        ev_by_wa[e.get("WA NUM", "").strip()].append(e)

    out = []
    for w in wells:
        la = dms(w.get("Surf Nad83 Lat"))
        lo = dms(w.get("Surf Nad83 Long"), negate=True)
        if la is None or lo is None:
            continue
        wa = w.get("WA Num", "").strip()
        evs = ev_by_wa.get(wa, [])
        uwis, td, bla, blo = [], 0.0, None, None
        for e in evs:
            u = e.get("UWI", "").strip()
            if u and u not in uwis:
                uwis.append(u)
            try:
                d = float(e.get("Td Depth (m)") or 0)
            except ValueError:
                d = 0
            if d > td:
                td = d
                bla = dms(e.get("Td nad83 lat"))
                blo = dms(e.get("Td nad83 long"), negate=True)
                if bla is None:
                    try:
                        zone = int(float(e.get("Td utm zone num") or 0))
                        no = float(e.get("Td utm83 northng (m)") or 0)
                        ea = float(e.get("Td utm83 eastng (m)") or 0)
                        if zone and no > 1e6 and ea > 1e5:
                            bla, blo = utm_to_latlon(zone, no, ea)
                    except ValueError:
                        pass
        rec = {"wa": wa, "n": w.get("Well Name", "").strip()[:60],
               "la": la, "lo": lo}
        if uwis:
            rec["u"] = uwis[:4]
        if td:
            rec["td"] = round(td, 1)
        if bla is not None and blo is not None and (abs(bla - la) > 1e-5 or abs(blo - lo) > 1e-5):
            rec["bla"], rec["blo"] = bla, blo
            dy = (bla - la) * 111_320
            dx = (blo - lo) * 111_320 * math.cos(math.radians((bla + la) / 2))
            rec["ll"] = round(math.hypot(dx, dy))    # lateral length proxy (m)
        fx = fracs.get(wa)
        if fx:
            rec.update(fx)
            if "pt" in fx and rec.get("ll"):
                rec["pi"] = round(fx["pt"] / rec["ll"], 2)   # proppant intensity t/m
        out.append(rec)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"v": 1, "source": "BC Energy Regulator open data (iris.bcogc.ca)",
                   "wells": out}, f, separators=(",", ":"))
    n_lat = sum(1 for r in out if "bla" in r)
    print(f"{len(out)} wells written ({n_lat} with bottomhole legs) -> {OUT} "
          f"({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
