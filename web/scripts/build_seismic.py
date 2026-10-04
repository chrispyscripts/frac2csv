"""Earthquakes around Stratum's region, from Natural Resources Canada's catalog.

    python3 web/scripts/build_seismic.py [--since 2013-01-01]

Queries the Earthquakes Canada FDSN event service (public) for the region's
box and keeps every event within the region's radius plus EDGE_KM, writing
web/public/data/seismic/events.json:

  {source, fetched, fields: [t, lat, lon, depth_km, mag, mag_type, fixed, industry], rows: [...]}

`fixed` marks a depth the network did not solve for: Earthquakes Canada
reports 0, 1, 5, 10, 15 or 20 km when the stations could not constrain it,
and more than half of this region's events carry one. Those draw as a ring at
the surface with no depth. `industry` is the catalog's own "suspected
industry-related" label.
"""
import argparse
import json
import math
import os
import subprocess
import time

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://www.earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query"
EDGE_KM = 5
FIXED = {0.0, 1.0, 5.0, 10.0, 15.0, 20.0}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2013-01-01")
    a = ap.parse_args()
    idx = json.load(open(os.path.join(_WEB, "public", "data", "region", "index.json")))
    lat0, lon0 = idx["center"]
    radius = idx["radius_km"] + EDGE_KM
    dlat = radius / 111.32
    dlon = radius / (111.32 * math.cos(math.radians(lat0)))
    q = (f"{URL}?starttime={a.since}&endtime={time.strftime('%Y-%m-%d', time.gmtime(time.time() + 86400))}"
         f"&minlatitude={lat0 - dlat:.3f}&maxlatitude={lat0 + dlat:.3f}"
         f"&minlongitude={lon0 - dlon:.3f}&maxlongitude={lon0 + dlon:.3f}&format=text&limit=50000")
    text = subprocess.run(["curl", "-sSL", "-m", "300", q], capture_output=True, text=True, check=True).stdout
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("|")
        la, lo, dep, mag = float(f[2]), float(f[3]), float(f[4] or 0), float(f[6] or 0)
        if math.hypot((la - lat0) * 111.32, (lo - lon0) * 111.32 * math.cos(math.radians(lat0))) > radius:
            continue
        rows.append([f[1][:19] + "Z", round(la, 4), round(lo, 4), round(dep, 2), round(mag, 2), f[5],
                     1 if dep in FIXED else 0, 1 if "industry" in f[7].lower() else 0])
    rows.sort(key=lambda r: r[0])
    out = os.path.join(_WEB, "public", "data", "seismic")
    os.makedirs(out, exist_ok=True)
    json.dump({"source": "Earthquakes Canada, Natural Resources Canada (FDSN event service)",
               "fetched": time.strftime("%Y-%m-%d"), "since": a.since,
               "fields": ["t", "lat", "lon", "depth_km", "mag", "mag_type", "fixed", "industry"], "rows": rows},
              open(os.path.join(out, "events.json"), "w"), separators=(",", ":"))
    print(f"{len(rows)} events within {radius:g} km since {a.since}; "
          f"{sum(r[6] for r in rows)} with a fixed depth, {sum(r[7] for r in rows)} labelled industry-related, "
          f"largest M{max(r[4] for r in rows)}")


if __name__ == "__main__":
    main()
