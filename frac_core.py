"""Frac2CSV core: extract frac-stage time-series curves from vector chart PDFs.

Works on MView-style frac charts where each data series is stroked vector
geometry in a distinct RGB color. Page metadata (UWI, stage/zone, date, axis
ranges) is auto-detected from the page text; every value can be overridden.

Layout assumptions (MView "Casing Ign Template" and similar):
  - page content rotated 90 deg: time runs along the PDF y axis
  - all value axes are zero-based and span the full plot frame
  - series colors: blue = treating pressure, red = slurry rate,
    green = prop conc @ blender (WH), purple = prop conc @ formation (BH)
"""
import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import fitz  # PyMuPDF
import numpy as np

# stroke color -> (csv column, axis kind)
SERIES = {
    (0.0, 0.0, 1.0): ("Tr Press", "pressure"),
    (1.0, 0.0, 0.0): ("Slurry Rate", "rate"),
    (0.0, 0.5, 0.0): ("WH Prop Conc", "conc"),
    (0.5, 0.0, 0.5): ("BH Prop Conc", "conc"),
}
COLUMNS = ["Tr Press", "Slurry Rate", "WH Prop Conc", "BH Prop Conc"]
UNITS = {"Tr Press": "MPa", "Slurry Rate": "m3/Min",
         "WH Prop Conc": "Kg/m3", "BH Prop Conc": "Kg/m3"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


@dataclass
class PageMeta:
    uwi: str = ""
    stage: str = ""
    date: str = ""            # YYYY-mm-dd
    start_time: str = "00:00:00"
    duration_min: float = 0.0
    pressure_max: float = 0.0
    rate_max: float = 0.0
    conc_max: float = 0.0
    title: str = ""
    warnings: list = field(default_factory=list)


def _detect_frame(page):
    """Plot frame = largest black stroked path with >= 4 segments."""
    best = None
    for d in page.get_drawings():
        if d.get("color") == (0.0, 0.0, 0.0) and d["type"] == "s" and len(d["items"]) >= 4:
            r = d["rect"]
            if best is None or r.width * r.height > best.width * best.height:
                best = r
    return best


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


def detect_meta(page, frame):
    """Read UWI/stage/date and axis ranges from the page text."""
    meta = PageMeta()
    text = page.get_text()

    m = re.search(r"(1[0-9A-F]\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups())
    else:
        meta.warnings.append("UWI not found in page text")

    m = re.search(r"(?:Zone|Stage)\s+(\d+)", text)
    if m:
        meta.stage = m.group(1)
    else:
        meta.warnings.append("stage/zone not found")

    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if m and m.group(1)[:3].lower() in MONTHS:
        meta.date = f"{int(m.group(3)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    else:
        meta.warnings.append("date not found")

    first_line = text.strip().splitlines()[0] if text.strip() else ""
    meta.title = first_line.strip()

    # axis labels: numeric spans grouped by position relative to the frame
    time_vals, pressure_vals, top_vals = [], [], []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                v = _num(span["text"].strip())
                if v is None:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if cx > frame.x1 and frame.y0 - 10 < cy < frame.y1 + 10:
                    time_vals.append(v)          # right of frame: time axis
                elif cy > frame.y1 and frame.x0 - 10 < cx < frame.x1 + 10:
                    pressure_vals.append(v)      # below frame: pressure axis
                elif cy < frame.y0 and frame.x0 - 10 < cx < frame.x1 + 10:
                    top_vals.append(v)           # above frame: rate + conc axes

    if time_vals:
        meta.duration_min = max(time_vals)
    else:
        meta.warnings.append("time axis labels not found")
    if pressure_vals:
        meta.pressure_max = max(pressure_vals)
    else:
        meta.warnings.append("pressure axis labels not found")
    if top_vals:
        meta.conc_max = max(top_vals)
        small = [v for v in top_vals if v < max(100.0, meta.conc_max / 10)]
        meta.rate_max = max(small) if small else 0.0
    if meta.rate_max <= 0 or meta.conc_max <= 0:
        meta.warnings.append("rate/conc axis labels not fully detected")
    return meta


def _collect_points(page, frame):
    """Per-series (y, x) point arrays, clipped to the plot frame."""
    raw = {}
    for d in page.get_drawings():
        color = d.get("color")
        if color is None:
            continue
        key = min(SERIES, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, color)))
        if sum((a - b) ** 2 for a, b in zip(key, color)) > 1e-4:
            continue
        pts = raw.setdefault(key, [])
        for item in d["items"]:
            if item[0] == "l":
                pts.append((item[1].x, item[1].y))
                pts.append((item[2].x, item[2].y))
            elif item[0] == "c":
                pts.append((item[1].x, item[1].y))
                pts.append((item[4].x, item[4].y))
    out = {}
    pad = 1.0
    for color, pts in raw.items():
        arr = np.array(pts)
        keep = ((arr[:, 0] >= frame.x0 - pad) & (arr[:, 0] <= frame.x1 + pad) &
                (arr[:, 1] >= frame.y0 - pad) & (arr[:, 1] <= frame.y1 + pad))
        arr = arr[keep]
        if len(arr):
            out[color] = arr
    return out


def _resample(t_min, values, sample_min):
    t_round = np.round(t_min, 6)
    uniq, inv = np.unique(t_round, return_inverse=True)
    v_uniq = np.bincount(inv, weights=values) / np.bincount(inv)
    v = np.interp(sample_min, uniq, v_uniq)
    v[(sample_min < uniq[0]) | (sample_min > uniq[-1])] = np.nan
    return v


def extract_page(page, meta=None, sample_sec=1.0):
    """Extract all series from one page. Returns (meta, sample_sec_array, {col: values})."""
    frame = _detect_frame(page)
    if frame is None:
        raise ValueError("no plot frame found on page")
    if meta is None:
        meta = detect_meta(page, frame)
    if meta.duration_min <= 0:
        raise ValueError("stage duration unknown (no time axis labels); set it manually")

    fullscale = {"pressure": meta.pressure_max, "rate": meta.rate_max, "conc": meta.conc_max}
    points = _collect_points(page, frame)
    if not points:
        raise ValueError("no series curves found on page")

    n = int(round(meta.duration_min * 60 / sample_sec))
    samples = np.arange(n) * sample_sec
    sample_min = samples / 60.0

    data = {}
    for color, arr in points.items():
        name, kind = SERIES[color]
        fs = fullscale[kind]
        if fs <= 0:
            meta.warnings.append(f"{name}: axis scale unknown, channel skipped")
            continue
        t = (frame.y1 - arr[:, 1]) / (frame.y1 - frame.y0) * meta.duration_min
        v = (frame.x1 - arr[:, 0]) / (frame.x1 - frame.x0) * fs
        order = np.argsort(t, kind="stable")
        data[name] = _resample(t[order], v[order], sample_min)
    return meta, samples, data


def write_csv(path, meta, samples, data, sample_sec=1.0):
    start = datetime.strptime(f"{meta.date or '1970-01-01'} {meta.start_time}",
                              "%Y-%m-%d %H:%M:%S")
    epoch0 = start.timestamp()  # local-time epoch, matches MView exports
    cols = [c for c in COLUMNS if c in data]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["UWI", "STAGE", "DATETIME", "ELAPSED", "TIMESTAMP", "LABEL"] + cols)
        w.writerow(["Units", "", "YYYY-mm-dd HH:MM:SS", "secs", "secs", ""] +
                   [UNITS[c] for c in cols])
        for i, s in enumerate(samples):
            dt = start + timedelta(seconds=float(s))
            row = [meta.uwi, meta.stage, dt.strftime("%Y-%m-%d %H:%M:%S"),
                   f"{s:.5f}", f"{epoch0 + s:.5f}", meta.stage]
            row += ["" if np.isnan(data[c][i]) else f"{data[c][i]:.5f}" for c in cols]
            w.writerow(row)
    return len(samples), cols
