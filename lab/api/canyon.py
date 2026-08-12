"""Canyon Technical Services chart template (Canyon-1 in Carmine's codes).

One page per interval: three stacked panels — Pressure (MPa), Rate (m³/min),
Concentration (kg/m³) — sharing an HH:MM time axis. Legends are black text
names preceded by colored line samples, so color↔series mapping comes from
the stroke nearest each name. Header block: Ticket#, Customer, LSD (DLS
UWI), Date, Interval "#N - depth".
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta, _resample

PANEL_UNITS = {"Pressure": "MPa", "Rate": "m³/min", "Concentration": "kg/m³"}


def detect(page):
    t = page.get_text()
    has_ticket = "Ticket#:" in t or "Ticket #:" in t
    return has_ticket and ("Pressure (MPa)" in t or "Rate (m³/min)" in t)


def _spans(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    x0, y0, x1, y1 = span["bbox"]
                    out.append({"t": t, "x0": x0, "x1": x1,
                                "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def _fit(pairs):
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    A = np.vstack([np.ones_like(c), c]).T
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(a), float(b)


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    text = page.get_text()

    meta = PageMeta()
    m = re.search(r"(1[0-9A-F]\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups())
    else:
        m = re.search(r"\b([a-dA-D])-?([A-Z]?\d{2,3})-([A-L])\s*/\s*0?(\d{2,3})-([A-P])-0?(\d{1,2})\b", text)
        if m:
            q, unit, blk, sheet, letter, num = m.groups()
            unit_num = unit if unit[:1].isalpha() else f"{int(unit):03d}"
            meta.uwi = (f"200{q.upper()}{unit_num}{blk.upper()}"
                        f"{int(sheet):03d}{letter.upper()}{int(num):02d}00")
    # Labels and values are separated in the text stream, so the interval has
    # to be found by its own shape rather than by what it sits next to —
    # reading the span after the "Interval:" LABEL hands back the ticket
    # number. The 2014 layout prints "#1 - 3709.32m"; the 2017 ones print a
    # bare "#1" (00204) or drop the "Interval:" label altogether and print the
    # number alone (00203, Painted Pony). Requiring the depth left every chart
    # page of both 2017 families with NO stage at all, so nothing could be
    # joined to a table by interval. Checked across all 92 chart pages of
    # 00009, 00203 and 00204: each has exactly ONE "#N" on it and the sequence
    # runs in order, so the bare form is safe to fall back to. A ticket number
    # is never at risk — those print as "Ticket#: 40-015318", digits separated
    # from the "#" by the colon.
    m = (re.search(r"#(\d+)\s*-\s*[\d,.]+\s*m\b", text)
         or re.search(r"#\s*(\d+)\b", text))
    if m:
        meta.stage = m.group(1)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        meta.date = m.group(0)
    meta.title = f"Canyon interval {meta.stage or '?'}"

    # panels: title spans mark panel tops
    panels = []
    for s in spans:
        pm = re.match(r"(Pressure|Rate|Concentration)\s*\(", s["t"])
        if pm:
            panels.append({"name": pm.group(1), "title_y": s["cy"], "x": s["cx"]})
    if not panels:
        raise ValueError("canyon: no panel titles")
    panels.sort(key=lambda p: p["title_y"])
    page_h = page.rect.height
    for i, p in enumerate(panels):
        p["y_end"] = panels[i + 1]["title_y"] if i + 1 < len(panels) else page_h

    # per-panel: y-axis ticks (black numerals, left column), time row, legend
    drawings = page.get_drawings()
    all_series = {}
    units = {}
    t_fit_global = None
    for p in panels:
        band = [s for s in spans if p["title_y"] < s["cy"] < p["y_end"]]
        nums = [s for s in band if re.fullmatch(r"[\d,]+(\.\d+)?", s["t"])]
        if not nums:
            continue
        left_x = min(s["cx"] for s in nums)
        ticks = [s for s in band if re.fullmatch(r"[\d,]+(\.\d+)?", s["t"])
                 and s["cx"] < left_x + 25]
        if len(ticks) < 3:
            continue
        vfit = _fit([(float(s["t"].replace(",", "")), s["cy"]) for s in ticks])
        y_lo = min(s["cy"] for s in ticks) - 8
        y_hi = max(s["cy"] for s in ticks) + 8

        tl = [s for s in band if re.fullmatch(r"\d{1,2}:\d{2}", s["t"])]
        if len(tl) >= 3:
            vals = []
            for s in sorted(tl, key=lambda s: s["cx"]):
                h, mnt = s["t"].split(":")
                vals.append((int(h) * 3600 + int(mnt) * 60, s["cx"]))
            for i in range(1, len(vals)):
                if vals[i][0] < vals[i - 1][0] - 20000:
                    vals[i] = (vals[i][0] + 86400, vals[i][1])
            tf = _fit(vals)
            if tf[1] > 0:
                t_fit_global = tf
                x_lo = min(v[1] for v in vals) - 15
                x_hi = max(v[1] for v in vals) + 15
                p["x_range"] = (x_lo, x_hi)
        if t_fit_global is None:
            continue

        # legend: black names on/near the title row; colored dash left of each
        legend_row = [s for s in band if abs(s["cy"] - p["title_y"]) < 8
                      and s["cx"] > p["x"] + 40
                      and re.search(r"[A-Za-z]", s["t"])]
        name_color = {}
        for s in legend_row:
            best, bestd = None, 30
            for d in drawings:
                c = d.get("color")
                if c is None or d["type"] not in ("s", "fs"):
                    continue
                r = d["rect"]
                ry = (r.y0 + r.y1) / 2
                if abs(ry - s["cy"]) < 4 and 0 < s["x0"] - r.x1 < bestd:
                    best, bestd = tuple(round(x, 2) for x in c), s["x0"] - r.x1
            if best:
                name_color.setdefault(s["t"], best)

        # curves: strokes within the panel plot box, keyed by legend color
        x_lo, x_hi = p.get("x_range", (0, page.rect.width))
        color_names = defaultdict(list)
        for name, color in name_color.items():
            color_names[color].append(name)
        for color, names in color_names.items():
            pts = []
            for d in drawings:
                c = d.get("color")
                if c is None or d["type"] not in ("s", "fs"):
                    continue
                if tuple(round(x, 2) for x in c) != color:
                    continue
                for item in d["items"]:
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        if color == (0.0, 0.0, 0.0):
                            # black shares ink with axes/grid: drop long
                            # axis-aligned segments
                            if (abs(p1.x - p2.x) < 0.01 or abs(p1.y - p2.y) < 0.01) and \
                               max(abs(p1.x - p2.x), abs(p1.y - p2.y)) > 5:
                                continue
                        pts.append((p1.x, p1.y))
                        pts.append((p2.x, p2.y))
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
            ta, tb = t_fit_global
            t = ta + tb * arr[:, 0]
            v = vfit[0] + vfit[1] * arr[:, 1]
            order = np.argsort(t, kind="stable")
            name = names[0] if len(names) == 1 else " / ".join(sorted(names))
            all_series[name] = (t[order], v[order])
            units[name] = PANEL_UNITS.get(p["name"], "")

    if not all_series or t_fit_global is None:
        raise ValueError("canyon: no calibrated series")
    t_lo = min(t.min() for t, _ in all_series.values())
    t_hi = max(t.max() for t, _ in all_series.values())
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"canyon: implausible duration {n}s")
    meta.duration_min = n / 60.0

    # geometry for the Lab's synced "Compare Original" view. Time runs along
    # x; the three stacked panels share it, so the value extent spans the
    # whole plotted region (top panel's frame down to the bottom panel's) —
    # the horizontal gridlines across all panels give that span.
    hgrid = []
    for d in drawings:
        if d.get("color") is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        if abs(r.y1 - r.y0) < 0.6 and (r.x1 - r.x0) > 100:
            hgrid.append((r.y0 + r.y1) / 2)
    if hgrid:
        ta, tb = t_fit_global
        meta.geom = {"axis": "x", "ta": float(ta - t_lo), "tb": float(tb),
                     "v0": float(min(hgrid)), "v1": float(max(hgrid))}
    if meta.date:
        h = int(t_lo // 3600) % 24
        meta.start_time = f"{h:02d}:{int(t_lo % 3600 // 60):02d}:{int(t_lo % 60):02d}"
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {}
    for name, (t, v) in all_series.items():
        data[name] = _resample(t - t_lo, v, samples)
    return meta, samples, data, units
