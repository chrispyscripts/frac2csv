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
import curve_trace as ct
from step1 import _frame_bbox, _page_geom, impossible_axis


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
        py = ar.curve_positions(sub) + y0
        vals = a + bb * py
        t_cols = (ta + tb * (np.arange(n_cols) + x0)) - t_start
        if np.isfinite(vals).sum() < 50:
            continue
        # No ink means no reading: np.interp with no left/right clamps to the
        # edge value, so every gap and both tails carried a flat invented line.
        # ct.resample blanks them instead (see curve_trace.resample).
        v = ct.resample(samples, t_cols, vals)
        # This channel's axis read AT the plot frame's top and bottom edges —
        # the same two rows geom's v0/v1 quote. Ghost stretches the page
        # between those edges, so a curve drawn against this pair lands on its
        # own ink; drawn against the tick range alone it sits a constant
        # fraction of the plot away, because the outermost tick is not the
        # frame. Both ends must come off the SAME rows as v0/v1.
        ch = {"key": label.lower().replace(" ", "-"),
              "label": label, "unit": unit, "color": "",
              "values": v, "ticks": ntick, "coverage": cov,
              "axis_frame": (float(a + bb * y0), float(a + bb * y1))}
        # An axis that cannot be this channel's own axis is normally a refusal
        # — a dropped channel is visible in the Lab, a wrong one is not — and
        # step1 does refuse. Hal-1 only WARNS, deliberately.
        #
        # Its concentration tick fit is systematically ~110 kg/m3 low on the
        # common render: 885 channels across 30 of 40 documents (12.5%) fail
        # the floor test, 715 of them sharing the identical frame
        # (1381.4, -111.2). On 00382 p113 the OCR reads six good ticks plus
        # two misreads (800 as "0.0", 0 as "120500") and the fit follows them.
        # So these channels are about 7% wrong, not garbage, and refusing them
        # would delete a eighth of Halliburton's concentration record to avoid
        # a modest error. Fix the tick fit and this warning goes quiet on its
        # own; until then the data ships with the axis flagged.
        bad = impossible_axis(ch)
        if bad:
            notes.append(bad)
            ch["axis_suspect"] = True
        channels.append(ch)
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
    # Chart geometry in PAGE units, so the Lab can lay the source page behind
    # the curves. Everything above works in IMAGE pixels; the page embeds that
    # image at a known rect, which makes the conversion a plain scale +
    # offset — exactly step1's raster case, so it uses step1's converter and
    # inherits its convention (ta relative to the STAGE start, v0/v1 the
    # frame's top and bottom in mupdf y-down page units).
    try:
        r = page.get_image_rects(im[0])[0]
        if r.width > 1 and r.height > 1:
            info["geom"] = _page_geom(info, pix.width / r.width,
                                      pix.height / r.height, r.x0, r.y0)
    except Exception:
        pass
    return page_meta(page), samples, channels, info
