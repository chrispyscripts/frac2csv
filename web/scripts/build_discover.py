"""FracView's Discover tables: one row per well in the region, and each well's
nearest neighbours, so an engineer can filter the whole region in the browser.

    python3 web/scripts/build_discover.py

Reads what the region build already wrote (web/public/data/): region/index.json,
region/pads/*.json (identity, survey, every filed stage), gamma.json (landing
gamma) and seismic/events.json (earthquakes matched to stages). Writes
discover/wells.json: a column list and a row per well, compact enough to load
whole:

  completion    stages filed, lateral length, stage spacing, proppant and fluid
                in total and per lateral metre, median rate, median average and
                peak treating pressure, median ISIP and breakdown
  landing       median gamma along the lateral (and whether it is estimated)
  production    cumulative gas as filed, and per lateral metre
  seismicity    earthquakes that coincided with one of its stages, largest
  spacing       the nearest offset lateral: across (plan) and vertical, metres,
                and the three nearest kept in discover/spacing.json

Spacing is measured where two laterals run side by side: points every 50 m
along one, each against the nearest point of the other where it falls within
the other's lateral (not off its ends), over at least 300 m of overlap. Plan
offset is the median across that overlap; vertical is the median TVD
difference, positive when the neighbour is deeper.
"""
import glob
import json
import math
import os
import statistics as st

import numpy as np

from geodesy import offset

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "data")
STEP_M, MIN_OVERLAP_M, NEAR_M, PARALLEL_DEG = 50.0, 300.0, 1500.0, 25.0

COLUMNS = ["wa", "name", "pad", "padName", "field", "operator", "formation", "year", "lat", "lon", "toeLat", "toeLon",
           "td", "tvd", "lateral", "stages", "curves", "stageSpacing", "proppant", "proppantPerM", "fluid", "fluidPerM",
           "rate", "avgP", "maxP", "isip", "breakdown", "gamma", "gammaEst", "gas", "gasPerM", "refracs",
           "quakes", "quakeMax", "nn", "nnH", "nnV"]


def med(xs):
    xs = [x for x in xs if x is not None and math.isfinite(x)]
    return round(st.median(xs), 2) if xs else None


def rnd(x, d=1):
    return None if x is None else round(x, d)


def latlon(w):
    """each survey station's latitude and longitude: as filed, or from its offsets"""
    t, W = w["trajectory"], w["well"]
    if t.get("lat") and t.get("lon"):
        return t["lat"], t["lon"]
    ll = [offset(W["lat"], W["lon"], ns, ew) for ns, ew in zip(t["ns"], t["ew"])]
    return [a for a, _ in ll], [b for _, b in ll]


def lateral_points(w):
    """the lateral's stations, in metres east/north of the region centre, with TVD"""
    t, heel = w["trajectory"], w["well"].get("heel_md")
    lats, lons = latlon(w)
    pts = [(lat, lon, tvd) for md, lat, lon, tvd in zip(t["md"], lats, lons, t["tvd"])
           if None not in (md, lat, lon, tvd) and (heel is None or md >= heel)]
    return pts if len(pts) >= 2 else None


def to_xy(pts, lat0, lon0):
    k = math.cos(math.radians(lat0))
    return np.array([[(lon - lon0) * 111320.0 * k, (lat - lat0) * 111320.0, tvd] for lat, lon, tvd in pts])


def resample(p, step):
    """points every `step` metres along a polyline (plan distance)"""
    seg = np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1]))
    s = np.concatenate([[0], np.cumsum(seg)])
    if s[-1] < step:
        return p[[0, -1]]
    at = np.arange(0, s[-1], step)
    return np.stack([np.interp(at, s, p[:, i]) for i in range(3)], axis=1)


def offsets(a, b):
    """a's points against b's lateral: plan distance, TVD difference, and whether
    the nearest point is inside b (not past either end)"""
    p0, p1 = b[:-1], b[1:]
    d = p1[:, :2] - p0[:, :2]
    L2 = np.maximum((d ** 2).sum(1), 1e-9)
    rel = a[:, None, :2] - p0[None, :, :2]
    f = np.clip((rel * d[None]).sum(2) / L2[None], 0, 1)
    near = p0[None, :, :2] + f[..., None] * d[None]
    dist = np.hypot(*(a[:, None, :2] - near).transpose(2, 0, 1))
    j = dist.argmin(1)
    fj = f[np.arange(len(a)), j]
    tvd = p0[j, 2] + fj * (p1[j, 2] - p0[j, 2])
    inside = ~(((j == 0) & (fj <= 0)) | ((j == len(b) - 2) & (fj >= 1)))
    return dist[np.arange(len(a)), j], tvd - a[:, 2], inside


def main():
    idx = json.load(open(os.path.join(DATA, "region", "index.json")))
    lat0, lon0 = idx["center"] if isinstance(idx.get("center"), list) else (56.794, -122.115)
    padinfo = {p["id"]: p for p in idx["pads"]}
    gamma = json.load(open(os.path.join(DATA, "gamma.json")))
    events = json.load(open(os.path.join(DATA, "seismic", "events.json")))
    quakes = {}
    for r in events["rows"]:
        m = r[11]
        if m:
            q = quakes.setdefault(str(int(m[0])), [])
            q.append(r[4])

    rows, laterals = [], {}
    for f in sorted(glob.glob(os.path.join(DATA, "region", "pads", "*.json"))):
        pad = json.load(open(f))
        info = padinfo.get(pad["id"], {})
        for w in pad["wells"]:
            W, stages = w["well"], w.get("stages") or []
            wa = str(int(W["wa"]))
            lat_m = W.get("lateral_m")
            prop = [s.get("proppant_t") for s in stages]
            fluid = [s.get("fluid_m3") for s in stages]
            ptot = sum(x for x in prop if x) or None
            ftot = sum(x for x in fluid if x) or None
            tops = sorted(s["top_m"] for s in stages if s.get("top_m") is not None)
            spacing = rnd((tops[-1] - tops[0]) / (len(tops) - 1)) if len(tops) > 2 else None
            g = gamma["wells"].get(wa.zfill(5)) or gamma["wells"].get(wa)
            gmed = None
            if g and g.get("v"):
                heel = W.get("heel_md") or 0
                gmed = med([v for i, v in enumerate(g["v"]) if v is not None and g["md0"] + (i + .5) * gamma["bin_m"] >= heel])
            toe = latlon(w)
            q = quakes.get(wa, [])
            gas = W.get("cum_gas_e3m3")
            rows.append({
                "wa": wa, "name": W.get("name", "").replace("  ", " "), "pad": pad["id"], "padName": pad["name"],
                "field": info.get("field"), "operator": W.get("operator") or info.get("operator"),
                "formation": W.get("formation"), "year": W.get("year"),
                "lat": rnd(W.get("lat"), 5), "lon": rnd(W.get("lon"), 5), "toeLat": rnd(toe[0][-1], 5), "toeLon": rnd(toe[1][-1], 5),
                "td": rnd(W.get("td_m"), 0), "tvd": rnd(W.get("tvd_m"), 0), "lateral": lat_m,
                "stages": W.get("stages_filed") or len(stages) or None, "curves": W.get("curves") or 0, "stageSpacing": spacing,
                "proppant": rnd(ptot, 0), "proppantPerM": rnd(ptot / lat_m, 2) if ptot and lat_m else None,
                "fluid": rnd(ftot, 0), "fluidPerM": rnd(ftot / lat_m, 2) if ftot and lat_m else None,
                "rate": med([s.get("avg_rate_m3_min") for s in stages]), "avgP": med([s.get("avg_pressure_mpa") for s in stages]),
                # a peak over 150 MPa is a typo in the filing (one reads 728), not a pressure
                "maxP": rnd(max([s["max_pressure_mpa"] for s in stages if s.get("max_pressure_mpa") and s["max_pressure_mpa"] <= 150], default=None), 1),
                "isip": med([s.get("isip_mpa") for s in stages]), "breakdown": med([s.get("breakdown_mpa") for s in stages]),
                "gamma": gmed, "gammaEst": bool(g and g.get("estimated")),
                "gas": rnd(gas, 0), "gasPerM": rnd(gas / lat_m, 3) if gas and lat_m else None, "refracs": W.get("refracs") or 0,
                "quakes": len(q), "quakeMax": max(q) if q else None, "nn": None, "nnH": None, "nnV": None,
            })
            pts = lateral_points(w)
            if pts:
                p = to_xy(pts, lat0, lon0)
                laterals[wa] = {"p": p, "s": resample(p, STEP_M), "mid": p[len(p) // 2, :2],
                                "dir": math.atan2(p[-1, 1] - p[0, 1], p[-1, 0] - p[0, 0]), "pad": pad["id"]}

    # nearest offset laterals: a grid of lateral midpoints, then side-by-side checks
    cell = NEAR_M
    grid = {}
    for wa, L in laterals.items():
        grid.setdefault((int(L["mid"][0] // cell), int(L["mid"][1] // cell)), []).append(wa)
    spacing = {}
    for wa, A in laterals.items():
        cx, cy = int(A["mid"][0] // cell), int(A["mid"][1] // cell)
        found = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for wb in grid.get((cx + dx, cy + dy), []):
                    if wb == wa:
                        continue
                    B = laterals[wb]
                    if np.hypot(*(A["mid"] - B["mid"])) > NEAR_M:
                        continue
                    ang = abs((A["dir"] - B["dir"] + math.pi / 2) % math.pi - math.pi / 2)
                    if math.degrees(ang) > PARALLEL_DEG:
                        continue
                    h, v, inside = offsets(A["s"], B["p"])
                    if inside.sum() * STEP_M < MIN_OVERLAP_M:
                        continue
                    found.append((float(np.median(h[inside])), float(np.median(v[inside])), int(inside.sum() * STEP_M), wb, B["pad"] == A["pad"]))
        found.sort(key=lambda x: math.hypot(x[0], x[1]))
        spacing[wa] = [[wb, round(hh), round(vv), ov, same] for hh, vv, ov, wb, same in found[:3]]

    byWa = {r["wa"]: r for r in rows}
    for wa, nb in spacing.items():
        if nb and wa in byWa:
            byWa[wa].update(nn=nb[0][0], nnH=nb[0][1], nnV=nb[0][2])

    out = os.path.join(DATA, "discover")
    os.makedirs(out, exist_ok=True)
    rows.sort(key=lambda r: (r["pad"], r["wa"]))
    json.dump({"v": 1, "columns": COLUMNS, "rows": [[r[c] for c in COLUMNS] for r in rows],
               "note": "BCER bulk data as filed; cumulative gas to the filing date; spacing where laterals run side by side"},
              open(os.path.join(out, "wells.json"), "w"), separators=(",", ":"))
    json.dump({"v": 1, "columns": ["wa", "neighbour", "across_m", "vertical_m", "overlap_m", "samePad"], "wells": spacing},
              open(os.path.join(out, "spacing.json"), "w"), separators=(",", ":"))
    print(f"{len(rows)} wells, {sum(1 for s in spacing.values() if s)} with a side-by-side neighbour -> {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
