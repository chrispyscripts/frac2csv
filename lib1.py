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
    return "Liberty Energy" in t and \
        re.search(r"Stage\s+(?:[A-Z]{2,4}\s+)?\d", t, re.I) is not None


def _parse_date(txt):
    """'YYYY/MM/DD', 'MM/DD/YYYY' or 'MM/DD/YY' (2025 Vermilion-operated
    filings use the short US form) -> (year, month, day)."""
    a, b, c = (int(x) for x in txt.split("/"))
    if a > 1900:
        return a, b, c
    if c > 1900:
        return c, a, b
    return 2000 + c, a, b


def _time_axis(spans):
    """date + 'HH:MM' span pairs -> abs seconds = a + b*cy."""
    dates = [s for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{2,4}/\d{2}/\d{2,4}", s["t"])]
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
        y, mo, dd = _parse_date(best["t"])
        parts = [int(p) for p in ts["t"].split(":")]
        # absolute days (fixed epoch), NOT day-of-year — a stage crossing
        # Dec 31 -> Jan 1 must keep increasing (Carmine: day/month/year can
        # all change inside one chart)
        secs = (dt.date(y, mo, dd) - dt.date(2000, 1, 1)).days * 86400 + \
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


def _horizontal(spans):
    """True when the time axis runs along X (landscape charts, page rotation 0)
    rather than Y (the rotated pages this template was first built for)."""
    tl = [s for s in spans if s["color"] == 0 and
          re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    if len(tl) < 3:
        return False
    cxs = [s["cx"] for s in tl]
    cys = [s["cy"] for s in tl]
    return (max(cxs) - min(cxs)) > (max(cys) - min(cys))


def _clean_name(name):
    """Drop a leading wellbore/leg prefix like 'B: ' or 'B :' so the curve
    name matches Carmine's alias table (e.g. 'B: Treating Pressure')."""
    return re.sub(r"^[A-Za-z]\s*:\s*", "", name).strip()


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    text = page.get_text()
    # landscape charts run time along X; swap axes so the (rotated) logic below
    # — which expects time along Y — applies unchanged
    horizontal = _horizontal(spans)
    if horizontal:
        spans = [{**s, "cx": s["cy"], "cy": s["cx"]} for s in spans]
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
            named.setdefault(s["color"], {"name": _clean_name(m.group(1).strip()),
                                          "unit": m.group(2).strip()})
    # a black series (e.g. a chemical CONC drawn in black) shares ink with
    # axes/grid, so all black curves are indistinguishable — accept one only
    # when the page has EXACTLY one black-named series (else they'd merge into
    # garbage) and its unit matches a colored series' axis (shared via unit_fit).
    colored_units = {v["unit"] for v in named.values()}
    black = []
    for s in spans:
        if s["color"] != 0:
            continue
        m = re.fullmatch(r"(.+?)\s*\(([^)]+)\)", s["t"])
        if m and len(m.group(1)) > 3 and m.group(2).strip() in colored_units:
            cand = {"name": _clean_name(m.group(1).strip()), "unit": m.group(2).strip()}
            if cand not in black:
                black.append(cand)
    if len(black) == 1:
        named[0] = black[0]
    ticks = defaultdict(list)
    for s in spans:
        if s["color"] != 0 and re.fullmatch(r"[\d,]+(\.\d+)?", s["t"]):
            ticks[s["color"]].append((float(s["t"].replace(",", "")), s["cx"], s["cy"]))
    # value gridlines: long constant-x strokes. Tick LABELS sit ~12pt off
    # the gridline they annotate (left-aligned text), which biased every
    # value by a constant few units — snap each label to its gridline and
    # fit on true geometry (Carmine's 0422 comparison caught this).
    grid_xs = []
    for d in page.get_drawings():
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        gx0, gy0, gx1, gy1 = (r.y0, r.x0, r.y1, r.x1) if horizontal \
            else (r.x0, r.y0, r.x1, r.y1)
        if abs(gx1 - gx0) < 0.5 and (gy1 - gy0) > 100:
            grid_xs.append(round((gx0 + gx1) / 2, 2))
    grid_xs = sorted(set(grid_xs))
    snap_tol = min((b - a for a, b in zip(grid_xs, grid_xs[1:])),
                   default=0) * 0.45

    fits = {}
    for color, pts in ticks.items():
        if len(pts) < 4:
            continue
        cys = sorted(p[2] for p in pts)
        split = (cys[0] + cys[-1]) / 2
        side = [p for p in pts if p[2] < split] or pts
        if len(side) < 3:
            side = pts
        anchors = [(v, x) for v, x, _ in side]
        if grid_xs and snap_tol > 0:
            snapped = []
            for v, x in anchors:
                g = min(grid_xs, key=lambda gx: abs(gx - x))
                snapped.append((v, g if abs(g - x) <= snap_tol else x))
            # only trust the snap when it stays one-to-one and ordered
            xs = [x for _, x in snapped]
            if len(set(xs)) == len(xs) and \
                    (sorted(xs) == xs or sorted(xs, reverse=True) == xs):
                anchors = snapped
        a, b = _fit(anchors)
        if abs(b) > 1e-9:
            vals = [v for v, _, _ in pts]
            fits[color] = (a, b, min(vals), max(vals))
    if not named or not fits:
        raise ValueError("lib1: legend or tick rows not found")
    # share an axis by unit for series without their own tick row (black series)
    unit_fit = {}
    for color, f in fits.items():
        u = named.get(color, {}).get("unit", "")
        if u and u not in unit_fit:
            unit_fit[u] = f

    meta = PageMeta()
    # stage labels carry re-frac suffixes/prefixes ("4A", "5B", "HRF 5A",
    # "14A - HRF") — capture the whole token, not just the leading digits,
    # or distinct treatments collide into one stage. The "Stage X of N"
    # chart title is the most explicit form; fall back to a bare token.
    # keep a "Part I/II" continuation tag distinct — same-key charts merge
    # by sample index, which would silently drop the later part. Carmine's
    # naming: "Part I/II" (roman or arabic) -> "Attempt 1/2".
    m = (re.search(r"Stage\s+([A-Za-z0-9][A-Za-z0-9\- ]*?)\s+of\s+\d+"
                   r"(?:\s+Part\s+(\w+))?", text, re.I)
         or re.search(r"Stage\s+((?:[A-Z]{2,4}\s+)?\d+[A-Z]?(?:\s*-\s*[A-Z]{2,4})?)\b()",
                      text, re.I))
    if m:
        stage = " ".join(m.group(1).split())
        part = m.group(2)
        if part:
            roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
            n = roman.get(part.lower()) or (int(part) if part.isdigit() else None)
            stage += f" Attempt {n}" if n else f" Attempt {part}"
        meta.stage = stage
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    m = re.search(r"^(.*?)\s+Stage\s+", first, re.I)
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
        fit = fits.get(color_int) or unit_fit.get(info["unit"])
        if fit is None:
            continue
        a, b, v_lo_ax, v_hi_ax = fit
        pts = []
        for d in page.get_drawings():
            c = d.get("color")
            if c is None or d["type"] not in ("s", "fs"):
                continue
            if not _close(c, color_int):
                continue
            # curves are dense polylines (hundreds of items per drawing); an
            # isolated 1-2 item drawing that is one long axis-aligned line is
            # axis/marker ink in the series color — it puts phantom spikes on
            # the curve (Carmine's 00374 rate spikes). Real flat stretches
            # live inside the dense drawings, so they survive this filter.
            sparse = len(d["items"]) <= 2
            for item in d["items"]:
                if item[0] == "l":
                    x1, y1, x2, y2 = item[1].x, item[1].y, item[2].x, item[2].y
                    if horizontal:            # match the swapped span coords
                        x1, y1, x2, y2 = y1, x1, y2, x2
                    aligned = abs(x1 - x2) < 0.01 or abs(y1 - y2) < 0.01
                    seg = max(abs(x1 - x2), abs(y1 - y2))
                    if color_int == 0:
                        # black series shares ink with axes/grid: drop long
                        # axis-aligned segments (frame + gridlines)
                        if aligned and seg > 5:
                            continue
                    elif sparse and aligned and seg > 10:
                        continue
                    pts.append((x1, y1)); pts.append((x2, y2))
                elif item[0] == "c":
                    ax, ay, bx, by = item[1].x, item[1].y, item[4].x, item[4].y
                    if horizontal:
                        ax, ay, bx, by = ay, ax, by, bx
                    pts.append((ax, ay)); pts.append((bx, by))
        if len(pts) < 40:
            continue
        arr = np.array(pts)
        keep = ((arr[:, 0] >= x_lo) & (arr[:, 0] <= x_hi) &
                (arr[:, 1] >= y_lo) & (arr[:, 1] <= y_hi))
        arr = arr[keep]
        if len(arr) < 40:
            continue
        t = ta + tb * arr[:, 1]
        # clamp to the axis' own tick range: ink at the frame edge maps a
        # hair outside the scale and shows up as impossible negatives in
        # the CSV (Carmine's 0422 sample never goes below the axis)
        v = np.clip(a + b * arr[:, 0], v_lo_ax, v_hi_ax)
        order = np.argsort(t, kind="stable")
        series[info["name"]] = (t[order], v[order])
        units[info["name"]] = info["unit"]
    if not series:
        raise ValueError("lib1: no curves matched")

    # window = the labeled time span, matching Carmine's own exports: his
    # sample starts exactly at the first time label, not at the first ink
    label_ts = [ta + tb * cy for cy in tl_cy]
    t_lo, t_hi = min(label_ts), max(label_ts)
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        t_lo = min(t.min() for t, _ in series.values())
        t_hi = max(t.max() for t, _ in series.values())
        n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"lib1: implausible duration {n}s")
    meta.duration_min = n / 60.0
    day_sec = t_lo % 86400
    meta.start_time = (f"{int(day_sec // 3600):02d}:{int(day_sec % 3600 // 60):02d}"
                       f":{int(day_sec % 60):02d}")
    # chart geometry in PAGE coordinates for the synced original-chart view:
    # elapsed seconds e -> page coord along `axis` = (t_lo + e - ta) / tb;
    # v0/v1 span the plot across the other dimension. (For landscape pages
    # the swapped span coords mean the time map applies to page-x and the
    # tick extent to page-y — which is exactly what axis/v0/v1 encode.)
    meta.geom = {"axis": "x" if horizontal else "y",
                 "ta": float(ta - t_lo), "tb": float(tb),
                 "v0": float(x_lo), "v1": float(x_hi)}
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {name: _resample(t - t_lo, v, samples) for name, (t, v) in series.items()}
    return meta, samples, data, units
