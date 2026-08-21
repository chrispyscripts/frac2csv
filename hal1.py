"""Halliburton treatment-plot template (Hal-1 in Carmine's codes).

Each "TREATMENT PLOT : Treatment Interval N" page carries one raster
chart image (matplotlib-style render). Fixed layout: rate ticks left of
the frame (green Slurry Rate), concentration ticks just inside the left
frame (chocolate Slurry Prop Conc + purple Bottom-Hole Prop Conc),
pressure ticks right of the frame (crimson Treating Pressure). Time axis
is "DD HH:MM" labels. Crimson and chocolate share auto_raster's red
family, so they are split on the g-vs-b channel inside hal1.

Because the concentration axis lives INSIDE the plot, its decoration — tick
stubs and the rotated "Conc. [kg/m3]" title, both drawn in the series' own
chocolate — is ink inside the plot rect, and reading it as a curve is the
one mistake this template invites. See _furniture_cols.
"""
import re

import fitz
import numpy as np

import auto_raster as ar
import curve_trace as ct
import ocr_labels
from step1 import _frame_bbox, _page_geom, impossible_axis

# Below this many characters a page is treated as having no text of its own.
_OCR_TEXT_MIN = 40


def _page_text(page):
    """The page's text, OCR'd when it has none of its own.

    A whole class of Halliburton filings prints every character as vector
    outlines — 126 of them on the two drives, 37,000 pages — so get_text()
    returns nothing and this template could not find a single chart on any of
    them. The chart itself was never the problem: the curve is a raster image
    and extract_image already OCRs its own axes. Only the two text lookups
    here stood in the way, and both strings are printed ON the image anyway
    ("TREATMENT PLOT : Treatment Interval 3", and the UWI above it).

    ocr_labels caches per document, so the second read of a page is free.
    """
    t = page.get_text()
    if len(t.strip()) > _OCR_TEXT_MIN or not ocr_labels.available():
        return t
    try:
        return ocr_labels.page_text(page) or t
    except Exception:
        return t


def detect(page):
    # The image test FIRST, because it is nearly free and OCR is not: this is
    # called on every page of every document, and a page with no big raster on
    # it cannot be a treatment plot whatever its text says.
    if not any(im[2] >= 500 and im[3] >= 400
               for im in page.get_images(full=True)):
        return False
    return "TREATMENT PLOT" in _page_text(page).upper()


def page_meta(page):
    text = _page_text(page)
    meta = {"stage": None, "uwi": ""}
    m = re.search(r"Treatment\s+Interval\s+(\d+)", text, re.I)
    if m:
        meta["stage"] = int(m.group(1))
    m = re.search(r"(\d{3})/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta["uwi"] = "{}{}{}{}{}W{}00".format(*m.groups())
    return meta


# How far outside the frame a y-axis tick label's OCR centre may still land.
# Matplotlib draws no tick beyond the axes limits, so the only slack a real
# label needs is the OCR's own centroid error, which on this 3x strip measures
# under 1.5 px against ticks whose true rows are known (25/20/15/10/5/0 come
# back at 74/213/351/490/629/767 against 74.0/213.1/352.1/491.2/630.3/767.0).
TICK_PAD_FRAC = 0.012


def _ocr_column(img, xa, xb, y0, y1):
    """OCR numerals in a vertical strip -> [(value, cy, True)].

    The strip is CUT to the plot's own rows before OCR. Read over the full page
    height instead — as this did — and the row of time labels under the chart
    arrives as extra ticks: they sit only 15 px below the bottom rule, inside
    the +-25 px window this used to allow, and "17:30" comes back through the
    digits-only whitelist as 1730, or 17, or 7230. On 01242 p267 that put
    (17.0, 782) in the concentration column, and RANSAC preferred the line
    through it — 7 inliers against the 6 real ticks give — so the axis fitted
    21.34 at the frame's bottom instead of 0 and every concentration in the
    export came out up to 21 kg/m3 high (Carmine, #73/#74: "conc seems
    elevated", "biasing the output ... shifting up a bit"). The junk also
    widens fit_ticks' tolerance, which is scaled to the value range it is
    handed, so one wild read makes the gate loose enough for the next one.
    """
    from PIL import Image
    xa = max(0, xa)
    pad = max(4, int(round(TICK_PAD_FRAC * (y1 - y0))))
    ya, yb = max(0, y0 - pad), min(img.shape[0], y1 + pad + 1)
    strip = img[ya:yb, xa:xb]
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
            py = int(cy / 3) + ya
            if y0 - pad <= py <= y1 + pad:
                out.append((float(t), py, True))
    return out


# Under the time axis the plot prints its own caption, and on every one of the
# 187 treatment plots sampled across 134 filings it reads
#   "Pump Time (Start Date: YYYY-MM-DD)"
# That string is the only place the DATE of a raster treatment plot appears:
# the page's text layer carries the well name, the UWI and the interval
# number and nothing else, which is why every one of these charts has been
# exported dated 2000-01-01 (Carmine, #368: "can we now add in smarts to get
# the times and dates at least on ones like this that have it on the image").
#
# It is read as a whole phrase, not as a loose date: "Start Date:" followed by
# an ISO date and a closing bracket is long enough that OCR noise cannot
# counterfeit it, and a bare date floating anywhere under the axis could just
# as easily be a tick label.
_START_DATE = re.compile(r"Start\s*Date\s*[:.]?\s*"
                         r"(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*\)")
_CAPTION_WL = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
               "0123456789:()-. ")


def axis_caption_date(img, x0, x1, y1):
    """The plot's printed "Start Date" as (y, m, d), or None.

    Read from the band under the time axis, which holds the tick labels and
    the caption and nothing else. Nothing here is inferred: a date that does
    not parse as a real calendar date is thrown away rather than repaired.
    """
    from PIL import Image
    H, W = img.shape[0], img.shape[1]
    strip = img[min(y1 + 1, H - 1):min(y1 + 140, H),
                max(0, x0 - 80):min(W, x1 + 80)]
    if strip.size == 0:
        return None
    pil = Image.fromarray(strip.astype(np.uint8))
    pil = pil.resize((pil.width * 3, pil.height * 3), Image.LANCZOS)
    words = ar.ocr_words(np.array(pil).astype(int), psm=6,
                         whitelist=_CAPTION_WL)
    m = _START_DATE.search(" ".join(w[0] for w in words))
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    try:
        import datetime
        return datetime.date(y, mo, d)
    except ValueError:
        return None


# The concentration axis is drawn INSIDE the frame (see the module docstring),
# and matplotlib colours an axis's furniture to match its series — so the tick
# stubs hard against the left rule and the rotated "Conc. [kg/m3]" title a
# little further in are BOTH chocolate, the same ink as Slurry Prop Conc, and
# both land in that channel's mask. Measured over 140 treatment plots on three
# wells (00784, 01242, 00382) the stubs sit at x0+3..x0+7 on 92 of them and
# the title at x0+51..x0+64 on 94; the earliest column any real concentration
# ink ever reaches is x0+68. They are what Carmine reported as
#   #70 "units for conc inside graph are getting extracted as data"
#   #71 "picking up data on data on the far left for wh conc"
# and they are why the peak on those pages reads ~800 kg/m3 when the trace
# itself never passes 460: the phantom, not the job, sets the maximum.
#
# Only the LEFTMOST few percent of the plot can hold this, and decoration is
# ink that is not a stroke: a curve column is a solid run three or four pixels
# tall, while a column through the stubs spans 555 rows of 693 holding ~16 lit
# pixels, and one through the rotated title spans 92 holding a third of them.
# Both fail "solid", every real column passes it (99th percentile span 17 px),
# and requiring the whole island to sit inside the band keeps a curve that
# merely starts early — it runs on past the band and is never a candidate.
FURNITURE_BAND = 0.08          # of the plot width, from the left frame edge
FURNITURE_SPAN = 0.05          # of the plot height: taller than any stroke
FURNITURE_FILL = 0.5           # lit pixels / span: below this it is not a run


def _furniture_cols(sub):
    """Columns of a plot-cropped mask that hold axis decoration, not a curve.

    Returns a boolean array over the mask's columns. Empty (all False) is the
    normal answer for every channel whose axis is drawn in the gutters.
    """
    H, W = sub.shape
    if H < 20 or W < 20:
        return np.zeros(W, bool)
    band = max(4, int(FURNITURE_BAND * W))
    tall = max(8.0, FURNITURE_SPAN * H)
    sparse = np.zeros(W, bool)
    for cx in range(band):
        ys = np.flatnonzero(sub[:, cx])
        if len(ys) < 2:
            continue
        span = float(ys[-1] - ys[0] + 1)
        if span > tall and len(ys) < FURNITURE_FILL * span:
            sparse[cx] = True
    if not sparse.any():
        return np.zeros(W, bool)
    out = np.zeros(W, bool)
    occ = sub.any(axis=0)
    idx = np.flatnonzero(occ)
    for run in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
        # an island that reaches past the band is a curve that started early
        if run[-1] >= band:
            continue
        if sparse[run].sum() * 2 > len(run):
            out[run] = True
    return out


# A stray no wider than this, with no ink of its own colour for this many
# columns either side, is not a reading. Crimson is anti-aliased into tan
# where the pressure trace plunges at the end of a job, and a few of those
# pixels clear hal1's chocolate cut — 01242 p267 x1017 and x1019, 00784 p282
# x1049..1051, p294 x1051..1052, each landing 300-700 kg/m3 above a
# concentration trace that has already gone to zero (#72 "a random set of data
# points or leaking from slurry", #74 "the leakage of values"). The export
# already shows them detached: curve_trace.resample blanks any hole wider than
# six columns, so nothing here was bridging to real data — the island simply
# stood on its own, and being the highest thing on the page it also set the
# channel's reported peak.
ORPHAN_COLS = 4
ORPHAN_GAP = 8


def _drop_orphans(py):
    """Blank isolated slivers in a per-column curve track (in place).

    Columns closer together than ORPHAN_GAP are one cluster — 01242 p267 leaks
    two single columns two apart, and judged one at a time each is "next to"
    the other and neither looks isolated.
    """
    idx = np.flatnonzero(np.isfinite(py))
    if not len(idx):
        return py
    for run in np.split(idx, np.flatnonzero(np.diff(idx) > ORPHAN_GAP) + 1):
        if len(run) <= ORPHAN_COLS:
            py[run] = np.nan
    return py


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
    tcal = ar.time_calibration_ex(img, x0, x1, y1)
    if tcal is None:
        raise ValueError("hal1: time axis unreadable")
    ta, tb, axis_kind = tcal
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
        sub = mask[y0:y1, x0:x1].copy()
        junk = _furniture_cols(sub)
        if junk.any():
            sub[:, junk] = False
        cov = float(sub.any(axis=0).mean())
        if cov < 0.05:
            continue
        n_cols = sub.shape[1]
        py = _drop_orphans(ar.curve_positions(sub)) + y0
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
        # It warned constantly, because the concentration tick fit was
        # systematically ~110 kg/m3 low on the common render: 885 channels
        # across 30 of 40 documents (12.5%) failed the floor test, 715 of them
        # sharing the identical frame (1381.4, -111.2). That was never the
        # OCR's fault. _ocr_column was reading the whole page height and taking
        # the time labels under the chart for ticks; cut the strip to the plot
        # and the fits land on the printed axis. Over 140 treatment plots on
        # three wells the concentration frame now reads 0.46..0.62 at the
        # bottom rule and 1500.0..1500.2 at the top, against a printed 0..1500,
        # where before it was out by up to 151; pressure and rate agree to
        # 0.05 MPa and 0.012 m3/min on every page. Every one of the 50 axis
        # warnings those files used to raise is gone, so a warning here now
        # means something and is worth reading.
        bad = impossible_axis(ch)
        if bad:
            notes.append(bad)
            ch["axis_suspect"] = True
        channels.append(ch)
    if not channels:
        raise ValueError("hal1: no channel calibrated; " + "; ".join(notes[:3]))
    info = {"plot": box, "t0_seconds": float(t_start),
            "duration_s": int(n), "notes": notes,
            # what the time axis was printed in, and the date printed beside
            # it — everything hal1_tables.chart_datetime needs to turn this
            # chart's own origin into a wall clock.
            "axis_kind": axis_kind,
            "start_date": axis_caption_date(img, x0, x1, y1)}
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
    # A whole class of these filings renders the plot SIDEWAYS: the same
    # matplotlib chart turned 90 degrees, so "Pump Time" runs down the page
    # and the value axes run across it. Everything below the frame — the tick
    # ladders, the time calibration, the series masks — is written for time
    # along x, and on a turned page the time axis simply is not where it
    # looks.
    #
    # The orientation is not guessed at. A page that is the right way up
    # reads on the first try and never reaches the rotation, so nothing that
    # works today can change; a turned one fails to find a time axis, which
    # is the evidence, and is then turned clockwise and read again.
    rotated = False
    try:
        samples, channels, info = extract_image(img, sample_sec)
    except ValueError as e:
        if "time axis" not in str(e):
            raise
        samples, channels, info = extract_image(np.rot90(img, -1), sample_sec)
        rotated = True
    # Chart geometry in PAGE units, so the Lab can lay the source page behind
    # the curves. Everything above works in IMAGE pixels; the page embeds that
    # image at a known rect, which makes the conversion a plain scale +
    # offset — exactly step1's raster case, so it uses step1's converter and
    # inherits its convention (ta relative to the STAGE start, v0/v1 the
    # frame's top and bottom in mupdf y-down page units).
    # Only for a page read the way it was drawn. geom is a plain scale and
    # offset from image pixels to page units, and that is not what it is any
    # more once the image has been turned — the Lab would lay the source page
    # behind the curves at ninety degrees to them. No geom means no underlay,
    # which is a feature missing rather than a feature lying.
    if not rotated:
        try:
            r = page.get_image_rects(im[0])[0]
            if r.width > 1 and r.height > 1:
                info["geom"] = _page_geom(info, pix.width / r.width,
                                          pix.height / r.height, r.x0, r.y0)
        except Exception:
            pass
    return page_meta(page), samples, channels, info
