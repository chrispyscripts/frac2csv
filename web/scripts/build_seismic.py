"""Earthquakes around Stratum's region, and the frac stages they line up with.

    python3 web/scripts/build_seismic.py [--since 2013-01-01] [--bcsrc DIR]

Two catalogues, best first:

  BC Seismic Research Consortium (Geoscience BC / BCER array), May 2022 -
    Apr 2024: events relocated against a local velocity model, with their
    location errors (typically ~250-600 m across, ~400 m in depth). Read from
    the published CSVs in --bcsrc (downloaded if missing).
  Earthquakes Canada (Natural Resources Canada), 2013 on, everywhere else in
    time: km-scale locations, and more than half the depths are the network's
    fixed defaults (0, 1, 5, 10, 15, 20 km), flagged `fixed`.

  BC Energy Regulator (its public seismicity layer, GEOLOGY/SEISMIC_EVENT_PT),
    2014 on: confirmed suspected-induced events, ML 1.5 and up, located on
    regional velocity models, with an error ellipse (major and minor axis, m,
    and azimuth) and a depth error. Updated daily.

Inside the consortium's window its events replace the others'. Outside it,
an Earthquakes Canada event that is also in the regulator's catalogue (within
20 s and 15 km) gives way to the regulator's.

The regulator's seismic monitoring areas (GEOLOGY/SEISMIC_AREA_PY) and the
rules each sets are written to seismic/areas.json, and every pad gets a
traffic light (seismic/padlights.json): the largest event within the rule's
distance of any of its laterals while the pad was being fracked (to two days
after its last stage), graded against today's rules for where the pad sits.

Each event is then matched to a frac stage: stage windows come from the Lab's
curves where a well has them (date, start and length, read off the chart) or
else from the BCER's frac table (date and start as filed, each stage running
until the next one starts, capped at 4 h). Both clocks are local time in NE BC,
which keeps UTC-7 all year. An event matches a stage it falls inside, or up to
TAIL_H after; the stage must be within reach of the event's location -- the
larger of 1.5 km and three location errors for a relocated event, 5 km for an
Earthquakes Canada one -- measured to the stage's own point on the wellbore.
The closest such stage in time, then distance, wins.

A match says the event coincided with a frac job nearby and which of its stages
was pumping; it does not say that stage caused it. Pads are fracked around the
clock and two wells are often pumped alternately, so in a busy area some stage
is nearly always running. How much of the matching is more than chance is
measured here by matching the same events again with their dates shifted by
weeks (CONTROL_DAYS): the shortfall is the share of matches the frac jobs
explain, and it is written out with the events.

Writes web/public/data/seismic/events.json:
  {fields: [t, lat, lon, depth_km, mag, mag_type, fixed, industry, src, herr_m, derr_m, match, maj_m, min_m, az], rows}
  src: bcsrc | bcer | nrcan; maj_m/min_m/az: the regulator's error ellipse (bcer only)
  match: [WA, stage label, "during"|"after", minutes after the stage ended, km to the stage,
          m between the event's depth and the stage's subsea depth (or null)] or null
"""
import argparse
import bisect
import sys
import csv
import glob
import json
import math
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geodesy import offset  # noqa: E402

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_WEB, "public", "data")
URL = "https://www.earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query"
BCSRC = {
    "Appendix_C_May2023-Apr2024_NEBC_Seismicity_Catalogue.csv":
        "https://www.geosciencebc.com/i/project_data/GBCReport2012-SEIS/Appendix_C_May2023-Apr2024_NEBC_Seismicity_Catalogue.csv",
    "May_2022-May_2023_NEBC_Seismicity_Catalogue_Revised_July26_2023.csv":
        "https://www.geosciencebc.com/i/project_data/GBCReport2012-SEIS/May_2022-May_2023_NEBC_Seismicity_Catalogue_Revised_July26_2023.csv",
}
BCER_EVENTS = "https://geoweb-ags.bc-er.ca/arcgis/rest/services/GEOLOGY/SEISMIC_EVENT_PT/MapServer/0/query"
BCER_AREAS = "https://geoweb-ags.bc-er.ca/arcgis/rest/services/GEOLOGY/SEISMIC_AREA_PY/FeatureServer/0/query"
# today's rules (BCER Induced Seismicity Operational Manual, Feb 2025; TU 2025-02):
# local magnitude, within `km` of the well's trajectory
RULES = {
    "KSMMA": {"name": "Kiskatinaw Seismic Monitoring and Mitigation Area", "km": 5, "since": "2018-05-21",
              "notify": 1.5, "mitigate": 2.0, "suspend": 3.0, "resuspend": 2.7},
    "NMSMMA": {"name": "North Montney Seismic Monitoring and Mitigation Area", "km": 5, "since": "2025-02-13",
               "notify": 2.5, "mitigate": 3.0, "suspend": 4.0, "resuspend": 3.7},
    "BC": {"name": "Province-wide (Drilling and Production Regulation s.21.1)", "km": 3, "since": None,
           "notify": 4.0, "mitigate": None, "suspend": 4.0, "resuspend": None},
}
EDGE_KM = 5
FIXED = {0.0, 1.0, 5.0, 10.0, 15.0, 20.0}
LOCAL = timezone(timedelta(hours=-7))       # NE BC: MST all year
TAIL_H = 2.0
CONTROL_DAYS = (-60, -30, 30, 60)
STAGE_CAP_H = 4.0


def utm10_to_latlon(e, n):
    """UTM zone 10N (NAD83 ~ WGS84) -> (lat, lon)."""
    a, f, k0 = 6378137.0, 1 / 298.257222101, 0.9996
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x, y = e - 500000.0, n
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(p1) ** 2; t1 = math.tan(p1) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(p1) ** 2); r1 = a * (1 - e2) / (1 - e2 * math.sin(p1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                           + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(p1)
    return math.degrees(lat), -123.0 + math.degrees(lon)


def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_bcsrc(folder):
    os.makedirs(folder, exist_ok=True)
    out = []
    for name, url in BCSRC.items():
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            subprocess.run(["curl", "-sSL", "-m", "300", "-A", "Mozilla/5.0", "-o", path, url], check=True)
        with open(path, errors="ignore", newline="") as f:
            rows = list(csv.reader(f))
        head = [h.strip() for h in rows[0]]
        if "Northing (m)" in head:                     # 2023-24: UTM, errors in metres
            col = {h: i for i, h in enumerate(head)}
            for r in rows[2:]:
                if len(r) < len(head) or not r[col["Northing (m)"]]:
                    continue
                lat, lon = utm10_to_latlon(float(r[col["Easting (m)"]]), float(r[col["Northing (m)"]]))
                dt = datetime.strptime(f"{r[col['Date (UTC)']]} {r[col['Time (UTC)']]}", "%m/%d/%Y %H:%M:%S")
                ne, ee = num(r[col["NorthErr (m)"]]), num(r[col["EastErr (m)"]])
                out.append({"t": dt, "lat": lat, "lon": lon, "depth": num(r[col["Depth (km)"]]),
                            "mag": num(r[col["Local Magnitude"]]), "type": "ML", "fixed": 0, "industry": 0,
                            "src": "bcsrc", "herr": round(max(ne, ee)) if ne and ee else None,
                            "derr": round(num(r[col["DepthErr (m)"]])) if num(r[col["DepthErr (m)"]]) else None})
        else:                                          # 2022-23: lat/lon, error ellipse
            for r in csv.DictReader(open(path, errors="ignore", newline="")):
                try:
                    dt = datetime.strptime(r["UTC Datetime"].strip(), "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                dz = num(r.get("Depth Error (km)"))
                out.append({"t": dt, "lat": float(r["Latitude (°N)"]), "lon": float(r["Longitude (°E)"]),
                            "depth": num(r["Depth (km)"]), "mag": num(r["Magnitude"]), "type": "ML", "fixed": 0,
                            "industry": 0, "src": "bcsrc",
                            "herr": round(num(r["Majoraxis Error (m)"])) if num(r.get("Majoraxis Error (m)")) else None,
                            "derr": round(dz * 1000) if dz else None})
    return out


def read_nrcan(lat0, lon0, radius, since):
    dlat = radius / 111.32
    dlon = radius / (111.32 * math.cos(math.radians(lat0)))
    q = (f"{URL}?starttime={since}&endtime={time.strftime('%Y-%m-%d', time.gmtime(time.time() + 86400))}"
         f"&minlatitude={lat0 - dlat:.3f}&maxlatitude={lat0 + dlat:.3f}"
         f"&minlongitude={lon0 - dlon:.3f}&maxlongitude={lon0 + dlon:.3f}&format=text&limit=50000")
    text = subprocess.run(["curl", "-sSL", "-m", "300", q], capture_output=True, text=True, check=True).stdout
    out = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("|")
        dep = float(f[4] or 0)
        out.append({"t": datetime.strptime(f[1][:19], "%Y-%m-%dT%H:%M:%S"), "lat": float(f[2]), "lon": float(f[3]),
                    "depth": dep, "mag": num(f[6]), "type": f[5], "fixed": 1 if dep in FIXED else 0,
                    "industry": 1 if "industry" in f[7].lower() else 0, "src": "nrcan", "herr": None, "derr": None})
    return out


def read_bcer(lat0, lon0, radius):
    """the regulator's catalogue around the region, paged 2,000 at a time"""
    dlat = radius / 111.32
    dlon = radius / (111.32 * math.cos(math.radians(lat0)))
    where = (f"LATITUDE >= {lat0 - dlat:.4f} AND LATITUDE <= {lat0 + dlat:.4f} AND "
             f"LONGITUDE >= {lon0 - dlon:.4f} AND LONGITUDE <= {lon0 + dlon:.4f}")
    out, offset_ = [], 0
    from urllib.parse import urlencode
    while True:
        q = BCER_EVENTS + "?" + urlencode({"where": where, "outFields": "*", "returnGeometry": "false", "f": "json",
                                           "orderByFields": "OBJECTID", "resultOffset": offset_, "resultRecordCount": 2000})
        page = json.loads(subprocess.run(["curl", "-sSL", "-m", "300", q], capture_output=True, text=True, check=True).stdout)
        feats = page.get("features") or []
        for f in feats:
            a = f["attributes"]
            if a.get("EVENT_DATE_TIME") is None or a.get("LATITUDE") is None:
                continue
            dz = a.get("DEPTH_ERROR")
            out.append({"t": datetime.fromtimestamp(a["EVENT_DATE_TIME"] / 1000, tz=timezone.utc).replace(tzinfo=None),
                        "lat": a["LATITUDE"], "lon": a["LONGITUDE"], "depth": a.get("DEPTH_KM"),
                        "mag": a.get("MAGNITUDE"), "type": a.get("MAGNITUDE_TYPE") or "ML", "fixed": 0,
                        "industry": 1 if "induced" in str(a.get("EVENT_TYPE") or "").lower() else 0, "src": "bcer",
                        "herr": round(a["MAJOR_AXIS_ERROR"]) if a.get("MAJOR_AXIS_ERROR") else None,
                        "derr": round(dz * 1000) if dz else None,
                        "maj": round(a["MAJOR_AXIS_ERROR"]) if a.get("MAJOR_AXIS_ERROR") else None,
                        "min": round(a["MINOR_AXIS_ERROR"]) if a.get("MINOR_AXIS_ERROR") else None,
                        "az": round(a["AZIMUTH"], 1) if a.get("AZIMUTH") is not None else None})
        if not page.get("exceededTransferLimit") and len(feats) < 2000:
            break
        offset_ += len(feats)
    return out


def same_event(a, b):
    return abs((a["t"] - b["t"]).total_seconds()) <= 20 and \
        math.hypot((a["lat"] - b["lat"]) * 111.32, (a["lon"] - b["lon"]) * 111.32 * math.cos(math.radians(a["lat"]))) <= 15


def read_areas():
    q = BCER_AREAS + "?where=1%3D1&outFields=NAME&outSR=4326&f=geojson"
    g = json.loads(subprocess.run(["curl", "-sSL", "-m", "120", q], capture_output=True, text=True, check=True).stdout)
    for f in g.get("features", []):
        name = f["properties"].get("NAME", "")
        f["properties"] = {"name": name, "rule": "KSMMA" if "KSMMA" in name else ("NMSMMA" if "NMSMMA" in name else None)}
    return g


def inside(lon, lat, geom):
    """point in a GeoJSON Polygon / MultiPolygon (outer rings, holes honoured)"""
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        hit = False
        for k, ring in enumerate(poly):
            c = False
            for i in range(len(ring)):
                x1, y1 = ring[i - 1][:2]
                x2, y2 = ring[i][:2]
                if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                    c = not c
            if k == 0:
                hit = c
            elif c:
                hit = False
        if hit:
            return True
    return False


def pad_lights(events, areas):
    """every pad's largest event near its laterals while it was being fracked,
    graded against today's rules for where it sits"""
    out = {}
    for f in sorted(glob.glob(os.path.join(_DATA, "region", "pads", "*.json"))):
        pad = json.load(open(f))
        rule = "BC"
        for a in areas.get("features", []):
            if a["properties"]["rule"] and inside(pad["lon"], pad["lat"], a["geometry"]):
                rule = a["properties"]["rule"]
        R = RULES[rule]
        pts, dates = [], []
        for w in pad["wells"]:
            W, t = w["well"], w.get("trajectory") or {}
            ns, ew = t.get("ns") or [], t.get("ew") or []
            for i in range(0, len(ns), 3):
                if ns[i] is not None and ew[i] is not None:
                    pts.append(offset(W["lat"], W["lon"], ns[i], ew[i]))
            dates += [str(s["date"])[:10] for s in w.get("stages") or [] if s.get("date")]
        if not pts or not dates:
            out[pad["id"]] = {"rule": rule}
            continue
        t0 = datetime.strptime(min(dates), "%Y-%m-%d")
        t1 = datetime.strptime(max(dates), "%Y-%m-%d") + timedelta(days=3)
        lat_c = sum(p[0] for p in pts) / len(pts)
        kx = 111.32 * math.cos(math.radians(lat_c))

        def dist(e):
            return min(math.hypot((e["lat"] - p[0]) * 111.32, (e["lon"] - p[1]) * kx) for p in pts)
        during = []
        for e in events:
            if e["mag"] is None or not (t0 <= e["t"] + timedelta(hours=-7) <= t1):
                continue
            if abs(e["lat"] - lat_c) > 0.2:
                continue
            d = dist(e)
            if d <= R["km"]:
                during.append((e["mag"], d, e))
        top = max(during, key=lambda x: x[0]) if during else None
        level = "none"
        if top:
            m = top[0]
            level = ("suspend" if R["suspend"] and m >= R["suspend"] else
                     "mitigate" if R["mitigate"] and m >= R["mitigate"] else
                     "notify" if R["notify"] and m >= R["notify"] else "below")
        out[pad["id"]] = {"rule": rule, "from": t0.strftime("%Y-%m-%d"), "to": t1.strftime("%Y-%m-%d"),
                          "n": len(during), "max": round(top[0], 2) if top else None,
                          "maxAt": iso(top[2]["t"]) if top else None, "maxKm": round(top[1], 2) if top else None,
                          "maxSrc": top[2]["src"] if top else None,
                          "n15": sum(1 for x in during if x[0] >= 1.5), "level": level}
    return out


def stage_windows():
    """Every region stage with a time: (start_utc, end_utc, wa, label, lat, lon, subsea_m)."""
    idx = json.load(open(os.path.join(_DATA, "region", "index.json")))
    out = []
    for p in idx["pads"]:
        pad = json.load(open(os.path.join(_DATA, "region", "pads", f"{p['id']}.json")))
        for w in pad["wells"]:
            well, t = w["well"], w["trajectory"]
            wa = str(well["wa"]).zfill(5)
            elev = well.get("elev_m") or 0
            def at(md):
                if md is None or not t["md"]:
                    return None
                i = min(bisect.bisect_left(t["md"], md), len(t["md"]) - 1)
                return (*offset(well["lat"], well["lon"], t["ns"][i], t["ew"][i]), t["tvd"][i] - elev)
            stages = []
            path_w = os.path.join(_DATA, "wells", f"{wa}.json")
            lab = []
            if os.path.exists(path_w):
                # a chart longer than 5 h is the whole job re-plotted, not a stage
                lab = [s for s in json.load(open(path_w)).get("stages") or []
                       if s.get("series") and s.get("date") and s.get("start") and (s.get("minutes") or 0) <= 300]
            if lab:                                    # the chart's own clock and length
                for s in lab:
                    t0 = datetime.strptime(f"{s['date']} {s['start'][:8]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL)
                    mins = min(s.get("minutes") or 60, STAGE_CAP_H * 60)
                    stages.append((t0, t0 + timedelta(minutes=mins), str(s["label"]), s.get("top_m")))
            else:                                      # the BCER table: each stage runs until the next
                filed = []
                for s in w.get("stages") or []:
                    if s.get("date") and s.get("start"):
                        try:
                            filed.append((datetime.strptime(f"{s['date']} {s['start']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL),
                                          str(s["label"]), s.get("top_m")))
                        except ValueError:
                            pass
                filed.sort()
                for i, (t0, lab_, md) in enumerate(filed):
                    nxt = filed[i + 1][0] if i + 1 < len(filed) else t0 + timedelta(hours=2)
                    stages.append((t0, min(nxt, t0 + timedelta(hours=STAGE_CAP_H)), lab_, md))
            for t0, t1, lab_, md in stages:
                pt = at(md) or at(t["md"][-1] if t["md"] else None)
                if pt:
                    out.append((t0.astimezone(timezone.utc).replace(tzinfo=None), t1.astimezone(timezone.utc).replace(tzinfo=None),
                                wa, lab_, pt[0], pt[1], pt[2]))
    out.sort()
    return out


def match(events, stages):
    starts = [s[0] for s in stages]
    longest = max((s[1] - s[0] for s in stages), default=timedelta(0)) + timedelta(hours=TAIL_H)
    for e in events:
        reach = max(1.5, 3 * e["herr"] / 1000) if e["src"] == "bcsrc" and e["herr"] else (1.5 if e["src"] == "bcsrc" else 5.0)
        lo = bisect.bisect_left(starts, e["t"] - longest)
        hi = bisect.bisect_right(starts, e["t"])
        best = None
        c = math.cos(math.radians(e["lat"]))
        for s in stages[lo:hi]:
            t0, t1, wa, lab, la, lo_, z = s
            if e["t"] > t1 + timedelta(hours=TAIL_H):
                continue
            d = math.hypot((la - e["lat"]) * 111.32, (lo_ - e["lon"]) * 111.32 * c)
            if d > reach:
                continue
            after = max(0.0, (e["t"] - t1).total_seconds() / 60)
            key = (after > 0, after, d)
            if best is None or key < best[0]:
                dz = round(e["depth"] * 1000 - z) if e["depth"] is not None and not e["fixed"] else None
                best = (key, [wa, lab, "after" if after > 0 else "during", round(after), round(d, 2), dz])
        e["match"] = best[1] if best else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2013-01-01")
    ap.add_argument("--bcsrc", default=os.path.expanduser("~/stratum-lab/seismic"))
    a = ap.parse_args()
    idx = json.load(open(os.path.join(_DATA, "region", "index.json")))
    lat0, lon0 = idx["center"]
    radius = idx["radius_km"] + EDGE_KM
    near = lambda e: math.hypot((e["lat"] - lat0) * 111.32, (e["lon"] - lon0) * 111.32 * math.cos(math.radians(lat0))) <= radius
    bc = [e for e in read_bcsrc(a.bcsrc) if near(e)]
    w0, w1 = min(e["t"] for e in bc), max(e["t"] for e in bc)
    er = [e for e in read_bcer(lat0, lon0, radius) if near(e) and not (w0 <= e["t"] <= w1)]
    er_by_day = {}
    for e in er:
        er_by_day.setdefault(e["t"].date(), []).append(e)

    def in_bcer(e):
        return any(same_event(e, x) for d in (e["t"].date() - timedelta(days=1), e["t"].date(), e["t"].date() + timedelta(days=1))
                   for x in er_by_day.get(d, []))
    nr_all = [e for e in read_nrcan(lat0, lon0, radius, a.since) if near(e) and not (w0 <= e["t"] <= w1)]
    nr = [e for e in nr_all if not in_bcer(e)]
    events = sorted(bc + er + nr, key=lambda e: e["t"])
    stages = stage_windows()
    match(events, stages)
    real = sum(1 for e in events if e["match"])
    chance = []
    for days in CONTROL_DAYS:
        shifted = [dict(e, t=e["t"] + timedelta(days=days)) for e in events]
        match(shifted, stages)
        chance.append(sum(1 for e in shifted if e["match"]))
    by_chance = sum(chance) / len(chance)
    control = {"matched": real, "by_chance": round(by_chance), "shifts_days": list(CONTROL_DAYS),
               "share_beyond_chance": round(max(0.0, 1 - by_chance / real), 2) if real else None}
    rows = [[iso(e["t"]), round(e["lat"], 5), round(e["lon"], 5), round(e["depth"], 3) if e["depth"] is not None else None,
             round(e["mag"], 2) if e["mag"] is not None else None, e["type"], e["fixed"], e["industry"], e["src"],
             e["herr"], e["derr"], e["match"], e.get("maj"), e.get("min"), e.get("az")] for e in events]
    out = os.path.join(_DATA, "seismic")
    os.makedirs(out, exist_ok=True)
    json.dump({"source": "BC Seismic Research Consortium relocated catalogues (Geoscience BC), May 2022-Apr 2024; "
                         "BC Energy Regulator seismicity catalogue and Earthquakes Canada (NRCan) for every other date",
               "window": [iso(w0), iso(w1)], "fetched": time.strftime("%Y-%m-%d"), "since": a.since, "control": control,
               "fields": ["t", "lat", "lon", "depth_km", "mag", "mag_type", "fixed", "industry", "src", "herr_m", "derr_m", "match",
                          "maj_m", "min_m", "az"],
               "rows": rows}, open(os.path.join(out, "events.json"), "w"), separators=(",", ":"))
    areas = read_areas()
    json.dump({"v": 1, "source": "BC Energy Regulator, GEOLOGY/SEISMIC_AREA_PY; rules from the BCER Induced Seismicity "
                                 "Operational Manual (Feb 2025) and TU 2025-02",
               "rules": RULES, "areas": areas}, open(os.path.join(out, "areas.json"), "w"), separators=(",", ":"))
    lights = pad_lights(events, areas)
    json.dump({"v": 1, "rules": RULES, "built": time.strftime("%Y-%m-%d"),
               "note": "largest event within the rule's distance of a lateral from the pad's first frac stage to two days "
                       "after its last, graded against the rules in force today",
               "pads": lights}, open(os.path.join(out, "padlights.json"), "w"), separators=(",", ":"))
    from collections import Counter
    print("pad lights:", dict(Counter(v.get("level") for v in lights.values())), dict(Counter(v["rule"] for v in lights.values())))
    m = [e for e in events if e["match"]]
    print(f"{len(events)} events ({len(bc)} relocated, {len(er)} BCER, {len(nr)} Earthquakes Canada only, "
          f"{len(nr_all) - len(nr)} also in the BCER's); {len(m)} matched to a stage "
          f"({sum(1 for e in m if e['match'][2] == 'during')} during, {sum(1 for e in m if e['match'][2] == 'after')} within {TAIL_H:g} h after); "
          f"{len({e['match'][0] for e in m})} wells; matching the same events shifted {CONTROL_DAYS} days gives "
          f"{control['by_chance']} on average, so ~{round(100 * (control['share_beyond_chance'] or 0))}% of matches are beyond chance")


if __name__ == "__main__":
    main()
