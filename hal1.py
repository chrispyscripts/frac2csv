"""Halliburton treatment-plot template (Hal-1 in Carmine's codes).

Each "TREATMENT PLOT : Treatment Interval N" page carries one raster
chart image (matplotlib-style render). Fixed layout: rate ticks left of
the frame (green Slurry Rate), concentration ticks just inside the left
frame (chocolate Slurry Prop Conc + purple Bottom-Hole Prop Conc),
pressure ticks right of the frame (crimson Treating Pressure). Time axis
is "DD HH:MM" labels. Crimson and chocolate share auto_raster's red
family, so they are split on the g-vs-b channel inside hal1.
"""
import re

import fitz
import numpy as np

import auto_raster as ar
from step1 import _frame_bbox


def detect(page):
    t = page.get_text()
    if "TREATMENT PLOT" not in t.upper():
        return False
    return any(im[2] >= 500 and im[3] >= 400
               for im in page.get_images(full=True))


def page_meta(page):
    text = page.get_text()
    meta = {"stage": None, "uwi": ""}
    m = re.search(r"Treatment\s+Interval\s+(\d+)", text, re.I)
    if m:
        meta["stage"] = int(m.group(1))
    m = re.search(r"(\d{3})/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta["uwi"] = "{}{}{}{}{}W{}00".format(*m.groups())
    return meta


def _ocr_column(img, xa, xb, y0, y1):
    """OCR numerals in a vertical strip -> [(value, cy, True)]."""
    from PIL import Image
    xa = max(0, xa)
    strip = img[:, xa:xb]
    if strip.size == 0:
        return []
    pil = Image.fromarray(strip.astype(np.uint8))
    pil = pil.resize((pil.width * 3, pil.height * 3), Image.LANCZOS)
    words = ar.ocr_words(np.array(pil).astype(int), psm=6,
                         whitelist="0123456789.-")
    out = []
    for text, cx, cy in words:
        t = text.replace(",", "").strip("-.")
        if re.fullmatch(r"\d+(\.\d+)?", t):
            py = int(cy / 3)
            if y0 - 25 <= py <= y1 + 25:
                out.append((float(t), py, True))
    return out


SERIES = [  # (label, unit, axis, mask_fn)
    ("Treating Pressure", "MPa", "press",
     lambda m, g, b: m.get("red", None) is not None and (m["red"] & (b >= g))),
    ("Slurry Prop Conc", "kg/m3", "conc",
     lambda m, g, b: m.get("red", None) is not None and (m["red"] & (g > b + 15))),
    ("BH Prop Conc", "kg/m3", "conc",
     lambda m, g, b: m.get("magenta")),
    ("Slurry Rate", "m3/min", "rate",
     lambda m, g, b: m.get("green") if m.get("green") is not None
     else m.get("cyan")),
]


def extract_image(img, sample_sec=1.0):
    """-> (samples, channels, info) from the treatment-plot image."""
    img = np.asarray(img).astype(int)
    box = _frame_bbox(img)
    if box is None:
        raise ValueError("hal1: no frame")
    x0, y0, x1, y1 = box
    tcal = ar.time_calibration(img, x0, x1, y1)
    if tcal is None:
        raise ValueError("hal1: time axis unreadable")
    ta, tb = tcal
    t_start = ta + tb * x0
    n = int((ta + tb * x1) - t_start)
    if not (120 < n < 100000):
        raise ValueError(f"hal1: implausible duration {n}s")

    fits = {
        "rate": ar.fit_ticks(
            [(v, y) for v, y, _ in _ocr_column(img, 0, x0, y0, y1)],
            min_inliers=4),
        "conc": ar.fit_ticks(
            [(v, y) for v, y, _ in _ocr_column(img, x0 + 2, x0 + 120, y0, y1)],
            min_inliers=4),
        "press": ar.fit_ticks(
            [(v, y) for v, y, _ in _ocr_column(img, x1 + 3, img.shape[1],
                                               y0, y1)],
            min_inliers=4),
    }

    masks = ar.hue_masks(img)
    g, b = img[..., 1], img[..., 2]
    samples = np.arange(int(n / sample_sec)) * sample_sec
    channels, notes = [], []
    for label, unit, axis, mask_fn in SERIES:
        cal = fits.get(axis)
        mask = mask_fn(masks, g, b)
        if mask is None or not mask.any():
            continue
        if cal is None:
            notes.append(f"{label}: axis unreadable")
            continue
        a, bb, ntick = cal
        sub = mask[y0:y1, x0:x1]
        cov = float(sub.any(axis=0).mean())
        if cov < 0.05:
            continue
        n_cols = sub.shape[1]
        py = np.full(n_cols, np.nan)
        for cx in range(n_cols):
            ys_ = np.where(sub[:, cx])[0]
            if len(ys_):
                py[cx] = np.median(ys_) + y0
        vals = a + bb * py
        t_cols = (ta + tb * (np.arange(n_cols) + x0)) - t_start
        ok = ~np.isnan(vals)
        if ok.sum() < 50:
            continue
        v = np.interp(samples, t_cols[ok], vals[ok])
        channels.append({"key": label.lower().replace(" ", "-"),
                         "label": label, "unit": unit, "color": "",
                         "values": v, "ticks": ntick, "coverage": cov})
    if not channels:
        raise ValueError("hal1: no channel calibrated; " + "; ".join(notes[:3]))
    info = {"plot": box, "t0_seconds": float(t_start),
            "duration_s": int(n), "notes": notes}
    return samples, channels, info


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, channels, info)"""
    doc = page.parent
    im = max((im for im in page.get_images(full=True)
              if im[2] >= 500 and im[3] >= 400),
             key=lambda im: im[2] * im[3])
    pix = fitz.Pixmap(doc, im[0])
    if pix.colorspace is None:
        raise ValueError("hal1: mask image")
    if pix.alpha or pix.colorspace.n != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3)
    samples, channels, info = extract_image(img, sample_sec)
    return page_meta(page), samples, channels, info
