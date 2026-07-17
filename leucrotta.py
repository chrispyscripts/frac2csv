"""Leucrotta-style acquisition chart template (BC COMP filings, 7th template).

Rotated pages (time along PDF y), one 2-hour window per page. Each series
is a stroke color with its own colored tick row (value along x, both page
edges); series lacking ticks share the axis of another series with the
same unit. A colored legend gives each series' name and unit. Stages can
span several consecutive pages — extract per page, then stitch on absolute
time (Job Date + HH:MM labels).
"""
import re
from collections import defaultdict

import fitz
import numpy as np

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def detect(page):
    t = page.get_text()
    return "Job Date:" in t and "Top Perf:" in t


def _spans(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    x0, y0, x1, y1 = span["bbox"]
                    out.append({"t": t, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                                "color": span.get("color", 0)})
    return out


def _fit(pairs):
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    A = np.vstack([np.ones_like(c), c]).T
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(a), float(b)


def _legend(spans):
    """color -> {name, unit} from 'Series Name' + 'value unit' span pairs."""
    out = {}
    for s in spans:
        if s["color"] == 0 or re.fullmatch(r"[\d,.:]+", s["t"]):
            continue
        m = re.fullmatch(r"[\d.,-]+\s*([A-Za-z³/%°]+[A-Za-z³/]*)", s["t"])
        if m:
            continue  # value+unit span; handled via partner lookup
        name = s["t"]
        # partner value-unit span: same color, nearby line
        unit = ""
        for c in spans:
            if c["color"] == s["color"] and c is not s and \
               abs(c["cy"] - s["cy"]) < 3 and \
               re.fullmatch(r"[\d.,-]+\s*(.+)", c["t"]):
                unit = re.fullmatch(r"[\d.,-]+\s*(.+)", c["t"]).group(1).strip()
                break
        if name and s["color"] not in out:
            out[s["color"]] = {"name": name, "unit": unit}
    return out


def _axis_fits(spans):
    """color -> (a, b): value = a + b * x, from that color's tick numerals."""
    ticks = defaultdict(list)
    for s in spans:
        if s["color"] != 0 and re.fullmatch(r"[\d,]+(\.\d+)?", s["t"]):
            ticks[s["color"]].append((float(s["t"].replace(",", "")), s["cx"], s["cy"]))
    fits = {}
    for color, pts in ticks.items():
        if len(pts) < 4:
            continue
        # ticks are duplicated on both page edges: keep one cy cluster
        cys = sorted(p[2] for p in pts)
        split = (cys[0] + cys[-1]) / 2
        side = [p for p in pts if p[2] < split] or pts
        if len(side) < 3:
            side = pts
        a, b = _fit([(v, x) for v, x, _ in side])
        if abs(b) > 1e-9:
            fits[color] = (a, b)
    return fits


def _time_axis(spans, text):
    """HH:MM labels along y -> absolute seconds = a + b * cy (+ date)."""
    m = re.search(r"Job Date:\s*([A-Za-z]{3})\w*\s+(\d{1,2})-(\d{4})", text)
    date = ""
    if m and m.group(1).lower() in MONTHS:
        date = f"{int(m.group(3)):04d}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    tl = [s for s in spans if s["color"] == 0 and
          re.fullmatch(r"\d{1,2}:\d{2}", s["t"])]
    if len(tl) < 3:
        return None, date
    # the axis labels form one x-column; keep the densest column
    cols = defaultdict(list)
    for s in tl:
        cols[round(s["cx"] / 8)].append(s)
    col = max(cols.values(), key=len)
    if len(col) < 3:
        return None, date
    col.sort(key=lambda s: s["cy"])
    vals = []
    for s in col:
        h, mnt = s["t"].split(":")
        vals.append((int(h) * 3600 + int(mnt) * 60, s["cy"]))
    for i in range(1, len(vals)):        # unwrap midnight
        if vals[i][0] < vals[i - 1][0] - 20000:
            vals[i] = (vals[i][0] + 86400, vals[i][1])
    a, b = _fit(vals)
    if abs(b) < 1e-12:
        return None, date
    return (a, b), date


def _close(stroke, color_int):
    r = ((color_int >> 16) & 255) / 255
    g = ((color_int >> 8) & 255) / 255
    b = (color_int & 255) / 255
    return sum((x - y) ** 2 for x, y in zip(stroke, (r, g, b))) < 0.02


def extract_window(page):
    """One chart page -> {'meta':…, 'series': {name: (abs_t, values, unit)}}"""
    spans = _spans(page)
    text = page.get_text()
    tfit, date = _time_axis(spans, text)
    if tfit is None:
        raise ValueError("leucrotta: time labels not found")
    ta, tb = tfit
    legend = _legend(spans)
    fits = _axis_fits(spans)
    if not fits:
        raise ValueError("leucrotta: no axis ticks")
    # share axes by unit for series without their own ticks
    unit_fit = {}
    for color, f in fits.items():
        u = legend.get(color, {}).get("unit", "")
        if u and u not in unit_fit:
            unit_fit[u] = f
    m = re.search(r"Stage#:\s*(\S+)", text)
    stage = m.group(1) if m else ""
    m = re.search(r"Well:\s*(\S+)", text)
    well = m.group(1) if m else ""
    m = re.search(r"Page:\s*(\d+)", text)
    pageno = int(m.group(1)) if m else 0

    # tick x-range for clipping (value axis span)
    all_tick_x = [s["cx"] for s in spans
                  if s["color"] != 0 and re.fullmatch(r"[\d,]+(\.\d+)?", s["t"])]
    x_lo, x_hi = min(all_tick_x) - 8, max(all_tick_x) + 8
    tl_cy = [s["cy"] for s in spans if s["color"] == 0 and re.fullmatch(r"\d{1,2}:\d{2}", s["t"])]
    y_lo, y_hi = min(tl_cy) - 10, max(tl_cy) + 10

    series = {}
    for color_int, info in legend.items():
        fit = fits.get(color_int) or unit_fit.get(info["unit"])
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
                    p1, p2 = item[1], item[2]
                    if color_int == 0 or (c == (0.0, 0.0, 0.0)):
                        # black series shares ink with the grid: drop
                        # perfectly axis-aligned segments (gridlines)
                        if abs(p1.x - p2.x) < 0.01 or abs(p1.y - p2.y) < 0.01:
                            if max(abs(p1.x - p2.x), abs(p1.y - p2.y)) > 5:
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
        t = ta + tb * arr[:, 1]
        v = a + b * arr[:, 0]
        order = np.argsort(t, kind="stable")
        series[info["name"]] = (t[order], v[order], info["unit"])
    if not series:
        raise ValueError("leucrotta: no curves matched")
    return {"stage": stage, "well": well, "page_in_stage": pageno,
            "date": date, "series": series}


def extract_document(path, sample_sec=1.0):
    """All chart pages, stitched by stage. -> [{stage, well, date, t0, samples, data, units}]"""
    doc = fitz.open(path)
    windows = []
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect(page):
            continue
        try:
            w = extract_window(page)
            w["pdf_page"] = pno + 1
            windows.append(w)
        except ValueError:
            continue
    doc.close()
    # group by stage id
    groups = defaultdict(list)
    for w in windows:
        groups[(w["well"], w["stage"])].append(w)
    out = []
    for (well, stage), ws in groups.items():
        merged = defaultdict(lambda: ([], [], ""))
        for w in ws:
            for name, (t, v, unit) in w["series"].items():
                ts, vs, _ = merged[name]
                ts.append(t)
                vs.append(v)
                merged[name] = (ts, vs, unit)
        t_lo = min(np.concatenate(ts).min() for ts, _, _ in merged.values())
        t_hi = max(np.concatenate(ts).max() for ts, _, _ in merged.values())
        n = int(t_hi - t_lo)
        if not (60 < n < 200000):
            continue
        samples = np.arange(int(n / sample_sec)) * sample_sec
        data, units = {}, {}
        for name, (ts, vs, unit) in merged.items():
            t = np.concatenate(ts) - t_lo
            v = np.concatenate(vs)
            order = np.argsort(t, kind="stable")
            t, v = t[order], v[order]
            uniq, inv = np.unique(np.round(t, 3), return_inverse=True)
            vu = np.bincount(inv, weights=v) / np.bincount(inv)
            out_v = np.interp(samples, uniq, vu)
            out_v[(samples < uniq[0]) | (samples > uniq[-1])] = np.nan
            data[name] = out_v
            units[name] = unit
        out.append({"well": well, "stage": stage, "date": ws[0]["date"],
                    "t0_seconds": float(t_lo), "pages": [w["pdf_page"] for w in ws],
                    "samples": samples, "data": data, "units": units})
    out.sort(key=lambda g: g["t0_seconds"])
    return out
