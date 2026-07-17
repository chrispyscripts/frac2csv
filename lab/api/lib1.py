"""Liberty Energy chart template (Lib-1 in Carmine's codes).

Rotated per-stage pages, one stage per page: each series has a COLORED
name span ("Treating Pressure (MPa)") and a matching colored tick row
(value along x). Time labels are date+HH:MM pairs along y, so absolute
time needs no midnight unwrapping. Structure is the Leucrotta family;
this template supplies Liberty's detection, metadata and time axis.
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta, _resample
from leucrotta import _fit, _close, _spans


def detect(page):
    t = page.get_text()
    return "Liberty Energy" in t and re.search(r"Stage\s+\d+", t) is not None


def _time_axis(spans):
    """date 'YYYY/MM/DD' + 'HH:MM' span pairs -> abs seconds = a + b*cy."""
    dates = [s for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{4}/\d{2}/\d{2}", s["t"])]
    times = [s for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    if len(times) < 3:
        return None, ""
    import datetime as dt
    pts = []
    date0 = None
    for ts in times:
        # nearest date label
        best = min(dates, key=lambda d: abs(d["cy"] - ts["cy"])) if dates else None
        if best is None or abs(best["cy"] - ts["cy"]) > 40:
            continue
        y, mo, dd = (int(x) for x in best["t"].split("/"))
        parts = [int(p) for p in ts["t"].split(":")]
        secs = (dt.date(y, mo, dd) - dt.date(y, 1, 1)).days * 86400 + \
            parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)
        pts.append((secs, ts["cy"]))
        if date0 is None:
            date0 = f"{y:04d}-{mo:02d}-{dd:02d}"
    if len(pts) < 3:
        return None, ""
    a, b = _fit(pts)
    if abs(b) < 1e-12:
        return None, ""
    return (a, b), (date0 or "")


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    text = page.get_text()
    tfit, date = _time_axis(spans)
    if tfit is None:
        raise ValueError("lib1: time labels not found")
    ta, tb = tfit

    # colored series: name span "<Name> (<unit>)" + same-color numeric ticks
    named = {}
    for s in spans:
        if s["color"] == 0:
            continue
        m = re.fullmatch(r"(.+?)\s*\(([^)]+)\)", s["t"])
        if m and len(m.group(1)) > 3:
            named.setdefault(s["color"], {"name": m.group(1).strip(),
                                          "unit": m.group(2).strip()})
    ticks = defaultdict(list)
    for s in spans:
        if s["color"] != 0 and re.fullmatch(r"[\d,]+(\.\d+)?", s["t"]):
            ticks[s["color"]].append((float(s["t"].replace(",", "")), s["cx"], s["cy"]))
    fits = {}
    for color, pts in ticks.items():
        if len(pts) < 4:
            continue
        cys = sorted(p[2] for p in pts)
        split = (cys[0] + cys[-1]) / 2
        side = [p for p in pts if p[2] < split] or pts
        if len(side) < 3:
            side = pts
        a, b = _fit([(v, x) for v, x, _ in side])
        if abs(b) > 1e-9:
            fits[color] = (a, b)
    if not named or not fits:
        raise ValueError("lib1: legend or tick rows not found")

    meta = PageMeta()
    m = re.search(r"Stage\s+(\d+)", text)
    if m:
        meta.stage = m.group(1)
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    m = re.search(r"^(.*?)\s+Stage\s+\d+", first)
    meta.title = (m.group(1) if m else first)[:60]
    meta.date = date

    tick_x = [x for pts in ticks.values() for _, x, _ in pts]
    x_lo, x_hi = min(tick_x) - 10, max(tick_x) + 10
    tl_cy = [s["cy"] for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    y_lo, y_hi = min(tl_cy) - 10, max(tl_cy) + 10

    series = {}
    units = {}
    for color_int, info in named.items():
        fit = fits.get(color_int)
        if fit is None:
            continue
        a, b = fit
        pts = []
        for d in page.get_drawings():
            c = d.get("color")
            if c is None or d["type"] not in ("s", "fs"):
                continue
            if not _close(c, color_int):
                continue
            for item in d["items"]:
                if item[0] == "l":
                    pts.append((item[1].x, item[1].y))
                    pts.append((item[2].x, item[2].y))
                elif item[0] == "c":
                    pts.append((item[1].x, item[1].y))
                    pts.append((item[4].x, item[4].y))
        if len(pts) < 40:
            continue
        arr = np.array(pts)
        keep = ((arr[:, 0] >= x_lo) & (arr[:, 0] <= x_hi) &
                (arr[:, 1] >= y_lo) & (arr[:, 1] <= y_hi))
        arr = arr[keep]
        if len(arr) < 40:
            continue
        t = ta + tb * arr[:, 1]
        v = a + b * arr[:, 0]
        order = np.argsort(t, kind="stable")
        series[info["name"]] = (t[order], v[order])
        units[info["name"]] = info["unit"]
    if not series:
        raise ValueError("lib1: no curves matched")

    t_lo = min(t.min() for t, _ in series.values())
    t_hi = max(t.max() for t, _ in series.values())
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"lib1: implausible duration {n}s")
    meta.duration_min = n / 60.0
    day_sec = t_lo % 86400
    meta.start_time = (f"{int(day_sec // 3600):02d}:{int(day_sec % 3600 // 60):02d}"
                       f":{int(day_sec % 60):02d}")
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {name: _resample(t - t_lo, v, samples) for name, (t, v) in series.items()}
    return meta, samples, data, units
