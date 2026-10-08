"""The stage-metrics engine (web/scripts/build_stage_metrics.py) on stages made
up with known answers, its chart-to-filing matching by time, and the region as
built (data/metrics) against the filings."""
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "web", "scripts"))
import build_stage_metrics as B  # noqa: E402

DATA = os.path.join(HERE, "..", "web", "public", "data")


def stage(minutes=60, rate=10.0, conc=150.0, p=60.0, slope=0.0, falloff_s=120, isip=30.0, shut=None, end_rise=0.0):
    """a stage at 1 s: 2 min ramp, `minutes` at rate, then shut in"""
    n = int(minutes * 60) + 120
    t = np.arange(n + falloff_s, dtype=float)
    R = np.zeros_like(t)
    R[:120] = np.linspace(0.5, rate, 120)
    R[120:n] = rate
    P = np.full_like(t, np.nan)
    P[:n] = p + slope * (t[:n] / 60)
    if end_rise:
        P[n - 180:n] += np.linspace(0, end_rise, 180)
    P[n:] = isip - 0.01 * (t[n:] - t[n])          # a slow falloff from the ISIP
    C = np.zeros_like(t)
    C[600:n] = conc
    if shut:
        a, b = shut
        R[a:b] = 0
    return t, P, R, C


def test_timing_volumes_and_sand():
    t, P, R, C = stage()
    m = B.stage_metrics(t, P, R, C, 1.0)
    assert abs(m["pumpMin"] - 62) < 0.2          # the first seconds of the ramp are under the pumping threshold
    assert abs(m["atRateMin"] - 60.3) < 0.5
    assert abs(m["slurry"] - (10 * 60 + 10.25 * 2 / 2)) < 15
    # proppant: rate x conc per m3 of clean fluid over the sand-laden time
    sand_min = (len(t) - 120 - 600) / 60
    want = 10 * sand_min * 150 / (1 + 150 / 2650) / 1000
    assert abs(m["prop"] - want) / want < 0.01
    assert abs(m["clean"] - (m["slurry"] - m["prop"] * 1000 / 2650)) < 1e-6
    assert m["shape"] == "flat" and not m["flags"]


def test_isip_from_the_falloff():
    m = B.stage_metrics(*stage(isip=31.5), 1.0)
    assert abs(m["isip"] - 31.5) < 0.2
    m = B.stage_metrics(*stage(falloff_s=8), 1.0)          # the chart stops at shut-in
    assert m["isip"] is None


def test_flags():
    m = B.stage_metrics(*stage(end_rise=8.0), 1.0)
    assert "screenout" in m["flags"]
    m = B.stage_metrics(*stage(shut=(1800, 1900)), 1.0)
    assert m["shutdowns"] == 1 and "shutdown" in m["flags"]
    t, P, R, C = stage()
    P[2000:] -= 7.0                                         # a step down in pressure, rate unchanged
    m = B.stage_metrics(t, P, R, C, 1.0)
    assert "drop" in m["flags"]
    m = B.stage_metrics(*stage(slope=0.2), 1.0)             # 12 MPa over the hour: rising
    assert m["shape"] == "rising"


def test_charts_matched_to_filings_by_time():
    base = datetime(2022, 2, 8, 14, 0)
    filed = [base + timedelta(hours=6 * i) for i in range(6)]
    # the charts run an hour early, and one filed stage has no chart
    charts = [f - timedelta(minutes=55) for i, f in enumerate(filed) if i != 3]
    pairs = B.align(charts, filed)
    assert pairs == {0: 0, 1: 1, 2: 2, 3: 4, 4: 5}
    assert B.align([None, base], [base]) == {1: 0}


def test_frac_gradient():
    # 28 MPa at surface over 2,100 m TVD of fresh water: 13.33 + 9.81 kPa/m
    assert abs(B.frac_gradient(28.0, 2100, "Fresh Water") - 23.14) < 0.01
    assert abs(B.frac_gradient(28.0, 2100, "Saline Water") - (28000 / 2100 + 9.80665 * 1.07)) < 1e-9


def test_region_as_built():
    s = json.load(open(os.path.join(DATA, "metrics", "summary.json")))
    assert s["wellsCharted"] > 1000 and s["stagesCharted"] > 35000
    assert 0.95 < s["propRatioMedian"] < 1.05, "proppant from the curves matches the filings"
    assert s["propWithin20pct"] > 0.85 and s["fluidWithin10pct"] > 0.8
    assert abs(s["isipBiasMPa"]) < 1 and s["isipWithin2MPa"] > 0.6
    assert s["misplacedStages"] == 0, "no chart left at the wrong interval (run with --fix-depths)"
    d = json.load(open(os.path.join(DATA, "metrics", "pads", "gundy-01.json")))
    rows = [dict(zip(d["cols"], r)) for w in d["wells"].values() for r in w["rows"]]
    assert rows and all(r["n"] is not None for r in rows)
    for w in d["wells"].values():
        ns = [r[d["cols"].index("n")] for r in w["rows"] if r[d["cols"].index("src")] != "filed"]
        assert len(ns) == len(set(ns)), "one row per stage"
