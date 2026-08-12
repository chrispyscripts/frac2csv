"""STEP Energy Services charts published as VECTOR pages.

step1.py handles the scanned variant of these reports — image tiles, OCR for
every tick and legend. The same operator also files the identical report as a
vector PDF, and nothing recognised it: no template matched, so the whole file
came back "no extractable data".

Vector is the easier case and needs no OCR at all. Each series carries one
colour, and that colour is shared by three things on the page:

    legend text   "Surf Total Prop Conc (kg/m³)"   -> the name and unit
    tick labels   1000 / 750 / 500 / 250 / 0       -> the value axis
    stroke paths                                    -> the curve

so a colour is enough to tie a curve to its own name and its own scale. Time
comes from the black labels under each plot ("Time (min)": 115, 130, ...).

A page holds two stacked charts — Treatment on top, Chemicals below — and the
SAME colour means different series in each (green is Surf Total Prop Conc
above and SFR-106 below), so everything is resolved per chart band rather than
per page.
"""
import re

import numpy as np

import curve_trace as ct

NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_UNIT = re.compile(r"\(([^)]*)\)\s*$")

# How far past its own outermost tick LABEL a curve's ink may still be that
# curve. These charts stack one value ladder per colour, so a label's centre
# sits up to a text row away from the gridline it names — measured at ~3.4pt
# on 00180 chart 15, against tick spacing of ~117pt. Without the slack a curve
# drawn at its own zero falls outside its ladder and is discarded; with more
# than this, a curve reaches ink belonging above its axis. See the clip below.
LADDER_PAD = 8.0


def detect(page):
    """A STEP report page drawn as vector, not scanned."""
    try:
        text = page.get_text()
    except Exception:
        return False
    if "STEP Energy Services" not in text:
        return False
    if "Treatment Analysis" not in text and "Chemicals Analysis" not in text:
        return False
    try:
        # The scanned variant carries no text layer at all, so the checks above
        # already exclude it; what identifies this one is that the chart is
        # DRAWN. Do not also require zero images — these pages embed the STEP
        # logo, and that alone was disqualifying whole files.
        return len(page.get_drawings()) > 40
    except Exception:
        return False


def _spans(page):
    """-> [(colour_int, text, cx, cy)] for every non-blank span."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                t = s["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                out.append((s.get("color", 0), t, (x0 + x1) / 2, (y0 + y1) / 2))
    return out


def _fit(pairs):
    """[(value, coord)] -> (a, b) with value = a + b*coord, or None."""
    if len(pairs) < 2:
        return None
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    if c.max() - c.min() < 1e-6:
        return None
    b, a = np.polyfit(c, v, 1)
    return float(a), float(b)


def _num(t):
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def _rgb_int(c):
    """Drawing colour (float triple) -> the int a text span carries."""
    r, g, b = (int(round(max(0.0, min(1.0, x)) * 255)) for x in c)
    return (r << 16) | (g << 8) | b


def _bands(spans):
    """Chart bands, one per plot, split on the 'Time (min)' axis captions."""
    ys = sorted(y for _c, t, _x, y in spans if t.lower().startswith("time ("))
    if not ys:
        return []
    out, top = [], 0.0
    for y in ys:
        out.append((top, y))
        top = y
    return out


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit}).

    Mirrors lib1's shape so pipeline can treat this like any other template.
    """
    class Meta:
        pass

    spans = _spans(page)
    bands = _bands(spans)
    if not bands:
        raise ValueError("step_vec: no time axis caption found")

    meta = Meta()
    text = page.get_text()
    meta.warnings = []
    m = re.search(r"-\s*Stage\s+([A-Za-z0-9]+)", text)
    meta.stage = m.group(1) if m else None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", text)
    meta.date = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""
    m = re.search(r"^(.*?)\s*-\s*Stage\s", text, re.M)
    meta.title = (m.group(1).strip() if m else "")[:60]
    meta.uwi = ""

    # curve points grouped by colour, kept with their y so a band can claim them
    strokes = {}
    for d in page.get_drawings():
        c = d.get("color")
        if c is None:
            continue
        key = _rgb_int(c)
        pts = strokes.setdefault(key, [])
        for item in d["items"]:
            if item[0] == "l":
                pts.append((item[1].x, item[1].y))
                pts.append((item[2].x, item[2].y))
            elif item[0] == "c":
                pts.append((item[1].x, item[1].y))
                pts.append((item[4].x, item[4].y))

    data, units, axes, axes_frame = {}, {}, {}, {}
    t_lo = t_hi = None
    geom = None
    for ylo, yhi in bands:
        in_band = [(c, t, x, y) for c, t, x, y in spans if ylo < y <= yhi]
        # Time axis: the black numeric row immediately above the caption.
        # Not "any black number in the band" — the info table between the two
        # charts is black too, and its licence number (29344) dragged the fit
        # to an 11,000-minute stage.
        cand = [(_num(t), x, y) for c, t, x, y in in_band
                if c == 0 and NUM.match(t) and _num(t) is not None]
        rows = {}
        for v, x, y in cand:
            rows.setdefault(round(y, 1), []).append((v, x))
        # the axis row is the lowest one that has several labels spread in x
        tpairs = []
        for ry in sorted(rows, reverse=True):
            pts = rows[ry]
            if len(pts) >= 3 and max(x for _v, x in pts) - min(x for _v, x in pts) > 80:
                tpairs = pts
                break
        tfit = _fit(tpairs)
        if tfit is None:
            continue
        ta, tb = tfit

        # per colour: the legend name and this chart's own tick ladder
        named, ticks = {}, {}
        for c, t, x, y in in_band:
            if c == 0:
                continue
            if NUM.match(t):
                v = _num(t)
                if v is not None:
                    ticks.setdefault(c, []).append((v, y))
            elif "(" in t:
                named[c] = t

        xs = [x for _v, x in tpairs]
        if not xs:
            continue
        x_lo, x_hi = min(xs), max(xs)
        # The plot's own top and bottom are where the outermost TICKS sit, and
        # a curve cannot leave them. The band reaches further: it includes the
        # legend, whose colour-matched line samples were being read as curve
        # points and pushed every peak a few percent past its axis (Surface
        # Press 41.16 on a 0..40 scale).
        if not ticks:
            continue
        # One frame for the whole band, spanning every colour's ticks. Ghost
        # stretches the source page so geom's v0..v1 fills the plot and then
        # places each curve inside its own frames pair, so the two have to be
        # quoted at the SAME page coordinates. Reading each channel's frame at
        # its own tick extent — while geom kept whichever channel happened to
        # be last — left every other curve sitting a fixed distance off its
        # ink, the same gap on every one.
        band_top = min(min(y for _v, y in t) for t in ticks.values()) - 2
        band_bot = max(max(y for _v, y in t) for t in ticks.values()) + 2
        for c, label in named.items():
            vfit = _fit(ticks.get(c, []))
            pts = strokes.get(c)
            if vfit is None or not pts:
                continue
            va, vb = vfit
            # Clip to the BAND, then clamp to this colour's axis.
            #
            # This used to clip to the colour's own tick ladder (min..max label
            # centre, +/- 2pt) to stop a curve running past its axis. But the
            # scales are STACKED and each colour prints its own "0" at its own
            # height, so a label centre is not the value it annotates: on 00180
            # chart 15 the green "0" sits above the orange one, and green's
            # baseline ink — the stretches where proppant concentration is
            # genuinely zero — fell below its own last label and was cut. That
            # deleted 1,650 of 3,716 samples, in three spans at 370.0-384.7,
            # 415.0-419.0 and 423.1-431.9 minutes: exactly the "missing pieces
            # of data at beginning, middle and end" in the client's report, and
            # the whole tail behind "missing end of data" on chart 21. Orange
            # was untouched on the same page only because its own "0" happens
            # to sit lower.
            #
            # The offset is small and bounded — it is one stacked text row,
            # measured at ~3.4pt on this page against tick spacing of ~117pt —
            # so the ladder is widened by LADDER_PAD rather than opened out to
            # the band. Opening it to the band does fix the zeros, but it also
            # let the chemical curves reach ink above their own ladder, taking
            # SSI-1 on this page from 0.27 to 1.95 on a 0..2 axis; that is the
            # "running past their axis" the original clip was written for.
            # Values are still clamped into the tick range, which is what lib1
            # does for the same reason: keep the ink, refuse to report a value
            # the axis cannot show.
            # Slack at the BASELINE end only. These ladders also draw a tick
            # stub in the series' own colour at every label, and widening the
            # high end admits the topmost stub: on chart 24 that took SSI-1
            # from 0.797 to the full 2.0 of its axis. The stub at the low end
            # is admitted too and does no harm — it sits AT zero, which is the
            # value the baseline ink already reports.
            own = [y for _v, y in ticks[c]]
            y_top, y_bot = min(own) - 2, max(own) + LADDER_PAD
            arr = np.array([p for p in pts
                            if y_top <= p[1] <= y_bot
                            and x_lo - 12 <= p[0] <= x_hi + 12])
            if len(arr) < 40:
                continue
            name = _UNIT.sub("", label).strip()
            unit = (_UNIT.search(label).group(1) if _UNIT.search(label) else "")
            t_abs = ta + tb * arr[:, 0]
            tv_all = sorted(v for v, _y in ticks[c])
            vals = np.clip(va + vb * arr[:, 1], tv_all[0], tv_all[-1])
            order = np.argsort(t_abs, kind="stable")
            t_abs, vals = t_abs[order], vals[order]
            lo, hi = float(t_abs.min()), float(t_abs.max())
            t_lo = lo if t_lo is None else min(t_lo, lo)
            t_hi = hi if t_hi is None else max(t_hi, hi)
            data[name] = (t_abs, vals)
            units[name] = unit.replace("³", "3")
            tv = sorted(v for v, _y in ticks[c])
            axes[name] = (tv[0], tv[-1])
            # this curve's axis read at the BAND's top and bottom — the same
            # contract as lib1's axes_frame
            axes_frame[name] = (float(va + vb * band_top),
                                float(va + vb * band_bot))
        if geom is None:
            geom = {"axis": "x", "ta": float(ta * 60.0), "tb": float(tb * 60.0),
                    "v0": float(band_top), "v1": float(band_bot)}

    if not data:
        raise ValueError("step_vec: no series curves matched a legend entry")

    # the labels are minutes; the pipeline works in seconds from stage start
    span_s = max(1.0, (t_hi - t_lo) * 60.0)
    n = int(span_s / sample_sec)
    if not (60 < n < 200000):
        raise ValueError(f"step_vec: implausible duration {n}s")
    samples = np.arange(n) * sample_sec
    out = {}
    for name, (t_abs, vals) in data.items():
        rel = (t_abs - t_lo) * 60.0
        keep = np.isfinite(rel) & np.isfinite(vals)
        if keep.sum() < 2:
            continue
        # Blank across a real break in the curve, not just past its ends.
        # np.interp draws a straight line over any hole, so where the chart
        # showed a channel stopping dead the export carried a long diagonal
        # gliding down to the next point it could find — data that is not on
        # the page (00180 chart 18's proppant concentration).
        out[name] = ct.resample(samples, rel[keep], vals[keep])
    meta.duration_min = span_s / 60.0
    meta.start_time = "00:00:00"
    meta.axes = axes
    meta.axes_frame = axes_frame
    if geom:
        # The tick fit reads ABSOLUTE minutes into the job ("Time (min)": 115,
        # 130, ...), but the samples above are rebased so each stage starts at
        # zero. Ghost mode places the page with (t - ta) / tb, so leaving the
        # absolute origin in there slid the source page left by however far
        # into the job the stage sat: a late page mapped to x -1824..-1428 on
        # a 612-wide page and vanished, an early one only lost its left half.
        geom["ta"] = float(geom["ta"] - t_lo * 60.0)
        meta.geom = geom
    return meta, samples, out, units
