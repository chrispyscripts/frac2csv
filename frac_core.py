"""Frac2CSV core: extract frac-stage time-series curves from vector chart PDFs.

Works on MView-style frac charts where each data series is stroked vector
geometry in a distinct RGB color. Page metadata (UWI, stage/zone, date, axis
ranges) is auto-detected from the page text; every value can be overridden.

Layout assumptions (MView "Casing Ign Template" and similar):
  - the plot frame is a closed black rectangle covering most of the page
  - time runs along the PDF y axis on the rotated pages and along x on the
    unrotated 2024 layout; whichever margin carries the "Time (min)" title
    settles it
  - all value axes are zero-based and span the full plot frame
  - which curve is which comes from the page's own legend, not from a fixed
    colour table: the same colours mean different curves across vintages
"""
import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import fitz  # PyMuPDF
import numpy as np

import aliases
import ocr_labels

# stroke color -> (csv column, axis kind). LAST-RESORT fallback only: the
# template re-uses the same colours for different curves across vintages, so
# detect_legend() reads the page's own legend first and this table is reached
# only when a page draws no legend at all. See detect_legend for the specifics.
SERIES = {
    (0.0, 0.0, 1.0): ("Tr Press", "pressure"),
    (1.0, 0.0, 0.0): ("Slurry Rate", "rate"),
    (0.0, 0.5, 0.0): ("WH Prop Conc", "conc"),
    (0.5, 0.0, 0.5): ("BH Prop Conc", "conc"),
}
COLUMNS = ["Tr Press", "Slurry Rate", "WH Prop Conc", "BH Prop Conc"]
KINDS = {"Tr Press": "pressure", "Slurry Rate": "rate",
         "WH Prop Conc": "conc", "BH Prop Conc": "conc"}
UNITS = {"Tr Press": "MPa", "Slurry Rate": "m3/Min",
         "WH Prop Conc": "Kg/m3", "BH Prop Conc": "Kg/m3"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


@dataclass
class PageMeta:
    uwi: str = ""
    stage: str = ""
    date: str = ""            # YYYY-mm-dd
    start_time: str = "00:00:00"
    duration_min: float = 0.0
    pressure_max: float = 0.0
    rate_max: float = 0.0
    conc_max: float = 0.0
    title: str = ""
    warnings: list = field(default_factory=list)


# Plot-frame geometry. A side must reach both of its corners to within
# _FRAME_TOL, and the enclosed box must cover _FRAME_MIN_SIDE of the page in
# both directions -- a chart frame always does, a table rule or a title box
# never does.
_FRAME_TOL = 3.0
_FRAME_MIN_SIDE = 0.45


# A frame is not always BLACK. The MView pages in ARC's Alberta filings rule
# their plot box and gridlines in mid grey (0.5, 0.5, 0.5), so a near-black-only
# test found ONE segment on 00089 p62 and _detect_frame returned None — "no plot
# frame found on page" on a chart that is perfectly readable (#341).
#
# Widened, but only ever ADDED to: anything the old rule accepted still passes,
# and the new part requires the ink to be NEUTRAL, so a dark coloured curve
# cannot become a frame edge. The len(items) guard below is what actually keeps
# curves out; this only decides what counts as frame-coloured.
_FRAME_MAX_LEVEL = 0.6
_FRAME_NEUTRAL_TOL = 0.10


def _frame_ink(color):
    """True for the near-black the frame used to be, or a neutral mid grey."""
    hi, lo = max(color), min(color)
    if hi <= 0.2:                       # the original rule, unchanged
        return True
    return hi <= _FRAME_MAX_LEVEL and (hi - lo) <= _FRAME_NEUTRAL_TOL


def _black_segments(page):
    """Axis-aligned near-black stroked segments: [(horizontal, pos, lo, hi)].

    Covers both shapes this template uses: the rotated pages draw the frame
    as one 4-segment path, the 2024 unrotated ones as four separate
    single-segment paths. Paths with many segments are skipped -- that is
    what a curve looks like, and a curve standing in for the frame is the bug
    this function exists to stop.
    """
    segs = []
    for d in page.get_drawings():
        color = d.get("color")
        if d.get("type") != "s" or color is None or not _frame_ink(color):
            continue
        items = d["items"]
        if len(items) > 6:
            continue
        for item in items:
            dark = max(color) <= 0.2
            if item[0] == "re":
                r = item[1]
                segs += [(True, r.y0, r.x0, r.x1, dark),
                         (True, r.y1, r.x0, r.x1, dark),
                         (False, r.x0, r.y0, r.y1, dark),
                         (False, r.x1, r.y0, r.y1, dark)]
                continue
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            dx, dy = abs(p1.x - p2.x), abs(p1.y - p2.y)
            if dy <= 0.5 < dx:
                segs.append((True, (p1.y + p2.y) / 2,
                             min(p1.x, p2.x), max(p1.x, p2.x), dark))
            elif dx <= 0.5 < dy:
                segs.append((False, (p1.x + p2.x) / 2,
                             min(p1.y, p2.y), max(p1.y, p2.y), dark))
    return segs


def _detect_frame(page):
    """Plot frame = the largest closed axis-aligned black rectangle.

    The old rule -- largest black stroked path with >= 4 items -- had no test
    for closure, so on the 2024 Tourmaline layout (which draws the frame as
    four separate one-segment paths and a black "Tubing Pressure" curve) the
    CURVE's bounding box became the frame and every axis was fitted from it:
    a 50-minute stage read as 600 minutes. Returns None when nothing closes,
    which the caller turns into a page-level failure. Guessing is worse than
    reporting the page.
    """
    box = page.cropbox or page.rect
    segs = _black_segments(page)
    # BLACK first, then longest, then capped: the pairing below is quadratic in
    # each list so the cap has to stay small, and once grey counts as frame ink
    # a page with many grey rules can push the real black frame out of the top
    # 16 — which shrank 66 frames on 00004 to a third of their height. Ranking
    # the ink the old rule accepted ahead of the new keeps every such page on
    # exactly the frame it had.
    def _cap(cands):
        """The 16 best, plus the two OUTERMOST — a frame's edges are the
        extreme lines, and on a grid they are the same length as every
        gridline, so "longest first" ranks them arbitrarily. On 00090 p65 all
        21 qualifying horizontals were 492.3pt long and the real top edge
        landed at index 18: the frame lost its top, came out 17% short, and
        every zone time was placed against a 1125-minute window on a chart
        whose axis reads 1350."""
        cands = list(cands)
        if not cands:
            return []
        keep = cands[:16]
        for extreme in (min(cands, key=lambda s: s[1]),
                        max(cands, key=lambda s: s[1])):
            if extreme not in keep:
                keep.append(extreme)
        return keep

    hs = _cap(sorted((s for s in segs
                      if s[0] and s[3] - s[2] >= _FRAME_MIN_SIDE * box.width),
                     key=lambda s: (not s[4], s[2] - s[3])))
    vs = _cap(sorted((s for s in segs
                      if not s[0] and s[3] - s[2] >= _FRAME_MIN_SIDE * box.height),
                     key=lambda s: (not s[4], s[2] - s[3])))
    best = best_dark = None
    for i, (_h, ytop, *_r) in enumerate(hs):
        for j in range(i + 1, len(hs)):
            top, bot = sorted((ytop, hs[j][1]))
            if bot - top < _FRAME_MIN_SIDE * box.height:
                continue
            for k, (_v, xa, *_s) in enumerate(vs):
                for m in range(k + 1, len(vs)):
                    left, right = sorted((xa, vs[m][1]))
                    if right - left < _FRAME_MIN_SIDE * box.width:
                        continue
                    sides = (hs[i], hs[j], vs[k], vs[m])
                    if any(s[2] > (left if s[0] else top) + _FRAME_TOL or
                           s[3] < (right if s[0] else bot) - _FRAME_TOL
                           for s in sides):
                        continue
                    area = (right - left) * (bot - top)
                    rect = fitz.Rect(left, top, right, bot)
                    if all(s[4] for s in sides):
                        if best_dark is None or area > best_dark[0]:
                            best_dark = (area, rect)
                    if best is None or area > best[0]:
                        best = (area, rect)
    # An all-BLACK frame wins outright when the page has one. Grey is only
    # here for pages that draw no black frame at all, and letting it compete
    # on area moved 33 frames by ~0.13pt — harmless in value terms, but it
    # means a page that used to read one way now reads another for no gain.
    if best_dark is not None:
        return best_dark[1]
    return best[1] if best else None


_TIME_LABEL = re.compile(r"time\s*\(\s*min", re.I)


def _orientation(page, frame):
    """'y' when time runs down the PDF y axis, 'x' when it runs along x.

    The 2013-2025 pages are rotated 90 degrees and plot time up the y axis;
    the 2024 Tourmaline layout is unrotated and plots it along x. Decided by
    which side of the frame carries the "Time (min)" axis title, because that
    is what actually labels the axis; page /Rotate is only the fallback.
    """
    for bbox, text in _text_spans(page):
        if not _TIME_LABEL.search(text):
            continue
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        if cx < frame.x0 or cx > frame.x1:
            return "y"
        if cy < frame.y0 or cy > frame.y1:
            return "x"
    return "y" if page.rotation in (90, 270) else "x"


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


# --- the page's own legend ------------------------------------------------
#
# A legend key is one short stroked segment drawn beside its label: 28.08pt
# at 1.44-1.5pt wide in every CalFrac vintage seen. The length bounds keep
# annotation rules (which run half the page) and stray one-segment curve
# fragments out; the width test keeps out the axis tick marks, which are 8pt
# hairlines sitting right beside the axis titles and would otherwise be read
# as keys for them.
_SWATCH_MIN, _SWATCH_MAX = 16.0, 60.0
_SWATCH_WIDTH = 0.5
_LEGEND_GAP = 8.0          # key-to-label clearance, pt
_LEGEND_TOL = 1.0          # slack when testing "the label covers this key"


def _clean_label(text):
    """'Master Conc @ Wellhead (kg/m³' -> 'Master Conc @ Wellhead'.

    The rotated layout clips the trailing unit mid-token, so the closing
    bracket is optional.
    """
    return re.sub(r"\s*\([^()]*\)?\s*$", "", text.strip()).strip()


def _legend_keys(page):
    """[(rgb, rect, horizontal)] for every legend swatch on the page."""
    out = []
    for d in page.get_drawings():
        if d.get("type") != "s" or d.get("color") is None:
            continue
        items = d["items"]
        if len(items) != 1 or items[0][0] != "l":
            continue
        p1, p2 = items[0][1], items[0][2]
        dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
        if min(dx, dy) > 1.0 or not _SWATCH_MIN <= max(dx, dy) <= _SWATCH_MAX:
            continue
        if (d.get("width") or 0) < _SWATCH_WIDTH:
            continue
        out.append((tuple(round(c, 4) for c in d["color"]), d["rect"], dx >= dy))
    return out


def _text_spans(page):
    """[(bbox, text)] for every span carrying a letter.

    A page whose text layer decodes to control characters has none, and its
    legend is read off the render instead (see ocr_labels). Nothing else
    about the page changes: the swatches, the frame and the curves are all
    real vector artwork and are read from the PDF as always.
    """
    if ocr_labels.garbled(page):
        return ocr_labels.text_spans(page)
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t and any(c.isalpha() for c in t):
                    out.append((span["bbox"], t))
    return out


def _label_for_key(rect, horizontal, spans):
    """The legend text this key belongs to, or None.

    Rotated pages stack the legend down the PDF x axis and draw each key
    directly after its label's y1; unrotated pages stack it down y and draw
    the key directly before the label's x0. Pick the nearest label that both
    covers the key across the stack and abuts it along it.
    """
    best, best_gap = None, None
    for (x0, y0, x1, y1), text in spans:
        if horizontal:
            cy = (rect.y0 + rect.y1) / 2
            if not y0 - _LEGEND_TOL <= cy <= y1 + _LEGEND_TOL:
                continue
            gap = x0 - rect.x1
        else:
            cx = (rect.x0 + rect.x1) / 2
            if not x0 - _LEGEND_TOL <= cx <= x1 + _LEGEND_TOL:
                continue
            gap = rect.y0 - y1
        if not -_LEGEND_TOL <= gap <= _LEGEND_GAP:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = text, gap
    return best


def detect_legend(page):
    """Read colour -> channel off the page's own legend.

    Returns (mapping, blocks) or (None, None) when the page draws no legend:
      mapping  {rgb: (column, kind)} for the four treatment channels
      blocks   [[(rgb, label, column|None), ...], ...] — every keyed curve,
               one list per legend block, in the order the block stacks them.

    A fixed colour table cannot serve this template. The 2013-2016 vintage
    strokes "Master Conc @ Wellhead" purple and "@ Formation" teal; 2025
    swaps the two. 2025 Surface pages draw the wellhead concentration in a
    green (0, 0.5, 0.25) that is in no table at all, so SERIES dropped it
    silently. And Net Pressure pages stroke "Net Pressure" in exactly the
    green SERIES reserves for wellhead concentration. Only the legend knows.

    Curve names resolve through Carmine's alias table; anything that is not
    one of the four treatment channels (Bottom Hole / Deadstring / Net
    Pressure, chemical concentrations, N2 and pump-down rates) is reported in
    `blocks` with a None column so callers can tell "deliberately excluded"
    from "unrecognised colour".
    """
    keys = _legend_keys(page)
    if not keys:
        return None, None
    spans = _text_spans(page)
    named = []
    for rgb, rect, horizontal in keys:
        text = _label_for_key(rect, horizontal, spans)
        if text is None:
            continue
        col = aliases.canon(_clean_label(text))
        named.append((rgb, rect, horizontal, text, col if col in KINDS else None))
    if not named:
        return None, None

    # Split into the page's legend blocks (pressure keys sit under the
    # pressure axis, rate/concentration keys under theirs) and order each
    # block the way it stacks -- the same order the tick-label columns use.
    blocks = {}
    for rgb, rect, horizontal, text, col in named:
        anchor = rect.x0 if horizontal else rect.y0
        anchor = next((a for a in blocks if abs(a - anchor) <= 2.0), anchor)
        sort = rect.y0 if horizontal else rect.x0
        blocks.setdefault(anchor, []).append((sort, rgb, text, col))
    ordered = []
    for anchor in sorted(blocks):
        ordered.append([(rgb, text, col)
                        for _s, rgb, text, col in sorted(blocks[anchor],
                                                         key=lambda r: r[0])])

    mapping, taken = {}, set()
    for block in ordered:
        for rgb, _text, col in block:
            # first key wins: a page that legends the same channel twice
            # (e.g. a repeated "Master Concentration") would otherwise have
            # its second curve overwrite the first
            if col is None or rgb in mapping or col in taken:
                continue
            mapping[rgb] = (col, KINDS[col])
            taken.add(col)
    return mapping, ordered


def _curveish(page):
    """Stroked paths long enough to be curves, in a colour that isn't ink.

    Greys and blacks are the frame, the gridlines and the text, so a page of
    prose does not reach the legend read below.
    """
    out = []
    for d in page.get_drawings():
        color = d.get("color")
        if color is None or len(d["items"]) <= 5:
            continue
        if max(color) - min(color) < 0.15:      # neutral: frame/grid/text
            continue
        out.append(tuple(round(c, 4) for c in color))
    return out


def page_kind(page):
    """'vector' if the page has stroked curves in known series colors,
    else 'raster'."""
    for d in page.get_drawings():
        color = d.get("color")
        if color is None:
            continue
        for c in SERIES:
            if sum((a - b) ** 2 for a, b in zip(c, color)) < 1e-4 and len(d["items"]) > 5:
                return "vector"
    # SERIES is a last-resort table — see its comment, and the module docstring:
    # which curve is which comes from the page's OWN legend, because the
    # template reuses colours differently across vintages. But this gate did
    # not, so a filing drawn in a restyled palette was called "raster" and
    # dropped before anything could read its legend. 01377 (#365) is 329 pages
    # carrying 96 charts whose curves are ordinary vector paths in
    # (0.03,0.32,0.65) blue and (0.93,0.11,0.14) red — near, but not equal to,
    # the pure primaries above — and it produced nothing at all for that reason.
    #
    # Only pages that already look like charts pay for the legend read, so a
    # page of prose still costs one get_drawings() scan.
    curves = _curveish(page)
    if not curves:
        return "raster"
    try:
        mapping, _rows = detect_legend(page)
    except Exception:
        return "raster"
    if mapping and any(c in mapping for c in curves):
        return "vector"
    return "raster"


def detect_text_meta(page, meta=None):
    """UWI/stage/date/title from page text (works even for raster pages
    that kept a text layer). Frame-independent."""
    if meta is None:
        meta = PageMeta()
    text = ocr_labels.page_text(page)

    m = re.search(r"(1[0-9A-F]\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups())
    else:
        # BC NTS format, tolerant of short forms: a-82-I/94-G-1
        m = re.search(r"\b([a-dA-D])-?(\d{2,3})-([A-L])\s*/\s*0?(\d{2,3})-([A-P])-0?(\d{1,2})\b",
                      text)
        if m:
            q, unit, blk, sheet, letter, num = m.groups()
            meta.uwi = (f"2 00{q.upper()}{int(unit):03d}{blk.upper()}"
                        f"{int(sheet):03d}{letter.upper()}{int(num):02d}00"
                        ).replace(" ", "")
    if not meta.uwi:
        meta.warnings.append("UWI not found in page text")

    m = re.search(r"(?:Zone|Stage)\s+(\d+)", text)
    if m:
        meta.stage = m.group(1)
    elif ocr_labels.garbled(page):
        # A lone "1" beside "Zone" is the one thing the full-page OCR pass
        # reliably gets wrong; ocr_labels reads that caption again, larger.
        meta.stage = ocr_labels.stage_number(page) or ""
        if not meta.stage:
            meta.warnings.append("stage/zone not found")
    elif not meta.stage:
        meta.warnings.append("stage/zone not found")


    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if m and m.group(1)[:3].lower() in MONTHS:
        meta.date = f"{int(m.group(3)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    elif not meta.date:
        meta.warnings.append("date not found")

    first_line = text.strip().splitlines()[0] if text.strip() else ""
    meta.title = first_line.strip()
    return meta


def is_chemicals(page):
    """True for an MView "... Chemicals" chart.

    These plot chemical additives against a Chemical Concentration (L/m3)
    axis, but this module identifies a curve purely by its COLOUR, so a
    chemicals page is read as a treatment page: its green "NE/Surf Conc
    (L/m3)" came out as WH Prop Conc in Kg/m3 on a 0..5 axis, sitting in the
    same chart as a real BH Prop Conc on 0..500. A stage spans several pages
    and the chemicals ones are interleaved with Surface/Bottom Hole, so they
    have to be excluded by type rather than by position.

    The export is defined as the four canonical treatment channels, so there
    is nothing on these pages that belongs in it.
    """
    try:
        text = ocr_labels.page_text(page)
    except Exception:
        return False
    if re.search(r"Chemical\s+Concentration", text, re.I):
        return True
    # the title line ends with the chart kind: "... Surface" / "... Bottom
    # Hole" / "... Chemicals"
    for line in (l.strip() for l in text.splitlines()):
        if line:
            return bool(re.search(r"\bChemicals?\s*$", line, re.I))
    return False


# Tick-label geometry. A value band's labels for one tick are printed as a
# single run with no gap between them; the gap to the next tick is tens of
# points. The band pad is generous on purpose: the FIRST label of a run sits
# up to ~12pt beyond the frame corner, and clipping it (the old +-10pt window
# did) throws away the whole axis's top tick.
_TICK_GAP = 1.5
_BAND_PAD = 30.0


def _numeric_spans(page):
    """[(bbox, value)] for every span that is a bare number."""
    if ocr_labels.garbled(page):
        return ocr_labels.numeric_spans(page)
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                v = _num(span["text"].strip())
                if v is not None:
                    out.append((span["bbox"], v))
    return out


def _axis_columns(page, frame, orient, band):
    """One value band's tick labels -> [full scale, per axis] in stack order.

    The template prints every value axis's label for a tick as one run: at
    the top tick of a 2025 Surface page it prints "16 1200 1200 4.0 4.0" side
    by side -- rate, wellhead conc, formation conc, and two chemical axes, in
    the order the legend lists them. Read as a flat list of numbers, as the
    old code did, there is no way to tell the rate axis from the
    concentration axis (it guessed with a "< 100" test) and no way at all to
    tell two concentration axes apart when their ranges differ.

    Returns None when the band does not read as a tick column -- the caller
    then falls back to the flat maximum.
    """
    lo_i, hi_i = (0, 2) if orient == "y" else (1, 3)
    runs = []
    for bbox, v in _numeric_spans(page):
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        if orient == "y":
            if not frame.x0 - _BAND_PAD < cx < frame.x1 + _BAND_PAD:
                continue
            if band == "pressure" and cy <= frame.y1:
                continue
            if band == "value" and cy >= frame.y0:
                continue
        else:
            if not frame.y0 - _BAND_PAD < cy < frame.y1 + _BAND_PAD:
                continue
            if band == "pressure" and cx >= frame.x0:
                continue
            if band == "value" and cx <= frame.x1:
                continue
        runs.append((bbox[lo_i], bbox[hi_i], v))
    runs.sort()
    groups = []
    for lo, hi, v in runs:
        if groups and lo - groups[-1][-1][1] < _TICK_GAP:
            groups[-1].append((lo, hi, v))
        else:
            groups.append([(lo, hi, v)])
    if len(groups) < 3:
        return None
    # Every tick prints one label per axis, so the number of axes is the
    # width almost every run has. The odd one out is the zero end, where the
    # time axis prints its own label hard up against this band's and the two
    # merge into one run; that run is dropped rather than allowed to shift
    # the axis indices.
    widths = [len(g) for g in groups]
    width = max(set(widths), key=widths.count)
    full = [g for g in groups if len(g) == width]
    if len(full) < 3 or len(full) * 2 < len(groups):
        return None
    if not ocr_labels.garbled(page):
        return [max(g[k][2] for g in full) for k in range(width)]
    # OCR'd ticks. This mapping is positional — column 0 is the rate axis,
    # the rest are concentrations — so it only holds while every tick row is
    # complete. One label the OCR did not see shortens that row, the modal
    # width follows the short rows, and the columns shift: on 00035 p114 the
    # rate axis (0..18) and the first concentration axis (0..900) both came
    # back as 700, which would have multiplied every rate in the CSV by
    # forty. So a ragged read is refused outright and the caller falls back
    # to the flat maxima, which cannot be misaligned because they are not
    # aligned to anything.
    if len(full) != len(groups):
        return None
    out = []
    for k in range(width):
        # ...and a column that survives that still has to be a straight
        # line: "900" read as "9000" at the top of a concentration axis is
        # a tenfold error that looks exactly like a bigger axis.
        kept = ocr_labels.axis_column_ok([(g[k][0], g[k][2]) for g in full])
        if not kept:
            return None
        out.append(max(v for _p, v in kept))
    return out


def _fit_time_axis(pts, far_edge):
    """OCR'd time labels -> the axis's value at the frame's far edge.

    `pts` is [(position, minutes)]. Returns None unless the labels fall on a
    line, which also throws out a stray number that wandered into the band.
    The answer is rounded to whole minutes: these axes are labelled in round
    numbers and the fit's own residual is a fraction of one.
    """
    kept = ocr_labels.axis_column_ok(pts)
    if not kept or len(kept) < 4:
        return None
    xs = np.array([p for p, _v in kept], float)
    ys = np.array([v for _p, v in kept], float)
    if xs.max() - xs.min() < 1e-6:
        return None
    b, a = np.polyfit(xs, ys, 1)
    dur = a + b * far_edge
    # The far edge is the END of the axis, so the answer sits at the largest
    # label or just past it — within half a tick either way, since the last
    # label is normally printed right on the edge and the fit lands a
    # fraction of a minute off it, and never more than two ticks beyond.
    step = float(np.median(np.abs(np.diff(np.sort(ys))))) or 1.0
    if not (ys.max() - 0.5 * step <= dur <= ys.max() + 2.0 * step):
        return None
    return round(float(dur))


def detect_meta(page, frame, orient=None):
    """Full metadata: text fields plus axis ranges read from tick labels."""
    meta = detect_text_meta(page)
    if orient is None:
        orient = _orientation(page, frame)

    # Axis labels: numeric spans grouped by which margin of the frame they sit
    # in. Which margin carries which axis depends on the layout -- rotated
    # pages run time up the right edge with the value axes above and below,
    # unrotated ones run time along the bottom with the value axes left and
    # right. Time is tested first: the unrotated layout's time labels sit
    # under the frame's bottom-right corner, inside the concentration
    # column's own x band.
    time_vals, pressure_vals, top_vals = [], [], []
    pad = 10
    # Through _numeric_spans, not page.get_text, so a page whose numbers had
    # to be OCR'd is banded by exactly the same rules as one whose numbers
    # were readable.
    time_pts = []
    for (x0, y0, x1, y1), v in _numeric_spans(page):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        along_x = frame.x0 - pad < cx < frame.x1 + pad
        along_y = frame.y0 - pad < cy < frame.y1 + pad
        if orient == "y":
            if cx > frame.x1 and along_y:
                time_vals.append(v); time_pts.append((cy, v))
            elif cy > frame.y1 and along_x:
                pressure_vals.append(v)
            elif cy < frame.y0 and along_x:
                top_vals.append(v)
        else:
            if cy > frame.y1 and along_x:
                time_vals.append(v); time_pts.append((cx, v))
            elif cx < frame.x0 and along_y:
                pressure_vals.append(v)
            elif cx > frame.x1 and along_y:
                top_vals.append(v)

    if time_vals and ocr_labels.garbled(page):
        # The duration sets where every sample lands, so on an OCR'd page it
        # is FITTED and read at the frame's far edge rather than taken as the
        # largest label seen. A missed last tick would otherwise shorten the
        # stage — 140 minutes for a 160-minute job — and squeeze every curve
        # on the page to match, with nothing to show it had happened.
        far = frame.y0 if orient == "y" else frame.x1
        meta.duration_min = _fit_time_axis(time_pts, far) or 0.0
        if meta.duration_min <= 0:
            meta.warnings.append("time axis labels did not fit a line")
    elif time_vals:
        meta.duration_min = max(time_vals)
    else:
        meta.warnings.append("time axis labels not found")

    # Per-axis full scales, one entry per tick-label column in legend order.
    # extract_page binds them to curves through the legend; the flat maxima
    # below stay populated for the manual-override path and as the fallback
    # when a page's tick columns do not parse.
    meta.axes = {"pressure": _axis_columns(page, frame, orient, "pressure"),
                 "value": _axis_columns(page, frame, orient, "value")}

    if meta.axes["pressure"]:
        meta.pressure_max = max(meta.axes["pressure"])
    elif pressure_vals:
        meta.pressure_max = max(pressure_vals)
    else:
        meta.warnings.append("pressure axis labels not found")
    value = meta.axes["value"]
    if value:
        # first column is the rate axis, the rest are concentrations and
        # chemical additives
        meta.rate_max = value[0]
        conc = [v for v in value[1:] if v > 0]
        meta.conc_max = max(conc) if conc else 0.0
    elif top_vals:
        meta.conc_max = max(top_vals)
        small = [v for v in top_vals if v < max(100.0, meta.conc_max / 10)]
        meta.rate_max = max(small) if small else 0.0
    if meta.rate_max <= 0 or meta.conc_max <= 0:
        meta.warnings.append("rate/conc axis labels not fully detected")
    return meta


def _match(color, table):
    """The table key this stroke colour is, or None."""
    if color is None or not table:
        return None
    key = min(table, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, color)))
    if sum((a - b) ** 2 for a, b in zip(key, color)) > 1e-4:
        return None
    return key


def _collect_points(page, frame, series=None, unclaimed=None, known=()):
    """Per-series (y, x) point arrays, clipped to the plot frame.

    `series` is the colour table to bind against (the page's legend, or
    SERIES as a fallback). Colours that stroke a real curve inside the frame
    but match neither `series` nor `known` (the legend's deliberate
    exclusions) are appended to `unclaimed` so the caller can warn: silently
    dropping a curve is how the wellhead concentration went missing from a
    third of the corpus.
    """
    if series is None:
        series = SERIES
    raw, orphan = {}, {}
    for d in page.get_drawings():
        color = d.get("color")
        if color is None or d.get("type") != "s":
            continue
        key = _match(color, series)
        pts = raw.setdefault(key, []) if key is not None else \
            orphan.setdefault(tuple(round(c, 4) for c in color), [])
        for item in d["items"]:
            if item[0] == "l":
                pts.append((item[1].x, item[1].y))
                pts.append((item[2].x, item[2].y))
            elif item[0] == "c":
                pts.append((item[1].x, item[1].y))
                pts.append((item[4].x, item[4].y))

    def inside(pts):
        arr = np.array(pts)
        pad = 1.0
        keep = ((arr[:, 0] >= frame.x0 - pad) & (arr[:, 0] <= frame.x1 + pad) &
                (arr[:, 1] >= frame.y0 - pad) & (arr[:, 1] <= frame.y1 + pad))
        return arr[keep]

    out = {}
    for color, pts in raw.items():
        arr = inside(pts)
        if len(arr):
            out[color] = arr
    if unclaimed is not None:
        for color, pts in orphan.items():
            # a curve, not chart furniture: many in-frame vertices, and not
            # the black/grey the frame, grid and annotations are drawn in
            if len(pts) < 60 or max(color) - min(color) < 0.05:
                continue
            if _match(color, known) is not None:
                continue                    # legended, deliberately excluded
            if len(inside(pts)) >= 60:
                unclaimed.append(color)
    return out


def _axes_by_curve(meta, blocks):
    """{column: full scale} by pairing legend entries with tick columns.

    The legend lists a block's curves in the same order the tick labels stack
    their columns, so the k-th curve reads against the k-th axis. Blocks are
    matched to bands by what they hold, not by where they sit: the legend is
    drawn INSIDE the plot frame, so its position says nothing about which
    margin its axis is in.

    A block can be longer than its column list -- the two concentrations
    share one axis on the 2013-2016 pages -- in which case the curves past
    the last column read against it too.
    """
    axes = getattr(meta, "axes", None)
    if not axes or not blocks:
        return {}
    out = {}
    for block in blocks:
        kinds = {KINDS[c] for _r, _t, c in block if c}
        if not kinds:
            continue
        band = "pressure" if kinds == {"pressure"} else \
               ("value" if "pressure" not in kinds else None)
        cols = axes.get(band) if band else None
        if not cols:
            continue
        for i, (_rgb, _text, col) in enumerate(block):
            if col and col not in out:
                out[col] = float(cols[min(i, len(cols) - 1)])
    return out


def _resample(t_min, values, sample_min):
    """Curve vertices (already sorted by time) -> the sample grid.

    A chart step is drawn as two vertices at the SAME instant, one at each
    level. Collapsing those to their mean — which this used to do — does not
    just soften the edge, it destroys the flat run on either side of it: the
    run's own endpoints are the step vertices, so both ends of a twenty-minute
    shut-in at zero concentration came back as half-height points and np.interp
    drew one long straight ramp between them. That is the "pen up/down" error:
    00087 p54 reported the wellhead concentration climbing steadily from 0 to
    25 kg/m³ across the shut-in, where the page prints a flat line at zero.

    So keep both levels. Each instant contributes two knots — the value the
    curve arrives at and the value it leaves with, in the order the path was
    stroked — and np.interp reads that pair as the vertical it is: the runs
    either side stay flat at their own level. Where an instant has only one
    vertex the two knots are equal and the result is unchanged.
    """
    t = np.round(np.asarray(t_min, float), 6)
    v = np.asarray(values, float)
    if len(t) == 0:
        return np.full(len(sample_min), np.nan)
    # bj1, canyon, halliburton_ifs and lib1 hand this their vertices unsorted —
    # np.unique used to sort for them. Stable, so that vertices sharing an
    # instant keep the order they were stroked in, which is what tells the
    # arriving level from the leaving one.
    if np.any(t[1:] < t[:-1]):
        order = np.argsort(t, kind="stable")
        t, v = t[order], v[order]
    first = np.empty(len(t), bool)
    first[0] = True
    first[1:] = t[1:] != t[:-1]
    starts = np.flatnonzero(first)
    ends = np.append(starts[1:], len(t)) - 1     # last vertex at each instant
    tk = np.repeat(t[starts], 2)
    vk = np.empty(starts.size * 2)
    vk[0::2] = v[starts]                         # arriving level
    vk[1::2] = v[ends]                           # leaving level
    out = np.interp(sample_min, tk, vk)
    # MView export convention: hold the first value back to t=0 (charts omit
    # the leading flatline), but leave samples after the data ends blank
    tol = sample_min[1] - sample_min[0] if len(sample_min) > 1 else 0.0
    out[sample_min < tk[0]] = vk[1]
    out[sample_min > tk[-1] + tol] = np.nan
    return out


def extract_page(page, meta=None, sample_sec=1.0):
    """Extract all series from one page. Returns (meta, sample_sec_array, {col: values})."""
    frame = _detect_frame(page)
    if frame is None:
        raise ValueError("no plot frame found on page")
    orient = _orientation(page, frame)
    if meta is None:
        meta = detect_meta(page, frame, orient)
    if meta.duration_min <= 0:
        raise ValueError("stage duration unknown (no time axis labels); set it manually")

    # Geometry for the Lab's synced "Compare Original" view. Most of this
    # template's pages are rotated -- time runs up the PDF y axis, the value
    # axes along x -- but the 2024 layout is unrotated, with time along x and
    # the value axes up y. The Lab wants t = ta + tb * coord, so invert
    # whichever sample mapping is used below and hand it the OTHER axis's
    # frame extent, far edge first. Taken from the detected frame itself, so
    # it lines up edge-to-edge rather than to the inset tick labels.
    D = meta.duration_min * 60.0
    if orient == "y":
        span, v0, v1 = frame.y1 - frame.y0, frame.x0, frame.x1
        base, sign = frame.y1, -1.0
    else:
        span, v0, v1 = frame.x1 - frame.x0, frame.y0, frame.y1
        base, sign = frame.x0, 1.0
    if span > 1e-9:
        meta.geom = {"axis": orient, "ta": float(-sign * D / span * base),
                     "tb": float(sign * D / span),
                     "v0": float(v0), "v1": float(v1)}

    fullscale = {"pressure": meta.pressure_max, "rate": meta.rate_max, "conc": meta.conc_max}
    series, blocks = detect_legend(page)
    if blocks is None:
        # no legend at all: fall back to the fixed colour table. A legend
        # that names only excluded curves (a Net Pressure page) is NOT a
        # fallback case -- falling back there is exactly how "Net Pressure
        # (MPa)", stroked in the same green as the wellhead concentration,
        # would be exported as a proppant concentration.
        series, known = SERIES, ()
    else:
        known = {rgb for block in blocks for rgb, _t, _c in block}
        if not series:
            raise ValueError(
                "no treatment channel in the page legend (%s)" % ", ".join(
                    _clean_label(t) for block in blocks for _r, t, _c in block))
    per_curve = _axes_by_curve(meta, blocks)
    unclaimed = []
    points = _collect_points(page, frame, series, unclaimed, known)
    for rgb in unclaimed:
        meta.warnings.append(
            "curve stroked in %s is in the plot but not in the legend, dropped"
            % (",".join(f"{c:.3g}" for c in rgb)))
    if not points:
        raise ValueError("no series curves found on page")

    n = int(round(meta.duration_min * 60 / sample_sec))
    samples = np.arange(n) * sample_sec
    sample_min = samples / 60.0

    data = {}
    # Each channel's axis full-scale. The Lab's ghost overlay needs it: the
    # printed curve is drawn against the chart's own axis, so normalising the
    # ghost to the channel's observed max would float it off the ink and make
    # a correctly-aligned chart look wrong.
    meta.scales = {}
    for color, arr in points.items():
        name, kind = series[color]
        fs = per_curve.get(name) or fullscale[kind]
        if fs <= 0:
            meta.warnings.append(f"{name}: axis scale unknown, channel skipped")
            continue
        meta.scales[name] = float(fs)
        if orient == "y":
            t = ((frame.y1 - arr[:, 1]) / (frame.y1 - frame.y0)
                 * meta.duration_min)
            v = (frame.x1 - arr[:, 0]) / (frame.x1 - frame.x0) * fs
        else:
            t = ((arr[:, 0] - frame.x0) / (frame.x1 - frame.x0)
                 * meta.duration_min)
            v = (frame.y1 - arr[:, 1]) / (frame.y1 - frame.y0) * fs
        order = np.argsort(t, kind="stable")
        data[name] = _resample(t[order], v[order], sample_min)
    return meta, samples, data


def write_csv(path, meta, samples, data, sample_sec=1.0):
    # fallback well past the epoch: pre-1970 local times crash .timestamp() on Windows
    start = datetime.strptime(f"{meta.date or '2000-01-01'} {meta.start_time}",
                              "%Y-%m-%d %H:%M:%S")
    epoch0 = start.timestamp()  # local-time epoch, matches MView exports
    cols = [c for c in COLUMNS if c in data] + \
           [c for c in data if c not in COLUMNS]   # auto-mode generic channels
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["UWI", "STAGE", "DATETIME", "ELAPSED", "TIMESTAMP", "LABEL"] + cols)
        w.writerow(["Units", "", "YYYY-mm-dd HH:MM:SS", "secs", "secs", ""] +
                   [UNITS.get(c, "") for c in cols])
        for i, s in enumerate(samples):
            dt = start + timedelta(seconds=float(s))
            row = [meta.uwi, meta.stage, dt.strftime("%Y-%m-%d %H:%M:%S"),
                   f"{s:.5f}", f"{epoch0 + s:.5f}", meta.stage]
            row += ["" if np.isnan(data[c][i]) else f"{data[c][i]:.5f}" for c in cols]
            w.writerow(row)
    return len(samples), cols
