"""STEP Energy Services template (Step-1 in Carmine's codes).

Pages are born-digital image renders with no text layer: each page is a
vertical stack of full-width image tiles that composite into one 1820px
canvas holding two charts (Treatment Analysis, Chemical Analysis). Chart
frames are solid black bars, so the plot boxes come from strict-dark
column runs and each chart is fed to auto_raster with an explicit plot
box. Time axis is "Time (min)" numerals; series are color-keyed
(red=Surface Pressure, cyan=Slurry Rate, green=Prop Conc, orange=Btm
Prop Conc).
"""
import fitz
import numpy as np

import auto_raster as ar

SERIES_NAMES = {
    # treatment chart
    ("t", "red"): ("Surface Pressure", "MPa"),
    ("t", "cyan"): ("Slurry Rate", "m3/min"),
    ("t", "green"): ("Prop Conc", "kg/m3"),
    ("t", "orange"): ("Btm Prop Conc", "kg/m3"),
    # chemical chart
    ("c", "cyan"): ("Combined Clean Rate", "m3/min"),
    ("c", "magenta"): ("SSI-3 Conc", "L/m3"),
    ("c", "red"): ("Aqucar 742 Conc", "L/m3"),
    ("c", "green"): ("SFR-202 B Conc", "L/m3"),
}


def detect(page):
    """Old format: image-only page tiled by >=3 full-width images.
    New format (2018+): text info table + 1-2 large chart images."""
    return _detect_tiled(page) or _detect_new(page)


def _detect_tiled(page):
    if page.get_text().strip():
        return False
    ims = page.get_images(full=True)
    if len(ims) < 3:
        return False
    widths = set()
    for im in ims:
        rects = page.get_image_rects(im[0])
        if not rects:
            return False
        widths.add(round(rects[0].width))
    return len(widths) == 1 and widths.pop() > page.rect.width * 0.9


def _detect_new(page):
    t = page.get_text()
    if "LSD:" not in t or ("Surface Chart" not in t and "Interval" not in t):
        return False
    big = [im for im in page.get_images(full=True)
           if im[2] >= 500 and im[3] >= 300]
    return len(big) >= 1


def composite(page):
    """Stack the page's image tiles top-to-bottom at native resolution."""
    doc = page.parent
    ims = sorted(page.get_images(full=True),
                 key=lambda im: page.get_image_rects(im[0])[0].y0)
    arrs = []
    for im in ims:
        pix = fitz.Pixmap(doc, im[0])
        if pix.colorspace is None:      # stencil/soft mask, not a tile
            continue
        if pix.alpha or pix.colorspace.n != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        arrs.append(np.frombuffer(pix.samples, dtype=np.uint8)
                    .reshape(pix.height, pix.width, 3))
    if not arrs:
        raise ValueError("step1: no image tiles")
    w = max(a.shape[1] for a in arrs)
    if any(a.shape[1] != w for a in arrs):
        from PIL import Image
        arrs = [a if a.shape[1] == w else
                np.array(Image.fromarray(a).resize(
                    (w, max(1, round(a.shape[0] * w / a.shape[1])))))
                for a in arrs]
    return np.vstack(arrs).astype(int)


def _runs(col, minlen):
    out, start = [], None
    for y, v in enumerate(col):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= minlen:
                out.append((start, y))
            start = None
    if start is not None and len(col) - start >= minlen:
        out.append((start, len(col)))
    return out


def find_charts(img):
    """-> [(x0, y0, x1, y1)] plot boxes, top chart first."""
    H, W = img.shape[:2]
    dark = img.sum(axis=2) < 200
    minlen, maxlen = int(H * 0.1), int(H * 0.7)
    bars = {}
    for x in range(W):
        rr = [r for r in _runs(dark[:, x], minlen) if r[1] - r[0] <= maxlen]
        if rr:
            bars[x] = rr
    if not bars:
        return []
    xs = sorted(bars)
    x_lo, x_hi = xs[0], xs[-1]
    if x_hi - x_lo < W * 0.3:
        return []
    charts = []
    for ya, yb in bars[x_lo]:
        # a chart needs a matching right bar overlapping the same y-range
        for yc, yd in bars[x_hi]:
            if min(yb, yd) - max(ya, yc) > (yb - ya) * 0.5:
                charts.append((x_lo, max(ya, yc), x_hi, min(yb, yd)))
                break
    return charts


def page_meta(img):
    """OCR the header band -> {stage, interval, kind}. kind 'main' is the
    Treatment/Prop-Conc page; 'casing' is the Well Casing Pressure twin."""
    import re
    words = ar.ocr_words(img[:340], psm=6, whitelist="")
    text = " ".join(w[0] for w in words)
    meta = {"stage": None, "interval": "", "kind": "main"}
    m = re.search(r"Treatment\s+(\d+)", text)
    if m:
        meta["stage"] = int(m.group(1))
    m = re.search(r"([\d,]+\.\d+)\s*m\s*-\s*([\d,]+\.\d+)\s*m", text)
    if m:
        meta["interval"] = f"{m.group(1)}-{m.group(2)} m"
    if "Prop Conc" not in text and "Casing" in text.replace("Cacinn", "Casing"):
        meta["kind"] = "casing"
    elif "Prop Conc" not in text:
        # garbled OCR on the casing twin is common; main pages OCR cleanly
        meta["kind"] = "casing" if "Surface Pressure" not in text else "main"
    return meta


def _frame_bbox(img):
    """Plot box = bounding box of long strict-dark line runs (frame and
    gridlines are black in the new format)."""
    H, W = img.shape[:2]
    dark = img.sum(axis=2) < 400
    col_ok = np.where(dark.sum(axis=0) > H * 0.6)[0]
    row_ok = np.where(dark.sum(axis=1) > W * 0.6)[0]
    if not len(col_ok) or not len(row_ok):
        return None
    return int(col_ok[0]), int(row_ok[0]), int(col_ok[-1]), int(row_ok[-1])


NEW_SURFACE = {"red": ("Surface Pressure", "MPa", "left"),
               "blue": ("Slurry Rate", "m3/min", "right1"),
               "cyan": ("Slurry Rate", "m3/min", "right1"),
               "green": ("Prop Conc", "kg/m3", "right2"),
               "orange": ("Btm Prop Conc", "kg/m3", "right2")}


def _extract_new_chart(img, sample_sec=1.0):
    """New-format chart image: black tick labels on fixed axes —
    left=Pressure(red), right1=Rate(blue), right2=Concentration."""
    img = np.asarray(img).astype(int)
    box = _frame_bbox(img)
    if box is None:
        raise ValueError("step1: no frame")
    x0, y0, x1, y1 = box
    tcal = ar.time_calibration(img, x0, x1, y1)
    if tcal is None:
        raise ValueError("step1: time axis unreadable")
    ta, tb = tcal
    t_start = ta + tb * x0
    n = int((ta + tb * x1) - t_start)
    if not (120 < n < 100000):
        raise ValueError(f"step1: implausible duration {n}s")

    def strip_ticks(xa, xb):
        from PIL import Image as _Im
        strip = img[:, max(0, xa):xb]
        if strip.size == 0:
            return []
        pil = _Im.fromarray(strip.astype(np.uint8))
        pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
        words = ar.ocr_words(np.array(pil).astype(int), psm=6,
                             whitelist="0123456789.-")
        out = []
        import re as _re
        for text, cx, cy in words:
            t = text.replace(",", "").strip("-.")
            if _re.fullmatch(r"\d+(\.\d+)?", t):
                out.append((float(t), int(cx / 3) + max(0, xa), int(cy / 3)))
        return [(v, y, True) for v, x, y in
                ((v, x, y) for v, x, y in out) if y0 - 25 <= y <= y1 + 25]

    W = img.shape[1]
    left = strip_ticks(0, x0)
    right = []
    from collections import defaultdict as _dd
    # right side: split labels into columns by x gap
    from PIL import Image as _Im
    strip = img[:, x1 + 3:W]
    cols = _dd(list)
    if strip.size:
        pil = _Im.fromarray(strip.astype(np.uint8))
        pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
        words = ar.ocr_words(np.array(pil).astype(int), psm=6,
                             whitelist="0123456789.-")
        import re as _re
        pts = []
        for text, cx, cy in words:
            t = text.replace(",", "").strip("-.")
            if _re.fullmatch(r"\d+(\.\d+)?", t):
                px, py = int(cx / 3) + x1 + 3, int(cy / 3)
                if y0 - 25 <= py <= y1 + 25:
                    pts.append((float(t), px, py))
        if pts:
            xs = sorted(p[1] for p in pts)
            gaps = [(b - a, a, b) for a, b in zip(xs, xs[1:]) if b - a > 40]
            split = (gaps[0][1] + gaps[0][2]) / 2 if gaps else max(xs) + 1
            for v, px, py in pts:
                cols["right1" if px <= split else "right2"].append(
                    (v, py, True))
    fits = {"left": ar.fit_ticks_guarded(left)}
    for k in ("right1", "right2"):
        fits[k] = ar.fit_ticks_guarded(cols.get(k, []))

    masks = ar.hue_masks(img)
    samples = np.arange(int(n / sample_sec)) * sample_sec
    channels = []
    seen = set()
    for fam, mask in masks.items():
        base = fam.rstrip("2")
        conv = NEW_SURFACE.get(base)
        if conv is None or conv[0] in seen:
            continue
        name, unit, axis = conv
        cal = fits.get(axis)
        if cal is None:
            continue
        a, b, ntick = cal
        sub = mask[y0:y1, x0:x1]
        cov = float(sub.any(axis=0).mean())
        if cov < 0.1:
            continue
        n_cols = sub.shape[1]
        py = np.full(n_cols, np.nan)
        for cx in range(n_cols):
            ys_ = np.where(sub[:, cx])[0]
            if len(ys_):
                py[cx] = np.median(ys_) + y0
        vals = a + b * py
        t_cols = (ta + tb * (np.arange(n_cols) + x0)) - t_start
        ok = ~np.isnan(vals)
        if ok.sum() < 50:
            continue
        v = np.interp(samples, t_cols[ok], vals[ok])
        channels.append({"key": f"series-{fam}", "label": name, "unit": unit,
                         "color": ar.HUE_HEX.get(base, "#555577"),
                         "values": v, "ticks": ntick, "coverage": cov})
        seen.add(name)
    if not channels:
        raise ValueError("step1: no channel calibrated")
    info = {"plot": box, "t0_seconds": float(t_start),
            "duration_s": int(n), "notes": []}
    return samples, channels, info


def _extract_new(page, sample_sec=1.0):
    import re
    doc = page.parent
    text = page.get_text()
    meta = {"stage": None, "interval": "", "kind": "main"}
    m = re.search(r"Interval\s+(\d+)", text)
    if m:
        meta["stage"] = int(m.group(1))
    m = re.search(r"([\d,]+\.\d+)\s*m\s*-\s*([\d,]+\.\d+)\s*m", text)
    if m:
        meta["interval"] = f"{m.group(1)}-{m.group(2)} m"
    ims = [im for im in page.get_images(full=True)
           if im[2] >= 500 and im[3] >= 300]
    ims.sort(key=lambda im: page.get_image_rects(im[0])[0].y0)
    out = []
    done = set()
    for i, im in enumerate(ims):
        if im[0] in done:
            continue
        done.add(im[0])
        pix = fitz.Pixmap(doc, im[0])
        if pix.colorspace is None:
            continue
        if pix.alpha or pix.colorspace.n != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3)
        tag = "t" if not out else "c"
        try:
            samples, chans, info = _extract_new_chart(img, sample_sec)
        except ValueError:
            continue
        out.append((tag, samples, chans, info))
    return meta, out


def extract_page(page, sample_sec=1.0):
    """-> (meta, [(chart_tag, samples, channels, info), ...])."""
    if not _detect_tiled(page) and _detect_new(page):
        return _extract_new(page, sample_sec)
    img = composite(page)
    out = []
    for i, box in enumerate(find_charts(img)):
        tag = "t" if i == 0 else "c"
        try:
            samples, chans, info = ar.extract(img, sample_sec=sample_sec,
                                              plot=box)
        except ValueError:
            continue
        for c in chans:
            fam = c["key"].replace("series-", "").rstrip("2")
            name, unit = SERIES_NAMES.get((tag, fam), (c["label"], c["unit"]))
            c["label"] = name
            c["unit"] = unit
        out.append((tag, samples, chans, info))
    return page_meta(img), out
