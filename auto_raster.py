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

HUE_NAMES = ["red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta"]
HUE_HEX = {"red": "#c8372d", "orange": "#d07a1f", "yellow": "#a89a17",
           "green": "#1e7a34", "cyan": "#118a8a", "blue": "#1d5bd8",
           "purple": "#6d3bb0", "magenta": "#b0329b"}


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

def hue_masks(img):
    """Series colors as broad families. Scans smear hue badly (a series'
    digits and curve can sit 60 deg apart), so tight clustering separates a
    series from its own tick numbers; broad channel-dominance rules keep
    them together. Validated on scanned PSC charts."""
    r = img[..., 0].astype(int); g = img[..., 1].astype(int); b = img[..., 2].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = mx - mn
    # rules validated on scanned/rendered charts; red vs orange split on the
    # green channel (orange carries mid green, true red does not)
    families = {
        "red":     (sat > 60) & (r > g + 40) & (r > b + 40) & (g < b + 60),
        "orange":  (sat > 60) & (r > g + 40) & (r > b + 45) & (g > b + 60),
        "green":   (sat > 50) & (g > r + 30) & (g > b + 20),
        "magenta": (sat > 60) & (r > g + 40) & (b > g + 40),
        "blue":    (sat > 60) & (b > g + 40) & (b > r + 40),
        "cyan":    (sat > 60) & (g > r + 40) & (b > r + 40) & (np.abs(g - b) < 35),
    }
    families["green"] = families["green"] & ~families["cyan"]
    min_px = max(400, img.shape[0] * img.shape[1] // 5000)
    return {k: m for k, m in families.items() if m.sum() >= min_px}


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


def time_calibration(img, x0, x1, y1):
    """OCR time labels under the plot. HH:MM:SS or plain minutes."""
    H, W, _ = img.shape
    xa, xb = max(0, x0 - 60), min(W, x1 + 60)
    strip = img[min(y1 + 5, H - 1):min(y1 + 95, H), xa:xb]
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


# ---------- main entry ----------

def extract(img, sample_sec=1.0, plot=None):
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
