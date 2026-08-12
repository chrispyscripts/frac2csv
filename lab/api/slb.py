"""Schlumberger (SLB) stimulation-report template.

Every file in the SLB corpus is an operator's BCER COMPLETION/WORKOVER
filing with a Schlumberger "Stimulation Service Report" bound into it —
SLB is the pressure pumper, the "Customer:" line names the operator
(Petronas, Ovintiv, Encana, Black Swan, Painted Pony, ARC).

The report prints its treatment curves on pages titled "PRC Plot", and
they are real vector polylines, not a raster:

  PRC Plot
  Customer: <operator>
  UWI: <the SLB report's own UWI - NOT to be trusted, see below>
  License: <NNNNN> // Interval <N>

  <value ticks>  <plot>  <value ticks>
                 <time ticks: h:mm AM/PM>
  <swatch> Treating Pressure  <swatch> Slurry Rate x 10  ...

Two vintages, both handled here:

  - per-interval: one PRC Plot per frac interval, the title line naming it
    ("// Interval 7"). 2019-2021, and the bulk of the corpus.
  - whole-job: a single PRC Plot spanning the entire job (30+ hours), no
    interval in the title. 2018-2021. The per-zone charts in those files are
    raster images, so this one page is their only vector time series; it is
    returned as one un-numbered block rather than split, because nothing on
    the page says where one zone ends and the next begins.

Both draw the same five curves in fixed colours — red Treating Pressure,
blue Slurry Rate, green Prop Con (wellhead), black BH Prop Con, dark-gold
friction reducer — but the colour table is NOT used: the page's own legend
is read, because the legend is also where the scale multiplier is printed
("Slurry Rate x 10" means the ink is ten times the real rate).

Two page orientations occur. Most are landscape with time along x; one
2020 vintage prints portrait with the whole chart rotated 90°. Everything
is mapped into one canonical frame (time along x) before any fitting.

DATA QUALITY — the printed UWI lies. In 39 of the 197 charted files the
"UWI:" line of the SLB report disagrees with the filing's own UWI, and on
pads like 00536/00537 and 00541/00543 the two neighbouring wells' reports
carry each other's UWI. Nothing here returns the printed UWI as the well's
identity; `extract_page` puts it in `meta.title` as reference text only and
leaves `meta.uwi` empty, so the caller's folder/filename UWI stands. (This
is the defect sanjel.py still has live — task #67.)

  - detect(page): a PRC Plot page.
  - extract_page(page, sample_sec): -> (meta, samples, {col: values},
    {col: unit}), the shape pipeline's per-page chart templates return.
  - find_summary_pages(doc): the report's table pages, grouped for viewing.
  - parse_zone_table(doc): the landscape per-zone treatment grid parsed to
    {columns, rows} — one row per zone.
"""
import re
from datetime import datetime, timedelta

import numpy as np

from frac_core import PageMeta, _resample

# ---------------------------------------------------------------- detection

PRC_TITLE = "PRC Plot"
ADDITIVES_TITLE = "Additives Plot"


def _head(page):
    for line in page.get_text().splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def detect(page):
    """True for an SLB "PRC Plot" treatment-curve page.

    The title alone is enough — no other template in the corpus prints it —
    but the Customer/License pair is checked too so that a table of contents
    naming the plot cannot be mistaken for one.
    """
    text = page.get_text()
    if _head(page) != PRC_TITLE:
        return False
    return ("Customer:" in text and re.search(r"^License:", text, re.M)
            is not None)


def is_additives_page(page):
    """True for the companion "Additives Plot" page. Not parsed — see the
    module docstring in parse notes; exposed so a caller can list it."""
    return _head(page) == ADDITIVES_TITLE and "Customer:" in page.get_text()


# ------------------------------------------------------- canonical geometry
#
# A rotated page draws every text line with dir=(0,-1). Mapping (x, y) ->
# (-y, x) puts time back along x and values along y, so one set of fitting
# code serves both vintages. The transform is its own documentation: a point
# that was low on a rotated page ends up left in canonical space.


def _rotated(page):
    vert = horiz = 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1, 0))
            n = len(line.get("spans", []))
            if abs(dy) > abs(dx):
                vert += n
            else:
                horiz += n
    return vert > horiz and vert >= 3


def _pt(rot, x, y):
    return (-y, x) if rot else (x, y)


def _box(rot, bbox):
    """A bbox in canonical orientation, as (x0, y0, x1, y1) normalised."""
    x0, y0, x1, y1 = bbox
    ax, ay = _pt(rot, x0, y0)
    bx, by = _pt(rot, x1, y1)
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def _spans(page, rot):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = _box(rot, span["bbox"])
                out.append({"t": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                            "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def _near_black(color):
    return color is not None and max(color) <= 0.15


def _frame(page, rot):
    """The plot rectangle, in canonical coordinates.

    It is the one near-black stroked path that encloses most of the page;
    the gridlines are pale grey and the tick marks are 3pt stubs, so neither
    can win on area. Some vintages stroke the frame as a single "re" item
    and some as four lines, hence the loose item count.
    """
    best, best_area = None, 0.0
    pw, ph = page.rect.width, page.rect.height
    for d in page.get_drawings():
        if d["type"] != "s" or not _near_black(d.get("color")):
            continue
        if len(d["items"]) > 8:
            continue
        r = d["rect"]
        if (r.x1 - r.x0) < 0.40 * pw or (r.y1 - r.y0) < 0.30 * ph:
            continue
        area = (r.x1 - r.x0) * (r.y1 - r.y0)
        if area > best_area:
            best_area, best = area, _box(rot, (r.x0, r.y0, r.x1, r.y1))
    return best


# ------------------------------------------------------------- the time axis

_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)?$", re.I)


def _clock_minutes(text):
    m = _CLOCK.match(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    sec = int(m.group(3) or 0)
    ampm = (m.group(4) or "").upper()
    if ampm:
        if h > 12 or h < 1 or mi > 59:
            return None
        h = h % 12 + (12 if ampm == "PM" else 0)
    elif h > 23 or mi > 59:
        return None
    return h * 60 + mi + sec / 60.0


def _time_axis(spans, frame):
    """-> (a, b, first_clock_minutes) for minutes = a + b*x, or None.

    The labels sit just outside the plot on the value-low side and read
    h:mm AM/PM. A job that crosses midnight prints 11:57 PM then 12:01 AM,
    so the sequence is unwrapped by adding a day each time it steps back
    rather than fitted as-is — fitted as-is a 40-minute stage came out
    running backwards for 23 hours.
    """
    pts = []
    for s in spans:
        if not (frame[1] - 30 <= s["cy"] <= frame[3] + 40):
            continue
        if frame[1] - 2 <= s["cy"] <= frame[3] + 2:
            continue                       # inside the plot: an annotation
        mins = _clock_minutes(s["t"])
        if mins is None:
            continue
        if not (frame[0] - 25 <= s["cx"] <= frame[2] + 25):
            continue
        pts.append((s["cx"], mins))
    if len(pts) < 3:
        return None
    pts.sort()
    xs = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    day = 0.0
    unwrapped = [vals[0]]
    for prev, cur in zip(vals, vals[1:]):
        if cur + day < unwrapped[-1] - 1.0:
            day += 1440.0
        unwrapped.append(cur + day)
    A = np.vstack([np.ones(len(xs)), np.asarray(xs, float)]).T
    (a, b), *_ = np.linalg.lstsq(A, np.asarray(unwrapped, float), rcond=None)
    if abs(b) < 1e-9:
        return None
    return float(a), float(b), vals[0]


# ------------------------------------------------------------ the value axes

_NUMTICK = re.compile(r"^-?\d{1,6}(?:\.\d+)?$")


def _value_axes(spans, frame):
    """-> [{'side', 'key', 'fit': (a, b), 'ticks': [...], 'title': str}].

    Tick labels are clustered on whichever edge of their box faces the plot
    — the columns are right-aligned to the left of the plot and left-aligned
    to the right of it, so the far edge wanders with the digit count and only
    the near edge is a straight line to cluster on.
    """
    cands = []
    for s in spans:
        if not _NUMTICK.match(s["t"]):
            continue
        if not (frame[1] - 20 <= s["cy"] <= frame[3] + 20):
            continue
        if s["cx"] < frame[0]:
            cands.append(("left", s["x1"], s))
        elif s["cx"] > frame[2]:
            cands.append(("right", s["x0"], s))
    groups = {}
    for side, key, s in cands:
        hit = next((k for (sd, k) in groups
                    if sd == side and abs(k - key) < 6), None)
        groups.setdefault((side, hit if hit is not None else key),
                          []).append(s)
    axes = []
    for (side, key), items in groups.items():
        if len(items) < 3:
            continue
        ys = np.array([s["cy"] for s in items], float)
        vs = np.array([float(s["t"]) for s in items], float)
        A = np.vstack([np.ones_like(ys), ys]).T
        (a, b), *_ = np.linalg.lstsq(A, vs, rcond=None)
        if abs(b) < 1e-9:
            continue
        resid = float(np.max(np.abs(a + b * ys - vs)))
        span = float(vs.max() - vs.min())
        if span <= 0 or resid > 0.02 * span:
            continue                       # not a linear tick column
        axes.append({"side": side, "key": key, "fit": (float(a), float(b)),
                     "lo": float(vs.min()), "hi": float(vs.max()),
                     "title": ""})
    # each column's axis title is the nearest non-numeric text further out
    for ax in axes:
        best, bestd = "", 1e9
        for s in spans:
            if _NUMTICK.match(s["t"]) or _CLOCK.match(s["t"]):
                continue
            if "(" not in s["t"]:
                continue
            if ax["side"] == "left":
                if s["cx"] >= ax["key"]:
                    continue
                d = ax["key"] - s["cx"]
            else:
                if s["cx"] <= ax["key"]:
                    continue
                d = s["cx"] - ax["key"]
            if d < bestd:
                bestd, best = d, s["t"]
        ax["title"] = best
    return axes


# ---------------------------------------------------------------- the legend

_SWATCH_MIN, _SWATCH_MAX = 12.0, 60.0


def _legend(page, rot, frame, spans):
    """-> [(rgb, label)] read off the page's own key.

    A key is a short single-segment stroke below the plot; its label is the
    next text to its right on the same line. Colour tables are deliberately
    not used: the SLB legend is also where the scale multiplier is printed,
    so the label has to be read anyway and reading it settles the colour too.
    """
    out = []
    for d in page.get_drawings():
        if d["type"] != "s" or len(d["items"]) != 1:
            continue
        color = d.get("color")
        if color is None:
            continue
        r = d["rect"]
        x0, y0, x1, y1 = _box(rot, (r.x0, r.y0, r.x1, r.y1))
        if not (_SWATCH_MIN <= (x1 - x0) <= _SWATCH_MAX):
            continue
        if (y1 - y0) > 3:
            continue
        cy = (y0 + y1) / 2
        if cy <= frame[3] + 2:
            continue                       # inside or above the plot
        label, bestd = "", 1e9
        for s in spans:
            if abs(s["cy"] - cy) > 12:
                continue
            if s["x0"] < x1 - 3:
                continue
            d2 = s["x0"] - x1
            if d2 < bestd and d2 < 90:
                bestd, label = d2, s["t"]
        if label:
            out.append((tuple(round(c, 3) for c in color), label))
    return out


# ------------------------------------------------------------- curve naming

_MULT = re.compile(r"\s*[x*X]\s*(\d+(?:\.\d+)?)\s*$")

# printed legend text -> (canonical column, axis kind). Matched on a
# lower-cased, multiplier-stripped label.
_NAMES = [
    ("treating pressure", "Tr Press", "pressure"),
    ("gorv pressure", "GORV Press", "pressure"),
    ("gorv", "GORV Press", "pressure"),
    ("slurry rate", "Slurry Rate", "rate"),
    ("injection rate", "Slurry Rate", "rate"),
    ("bh prop con", "BH Prop Conc", "conc"),
    ("prop con", "WH Prop Conc", "conc"),
]

_UNITS = {"Tr Press": "MPa", "GORV Press": "MPa", "Slurry Rate": "m3/min",
          "WH Prop Conc": "Kg/m3", "BH Prop Conc": "Kg/m3"}


def _split_multiplier(label):
    """'Slurry Rate x 10' -> ('Slurry Rate', 10.0)."""
    m = _MULT.search(label)
    if not m:
        return label.strip(), 1.0
    try:
        f = float(m.group(1))
    except ValueError:
        return label.strip(), 1.0
    if f <= 0:
        return label.strip(), 1.0
    return label[:m.start()].strip(), f


def _classify(label):
    """-> (column, kind, multiplier) for a legend label, or None.

    Unrecognised labels are dropped rather than guessed at. The friction
    reducer and the dry-CMC traces have no canonical column and no way to
    tell which of the two axes they read against, so naming them would be
    inventing numbers; they are reported as skipped instead.
    """
    base, mult = _split_multiplier(label)
    low = base.lower().replace("_", " ")
    for key, col, kind in _NAMES:
        if key in low:
            return col, kind, mult
    return None


def _axis_multiplier(title, kind):
    """The 'x 10' some vintages print on the shared axis title instead of on
    the legend entry: "Pressure (MPa) / Rate (m3/min) x 10". It trails the
    rate half of the title, so it scales the rate curve and nothing else."""
    if kind != "rate":
        return 1.0
    m = _MULT.search(title or "")
    if not m or not re.search(r"rate", title, re.I):
        return 1.0
    try:
        f = float(m.group(1))
    except ValueError:
        return 1.0
    return f if f > 0 else 1.0


def _pick_axis(axes, kind):
    """Which tick column a curve of this kind reads against.

    The report normally names both axes — "Prop Con (kgPA)" against
    "Pressure (MPa) / Rate (m3/min)" — and the title is the first and best
    signal. But 43 pages print the concentration axis with no title at all,
    and matching only on "prop con" left those pages with no concentration
    axis and dropped every curve onto whichever column came first: 00490's
    interval 6 reported a treating pressure of 937 MPa off the 0-1000 kgPA
    ticks. So the identification runs the other way too — a column titled
    for pressure or rate is definitively NOT the concentration one — and
    only when neither axis is titled does it fall back to scale, where the
    concentration axis (hundreds of kg/m³) always tops the pressure/rate
    axis (about a hundred MPa) by an order of magnitude.
    """
    if not axes:
        return None
    axes = sorted(axes, key=lambda a: (a["side"], a["key"]))
    conc = [a for a in axes if re.search(r"prop\s*con", a["title"], re.I)]
    value = [a for a in axes
             if re.search(r"pressure|rate", a["title"], re.I) and a not in conc]
    if not conc and value:
        conc = [a for a in axes if a not in value]
    if not conc and not value and len(axes) > 1:
        by_scale = sorted(axes, key=lambda a: a["hi"])
        value, conc = by_scale[:1], by_scale[-1:]
    if kind == "conc":
        return (conc or value or axes)[0]
    return (value or conc or axes)[0]


# ---------------------------------------------------------------- the curves


def _curves(page, rot, frame, colors):
    """{rgb: Nx2 canonical points} for the stroked polylines in the plot.

    Colour cannot tell a curve from the furniture — the bottom-hole
    concentration trace is stroked in the same pure black as the frame and
    the tick marks, and a colour rule dropped it from every page. Vertex
    count cannot do it alone either: the 62 tick stubs down one axis are
    emitted as a single 62-item path, and taken as a curve it read as a
    trace sweeping the axis from 0 to full scale, which is how 00598's
    bottom-hole concentration came back peaking at 999 kg/m³ against a
    printed 335. So a curve must also RUN somewhere: its own bounding box
    has to cover a real share of the plot along the time axis, which a
    column of tick stubs three points wide never does.
    """
    out = {}
    span_min = 0.20 * (frame[2] - frame[0])
    for d in page.get_drawings():
        if d["type"] != "s" or len(d["items"]) < 50:
            continue
        color = d.get("color")
        if color is None:
            continue
        r = d["rect"]
        bx0, _by0, bx1, _by1 = _box(rot, (r.x0, r.y0, r.x1, r.y1))
        if (bx1 - bx0) < span_min:
            continue
        key = tuple(round(c, 3) for c in color)
        if colors and key not in colors:
            continue
        pts = out.setdefault(key, [])
        for item in d["items"]:
            if item[0] == "l":
                pts.append(_pt(rot, item[1].x, item[1].y))
                pts.append(_pt(rot, item[2].x, item[2].y))
            elif item[0] == "c":
                pts.append(_pt(rot, item[1].x, item[1].y))
                pts.append(_pt(rot, item[4].x, item[4].y))
    clipped = {}
    pad = 1.5
    for key, pts in out.items():
        if not pts:
            continue
        arr = np.asarray(pts, float)
        keep = ((arr[:, 0] >= frame[0] - pad) & (arr[:, 0] <= frame[2] + pad) &
                (arr[:, 1] >= frame[1] - pad) & (arr[:, 1] <= frame[3] + pad))
        arr = arr[keep]
        if len(arr) >= 10:
            clipped[key] = arr
    return clipped


# ------------------------------------------------------------------ metadata

_LICENSE = re.compile(r"^License:.*$", re.M)
_INTERVAL = re.compile(r"Interval\s*(\d+)\s*(.*)$")
_UWI_LINE = re.compile(r"^UWI:\s*(\S+)", re.M)
_CUSTOMER = re.compile(r"^Customer:\s*(.+?)\s*$", re.M)


def page_stage(page):
    """The interval this PRC page charts, as printed, or None for a
    whole-job plot.

    Read off the License line, but without requiring a licence number to be
    there: 171 pages print "License:  // Interval 1" with the number blank,
    and a pattern that insisted on one called every one of them a whole-job
    plot — which then suppressed the stage on a page that names it plainly.

    The suffix the report writes after the number is part of the label, not
    noise. An interval that was flushed or re-treated gets its own plot
    titled "Interval 12 FLUSH A", "... FLUSH B", "... FLUSH C"; reduced to a
    bare "12" all four pages claim the same stage, and 221 pages across 88
    files would have piled onto a stage already occupied — 00206's interval
    12 charts four separate runs. Keeping the printed suffix keeps them
    four stages, in the same style as CalFrac's "9A" / "12 Attempt 2".
    """
    m = _LICENSE.search(page.get_text())
    if not m:
        return None
    n = _INTERVAL.search(m.group(0))
    if not n:
        return None
    suffix = re.sub(r"\s+", " ", n.group(2)).strip(" /-")
    return f"{n.group(1)} {suffix}".strip() if suffix else n.group(1)


# ---------------------------------------------------------------- extraction


def extract_page(page, sample_sec=1.0):
    """One PRC Plot page -> (meta, samples, {col: values}, {col: unit}).

    `samples` is the elapsed-minute grid the values are sampled on, the same
    contract bj1/lib1/halliburton_ifs return.
    """
    rot = _rotated(page)
    frame = _frame(page, rot)
    if frame is None:
        raise ValueError("slb: no plot frame on page")
    spans = _spans(page, rot)
    tfit = _time_axis(spans, frame)
    if tfit is None:
        # 37 pages in the corpus stroke their curves but print no time axis,
        # no legend and no second axis — the plot overflows to x=-809 on
        # 00228's, so the page itself is malformed, not the reading of it.
        # Nothing on such a page says what the curves are or when they ran.
        raise ValueError(
            "slb: page prints no time-axis labels — the plot is incomplete "
            "in the source PDF and its curves cannot be placed in time")
    ta, tb, first_clock = tfit
    axes = _value_axes(spans, frame)
    if not axes:
        raise ValueError("slb: no value axis found")

    legend = _legend(page, rot, frame, spans)
    wanted, skipped = {}, []
    for rgb, label in legend:
        hit = _classify(label)
        if hit is None:
            skipped.append(label)
            continue
        col, kind, mult = hit
        if col in [v[0] for v in wanted.values()]:
            continue                        # a colour already claimed it
        wanted[rgb] = (col, kind, mult, label)

    curves = _curves(page, rot, frame, set(wanted))
    text = page.get_text()

    data, units, labels = {}, {}, {}
    tmin_all, tmax_all = None, None
    for rgb, arr in curves.items():
        col, kind, mult, label = wanted[rgb]
        ax = _pick_axis(axes, kind)
        if ax is None:
            continue
        mult = mult * _axis_multiplier(ax["title"], kind)
        a, b = ax["fit"]
        t = ta + tb * arr[:, 0]
        v = (a + b * arr[:, 1]) / mult
        order = np.argsort(t, kind="stable")
        t, v = t[order], v[order]
        data[col] = (t, v)
        units[col] = _UNITS.get(col, "")
        labels[col] = label
        tmin_all = t[0] if tmin_all is None else min(tmin_all, t[0])
        tmax_all = t[-1] if tmax_all is None else max(tmax_all, t[-1])

    if not data:
        raise ValueError("slb: no legended curves found on page")

    step = sample_sec / 60.0
    n = max(2, int(round((tmax_all - tmin_all) / step)) + 1)
    grid = tmin_all + step * np.arange(n)
    out = {}
    for col, (t, v) in data.items():
        out[col] = _resample(t - tmin_all, v, grid - tmin_all)
    samples = grid - tmin_all

    start = timedelta(minutes=float(tmin_all) % 1440.0)
    meta = PageMeta()
    meta.stage = page_stage(page) or ""
    meta.start_time = str(start).split(".")[0].rjust(8, "0")
    meta.duration_min = float(tmax_all - tmin_all)
    # The report's own UWI line is kept as reference text only. It is wrong
    # often enough — and wrong by carrying a neighbouring well's UWI, not by
    # being blank — that letting it reach meta.uwi would relabel whole wells.
    printed = _UWI_LINE.search(text)
    cust = _CUSTOMER.search(text)
    bits = [PRC_TITLE]
    if meta.stage:
        bits.append(f"Interval {meta.stage}")
    if cust:
        bits.append(cust.group(1))
    if printed:
        bits.append(f"report UWI {printed.group(1)}")
    meta.title = " — ".join(bits)
    meta.uwi = ""
    if skipped:
        meta.warnings.append(
            "curve(s) not named by this template, left unextracted: "
            + ", ".join(sorted(set(skipped))))
    if not meta.stage:
        meta.warnings.append(
            "whole-job PRC plot: this page charts the entire treatment and "
            "names no interval, so it is not split into stages")
    return meta, samples, out, units


# ------------------------------------------------------ summary table pages

SUMMARY_KINDS = [
    ("cover", r"^Horizontal .*Stimulation Summary|^Vertical .*Stimulation Summary"),
    ("welldata", r"^Perforation Data$|^Pipe Data$"),
    ("pumping", r"^\d+ Stage Pumping Summary$"),
    ("joblog", None),
    ("zonetable", None),
    ("materials", r"^Stage-by-Stage Materials Summary$"),
    ("zonesummary", r"^Zone \d+ Summary$"),
    ("intervalsummary", r"^Interval \d+ Summary$"),
]
KIND_TITLES = {
    "cover": "Stimulation Summary (cover)",
    "welldata": "Well / Pipe / Perforation Data",
    "pumping": "Stage Pumping Summary",
    "joblog": "Job log (DATE / TIME / TR PRESS / ... / REMARKS)",
    "zonetable": "Per-zone treatment summary",
    "materials": "Stage-by-Stage Materials Summary",
    "zonesummary": "Zone summaries",
    "intervalsummary": "Interval summaries",
}

_JOBLOG = re.compile(r"TR\s*\n?\s*PRESS")
_ZONETABLE = re.compile(r"Interval Length")


# These two sheets print their own title, but the PDF text stream orders the
# page by drawing order, not by layout, so the title lands wherever it was
# stroked — halfway down a 90-line page on a 2020 Encana file. Matching them
# on the first few lines like the other kinds found none of them and left
# those documents with an empty Summary tab.
_TITLED_ANYWHERE = [("zonesummary", re.compile(r"^Zone \d+ Summary$", re.M)),
                    ("intervalsummary",
                     re.compile(r"^Interval \d+ Summary$", re.M))]


def _page_kind(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if _JOBLOG.search(text) and "REMARKS" in text and "DATE" in lines:
        return "joblog"
    if _ZONETABLE.search(text) and "Zone" in lines and "Port Open" in lines:
        return "zonetable"
    for kind, pat in _TITLED_ANYWHERE:
        if pat.search(text):
            return kind
    for kind, pat in SUMMARY_KINDS:
        if pat is None:
            continue
        for line in lines[:6]:
            if re.search(pat, line):
                return kind
    return None


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — the SLB report's table pages, one
    entry per section kind, in the order the sections first appear.

    The other templates group by page adjacency, which suits a report whose
    sections are contiguous. SLB's are not: it prints a summary sheet, a job
    log, then the stage's two chart pages, then the next stage's summary
    sheet, all the way down. Adjacency never merged any of it — a 36-stage
    Petronas well produced 36 separate one-page "cover" entries and the
    corpus produced 2975 one-page "Interval summaries" — so the kind itself
    is the group and its `pages` list carries the order.
    """
    groups, by_kind = [], {}
    for p in range(doc.page_count):
        try:
            text = doc[p].get_text()
        except Exception:
            continue
        kind = _page_kind(text)
        if kind is None:
            continue
        g = by_kind.get(kind)
        if g is None:
            g = {"kind": kind, "title": KIND_TITLES.get(kind, kind),
                 "pages": []}
            by_kind[kind] = g
            groups.append(g)
        g["pages"].append(p + 1)
    return groups


# ------------------------------------------------------- the per-zone table
#
# The landscape grid the whole-job vintage prints once per well. Its column
# set is what makes these reports worth reading as tables: nothing else in
# the corpus prints a minimum slurry rate, a ball size or an interval length
# per stage.

ZONE_COLUMNS = [
    ("Zone", ""),
    ("Fluid", ""),
    ("Port Open Pressure", "MPa"),
    ("Breakdown Pressure", "MPa"),
    ("Average Pressure", "MPa"),
    ("Maximum Pressure", "MPa"),
    ("Minimum Pressure", "MPa"),
    ("Average Slurry Rate", "m3/min"),
    ("Maximum Slurry Rate", "m3/min"),
    ("Minimum Slurry Rate", "m3/min"),
    ("Maximum Prop Con", "kgPA"),
    ("Frac Port", "m"),
    ("Ball Size", "in"),
    ("Interval Length", "m"),
]


def is_zone_table_page(page):
    return _page_kind(page.get_text()) == "zonetable"


def _rows_by_y(page, tol=3.0):
    """spans grouped into printed rows -> [(y, [(x, text)])]."""
    runs = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                runs.append(((y0 + y1) / 2, x0, t))
    rows = {}
    for y, x, t in sorted(runs):
        key = next((k for k in rows if abs(k - y) < tol), y)
        rows.setdefault(key, []).append((x, t))
    return [(y, sorted(v)) for y, v in sorted(rows.items())]


_ZONE_LABEL = re.compile(r"^\d{1,2}$")
_ZONE_VALUE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


def parse_zone_table(doc):
    """-> {columns, rows} for the per-zone treatment grid, or None.

    Read positionally against the header's own column anchors rather than by
    counting cells: a zone that was not ball-dropped prints no ball size and
    no interval length, and a row read by position keeps the blanks in the
    right columns instead of shifting every later value one place left.
    """
    pno = next((p for p in range(doc.page_count)
                if is_zone_table_page(doc[p])), None)
    if pno is None:
        return None
    rows = [(0, y, cells) for y, cells in _rows_by_y(doc[pno])]
    # A well with more zones than fit on one sheet runs on to the next page,
    # and that page does NOT repeat the header. Reading only the headed page
    # silently truncated eight wells — 00036 returned 37 zones of the 42 its
    # own cover states, with zones 38-42 sitting unread on the next page.
    #
    # The test for "is this the rest of my table" is that the zone numbers
    # CONTINUE, not merely that the page has zone-numbered rows. The
    # Stage-by-Stage Materials Summary that follows is also a zone-per-row
    # landscape grid and also prints its title too low on the page to be
    # caught by a first-lines match, so an adjacency-only rule appended it
    # whole and every well came back with about twice the zones it has.
    seen_max = max((int(cells[0][1]) for _y, cells in _rows_by_y(doc[pno])
                    if len(cells) >= 6 and _ZONE_LABEL.match(cells[0][1])),
                   default=0)
    for nxt in range(pno + 1, min(pno + 4, doc.page_count)):
        cont = doc[nxt]
        if _page_kind(cont.get_text()) is not None:
            break                            # a new titled section
        crows = _rows_by_y(cont)
        zs = [int(cells[0][1]) for _y, cells in crows
              if len(cells) >= 6 and _ZONE_LABEL.match(cells[0][1])]
        if not zs or min(zs) != seen_max + 1:
            break
        rows += [(nxt - pno, y, cells) for y, cells in crows]
        seen_max = max(zs)

    # The header is printed over three stacked lines ("Average" / "Slurry
    # Rate" / "(m3/min)"); its anchor row is the one carrying "Zone".
    hy = next((y for pg, y, cells in rows
               if pg == 0 and any(t == "Zone" for _x, t in cells)), None)
    if hy is None:
        return None

    # data rows: any row led by a bare zone number. The header-clearance test
    # applies only to the headed page — a continuation page starts its rows at
    # the same height the header sat at, so applying it there would discard
    # exactly the rows the continuation exists to carry.
    data_rows = []
    for pg, y, cells in rows:
        if len(cells) < 4:
            continue
        if pg == 0 and y <= hy + 6:
            continue
        if not _ZONE_LABEL.match(cells[0][1]) and cells[0][1] != "Total":
            continue
        data_rows.append((y, cells))
    if len(data_rows) < 2:
        return None

    # Column anchors come from the data itself: every zone row lays its cells
    # on the same x grid, so clustering the numeric cells' left edges over
    # all rows recovers the grid even where a row has gaps.
    xs = sorted(x for _y, cells in data_rows for x, t in cells[1:]
                if _ZONE_VALUE.match(t.replace(",", "")))
    anchors = []
    for x in xs:
        if not anchors or x - anchors[-1][0] > 9:
            anchors.append([x, 1])
        else:
            a = anchors[-1]
            a[0] = (a[0] * a[1] + x) / (a[1] + 1)
            a[1] += 1
    anchors = [a for a, n in anchors if n >= max(2, len(data_rows) // 3)]
    if len(anchors) < 8:
        return None

    def col_of(x):
        i = min(range(len(anchors)), key=lambda i: abs(anchors[i] - x))
        return i if abs(anchors[i] - x) < 14 else None

    out_rows = []
    for _y, cells in data_rows:
        row = [cells[0][1]] + [None] * (len(anchors) + 1)
        for x, t in cells[1:]:
            clean = t.replace(",", "")
            ci = col_of(x)
            if _ZONE_VALUE.match(clean):
                if ci is not None and row[ci + 2] is None:
                    row[ci + 2] = clean
            elif row[1] is None and ci is None:
                row[1] = t                  # the fluid name
            elif ci is not None and row[ci + 2] is None:
                # A word in a numeric column is still that column's value:
                # the toe stage prints "TOE" where the others print a port-
                # open pressure and "Hyd." where they print a ball size.
                # Dropped as non-numeric, zone 1 lost the one field that says
                # how it was opened.
                row[ci + 2] = t
        out_rows.append(row)

    names = [c for c, _u in ZONE_COLUMNS]
    units = {c: u for c, u in ZONE_COLUMNS}
    width = len(anchors) + 2
    if width <= len(names):
        cols = names[:width]
    else:
        cols = names + [f"col{i}" for i in range(len(names) + 1, width + 1)]
    columns = [c + (f" ({units[c]})" if units.get(c) else "") for c in cols]
    out_rows = [r[:len(columns)] for r in out_rows]
    return {"columns": columns, "rows": out_rows}


# --------------------------------------------------- the per-interval sheets
#
# The per-interval vintage prints one "Interval N Summary" sheet per stage
# instead of one grid per well. The sheet is a set of small labelled blocks,
# and the text stream comes out of the PDF in an order that has nothing to do
# with the printed layout, so every value is taken by position: the number on
# the label's own printed row, in the label's own block.

# (column name, unit, printed label, block) — block "p" is the PRESSURES
# panel, "r" the RATES panel, "x" a standalone label with one value.
_IS_FIELDS = [
    ("Start Time", "", "START TIME", "x"),
    ("End Time", "", "END TIME", "x"),
    ("Displacement Volume", "m3", "DISP VOL (m3)", "x"),
    ("Open Well Pressure", "MPa", "OPEN WELL", "p"),
    ("Breakdown Pressure", "MPa", "BREAKDOWN", "p"),
    ("Average Pressure", "MPa", "AVERAGE", "p"),
    ("Maximum Pressure", "MPa", "MAXIMUM", "p"),
    ("Minimum Pressure", "MPa", "MINIMUM", "p"),
    ("Post-Frac ISIP", "MPa", "POST-FRAC ISIP", "p"),
    ("1 Min ISIP", "MPa", "1 MIN ISIP", "p"),
    ("Frac Gradient", "kPa/m", "FRAC GRADIENT (kPa/m)", "p"),
    ("Ball Seat Pressure", "MPa", "BALL SEAT PRESSURE", "p"),
    ("Average Clean Rate", "m3/min", "AVERAGE", "r"),
    ("Maximum Clean Rate", "m3/min", "MAXIMUM", "r"),
    ("Minimum Clean Rate", "m3/min", "MINIMUM", "r"),
    ("Average Slurry Rate", "m3/min", "AVERAGE", "r2"),
    ("Maximum Slurry Rate", "m3/min", "MAXIMUM", "r2"),
    ("Minimum Slurry Rate", "m3/min", "MINIMUM", "r2"),
    ("Horsepower", "kW", "HORSEPOWER (kW)", "x"),
]

_TIMEVAL = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M$", re.I)


def _interval_no(page):
    """The label for an Interval Summary sheet, or None if it is not one.

    The sheet is identified by its printed title but LABELLED off the same
    License line the chart pages use, so a stage's table row and its chart
    carry the same label. Taken from the title, a re-treat sheet titled
    "Interval 12 FLUSH A Summary" was invisible, and 27 wells produced two
    rows both claiming interval 12 with nothing to tell them apart.
    """
    title = re.search(r"^Interval (\S+.*?) Summary$", page.get_text(), re.M)
    if not title:
        return None
    label = page_stage(page)
    if label:
        return label
    # Eight sheets across six wells were printed with the License line's
    # placeholder still in it — "License: 038557 // Interval XX" — while the
    # sheet's own title names the interval correctly. Take the title there.
    m = re.match(r"\d+", title.group(1))
    return re.sub(r"\s+", " ", title.group(1)).strip() if m else None


def is_interval_summary_page(page):
    return _interval_no(page) is not None


def _parse_interval_page(page):
    """One Interval N Summary sheet -> {column: value}."""
    rows = _rows_by_y(page)
    rates_x = None
    for _y, cells in rows:
        for x, t in cells:
            if t.startswith("RATES"):
                rates_x = x
    got = {}
    for _y, cells in rows:
        for i, (lx, lt) in enumerate(cells):
            for name, _unit, label, block in _IS_FIELDS:
                if lt != label or name in got:
                    continue
                right = [(x, t) for x, t in cells if x > lx + 2]
                if block == "p" and rates_x is not None:
                    right = [(x, t) for x, t in right if x < rates_x - 20]
                elif block in ("r", "r2"):
                    if rates_x is None or lx < rates_x - 20:
                        continue
                nums = [(x, t) for x, t in right
                        if _ZONE_VALUE.match(t.replace(",", ""))
                        or _TIMEVAL.match(t)]
                if not nums:
                    continue
                # the RATES panel prints CLEAN then SLURRY on one row
                pick = nums[1] if block == "r2" and len(nums) > 1 else nums[0]
                if block == "r" and len(nums) < 2:
                    # only one number printed: it is the clean column
                    pass
                got[name] = pick[1].replace(",", "")
    return got


def parse_interval_summaries(doc):
    """-> {columns, rows}, one row per interval, or None.

    Only the fixed labelled scalars are taken. The proppant, fluid-stage and
    additive blocks on the same sheet are variable-width tables whose columns
    change job to job (product codes, mesh sizes), and folding them into a
    fixed grid would put one job's 30/50 sand under another job's 40/70; they
    are left for the page view instead.
    """
    rows, order = [], []
    for p in range(doc.page_count):
        page = doc[p]
        n = _interval_no(page)
        if n is None:
            continue
        vals = _parse_interval_page(page)
        if not vals:
            continue
        rows.append((n, vals))
        for k in vals:
            if k not in order:
                order.append(k)
    # One row is a table. The usual "at least two rows or it is a false
    # positive" guard does not apply here — the sheet announces itself by
    # title — and it threw away five single-interval wells outright.
    if not rows:
        return None
    rows.sort(key=lambda r: (int(re.match(r"\d+", r[0]).group(0)), r[0]))
    names = [c for c, _u, _l, _b in _IS_FIELDS if c in order]
    units = {c: u for c, u, _l, _b in _IS_FIELDS}
    columns = ["Interval"] + [c + (f" ({units[c]})" if units.get(c) else "")
                              for c in names]
    out = [[n] + [v.get(c) for c in names] for n, v in rows]
    return {"columns": columns, "rows": out}
