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

# Max seconds a time label may disagree with the gridline/frame-edge fit
# before that fit is rejected. Labels are minute-rounded and their gridline
# spacing is uneven by up to a minute, so this has to sit above 60.
FRAME_FIT_TOL = 75


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


def _time_axis(spans, time_frame=None, time_grid=None):
    """date + 'HH:MM' span pairs -> abs seconds = a + b*cy. Label anchors
    snap to the time gridlines when the page provides them — edge labels
    shift inward from their gridline, which skews a label-only fit."""
    dates = [s for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{2,4}/\d{2}/\d{2,4}", s["t"])]
    times = [s for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    if len(times) < 3:
        return None, "", None
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
        return None, "", None
    # Liberty prints the first/last time labels AT the plot frame edges, but
    # the label TEXT sits several points inside the frame — a label-only fit
    # maps the first ~1-2 minutes of ink to negative time, which the export
    # window then cuts (Carmine's missing ramp starts). When the frame's
    # time extent is known, calibrate on the two edges and keep that fit only
    # if every label still lands on a gridline or edge under it.
    if time_frame:
        lo_e, hi_e = time_frame
        anchors = list(time_grid or []) + [lo_e, hi_e]
        by_cy = sorted(pts, key=lambda p: p[1])
        first, last = by_cy[0], by_cy[-1]
        span_lbl = abs(last[1] - first[1])
        if span_lbl > 1 and \
                abs(first[1] - lo_e) < span_lbl * 0.1 and \
                abs(last[1] - hi_e) < span_lbl * 0.1:
            a2, b2 = _fit([(first[0], lo_e), (last[0], hi_e)])
            if abs(b2) > 1e-12:
                # every label must sit on a gridline/edge under this fit.
                # Labels are minute-rounded and their spacing is uneven by
                # up to a minute, so judge at that scale — a tighter bound
                # rejects good fits and the window falls back to the label
                # span, which clips the stage's opening ramp.
                ok = all(abs(a2 + b2 * min(anchors, key=lambda g: abs(g - cy))
                             - secs) <= FRAME_FIT_TOL for secs, cy in pts)
                if ok:
                    win = tuple(sorted((a2 + b2 * lo_e, a2 + b2 * hi_e)))
                    return (a2, b2), (date0 or ""), win
    a, b = _fit(pts)
    if abs(b) < 1e-12:
        return None, "", None
    return (a, b), (date0 or ""), None


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
    # frame time extent: the value gridlines run the full time width of the
    # plot, so their span along the time axis marks the frame edges
    t_edges = []
    for d in page.get_drawings():
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        gx0, gy0, gx1, gy1 = (r.y0, r.x0, r.y1, r.x1) if horizontal \
            else (r.x0, r.y0, r.x1, r.y1)
        if abs(gx1 - gx0) < 0.5 and (gy1 - gy0) > 100:
            t_edges.append((gy0, gy1))
    time_frame = None
    if t_edges:
        time_frame = (min(e[0] for e in t_edges), max(e[1] for e in t_edges))
    # time gridlines (constant along time coord, long across values) anchor
    # the interior labels when validating the frame fit
    time_grid = []
    for d in page.get_drawings():
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        gx0, gy0, gx1, gy1 = (r.y0, r.x0, r.y1, r.x1) if horizontal \
            else (r.x0, r.y0, r.x1, r.y1)
        if abs(gy1 - gy0) < 0.5 and (gx1 - gx0) > 100:
            time_grid.append(round((gy0 + gy1) / 2, 2))
    time_grid = sorted(set(time_grid))
    tfit, date, frame_win = _time_axis(spans, time_frame, time_grid)
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
        # Liberty prints the zero tick of several axes as '-0' (the charting
        # tool's negative zero). Without the optional sign that tick was
        # dropped, so e.g. Treating Pressure came out 15..75 instead of 0..75
        # and Slurry Rate 4..20 instead of 0..20 — every curve on those axes
        # was then placed against the wrong range. '+ 0.0' normalises -0.0.
        if s["color"] != 0 and re.fullmatch(r"-?[\d,]+(\.\d+)?", s["t"]):
            ticks[s["color"]].append((float(s["t"].replace(",", "")) + 0.0,
                                      s["cx"], s["cy"]))
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
    # Clip curve ink to the plot FRAME, not to the time-LABEL span. The last
    # label sits inside the frame, so a label-span clip threw away every point
    # after it while the export window (taken from the frame) still ran to the
    # frame edge — the stage's last minutes came out empty. Measured on 00374:
    # 110-220s lost off the tail of every stage, 0 off the head, which is
    # exactly what Carmine reported ("the start looks ok").
    if time_frame:
        y_lo, y_hi = time_frame[0] - 10, time_frame[1] + 10
    else:
        y_lo, y_hi = min(tl_cy) - 10, max(tl_cy) + 10

    series = {}
    units = {}
    axes = {}          # name -> (axis_min, axis_max) from the printed ticks
    axis_fit = {}      # name -> (a, b) so the axis can be read AT the frame
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
        # The chart's OWN axis range for this curve, straight off its printed
        # tick labels. The Lab plots against this instead of guessing a top
        # from the data, so our y axis reads the same as the source report.
        axes[info["name"]] = (float(v_lo_ax), float(v_hi_ax))
        axis_fit[info["name"]] = (float(a), float(b))
    if not series:
        raise ValueError("lib1: no curves matched")

    # window = the labeled time span, matching Carmine's own exports: his
    # sample starts exactly at the first time label, not at the first ink
    if frame_win:
        t_lo, t_hi = frame_win
    else:
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
    # Ghost/compare stretches the page so v0..v1 fills our plot rect, and the
    # Lab draws each curve against its printed tick range. Those only agree if
    # v0/v1 are the page coords where the axis READS those tick values.
    # min/max of the gridlines is not that: there is no gridline at the axis
    # zero, so the lowest one sits ~11% of the span above it and the backdrop
    # rode up by that much. Invert each series' own fit instead and take the
    # median, so one noisy axis can't drag the frame.
    edges_lo, edges_hi = [], []
    for _n, (fa, fb) in axis_fit.items():
        if abs(fb) < 1e-12:
            continue
        lo_v, hi_v = axes[_n]
        edges_lo.append((lo_v - fa) / fb)
        edges_hi.append((hi_v - fa) / fb)
    if edges_lo and edges_hi:
        edges_lo.sort(); edges_hi.sort()
        p_lo = edges_lo[len(edges_lo) // 2]
        p_hi = edges_hi[len(edges_hi) // 2]
        v_lo_f, v_hi_f = min(p_lo, p_hi), max(p_lo, p_hi)
    else:
        v_lo_f = min(grid_xs) if grid_xs else x_lo
        v_hi_f = max(grid_xs) if grid_xs else x_hi
    meta.geom = {"axis": "x" if horizontal else "y",
                 "ta": float(ta - t_lo), "tb": float(tb),
                 "v0": float(v_lo_f), "v1": float(v_hi_f)}
    samples = np.arange(int(n / sample_sec)) * sample_sec
    # diagnostic: where each curve's INK actually starts/ends relative to the
    # export window, so truncated heads/tails can be measured rather than eyeballed
    meta.ink = {name: (float(t.min() - t_lo), float(t.max() - t_lo))
                for name, (t, _v) in series.items()}
    meta.window = float(n)
    data = {name: _resample(t - t_lo, v, samples) for name, (t, v) in series.items()}
    # The plot frame runs a little past the last recorded point, and the window
    # is taken from the frame so the opening ramp is never clipped. That left
    # 1-3 minutes of EMPTY rows at the end of every stage — what Carmine saw as
    # "not getting the ends of the pressure and rates". Trim to the last sample
    # any channel actually reaches. The head is deliberately untouched: t=0
    # must stay at the frame edge or the ramp start comes back off.
    if data:
        fin = np.zeros(len(samples), dtype=bool)
        for v in data.values():
            fin |= np.isfinite(np.asarray(v, dtype=float))
        if fin.any():
            last = int(np.nonzero(fin)[0][-1]) + 1
            if last < len(samples):
                samples = samples[:last]
                data = {k: np.asarray(v)[:last] for k, v in data.items()}
                meta.duration_min = (last * sample_sec) / 60.0
                meta.window = float(last)
    # printed axis range per curve; the Lab plots against these so its y
    # axis matches the source report instead of a value-derived guess.
    # axes_frame is the same axis read AT the plot-frame edges (what geom
    # v0/v1 spans) — ghost mode stretches the page between those edges, so
    # this is the range our curves must be placed against to sit on the ink.
    meta.axes = axes
    meta.axes_frame = {n: (af[0] + af[1] * v_lo_f, af[0] + af[1] * v_hi_f)
                       for n, af in axis_fit.items()}
    return meta, samples, data, units
