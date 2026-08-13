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

Two vintages, and the SECOND OF THEM IS MIXED INSIDE ONE DOCUMENT:

  - per-interval: one PRC Plot per frac interval, the title line naming it
    ("// Interval 7"). 2019-2021, 150 files, vector from end to end.
  - whole-job: 47 files whose only PRC Plot spans the entire job (30+
    hours) and names no interval. That page is not what the report offers
    per stage. The SAME document prints a "Zone N Summary" sheet per zone,
    and each of those sheets carries that zone's own chart as a 1572x1033
    RASTER image. On 00023, 30 raster sheets against 4 pages in the whole
    109 that carry any long vector path at all.

    So the branch here is PER PAGE, not per file: `page_chart_kind` decides
    vector-or-raster from what the page is made of, and a document is free
    to hold both. The whole-job plot is dropped — the client's own reading
    of it is that "all of the data necessary should be available in
    individual charts" — and the per-zone sheets are traced instead.

    Which zone a sheet belongs to is read from the page's VECTOR TEXT, so
    labelling needs no OCR; only the curve tracing does. Both shipping
    runtimes (the Windows EXE and the local Mac app) carry tesseract.

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

  - page_chart_kind(page): 'vector' | 'raster' | None — what this ONE page
    carries. Structural, not keyed on print wording.
  - page_source(page): the provider label the page's chart is filed under.
    The raster one says "(raster)", which is what makes the Lab tag it IMAGE.
  - detect(page): a page this template extracts, of either kind.
  - detect_document(doc): the PDF carries an SLB report at all — the gate
    the TABLES belong on, since a blank plot must not suppress them.
  - extract_page(page, sample_sec): -> (meta, samples, {col: values},
    {col: unit}), the shape pipeline's per-page chart templates return.
  - extract_page_blocks(page, sample_sec): the same, as a LIST. One entry
    for a per-interval vector plot or a per-zone raster sheet; EMPTY for a
    whole-job plot, which this template no longer exports.
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
    """The page's first printed line, with runs of whitespace collapsed.

    The collapse is not cosmetic. This report prints its titles with
    NO-BREAK SPACE (U+00A0) between the words on some vintages, and a
    comparison against a literal " " then fails on pages that print exactly
    the expected title — the defect that cost another template in this tree
    143 pages. Nothing downstream cares which space character was used.
    """
    for line in page.get_text().splitlines():
        s = re.sub(r"\s+", " ", line).strip()
        if s:
            return s
    return ""


def detect_prc(page):
    """True for an SLB "PRC Plot" treatment-curve page — the VECTOR kind.

    The title alone is enough — no other template in the corpus prints it —
    but the Customer/License pair is checked too so that a table of contents
    naming the plot cannot be mistaken for one.
    """
    text = page.get_text()
    if _head(page) != PRC_TITLE:
        return False
    return ("Customer:" in text and re.search(r"^License:", text, re.M)
            is not None)


# ------------------------------------------------- per-page classification
#
# A whole-job document is NOT "a raster document". 00023 is 109 pages: four
# of them carry a vector path long enough to be a plotted curve (two schematic
# sheets and the whole-job PRC pair at the end) and thirty carry a per-zone
# chart as an embedded image. Deciding vector-or-raster once for the file gets
# one of those two groups wrong whichever way it is decided, so the decision is
# made per page, from what the page is made of.
#
# The tests below are on STRUCTURE — how long the stroked paths are, how big
# the embedded image is and how much of the page it covers. The one thing read
# out of the text is the zone number, and that is not detection: it is the
# stage label, which has to be read anyway and is a printed number the report
# stakes its own tables on.

# A plotted curve is thousands of segments; a table rule or a tick column is
# tens. 200 is far above the furniture (473 on 00023's busiest schematic) and
# far below a real trace (39,441 on its Additives plot).
_PLOT_PATH_ITEMS = 200
_PLOT_PATH_FRAC = (0.40, 0.25)      # of page width, height

# The per-zone charts render at 1530-1572 x 1027-1033 px across all 47 files
# and are placed about 513 x 292 pt on a 612 x 792 page. The floors are set
# well under that so a different render still qualifies, and well over the
# report's letterhead logo (199 x 42) and its inline icons.
_CHART_IMG_PX = (600, 400)
_CHART_IMG_FRAC = (0.30, 0.15)

# "Zone 12 Summary". Whitespace-tolerant for the same reason _head is: \s
# matches U+00A0, a literal space does not.
_ZONE_SHEET = re.compile(r"\bZone\s+(\d{1,3})\s+Summary\b", re.I)


def _has_vector_plot(page):
    """True when a stroked path on this page is long enough and wide enough
    to be a plotted curve rather than a rule, a box or a column of ticks."""
    pw, ph = page.rect.width, page.rect.height
    try:
        drawings = page.get_drawings()
    except Exception:
        return False
    for d in drawings:
        if _ink(d) is None or len(d["items"]) < _PLOT_PATH_ITEMS:
            continue
        r = d["rect"]
        if ((r.x1 - r.x0) >= _PLOT_PATH_FRAC[0] * pw
                and (r.y1 - r.y0) >= _PLOT_PATH_FRAC[1] * ph):
            return True
    return False


def _chart_image(page):
    """-> (xref, page rect) of the biggest chart-sized image placed on this
    page, or None. Size is judged in BOTH pixels and printed area: the
    letterhead logo is small in both, a scanned cover page is large in pixels
    but portrait and page-filling, and neither is a chart."""
    best = None
    pw, ph = page.rect.width, page.rect.height
    try:
        images = page.get_images(full=True)
    except Exception:
        return None
    for im in images:
        w, h = im[2], im[3]
        if w < _CHART_IMG_PX[0] or h < _CHART_IMG_PX[1] or w <= h:
            continue                    # a chart of this report is landscape
        try:
            rects = page.get_image_rects(im[0])
        except Exception:
            continue
        for r in rects:
            if (r.width < _CHART_IMG_FRAC[0] * pw
                    or r.height < _CHART_IMG_FRAC[1] * ph):
                continue
            if best is None or w * h > best[2]:
                best = (im[0], r, w * h)
    return (best[0], best[1]) if best else None


def zone_number(page):
    """The zone this Zone N Summary sheet reports, as an int, or None."""
    m = _ZONE_SHEET.search(page.get_text())
    return int(m.group(1)) if m else None


def page_chart_kind(page):
    """'vector', 'raster' or None — the kind of treatment chart on THIS page.

    A vector PRC page is the titled plot — that test is left exactly as it
    was, so no page that reads today stops reading. A raster per-zone sheet
    is a chart-sized image on a page that names a zone and strokes no long
    path; the last clause is the structural half of the branch, and it is
    what stops a page that draws its own curves being traced as a picture.
    """
    if detect_prc(page):
        return "vector"
    if (zone_number(page) is not None and not _has_vector_plot(page)
            and _chart_image(page) is not None):
        return "raster"
    return None


def detect(page):
    """True for any page this template extracts a chart from."""
    return page_chart_kind(page) is not None


# The Lab decides whether to print its IMAGE tag from the SOURCE STRING a
# chart is filed under: "(raster)" is the corpus-wide word for "traced off a
# picture by colour and OCR", spelled the same way by step1, hal1 and
# trican_charts. A per-zone sheet IS that and was being filed as though it
# were vector, which is what the client's report #95 is about ("this is a
# SCHLUM-2 image type should report image"). A PRC Plot is genuinely vector
# and keeps the label it has always had. Both names carry "SLB" so a filing
# that prints both kinds still reads as one provider.
_SOURCE = {"vector": "SLB PRC chart",
           "raster": "SLB Zone Summary chart (raster)"}


def page_source(page):
    """The provider label this page's chart should be filed under."""
    return _SOURCE.get(page_chart_kind(page), _SOURCE["vector"])


def is_additives_page(page):
    """True for the companion "Additives Plot" page. Not parsed — see the
    module docstring in parse notes; exposed so a caller can list it."""
    return _head(page) == ADDITIVES_TITLE and "Customer:" in page.get_text()


def detect_document(doc):
    """True when this PDF carries an SLB Stimulation Service Report at all.

    The tables must not be gated on the CHART succeeding. 00117 and 00118
    each print one PRC page and that page is blank in the source PDF — no
    frame, no curves — so no chart result appears, and a gate keyed to the
    chart source suppressed their Interval Summary sheet and job log too.
    Both wells came back "no extractable data" when the report plainly
    prints a full interval-29 summary. Whether a plot rendered says nothing
    about whether the tables are there.
    """
    for p in range(doc.page_count):
        try:
            page = doc[p]
        except Exception:
            continue
        if detect(page) or is_additives_page(page):
            return True
        if _page_kind(page.get_text()) is not None:
            return True
    return False


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


def _ink(d):
    """The colour a path paints with, whichever operator drew it.

    One SLB vintage draws its whole plot with FILLS instead of strokes: the
    frame, the gridlines, the legend keys and every curve come back as type
    "f" carrying a `fill` colour and no `color` at all. 00117 and 00118 have
    ZERO stroked paths on their PRC page — which is why the frame search
    found nothing and both files reported "no extractable data" across 157
    and 148 pages (issues #79, #80). The curves themselves were never the
    problem: that page holds a 10,119-item blue path, a 9,211-item red, a
    9,077-item green and a 6,175-item black, all fully traceable.

    Reading either operator costs nothing on the stroked vintages, where
    `fill` is absent.
    """
    if d.get("type") == "s":
        return d.get("color")           # stroked vintages: unchanged, exactly
    fill = d.get("fill") or d.get("color")
    if fill is None:
        return None
    # On the stroked vintages the gridlines are pale grey STROKES, which the
    # existing per-caller filters already reject. Here they arrive as fills
    # and would be admitted as another curve colour, so grey and white are
    # ruled out at the source: a curve is either near-black or saturated,
    # never 0.83 grey. (Letting them through raised a bare colour tuple out
    # of a colour lookup — "SLB PRC chart failed — (0.827, 0.827, 0.827)".)
    if _near_black(fill):
        return fill
    return fill if (max(fill) - min(fill)) > 0.15 else None


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
        if not _near_black(_ink(d)):
            continue
        # A stroked frame is four lines or one "re". The filled vintage draws
        # the same rectangle as an outline path of up to sixteen segments
        # (each corner arrives as a curve), so it needs the looser cap — but
        # a curve on that page carries thousands of items, so nothing that
        # could be data gets in either way.
        if len(d["items"]) > (8 if d.get("type") == "s" else 24):
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
        # A stroked key is one segment. The filled vintage draws the same
        # 20.8 x 1.6pt sliver as a closed outline of six items, so it needs
        # the looser count — the swatch width and height tests below are what
        # actually keep curves and rules out.
        if len(d["items"]) > (1 if d.get("type") == "s" else 8):
            continue
        color = _ink(d)
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
        if len(d["items"]) < 50:
            continue
        color = _ink(d)                 # the filled vintage paints, not strokes
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
    """One chart page -> (meta, samples, {col: values}, {col: unit}).

    `samples` is the elapsed-minute grid the values are sampled on, the same
    contract bj1/lib1/halliburton_ifs return. Dispatches on what the page
    actually is, so a caller holding a page needs to know nothing about the
    vintage; extract_page_blocks() is the same thing in list form, and is
    what a caller iterating a document should use.
    """
    blocks = extract_page_blocks(page, sample_sec)
    if not blocks:
        raise ValueError("slb: this page yields no chart")
    return blocks[0]


def _extract_core(page, sample_sec=1.0):
    """extract_page() plus `t0_abs` — the clock position of samples[0] in
    minutes from midnight of the chart's first-labelled day, which is what
    the per-zone split needs to line the printed zone times up with the ink.
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
    return meta, samples, out, units, float(tmin_all)


# ------------------------------------------- the per-zone Zone Summary sheet
#
# WHAT THIS REPLACED, AND WHY
#
# 47 files chart the ENTIRE treatment on one whole-job plot and name no
# interval. That page used to be sliced into one block per zone at the times
# the "Zone N Summary" sheets print — 1,513 blocks, and accurate, because the
# ink being cut was vector.
#
# It was also the wrong page. Every one of those 47 reports prints a per-zone
# chart of its own, on the zone summary sheet, and the client's instruction is
# plain: "there shouldn't be any splitting happening. That combined chart at
# the end isn't relevant as all of the data necessary should be available in
# individual charts." A block cut out of the job plot is this template's
# arithmetic; a per-zone sheet is what the report published. When they
# disagree the published sheet is the answer, and only the sheet has a
# printed start, end and title of its own.
#
# WHAT IT COSTS
#
# These sheets are pictures, so the curves have to be traced instead of read.
# Measured against each report's own per-zone grid (Maximum Pressure, Maximum
# Slurry Rate, Maximum Prop Con) the tracing lands within a few tenths of a
# percent of the vector split it replaces — see the measurements in the task
# notes — because the image is a clean 1572x1033 render of pure ink on white,
# not a scan. It is not free: the time axis and the two value axes are OCR'd,
# and a report that would not OCR would lose these charts entirely. Both
# shipping runtimes carry tesseract, which is what makes that acceptable.
#
# The date helpers below are kept because the sheet's printed START DATE is
# still the best source for a zone's date — vector text, exact, no OCR.

# Three date conventions occur on these sheets: "11/14/2018" (2018),
# "3/12/2019" (2019 on) and ISO "2019-07-17" on the 2019 Black Swan reports.
# Accepting only the US form left nine wells with no readable zone times and
# their charts fused.
_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_ZONE_TITLE = re.compile(r"^Zone (\d+) Summary$", re.M)
_TIME_LABELS = ("START DATE", "END DATE", "START TIME", "END TIME")

# The sheets print the time in whichever convention their vintage used —
# "09:14:44" on the 2018 reports, "2:47:00 AM" from 2019 on. Matching only
# the 24-hour form found the times in four files out of forty-seven and
# quietly left the other forty-three fused. _clock_minutes is the same
# AM/PM-aware reader the time axis already uses.
_tod_minutes = _clock_minutes


def _is_date(text):
    return _MDY.match(text) is not None or _ISO.match(text) is not None


def _date(text):
    m = _ISO.match(text)
    if m:
        y, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _MDY.match(text)
        if not m:
            return None
        y, mo, dy = int(m.group(3)), int(m.group(1)), int(m.group(2))
    try:
        return datetime(y, mo, dy).date()
    except ValueError:
        return None


def _zone_sheet_times(page):
    """The four printed timestamps on one Zone N Summary sheet.

    Taken positionally: the value is the first cell to the right of the label
    on the label's own printed row. The text stream on these sheets is
    ordered by drawing order, so the four dates and times arrive nowhere near
    their labels in it.
    """
    got = {}
    for _y, cells in _rows_by_y(page):
        for lx, lt in cells:
            if lt not in _TIME_LABELS or lt in got:
                continue
            for x, t in cells:
                if x <= lx:
                    continue
                if lt.endswith("DATE") and _is_date(t):
                    got[lt] = t
                    break
                if lt.endswith("TIME") and _CLOCK.match(t):
                    got[lt] = t
                    break
    return got


def _zone_sheet_start(page):
    """(date, minutes-of-day) as printed on this Zone N Summary sheet.

    Vector text, so it is exact and costs no OCR. The chart's own time axis
    says where sample 0 sits; this says which DAY that clock belongs to, which
    is the one thing a clock-only axis cannot tell you.
    """
    t = _zone_sheet_times(page)
    d = _date(t["START DATE"]) if "START DATE" in t else None
    m = _tod_minutes(t["START TIME"]) if "START TIME" in t else None
    if d is None or m is None:
        return None
    return d, m


# ------------------------------------------------ tracing the zone's chart
#
# These images are renders, not scans: pure (255,0,0), (0,0,255), (0,128,0)
# and black strokes on white, with pale grey gridlines, at 1572x1033. That is
# why the tracing lands as close to the printed grid as the vector split did.
#
# COLOURS ARE NOT GUESSED. The document's own PRC page legends every curve
# with its exact RGB, so the ink to look for is read out of vector text and
# only the WHERE is traced. Two things in the corpus make a fixed colour
# table wrong: 00547 legends a fifth curve, GORV Pressure, in burlywood
# (0.871, 0.722, 0.529), and 00129 legends "Injection Rate" in a light grey
# (0.827, 0.827, 0.827) that is the same ink as the gridlines. The first has
# to be picked up, the second has to be refused — see _traceable.

# A pixel belongs to a curve when it sits on the ray from white towards that
# curve's colour: alpha is how far along, resid how far off. Anti-aliasing
# moves a pixel along the ray; a different colour moves it off. Measured on
# 00023/00547 the greatest confusion left is a grey gridline pixel against
# red, at alpha 0.17 — under the floor twice over.
_INK_ALPHA_MIN = 0.50
_INK_ALPHA_MAX = 1.35
_INK_RESID_MAX = 40.0

# A legend colour this washed out cannot be told from the gridlines, whatever
# the rule: light grey ink IS the gridline ink. 00129's "Injection Rate" is
# refused here rather than traced as 20,940 pixels of chart furniture.
_PALE_SAT = 40.0
_PALE_LIGHT = 120.0

# The report's fixed palette, used only when the document's own PRC page
# cannot be read (a blank plot, a missing frame). Named exactly as the legend
# names them so _classify sees the same strings either way.
_DEFAULT_SERIES = [((1.0, 0.0, 0.0), "Treating Pressure"),
                   ((0.0, 0.0, 1.0), "Slurry Rate"),
                   ((0.0, 0.502, 0.0), "Prop Con"),
                   ((0.0, 0.0, 0.0), "BH Prop Con")]


def _traceable(rgb):
    r, g, b = (c * 255.0 for c in rgb)
    hi, lo = max(r, g, b), min(r, g, b)
    return not (hi - lo <= _PALE_SAT and hi > _PALE_LIGHT)


def document_series(doc):
    """[(rgb, legend label)] for the curves this report draws.

    Read off the document's vector PRC page, which every whole-job file has
    exactly one of. Cached on the document: the answer is a property of the
    report, and re-reading a 40,000-segment path once per zone sheet would
    cost more than everything else here put together.
    """
    got = getattr(doc, "_slb_series", None)
    if got is not None:
        return got
    series = []
    for p in range(doc.page_count):
        try:
            page = doc[p]
            if not detect_prc(page):
                continue
            rot = _rotated(page)
            frame = _frame(page, rot)
            if frame is None:
                continue
            legend = _legend(page, rot, frame, _spans(page, rot))
        except Exception:
            continue
        if legend:
            series = legend
            break
    if not series:
        series = list(_DEFAULT_SERIES)
    try:
        doc._slb_series = series
    except Exception:
        pass
    return series


def _page_image(page):
    """The zone chart as an HxWx3 int array, plus its rect on the page."""
    import fitz

    found = _chart_image(page)
    if found is None:
        raise ValueError("slb: no chart image on this zone sheet")
    xref, rect = found
    pix = fitz.Pixmap(page.parent, xref)
    if pix.colorspace is None:
        raise ValueError("slb: the zone chart is a stencil mask, not a chart")
    if pix.alpha or pix.colorspace.n != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3).astype(int)
    return img, rect


def _image_frame(img):
    """The plot rectangle in image pixels, as (x0, y0, x1, y1).

    The frame is the only BLACK full-length rule on the page; the gridlines
    render at 201-236 grey and never reach the 400 sum this admits, so the
    box cannot close on a gridline the way a brightness-relative test would.
    """
    dark = img.sum(axis=2) < 400
    h, w = dark.shape
    cols = np.flatnonzero(dark.sum(axis=0) > 0.5 * h)
    rows = np.flatnonzero(dark.sum(axis=1) > 0.5 * w)
    if not len(cols) or not len(rows):
        return None
    box = int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])
    if (box[2] - box[0]) < 0.40 * w or (box[3] - box[1]) < 0.35 * h:
        return None
    return box


def _ocr(sub, psm=6, whitelist="0123456789.-", scale=3):
    """OCR a crop, returning [(text, cx, cy)] in the crop's own pixels."""
    import auto_raster as ar
    from PIL import Image

    if sub.size == 0:
        return []
    pil = Image.fromarray(sub.astype(np.uint8))
    pil = pil.resize((pil.width * scale, pil.height * scale), Image.LANCZOS)
    return [(t, cx / scale, cy / scale)
            for t, cx, cy in ar.ocr_words(np.array(pil).astype(int), psm=psm,
                                          whitelist=whitelist)]


def _tick_column(img, xa, xb, y0, y1):
    """[(value, image row)] for the numeric labels in one gutter.

    The strip is cut to the plot's own rows: the time labels under the chart
    would otherwise arrive as ticks, which is the exact defect hal1 documents
    at _ocr_column and which biased a whole channel there.
    """
    pad = 10
    ya, yb = max(0, y0 - pad), min(img.shape[0], y1 + pad + 1)
    out = []
    for text, _cx, cy in _ocr(img[ya:yb, max(0, xa):xb]):
        t = text.replace(",", "").strip("-. ")
        if re.fullmatch(r"\d+(\.\d+)?", t):
            out.append((float(t), cy + ya))
    return out


_RASTER_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?([AP]M)?$")


def _time_label_passes(img, y1):
    """Yields [(image column, minutes of day)] for the row of clock labels,
    cheapest reading first."""
    h = img.shape[0]
    band = img[min(y1 + 2, h - 1):min(y1 + 62, h), :]
    if band.size == 0:
        return

    def parse(words, dx=0.0):
        pts = []
        for text, cx, _cy in words:
            m = _RASTER_CLOCK.match(text.replace(" ", ""))
            if not m:
                continue
            hh, mm = int(m.group(1)), int(m.group(2))
            ss = int(m.group(3) or 0)
            ap = m.group(4)
            if ap:
                if hh < 1 or hh > 12 or mm > 59:
                    continue
                hh = hh % 12 + (12 if ap == "PM" else 0)
            elif hh > 23 or mm > 59:
                continue
            pts.append((cx + dx, hh * 60.0 + mm + ss / 60.0))
        return pts

    yield parse(_ocr(band, psm=6, whitelist="0123456789:AMP "))

    # Per-label fallback: split the row on its own ink gaps and read each
    # label alone. Worth its four-times cost, and worth trying even when the
    # cheap pass returned plenty of points — 00023's zone 23 is labelled
    # 8:14 AM through 8:53 AM and the one-shot read returned nine points of
    # which six had the leading 8 as a 5 or a 3. Nine wrong points pass any
    # test that counts them, so the caller retries on a failed FIT, not on a
    # thin one.
    dark = (band.sum(axis=2) < 450).any(axis=0)
    runs, start, gap = [], None, 0
    for i, on in enumerate(dark):
        if on:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 30:
                runs.append((start, i - gap))
                start = None
    if start is not None:
        runs.append((start, len(dark) - 1))
    out = []
    for c0, c1 in runs:
        if c1 - c0 < 20:
            continue
        words = _ocr(band[:, max(0, c0 - 6):c1 + 7], psm=7,
                     whitelist="0123456789:AMP")
        joined = [("".join(w[0] for w in words), (c0 + c1) / 2.0, 0.0)]
        out += parse(joined)
    yield out


# How far the chart's left edge may sit from the START TIME the sheet prints
# beside it. Measured over 00023 and 00035 the two agree to under two minutes
# on every zone; an hour-digit misread that survives the vote moves the fit by
# a whole hour, so this separates the two cleanly without being tight enough
# to reject a chart that simply opens a little early.
_CLOCK_TOL_MIN = 20.0


def _fit_time_labels(pts, x0, x1):
    """RANSAC one reading of the label row -> (a, b, inliers) or None.

    RANSAC, not least squares. The labels themselves are crisp but OCR is
    not: over 00023's thirty sheets it turned 11:07 into 1:07, 11:11 into
    11011 and 9:44 into 9:49, and a least-squares fit that also has to
    unwrap midnight takes a single misread and runs the whole chart hours
    long — four of those thirty zones came out with durations of 30 to 64
    HOURS and four more with a fitted residual near a thousand minutes.
    With the outliers voted out all thirty read their true 30-90 minutes.

    Midnight is handled inside the vote rather than before it: a candidate
    pair may put the later label a day on, and every point is scored against
    whichever day lands nearest. 00023's zone 16 runs 11:21 PM to 12:07 AM
    and needs that; the misreads must not be allowed to trigger it.
    """
    if len(pts) < 4:
        return None
    pts = sorted(pts)
    xs = np.array([p[0] for p in pts], float)
    vs = np.array([p[1] for p in pts], float)
    span = float(x1 - x0)
    best = (0, None, None)
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = xs[j] - xs[i]
            if dx < 80:
                continue
            for day in (0.0, 1440.0):
                b = (vs[j] + day - vs[i]) / dx
                if b <= 0:
                    continue
                dur = b * span
                if not (0.5 < dur < 12 * 60):
                    continue
                a = vs[i] - b * xs[i]
                pred = a + b * xs
                off = np.round((pred - vs) / 1440.0)
                inl = np.abs(pred - (vs + 1440.0 * off)) <= max(0.6,
                                                                0.015 * dur)
                if int(inl.sum()) > best[0]:
                    best = (int(inl.sum()), inl, off)
    n, inl, off = best
    if inl is None or n < 4 or n < 0.6 * len(pts):
        return None
    x, y = xs[inl], vs[inl] + 1440.0 * off[inl]
    A = np.vstack([np.ones(len(x)), x]).T
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)
    if b <= 0:
        return None
    return float(a), float(b), n


def _raster_time_axis(img, x0, x1, y1, printed_start=None):
    """-> (a, b, inliers, drift) for minutes-of-day = a + b*column, or None.

    Two things guard this. A reading that admits no fit is re-read label by
    label, because a bad reading can be plentiful as well as thin — 00023's
    zone 23 returns nine points from the cheap pass and six of them have the
    leading 8 read as a 5 or a 3; nine wrong points pass any test that counts
    them, so the retry is keyed on the FIT failing, not on the count.

    Then the surviving fit is weighed against the START TIME the sheet prints
    in VECTOR TEXT next to the chart — the one piece of this page needing no
    OCR at all. It is used to CHOOSE between readings, not to veto them.
    Vetoing looks right until a sheet is simply wrong about itself: 00023's
    zone 21 is stamped 02:44:05 to 04:36:34 and its chart is labelled 3:41 AM
    to 4:40 AM, ten labels out of ten agreeing across both passes. The chart
    is legible and says what it says; `drift` is returned so the caller can
    say so too.
    """
    best = None
    for pts in _time_label_passes(img, y1):
        fit = _fit_time_labels(pts, x0, x1)
        if fit is None:
            continue
        if printed_start is None:
            return fit + (None,)
        drift = abs(((fit[0] + fit[1] * x0) - printed_start + 720.0)
                    % 1440.0 - 720.0)
        if drift <= _CLOCK_TOL_MIN:
            return fit + (drift,)
        if best is None or fit[2] > best[2]:
            best = fit + (drift,)
    return best


def _axis_title(img, xa, xb):
    """The rotated axis title in a gutter, upright and OCR'd.

    Both titles read bottom-to-top, so both want the same quarter turn; the
    other turn is tried second because it costs one OCR to be sure rather
    than to assume, and a title read upside down comes back as noise
    ("OL X (ulmjeu) ayey") that no pattern here would match anyway.
    """
    from PIL import Image

    sub = img[:, max(0, xa):xb]
    if sub.size == 0:
        return ""
    letters = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
               "0123456789()/. x")
    for turn in (-90, 90):
        pil = Image.fromarray(sub.astype(np.uint8)).rotate(turn, expand=True)
        words = _ocr(np.array(pil).astype(int), psm=6, whitelist=letters)
        text = " ".join(w[0] for w in sorted(words, key=lambda w: w[1]))
        if re.search(r"press|rate|prop\s*con", text, re.I):
            return text
    return ""


def _colour_masks(img, colours):
    """{rgb: mask} — every pixel given to the legend colour whose white->ink
    ray it lies on, or to none of them."""
    ink = 255.0 - img.astype(float)
    resid_best = np.full(img.shape[:2], _INK_RESID_MAX)
    idx = np.full(img.shape[:2], -1, int)
    for i, rgb in enumerate(colours):
        u = np.array([255.0 * (1.0 - c) for c in rgb], float)
        nu = float(u.dot(u))
        if nu <= 0.0:
            continue
        # einsum, not `ink @ u`. The two agree bit for bit, but on macOS the
        # matmul is dispatched to Accelerate, which raises overflow / invalid
        # / divide-by-zero flags off the padding lanes of its SIMD tail and
        # so prints three RuntimeWarnings per zone sheet on a run that is
        # arithmetically clean — thirty of them per report, straight to the
        # EXE's console. Reproduced on an array of literal 1.0 at this size
        # and silent at 100x100x3, so it is the array's shape that trips it,
        # not its contents; alpha comes back finite either way. einsum takes
        # its own loop and is the same speed here.
        alpha = np.einsum("ijk,k->ij", ink, u) / nu
        resid = np.linalg.norm(ink - alpha[..., None] * u, axis=2)
        take = ((alpha >= _INK_ALPHA_MIN) & (alpha <= _INK_ALPHA_MAX)
                & (resid < resid_best))
        resid_best = np.where(take, resid, resid_best)
        idx = np.where(take, i, idx)
    return {rgb: (idx == i) for i, rgb in enumerate(colours)}


# The frame is stroked in the same black as the bottom-hole concentration
# trace, so it lands in that channel's mask. It is removed as STRUCTURE, not
# as colour: a rule is a line that runs the length of the plot, and only the
# few pixels at each edge can hold one. Clearing every long run instead would
# delete a rate trace that holds one value for most of the chart, which is
# what a steady stage looks like.
_RULE_EDGE = 6
_RULE_FILL = 0.5


def _drop_frame_rules(sub):
    h, w = sub.shape
    if h < 2 * _RULE_EDGE or w < 2 * _RULE_EDGE:
        return sub
    for r in list(range(_RULE_EDGE)) + list(range(h - _RULE_EDGE, h)):
        if sub[r].mean() > _RULE_FILL:
            sub[r] = False
    for c in list(range(_RULE_EDGE)) + list(range(w - _RULE_EDGE, w)):
        if sub[:, c].mean() > _RULE_FILL:
            sub[:, c] = False
    return sub


# A traced channel covering less of the plot than this is a stray, not a
# curve; matches the floor hal1 uses.
_MIN_COVERAGE = 0.05


def _printed_span(pts, fit):
    """(lowest, highest) tick VALUE this axis actually PRINTS, or None.

    The plot frame runs a hair past the outermost tick, so the axis read at
    the frame edge is -0.01 where the report prints 0. The Lab labels its own
    y axis with the printed pair whenever the two agree to within a tick, so
    it wants the printed numbers as well as the frame's arithmetic.

    Only ticks the fit accepted count. OCR reads a gridline crossing as a
    stray number often enough that a raw min/max over the column would invent
    a range the chart never prints — the tolerance is fit_ticks' own.
    """
    a, b, _n = fit
    tol = max(abs(b) * 20, 1e-9)
    keep = [v for v, c in pts if abs(a + b * c - v) < tol]
    return (min(keep), max(keep)) if len(keep) >= 2 else None


def _zone_geom(rect, shape, box, duration_min):
    """The zone chart's PLOT FRAME in page coordinates, for the Lab's synced
    "Compare Original" view, or None.

    THE CLIENT'S ACTUAL ASK (report #95) is "extract the image from the page
    for Ghosting without the summary data which is text". A Zone N Summary
    sheet is one page carrying two unrelated things: real vector text — the
    START/END times, the fluid and proppant grids — filling the top two
    thirds, and ONE embedded 1572x1033 chart image pasted into the bottom
    third. This is what separates them, and it does it without cutting a
    picture out: geometry quoted at the chart's own plot frame makes the Lab
    stretch that frame across its plot rect, and the Lab crops everything
    above the rect — so the tables go off the top of their own accord and the
    ghost is the chart alone. Nothing here has to know the tables exist.

    Everything upstream works in the chart image's own pixels. The sheet
    places that image with a plain positive scale and no rotation or flip
    (measured across the corpus: transform (512.99, 0, 0, 292.39, x, y) on
    every zone sheet, page rotation 0), so image pixel -> page point is a
    scale and an offset — hal1's raster case exactly, so it uses step1's
    converter and inherits its convention: elapsed second e sits at page
    coordinate (e - ta) / tb along `axis`, and v0/v1 bracket the plot on the
    other axis in mupdf (y-down) units.
    """
    from step1 import _page_geom

    if rect.width <= 1 or rect.height <= 1 or duration_min <= 0:
        return None
    ih, iw = shape[0], shape[1]
    # samples[0] is the frame's left edge, so elapsed time starts at zero
    # there — which is what t0_seconds = 0 tells the converter.
    return _page_geom({"plot": box, "duration_s": float(duration_min) * 60.0,
                       "t0_seconds": 0.0},
                      iw / rect.width, ih / rect.height, rect.x0, rect.y0)


def extract_zone_page(page, sample_sec=1.0):
    """One Zone N Summary sheet -> (meta, samples, {col: values}, {col: unit}).

    The zone number, the start date and the customer come off the page as
    vector text. Only the curves, the two value axes and the clock labels
    are read from the picture.
    """
    import auto_raster as ar
    import curve_trace as ct

    zone = zone_number(page)
    if zone is None:
        raise ValueError("slb: this page names no zone")
    if not ar.available():
        raise ValueError(
            "slb: zone %d's chart is a raster image and tesseract is not "
            "installed, so its curves cannot be traced" % zone)

    img, rect = _page_image(page)
    box = _image_frame(img)
    if box is None:
        raise ValueError("slb: no plot frame in zone %d's chart image" % zone)
    x0, y0, x1, y1 = box

    printed = _zone_sheet_start(page)
    tfit = _raster_time_axis(img, x0, x1, y1, printed[1] if printed else None)
    if tfit is None:
        raise ValueError("slb: zone %d's chart prints no readable time axis"
                         % zone)
    ta, tb, _n_labels, drift = tfit
    t0_abs = ta + tb * x0
    duration = tb * (x1 - x0)

    warnings = []
    if drift is not None and drift > _CLOCK_TOL_MIN:
        warnings.append(
            "this chart's own time axis opens %.0f minutes from the START "
            "TIME printed on the same sheet; the chart's axis is what is "
            "used, and the two disagree about this zone" % drift)
    left_pts = _tick_column(img, 0, max(1, x0 - 2), y0, y1)
    right_pts = _tick_column(img, x1 + 3, img.shape[1], y0, y1)
    left = ar.fit_ticks(left_pts, min_inliers=4)
    right = ar.fit_ticks(right_pts, min_inliers=4)
    left_title = _axis_title(img, 0, max(1, x0 - 50))
    right_title = _axis_title(img, x1 + 50, img.shape[1])
    axes = []
    if left:
        axes.append({"side": "left", "key": 0.0, "title": left_title,
                     "fit": (left[0], left[1]),
                     "printed": _printed_span(left_pts, left),
                     "lo": left[0] + left[1] * y1, "hi": left[0] + left[1] * y0})
    if right:
        axes.append({"side": "right", "key": 1.0, "title": right_title,
                     "fit": (right[0], right[1]),
                     "printed": _printed_span(right_pts, right),
                     "lo": right[0] + right[1] * y1,
                     "hi": right[0] + right[1] * y0})
    if not axes:
        raise ValueError("slb: no value axis readable on zone %d's chart"
                         % zone)

    # The multiplier is read from THIS page and no other. 00547's whole-job
    # plot prints its shared axis as "Pressure (MPa) / Rate (m3/min)" while
    # every one of its 39 per-zone charts prints the same axis as "... x 10";
    # borrowing the document's answer would have shipped that well's rates ten
    # times over. When the title cannot be read the rate is dropped rather
    # than guessed — a missing channel is visible, a tenfold one is not.
    rate_scale_known = bool(re.search(r"rate", left_title or "", re.I))

    series = document_series(page.parent)
    wanted, skipped, pale = {}, [], []
    for rgb, label in series:
        hit = _classify(label)
        if hit is None:
            skipped.append(label)
            continue
        if not _traceable(rgb):
            pale.append(label)
            continue
        col, kind, mult = hit
        if col in [v[0] for v in wanted.values()]:
            continue
        wanted[rgb] = (col, kind, mult, label)
    if not wanted:
        raise ValueError("slb: no curve on zone %d's chart is a channel this "
                         "template names" % zone)

    masks = _colour_masks(img, list(wanted))
    n = max(2, int(round(duration * 60.0 / sample_sec)) + 1)
    samples_s = np.arange(n) * float(sample_sec)
    col_s = np.arange(x1 - x0 + 1) * tb * 60.0

    out, units = {}, {}
    scales, frames = {}, {}
    for rgb, (col, kind, mult, label) in wanted.items():
        sub = _drop_frame_rules(masks[rgb][y0:y1 + 1, x0:x1 + 1].copy())
        if not sub.any():
            continue
        ax = _pick_axis(axes, kind)
        if ax is None:
            continue
        mult = mult * _axis_multiplier(ax["title"], kind)
        if kind == "rate" and not rate_scale_known:
            warnings.append(
                "%s not exported: this chart's shared value axis is a "
                "picture and its title could not be read, so the 'x 10' the "
                "report prints on it cannot be confirmed" % label)
            continue
        py = ct.column_track(sub)
        if py is None:
            py = ar.curve_positions(sub)
        vals = (ax["fit"][0] + ax["fit"][1] * (py + y0)) / mult
        if float(np.isfinite(vals).mean()) < _MIN_COVERAGE:
            continue
        out[col] = ct.resample(samples_s, col_s, vals)
        units[col] = _UNITS.get(col, "")
        # This curve's own axis read AT THE PLOT FRAME, top edge then bottom.
        # Ghost stretches the source page so exactly those two rows fill the
        # Lab's plot rect, so this is the pair a curve has to be placed
        # against to land on its own printed ink; ax["hi"]/ax["lo"] are the
        # same fit evaluated at the same two rows, before the legend's "x 10"
        # is divided out. Without it the Lab falls back to a rounded peak —
        # the "0..60 (guessed)" the client's own flag report printed.
        frames[col] = (ax["hi"] / mult, ax["lo"] / mult)
        span = ax.get("printed") or (min(ax["lo"], ax["hi"]),
                                     max(ax["lo"], ax["hi"]))
        scales[col] = (span[0] / mult, span[1] / mult)
    if not out:
        raise ValueError("slb: no curve traced on zone %d's chart" % zone)

    meta = PageMeta()
    meta.stage = str(zone)
    meta.uwi = ""                       # never the printed one; see module doc
    meta.duration_min = float(duration)
    meta.axes = scales
    meta.axes_frame = frames
    meta.geom = _zone_geom(rect, img.shape, (x0, y0, x1, y1), duration)
    clock = t0_abs % 1440.0
    meta.start_time = "%02d:%02d:%02d" % (int(clock // 60), int(clock % 60),
                                          int(round(clock * 60)) % 60)
    if printed:
        day, printed_min = printed
        # the chart opens within a minute or two of the printed start; more
        # than half a day apart means the two sit either side of midnight
        drift = clock - printed_min
        if drift > 720.0:
            day = day - timedelta(days=1)
        elif drift < -720.0:
            day = day + timedelta(days=1)
        meta.date = day.strftime("%Y-%m-%d")
    text = page.get_text()
    cust = _CUSTOMER.search(text)
    printed_uwi = _UWI_LINE.search(text)
    bits = ["%s — Zone %d" % (PRC_TITLE, zone)]
    if cust:
        bits.append(cust.group(1))
    if printed_uwi:
        bits.append("report UWI %s" % printed_uwi.group(1))
    meta.title = " — ".join(bits)
    if skipped:
        meta.warnings.append(
            "curve(s) not named by this template, left untraced: "
            + ", ".join(sorted(set(skipped))))
    if pale:
        meta.warnings.append(
            "curve(s) drawn in an ink too pale to tell from the chart's own "
            "gridlines, left untraced: " + ", ".join(sorted(set(pale))))
    meta.warnings += warnings
    return meta, samples_s / 60.0, out, units


def extract_page_blocks(page, sample_sec=1.0):
    """One chart page -> [(meta, samples, {col: values}, {col: unit})].

    One block for a per-interval vector plot and one for a per-zone raster
    sheet. A whole-job plot yields none: see the section header above.
    """
    kind = page_chart_kind(page)
    if kind == "raster":
        return [extract_zone_page(page, sample_sec)]
    if kind != "vector":
        raise ValueError("slb: not a chart page")
    if page_stage(page) is None:
        doc = getattr(page, "parent", None)
        sheets = 0
        if doc is not None:
            try:
                sheets = sum(1 for p in range(doc.page_count)
                             if zone_number(doc[p]) is not None)
            except Exception:
                sheets = 0
        raise ValueError(
            "whole-job PRC plot not exported — this page charts the entire "
            "treatment on one axis and names no interval; the report's own "
            "%d per-zone chart(s) are read instead" % sheets)
    meta, samples, data, units, _t0 = _extract_core(page, sample_sec)
    return [(meta, samples, data, units)]
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
