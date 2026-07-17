"""BJ / Baker Hughes chart template (BJ-1 in Carmine's codes).

One vector chart page per stage: title "UWI - Well X - Stage NN", time
axis labeled "Mon-DD HH:MM" (slanted black spans), stacked y-axes whose
numeric tick columns sit left/right of the plot with rotated axis-name
spans beside them (a shared axis names two series in one span). Legend
names are black text with a colored dash stroke to the left, so the
color↔series map comes from the dash nearest each name (Canyon-style).
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta, _resample

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
TIME_RE = re.compile(r"([A-Z][a-z]{2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")


def detect(page):
    t = page.get_text()
    return ("Stage" in t and TIME_RE.search(t) is not None
            and re.search(r"\d{3}/\d{2}-\d{2}-\d{3}-\d{2}W\d", t) is not None)


def _spans(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    x0, y0, x1, y1 = span["bbox"]
                    out.append({"t": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
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
    m = re.search(r"(\d{3})/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)"
                  r".*?Stage\s*(\d+)", text, re.S)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups()[:6])
        meta.stage = str(int(m.group(7)))
    tm = re.search(r"([A-Z][a-z]{2})-(\d{1,2})", text)
    if tm:
        meta.date = f"{tm.group(1)}-{int(tm.group(2)):02d}"
    meta.title = next((s["t"] for s in spans if " - Stage" in s["t"]), "")[:60]

    # time axis: slanted "Mon-DD HH:MM" labels; right bbox edge sits on
    # the gridline they annotate
    tpts = []
    for s in spans:
        m = TIME_RE.fullmatch(s["t"])
        if m:
            mon, day, hh, mm = m.groups()
            if mon not in MONTHS:
                continue
            secs = ((MONTHS[mon] * 31 + int(day)) * 86400
                    + int(hh) * 3600 + int(mm) * 60)
            tpts.append((secs, s["x1"], s["cy"]))
    if len(tpts) < 3:
        raise ValueError("bj1: time labels not found")
    tfit = _fit([(v, x) for v, x, _ in tpts])
    if tfit[1] <= 0:
        raise ValueError("bj1: bad time fit")
    time_y = min(cy for _, _, cy in tpts)

    # y-axis tick columns: numeric spans above the time labels, clustered
    # by right-edge x
    nums = [s for s in spans if re.fullmatch(r"-?[\d,]+(\.\d+)?", s["t"])
            and s["cy"] < time_y - 5]
    cols = defaultdict(list)
    for s in nums:
        placed = False
        for key in list(cols):
            if abs(key - s["x1"]) < 8:
                cols[key].append(s)
                placed = True
                break
        if not placed:
            cols[round(s["x1"])].append(s)
    fits = {}          # col_x -> (a, b, y_lo, y_hi)
    for key, ss in cols.items():
        if len(ss) < 3:
            continue
        a, b = _fit([(float(s["t"].replace(",", "")), s["cy"]) for s in ss])
        if abs(b) > 1e-9:
            ys = [s["cy"] for s in ss]
            fits[key] = (a, b, min(ys) - 10, max(ys) + 10)
    if not fits:
        raise ValueError("bj1: no axis tick columns")

    # rotated axis-name spans (taller than wide) -> nearest tick column
    axis_names = {}
    for s in spans:
        if (s["y1"] - s["y0"]) > (s["x1"] - s["x0"]) * 1.5 and \
                re.search(r"[A-Za-z]{3}", s["t"]):
            key = min(fits, key=lambda k: abs(k - s["cx"]))
            axis_names[s["t"]] = key

    # legend: black names with a short colored dash stroke to the left
    drawings = page.get_drawings()
    dashes = []
    for d in drawings:
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        c = tuple(round(x, 2) for x in c)
        if c == (0.0, 0.0, 0.0) or len(d["items"]) > 4:
            continue
        r = d["rect"]
        if r.width < 40 and r.height < 4:
            dashes.append((c, r))
    name_color = {}
    for s in spans:
        if not re.search(r"\([^)]+\)", s["t"]) or (s["y1"] - s["y0"]) > 20:
            continue
        best, bestd = None, 25
        for c, r in dashes:
            dy = abs((r.y0 + r.y1) / 2 - s["cy"])
            dx = s["x0"] - r.x1
            if dy < 6 and 0 < dx < bestd:
                best, bestd = c, dx
        if best:
            name_color.setdefault(s["t"], best)
    if not name_color:
        raise ValueError("bj1: no legend colors")

    # match each legend name to the axis whose name span mentions it
    def name_axis(name):
        base = re.sub(r"\s+", " ", name)
        for ax_text, key in axis_names.items():
            if base in re.sub(r"\s+", " ", ax_text):
                return key
        return None

    x_lo = min(x for _, x, _ in tpts) - 15
    x_hi = max(x for _, x, _ in tpts) + 15
    series, units = {}, {}
    for name, color in name_color.items():
        key = name_axis(name)
        if key is None:
            continue
        a, b, y_lo, y_hi = fits[key]
        pts = []
        for d in drawings:
            c = d.get("color")
            if c is None or d["type"] not in ("s", "fs"):
                continue
            if tuple(round(x, 2) for x in c) != color or len(d["items"]) < 5:
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
        t = tfit[0] + tfit[1] * arr[:, 0]
        v = a + b * arr[:, 1]
        order = np.argsort(t, kind="stable")
        mn = re.match(r"(.+?)\s*\(([^)]+)\)", name)
        label = mn.group(1).strip() if mn else name
        series[label] = (t[order], v[order])
        units[label] = mn.group(2).strip() if mn else ""
    if not series:
        raise ValueError("bj1: no curves matched")

    t_lo = min(t.min() for t, _ in series.values())
    t_hi = max(t.max() for t, _ in series.values())
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"bj1: implausible duration {n}s")
    meta.duration_min = n / 60.0
    day_sec = t_lo % 86400
    meta.start_time = (f"{int(day_sec // 3600):02d}:"
                       f"{int(day_sec % 3600 // 60):02d}:"
                       f"{int(day_sec % 60):02d}")
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {name: _resample(t - t_lo, v, samples)
            for name, (t, v) in series.items()}
    return meta, samples, data, units
