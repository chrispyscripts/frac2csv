"""Scanned CalFrac/MView overview charts: a page that is one picture of the
whole-job plot with an OCR text layer laid over it.

Tourmaline's and TAQA's 2018 Spirit River filings (00019, 00031, 00035 in
the AER set) were scanned from paper. Each holds the MView overview plots —
"Zones 1-19 … Surface", its "Bottom Hole" twin, then Chemicals and Net
Pressure — and no per-zone charts at all, so the overview is the only
treatment data the file carries. The vector MView reader finds no strokes
on a picture, and the generic raster reader could not find the frame
through scan noise nor match the tick labels to the curves by colour, so
these books read as "no page in it draws a plotted curve".

What is on the page is readable. The frame is the longest dark runs
(raster_core.find_frame_px), the time axis is "Time (min)" in elapsed
minutes (auto_raster.time_calibration_ex), and the tick ladders OCR
cleanly — pressure in black on the left, rate and concentration
interleaved on the right and told apart by magnitude. The curves are
MView's fixed palette: blue treating pressure, red rate, green
concentration, purple wellhead concentration on the Bottom Hole page.
Black curves (Bottom Hole Pressure, Annulus Pressure) have no hue to
trace by and are left out with a note.

  python3 -m unittest tests.test_calfrac_scan
"""
import re

import fitz
import numpy as np

import auto_raster as ar
import curve_trace as ct
import raster_core as rc

# series -> the hue families it is printed in, first choice first. MView's
# palette is blue pressure, red rate, green concentration and purple
# wellhead concentration (Tourmaline, 00019/00031); TAQA's copy of it
# (00035) prints the wellhead concentration teal and the formation
# concentration maroon — the maroon lands in the red family with the rate,
# where nothing can tell the two apart, so that series is left out there.
SURFACE = {"Treating Pressure": ("blue",), "Blender Slurry Rate": ("red",),
           "Master Conc @ Blender": ("green",)}
BOTTOM = {"Treating Pressure": ("blue",), "Combined Rate @ Formation": ("red",),
          "Master Conc @ Wellhead": ("magenta", "cyan"),
          "Master Conc @ Formation": ("green",)}
AXIS = {"blue": "pressure", "red": "rate", "green": "conc", "magenta": "conc",
        "cyan": "conc"}
UNITS = {"pressure": "MPa", "rate": "m3/min", "conc": "kg/m3"}
# the black curves each page can carry, named so their absence is explained
BLACK = {" Surface": "Annulus Pressure", " BH": "Bottom Hole Pressure"}

# the rate ladder tops out at 10..20 m3/min; concentration starts at 100
RATE_MAX = 30
CONC_MIN = 50

_UWI = re.compile(r"\d{3}/\d{2}-\d{2}-\d{3}-\d{2}W\d/\d{2}")
_ZONES = re.compile(r"Zones?\s*(\d+)\s*[-–]\s*(\d+)", re.I)
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")


def _lines(page):
    """The OCR layer's words as lines, top to bottom."""
    rows = {}
    for w in page.get_text("words"):
        rows.setdefault(int(w[1] // 6), []).append(w)
    return [" ".join(x[4] for x in sorted(r, key=lambda x: x[0]))
            for _k, r in sorted(rows.items())]


def _text(page):
    return " ".join(_lines(page))


def variant(text):
    """' Surface' / ' BH' / '' — which of MView's two overview pages this
    is. The title says so when the OCR kept it (00035 reads "urtace"), and
    the legend says so regardless: only the Bottom Hole page plots anything
    "@ Formation", only the Surface page the Blender Slurry Rate."""
    if re.search(r"bottom\s*hole|@\s*formation", text, re.I):
        return " BH"
    if re.search(r"\bsurface\b|blender\s*slurry", text, re.I):
        return " Surface"
    return ""


def detect(page):
    """One picture, no vector art, and an OCR layer that reads like an MView
    overview: a minutes axis, a pressure axis and one of the two page kinds."""
    try:
        if len(page.get_images(full=True)) != 1 or page.get_drawings():
            return False
    except Exception:
        return False
    t = _text(page)
    # TAQA's scans (00035) cut the "Time (min)" title off the foot of the
    # page; the legend still names a rate in m3/min, which no other MView
    # page kind prints beside a pressure axis
    return bool(re.search(r"Pressures?\s*\(\s*MPa\s*\)", t, re.I)
                and (re.search(r"Time\s*\(\s*min\s*\)", t, re.I)
                     or re.search(r"Rate\b[^()]{0,30}\(\s*(?:s?m3|rn3|remin)", t, re.I))
                and variant(t))


def _ticks(strip, yoff):
    """OCR one tick strip -> [(value, y)] in image rows."""
    pts = []
    for b in ar.ocr_boxes(strip, psm=6, whitelist="0123456789"):
        if re.fullmatch(r"\d{1,4}", b["text"] or ""):
            pts.append((float(b["text"]), yoff + (b["y0"] + b["y1"]) / 2.0))
    return pts


def _ladder(pts):
    """The one straight ladder in a pile of tick readings -> (inliers, rest)."""
    fit = ar.fit_ticks(pts, min_inliers=4)
    if fit is None:
        return [], list(pts)
    a, b, _n = fit
    vals = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
    tol = max(abs(b) * 20, (vals.max() - vals.min()) * 0.015 + 1e-9)
    inl = np.abs(a + b * ys - vals) < tol
    return [p for p, k in zip(pts, inl) if k], [p for p, k in zip(pts, inl) if not k]


def split_right(pts):
    """The right-hand strip's readings -> (rate ladder, conc ladder, other).

    MView prints the rate and concentration ladders interleaved down one
    column — "12" over "400" over "9" over "300" — so the column position
    cannot separate them, but their magnitudes can: rate is 0..15, the
    concentration hundreds. The zero at the bottom belongs to both. TAQA's
    page adds an N2 ladder (0..500 sm3/min) beside the concentration's
    (0..1000): two straight ladders in the hundreds, the concentration the
    one that climbs higher.
    """
    zeros = [p for p in pts if p[0] == 0]
    rate = [p for p in pts if 0 < p[0] <= RATE_MAX] + zeros
    big = [p for p in pts if p[0] >= CONC_MIN]
    first, rest = _ladder(big)
    second, rest = _ladder(rest) if len(rest) >= 4 else ([], rest)
    ladders = [l for l in (first, second) if l]
    if not ladders:
        return rate, [], []
    ladders.sort(key=lambda l: max(p[0] for p in l), reverse=True)
    conc = ladders[0] + zeros
    other = ladders[1] if len(ladders) > 1 else []
    return rate, conc, other


def axis(pts, y0, y1, kind=None):
    """Tick readings -> (a, b) with value = a + b*y, snapped to the round
    bounds the frame edges print. None when fewer than four labels agree.

    A pressure ladder is printed in tens (0, 20, 40 … 100 MPa), and a scan
    misreads its middle labels as single digits — 00035 p116's "60" and "40"
    came back "3", "260", "2", "4", "4" — which are as straight a line as
    the true labels and fitted a 1..5 MPa axis. So a pressure ladder keeps
    only readings in tens, and an axis whose top is under 20 MPa or whose
    bottom is not near zero is not one.
    """
    if kind == "pressure":
        pts = [p for p in pts if p[0] == 0 or (p[0] >= 10 and p[0] % 10 == 0)]
    fit = ar.fit_ticks(pts, min_inliers=4)
    if fit is None:
        return None
    a, b, _n = fit
    vt, vb, snapped = ar.snap_axis(a + b * y0, a + b * y1, tol_frac=0.05)
    if snapped and abs(y1 - y0) > 1:
        b = (vb - vt) / float(y1 - y0)
        a = vt - b * y0
    if kind == "pressure" and not (a + b * y0 >= 20 and abs(a + b * y1) <= 5):
        return None
    return float(a), float(b)


def elapsed_axis(img, x0, x1, y1):
    """The "Time (min)" labels under the frame -> (seconds at x=0, sec/px)
    or None — for the strip the generic reader declines. 00019 p47 prints
    five labels, 0 50 100 150 200, that OCR perfectly and that
    auto_raster._time_fit still returns nothing for; five round minutes on
    a straight line are a calibration, so they are fitted here."""
    H, W = img.shape[:2]
    xa, xb = max(0, x0 - 60), min(W, x1 + 60)
    strip = img[min(H - 1, y1 + 1):min(H, y1 + 95), xa:xb]
    if strip.size == 0:
        return None
    pts = []
    for text, wx, _wy in ar.ocr_words(strip, psm=6, whitelist="0123456789"):
        if re.fullmatch(r"\d{1,4}", text.strip()):
            pts.append((float(text) * 60.0, xa + wx))
    fit = ar.fit_ticks(pts, min_inliers=4)
    if fit is None or fit[1] <= 0:
        return None
    return float(fit[0]), float(fit[1])


def render(page):
    """The page at the scan's own resolution (at least 3x, at most 4.5x)."""
    im = page.get_images(full=True)[0]
    sc = min(4.5, max(3.0, im[2] / float(page.rect.width or 1)))
    pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc))
    return rc.pixmap_to_array(pix).astype(int), sc


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, data, units, info)."""
    text = _text(page)
    var = variant(text)
    img, sc = render(page)
    H, W = img.shape[:2]
    frame = rc.find_frame_px(img)
    if frame is None:
        raise ValueError("no plot frame found on the scan")
    x0, y0, x1, y1 = [int(v) for v in frame]
    if x1 - x0 < 0.4 * W or y1 - y0 < 0.3 * H:
        raise ValueError(f"frame {x1 - x0}x{y1 - y0} px is not the plot")
    tcal = ar.time_calibration_ex(img, x0, x1, y1)
    if tcal is None:
        tcal = elapsed_axis(img, x0, x1, y1)
        if tcal is None:
            raise ValueError("the time axis labels did not read")
        tcal = (tcal[0], tcal[1], ar.CLOCK_ELAPSED)
    ta, tb, kind = tcal
    t_start = ta + tb * x0
    n = int(tb * (x1 - x0))
    if not (120 < n < 100000):
        raise ValueError(f"implausible duration {n}s from the time axis")
    samples = np.arange(int(n / sample_sec)) * sample_sec

    ry0 = max(0, y0 - 40)
    rows = img[ry0:min(H, y1 + 40)]
    left = _ticks(rows[:, max(0, x0 - 150):max(1, x0 - 4)], ry0)
    rate, conc, other = split_right(_ticks(rows[:, x1 + 4:min(W, x1 + 190)], ry0))
    axes = {"pressure": axis(left, y0, y1, "pressure"), "rate": axis(rate, y0, y1),
            "conc": axis(conc, y0, y1)}

    names = BOTTOM if var == " BH" else SURFACE
    masks = ar.hue_masks(img) or {}
    data, units, frames, notes = {}, {}, {}, []
    for name, hues in names.items():
        # the first of its hues that draws a curve inside the frame
        hue, sub, cov = None, None, 0.0
        for h in hues:
            m = masks.get(h)
            if m is None:
                continue
            c = float(m[y0:y1, x0:x1].any(axis=0).mean())
            if c >= 0.05:
                hue, sub, cov = h, m[y0:y1, x0:x1], c
                break
            cov = max(cov, c)
        if hue is None:
            notes.append(f"{name}: no {' or '.join(hues)} curve in the frame "
                         f"({cov:.0%} of columns) — left out")
            continue
        ax = axes.get(AXIS[hue])
        if ax is None:
            notes.append(f"{name}: its axis ticks did not read on the scan — left out")
            continue
        a, b = ax
        py = ar.curve_positions(sub, edge_blank=True) + y0
        vals = a + b * py
        if np.isfinite(vals).sum() < 50:
            continue
        t_cols = (ta + tb * (np.arange(sub.shape[1]) + x0)) - t_start
        data[name] = ct.resample(samples, t_cols, vals)
        units[name] = UNITS[AXIS[hue]]
        frames[name] = (float(a + b * y0), float(a + b * y1))
    if not data:
        raise ValueError("no curve could be read against its axis; "
                         + "; ".join(notes[:3]))
    black = BLACK.get(var)
    if black and re.search(re.escape(black.split()[0]), text, re.I):
        notes.append(f"{black} is drawn in black and cannot be traced by colour "
                     f"on a scan — left out")
    if other:
        notes.append("a second ladder in the hundreds (N2 rate) shares the right "
                     "axis; its dark-red curve may mix into the rate trace")
    if var == " BH" and "Master Conc @ Formation" not in data \
            and re.search(r"conc\s*@\s*formation", text, re.I):
        notes.append("Master Conc @ Formation is drawn in maroon here, which the "
                     "scan cannot tell from the rate's red — left out, and the "
                     "rate trace may carry some of it")
    if kind != ar.CLOCK_ELAPSED:
        notes.append(f"time axis read as {kind}, not elapsed minutes")

    z = _ZONES.search(text)
    zones = f"Zones {z.group(1)}-{z.group(2)}" if z else ""
    d = _DATE.search(text)
    date = f"{d.group(3)}-{int(d.group(1)):02d}-{int(d.group(2)):02d}" if d else ""
    u = _UWI.search(text)
    meta = {"title": f"{zones or 'Overview'}{var} (scanned)",
            "uwi": u.group(0) if u else "", "stage": f"{zones}{var}" if zones else "",
            "zones": zones, "mv": var, "multi_zone": bool(zones),
            "date": date, "start_time": "00:00:00", "elapsed": True,
            "duration_min": len(samples) / 60.0, "warnings": notes}
    info = {"plot": (x0, y0, x1, y1), "scale": sc, "frames": frames,
            "t0_seconds": float(t_start), "duration_s": n}
    return meta, samples, data, units, info
