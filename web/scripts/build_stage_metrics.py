"""FracView's stage metrics: numbers worked out from each stage's treatment
curves, each checked against what the operator filed with the BCER.

    python3 web/scripts/build_stage_metrics.py [--workers 6] [--fix-depths]

For every region well, per stage:

  timing      pump time, span (first to last pumping), time at rate, ramp-up
              time, mid-stage shutdowns (a minute or more with the rate down)
  pressure    average treating pressure at rate, peak, the slope at rate and
              over the last three minutes (MPa/min), an ISIP read from the
              falloff when the chart runs on past shut-in, frac gradient
  rate, sand  average and peak slurry rate, peak concentration, slurry and
              clean volume and proppant mass integrated from the curves,
              tonnes per pumping hour
  shape       the pressure at rate: rising, flat, falling or erratic
  flags       possible screenout, mid-stage shutdown, a pressure spike or a
              drop with no change in rate, a short stage, gaps in the curves,
              and disagreements with the filing (proppant, fluid, ISIP, depth)
  filed       the operator's own numbers for the same stage

The curves come from the Lab's 1-second exports (<report>-seconds.csv, found
under LAB_ROOTS) when they are on disk, else the ~360-point series already
in data/wells/<WA>.json (flags that need second-by-second detail are skipped
there). Each chart is matched to its filed stage by pumping time -- charts
and the BCER table list the same stages in the same order, a few minutes to
an hour or two apart -- with the stage number as the fallback when a chart
has no clock. Wells with no charts still get their filed numbers, so every
view can colour every well by what was filed.

Proppant is integrated as slurry rate x concentration per m3 of clean fluid
(1 + c/2650 of slurry); which convention the curves follow is checked against
the filed totals and reported in summary.json.

--fix-depths moves charts the import placed at the wrong interval (the
completion's port table numbered differently from the frac table) to the
interval filed for the stage they match in time, in data/wells/<WA>.json.

Writes data/metrics/pads/<pad>.json (every well's stage rows, for the views),
data/metrics/stages.json (every charted stage in the region, columnar, for
Discover) and data/metrics/summary.json (how well curves and filings agree).
"""
import argparse
import glob
import json
import math
import os
import re
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
REPO = os.path.dirname(WEB)
DATA = os.path.join(WEB, "public", "data")
sys.path.insert(0, REPO)
import well_json  # noqa: E402

LAB_ROOTS = [os.path.expanduser(p) for p in (
    os.environ.get("FRACVIEW_LAB_ROOTS", "").split(os.pathsep) if os.environ.get("FRACVIEW_LAB_ROOTS") else [])] + [
    os.path.expanduser("~/stratum-lab/region"), os.path.expanduser("~/stratum-lab/region-retry"),
    os.path.expanduser("~/stratum-lab/clusters"),
    os.path.join(os.path.dirname(REPO), "exports", "bc-gundy-cluster", "lab-seconds")]

SAND_KG_M3 = 2650.0
MATCH_MIN = 180          # a chart and a filed stage this far apart in time are not the same stage
DEPTH_M = 10             # a chart this far outside its filed interval is misplaced

COLS = ["n", "label", "date", "start", "top", "base", "tvd", "src",
        "pumpMin", "spanMin", "atRateMin", "rampMin", "shutdowns", "shutMin",
        "avgP", "maxP", "pSlope", "pEndSlope", "avgRate", "maxRate", "maxConc",
        "slurry", "clean", "prop", "tph", "isip", "isipFall", "fg",
        "fProp", "fFluid", "fIsip", "fBreak", "fAvgP", "fMaxP", "fRate", "fN", "dtMin",
        "shape", "flags"]
FLAGS = ["screenout", "shutdown", "spike", "drop", "short", "gaps", "qcProp", "qcFluid", "qcIsip", "depth"]
REGION_COLS = ["wa", "n", "date", "md", "tvd", "pumpMin", "atRateMin", "rampMin", "avgP", "maxP", "pSlope", "avgRate",
               "maxRate", "maxConc", "slurry", "clean", "prop", "tph", "isip", "fIsip", "fg", "fProp", "shape", "flags"]


def rnd(x, d=2):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, d) if math.isfinite(x) else None


def rollmed(a, k):
    if k <= 1 or len(a) < k:
        return a
    return pd.Series(a).rolling(k, center=True, min_periods=1).median().to_numpy()


def runs(mask):
    """(start, stop) of each run of True"""
    m = np.concatenate([[False], mask, [False]]).astype(int)
    d = np.diff(m)
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def slope(t, p):
    ok = np.isfinite(p)
    if ok.sum() < 5 or np.ptp(t[ok]) <= 0:
        return None
    return float(np.polyfit(t[ok] / 60.0, p[ok], 1)[0])


def stage_metrics(t, P, R, C, dt):
    """t seconds from the chart's start; P MPa, R m3/min, C kg/m3 (NaN where blank)."""
    fin = np.isfinite(R)
    if fin.sum() < 10:
        return None
    r95 = np.nanpercentile(R, 95)
    thr = max(0.3, 0.1 * r95)
    pump = fin & (R > thr)
    if pump.sum() * dt < 120:
        return None
    idx = np.flatnonzero(pump)
    i0, i1 = idx[0], idx[-1]
    k = max(1, int(round(3 / dt)))
    Pm, Rm, Cm = rollmed(P, k), rollmed(R, k), rollmed(C, k)
    out = {"pumpMin": pump.sum() * dt / 60, "spanMin": (t[i1] - t[i0] + dt) / 60}
    downs = [(a, b) for a, b in runs(~pump[i0:i1 + 1]) if (b - a) * dt >= 60]
    out["shutdowns"] = len(downs)
    out["shutMin"] = sum(b - a for a, b in downs) * dt / 60
    r90 = np.nanpercentile(R[pump], 90)
    at = pump & (R >= 0.85 * r90)
    out["atRateMin"] = at.sum() * dt / 60
    reach = np.flatnonzero((R >= 0.9 * r90) & fin)
    reach = reach[reach >= i0]
    out["rampMin"] = (t[reach[0]] - t[i0]) / 60 if reach.size else None
    out["avgP"] = float(np.nanmean(P[at])) if np.isfinite(P[at]).any() else None
    pp = Pm[i0:i1 + 1]
    out["maxP"] = float(np.nanmax(pp)) if np.isfinite(pp).any() else None
    out["pSlope"] = slope(t[at], P[at])
    endw = at & (t >= t[i1] - 180)
    out["pEndSlope"] = slope(t[endw], P[endw])
    out["avgRate"] = float(np.nanmean(R[at]))
    out["maxRate"] = float(np.nanmax(Rm[pump]))
    c = np.where(np.isfinite(C), C, 0.0)
    c = np.clip(c, 0, 3000)
    out["maxConc"] = float(np.nanmax(Cm[pump])) if np.isfinite(Cm[pump]).any() else None
    slurry = float(np.nansum(R[pump])) * dt / 60
    prop_kg = float(np.nansum(R[pump] * c[pump] / (1 + c[pump] / SAND_KG_M3))) * dt / 60
    out["slurry"] = slurry
    out["prop"] = prop_kg / 1000
    out["clean"] = slurry - prop_kg / SAND_KG_M3
    out["tph"] = out["prop"] / (out["pumpMin"] / 60) if out["pumpMin"] > 0 else None

    # ISIP: the falloff after the last pumping sample, a line through 10-70 s
    # after shut-in run back to the moment of shut-in (past the water hammer)
    after = (t > t[i1] + 10) & (t <= t[i1] + 70) & np.isfinite(P) & ~(np.isfinite(R) & (R > thr))
    tail = np.flatnonzero(np.isfinite(P) & (t > t[i1]))
    out["isipFall"] = float(t[tail[-1]] - t[i1]) if tail.size else 0.0
    out["isip"] = None
    if after.sum() * dt >= 20:
        a, b = np.polyfit(t[after] - t[i1], P[after], 1)[::-1]
        if 0 < a < (out["maxP"] or 1e9) and abs(b) < 0.2:
            out["isip"] = float(a)

    # the pressure at rate, middle 80% of the time at rate
    shape = None
    ai = np.flatnonzero(at)
    if ai.size >= 10 and out["avgP"]:
        lo, hi = ai[int(ai.size * .1)], ai[int(ai.size * .9) - 1]
        w = at.copy()
        w[:lo] = False
        w[hi + 1:] = False
        tt, pw = t[w], P[w]
        ok = np.isfinite(pw)
        if ok.sum() >= 10 and np.ptp(tt[ok]) > 0:
            fit = np.polyfit(tt[ok], pw[ok], 1)
            rise = fit[0] * np.ptp(tt[ok]) / out["avgP"]
            resid = float(np.std(pw[ok] - np.polyval(fit, tt[ok]))) / out["avgP"]
            shape = "erratic" if resid > 0.06 else ("rising" if rise > 0.08 else ("falling" if rise < -0.08 else "flat"))
    out["shape"] = shape

    flags = []
    # possible screenout: pressure climbing hard at the end, with sand still going in
    if out["maxConc"] and out["maxConc"] > 50 and out["avgP"]:
        endsand = np.nanmean(c[max(i0, i1 - int(120 / dt)):i1 + 1])
        last3 = (t >= t[i1] - 180) & (t <= t[i1]) & np.isfinite(P)
        early = (t >= t[i1] - 360) & (t < t[i1] - 180) & np.isfinite(P) & pump
        if last3.sum() > 3 and early.sum() > 3:
            rise = np.nanpercentile(P[last3], 90) - np.nanmedian(P[early])
            if rise >= max(3.0, 0.05 * out["avgP"]) and endsand > 0.25 * out["maxConc"]:
                flags.append("screenout")
    if out["shutdowns"]:
        flags.append("shutdown")
    if dt <= 2 and out["avgP"]:
        # a sudden jump or fall in pressure while the rate holds, past the breakdown
        # and before the shut-down
        w = int(20 / dt)
        body = np.zeros_like(pump)
        body[i0 + int(180 / dt):max(i0, i1 - int(120 / dt))] = True
        body &= at
        if body.sum() > w * 2:
            # the rate must hold for 30 s past the change too: on a chart the
            # pressure pen often leads the rate pen by a few seconds into a cut
            W2 = w + int(30 / dt)
            rev = pd.Series(Rm[::-1])
            fmax = rev.rolling(W2, min_periods=1).max().to_numpy()[::-1]
            fmin = rev.rolling(W2, min_periods=1).min().to_numpy()[::-1]
            held = (fmax - fmin) / np.maximum(Rm, 0.1) < 0.05
            ahead = np.zeros_like(body)
            ahead[:-W2] = body[W2:]
            dP = Pm[w:] - Pm[:-w]
            steady = body[w:] & body[:-w] & held[:-w] & ahead[:-w]
            if np.any(steady & (dP >= max(8.0, 0.12 * out["avgP"]))):
                flags.append("spike")
            if np.any(steady & (dP <= -max(5.0, 0.08 * out["avgP"]))):
                flags.append("drop")
    span = slice(i0, i1 + 1)
    blank = ~np.isfinite(P[span]) | ~np.isfinite(R[span])
    if blank.mean() > 0.1:
        flags.append("gaps")
    out["flags"] = flags
    return out


def read_seconds(path):
    """-> [(label, date, start, t, P, R, C)] in file order, from a Lab -seconds.csv"""
    head = pd.read_csv(path, nrows=0).columns.tolist()
    want = [c for c in ("STAGE", "DATETIME", "ELAPSED", "LABEL", "Tr Press", "Slurry Rate", "WH Prop Conc", "BH Prop Conc") if c in head]
    df = pd.read_csv(path, skiprows=[1], usecols=want, dtype={"STAGE": str, "LABEL": str, "DATETIME": str}, low_memory=False)
    lab = df["LABEL"].fillna(df["STAGE"]) if "LABEL" in df else df["STAGE"]
    df["_lab"] = lab.astype(str)
    out = []
    for label, g in df.groupby("_lab", sort=False):
        el = pd.to_numeric(g["ELAPSED"], errors="coerce").to_numpy(float) if "ELAPSED" in g else np.arange(len(g), dtype=float)
        if not np.isfinite(el).any():
            el = np.arange(len(g), dtype=float)
        t = el - np.nanmin(el)
        num = lambda c: pd.to_numeric(g[c], errors="coerce").to_numpy(float) if c in g else np.full(len(g), np.nan)
        wh, bh = num("WH Prop Conc"), num("BH Prop Conc")
        C = wh if np.nansum(np.abs(wh)) > 0 else bh
        dtv = str(g["DATETIME"].iloc[0]) if "DATETIME" in g else ""
        date, start = (dtv.split(" ") + ["", ""])[:2]
        if date.startswith("2000-01-01") or date == "nan":
            date, start = "", ""
        out.append((label, date, start, t, num("Tr Press"), num("Slurry Rate"), C))
    return out


def when(date, start):
    try:
        return datetime.strptime(f"{date} {start[:8] if len(start) >= 8 else start[:5]}",
                                 "%Y-%m-%d %H:%M:%S" if len(start) >= 8 else "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


def align(charts, filed):
    """charts and filed stages in time order -> {chart index: filed index}, order kept.
    Each is a list of datetimes (None when unknown)."""
    ci = [i for i, d in enumerate(charts) if d]
    fi = [j for j, d in enumerate(filed) if d]
    ci.sort(key=lambda i: charts[i])
    fi.sort(key=lambda j: filed[j])
    n, m = len(ci), len(fi)
    if not n or not m:
        return {}
    INF = float("inf")
    cost = np.full((n + 1, m + 1), INF)
    back = np.zeros((n + 1, m + 1), dtype=np.int8)
    cost[0, :] = np.arange(m + 1)
    cost[:, 0] = np.arange(n + 1)
    for a in range(1, n + 1):
        ta = charts[ci[a - 1]]
        for b in range(1, m + 1):
            gap = abs((ta - filed[fi[b - 1]]).total_seconds()) / 60
            best, how = cost[a - 1, b] + 1, 1
            if cost[a, b - 1] + 1 < best:
                best, how = cost[a, b - 1] + 1, 2
            if gap <= MATCH_MIN and cost[a - 1, b - 1] + gap / MATCH_MIN < best:
                best, how = cost[a - 1, b - 1] + gap / MATCH_MIN, 3
            cost[a, b], back[a, b] = best, how
    out, a, b = {}, n, m
    while a > 0 and b > 0:
        h = back[a, b]
        if h == 3:
            out[ci[a - 1]] = fi[b - 1]
            a, b = a - 1, b - 1
        elif h == 1:
            a -= 1
        else:
            b -= 1
    return out


def tvd_at(traj, md):
    if md is None or not traj or not traj.get("md"):
        return None
    m = np.asarray(traj["md"], float)
    v = np.asarray(traj["tvd"], float)
    ok = np.isfinite(m) & np.isfinite(v)
    if ok.sum() < 2:
        return None
    return float(np.interp(md, m[ok], v[ok]))


def fluid_sg(base):
    return 1.07 if base and "saline" in str(base).lower() and "non" not in str(base).lower() else 1.0


def frac_gradient(isip, tvd, base):
    """kPa/m: the surface ISIP plus the column of what was pumped, over TVD"""
    if not isip or not tvd:
        return None
    return isip * 1000 / tvd + 9.80665 * fluid_sg(base)


def seconds_index():
    idx = {}
    for root in LAB_ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.endswith("-seconds.csv"):
                    idx.setdefault(f, os.path.join(dp, f))
    return idx


def work(job):
    """one well -> its stage rows, totals and (optionally) a fixed stage list"""
    wa, pad_well, csv_path = job
    traj = pad_well.get("trajectory") or {}
    filed = sorted(pad_well.get("stages") or [], key=lambda s: s.get("n") or 0)
    path_w = os.path.join(DATA, "wells", f"{wa}.json")
    doc = json.load(open(path_w)) if os.path.exists(path_w) else {}
    stages = doc.get("stages") or []
    lab = [s for s in stages if s.get("series")]

    charts = []          # (json stage, t, P, R, C, dt, src)
    if lab and csv_path:
        try:
            groups = read_seconds(csv_path)
        except Exception as e:  # noqa: BLE001 -- a bad export falls back to the thinned series
            groups, err = [], str(e)
        keyed = {}
        for g in groups:
            keyed.setdefault((well_json._label(g[0]), g[1], g[2]), []).append(g)
        for s in lab:
            hit = keyed.get((s.get("label"), s.get("date") or "", s.get("start") or ""))
            if hit:
                _l, _d, _s, t, P, R, C = hit.pop(0)
                charts.append((s, t, P, R, C, 1.0, "1 s"))
    if lab and len(charts) < len(lab):
        done = {id(c[0]) for c in charts}
        for s in lab:
            if id(s) in done:
                continue
            ser, step = s.get("series") or {}, float(s.get("step_s") or 10)
            P = np.asarray([np.nan if v is None else v for v in ser.get("press", [])], float)
            if not P.size:
                continue
            R = np.asarray([np.nan if v is None else v for v in ser.get("rate", [])], float)
            cser = ser.get("wh_conc") if any(v for v in (ser.get("wh_conc") or []) if v) else ser.get("bh_conc")
            C = np.asarray([np.nan if v is None else v for v in (cser or [])], float)
            L = min(P.size, R.size) if R.size else 0
            if not L:
                continue
            C = C[:L] if C.size >= L else np.full(L, np.nan)
            charts.append((s, np.arange(L) * step, P[:L], R[:L], C, step, f"{int(step)} s"))

    # charts against filed stages, by time
    ct = [when(c[0].get("date") or "", c[0].get("start") or "") for c in charts]
    ft = [when(f.get("date") or "", f.get("start") or "") for f in filed]
    pairs = align(ct, ft)
    by_n = {f.get("n"): j for j, f in enumerate(filed)}
    for i, c in enumerate(charts):
        if i not in pairs and c[0].get("n") in by_n and not any(v == by_n[c[0]["n"]] for v in pairs.values()):
            pairs[i] = by_n[c[0]["n"]]
    matched_by_time = sum(1 for i in pairs if ct[i] and ft[pairs[i]])
    # a match is trusted when it keeps to the well's usual lag between chart
    # clock and filed start (charts often run an hour or two off the filing)
    lags = [(ct[i] - ft[j]).total_seconds() / 60 for i, j in pairs.items() if ct[i] and ft[j]]
    lag = st.median(lags) if len(lags) >= 3 else None
    trusted = {i for i, j in pairs.items() if lag is not None and ct[i] and ft[j]
               and abs((ct[i] - ft[j]).total_seconds() / 60 - lag) <= 45}

    rows, fixes, used = [], [], set()
    for i, (s, t, P, R, C, dt, src) in enumerate(charts):
        m = stage_metrics(t, P, R, C, dt) or {"flags": []}
        f = filed[pairs[i]] if i in pairs else {}
        if i in pairs:
            used.add(pairs[i])
        top, base = s.get("top_m"), s.get("base_m")
        flags = list(m.get("flags", []))
        if f and f.get("top_m") is not None and i in trusted and (top is None or not (
                f["top_m"] - DEPTH_M <= top <= (f.get("base_m") or f["top_m"]) + DEPTH_M)):
            flags.append("depth")
            # move it only where the import guessed the interval (from the port
            # table by number or order), never where the report printed it
            if top is None or any("BCER" in x or "order" in x for x in s.get("notes", [])):
                fixes.append((s, f))
        mid = None
        if f.get("top_m") is not None:
            mid = (f["top_m"] + (f.get("base_m") or f["top_m"])) / 2
        elif top is not None:
            mid = (top + (base or top)) / 2
        tvd = tvd_at(traj, mid)
        fp, ff, fi = f.get("proppant_t"), f.get("fluid_m3"), f.get("isip_mpa")
        fi = fi if fi and fi >= 5 else None          # an ISIP under 5 MPa is a typo in the filing
        if fp and fp >= 5 and m.get("prop") is not None and abs(m["prop"] - fp) / fp > 0.2:
            flags.append("qcProp")
        if ff and ff >= 20 and m.get("clean") is not None and abs(m["clean"] - ff) / ff > 0.2:
            flags.append("qcFluid")
        if fi and m.get("isip") and abs(m["isip"] - fi) > 3:
            flags.append("qcIsip")
        isip = fi or m.get("isip")
        rows.append({
            "n": f.get("n", s.get("n")), "label": s.get("label"), "date": s.get("date") or f.get("date"),
            "start": s.get("start") or f.get("start"), "top": f.get("top_m", top), "base": f.get("base_m", base),
            "tvd": rnd(tvd, 0), "src": src, **{k: m.get(k) for k in (
                "pumpMin", "spanMin", "atRateMin", "rampMin", "shutdowns", "shutMin", "avgP", "maxP", "pSlope",
                "pEndSlope", "avgRate", "maxRate", "maxConc", "slurry", "clean", "prop", "tph", "isip", "isipFall", "shape")},
            "fg": frac_gradient(isip, tvd, f.get("base_fluid")),
            "fProp": fp, "fFluid": ff, "fIsip": fi, "fBreak": f.get("breakdown_mpa"), "fAvgP": f.get("avg_pressure_mpa"),
            "fMaxP": f.get("max_pressure_mpa") if (f.get("max_pressure_mpa") or 0) <= 150 else None,
            "fRate": f.get("avg_rate_m3_min"), "fN": f.get("n"),
            "dtMin": rnd((ct[i] - ft[pairs[i]]).total_seconds() / 60, 0) if i in pairs and ct[i] and ft[pairs[i]] else None,
            "flags": flags})

    # a short stage: well under the well's usual pump time and sand
    pm = [r["pumpMin"] for r in rows if r.get("pumpMin")]
    pr = [r["prop"] for r in rows if r.get("prop")]
    if len(pm) >= 5:
        mp, mprop = st.median(pm), (st.median(pr) if len(pr) >= 5 else None)
        for r in rows:
            if r.get("pumpMin") and r["pumpMin"] < 0.5 * mp and (not mprop or (r.get("prop") or 0) < 0.5 * mprop):
                r["flags"].append("short")

    # filed stages with no chart: their own numbers
    for j, f in enumerate(filed):
        if j in used:
            continue
        mid = (f["top_m"] + (f.get("base_m") or f["top_m"])) / 2 if f.get("top_m") is not None else None
        tvd = tvd_at(traj, mid)
        rows.append({"n": f.get("n"), "label": f.get("label"), "date": f.get("date"), "start": f.get("start"),
                     "top": f.get("top_m"), "base": f.get("base_m"), "tvd": rnd(tvd, 0), "src": "filed",
                     "fg": frac_gradient(f.get("isip_mpa") if (f.get("isip_mpa") or 0) >= 5 else None, tvd, f.get("base_fluid")),
                     "fProp": f.get("proppant_t"), "fFluid": f.get("fluid_m3"), "fIsip": f.get("isip_mpa"),
                     "fBreak": f.get("breakdown_mpa"), "fAvgP": f.get("avg_pressure_mpa"),
                     "fMaxP": f.get("max_pressure_mpa") if (f.get("max_pressure_mpa") or 0) <= 150 else None,
                     "fRate": f.get("avg_rate_m3_min"), "fN": f.get("n"), "flags": []})
    # toe first; rows without a depth by stage number
    rows.sort(key=lambda r: (r["top"] is None, -(r["top"] or 0), r["n"] if isinstance(r["n"], (int, float)) else 1e9))

    charted = [r for r in rows if r["src"] != "filed"]
    tot = {
        "stagesFiled": len(filed), "stagesCharted": len(charted), "matchedByTime": matched_by_time,
        "src": charts[0][6] if charts else None, "file": doc.get("file"),
        "prop": rnd(sum(r["prop"] for r in charted if r.get("prop")), 1) if charted else None,
        "propFiled": rnd(sum(f.get("proppant_t") or 0 for f in filed), 1) or None,
        "propFiledCharted": rnd(sum(r["fProp"] for r in charted if r.get("fProp")), 1) or None,
        "clean": rnd(sum(r["clean"] for r in charted if r.get("clean")), 0) if charted else None,
        "fluidFiled": rnd(sum(f.get("fluid_m3") or 0 for f in filed), 0) or None,
        "fluidFiledCharted": rnd(sum(r["fFluid"] for r in charted if r.get("fFluid")), 0) or None,
        "pumpHours": rnd(sum(r["pumpMin"] for r in charted if r.get("pumpMin")) / 60, 1) if charted else None,
        "flagged": sum(1 for r in charted if any(x for x in r["flags"] if not x.startswith("qc") and x != "depth")),
        "misplaced": len(fixes),
    }
    for k in ("pumpMin", "tph", "avgP", "isip", "fg", "avgRate", "rampMin"):
        v = [r[k] for r in rows if r.get(k) is not None]
        tot[k + "Med"] = rnd(st.median(v), 2) if v else None
    return wa, rows, tot, [(s.get("label"), s.get("date"), s.get("start"), f.get("n"), f.get("top_m"), f.get("base_m"),
                            s.get("top_m")) for s, f in fixes]


def pack(rows):
    def cell(r, k):
        v = r.get(k)
        if k == "flags":
            return sum(1 << FLAGS.index(x) for x in set(v or []))
        if isinstance(v, float):
            return rnd(v, 3 if k in ("pSlope", "pEndSlope") else 2)
        return v
    return [[cell(r, k) for k in COLS] for r in rows]


def fix_depths(fixes, padw):
    """move misplaced charts to the interval filed for the stage they match in
    time; the well's depth-only rows become the filed stages no chart is on"""
    for wa, items in fixes.items():
        path = os.path.join(DATA, "wells", f"{wa}.json")
        doc = json.load(open(path))
        moved = 0
        for label, date, start, fn, top, base, old in items:
            for s in doc["stages"]:
                if s.get("series") and s.get("label") == label and (s.get("date") or None) == (date or None) \
                        and (s.get("start") or None) == (start or None):
                    s.update(n=fn, top_m=top, base_m=base, placed=False)
                    s["notes"] = [x for x in s.get("notes", []) if "from the completion's order" not in x and "matched by" not in x]
                    s["notes"].append(f"interval from the BCER frac table, stage {fn}, matched by pumping time"
                                      + (f" (the import had it at {old:g} m)" if old is not None else ""))
                    moved += 1
                    break
        charts = [s for s in doc["stages"] if s.get("series")]
        taken = {s["n"] for s in charts}
        rest = []
        for f in (padw.get(wa) or {}).get("stages") or []:
            if f.get("n") in taken:
                continue
            row = dict(f)
            row.update(placed=False, start=f.get("start") or "", clock_chart=False, minutes=0, step_s=0, page=None,
                       series={}, peaks={}, notes=["filed with the BCER; treatment curves await the Lab export"])
            rest.append(row)
        doc["stages"] = sorted(charts + rest, key=lambda s: (s.get("n") is None, s.get("n") or 0))
        json.dump(doc, open(path, "w"), separators=(",", ":"))
        print(f"  {wa}: {moved} charts moved to their filed intervals")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 2)))
    ap.add_argument("--fix-depths", action="store_true")
    ap.add_argument("--only", help="comma-separated WA numbers (testing)")
    a = ap.parse_args()

    secs = seconds_index()
    pads = {}
    jobs = []
    only = set(x.zfill(5) for x in a.only.split(",")) if a.only else None
    for f in sorted(glob.glob(os.path.join(DATA, "region", "pads", "*.json"))):
        pad = json.load(open(f))
        pads[pad["id"]] = pad
        for w in pad["wells"]:
            wa = str(int(w["well"]["wa"])).zfill(5)
            if only and wa not in only:
                continue
            path_w = os.path.join(DATA, "wells", f"{wa}.json")
            csv_path = None
            if os.path.exists(path_w):
                fname = (json.load(open(path_w)).get("file") or "")
                stem = re.sub(r"\.pdf$", "", fname, flags=re.I)
                csv_path = secs.get(stem + "-seconds.csv") if stem else None
            jobs.append((wa, w, csv_path))
    print(f"{len(jobs)} wells, {sum(1 for j in jobs if j[2])} with a 1-second export on disk", flush=True)

    results = {}
    with ProcessPoolExecutor(a.workers) as ex:
        for k, (wa, rows, tot, fixes) in enumerate(ex.map(work, jobs, chunksize=4)):
            results[wa] = (rows, tot, fixes)
            if k % 250 == 0:
                print(f"  {k}/{len(jobs)}", flush=True)

    padof = {}
    for pid, pad in pads.items():
        for w in pad["wells"]:
            padof[str(int(w["well"]["wa"])).zfill(5)] = pid
    out = os.path.join(DATA, "metrics")
    os.makedirs(os.path.join(out, "pads"), exist_ok=True)
    by_pad = {}
    for wa, (rows, tot, _f) in results.items():
        by_pad.setdefault(padof[wa], {})[wa] = {"totals": tot, "rows": pack(rows)}
    if not only:
        for old in glob.glob(os.path.join(out, "pads", "*.json")):
            if os.path.basename(old)[:-5] not in by_pad:
                os.remove(old)
    for pid, wells in by_pad.items():
        path = os.path.join(out, "pads", f"{pid}.json")
        doc = {"v": 1, "pad": pid, "cols": COLS, "flags": FLAGS, "wells": {}}
        if only and os.path.exists(path):
            doc = json.load(open(path))
        doc["wells"].update(wells)
        json.dump(doc, open(path, "w"), separators=(",", ":"))

    # the region's charted stages, for Discover
    reg = []
    for wa, (rows, _t, _f) in sorted(results.items()):
        for r in rows:
            if r["src"] == "filed" or r.get("pumpMin") is None:
                continue
            md = (r["top"] + (r["base"] or r["top"])) / 2 if r.get("top") is not None else None
            reg.append([wa if k == "wa" else (rnd(md, 0) if k == "md" else r.get(k)) for k in REGION_COLS])
    for row in reg:
        for i, k in enumerate(REGION_COLS):
            if k == "flags":
                row[i] = sum(1 << FLAGS.index(x) for x in set(row[i] or []))
            elif isinstance(row[i], float):
                row[i] = rnd(row[i], 3 if k == "pSlope" else 2)

    # how well the curves and the filings agree
    def ratio(a_, b_):
        return a_ / b_ if a_ and b_ else None
    prop_r = [ratio(t["prop"], t["propFiledCharted"]) for _r, t, _f in results.values()]
    prop_r = [x for x in prop_r if x and 0.2 < x < 5]
    fl_r = [ratio(t["clean"], t["fluidFiledCharted"]) for _r, t, _f in results.values()]
    fl_r = [x for x in fl_r if x and 0.2 < x < 5]
    isip_d = [r["isip"] - r["fIsip"] for rows, _t, _f in results.values() for r in rows if r.get("isip") and r.get("fIsip")]
    charted = [r for rows, _t, _f in results.values() for r in rows if r["src"] != "filed"]
    fixes = {wa: f for wa, (_r, _t, f) in results.items() if f}
    summary = {
        "v": 1, "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "wells": len(results), "wellsCharted": sum(1 for _r, t, _f in results.values() if t["stagesCharted"]),
        "stagesCharted": len(charted), "from1s": sum(1 for r in charted if r["src"] == "1 s"),
        "matchedByTime": sum(t["matchedByTime"] for _r, t, _f in results.values()),
        "propRatioMedian": rnd(st.median(prop_r), 3) if prop_r else None,
        "propWithin10pct": rnd(sum(1 for x in prop_r if abs(x - 1) <= 0.1) / len(prop_r), 3) if prop_r else None,
        "propWithin20pct": rnd(sum(1 for x in prop_r if abs(x - 1) <= 0.2) / len(prop_r), 3) if prop_r else None,
        "fluidRatioMedian": rnd(st.median(fl_r), 3) if fl_r else None,
        "fluidWithin10pct": rnd(sum(1 for x in fl_r if abs(x - 1) <= 0.1) / len(fl_r), 3) if fl_r else None,
        "isipStages": len(isip_d), "isipBiasMPa": rnd(st.median(isip_d), 2) if isip_d else None,
        "isipWithin2MPa": rnd(sum(1 for x in isip_d if abs(x) <= 2) / len(isip_d), 3) if isip_d else None,
        "isipFromCurves": sum(1 for r in charted if r.get("isip")),
        "flagCounts": {f: sum(1 for r in charted if f in r["flags"]) for f in FLAGS},
        "misplacedWells": len(fixes), "misplacedStages": sum(len(f) for f in fixes.values()),
    }
    if not only:
        json.dump({"v": 1, "columns": REGION_COLS, "flags": FLAGS, "rows": reg}, open(os.path.join(out, "stages.json"), "w"),
                  separators=(",", ":"))
        json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))
    if a.fix_depths and fixes:
        padw = {str(int(w["well"]["wa"])).zfill(5): w for pad in pads.values() for w in pad["wells"]}
        fix_depths(fixes, padw)
        print("charts moved; run this again (without --fix-depths) so the metrics see them where they are")


if __name__ == "__main__":
    main()
