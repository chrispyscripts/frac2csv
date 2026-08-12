"""Frac2CSV auto-calibrating raster mode.

Extracts time-series curves from scanned/unknown-template chart images with
no manual configuration, when the chart follows the common industry layout:
a rectangular plot area, colored series curves, color-matched numeric tick
columns left of the plot, and time labels (HH:MM:SS or minutes) underneath.

Requires the tesseract OCR binary. Techniques (validated on scanned PSC
charts, 74% page yield): frame from long dark-line runs, tick numbers
assigned to series by pixel color, RANSAC calibration that tolerates heavy
OCR noise, midnight-unwrapped time axis.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import difflib
import math
import numpy as np

import curve_trace as ct

HUE_NAMES = ["red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta"]
# how far a faint pixel must stay clear of crimson ink to count as orange —
# see hue_masks
HALO_PX = 3
HUE_HEX = {"red": "#c8372d", "orange": "#d07a1f", "yellow": "#a89a17",
           "green": "#1e7a34", "cyan": "#118a8a", "blue": "#1d5bd8",
           "purple": "#6d3bb0", "magenta": "#b0329b"}

# How much taller than the pen a column's ink must be before it is read as a
# SWEPT column — one where the curve moved through a range inside that column —
# and reported at the end of the run rather than its middle. See
# curve_positions. Lower keeps more detail; the reducer never invents a value,
# because both ends of a run are ink the page actually printed, so the cost of
# lowering it is only that a heavy flat line reports alternate edges of its own
# pen. The client's instruction is explicit: less smooth the better.
SWEPT_FACTOR = 1.4


def tesseract_path():
    """Locate tesseract: bundled (PyInstaller) first, then PATH."""
    if getattr(sys, "_MEIPASS", None):
        cand = os.path.join(sys._MEIPASS, "tesseract", "tesseract.exe")
        if os.path.exists(cand):
            return cand
    return shutil.which("tesseract")


def _tess_env(binpath):
    env = os.environ.copy()
    d = os.path.join(os.path.dirname(binpath), "tessdata")
    if os.path.isdir(d):
        env["TESSDATA_PREFIX"] = d
    return env


def available():
    return tesseract_path() is not None


# ---------- color discovery ----------

def _grow(mask, k):
    """Spread a boolean mask k pixels in every direction."""
    out = mask
    for _ in range(k):
        o = out.copy()
        o[1:] |= out[:-1]
        o[:-1] |= out[1:]
        o[:, 1:] |= out[:, :-1]
        o[:, :-1] |= out[:, 1:]
        out = o
    return out


def _faint_orange(r, g, b, sat, s_min, red):
    """Orange ink too faint for the absolute red/orange margin to see.

    hue_masks splits warm ink on `g > b + m3`, an ABSOLUTE margin, and printed
    ink fades. On 01396 p292 (STEP, Btm Prop Conc) a third of the trace runs at
    saturation 30-60, where genuine orange pixels — (205,174,146), (194,159,132),
    (167,118,92) — carry g only 27-28 above b, land under m3 = 31.5 and are
    filed as RED. Over that file's 112 charts the channel's ink covered a median
    52% of the plot columns, against 93% for the green Prop Conc beside it.

    The hue itself does not fade; only its amplitude does. Blending ink toward
    white scales (g-b) and (r-b) by the same factor, so their RATIO is what
    survives: measured on that page, orange holds (g-b)/(r-b) at 0.46-0.68 in
    every saturation band while crimson sits at -0.45..+0.06. A 0.30 cut
    separates them at any strength, where a fixed 31.5 only works while the ink
    is strong. The upper bound keeps yellow-ish ink (g approaching r) out, which
    is what the r > g + m1 term used to do.

    The ratio alone is not enough. A crimson stroke on a JPEG-compressed scan
    is fringed with tan — (255,229,214) sits one pixel from (228,29,41) — which
    reads as orange by hue and by ratio. One such pixel in a column with no
    other ink would put a Btm Prop Conc reading on the Treating Pressure trace,
    which is worse than the gap it fills, so faint ink within HALO_PX of crimson
    is not eligible. Measured on 16 charts of 01396: without that guard 292
    recovered columns land on the pressure trace, with it 5.

    The result is ADDED to "orange" and NOT removed from "red". hal1 splits
    crimson from chocolate inside the red family itself (b >= g for Treating
    Pressure, g > b + 15 for Slurry Prop Conc); moving the chocolate out would
    empty Halliburton's concentration channel. Red is left bit-for-bit as it
    was and the two families simply overlap in the faint band.
    """
    gb = g - b
    rb = r - b
    # b <= g < r, so rb is this pixel's saturation and gb its position along
    # the ramp from blue to red — the hue, expressed without a division.
    warm = (sat > s_min) & (r > g) & (g >= b)
    hue = warm & (gb * 100 > 30 * rb) & (gb * 100 < 78 * rb)
    crimson = red & (gb * 100 <= 30 * rb)
    return hue & ~_grow(crimson, HALO_PX)


def hue_masks(img):
    """Series colors as broad families. Scans smear hue badly (a series'
    digits and curve can sit 60 deg apart), so tight clustering separates a
    series from its own tick numbers; broad channel-dominance rules keep
    them together. Validated on scanned PSC charts.

    The cut-offs adapt to how saturated the page actually is. They were fixed
    at sat>60 with 40-point channel margins, which suits a vivid scan but not
    a faded one: on 00273 the tick ink peaks at saturation 66 and averages 30,
    so 3 pixels out of 1736 qualified, no family was found, no ticks were
    assigned to any series, and the file reported no extractable data. The
    reference page (00183) sits at saturation 255 and is unaffected.
    """
    r = img[..., 0].astype(int); g = img[..., 1].astype(int); b = img[..., 2].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = mx - mn
    # how colourful is the ink on this page? measure only non-white pixels, so
    # the white background does not drag the estimate down
    ink = (r + g + b) < 600
    strength = float(np.percentile(sat[ink], 90)) if ink.any() else 255.0
    k = min(1.0, max(0.28, strength / 255.0))
    s_min = max(16.0, 60.0 * k)          # saturation floor
    m1 = max(12.0, 40.0 * k)             # dominant-channel margin
    m2 = max(14.0, 45.0 * k)
    m3 = max(16.0, 60.0 * k)
    m4 = max(10.0, 35.0 * k)             # cyan's green/blue closeness
    m5 = max(9.0, 30.0 * k)
    m6 = max(6.0, 20.0 * k)
    # rules validated on scanned/rendered charts; red vs orange split on the
    # green channel (orange carries mid green, true red does not)
    families = {
        "red":     (sat > s_min) & (r > g + m1) & (r > b + m1) & (g < b + m3),
        "orange":  (sat > s_min) & (r > g + m1) & (r > b + m2) & (g > b + m3),
        "green":   (sat > s_min * 0.83) & (g > r + m5) & (g > b + m6),
        "magenta": (sat > s_min) & (r > g + m1) & (b > g + m1),
        "blue":    (sat > s_min) & (b > g + m1) & (b > r + m1),
        "cyan":    (sat > s_min) & (g > r + m1) & (b > r + m1) & (np.abs(g - b) < m4),
    }
    families["green"] = families["green"] & ~families["cyan"]
    min_px = max(400, img.shape[0] * img.shape[1] // 5000)
    # The faint pass only COMPLETES an orange series this page already shows;
    # it never introduces one, and it may not become most of one. STEP's
    # chemical chart draws its additives in a tan the faint rule reads as
    # orange — 01396 p340 "Secure BIO 108 (L/m3)" at 0.09 — and step1 maps
    # orange to Btm Prop Conc, so an additive trace would ship as a proppant
    # concentration in kg/m3. Two conditions keep the recovery on the curves it
    # was measured on: the strict rule must already have found a family here,
    # and the recovery may not add more than 1.5x the ink that family holds.
    # Across the 182 STEP surface charts of six files the faint pass takes
    # orange to 1.01-2.46x its original size; on the five chemical charts that
    # carry any orange at all it takes it to 2.97-7.30x, because there it is
    # drawing a curve rather than filling the gaps in one.
    base_px = int(families["orange"].sum())
    if base_px >= min_px:
        add = (_faint_orange(r, g, b, sat, s_min, families["red"])
               & ~families["orange"])
        if int(add.sum()) <= 1.5 * base_px:
            families["orange"] = families["orange"] | add
    return {k2: m for k2, m in families.items() if m.sum() >= min_px}


# ---------- geometry ----------

def _max_run(v):
    best = cur = 0
    for x in v:
        cur = cur + 1 if x else 0
        if cur > best:
            best = cur
    return best


def find_plot_area(img, masks):
    H, W, _ = img.shape
    dark = img.sum(axis=2) < 430
    any_series = np.zeros((H, W), bool)
    for m in masks.values():
        any_series |= m
    ys, xs = np.where(any_series)
    if len(xs) < 500:
        raise ValueError("no series curves found")
    x_med, y_med = int(np.median(xs)), int(np.median(ys))
    v_lines = [x for x in range(W)
               if dark[:, x].sum() > 0.3 * H and _max_run(dark[:, x]) > 0.25 * H]
    h_lines = [y for y in range(H)
               if dark[y, :].sum() > 0.3 * W and _max_run(dark[y, :]) > 0.25 * W]
    left = [x for x in v_lines if x < x_med - 200]
    right = [x for x in v_lines if x > x_med + 200]
    top = [y for y in h_lines if y < y_med - 150]
    sx0, sx1 = np.percentile(xs, [1, 99.5]).astype(int)
    sy0, sy1 = np.percentile(ys, [1, 99.5]).astype(int)
    x0 = max(left) if left else sx0
    x1 = min(right) if right else sx1
    y0 = max(top) if top else sy0
    y1 = None
    for y in range(y_med + 150, H - 40):
        row = dark[y, x0:x1]
        if row.mean() > 0.10 and _max_run(row) < 100:
            y1 = y - 6
            break
    if y1 is None:
        bot = [y for y in h_lines if y > y_med + 150]
        y1 = min(bot) if bot else sy1
    if x1 - x0 < 400 or y1 - y0 < 250:
        raise ValueError("no plausible plot frame")
    return int(x0), int(y0), int(x1), int(y1)


# ---------- OCR ----------

def ocr_words(img_arr, psm=6, whitelist="0123456789:.-"):
    binpath = tesseract_path()
    if binpath is None:
        return []
    from PIL import Image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        Image.fromarray(img_arr.astype(np.uint8)).save(f.name)
        path = f.name
    try:
        out = subprocess.run(
            [binpath, path, "stdout", "--psm", str(psm), "-c",
             f"tessedit_char_whitelist={whitelist}", "tsv"],
            capture_output=True, text=True, timeout=120,
            # Tesseract writes UTF-8. Without saying so, Python decodes with
            # the locale codepage (cp1252 on a Canadian Windows box) and a
            # single stray byte raises UnicodeDecodeError inside the worker
            # thread, losing the whole page silently.
            encoding="utf-8", errors="replace",
            env=_tess_env(binpath)).stdout
    finally:
        os.unlink(path)
    words = []
    for line in out.splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 12 and p[11].strip():
            try:
                x, y, w, h = int(p[6]), int(p[7]), int(p[8]), int(p[9])
            except ValueError:
                continue
            words.append((p[11].strip(), x + w / 2, y + h / 2))
    return words


def fit_ticks(pts, min_inliers=5):
    """RANSAC linear fit value = a + b*coord; tolerates heavy OCR junk."""
    if len(pts) < 4:
        return None
    vals = np.array([p[0] for p in pts], float)
    coords = np.array([p[1] for p in pts], float)
    n = len(pts)
    best = (0, None)
    for i in range(n):
        for j in range(i + 1, n):
            dc = coords[j] - coords[i]
            if abs(dc) < 60 or vals[i] == vals[j]:
                continue
            b = (vals[j] - vals[i]) / dc
            a = vals[i] - b * coords[i]
            tol = max(abs(b) * 20, (vals.max() - vals.min()) * 0.015 + 1e-9)
            inl = np.abs(a + b * coords - vals) < tol
            if inl.sum() > best[0]:
                best = (int(inl.sum()), inl)
    if best[1] is None or best[0] < min_inliers:
        return None
    inl = best[1]
    A = np.vstack([np.ones(inl.sum()), coords[inl]]).T
    (a, b), *_ = np.linalg.lstsq(A, vals[inl], rcond=None)
    if abs(b) < 1e-12:
        return None
    return (float(a), float(b), int(inl.sum()))


def ocr_tick_strip(img, masks, xa, xb, out=None):
    """OCR a vertical tick-label strip; assign numbers to series by color."""
    from PIL import Image
    xa = max(0, xa)
    strip = img[:, xa:xb]
    if out is None:
        out = {k: [] for k in masks}
    if strip.size == 0:
        return out
    SCALE = 3
    pil = Image.fromarray(strip.astype(np.uint8))
    pil = pil.resize((pil.width * SCALE, pil.height * SCALE), Image.LANCZOS)
    words = ocr_words(np.array(pil).astype(int), psm=6, whitelist="0123456789.-")
    for text, cx, cy in words:
        t = text.replace(",", "").strip("-.")
        if not re.fullmatch(r"\d+(\.\d+)?", t):
            continue
        px, py = int(cx / SCALE) + xa, int(cy / SCALE)
        y0, y1 = max(0, py - 12), py + 13
        x0, x1 = max(0, px - 40), px + 41
        counts = {k: int(m[y0:y1, x0:x1].sum()) for k, m in masks.items()}
        bestk = max(counts, key=counts.get)
        if counts[bestk] > 30:
            out[bestk].append((float(t), py, True))
            # ambiguous color (scan fringe): runner-up gets a borrowed vote
            for k, c in counts.items():
                if k != bestk and c > 30 and c >= 0.4 * counts[bestk]:
                    out[k].append((float(t), py, False))
    return out


def ocr_left_ticks(img, masks, x_hi):
    return ocr_tick_strip(img, masks, 0, x_hi)


def snap_axis(top, bot, tick_vals=None, tol_frac=0.03):
    """Pull fitted frame-edge values onto round numbers.

    Scanned charts print round axis bounds sitting on the frame edges. The fit
    is built from OCR'd label centroids, which sit a little off their tick, so
    it lands near-but-not-on those bounds — measured 0.6-2.0% against a page
    read by eye, an error that otherwise rides into the exported values.

    Deliberately does NOT use the tick values to infer a step: that strip
    carries junk (a dropped decimal turns "12.00" into 1200, and a neighbouring
    scale bleeds in), which made a true step of 12 estimate as 36. The span
    alone gives a reliable unit, and a bound is only moved when it is already
    within `tol_frac` of a round multiple.

    -> (top, bot, snapped_bool)
    """
    span = abs(top - bot)
    if not np.isfinite(span) or span <= 0:
        return top, bot, False
    base = 10.0 ** math.floor(math.log10(span))
    tol = tol_frac * span
    # Coarsest grid first, so a 0..60 axis snaps on tens rather than being
    # dragged onto a finer multiple. Axis bounds are not always a power of ten
    # — STEP prints rate as 0..16 — so step down to halves, fifths and tenths
    # before giving up. Both bounds must fit the SAME grid or the axis is left
    # alone; snapping one end only would skew the scale.
    for mult in (1.0, 0.5, 0.2, 0.1):
        unit = base * mult
        t2 = round(top / unit) * unit
        b2 = round(bot / unit) * unit
        if abs(top - t2) <= tol and abs(bot - b2) <= tol and t2 != b2:
            return t2, b2, (t2 != top or b2 != bot)
    return top, bot, False


def ocr_line(img_arr, psm=7):
    """OCR a small crop as plain text (letters allowed, unlike ocr_words)."""
    binpath = tesseract_path()
    if binpath is None:
        return ""
    from PIL import Image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        Image.fromarray(img_arr.astype(np.uint8)).save(f.name)
        path = f.name
    try:
        out = subprocess.run(
            [binpath, path, "stdout", "--psm", str(psm)],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
            env=_tess_env(binpath)).stdout
    except Exception:
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return " ".join(out.split())


_LEGEND_UNITS = ["m3/min", "kg/m3", "L/m3", "MPa", "kPa", "m3", "kg"]


def _legend_unit(raw):
    """OCR'd unit text -> a known unit, or ''. Scans mangle the superscript
    and the slash badly ('kg/m*}', '(Lim3)'), so match loosely."""
    if not raw:
        return ""
    u = raw.strip(" ()[]{}")
    u = (u.replace("*", "3").replace("^", "3").replace("\u00b3", "3")
          .replace("\u2019", "").replace("|", "/"))
    u = re.sub(r"[^A-Za-z0-9/]", "", u)
    if not u:
        return ""
    low = u.lower().replace("lim", "l/m")      # '(L/m3)' often reads '(Lim3)'
    best = difflib.get_close_matches(
        low, [x.lower() for x in _LEGEND_UNITS], n=1, cutoff=0.62)
    if not best:
        return ""
    return _LEGEND_UNITS[[x.lower() for x in _LEGEND_UNITS].index(best[0])]


def _legend_name(raw):
    """Strip the rule sample, the trailing unit and OCR speckle."""
    s = re.sub(r"[\u2014\u2013_=~]+", " ", raw)
    s = re.sub(r"\([^)]*\)|\{[^}]*\}|\[[^\]]*\]", " ", s)
    s = re.sub(r"[^A-Za-z0-9 .\-/+]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-/")
    toks = [t for t in s.split()
            if re.search(r"[A-Za-z]{2}", t) or re.fullmatch(r"[\d.\-]{2,}", t)]
    return " ".join(toks).strip()


def _col_groups(mask, gap=40, min_w=55):
    """Column runs of a mask, merged across small gaps -> [(x0, x1)].
    The legend prints two columns; one bounding box over both would feed
    tesseract two unrelated labels as a single line."""
    cols = np.where(mask.any(axis=0))[0]
    if len(cols) == 0:
        return []
    groups, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > gap:
            groups.append((start, prev))
            start = c
        prev = c
    groups.append((start, prev))
    return [(a, b) for a, b in groups if b - a >= min_w]


def _col_groups(mask, gap=45, min_w=55):
    """Column runs of a mask, merged across small gaps -> [(x0, x1)].
    The legend prints two columns; one bounding box over both would hand
    tesseract two unrelated labels as a single line."""
    cols = np.where(mask.any(axis=0))[0]
    if len(cols) == 0:
        return []
    groups, a, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > gap:
            groups.append((a, prev))
            a = c
        prev = c
    groups.append((a, prev))
    return [(x, y) for x, y in groups if y - x >= min_w]


# What a legend entry is allowed to be called. A scanned legend OCRs roughly
# ("Aqucar" -> "Aaqucar", "Conc" -> "Cone"), so a raw read is not trustworthy
# enough to name a column in a deliverable. Only a confident match against
# this vocabulary is accepted; anything else leaves the caller's own naming
# alone, so a bad read can never rename a channel to something wrong.
LEGEND_VOCAB = [
    "Surface Pressure", "Surface BU", "Treating Pressure", "Hydr Pressure",
    "Slurry Rate", "Combined Slurry Rate", "Combined Clean Rate", "Clean Rate",
    "Prop Conc", "Btm Prop Conc", "Bottom Prop Conc",
    "Surf Total Proppant Conc", "Total Proppant Conc",
]


def match_legend_name(raw, cutoff=0.78):
    """OCR'd legend text -> a canonical name from LEGEND_VOCAB, or ''."""
    if not raw or len(raw) < 4:
        return ""
    key = re.sub(r"[^a-z ]", " ", raw.lower())
    key = re.sub(r"\s+", " ", key).strip()
    if not key:
        return ""
    best, score = "", 0.0
    for cand in LEGEND_VOCAB:
        r = difflib.SequenceMatcher(None, key, cand.lower()).ratio()
        if r > score:
            best, score = cand, r
    return best if score >= cutoff else ""


# Names that cannot legitimately appear on a chemical-analysis chart. Used to
# reject a legend that names the wrong thing — see read_chart_title.
TREATMENT_ONLY = {
    "Surface Pressure", "Surface BU", "Treating Pressure", "Hydr Pressure",
    "Prop Conc", "Btm Prop Conc", "Bottom Prop Conc",
    "Surf Total Proppant Conc", "Total Proppant Conc",
}


def read_chart_title(img, box):
    """The chart's own title line ('... Treatment Analysis' / '... Chemical
    Analysis'), lowercased.

    Large dark text on a plain bar, so it OCRs far more reliably than the
    coloured legend — reliable enough to decide what KIND of chart this is,
    which position-in-page cannot: a page's second chart is not always the
    chemical one.
    """
    x0, y0, x1, y1 = box
    band = int(min(130, max(35, (y1 - y0) * 0.10)))
    t0 = max(0, y0 - band - 95)
    t1 = max(t0 + 1, y0 - band)
    if t1 - t0 < 12:
        return ""
    strip = img[t0:t1, x0:x1]
    try:
        grey = np.asarray(strip).sum(axis=2) / 3.0
    except Exception:
        return ""
    canvas = np.where(grey < 150, 0, 255).astype(np.uint8)   # dark text only
    from PIL import Image
    pil = Image.fromarray(canvas)
    pil = pil.resize((pil.width * 3, pil.height * 3), Image.LANCZOS)
    return ocr_line(np.array(pil), psm=6).lower()


def read_legend(img, box):
    """{colour family: (name, unit)} read off the legend above the plot.

    The colour -> series mapping is NOT fixed, so it cannot be hardcoded: in
    one PSC report Surface Pressure is red on the first chart and cyan on the
    second, where Slurry Rate is magenta — and that second chart is a
    treatment chart sitting where the chemical one usually goes. The legend is
    the only place the pairing is actually stated.

    Names are returned only when they match LEGEND_VOCAB confidently, so a
    poor scan degrades to "no opinion" rather than to a wrong label.
    """
    x0, y0, x1, y1 = box
    band = int(min(130, max(35, (y1 - y0) * 0.10)))
    top = max(0, y0 - band)
    if y0 - 3 - top < 12:
        return {}
    strip = img[top:y0 - 3, x0:x1]
    try:
        masks = hue_masks(strip)
    except Exception:
        return {}
    from PIL import Image
    out = {}
    for key, m in masks.items():
        best = None
        for gx0, gx1 in _col_groups(m):
            sub = m[:, gx0:gx1 + 1]
            rows = np.where(sub.any(axis=1))[0]
            if len(rows) < 4:
                continue
            crop = sub[rows.min():rows.max() + 1]
            canvas = np.where(crop, 0, 255).astype(np.uint8)
            pil = Image.fromarray(canvas)
            # LANCZOS on the binary mask restores anti-aliased edges, which
            # tesseract reads far better than hard pixel steps
            pil = pil.resize((pil.width * 6, pil.height * 6), Image.LANCZOS)
            raw = ocr_line(np.array(pil), psm=7)
            name = match_legend_name(_legend_name(raw))
            if not name:
                continue
            mu = re.search(r"[\(\{\[]([^\)\}\]]*)[\)\}\]]\s*$", raw)
            unit = _legend_unit(mu.group(1) if mu else "")
            score = len(name)
            if best is None or score > best[2]:
                best = (name, unit, score)
        if best:
            out[key] = (best[0], best[1])
    return out


# A rotated value-axis title names the QUANTITY it measures. Only these three
# appear on a frac chart's value axes, and each maps to one unit family, which
# is what lets a colour be matched to an axis.
# "cone" is not a typo: tesseract reads the axis title "Chem Conc (L/m3)" as
# "Chem Cone (Uim\")" on every one of these pages, and "cone" scores 0.75
# against "conc" — just under the cutoff that keeps "rate"/"pressure" honest.
_AXIS_QTY = {"pressure": "pressure", "rate": "rate",
             "concentration": "conc", "conc": "conc", "cone": "conc"}


def axis_qty(word):
    """One word of a rotated axis title -> 'pressure' | 'rate' | 'conc' | ''."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if len(w) < 4:
        return ""
    best, score = "", 0.0
    for cand, qty in _AXIS_QTY.items():
        r = difflib.SequenceMatcher(None, w, cand).ratio()
        if r > score:
            best, score = qty, r
    return best if score >= 0.8 else ""


def read_axis_titles(img, xa, xb, ccw=True, merge=25):
    """Rotated value-axis titles in a vertical strip -> [(qty, x)] by x.

    Charts that stack several value axes on one side print, for each axis, a
    column of tick numbers and then — on the far side of them, away from the
    plot — that axis's own rotated title. Position alone cannot say which
    column measures what: STEP's new-format surface chart prints Concentration
    as the INNER right column and Rate as the OUTER one, the opposite of the
    order the code assumed. The title says it outright, and because it sits
    just outside its own numbers it also delimits that column from the next.

    `ccw` rotates the strip counter-clockwise (right-hand axes, which read
    bottom-to-top); clockwise suits a left-hand axis.
    """
    from PIL import Image
    xa = max(0, xa)
    strip = img[:, xa:xb]
    if strip.size == 0:
        return []
    wc = strip.shape[1]
    pil = Image.fromarray(strip.astype(np.uint8)).rotate(90 if ccw else -90,
                                                         expand=True)
    scale = 3
    pil = pil.resize((pil.width * scale, pil.height * scale), Image.LANCZOS)
    hits = []
    for text, _cx, cy in ocr_words(np.array(pil).astype(int), psm=6,
                                   whitelist=""):
        qty = axis_qty(text)
        if not qty:
            continue
        c = int(cy / scale)
        hits.append((qty, (wc - 1 - c if ccw else c) + xa))
    hits.sort(key=lambda t: t[1])
    # a title is several words on one line ("Chem Conc (L/m3)") and OCRs as
    # separate boxes a few pixels apart — collapse them into one axis
    out = []
    for qty, x in hits:
        if out and abs(x - out[-1][1]) <= merge:
            continue
        out.append((qty, x))
    return out


def plausible_pressure_axis(v0, v1):
    """Could (v0, v1) be the two ends of a treating-pressure axis?

    A miscalibrated pressure channel is the worst thing this tool can export:
    a dropped channel is visible, "0.19 MPa" is not. Two shapes of axis are
    flatly impossible and both were being exported —

      - a span under 5 units. A frac chart's pressure axis is drawn 0..40 at
        the very least; a [0.0, 2.0] axis is a chemical concentration scale
        that got mistaken for one.
      - a floor well below zero. [-60, 90] exported -51 MPa. The small
        negative that a fit on OCR'd label centroids leaves behind (00183
        reads -1.18 on a 0..80 axis) is fine and is judged against the span,
        not against zero.
    """
    lo, hi = min(float(v0), float(v1)), max(float(v0), float(v1))
    span = hi - lo
    if not np.isfinite(span) or span < 5:
        return False
    return lo >= -0.05 * span


def plausible_floor_axis(v0, v1):
    """Could (v0, v1) be the two ends of an axis for a quantity that cannot
    go below zero — a concentration or a pump rate?

    Same reasoning as plausible_pressure_axis, minus the span test: a
    chemical axis really is drawn 0..2, so only the floor can be judged.
    Nothing pumped downhole has a negative concentration or a negative
    rate, so an axis whose bottom end sits well under zero has been fitted
    to the wrong ticks — 00269 p70 reads Btm Prop Conc off an (800, -150)
    axis and exports -147 kg/m3. The small negative a fit on OCR'd label
    centroids leaves behind is fine and is judged against the span.
    """
    lo, hi = min(float(v0), float(v1)), max(float(v0), float(v1))
    span = hi - lo
    if not np.isfinite(span) or span <= 0:
        return False
    return lo >= -0.05 * span


def fit_ticks_guarded(pts):
    """Fit on a family's own (strict) ticks; borrowed votes only rescue a
    fit when the family has real ticks of its own, so one series' axis
    can't masquerade as another's."""
    strict = [(v, y) for v, y, s in pts if s]
    fit = fit_ticks(strict, min_inliers=max(4, len(strict) // 2))
    if fit:
        return fit
    if len(strict) >= 4:
        # OCR drops decimal points ("7.500" -> 7500): shrink magnitude
        # outliers by powers of ten; a wrong repair still fails RANSAC
        repaired = []
        for i, (v, y) in enumerate(strict):
            others = [abs(w) for j, (w, _) in enumerate(strict) if j != i]
            m = float(np.median(others)) if others else 0
            m = m or 1
            if abs(v) > 3 * m:
                good = [c for c in (v / 10, v / 100, v / 1000)
                        if abs(c) <= 3 * m]
                if good:
                    v = max(good, key=abs)
            repaired.append((v, y))
        fit = fit_ticks(repaired, min_inliers=max(4, len(repaired) // 2))
        if fit:
            return fit
    if len(strict) >= 2:
        fit = fit_ticks([(v, y) for v, y, _ in pts])
        if fit:
            a, b, _ = fit
            vals = np.array([v for v, _ in strict])
            ys = np.array([y for _, y in strict])
            tol = max(abs(b) * 20, (vals.max() - vals.min()) * 0.02 + 1e-9)
            # a borrowed fit must still explain this family's own ticks,
            # else it's another series' axis wearing the wrong color
            need = 3 if len(strict) >= 3 else len(strict)
            if (np.abs(a + b * ys - vals) < tol).sum() >= need:
                return fit
    return None


def _label_band(strip):
    """The first row band of text under the plot -> that band's rows, or None.

    The time labels are always the first thing under the axis, so the first
    band of ink is them and nothing else — see time_calibration for why that
    matters. A sparse leading band is a row of tick marks rather than text and
    is skipped.
    """
    w = strip.shape[1]
    ink = (strip.sum(axis=2) < 400).sum(axis=1)
    # a row that is dark right across is the frame rule, not a line of text —
    # the window starts one pixel under the axis (see time_calibration) and on
    # a thick scan that pixel is still the rule
    on = (ink > max(2, w * 0.004)) & (ink < 0.5 * w)
    bands, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            bands.append((start, i)); start = None
    if start is not None:
        bands.append((start, len(on)))
    for b0, b1 in bands:
        if b1 - b0 >= 3 and ink[b0:b1].max() > w * 0.02:
            return max(0, b0 - 3), min(len(on), b1 + 3)
    return None


def time_calibration(img, x0, x1, y1):
    """OCR time labels under the plot. HH:MM:SS or plain minutes."""
    H, W, _ = img.shape
    xa, xb = max(0, x0 - 60), min(W, x1 + 60)
    hi = min(y1 + 95, H)
    # Two candidate windows, tried in order.
    #
    # First, just the row band the labels occupy, measured from ONE pixel under
    # the axis rather than five. Both parts matter at the 880x680 render that
    # 01396 files some of its pages at: five pixels take the tops off every
    # digit ("08:05" OCRs as ":0"), and the fixed 90px window — sized for the
    # ~920px-tall render — reaches past the labels into the LEGEND, whose long
    # entries bridge the gaps between them so the column clustering returns one
    # 900px blob. Stages 25 and 26 had no time axis at all because of it.
    #
    # Then the original window, unchanged, so any page that already read
    # cleanly reads exactly the same way. A candidate only counts if it
    # survives the duration test every caller applies (120s..100000s): on
    # 00269 p43/45/73 the band crop fits a 55-second treatment, which is not a
    # reading, and returning it hid the fit those pages have always had.
    tight = img[min(y1 + 1, H - 1):hi, xa:xb]
    band = _label_band(tight) if tight.size else None
    cands = ([tight[band[0]:band[1]]] if band else []) + \
            [img[min(y1 + 5, H - 1):hi, xa:xb]]
    for strip in cands:
        got = _time_fit(strip, xa, x0, x1)
        if got and 120 < got[1] * (x1 - x0) < 100000:
            return got
    return None


def _time_fit(strip, xa, x0, x1):
    """One candidate label strip -> (t0, seconds-per-pixel), or None."""
    if strip.size == 0:
        return None
    # small renders leave labels below OCR size: upscale 3x
    from PIL import Image as _Im
    _pil = _Im.fromarray(strip.astype(np.uint8))
    _pil = _pil.resize((_pil.width * 3, _pil.height * 3), _Im.LANCZOS)
    strip = np.array(_pil).astype(int)
    dark = strip.sum(axis=2) < 400
    # drop gridline/frame rows so labels don't weld into one cluster
    line_rows = dark.mean(axis=1) > 0.5
    dark[line_rows, :] = False
    colhit = dark.any(axis=0)
    clusters, start, gap = [], None, 0
    for i, v in enumerate(colhit):
        if v:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 30:
                clusters.append((start, i - gap)); start = None
    if start is not None:
        clusters.append((start, len(colhit) - 1))
    pts_hms, pts_mms, pts_num = [], [], []
    for c0, c1 in clusters:
        if c1 - c0 < 40:
            continue
        crop = strip[:, max(0, c0 - 8):c1 + 9]
        for text, _, _ in ocr_words(crop, psm=7, whitelist="0123456789:."):
            cx = (c0 + c1) / 6.0 + xa   # cluster coords are in 3x space
            m = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})", text)
            if m:
                pts_hms.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60
                                + int(m.group(3)), cx))
                break
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
            if m:
                pts_mms.append((int(m.group(1)) * 60 + int(m.group(2)), cx))
                break
            m = re.fullmatch(r"(\d{2})(\d{2}):(\d{2})", text)
            if m:   # "DD HH:MM" with the space lost in OCR
                pts_hms.append((int(m.group(1)) * 86400
                                + int(m.group(2)) * 3600
                                + int(m.group(3)) * 60, cx))
                break
            t = text.strip(".")
            if re.fullmatch(r"\d+(\.\d+)?", t):
                pts_num.append((float(t) * 60, cx))   # assume minutes
                break
    # strict HH:MM:SS wins; other formats only when it's absent (mixing
    # truncated misreads across formats poisons the fit)
    for pts in (pts_hms, pts_mms, pts_num):
        if len(pts) < 4:
            continue
        vals = np.array([p[0] for p in pts], float)
        coords = np.array([p[1] for p in pts], float)
        order = np.argsort(coords)
        vals, coords = vals[order], coords[order]
        if pts is pts_hms:
            for i in range(1, len(vals)):             # unwrap midnight
                if vals[i] < vals[i - 1] - 20000:
                    vals[i:] += 86400
        fit = fit_ticks(list(zip(vals, coords)),
                        min_inliers=max(4, int(len(vals) * 0.5)))
        if pts is pts_mms:
            # "A:B" is ambiguous: MM:SS or HH:MM. Prefer the reading whose
            # plot-wide duration is plausible for a treatment.
            dur = fit[1] * (x1 - x0) if fit else 0
            if not (600 <= dur <= 100000):
                v2 = vals * 60
                for i in range(1, len(v2)):           # unwrap midnight
                    if v2[i] < v2[i - 1] - 20000:
                        v2[i:] += 86400
                fit2 = fit_ticks(list(zip(v2, coords)),
                                 min_inliers=max(4, int(len(v2) * 0.5)))
                if fit2 and 600 <= fit2[1] * (x1 - x0) <= 100000:
                    fit = fit2
        if fit and fit[1] > 0:
            return fit[0], fit[1]
    return None


# ---------- printed graphics inside the plot ----------

# A chart's plot area is not always curves and gridlines. FracPro prints its
# own logo INSIDE the frame — on STEP's tiled reports it lands in the top 6% of
# the plot, and its lettering is drawn in the same inks the series use:
# 00184 p37 carries 2,048 red pixels (the "PRO"), 2,421 cyan ("FRAC") and 366
# green (the swoosh) between rows 12 and 43 of a 672-row plot. Orange is the
# one series colour absent from the logo, and orange was the one channel on
# that page the client did not report as wrong.
#
# It defeats curve_positions outright. That routine keeps the run nearest a
# rolling median of the trace, which is the right rule for a second blob a few
# columns wide — but this blob spans 400 columns against a 70-column window, so
# the median itself moves into the logo and then every run near it looks
# correct. Measured on 00184 stage 17: Tr Press exported 78.51 MPa against
# 58.34 filed with the regulator, Prop Conc 965 kg/m3 on a 0..1000 axis, and
# Combined Clean Rate 15.69 on a 0..16 axis — three channels reading ~98% of
# full scale because the logo sits just under the frame's top edge.
#
# Shape tells the two apart, and position does not. Components, measured on
# that page:
#
#   curve       w 55-99.6% of the plot, fill 0.013-0.016
#   logo glyph  w 2.3-7.0%,             fill 0.185-0.600
#
# A pen stroke fills ~1.5% of its own bounding box; a letter fills a third of
# it. But DENSITY ALONE IS NOT ENOUGH, and this is the trap: a genuine
# near-vertical move is also narrow and solid — the end-of-job pressure drop on
# that same page is 6 columns wide with fill 0.361, and the client asked
# explicitly for those spikes to survive (see the reducer in curve_positions).
# What separates them is that a spike belongs to its curve and a logo does not:
# the drop's rows meet the trace's rows where they share columns, while the
# logo sits ~180 rows clear of the pressure curve beneath it. So density only
# nominates a candidate; distance from the trace convicts it.
#
# A curve that runs THROUGH the logo merges with it into one wide component and
# is left alone — no test fires, and the contamination survives on that page.
# That is deliberate: splitting a merged component means guessing where the
# curve goes under the ink, and inventing it is worse than reporting it.
GLYPH_WIDTH = 0.12       # of plot width: wider than this is a curve, not a mark
GLYPH_FILL = 0.15        # lit / bounding box; curves measured <= 0.094
GLYPH_NEAR = 0.05        # of plot height: how close to the trace still belongs
GLYPH_PAD = 0.03         # of plot width: how far to look sideways for the trace


def _components(sub):
    """8-connected components of a boolean mask -> [(cols, rows, count)].

    numpy has no labeller and scipy is not a dependency of this project, but
    the ink is sparse — a plot column holds one or two runs — so union-find
    over column runs settles it in a few thousand operations instead of a
    million-pixel flood fill.
    """
    H, W = sub.shape
    runs = []                       # (col, row0, row1)
    per_col = []
    for c in range(W):
        ys = np.flatnonzero(sub[:, c])
        idx = []
        if len(ys):
            for r in np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1):
                idx.append(len(runs))
                runs.append((c, int(r[0]), int(r[-1])))
        per_col.append(idx)
    if not runs:
        return []
    parent = list(range(len(runs)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for c in range(1, W):
        for i in per_col[c]:
            _, a0, a1 = runs[i]
            for j in per_col[c - 1]:
                _, b0, b1 = runs[j]
                if a0 <= b1 + 1 and b0 <= a1 + 1:      # 8-connected
                    ra, rb = find(i), find(j)
                    if ra != rb:
                        parent[rb] = ra
    agg = {}
    for i, (c, y0, y1) in enumerate(runs):
        k = find(i)
        a = agg.get(k)
        if a is None:
            agg[k] = [c, c, y0, y1, y1 - y0 + 1, [i]]
        else:
            a[0] = min(a[0], c)
            a[1] = max(a[1], c)
            a[2] = min(a[2], y0)
            a[3] = max(a[3], y1)
            a[4] += y1 - y0 + 1
            a[5].append(i)
    return [{"c0": v[0], "c1": v[1], "y0": v[2], "y1": v[3], "n": v[4],
             "runs": v[5]} for v in agg.values()], runs


def drop_glyph_islands(sub):
    """Clear printed marks (a logo, a stamp) from a plot-cropped colour mask.

    Returns a copy with the offending pixels cleared, or the input untouched
    when nothing qualifies — which is the overwhelming majority of charts.
    See the note above for what qualifies and why a spike does not.
    """
    sub = np.asarray(sub, bool)
    H, W = sub.shape
    if H < 8 or W < 8 or not sub.any():
        return sub
    found = _components(sub)
    if not found:
        return sub
    comps, runs = found
    if len(comps) < 2:
        return sub                      # one blob is the curve, whatever it is
    cand, keep = [], []
    for cp in comps:
        w = cp["c1"] - cp["c0"] + 1
        h = cp["y1"] - cp["y0"] + 1
        fill = cp["n"] / float(w * h)
        if w <= GLYPH_WIDTH * W and fill >= GLYPH_FILL:
            cand.append(cp)
        else:
            keep.append(cp)
    if not cand or not keep:
        return sub                      # nothing to judge, or nothing to judge against
    # Per-column extent of the ink we are sure about, so a candidate can be
    # asked whether the trace passes anywhere near it.
    lo = np.full(W, np.nan)
    hi = np.full(W, np.nan)
    for cp in keep:
        for i in cp["runs"]:
            c, y0, y1 = runs[i]
            lo[c] = y0 if not np.isfinite(lo[c]) else min(lo[c], y0)
            hi[c] = y1 if not np.isfinite(hi[c]) else max(hi[c], y1)
    have = np.flatnonzero(np.isfinite(lo))
    if not len(have):
        return sub
    pad = max(4, int(GLYPH_PAD * W))
    near = max(4.0, GLYPH_NEAR * H)

    # Reprieve chains, not just single components. A steep move is torn into
    # several narrow dense pieces by anti-aliasing — the opening pressure drop
    # on 00184 p37 arrives as rows 289-349 over cols 1-23 and rows 356-470 over
    # cols 20-25, with the curve proper not starting until col 28. Judged once
    # each, the lower piece touches the curve and the upper piece is 151 rows
    # clear of it and would be destroyed, taking the top of the transient with
    # it. So a candidate that is cleared joins the trace and the rest are asked
    # again, until nothing more is reprieved: ink that chains back to the curve
    # IS the curve. The logo never chains — nothing bridges the ~180 rows
    # between it and the pressure trace — so the loop settles with it still
    # condemned.
    pending = list(cand)
    while pending:
        spared = []
        for cp in pending:
            a = max(0, cp["c0"] - pad)
            b = min(W - 1, cp["c1"] + pad)
            cols = have[(have >= a) & (have <= b)]
            if not len(cols):
                # No trace beside it at all: fall back to the nearest columns
                # that do carry one, so a real spike standing off on its own —
                # the green needles at the left of 00184 p37 — is still
                # measured against the curve it belongs to rather than
                # condemned for being alone.
                j = int(np.argmin(np.abs(have - (cp["c0"] + cp["c1"]) // 2)))
                cols = have[j:j + 1]
            t0 = float(np.nanmin(lo[cols]))
            t1 = float(np.nanmax(hi[cols]))
            gap = max(t0 - cp["y1"], cp["y0"] - t1, 0.0)
            if gap <= near:
                spared.append(cp)
        if not spared:
            break
        for cp in spared:
            pending.remove(cp)
            for i in cp["runs"]:
                c, y0, y1 = runs[i]
                lo[c] = y0 if not np.isfinite(lo[c]) else min(lo[c], y0)
                hi[c] = y1 if not np.isfinite(hi[c]) else max(hi[c], y1)
        have = np.flatnonzero(np.isfinite(lo))

    if not pending:
        return sub
    out = sub.copy()
    for cp in pending:
        for i in cp["runs"]:
            c, y0, y1 = runs[i]
            out[y0:y1 + 1, c] = False
    return out


# ---------- per-column curve position ----------

def _rolling_median(v, k):
    """Rolling median that ignores NaN (windows shrink at the ends)."""
    n = len(v)
    out = np.full(n, np.nan)
    h = k // 2
    for i in range(n):
        w = v[max(0, i - h):i + h + 1]
        w = w[np.isfinite(w)]
        if len(w):
            out[i] = np.median(w)
    return out


def curve_positions(sub, gap=2, win=None, iters=3, spike_tol=0.12,
                    spike_run=8, glyphs=False, envelope=True,
                    swept_factor=None):
    """One colour mask cropped to the plot -> the curve's row in each column,
    NaN where the curve is not on the page.

    This was a plain median over EVERY masked pixel in the column, which is
    only right when the column holds the curve and nothing else. Charts
    routinely put a second blob of the same colour in the same column:

      - a second series of the same hue. 00183 p40 legends both
        "Surface BU (MPa)" and "O Well (MPa)" in red, and O Well runs flat on
        the axis under the left 69% of the plot;
      - an in-plot legend swatch (00244 p20 draws its key inside the frame);
      - the anti-aliased fringe of a NEIGHBOURING curve, which lands on the
        wrong side of the hue split. On 00244 p20 the washed-out edge of the
        orange step risers, (200,173,143), reads as red.

    With two blobs the median lands BETWEEN them, halfway down the plot, and
    in the few columns where the curve itself is missing it lands on the
    contaminant alone -- the narrow plunge-to-zero notches seen on exported
    STEP charts.

    So split the column into contiguous runs and keep the run nearest a
    rolling median of the trace, re-derived from the chosen runs. The
    reference is global, so there is no seed column to get wrong: seeding on
    column 0 pins the trace to whatever the frame put there and it never
    recovers. A column holding a single run -- the overwhelming majority on
    every template -- comes out bit-identical to before.
    """
    sub = np.asarray(sub, bool)
    H, W = sub.shape
    if H == 0 or W == 0:
        return np.full(W, np.nan)
    # A printed mark inside the frame is not a second blob to choose against —
    # it is wider than the window that does the choosing. Clear it first.
    #
    # Off by default, and deliberately so. It is measured on STEP's tiled
    # reports and nowhere else: run over Halliburton 00784 it also clears 38%
    # of the magenta mask (anti-aliased flecks of the dashed pressure line,
    # the contamination hal1's own _drop_orphans exists for) and moves one
    # stage's BH Prop Conc peak by 2.8%, which may well be an improvement but
    # has not been scored against that template's printed tables. Templates
    # opt in one at a time, each with its own validation.
    if glyphs:
        sub = drop_glyph_islands(sub)
    cols = []                    # per column: ((run median, run height), ...)
    py = np.full(W, np.nan)
    for cx in range(W):
        ys = np.flatnonzero(sub[:, cx])
        if not len(ys):
            cols.append(())
            continue
        py[cx] = np.median(ys)
        cuts = np.flatnonzero(np.diff(ys) > gap) + 1
        cols.append(tuple((float(np.median(r)), int(r[-1] - r[0] + 1))
                          for r in np.split(ys, cuts)))
    k = win or (max(31, W // 20) | 1)
    for _ in range(iters):
        ref = _rolling_median(py, k)
        moved = False
        for cx, rs in enumerate(cols):
            if len(rs) < 2 or not np.isfinite(ref[cx]):
                continue
            best = min(rs, key=lambda t: abs(t[0] - ref[cx]))[0]
            if best != py[cx]:
                py[cx] = best
                moved = True
        if not moved:
            break
    # A column whose only ink is contaminant -- the curve has a gap there --
    # still reads far off the trace; that is the notch. Drop it and let the
    # caller's interpolation bridge the hole, which is what the eye reads off
    # the page. A genuine near-vertical move is a TALL run, so spike_run
    # keeps it.
    ref = _rolling_median(py, 31)
    for cx, rs in enumerate(cols):
        if not rs or not np.isfinite(py[cx]) or not np.isfinite(ref[cx]):
            continue
        hgt = next((h for m, h in rs if m == py[cx]), 1)
        if hgt <= spike_run and abs(py[cx] - ref[cx]) > spike_tol * H:
            py[cx] = np.nan

    # Report the EXTREME of a swept column, not its middle.
    #
    # A column's ink is a run of pixels. Where the run is only as tall as the
    # pen, its middle IS the curve. But where the curve moved through a range
    # inside that column — a pressure transient, the oscillation at a step
    # down — the run spans the whole excursion, and taking its median reports
    # the centre of a swing the chart never sat at. On 00183 chart 32 the page
    # shows a band of red several MPa wide through the 21.3-minute transition
    # and we drew a smooth line down its middle. The client's instruction is
    # explicit: he wants the spikes, not the averaging.
    #
    # So a run taller than the pen is read at whichever END lies further from
    # the local trend — the top on the way up, the bottom on the way down —
    # which traces the envelope of the excursion instead of its centre. The
    # pen's own width is measured from this trace's own runs rather than
    # assumed, so a heavy line does not turn into a spike generator.
    heights = [h for rs in cols for _m, h in rs] if envelope else []
    if heights:
        pen = float(np.median(heights))
        swept = max(3.0, (SWEPT_FACTOR if swept_factor is None
                          else swept_factor) * pen)
        for cx, rs in enumerate(cols):
            if not rs or not np.isfinite(py[cx]) or not np.isfinite(ref[cx]):
                continue
            run = next((r for r in rs if r[0] == py[cx]), None)
            if run is None or run[1] < swept:
                continue
            half = run[1] / 2.0
            lo, hi = py[cx] - half, py[cx] + half
            py[cx] = lo if abs(lo - ref[cx]) > abs(hi - ref[cx]) else hi
    return py


# ---------- main entry ----------

def extract(img, sample_sec=1.0, plot=None, glyphs=False):
    """Auto-calibrated extraction from a chart image (HxWx3 uint8/int array).

    Returns (samples, channels, info):
      channels = [{key,label,unit,color,values,ticks,coverage}], values np.array
      info = {plot, t0_seconds, duration_s, notes[]}
    Raises ValueError with a reason when the page can't be auto-calibrated.
    """
    img = np.asarray(img).astype(int)
    masks = hue_masks(img)
    if not masks:
        raise ValueError("no saturated series colors found")
    x0, y0, x1, y1 = plot if plot is not None else find_plot_area(img, masks)
    tcal = time_calibration(img, x0, x1, y1)
    if tcal is None:
        raise ValueError("time-axis labels could not be read")
    ta, tb = tcal
    t_start = ta + tb * x0
    n = int((ta + tb * x1) - t_start)
    if not (120 < n < 100000):
        raise ValueError(f"implausible duration {n}s from time axis")
    samples = np.arange(int(n / sample_sec)) * sample_sec

    ticks = ocr_tick_strip(img, masks, 0, x0)
    ticks = ocr_tick_strip(img, masks, x1 + 3, min(img.shape[1], x1 + 160), out=ticks)
    ticks = {k: [(v, y, st) for v, y, st in pts if y0 - 25 <= y <= y1 + 25]
             for k, pts in ticks.items()}
    channels, notes = [], []
    for key, mask in masks.items():
        cal = fit_ticks_guarded(ticks.get(key, []))
        sub = mask[y0:y1, x0:x1]
        n_cols = sub.shape[1]
        cov = float(sub.any(axis=0).mean())
        if cal is None:
            notes.append(f"series '{key}': axis ticks unreadable — channel skipped")
            continue
        if cov < 0.1:
            notes.append(f"series '{key}': too sparse ({cov:.0%}) — skipped")
            continue
        a, b, ntick = cal
        # The axis bounds are printed round and sit on the frame edges. The fit
        # comes from OCR'd label centroids and lands ~1-2% off them, an error
        # that otherwise rides straight into the exported values. Snap the two
        # edges onto the tick grid and re-derive the line through them.
        _vt, _vb, _snapped = snap_axis(a + b * y0, a + b * y1)
        if _snapped and abs(y1 - y0) > 1:
            # re-derive through the snapped edges so the correction reaches the
            # exported values, not just the drawing
            b = (_vb - _vt) / float(y1 - y0)
            a = _vt - b * y0
        py = curve_positions(sub, glyphs=glyphs) + y0
        vals = a + b * py
        t_cols = (ta + tb * (np.arange(n_cols) + x0)) - t_start
        if np.isfinite(vals).sum() < 50:
            continue
        # No ink means no reading: np.interp with no left/right clamps to the
        # edge value, so every gap and both tails carried a flat invented line.
        # ct.resample blanks them instead (see curve_trace.resample).
        v = ct.resample(samples, t_cols, vals)
        channels.append({"key": f"series-{key}", "label": f"Series ({key})",
                         "unit": "", "color": HUE_HEX.get(key.rstrip("2"), "#555577"),
                         "values": v, "ticks": ntick, "coverage": cov,
                         # the axis read AT the frame edges (top, bottom).
                         # Same idea as lib1's axes_frame: the Lab positions
                         # against this so a curve lands on its own ink in
                         # ghost mode instead of on a guessed 0..peak scale.
                         "axis_frame": (float(a + b * y0), float(a + b * y1))})
    if not channels:
        raise ValueError("no channel could be calibrated; " + "; ".join(notes[:3]))
    info = {"plot": (x0, y0, x1, y1), "t0_seconds": float(t_start),
            "duration_s": int(n), "notes": notes}
    return samples, channels, info
