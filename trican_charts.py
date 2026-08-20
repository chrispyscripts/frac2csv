"""Trican treatment charts — both report layouts.

Trican filings DO carry treatment charts; the charts are embedded raster
images rather than vector art, which is why the corpus survey's vector
detector recorded "NO charts" for the whole Trican corpus and why the Lab
showed only trican2's STAGE INFORMATION tables.  704 documents carry the
"trican" marker; 347 of them (341 wells) hold charts, in two layouts:

  * layout A — "POST-FRAC SUMMARY" (2015-2016), 82 documents / 76 wells /
    2,524 chart pages.  These are the same files trican2.py reads, so the
    STAGE INFORMATION table on the next page is a per-stage answer key.
    Read by detect()/extract_page().
  * layout B — "Stage # N" (2024-2025), 265 documents / 265 wells / 10,387
    chart pages.  Each page prints its own Pressure / Wellhead Rate /
    Proppant Conc average and maximum, which is the answer key here.
    Read by detect_b()/extract_page_b().

No existing template reads either.  auto_raster.extract cannot: its hue
families split layout A's maroon BH Pressure between "red" and "orange" and
fold both of layout A's greens into one, and on layout B they miss both
olives outright (olive's green channel is 5 above its red, the green rule
wants 30) while its time-axis reader finds nothing at all (layout B's clock
labels sit around ink-sum 620, every ink test in the tree is written for
<450).  hal1/step1 are close cousins structurally and their helpers
(_frame_bbox, hue-free tick fitting, curve_positions, ct.resample) are
reused here, but their axis and time layouts are not these.

LAYOUT A (one template, 2015-2016, pixel-identical across all 82 documents):

  * per-stage page: title "Stage N: <top> - <bottom> m", then two 977x483
    images — "PRESSURES, RATES, AND CONCENTRATIONS" above, "CHEMICAL
    CONCENTRATIONS" below.  Whole-job pages repeat both at 1265x720 under
    "CONTINUOUS ...".
  * main chart: plot frame in black, light-grey gridlines, five colour-keyed
    series, legend above the frame.  Time runs along x, twice: clock time
    (HH:MM) above the frame, elapsed minutes below it.  Value ticks sit
    OUTSIDE the frame — pressure on the left, a shared rate/concentration
    scale on the right.
  * the left axis is titled "Pressure (MPa)" but its ticks are kPa
    (0..80000); the right axis is "Rate (m3/min) / Conc (100kg/m3)", so
    concentrations are read at 100x.  Both are corrected here, which is what
    makes the numbers line up with the STAGE INFORMATION table on the very
    next page.

LAYOUT B is documented at the section break further down.

Only the main chart of each layout is read.  Both layouts also file a
chemical-concentration chart, whose series are job-specific (FR-9, S-2,
Busan, CC-7, Aqucar GA50 ...) and one of which is always drawn in black or
near-black; naming them needs a legend OCR pass, which is not worth carrying
until someone asks for chemicals.

Both layouts return chart geometry in PAGE units (info["geom"]) and each
channel's axis read at the plot-frame edges (channel["axis_frame"]), so the
Lab can lay the source page behind the curves. See _attach_geom for the two
conventions that are easy to get wrong here.
"""
import re

import fitz
import numpy as np

import auto_raster as ar
import curve_trace as ct
from step1 import _frame_bbox, _page_geom

MAIN_TITLE = "PRESSURES, RATES, AND CONCENTRATIONS"
CHEM_TITLE = "CHEMICAL CONCENTRATIONS"

# Longest plausible SINGLE STAGE. Every other raster template rejects an
# implausible duration; this one could not use their flat cap, because layout
# A files whole-job CONTINUOUS pages that really do run half a day (00024 p123
# spans 51,300 s). So the cap is applied to per-stage pages only, and whole-job
# pages — which the page text names — are exempt.
#
# trican2's STAGE INFORMATION tables are the answer key for the number: across
# 2,253 stages the longest as-pumped Total Time is 416 min (24,984 s) and
# 99.9% finish inside 255 min. 30,000 s clears anything real by 20% and still
# catches 00430 p140, the mildest of that report's three misread axes at
# 33,569 s. A within-document ratio test was measured and rejected instead:
# real reports run a stage up to 11.5x their own median (00081), so no ratio
# tight enough to catch a misread is loose enough to spare a long stage.
STAGE_MAX_S = 30000


def detect(page):
    t = page.get_text()
    if MAIN_TITLE not in t.upper():
        return False
    if "trican" not in t.lower():
        return False
    return any(im[2] >= 700 and im[3] >= 400
               for im in page.get_images(full=True))


def page_meta(page):
    text = page.get_text()
    meta = {"stage": None, "uwi": "", "wa": "", "top_m": None, "base_m": None,
            "continuous": bool(re.search(r"\bCONTINUOUS\b", text))}
    m = re.search(r"\bStage\s+(\d+)\s*:\s*([\d.]+)\s*-\s*([\d.]+)\s*m", text)
    if m:
        meta["stage"] = int(m.group(1))
        meta["top_m"] = float(m.group(2))
        meta["base_m"] = float(m.group(3))
    m = re.search(r"(\d{4,5})\s*:\s*(\d{3}/[\dA-Z-]+W\d(?:/\d\d)?)", text)
    if m:
        meta["wa"] = m.group(1)
        meta["uwi"] = m.group(2)
    return meta


# ---------------------------------------------------------------- masks

def series_masks(img):
    """Exact-palette masks for the five plotted series.

    These are renders, not scans, so the curve cores land on their palette
    colour and everything else is a blend towards white.  auto_raster's broad
    hue families are the wrong tool here: they put the maroon BH Pressure
    trace half in "red" and half in "orange" (its blends carry g > b), and
    they fold both greens together.  Narrow rules keyed to this one palette
    separate all five, and the blend tails are simply left out — a curve one
    core pixel wide per column is all curve_positions needs.
    """
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    # The two concentrations are both green and were split by two INDEPENDENT
    # threshold rules, which left a gap between them: forest green demanded
    # |r-b| <= 30 and yellow-green demanded r-b >= 38, so ink sitting at r-b
    # around 36 answered to neither and was dropped. Measured on 00005 p75,
    # 564 of 1,736 greenish pixels — 32% — matched no rule, and not merely the
    # antialiased fringe: solid (72,156,36) and (156,204,120) both fall in the
    # dead zone. That is why the client reports pressure and rate good and
    # "conc having issues" (#105, #109) on a chart where WH Prop Conc came out
    # 73% blank and DH Prop Conc 51% against 0.3% for every other channel.
    #
    # So make the two a PARTITION rather than two filters. The confident cores
    # keep their original rules, bit for bit; everything else that is plainly
    # green ink is then handed to whichever of the two reference colours it
    # sits nearer. A partition cannot have a gap, and cannot double-count.
    _wh = (g - r >= 25) & (g - b >= 25) & (np.abs(r - b) <= 30)
    _dh = (g - b >= 55) & (r - b >= 38) & (g >= r)
    _green = (g > r + 8) & (g > b + 8) & ((r + g + b) < 700)
    _spare = _green & ~_wh & ~_dh
    if _spare.any():
        # distance to (34,139,34) forest vs (154,205,50) yellow-green
        d_wh = (r - 34) ** 2 + (g - 139) ** 2 + (b - 34) ** 2
        d_dh = (r - 154) ** 2 + (g - 205) ** 2 + (b - 50) ** 2
        _wh = _wh | (_spare & (d_wh <= d_dh))
        _dh = _dh | (_spare & (d_dh < d_wh))
    return {
        # (255,0,0) bright red, blends stay at r=255
        "surface": (r >= 200) & (r - g >= 90) & (r - b >= 90),
        # (116,0,0) maroon; never reaches the bright-red band
        "bh": (r < 190) & (r >= 55) & (r - g >= 33) & (r - b >= 33),
        # (0,116,191) medium blue
        "rate": (b - r >= 40) & (b - g >= 12),
        # (34,139,34) forest green
        "wh_conc": _wh,
        # (154,205,50) yellow-green
        "dh_conc": _dh,
    }


# key -> (label, unit, axis, factor applied to the axis reading).  The right
# axis is shared: it is titled "Rate (m3/min) / Conc (100kg/m3)", so the two
# concentration traces are read at 100x and the rate straight off.
SERIES = [
    ("bh", "BH Pressure", "MPa", "press", 1.0),
    ("surface", "Surface Pressure", "MPa", "press", 1.0),
    ("rate", "WH Rate", "m3/min", "rate", 1.0),
    ("wh_conc", "WH Prop Conc", "kg/m3", "rate", 100.0),
    ("dh_conc", "DH Prop Conc", "kg/m3", "rate", 100.0),
]


def _snap_zero(fit, y0, y1):
    """Pull a fitted axis onto round bounds, but only when its bottom lands
    on zero — which every scale on this template does.

    The guard is what makes auto_raster.snap_axis safe to use here: left to
    itself it snapped a 0.34 zero up to 0.5 on the 0..10 rate axis (34 kg/m3
    of bias), because 0.5 is a legal multiple.  Requiring the bottom to snap
    to exactly zero rejects that and still fixes the case this is for: a top
    label OCR'd as "0" instead of "100000", which drops the top tick from the
    fit and leaves the axis reading 100138.
    """
    if fit is None:
        return None
    a, b, n = fit
    top, bot = a + b * y0, a + b * y1
    t2, b2, changed = ar.snap_axis(top, bot)
    if not changed or b2 != 0 or t2 == b2:
        return fit
    b_new = (t2 - b2) / (y0 - y1)
    return (b2 - b_new * y1, b_new, n)


def _plausible(fit, y0, y1, top_range, alt_range=None):
    """Drop an axis fit whose bounds cannot be what the chart printed.

    Both scales start at zero on this template, so a fit is only kept when
    the bottom rule reads near zero and the top rule lands in the range the
    axis is known to use (in either of its two units, where it has two).
    """
    if fit is None:
        return None
    a, b, n = fit
    bot = a + b * y1
    top = a + b * y0
    span = abs(top - bot)
    if span <= 0 or abs(bot) > 0.04 * span:
        return None
    for lo, hi in [r for r in (top_range, alt_range) if r]:
        if lo <= top <= hi:
            return fit
    return None


def _first_row_band(strip):
    """The first band of TEXT rows under the axis -> (row_from, row_to).

    Two things sit between the frame and the labels: the second row of a
    2px-thick frame rule, and the row of tick marks.  The rule is dropped as
    a rule (it runs right across), and the ticks on height — a handful of 1px
    marks is five rows tall at most, a row of digits is ten or more.  Taking
    the first band regardless read the ticks and returned no numbers at all.
    """
    w = strip.shape[1]
    dark = (strip.sum(axis=2) < 450).sum(axis=1)
    on = (dark > max(2, w * 0.004)) & (dark < 0.25 * w)
    bands, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            bands.append((start, i)); start = None
    if start is not None:
        bands.append((start, len(on)))
    for b0, b1 in bands:
        if b1 - b0 >= 6 and dark[b0:b1].max() > w * 0.015:
            return max(0, b0 - 2), min(len(on), b1 + 2)
    return None


def time_axis(img, x0, x1, y1):
    """Read the "Elapsed Time (min)" labels -> (minutes at x0, min/px).

    auto_raster.time_calibration can read this row — the labels are plain
    decimal minutes — but it rejects any fit longer than 100000 s, and the
    whole-job charts run to 2336 minutes (39 h).  Reading it here also lets
    the fit be anchored on the frame: the first and last labels are printed
    against the frame rules, so two exact points beat a least-squares line
    through six OCR centroids.
    """
    from PIL import Image
    H, W, _ = img.shape
    strip = img[min(y1 + 1, H - 1):min(y1 + 46, H), :]
    if strip.size == 0:
        return None
    band = _first_row_band(strip)
    if band is None:
        return None
    lab = strip[band[0]:band[1], :]
    pts = []
    for ca, cb in _ink_columns(lab, gap=8):
        if cb - ca < 8:
            continue
        cx = (ca + cb) / 2.0
        if not (x0 - 60 <= cx <= x1 + 60):
            continue
        crop = lab[:, max(0, ca - 4):cb + 4]
        pil = Image.fromarray(crop.astype(np.uint8))
        pil = pil.resize((pil.width * 4, pil.height * 4), Image.LANCZOS)
        for text, _wx, _wy in ar.ocr_words(np.array(pil).astype(int), psm=7,
                                           whitelist="0123456789."):
            t = text.strip(".")
            if re.fullmatch(r"\d+(\.\d+)?", t):
                pts.append((float(t), cx))
                break
    if len(pts) < 3:
        return None
    fit = _ransac(pts, x0, x1)
    if fit is None:
        return None
    a, b, inl = fit
    edge = max(6.0, 0.03 * (x1 - x0))
    lo = min((pts[k] for k in inl), key=lambda p: p[1])
    hi = max((pts[k] for k in inl), key=lambda p: p[1])
    if abs(lo[1] - x0) <= edge and abs(hi[1] - x1) <= edge and lo[0] != hi[0]:
        b = (hi[0] - lo[0]) / (x1 - x0)
        a = lo[0] - b * x0
    if b <= 0:
        return None
    return a, b


def _ink_columns(strip, gap=4):
    """Column runs of dark ink in a tick strip -> [(x_from, x_to)]."""
    dark = strip.sum(axis=2) < 450
    col = dark.sum(axis=0) > 0
    out, start, run = [], None, 0
    for i, v in enumerate(col):
        if v:
            if start is None:
                start = i
            run = 0
        elif start is not None:
            run += 1
            if run >= gap:
                out.append((start, i - run + 1)); start = None
    if start is not None:
        out.append((start, len(col)))
    return out


def _ocr_column(img, xa, xb, y0, y1, side):
    """OCR the tick numbers in one vertical strip -> [(value, row)].

    The numbers are isolated by ink geometry before OCR, not after.  Each
    strip also carries a rotated axis title, and "Rate (m3/min) / Conc
    (100kg/m3)" hands the fit a "100" and a "3" that are not ticks — enough
    on its own to fit the right-hand scale as 12..100 on a 0..10 axis.  The
    title always sits farther from the frame than the numbers and is
    separated by clear whitespace, so the run of ink nearest the frame is the
    tick column.
    """
    from PIL import Image
    xa = max(0, xa)
    if xb <= xa:
        return []
    ya, yb = max(0, y0 - 18), min(img.shape[0], y1 + 18)
    runs = _ink_columns(img[ya:yb, xa:xb])
    if not runs:
        return []
    pick = max(runs, key=lambda r: r[1]) if side == "left" \
        else min(runs, key=lambda r: r[0])
    ca, cb = max(0, xa + pick[0] - 3), min(img.shape[1], xa + pick[1] + 3)
    strip = img[:, ca:cb]
    if strip.size == 0:
        return []
    pil = Image.fromarray(strip.astype(np.uint8))
    pil = pil.resize((pil.width * 3, pil.height * 3), Image.LANCZOS)
    words = ar.ocr_words(np.array(pil).astype(int), psm=6,
                         whitelist="0123456789.-")
    pts = []
    for text, _cx, cy in words:
        t = text.replace(",", "").strip("-.")
        if re.fullmatch(r"\d+(\.\d+)?", t):
            py = int(cy / 3)
            if y0 - 18 <= py <= y1 + 18:
                pts.append((float(t), py))
    return pts


def grid_rows(img, x0, x1, y0, y1):
    """Rows carrying a gridline or a frame rule, inside the plot only.

    The template draws its horizontal ticks as full-width light-grey rules
    (211,211,211) with the black frame at both ends, so the tick ROWS are
    exact even though the OCR'd label centroids are not.  A row counts only
    when most of its pixels are neutral grey: a long flat pressure trace also
    fills a row right across, and a brightness test alone would call it a tick.
    """
    band = img[y0:y1 + 1, x0 + 2:x1 - 1]
    if band.size == 0:
        return []
    mx = band.max(axis=2)
    mn = band.min(axis=2)
    grey = (mx - mn < 20) & (mx < 240)
    hit = grey.mean(axis=1) > 0.6
    rows, run = [], []
    for i, v in enumerate(hit):
        if v:
            run.append(i)
        elif run:
            rows.append(y0 + int(np.mean(run)))
            run = []
    if run:
        rows.append(y0 + int(np.mean(run)))
    return rows


def _ransac(pts, y0, y1, tol_frac=0.012):
    """pts [(value, row)] -> (a, b, inlier indices) for value = a + b*row."""
    n = len(pts)
    best = (0, None)
    for i in range(n):
        for j in range(i + 1, n):
            (vi, ci), (vj, cj) = pts[i], pts[j]
            if abs(cj - ci) < 20 or vi == vj:
                continue
            b = (vj - vi) / (cj - ci)
            a = vi - b * ci
            tol = max(1e-9, tol_frac * abs(b) * (y1 - y0))
            inl = [k for k in range(n)
                   if abs(a + b * pts[k][1] - pts[k][0]) <= tol]
            if len(inl) > best[0]:
                best = (len(inl), inl)
    if best[1] is None or best[0] < 3:
        return None
    inl = best[1]
    coords = np.array([pts[k][1] for k in inl], float)
    vals = np.array([pts[k][0] for k in inl], float)
    A = np.vstack([np.ones(len(inl)), coords]).T
    (a, b), *_ = np.linalg.lstsq(A, vals, rcond=None)
    if abs(b) < 1e-12:
        return None
    return float(a), float(b), inl


def _axis_fit(pts, rows, y0, y1):
    """Tick readings -> (value = a + b*row, n_inliers).

    Fitting the OCR'd label centroids alone lands 1-2% high at the top of the
    axis and, worse, several units off at zero: the right-hand scale fitted
    0.34 for its zero, which is 34 kg/m3 of pure bias on every concentration
    reading, and auto_raster.snap_axis cannot rescue it (0.34 snaps to 0.5 on
    a 0..10 axis, not to 0).

    So the fit is anchored on the frame instead.  This template prints its
    first and last tick ON the frame rules, top and bottom, which is exact —
    unlike a centroid.  Gridline snapping is only the fallback, and is
    deliberately NOT applied to the right-hand axis by default: the whole-job
    charts scale the two sides differently (left 0..80000 in five steps,
    right 0..10 in six), so half the right-hand labels sit between gridlines
    and snapping them drags the top of the scale from 10 down to 8.
    """
    if len(pts) < 3:
        return None
    fit = _ransac([(v, float(y)) for v, y in pts], y0, y1)
    if fit is None:
        return None
    a, b, inl = fit
    edge = max(8.0, 0.06 * (y1 - y0))
    top = min((pts[k] for k in inl), key=lambda p: p[1])
    bot = max((pts[k] for k in inl), key=lambda p: p[1])
    if abs(top[1] - y0) <= edge and abs(bot[1] - y1) <= edge \
            and top[0] != bot[0]:
        b2 = (top[0] - bot[0]) / (y0 - y1)
        return (bot[0] - b2 * y1, b2, len(inl))
    if rows:                                   # fallback: pull onto gridlines
        snapped = []
        for v, py in pts:
            near = min(rows, key=lambda r: abs(r - py))
            if abs(near - py) <= max(6, 0.04 * (y1 - y0)):
                snapped.append((v, float(near)))
        got = _ransac(snapped, y0, y1, tol_frac=0.004) if len(snapped) >= 3 \
            else None
        if got:
            return got[0], got[1], len(got[2])
    return a, b, len(inl)


def extract_image(img, sample_sec=1.0):
    """-> (samples, channels, info) for one main Trican chart image."""
    img = np.asarray(img).astype(int)
    box = _frame_bbox(img)
    if box is None:
        raise ValueError("trican: no plot frame")
    x0, y0, x1, y1 = box
    if x1 - x0 < 300 or y1 - y0 < 120:
        raise ValueError("trican: frame too small")

    mcal = time_axis(img, x0, x1, y1)
    if mcal is not None:
        ta, tb = mcal[0] * 60.0, mcal[1] * 60.0     # minutes -> seconds
    else:
        tcal = ar.time_calibration(img, x0, x1, y1)
        if tcal is None:
            raise ValueError("trican: time axis unreadable")
        ta, tb = tcal
    t_start = ta + tb * x0
    n = int((ta + tb * x1) - t_start)
    if not (60 < n < 400000):
        raise ValueError(f"trican: implausible duration {n}s")

    rows = grid_rows(img, x0, x1, y0, y1)
    press = _axis_fit(_ocr_column(img, 0, x0 - 1, y0, y1, "left"),
                      rows, y0, y1)
    rate = _axis_fit(_ocr_column(img, x1 + 2, img.shape[1], y0, y1, "right"),
                     rows, y0, y1)
    press = _plausible(_snap_zero(press, y0, y1), y0, y1,
                       (20.0, 250.0), (15000.0, 250000.0))
    rate = _plausible(_snap_zero(rate, y0, y1), y0, y1, (1.5, 60.0), None)
    fits = {"press": press, "rate": rate}
    # The left axis is titled MPa but ticked in kPa on every document seen;
    # decide per chart rather than trusting the title, since the title is
    # demonstrably wrong.
    press_scale = 0.001 if press and abs(press[0] + press[1] * y0) > 1000 \
        else 1.0

    masks = series_masks(img)
    samples = np.arange(int(n / sample_sec)) * sample_sec
    channels, notes = [], []
    for key, label, unit, axis, factor in SERIES:
        scale = factor * (press_scale if axis == "press" else 1.0)
        cal = fits.get(axis)
        mask = masks.get(key)
        if mask is None or not mask.any():
            continue
        # Read one row PAST the frame, and pull anything found there back onto
        # it.  A curve resting at zero is drawn ON the bottom frame line, and
        # the frame is painted over it: the pen is 2px, so it straddles y1 and
        # y1+1, the black frame takes y1, and the only surviving green is the
        # row a [y0+1:y1] crop throws away.  That is the whole of the client's
        # "conc having issues" (#105, #109) — the tracer was discarding
        # nothing, the mask simply never saw the ink.  Measured on 00005 p75,
        # 311 of the 327 blank columns have conc ink at y1+1; corpus-wide over
        # 103 chart pages, 22,262 of 23,311 (95.5%).
        #
        # Safe for the other three series because they put nothing there.
        # Counting every masked pixel below the frame across those 103 pages:
        # BH Pressure, Surface Pressure and WH Rate score 0 on every row from
        # y1 to y1+4, while WH Prop Conc has 9,582 and DH Prop Conc 24,476 —
        # all of them on y1+1 exactly, none on y1+2 or beyond.  So this widens
        # by one row, not by a guess, and only the two conc traces can move.
        y_end = min(y1 + 2, mask.shape[0])
        sub = mask[y0 + 1:y_end, x0 + 1:x1]
        cov = float(sub.any(axis=0).mean())
        if cov < 0.05:
            continue
        if cal is None:
            notes.append(f"{label}: {axis} axis unreadable")
            continue
        a, bb, ntick = cal
        # Clamp to the frame rather than reading the row literally: y1 is the
        # axis zero, so a value taken at y1+1 would export a small NEGATIVE
        # concentration for ink the chart drew to mean zero.  The clamp only
        # bites where the pen fell below the frame; a curve inside the plot is
        # untouched.
        py = np.minimum(ar.curve_positions(sub) + y0 + 1, float(y1))
        vals = (a + bb * py) * scale
        n_cols = sub.shape[1]
        t_cols = (ta + tb * (np.arange(n_cols) + x0 + 1)) - t_start
        if np.isfinite(vals).sum() < 30:
            continue
        v = ct.resample(samples, t_cols, vals)
        # This channel's axis read AT the plot frame's top and bottom edges —
        # the same two rows geom's v0/v1 quote, in the same units the values
        # are exported in. Ghost mode stretches the page between those edges,
        # so a curve drawn against this pair lands on its own ink; drawn
        # against the tick range alone it sits a constant fraction of the plot
        # away, because the outermost tick is not the frame.
        channels.append({"key": key, "label": label, "unit": unit,
                         "color": "", "values": v, "ticks": ntick,
                         "coverage": cov,
                         "axis_frame": (float((a + bb * y0) * scale),
                                        float((a + bb * y1) * scale))})
    if not channels:
        raise ValueError("trican: no channel calibrated; " + "; ".join(notes[:3]))
    # t0_seconds is the chart's own elapsed-time origin, kept because these
    # per-stage windows are cut out of ONE job-long clock: stage 5 starts at
    # 415 min, not at 0, and the exported samples restart at 0.
    info = {"plot": box, "t0_seconds": float(t_start), "duration_s": int(n),
            "notes": notes, "press_scale": press_scale,
            "press_axis": None if press is None else
            (press[0] + press[1] * y1, press[0] + press[1] * y0),
            "rate_axis": None if rate is None else
            (rate[0] + rate[1] * y1, rate[0] + rate[1] * y0)}
    return samples, channels, info


def _main_image(page):
    """The PRESSURES/RATES/CONC image on this page.

    Chosen by the printed title rather than by size or order: the chemical
    chart is the same 977x483 render and sits directly below, so "first" or
    "biggest" picks it whenever the page order flips.
    """
    imgs = [im for im in page.get_images(full=True)
            if im[2] >= 700 and im[3] >= 400]
    if not imgs:
        raise ValueError("trican: no chart image")
    rects = []
    for im in imgs:
        try:
            rs = page.get_image_rects(im[0])
        except Exception:
            rs = []
        if rs:
            rects.append((rs[0].y0, im))
    if not rects:
        return imgs[0]
    rects.sort()
    hits = page.search_for(MAIN_TITLE)
    if hits:
        ty = min(h.y0 for h in hits)
        below = [(y, im) for y, im in rects if y >= ty - 4]
        if below:
            return below[0][1]
    return rects[0][1]


def _pixmap(doc, im):
    pix = fitz.Pixmap(doc, im[0])
    if pix.colorspace is None:
        raise ValueError("trican: mask image")
    if pix.alpha or pix.colorspace.n != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3)


def _attach_geom(page, im, img, info):
    """Chart geometry in PAGE units, so the Lab can lay the source page
    behind our curves (ghost mode) instead of showing a blank overlay.

    Everything above works in IMAGE pixels; the page embeds that image at a
    known rect, so the conversion is a plain scale + offset — exactly
    step1/hal1's raster case, and it uses their converter to inherit their
    convention. Two things that convention gets right and are easy to get
    wrong here:

      - `ta` comes out relative to the STAGE start. It has to: layout A's
        elapsed axis is CUMULATIVE OVER THE WHOLE JOB (stage 5 of 00041 runs
        415.0-477.9 min) while the exported samples restart at 0.
        _page_geom subtracts info["t0_seconds"], which is that stage's
        origin on the job clock.
      - v0/v1 are the frame's top and bottom rows, and each channel's
        axis_frame is its axis read at those SAME two rows. Quote them at
        different rows and every curve sits a constant distance off its ink.
    """
    try:
        r = page.get_image_rects(im[0])[0]
    except Exception:
        return
    if r.width <= 1 or r.height <= 1:
        return
    h, w = img.shape[:2]
    info["geom"] = _page_geom(info, w / r.width, h / r.height, r.x0, r.y0)


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, channels, info)"""
    im = _main_image(page)
    img = _pixmap(page.parent, im)
    meta = page_meta(page)
    samples, channels, info = extract_image(img, sample_sec)
    if not meta.get("continuous") and info["duration_s"] > STAGE_MAX_S:
        raise ValueError("trican: implausible stage duration "
                         f"{info['duration_s']}s")
    _attach_geom(page, im, img, info)
    return meta, samples, channels, info


# ===================================================================
# Layout B — the 2024/2025 "Stage # N" reports
# ===================================================================
#
# A completely different render: 900x500 (main) + 900x300 (chemical) per
# stage page, no plot frame, dotted grey gridlines, legend UNDER the plot,
# clock-time x axis, and THREE value axes — pressure on the left, wellhead
# rate and proppant concentration stacked on the right, each printed in its
# series' own colour.  Nothing in the tree reads it: auto_raster.extract
# fails on the time axis (the labels are too pale for its <400 ink test) and
# its hue families miss both olives outright (olive has g only 5 above r,
# and the green rule wants 30).
#
# The page text carries its own answer key — "Pressure Average .. Maximum ..",
# "Wellhead Rate ..", "Proppant Conc .." — which is what the numbers below
# were checked against.

B_SERIES = [
    ("mainline", (255, 0, 0), "Mainline Pressure", "MPa", "press"),
    ("monitor", (189, 153, 153), "Monitor Pressure", "MPa", "press"),
    ("wh_rate", (78, 173, 228), "WH Slurry Rate", "m3/min", "rate"),
    ("wh_conc", (92, 97, 5), "WH Prop Conc", "kg/m3", "conc"),
    ("dh_conc", (199, 204, 51), "DH Prop Conc", "kg/m3", "conc"),
]
B_RADIUS = 42


def b_masks(img):
    """Nearest-palette masks, cores only.

    The palette is byte-identical on every layout-B document sampled, so a
    radius test on the exact colours beats any hue rule — and it has to,
    because Monitor Pressure (189,153,153) is only 67 away from the grey the
    axis labels are printed in, and the two olives are 6 apart in hue.
    """
    flat = img.reshape(-1, 3)
    d = np.stack([((flat - np.array(c)) ** 2).sum(axis=1)
                  for _k, c, _l, _u, _a in B_SERIES], axis=1)
    best = d.argmin(axis=1)
    ok = d[np.arange(len(flat)), best] <= B_RADIUS ** 2
    out = {}
    for i, (key, _c, _l, _u, _a) in enumerate(B_SERIES):
        out[key] = ((best == i) & ok).reshape(img.shape[:2])
    return out


def _b_row_groups(mask_counts, thresh):
    groups, run = [], []
    for i, v in enumerate(mask_counts > thresh):
        if v:
            run.append(i)
        elif run:
            groups.append(run); run = []
    if run:
        groups.append(run)
    return groups


def b_box(img):
    """-> (x0, y0, x1, y1, gridline rows).

    There is no frame to find.  The baseline is the densest near-full-width
    row in the lower half — the axis rule, drawn solid where the gridlines
    are dotted — and the plot's left and right edges are the median span of
    the gridlines above it, which run the full width of the plot.
    """
    H, W = img.shape[:2]
    nw = img.sum(axis=2) < 720
    cnt = nw.sum(axis=1)
    lower = cnt.copy()
    lower[:H // 2] = 0
    y1 = int(np.argmax(lower))
    if cnt[y1] < 0.35 * W:
        raise ValueError("trican-B: no axis rule")
    rows = [g[len(g) // 2] for g in _b_row_groups(cnt[:y1 - 2], 0.28 * W)]
    if len(rows) < 3:
        raise ValueError("trican-B: no gridlines")
    # The longest near-solid run in the row, NOT the row's ink extent: every
    # tick label is printed centred on its own gridline, so the extent runs
    # out past the axis titles and puts the plot's right edge 60px inside the
    # label block.  A dotted gridline breaks by 2-3px; the gap to the first
    # label is far wider, so a 3px tolerance separates them cleanly.
    spans = []
    for r in rows + [y1]:
        xs = np.where(nw[r])[0]
        if len(xs) < 10:
            continue
        best = cur = (xs[0], xs[0])
        for x in xs[1:]:
            cur = (cur[0], x) if x - cur[1] <= 3 else (x, x)
            if cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        spans.append(best)
    if not spans:
        raise ValueError("trican-B: no gridline span")
    x0 = int(np.median([sp[0] for sp in spans]))
    x1 = int(np.median([sp[1] for sp in spans]))
    if x1 - x0 < 300:
        raise ValueError("trican-B: plot too narrow")
    return x0, rows[0], x1, y1, rows + [y1]


def _b_darken(a, cut=700):
    """Pale grey label ink -> black on white, so OCR and the band finder can
    see it.  The clock labels sit around sum 620; every ink test in the tree
    is written for sum < 400-450 text and finds nothing at all."""
    m = a.sum(axis=2) < cut
    out = np.full(a.shape, 255, dtype=np.uint8)
    out[m] = 0
    return out.astype(int)


def _b_group_class(img, ca, cb, ya, yb):
    """Colour class of one ink column: press / rate / conc, or None."""
    crop = img[ya:yb, ca:cb]
    ink = crop.sum(axis=2) < 690
    if ink.sum() < 12:
        return None
    r, g, b = [float(crop[..., i][ink].mean()) for i in range(3)]
    if r > g + 35 and r > b + 35:
        return "press"
    if b > r + 35 and b > g + 10:
        return "rate"
    if g > b + 35 and g > r - 25:
        return "conc"
    return None


def _b_read_rotated(col, y0, y1):
    """Read one rotated tick column, trying both quarter turns.

    The three columns are not turned the same way — the pressure labels read
    one way and the concentration labels the other, so a fixed rotation gets
    half of them mirrored: "200" comes back as "002" and "600" as "006", which
    still parse as numbers and still land on the right rows.  Both turns are
    OCR'd and the one whose readings actually fall on a straight line wins.
    """
    from PIL import Image
    h_s = col.shape[0]
    best_pts, best_score = [], 0
    for k in (-1, 1):
        turned = np.rot90(col, k=k)
        pil = Image.fromarray(turned.astype(np.uint8))
        pil = pil.resize((pil.width * 3, pil.height * 3), Image.LANCZOS)
        pts = []
        for text, cx, _cy in ar.ocr_words(np.array(pil).astype(int), psm=6,
                                          whitelist="0123456789.-"):
            t = text.replace(",", "").strip("-.")
            if re.fullmatch(r"\d+(\.\d+)?", t):
                px = int(cx / 3)
                py = (h_s - 1 - px) if k == -1 else px
                if y0 - 14 <= py <= y1 + 14:
                    pts.append((float(t), py))
        fit = _ransac(pts, y0, y1) if len(pts) >= 3 else None
        score = len(fit[2]) if fit else 0
        if score > best_score:
            best_pts, best_score = pts, score
    return best_pts


def b_tick_points(img, x0, x1, y0, y1):
    """-> {axis: [(value, row)]} from the three coloured tick columns.

    Layout B prints its value-axis labels ROTATED 90 degrees, reading bottom
    to top, so each strip is turned upright before OCR and the word's x in
    the turned image maps back to a row in the original.  Read flat they come
    back as "3" and "2" at random rows, which is what the first pass did.
    """
    from PIL import Image
    H, W = img.shape[:2]
    ya, yb = max(0, y0 - 14), min(H, y1 + 14)
    out = {}
    for xa, xb, side in ((0, max(1, x0 - 3), "left"),
                         (min(W - 1, x1 + 3), W, "right")):
        runs = _ink_columns(_b_darken(img[ya:yb, xa:xb]), gap=5)
        for ca, cb in runs:
            if cb - ca < 5:
                continue
            cls = _b_group_class(img, xa + ca, xa + cb, ya, yb)
            if cls is None:
                continue
            # the axis TITLE is printed in the same colour as its numbers and
            # sits outside them, so colour alone cannot tell them apart —
            # the column nearest the plot is the numbers
            dist = (x0 - (xa + cb)) if side == "left" else ((xa + ca) - x1)
            prev = out.get(cls)
            if prev is not None and prev[0] <= dist:
                continue
            col = _b_darken(img[:, max(0, xa + ca - 3):xa + cb + 3])
            pts = _b_read_rotated(col, y0, y1)
            if len(pts) >= 3:
                out[cls] = (dist, pts)
    return {k: v[1] for k, v in out.items()}


def b_time_axis(img, x0, x1, y1):
    """Clock-time labels under the plot -> (seconds at x0, sec/px)."""
    from PIL import Image
    H, W = img.shape[:2]
    strip = _b_darken(img[min(y1 + 2, H - 1):min(y1 + 46, H), :])
    band = _first_row_band(strip)
    if band is None:
        return None
    lab = strip[band[0]:band[1], :]
    pts = []
    for ca, cb in _ink_columns(lab, gap=8):
        if cb - ca < 12:
            continue
        cx = (ca + cb) / 2.0
        if not (x0 - 40 <= cx <= x1 + 40):
            continue
        crop = lab[:, max(0, ca - 4):cb + 4]
        pil = Image.fromarray(crop.astype(np.uint8))
        pil = pil.resize((pil.width * 4, pil.height * 4), Image.LANCZOS)
        for text, _wx, _wy in ar.ocr_words(np.array(pil).astype(int), psm=7,
                                           whitelist="0123456789:"):
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
            if m:
                pts.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60, cx))
                break
    if len(pts) < 3:
        return None
    pts.sort(key=lambda p: p[1])
    vals = [p[0] for p in pts]
    for i in range(1, len(vals)):                  # unwrap midnight
        if vals[i] < vals[i - 1] - 3600:
            for j in range(i, len(vals)):
                vals[j] += 86400
    pts = [(v, p[1]) for v, p in zip(vals, pts)]
    fit = _ransac(pts, x0, x1, tol_frac=0.02)
    if fit is None or fit[1] <= 0:
        return None
    return fit[0], fit[1]


B_AXIS_RANGE = {"press": (10.0, 250.0), "rate": (1.5, 60.0),
                "conc": (50.0, 5000.0)}

# Concentration per unit of the rate axis. Layout A hard-codes the same 100 in
# its SERIES table ("concentration traces are read at 100x and the rate
# straight off"); layout B prints only the zero on its conc axis for the same
# reason — the two axes are one.
CONC_PER_RATE = 100.0
# How far the traced maximum may sit from the one the page prints before the
# derivation is refused. 0.6% is the worst of three measured pages, so 8%
# leaves room for a curve clipped at the frame or a peak one pixel wide
# without ever letting a wrong scale through.
CONC_CHECK_TOL = 0.08


def _is_rule_row(mask, r, x0, x1):
    """Does this row of the mask hold a dotted RULE rather than a curve?

    A dotted rule is dozens of one-pixel dashes spread across the plot; a
    curve crossing or lying along the row is a handful of long runs. On
    00583 p33 the rule rows carry ~360 runs of median length 1 and the curve
    row carries 8 of median 22, so the two are not close.
    """
    v = np.asarray(mask[r, x0 + 5:x1 - 5], bool)
    idx = np.flatnonzero(v)
    if len(idx) < 20:
        return False
    cuts = np.flatnonzero(np.diff(idx) > 1) + 1
    runs = [len(g) for g in np.split(idx, cuts)]
    return len(runs) >= 20 and float(np.median(runs)) <= 3.0


def extract_image_b(img, sample_sec=1.0):
    img = np.asarray(img).astype(int)
    x0, y0, x1, y1, rows = b_box(img)
    tcal = b_time_axis(img, x0, x1, y1)
    if tcal is None:
        raise ValueError("trican-B: time axis unreadable")
    ta, tb = tcal
    t_start = ta + tb * x0
    n = int((ta + tb * x1) - t_start)
    if not (60 < n < 400000):
        raise ValueError(f"trican-B: implausible duration {n}s")

    pts = b_tick_points(img, x0, x1, y0, y1)
    fits = {}
    for axis, rng in B_AXIS_RANGE.items():
        f = _axis_fit(pts.get(axis, []), rows, y0, y1)
        fits[axis] = _plausible(_snap_zero(f, y0, y1), y0, y1, rng)

    # The concentration axis usually prints ONE label, and it is "0".
    #
    # Rendering 00583 p33's right margin and reading it: the Wellhead Rate
    # axis prints ten ticks, 0 through 9, and the Concentration (kg/m³) axis
    # prints a single 0. A fit needs three, so there was never an axis to
    # find and both conc channels were dropped on every page of the file —
    # which is #564, and which read as a tracing failure when it is not one.
    #
    # It is not missing, it is SHARED. Layout A says so already, in its own
    # SERIES table: its two conc traces are read against the "rate" axis with
    # a factor of 100. Same vendor, same chart family — rate 0..10 is conc
    # 0..1000, which is why the concentration axis bothers to print only its
    # zero.
    #
    # Derived, never assumed: the caller checks the result against the
    # "Conc Average .. Maximum .." line the page prints for itself, and drops
    # the channels if the two disagree. Against that answer key on three
    # pages this lands within 0.6% — 480.4 against a printed 483.1, 539.1
    # against 537.0, 553.8 against 552.2.
    if fits.get("conc") is None and fits.get("rate") is not None:
        ra, rb, rn = fits["rate"]
        fits["conc"] = (ra * CONC_PER_RATE, rb * CONC_PER_RATE, rn)
        info_conc_derived = True
    else:
        info_conc_derived = False

    masks = b_masks(img)
    # The dotted gridlines are drawn in (92,97,5) — the SAME colour as the WH
    # Prop Conc trace — so that series' mask arrives with eight full-width
    # rules in it and the trace reads 499 kg/m3 (a gridline) instead of 162.
    # Blank the gridline rows out of any mask whose colour collides; a curve
    # loses 3px where it crosses a rule, which curve_positions bridges.
    # The rule colour is read PER ROW, and a row is only blanked when it
    # actually holds a rule.
    #
    # Two things were wrong. The colour was taken from the middle row alone
    # and applied to all of them — but this template tints each axis's rules
    # to match that axis's curve, so the top rule is Prop Conc olive while the
    # rest are Slurry Rate blue, and one sample cannot describe both.
    #
    # Worse, every row in `rows` was blanked across the FULL WIDTH whether it
    # held a rule or not. On 00583 p33 rows 132 and 136 are adjacent and only
    # 132 is a rule: 136 is the rate curve. Blanking it took the curve out for
    # its whole horizontal extent, and WH Slurry Rate went from 96.6% of
    # columns carrying ink to 59.9%, leaving 40.8% of the trace as NaN for
    # resample to bridge or blank. That is the "interpolation" everyone was
    # looking at — the interpolator was fine, what it was handed was not.
    #
    # A rule and a curve do not look alike along the row. Measured on that
    # page: a rule is ~360 runs of ONE pixel, a 1-on-1-off dotted line; the
    # curve at row 136 is 8 runs with a median of 22 and a longest of 46. So
    # ask the row.
    for r in rows:
        seg = img[r, x0 + 5:x1 - 5]
        band = seg[seg.sum(axis=1) < 720]
        if not len(band):
            continue
        vals, counts = np.unique(band, axis=0, return_counts=True)
        gcol = vals[counts.argmax()]
        for key, col, _l, _u, _a in B_SERIES:
            if ((np.array(col) - gcol) ** 2).sum() > B_RADIUS ** 2:
                continue
            if not _is_rule_row(masks[key], r, x0, x1):
                continue                  # the curve happens to run here
            masks[key][max(0, r - 1):r + 2, :] = False
    samples = np.arange(int(n / sample_sec)) * sample_sec
    channels, notes = [], []
    for key, _c, label, unit, axis in B_SERIES:
        cal, mask = fits.get(axis), masks.get(key)
        if mask is None or not mask.any():
            continue
        sub = mask[y0:y1, x0 + 1:x1]
        cov = float(sub.any(axis=0).mean())
        if cov < 0.05:
            continue
        if cal is None:
            notes.append(f"{label}: {axis} axis unreadable")
            continue
        a, bb, ntick = cal
        py = ar.curve_positions(sub) + y0
        vals = a + bb * py
        t_cols = (ta + tb * (np.arange(sub.shape[1]) + x0 + 1)) - t_start
        if np.isfinite(vals).sum() < 30:
            continue
        channels.append({"key": key, "label": label, "unit": unit, "color": "",
                         "values": ct.resample(samples, t_cols, vals),
                         "ticks": ntick, "coverage": cov,
                         "axis_frame": (float(a + bb * y0),
                                        float(a + bb * y1))})
        # A sparse channel is not necessarily a broken one, and on this
        # template it usually is not. Say where the absence is, because "WH
        # Prop Conc is 31% empty" reads as a fault and "it is not drawn until
        # a third of the way in" reads as the chart.
        #
        # Measured over all 23 chart pages of 00583: WH Prop Conc has 109
        # blank runs totalling 8,148 columns, and 6,882 of those columns —
        # 84% — are before its first reading or after its last. That is the
        # pad and the flush, where the wellhead concentration has not started
        # or has finished, and ct.resample is right to hand back nothing
        # rather than extend the curve into them.
        if cov < 0.9:
            lit = np.flatnonzero(sub.any(axis=0))
            drawn = (lit[0] / sub.shape[1], (lit[-1] + 1) / sub.shape[1])
            inner = sub[:, lit[0]:lit[-1] + 1].any(axis=0)
            holes = int(np.count_nonzero(np.diff(np.concatenate(
                ([True], inner, [True]))) == -1))
            notes.append(
                f"{label}: drawn from {drawn[0]*100:.0f}% to {drawn[1]*100:.0f}% "
                f"of the chart's width, with {holes} gap(s) inside that span. "
                f"Outside it the chart draws no curve, so nothing is exported "
                f"there rather than the trace being extended")
    if not channels:
        raise ValueError("trican-B: no channel calibrated; "
                         + "; ".join(notes[:3]))
    info = {"plot": (x0, y0, x1, y1), "t0_seconds": float(t_start),
            "duration_s": int(n), "notes": notes,
            "conc_derived": info_conc_derived,
            "axes": {k: None if v is None else (v[0] + v[1] * y1,
                                                v[0] + v[1] * y0)
                     for k, v in fits.items()}}
    return samples, channels, info


B_STAGE = re.compile(r"Stage\s*#\s*(\d+)")


def _b_images(page):
    return [im for im in page.get_images(full=True)
            if 850 <= im[2] <= 1400 and 440 <= im[3] <= 620]


def detect_b(page):
    t = page.get_text()
    if not B_STAGE.search(t) or "trican" not in t.lower():
        return False
    if MAIN_TITLE in t.upper():             # layout A, read by detect()
        return False
    return bool(_b_images(page))


def page_meta_b(page):
    """Stage id and the report's own printed maxima, which are on the page."""
    text = page.get_text()
    meta = {"stage": None, "uwi": "", "depth_m": None, "continuous": False,
            "printed": {}}
    m = B_STAGE.search(text)
    if m:
        meta["stage"] = int(m.group(1))
    m = re.search(r"Depth\s+([\d.]+)\s*m", text)
    if m:
        meta["depth_m"] = float(m.group(1))
    m = re.search(r"(\d{3}/[a-zA-Z0-9-]+/[0-9A-Za-z-]+/\d{2})", text)
    if m:
        meta["uwi"] = m.group(1)
    else:
        m = re.search(r"(\d{3}/\d{2}-\d{2}-\d{3}-\d{2}W\d(?:/\d{2})?)", text)
        if m:
            meta["uwi"] = m.group(1)
    for key, pat in (
            ("press_max", r"Pressure\s+Average\s+[\d.]+MPa\s+Maximum\s+([\d.]+)MPa"),
            ("press_avg", r"Pressure\s+Average\s+([\d.]+)MPa"),
            ("rate_max", r"Rate\s+Average\s+[\d.]+m³/min\s+Maximum\s+([\d.]+)m³/min"),
            ("rate_avg", r"Rate\s+Average\s+([\d.]+)m³/min"),
            ("conc_max", r"Conc\s+Average\s+[\d.]+kg/m³\s+Maximum\s+([\d.]+)kg/m³"),
            ("conc_avg", r"Conc\s+Average\s+([\d.]+)kg/m³")):
        mm = re.search(pat, text)
        if mm:
            meta["printed"][key] = float(mm.group(1))
    return meta


def _b_main_image(page):
    """The pressures/rate/conc render: the taller of the two on the page.

    The chemical chart is 900x300 against the main chart's 900x500 and is
    always second, but height is what actually separates them.
    """
    imgs = _b_images(page)
    if not imgs:
        raise ValueError("trican-B: no chart image")
    return max(imgs, key=lambda im: im[3])


def extract_page_b(page, sample_sec=1.0):
    """-> (meta, samples, channels, info)"""
    im = _b_main_image(page)
    img = _pixmap(page.parent, im)
    samples, channels, info = extract_image_b(img, sample_sec)
    # Layout B has no whole-job page — detect_b requires a "Stage # N"
    # caption — so every page here is a single stage and the cap applies.
    if info["duration_s"] > STAGE_MAX_S:
        raise ValueError("trican-B: implausible stage duration "
                         f"{info['duration_s']}s")
    _attach_geom(page, im, img, info)
    meta = page_meta_b(page)
    if info.get("conc_derived"):
        channels = _check_derived_conc(channels, meta, info)
    return meta, samples, channels, info


def _check_derived_conc(channels, meta, info):
    """Believe the borrowed conc axis only if the page's own numbers agree.

    The scale came from the rate axis rather than from ticks of its own, so it
    is a derivation and has to answer to something. The page prints its own
    "Conc Average .. Maximum .. kg/m³" for the stage, and that is the check:
    the traced maximum has to land on the printed one.

    Refused rather than shipped when it does not. A concentration on a
    borrowed scale that disagrees with the sheet is a plausible wrong number,
    and those are the ones that reach a CSV and get believed.
    """
    printed = (meta.get("printed") or {}).get("conc_max")
    conc = [c for c in channels if c.get("key") in ("wh_conc", "dh_conc")]
    if not conc:
        return channels
    if not printed:
        info["notes"].append(
            "Prop Conc: axis read from the rate axis, and this page prints no "
            "Conc Maximum to check it against")
        return [c for c in channels if c not in conc]
    best, hit = None, False
    for c in conc:
        v = np.asarray(c["values"], float)
        v = v[np.isfinite(v)]
        if not v.size:
            continue
        peak = float(v.max())
        if best is None or abs(peak - printed) < abs(best - printed):
            best = peak
        if abs(peak - printed) <= CONC_CHECK_TOL * max(1.0, printed):
            hit = True
    if hit:
        info["notes"].append(
            f"Prop Conc: no ticks on the concentration axis, so it is read "
            f"from the rate axis x{CONC_PER_RATE:g} — the same scale layout A "
            f"uses. Checked against this page's printed Conc Maximum "
            f"{printed:g} kg/m3 (traced {best:.1f}).")
        return channels
    info["notes"].append(
        f"Prop Conc: axis read from the rate axis x{CONC_PER_RATE:g} did not "
        f"agree with the page's printed Conc Maximum {printed:g} kg/m3 "
        f"(traced {best if best is None else round(best, 1)}) — dropped rather "
        f"than exported on a scale that does not hold")
    return [c for c in channels if c not in conc]
