"""FracView's production: every region well's monthly volumes from the BCER's
production file, for type curves, Discover and the well views.

    python3 web/scripts/build_production.py [--prod ~/stratum-lab/bcer-prod]

Source: the BCER's zone production tables (iris.bcogc.ca/download/prod_csv.zip,
zone_prd_2007_to_2015.csv, zone_prd_2016_to_2024.csv,
zone_prd_2025_to_present.csv), one row per well, completion event, zone and
month: gas (e3m3), oil, condensate and water (m3), producing days. A well
producing from more than one zone or completion event is summed by month.

Writes data/prod/wells.json: per well the first month it produced and its
monthly gas, condensate, oil, water and producing days from then on, plus a
few figures per well (first month, months on, the first 12 producing months'
gas/condensate/water, peak calendar-day gas rate, cumulatives) that
build_discover.py reads.
"""
import argparse
import csv
import glob
import json
import os

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "data")
FILES = ("zone_prd_2007_to_2015.csv", "zone_prd_2016_to_2024.csv", "zone_prd_2025_to_present.csv")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def months_between(a, b):
    """YYYYMM a to b, in months"""
    return (b // 100 - a // 100) * 12 + (b % 100 - a % 100)


def add_months(a, k):
    y, m = divmod(a // 100 * 12 + a % 100 - 1 + k, 12)
    return y * 100 + m + 1


def days_in(ym):
    y, m = divmod(ym, 100)
    if m == 2:
        return 29 if (y % 4 == 0 and y % 100) or y % 400 == 0 else 28
    return 30 if m in (4, 6, 9, 11) else 31


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prod", default=os.path.expanduser("~/stratum-lab/bcer-prod"))
    a = ap.parse_args()

    wells = set()
    for f in glob.glob(os.path.join(DATA, "region", "pads", "*.json")):
        for w in json.load(open(f))["wells"]:
            wells.add(str(int(w["well"]["wa"])).zfill(5))

    by = {}          # wa -> {yyyymm: [gas, cond, oil, water, days]}
    latest = 0
    for name in FILES:
        path = os.path.join(a.prod, name)
        with open(path, newline="") as f:
            next(f)                                   # the file's own title line
            rd = csv.reader(f)
            head = [h.strip() for h in next(rd)]
            col = {h: i for i, h in enumerate(head)}
            iw, ip = col["Wa_num"], col["Prod_period"]
            ig, io, iwt, ic, idays = (col["Gas_prod_vol (e3m3)"], col["Oil_prod_vol (m3)"], col["Water_prod_vol (m3)"],
                                      col["Cond_prod_vol (m3)"], col["Prod_days"])
            for r in rd:
                wa = r[iw].zfill(5)
                if wa not in wells:
                    continue
                ym = int(r[ip])
                latest = max(latest, ym)
                m = by.setdefault(wa, {}).setdefault(ym, [0.0, 0.0, 0.0, 0.0, 0.0])
                m[0] += num(r[ig])
                m[1] += num(r[ic])
                m[2] += num(r[io])
                m[3] += num(r[iwt])
                m[4] = max(m[4], num(r[idays]))

    out = {}
    for wa, months in by.items():
        live = sorted(ym for ym, v in months.items() if v[0] > 0 or v[1] > 0 or v[2] > 0)
        if not live:
            continue
        first, last = live[0], max(months)
        n = months_between(first, last) + 1
        series = [months.get(add_months(first, k), [0, 0, 0, 0, 0]) for k in range(n)]
        g = [round(v[0], 1) for v in series]
        c = [round(v[1], 1) for v in series]
        o = [round(v[2], 1) for v in series]
        wt = [round(v[3], 1) for v in series]
        d = [round(v[4]) for v in series]
        prod = [i for i, v in enumerate(series) if v[0] > 0 or v[1] > 0]
        first12 = prod[:12]
        gas12 = sum(g[i] for i in first12) if len(first12) == 12 else None
        cond12 = sum(c[i] for i in first12) + sum(o[i] for i in first12) if len(first12) == 12 else None
        water12 = sum(wt[i] for i in first12) if len(first12) == 12 else None
        # peak calendar-day gas rate over the first three producing months
        peak = max((g[i] / days_in(add_months(first, i)) for i in prod[:3]), default=None)
        out[wa] = {
            "f": f"{first // 100}-{first % 100:02d}", "g": g, "c": c, "o": o, "w": wt, "d": d,
            "s": {"months": len(prod), "gas12": round(gas12) if gas12 is not None else None,
                  "liq12": round(cond12) if cond12 is not None else None,
                  "water12": round(water12) if water12 is not None else None,
                  "peakGas": round(peak, 1) if peak is not None else None,
                  "cumGas": round(sum(g)), "cumLiq": round(sum(c) + sum(o)), "cumWater": round(sum(wt))}}
    os.makedirs(os.path.join(DATA, "prod"), exist_ok=True)
    json.dump({"v": 1, "through": f"{latest // 100}-{latest % 100:02d}",
               "units": {"g": "e3m3", "c": "m3", "o": "m3", "w": "m3", "d": "days"},
               "source": "BC Energy Regulator zone production (iris.bcogc.ca prod_csv.zip)", "wells": out},
              open(os.path.join(DATA, "prod", "wells.json"), "w"), separators=(",", ":"))
    print(f"{len(out)} of {len(wells)} region wells have production, through {latest}")


if __name__ == "__main__":
    main()
