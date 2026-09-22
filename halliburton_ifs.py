"""Halliburton IFS chart template (as filed by Shell, Vermilion, Ovintiv in BC).

Layout (landscape, unrotated): per-interval treatment charts titled
"x.y Interval N - Entire Treatment", footer "(IFS v x.y.z)". The legend
lists each series in its stroke color followed by a same-colored axis
letter (A/B/C); numeric tick columns for A sit left of the plot, B and C
to the right. Time axis is HH:MM labels along the bottom.

Everything needed is in the text layer, so calibration comes entirely from
tick-label positions — no frame detection required.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

import fitz
import numpy as np

import ocr_labels
from frac_core import PageMeta

STD_NAMES = [
    (("treating pressure",), "Tr Press"),
    (("slurry rate", "clean rate"), "Slurry Rate"),
    (("slurry proppant conc", "blender prop"), "WH Prop Conc"),
    (("bh proppant conc", "bottomhole prop"), "BH Prop Conc"),
]


def _page_text(page):
    """The page's text, OCR'd when it has none of its own.

    An IFS filing can be drawn with every string converted to outlines: 00148
    is 116 chart pages and NOT ONE readable character, so `"(IFS v" in text`
    was false and no Halliburton chart in the file was ever looked at. The
    page is an ordinary IFS chart otherwise — "Interval 1 - Entire Treatment",
    axes 0..100 MPa / 0..20 m3/min / 0..1000 kg/m3, full legend.
    """
    t = page.get_text()
    if len(t.strip()) > _OCR_TEXT_MIN or not ocr_labels.available():
        return t
    try:
        return ocr_labels.page_text(page) or t
    except Exception:
        return t


# Below this many characters a page is drawing its labels rather than writing
# them. An outlined IFS page carries 0; a normal one carries hundreds.
_OCR_TEXT_MIN = 40


def _outline_colours(page):
    """[(rect, int_rgb)] for the coloured vector fills that DRAW the glyphs.

    This module keys the legend to the curves by the TEXT's colour — a name
    and its axis letter are the pair that share one — and OCR returns words
    with no colour at all. But an outlined page has not lost the colour: the
    glyphs are filled paths and each carries the colour the text used to have.
    Measured on 00148 p136: "Treating"/"Pressure" come back (1,0,0),
    "Backside" (1,0,1), "Slurry"/"Rate" (0,.5,.5), "Slurry"/"Conc" (0,1,0),
    the second "Conc" (.5,.5,0) and "Interval" black — which is exactly what
    the page draws.
    """
    out = []
    for d in page.get_drawings():
        c = d.get("fill") or d.get("color")
        if c is None:
            continue
        try:
            rgb = (int(round(c[0] * 255)) << 16 | int(round(c[1] * 255)) << 8
                   | int(round(c[2] * 255)))
        except Exception:
            continue
        out.append((fitz.Rect(d["rect"]), rgb))
    return out


def _ocr_spans(page, rotated):
    """_spans() for a page whose labels are outlines. [] when OCR is absent."""
    if not ocr_labels.available():
        return []
    try:
        words = ocr_labels.words(page)
    except Exception:
        return []
    fills = _outline_colours(page)
    out = []
    for w in words:
        t = (w.get("text") or "").strip()
        if not t:
            continue
        r = fitz.Rect(w["rect"])
        tally = defaultdict(int)
        for rect, rgb in fills:
            # a glyph's own path sits INSIDE the word box; the curve behind it
            # and the frame around it are far larger, so size keeps them out
            if rect.width < r.width * 3 and rect.height < r.height * 3 \
                    and r.intersects(rect):
                tally[rgb] += 1
        colour = max(tally.items(), key=lambda kv: kv[1])[0] if tally else 0
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if rotated:
            cx, cy = _unrotate(cx, cy)
        out.append({"t": t, "cx": cx, "cy": cy, "ocr": True,
                    "x0": r.x0, "x1": r.x1, "color": colour})
    return out


# The build stamp every IFS page carries. Matched WITHOUT case, because the
# case changed: builds up to v4.6.3 print "(IFS v4.6.3)" and v6 prints
# "(IFS V6.0.0)". A literal "(IFS v" test saw the second as a different
# document entirely — 00084 carries the marker on 238 pages and detect claimed
# none of them, so the whole v6 family came back "No extractable data"
# (Carmine, #612: "a large number of Hal-2 type in the AER ARC folder not
# extractable but they are all fine").
_IFS_MARK = re.compile(r"\(IFS\s*v", re.I)


# How much curve ink a page has to draw before this module will call it a
# chart. The stamp alone is not enough: an IFS filing prints it on EVERY
# page, and 00973 is 282 pages of which only 105 are charts — the rest are
# the table of contents, the treatment summary, a stage-summary table and a
# service-report form per interval, and all of them carry "(IFS v 7)". Asked
# only for the stamp, detect claimed 184 pages and 88 of them then failed,
# so a reader's page-by-page log reported 79 charts lost that were never
# charts (#699).
#
# The test is the extractor's own: the ink _curve_ink counts is the ink
# extract_page collects, by the same rule it uses to keep a black curve apart
# from the frame it shares a colour with. Measured on 00973 every one of the
# 105 charts draws between 8,300 and 50,140 such segments and every other
# stamped page draws NONE, so where the line falls between them does not
# matter much; it is set low so that a sparse chart still counts.
_CURVE_INK_MIN = 200


def _curve_ink(page):
    """Stroked segments that are not a long axis-aligned rule. -> count

    A frame, a gridline and a table border are all straight and long; a
    plotted curve is neither for more than a few segments at a time. This is
    the same test extract_page applies to black ink, applied to every colour.
    """
    n = 0
    for d in page.get_drawings():
        if d.get("color") is None or d["type"] not in ("s", "fs"):
            continue
        for item in d["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
            elif item[0] == "c":
                p1, p2 = item[1], item[4]
            else:
                continue
            dx, dy = abs(p1.x - p2.x), abs(p1.y - p2.y)
            if (dx < 0.01 or dy < 0.01) and max(dx, dy) > 5:
                continue
            n += 1
            if n >= _CURVE_INK_MIN:
                return n
    return n


def detect(page):
    # Ink before text: _page_text OCRs a page whose labels are outlines, and
    # that costs seconds a page with nothing on it should not be charged.
    #
    # An IFS chart filed as a BITMAP rather than drawn falls on the false
    # side of this, and that is the honest answer — this module reads vector
    # curves and cannot read those pages either. The pipeline reports them
    # separately (_ifs_raster) and does not ask here.
    if _curve_ink(page) < _CURVE_INK_MIN:
        return False
    return _IFS_MARK.search(_page_text(page)) is not None


def is_entire_treatment(page):
    # lettered intervals ("Interval 4A - Entire Treatment") count too
    return re.search(r"Interval\s+\d{1,3}[A-Za-z]?\s*[-–—]\s*Entire Treatment",
                     _page_text(page)) is not None


def page_rotated(page):
    """True when the chart is drawn 90° rotated (time axis vertical). Some
    IFS builds (v4.3.1) render portrait: every text span reads bottom-to-top
    (dir≈(0,-1)). Detected by the dominant span direction."""
    vert = horiz = 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1, 0))
            if abs(dy) > abs(dx):
                vert += len(line.get("spans", []))
            else:
                horiz += len(line.get("spans", []))
    if vert or horiz:
        return vert > horiz and vert >= 3
    # A page whose strings are outlines has no text lines to take a direction
    # from, so the count comes back 0 to 0 and the page is called upright by
    # default. 00148 is not: /Rotate 90, "HALLIBURTON" measures 17pt wide by
    # 144pt tall, and its clock labels 04:10..04:50 sit at a CONSTANT x with
    # varying y. Called upright, the chart is read against the wrong axes and
    # the time labels are never found at all.
    #
    # This is the same defect fb6b1a3 fixed in slb._rotated, and the same
    # remedy: when there is no text to take a direction from, take it from
    # the shape of the OCR words.
    if not ocr_labels.available():
        return False
    try:
        words = ocr_labels.words(page)
    except Exception:
        return False
    tall = sum(1 for w in words
               if (w["rect"][3] - w["rect"][1]) > (w["rect"][2] - w["rect"][0]))
    return tall > (len(words) - tall) and tall >= 3


def _unrotate(x, y):
    """Map a 90°-rotated (dir=(0,-1)) point back to canonical orientation so
    the horizontal-chart logic applies unchanged: (x, y) -> (-y, x)."""
    return -y, x


def _spans(page, rotated=None):
    if rotated is None:
        rotated = page_rotated(page)
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if rotated:
                    cx, cy = _unrotate(cx, cy)
                out.append({"t": t, "cx": cx, "cy": cy,
                            "x0": x0, "x1": x1, "color": span.get("color", 0)})
    if not out:
        return _ocr_spans(page, rotated)
    return out


def _fit(pairs):
    """least squares value = a + b*coord over [(value, coord)]"""
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    A = np.vstack([np.ones_like(c), c]).T
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(a), float(b)


def visible_plot_box(page):
    """-> (first_visible_drawing_index, plot_rect) for a page that draws its
    chart more than once.

    Some IFS pages render the whole chart, paint an OPAQUE WHITE rectangle
    over the plot area, and render it again at a different scale. Both copies
    are in the content stream with the same colours, the same clip and full
    opacity, so every collector sees two of every curve and two of every tick
    column — 181 one-sample dips on Treating Pressure on 00002 p339, which is
    what "extreme spikes" turned out to be. Nothing is wrong with the ink; the
    first copy is simply painted over and invisible.

    So the rule is the page's own rendering rule: whatever is drawn after the
    LAST full-plot white fill is what a reader sees. On a page that draws its
    chart once, that fill is the ordinary background at the top of the stream
    and this returns an index that excludes nothing.
    """
    cut, box = 0, None
    pr = page.rect
    for i, d in enumerate(page.get_drawings()):
        f = d.get("fill")
        if f is None or d["type"] not in ("f", "fs"):
            continue
        if min(f[:3]) < 0.97:                       # not white
            continue
        if (d.get("fill_opacity") or 1) < 0.99:     # not opaque: no cover
            continue
        r = d["rect"]
        if r.width > pr.width * 0.5 and r.height > pr.height * 0.4:
            cut, box = i, r
    return cut, box


def _axis_letter(text):
    """The axis letter a short black span names, tolerating OCR noise -> None.

    IFS prints the letter alone above its own tick column, and OCR returns it
    with a speck attached: 00973 p117 reads the rate ladder's "B" as "cB" and
    the concentration ladder's "C" as "c". A strict [A-F] match placed only
    the pressure ladder, the rest fell through to left-to-right order, and
    Slurry Proppant Conc was mapped onto the RATE axis — a 0..20 scale for a
    0..1000 reading, which the sanity check then threw away, so the channel
    vanished from the chart (#709, #711).

    Two characters at most, so a word like "INC" — which also ends in a
    letter in the range — cannot be taken for an axis.
    """
    t = (text or "").strip()
    if not 1 <= len(t) <= 2:
        return None
    alpha = [ch for ch in t if ch.isalpha()]
    if not alpha:
        return None
    last = alpha[-1].upper()
    return last if "A" <= last <= "F" else None


def _axis_columns(spans, box=None):
    """Cluster numeric black tick labels into vertical columns."""
    ocr = any(s.get("ocr") for s in spans)
    if ocr:
        # OCR glues the tick MARK, or a speck of the gridline, onto the front
        # of a label: 00973 p117's rate ladder comes back "20", "+18", and its
        # concentration ladder "1000", "~900". A label that fails the numeric
        # test is not read at all, the column falls below the three it needs,
        # and the whole axis vanishes — that page found the pressure and
        # concentration ladders and no rate ladder, so Slurry Rate had nothing
        # to be scaled against and was dropped from the chart (#709, #711).
        #
        # Only a leading NON-numeric is removed, so a real minus survives and
        # the tick-mark-as-minus rule below still decides that case.
        for s in spans:
            if s["color"] != 0:
                continue
            t = s["t"].strip().replace(",", "")
            if re.fullmatch(r"-?\d+(\.\d+)?", t):
                continue
            m = re.fullmatch(r"[^\d\-]{1,2}(-?\d+(?:\.\d+)?)", t)
            if m:
                s["t"] = m.group(1)
    nums = [s for s in spans if s["color"] == 0 and
            re.fullmatch(r"-?\d+(\.\d+)?", s["t"].replace(",", ""))]
    if ocr:
        # A tick MARK beside its label reads as a minus sign: 00148 p136's
        # concentration column comes back "-0", "-500", "1000". A leading
        # minus is dropped only when the column carries a larger positive
        # too, so a genuinely negative axis — which would be negative
        # throughout — is never rewritten.
        pos = {abs(float(s["t"].replace(",", ""))) for s in nums
               if not s["t"].startswith("-")}
        for s in nums:
            if s["t"].startswith("-"):
                bare = s["t"][1:]
                try:
                    if any(v > abs(float(bare)) for v in pos):
                        s["t"] = bare
                except ValueError:
                    pass
    # cluster on label centers (alignment varies by axis side); tick digits
    # are short so centers stay within ~6 pt per column — but an OCR'd label
    # is only as tight as its box, and a wider number pulls its centre off
    # the column: on 00148 p136 "1000" landed 11 pt from "500" and the
    # concentration axis split into two columns of one and two, so it was
    # never read at all. Widen the window rather than change what is
    # measured; the near edge is not available in the same frame as cx here,
    # because a rotated page's spans carry unrotated centres and raw edges.
    nums.sort(key=lambda s: s["cx"])
    span_ = 14 if ocr else 6
    clusters, cur = [], [nums[0]] if nums else []
    for s in nums[1:]:
        if s["cx"] - cur[-1]["cx"] > span_:
            clusters.append(cur); cur = [s]
        else:
            cur.append(s)
    if cur:
        clusters.append(cur)

    _min_chain = 3 if ocr else 4
    out = []
    for group in clusters:
        # Four labels is the guard that keeps a stray pair from becoming an
        # axis. OCR loses labels rather than inventing them — 00148's rate
        # column returns 3 of its 5 — so on an OCR page three is allowed,
        # which is still enough to fit a line AND check it against a third
        # point. Text pages are unchanged.
        if len(group) < (3 if ocr else 4):
            continue
        # keep the longest chain that is evenly spaced in y AND arithmetic in
        # value (drops strays: section numbers, stray decimals, event-marker
        # labels that share the column's x range but break the tick scale)
        group.sort(key=lambda s: s["cy"])

        def val(s):
            return float(s["t"].replace(",", ""))

        chains = []
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                gap = group[j]["cy"] - group[i]["cy"]
                if gap < 8:
                    continue
                vstep = val(group[j]) - val(group[i])
                if vstep == 0:
                    continue
                chain = [group[i], group[j]]
                exp_y = group[j]["cy"] + gap
                exp_v = val(group[j]) + vstep
                for k in range(j + 1, len(group)):
                    if abs(group[k]["cy"] - exp_y) <= gap * 0.2 and \
                       abs(val(group[k]) - exp_v) <= abs(vstep) * 0.15 + 1e-9:
                        chain.append(group[k])
                        exp_y = group[k]["cy"] + gap
                        exp_v = val(group[k]) + vstep
                # Four ticks is what proves a column is an axis and not a
                # coincidence. OCR drops labels rather than inventing them —
                # 00148 p136 returns 3 of the rate axis' 5 and 3 of the
                # concentration axis' 5 — so three is enough on an OCR page:
                # two points fit the line and the third has to land on it.
                if len(chain) >= _min_chain:
                    chains.append(chain)
        if not chains:
            continue
        longest = max(len(c) for c in chains)
        keep = [c for c in chains if len(c) >= longest - 1]
        if box is not None and len(keep) > 1:
            # two label sets of EQUAL length, one per copy of the chart: the
            # visible one is the set whose ticks span the visible plot box.
            # Picking "longest" alone chose between them arbitrarily and got
            # 00002 p339 wrong by 4 MPa on top of the spikes.
            def off(c):
                ys = [t["cy"] for t in c]
                return abs(min(ys) - box.y0) + abs(max(ys) - box.y1)
            best_chain = min(keep, key=off)
        else:
            best_chain = max(keep, key=len)
        if len(best_chain) < _min_chain:
            continue
        vals = [(val(s), s["cy"]) for s in best_chain]
        a, b = _fit(vals)
        if abs(b) < 1e-9:
            continue
        ys = [y for _, y in vals]
        out.append({"x": float(np.mean([s["cx"] for s in best_chain])),
                    "a": a, "b": b, "n": len(best_chain),
                    "y_lo": min(ys), "y_hi": max(ys)})
    # A value axis is labelled the full height of the plot. IFS also numbers
    # the EVENT MARKERS down the right-hand side, 1..N, and once an interval
    # runs past sixteen events four of those numbers ("17 18 19 20") sit in
    # their own column, evenly spaced, arithmetic — indistinguishable from a
    # tick ladder except that they cover a fifth of the frame. On 00001
    # interval 3 (41 events) that phantom column took axis B, which pushed
    # Slurry Rate onto a 17..20 scale and BOTH concentrations onto the rate
    # axis: WH Prop Conc came back as 16.59 kg/m3 on a 0..16 scale (#77).
    if out and not ocr:
        tallest = max(c["y_hi"] - c["y_lo"] for c in out)
        out = [c for c in out if c["y_hi"] - c["y_lo"] >= 0.6 * tallest]
    elif out:
        # Same guard, measured differently, because OCR breaks its premise.
        # "Labelled the full height" assumes the labels are all there; OCR
        # found 3 of the rate axis' 5 on 00148 p136, so it spanned 164.9
        # against a 197.6 threshold and was thrown away — after which axis B
        # inherited the CONCENTRATION column and Slurry Rate read 628 against
        # a printed 0..20.
        #
        # What actually separates an axis from a marker ladder is where it
        # reaches ZERO. Every real axis on that page extrapolates to within a
        # fraction of a point of the same span — A 329.3, B 329.8, C 329.4,
        # because they all run the height of one frame — while #77's phantom
        # column of event numbers 17..20, stepping by one over a fifth of the
        # frame, would have to run about 440 to reach zero. The reference is
        # the column with the MOST ticks, which is the best-evidenced fit on
        # the page.
        def _zero_span(c):
            if abs(c["b"]) < 1e-9:
                return c["y_hi"] - c["y_lo"]
            ys = (c["y_lo"], c["y_hi"], -c["a"] / c["b"])
            return max(ys) - min(ys)

        ref = _zero_span(max(out, key=lambda c: c["n"]))
        if ref > 0:
            out = [c for c in out if 0.8 <= _zero_span(c) / ref <= 1.25]
    out.sort(key=lambda c: c["x"])
    return out


_CLOCK = re.compile(r"\d{1,2}:\d{2}(:\d{2})?")

# How wide the clock labels' band is. 16pt clears "07:00" at this template's
# 6pt type and stops short of the axis DATE printed on the line below — on
# 00973 p107 the clock sits at page x 482 and "2021-09-01" at 489.4, and a
# crop that takes both reads "©0700"" for the label it should read "07:00".
_CLOCK_BAND = 16.0


def _clock_secs(text):
    """'06:20' / '05:54:20' -> seconds since midnight."""
    parts = [int(p) for p in text.split(":")]
    sec = parts[2] if len(parts) > 2 else 0
    return parts[0] * 3600 + parts[1] * 60 + sec


def _unwrap_midnight(vals):
    """[(secs, position)] in position order, with midnight added back on."""
    out = list(vals)
    for i in range(1, len(out)):
        if out[i][0] < out[i - 1][0] - 20000:
            out[i] = (out[i][0] + 86400, out[i][1])
    return out


def _clock_bands(page, spans, box):
    """The page-x bands the clock row may sit in, as clip rects.

    Two, because neither one alone finds it on every page and they cost one
    OCR each on a page that has already failed:

      - the labels the page pass DID read say where the row is, which is the
        only anchor on a page whose plot frame was not found. 00973 p133 and
        p214 are read this way and no other.
      - the plot frame's far edge, for the pages where the page pass read a
        label so badly that its box is the wrong shape: 00973 p208 and 00971
        p222 give up two labels to the first band and four to this one.
    """
    out = []
    clocks = [s for s in spans if _CLOCK.fullmatch(s["t"])]
    if clocks:
        # the MEDIAN box, not the union: one badly-shaped reading widens the
        # union enough to sweep the date line in, which is what the band is
        # drawn narrow to avoid
        mid = sorted((s["x0"] + s["x1"]) / 2 for s in clocks)[len(clocks) // 2]
        out.append(fitz.Rect(mid - _CLOCK_BAND / 2, 0,
                             mid + _CLOCK_BAND / 2, page.rect.y1))
    if box is not None:
        out.append(fitz.Rect(box.x1 + 1, box.y0,
                             box.x1 + 1 + _CLOCK_BAND, box.y1))
    return out


def _ladder_only(readings):
    """The readings that sit on the row's own straight line. -> [] or subset

    `readings` is [(position, "HH:MM")] for one crop of the clock band.

    A clock axis is evenly spaced by construction, so a label off the line is
    a misread digit and not an unusual axis. The crops earn this guard: 00973
    p223 comes back 19:00, 19:20, 19:40 and then "29:00" where the page
    prints 20:00, and 00971 p164 reads "95:20" for 05:20. Nine hours of error
    in one label moves the whole fit, and the axis is what dates every row
    the chart exports.

    Same shape as auto_raster.fit_ticks — every pair seeds a line and the
    line with the most readings on it wins — but it has to work on three
    readings, which fit_ticks will not look at. p223 loses the one bad label
    and keeps its three; p164 has only three and cannot spare one, so nothing
    survives and the page stays a failure a reader can see.
    """
    if len(readings) < 3:
        return []
    ordered = sorted(readings, key=lambda r: r[0])
    vals = _unwrap_midnight([(_clock_secs(t), x) for x, t in ordered])
    gaps = sorted(abs(vals[k][1] - vals[k - 1][1])
                  for k in range(1, len(vals)))
    gap = gaps[len(gaps) // 2]
    if gap <= 0:
        return []
    best = []
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            dx = vals[j][1] - vals[i][1]
            if abs(dx) < 1e-6:
                continue
            b = (vals[j][0] - vals[i][0]) / dx
            if b <= 0:                      # time runs left to right
                continue
            a = vals[i][0] - b * vals[i][1]
            # a quarter of one label-to-label step: wide enough for a box
            # centre that OCR put a point or two out, far too narrow for an
            # hour digit read wrong
            tol = 0.25 * b * gap
            on = [k for k, (v, x) in enumerate(vals)
                  if abs(a + b * x - v) <= tol]
            if len(on) > len(best):
                best = on
    if len(best) < 3:
        return []
    return [ordered[k] for k in best]


def _clock_strip_spans(page, rotated, spans, box):
    """Span dicts for the time labels, re-read from their own band. -> []

    Only for a chart drawn sideways, which is the layout every OCR'd IFS
    filing in this corpus uses; an upright one is left to the page pass
    rather than handled untested. Each candidate band is read and checked on
    its own and the one that survives with the most labels wins — they are
    two crops of ONE row, not two rows.
    """
    if not rotated:
        return []
    best = []
    for clip in _clock_bands(page, spans, box):
        got = _ladder_only([(_unrotate(x, y)[0], t)
                            for x, y, t in
                            ocr_labels.rotated_clock_strip(page, clip)])
        if len(got) > len(best):
            best = got
    # The row keeps the y the page pass gave it, so that _axis_date still
    # looks for the date on the line below the clock and not somewhere else.
    cy = _clock_row_cy(spans)
    return [{"t": t, "cx": cx, "cy": cy, "ocr": True,
             "x0": 0.0, "x1": 0.0, "color": 0} for cx, t in best]


def _clock_row_cy(spans):
    """Where the page pass put the clock row, or a band-free default."""
    clocks = [s for s in spans if _CLOCK.fullmatch(s["t"])]
    if not clocks:
        return 0.0
    return sorted(s["cy"] for s in clocks)[len(clocks) // 2]


def _time_axis(spans):
    """HH:MM(:SS) labels row -> seconds = a + b * x, plus start date if shown."""
    tspans = [s for s in spans if _CLOCK.fullmatch(s["t"])]
    if len(tspans) < 3:
        return None, ""
    # keep the y-row with the most time labels (legend times would be rare)
    rows = defaultdict(list)
    for s in tspans:
        rows[round(s["cy"] / 6)].append(s)
    row = max(rows.values(), key=len)
    if len(row) < 3:
        return None, ""
    row.sort(key=lambda s: s["cx"])
    vals = _unwrap_midnight([(_clock_secs(s["t"]), s["cx"]) for s in row])
    a, b = _fit(vals)
    if b <= 0:
        return None, ""
    date = _axis_date(spans, row)
    return (a, b), date


# Two printed forms, one place. The BC filings label the axis "3/3/2019"; the
# AER Montney ones print ISO, "2021-10-27" — and only the slash form was read,
# so every HAL-2 vector chart in that set came through with NO date. Carmine,
# #575: "not showing date times for these HAL-2 vector time it does for the
# image one HAL-1 type !!!!". He is comparing against Hal-1 raster, which
# dates itself off the document's EVENT LOG; IFS has no such cascade and never
# needed one, because the date is printed right there on the chart.
#
# Where it sits, measured on 00328 p102/p103/p107: one row under the clock
# labels (y 486.3 against 474.2) and TWICE — once at the left end of the
# plotted window and once at the right. So the label is anchored to the axis
# row rather than hunted across the page, and the LEFT one wins, because that
# is where the chart starts and what start_time is counted from. A page-wide
# scan would let a header or a footer date outrank the axis.
#
# The slash form is deliberately NOT widened to accept day-first. This same
# document prints "14/11/2021" and "27/10/2021" on p91/p97, which are plainly
# D/M, so a general slash rule would have to guess which half is the month —
# and a wrong guess moves a stage to another month in silence. ISO cannot be
# misread, and the M/D branch keeps its reading on the filings it was written
# for.
#
# What it does NOT keep is emitting a month it just read as 14. "14/11/2021"
# used to come out "2021-14-11": a string that is truthy, so start_time was
# then computed off it, that no calendar accepts, and that reaches the CSV's
# DATETIME column and FracView's clock as garbage rather than as absence. A
# date that cannot exist is not a date. Rejected, not swapped — swapping would
# read the unambiguous ones day-first while still reading "3/4/2021" the other
# way round, which is a worse answer than no answer.
_D_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_D_MDY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _mdy(m):
    """'3/3/2019' -> '2019-03-03'. '' when the fields cannot be a date."""
    mon, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mon <= 12 and 1 <= day <= 31):
        return ""
    return f"{yr:04d}-{mon:02d}-{day:02d}"


def _iso(m):
    """'2021-09-01' -> '2021-09-01'. '' when the fields cannot be a date.

    The M/D form has always been validated through _mdy and the ISO form was
    pasted straight through, so a misread digit left the module by the front
    door: 00971 p134 exports 2051-00-02 and p157 2021-00-03 — month zero, into
    the CSV's DATETIME column, on pages that extract cleanly. The same range
    test _mdy applies is applied here, so a mangled ISO label is refused and
    the page falls back to whatever else it prints, exactly as a mangled M/D
    label already did.
    """
    yr, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mon <= 12 and 1 <= day <= 31):
        return ""
    return f"{yr:04d}-{mon:02d}-{day:02d}"


def _start_stamp(label_date, t_min_all):
    """(date, start_time) for a chart's first sample. -> ('YYYY-mm-dd', 'HH:MM:SS')

    `label_date` is what the axis PRINTS and `t_min_all` is the first sample's
    offset in the tick fit's own seconds, midnight already unwrapped — so it
    goes negative when the data starts before the first tick, and past 86400
    when it starts after the last midnight the axis crossed. Floor-dividing by
    a day is therefore the whole correction, and the clock below has always
    been right: Python's floor semantics already turn -305 into 23:54:55.
    """
    shift = int(t_min_all // 86400)
    if shift:
        label_date = (datetime.strptime(label_date, "%Y-%m-%d")
                      + timedelta(days=shift)).strftime("%Y-%m-%d")
    h = int(t_min_all // 3600) % 24
    mnt = int(t_min_all % 3600 // 60)
    s = int(t_min_all % 60)
    return label_date, f"{h:02d}:{mnt:02d}:{s:02d}"


def _axis_date(spans, row):
    """The date printed under the time axis. -> 'YYYY-mm-dd' or ''."""
    row_cy = sum(s["cy"] for s in row) / len(row)
    found = []
    for s in spans:
        if not 0 < s["cy"] - row_cy < 40:      # the row directly beneath
            continue
        m = _D_ISO.fullmatch(s["t"])
        if m and _iso(m):
            found.append((s["cx"], _iso(m)))
            continue
        m = _D_MDY.fullmatch(s["t"])
        if m and _mdy(m):
            found.append((s["cx"], _mdy(m)))
    if found:
        return min(found)[1]
    # Unchanged fallback: the filings this was written for are still read the
    # way they always were, even if their label does not sit under the axis.
    for s in spans:
        m = _D_MDY.fullmatch(s["t"])
        if m and _mdy(m):
            return _mdy(m)
    return ""


# OCR mangles the superscript in a unit — "m³/min" comes back "m/min" and
# "kg/m³" as "kg/m?". These are the only two units an IFS treatment legend
# prints for these channels, so the repair is a lookup and not a guess.
_OCR_UNITS = {"m/min": "m3/min", "m?/min": "m3/min", "m3/min": "m3/min",
              "kg/m?": "kg/m3", "kg/m": "kg/m3", "kg/m3": "kg/m3"}


def _ocr_legend_spans(spans):
    """Rebuild whole legend entries from OCR words. -> (named, letters).

    A PDF writes "Treating Pressure (MPa)" as ONE span and _legend matches on
    exactly that shape. OCR returns 'Treating', 'Pressure', '(MPa)' and the
    axis letter as four words, so nothing matched and 00148 failed with
    "legend not found" on all 116 of its chart pages.

    An entry is the words of ONE COLOUR on ONE ROW, in reading order, and the
    colour is what keeps two entries printed side by side apart — the legend
    has two columns, and on 00148 p136 the red "Treating Pressure" and the
    magenta "Backside Pressure" share a row at cy 98. The trailing token is
    the axis letter, which OCR renders as "B_" or "Cc" often enough that it
    is taken as a letter followed by noise rather than matched exactly.
    """
    # Cluster the rows, do not bucket them: OCR puts the words of one line
    # within a point or two of each other, and rounding cy to a fixed grid
    # SPLITS a row whenever it straddles a boundary. The red row's words came
    # back at cy 99.2, 97.9, 99.0 and 97.9 — one grid step apart — and the
    # entry was lost while the teal row two lines down survived by luck.
    by_colour = defaultdict(list)
    for s in spans:
        if s["color"] == 0:
            continue
        by_colour[s["color"]].append(s)
    rows = {}
    for colour, items in by_colour.items():
        for s in sorted(items, key=lambda x: x["cy"]):
            hit = next((k for k in rows
                        if k[0] == colour and abs(k[1] - s["cy"]) <= 4.0), None)
            rows.setdefault(hit or (colour, s["cy"]), []).append(s)
    named, letters = [], []
    for (colour, _band), items in rows.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda s: s["cx"])
        letter = None
        m = re.match(r"^([A-F])[^A-Za-z0-9]?[a-z]?$", items[-1]["t"])
        if m and len(items) > 2:
            letter = dict(items[-1], t=m.group(1))
            items = items[:-1]
        text = " ".join(x["t"] for x in items)
        m = re.match(r"(.+?)\s*\(([^)]*)\)\s*$", text)
        if not m:
            continue
        unit = _OCR_UNITS.get(m.group(2).strip(), m.group(2).strip())
        named.append(dict(items[0], t=f"{m.group(1).strip()} ({unit})",
                          cx=items[0]["cx"], color=colour))
        if letter:
            letters.append(letter)
    return named, letters


# A legend's axis letter is ONE character, and the whole-page OCR pass does
# not return isolated single characters: on 00973 p108 the six coloured
# letters "A B A A B A" the page draws at (93..191, 120..131) come back as
# nothing at all, while every name word on the same rows reads at confidence
# 89-96. Every entry then had no letter, every entry was dropped for want of
# one, and the page failed outright with "legend not found" (#699, #711).
#
# The letters have not been lost, only unread: like every other string in
# this filing they are drawn as filled glyph outlines, and a crop of one,
# read on its own, comes back right. So the letter is READ off the page, and
# nothing here infers one.
_GLYPH_MAX = 24.0   # pt. A legend character is ~11pt tall on these pages;
                    # the colour swatch rule on the same row is 161pt long
                    # (00973 p109) and a curve or frame longer still.
_GLYPH_MIN = 2.0    # pt. Below this it is a speck of chart ink, not a glyph.


def _glyph_letters(page, rows, rotated):
    """{row index: axis letter} for legend rows whose letter OCR never read.

    A candidate is a filled outline in the ROW'S OWN COLOUR, one character
    in size, on that row and to the right of its name, which the whole-page
    OCR pass did not already read as part of a word. That last test is what
    keeps the glyphs of the NAME itself out — every one of those sits inside
    an OCR word box, and on 00973 p108 the name "Optikleen-WF Conc (kg/m3)"
    is 20 such glyphs on the same row in the same ink as its letter.

    A row with more than one unread glyph is left alone, and so is a crop
    that does not read as a single A-F character. Which of two glyphs is the
    axis letter would be a guess, and a guess here is this reader's worst
    failure: a series read off the wrong ladder exports a plausible wrong
    number (#699). A row that keeps no letter is dropped downstream, and a
    missing channel is the honest answer.
    """
    if not rows or not ocr_labels.available():
        return {}
    try:
        read = [fitz.Rect(w["rect"]) for w in ocr_labels.words(page)]
    except Exception:
        return {}
    cands = defaultdict(list)
    for rect, rgb in _outline_colours(page):
        if not (_GLYPH_MIN <= rect.width <= _GLYPH_MAX
                and _GLYPH_MIN <= rect.height <= _GLYPH_MAX):
            continue
        if any(r.intersects(rect) for r in read):
            continue
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        if rotated:
            cx, cy = _unrotate(cx, cy)
        for i, s in enumerate(rows):
            # Black is the page's structural ink — frame, grid, ticks, tick
            # digits — so an unread black glyph on a row is as likely to be a
            # tick mark as a letter. The one black-named series this module
            # accepts is already the case it says it cannot separate by
            # colour, and it is not given a letter here either.
            if not s["color"]:
                continue
            # same ink, same row, right of the name: the geometry _legend
            # already requires of a letter span it can see
            if rgb == s["color"] and abs(cy - s["cy"]) <= 4 and cx > s["cx"]:
                cands[i].append(rect)
    # A page can overprint its own artwork: 00973 p203 draws every legend
    # letter twice at bit-identical coordinates, and 541 of its 1163 filled
    # paths are exact duplicates. Counting the second copy as a rival
    # candidate refused three otherwise perfect pages. Two marks at the SAME
    # place in the SAME ink are one mark and cannot disagree about the
    # letter; one anywhere else still refuses the row.
    single = {}
    for i, v in cands.items():
        if len({(r.x0, r.y0, r.x1, r.y1) for r in v}) == 1:
            single[i] = v[0]
    if not single:
        return {}
    order = sorted(single)
    # the rotated build draws its text bottom-to-top, which is the direction
    # _unrotate assumes for it as well
    direction = (0.0, -1.0) if rotated else (1.0, 0.0)
    try:
        texts = ocr_labels.span_texts(
            page, [(tuple(single[i]), direction) for i in order])
    except Exception:
        return {}
    out = {}
    for i, t in zip(order, texts):
        t = (t or "").strip()
        # exact, not _axis_letter's tolerant match: the crop holds one glyph
        # and nothing else, so anything but one letter means it was not read
        if re.fullmatch(r"[A-Fa-f]", t):
            out[i] = t.upper()
    return out


def _legend(spans, page=None, rotated=False):
    """[(series_name, unit, color_int, axis_letter)] from legend rows.

    `page`, when given, lets a row whose axis letter OCR never returned have
    that letter read off the page's own glyph outlines — see _glyph_letters.
    """
    out = []

    orphans = []                      # entries whose axis letter OCR lost
    orphan_rows = []                  # the legend span each orphan came from

    def add(s, letters):
        m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", s["t"])
        if not m or len(m.group(1).strip()) < 3:
            return
        name, unit = m.group(1).strip(), m.group(2).strip()
        # the axis letter of the same color on (nearly) the same line
        best, bestd = None, 1e9
        for l in letters:
            if l["color"] != s["color"]:
                continue
            d = abs(l["cy"] - s["cy"])
            if d < 4 and l["cx"] > s["cx"] and (l["cx"] - s["cx"]) < bestd:
                best, bestd = l["t"], l["cx"] - s["cx"]
        if best:
            out.append((name, unit, s["color"], best))
        else:
            orphans.append((name, unit, s["color"]))
            orphan_rows.append(s)

    named = [s for s in spans if s["color"] != 0 and
             re.search(r"\(([^)]+)\)\s*$", s["t"]) and len(s["t"]) > 8]
    letters = [s for s in spans if s["color"] != 0 and re.fullmatch(r"[A-F]", s["t"])]
    if not named and any(s.get("ocr") for s in spans):
        named, letters = _ocr_legend_spans(spans)
    for s in named:
        add(s, letters)

    # one black series (e.g. N2 Standard Rate) has a black name + black axis
    # letter. Accept it only when exactly one such black-named series exists,
    # since black curves share ink and can't be separated by colour.
    black_named = [s for s in spans if s["color"] == 0 and "IFS" not in s["t"]
                   and re.fullmatch(r".{3,}?\s*\([A-Za-z][^)]{0,9}\)", s["t"])]
    if len(black_named) == 1:
        black_letters = [s for s in spans if s["color"] == 0 and re.fullmatch(r"[A-F]", s["t"])]
        add(black_named[0], black_letters)
    # Read before inferring. _adopt_orphans below reasons from the units and
    # from which axes are still unclaimed; a letter the page itself prints
    # beats either, so it goes first. Only an OCR'd page pays for it — on a
    # page with a text layer the letters are spans and are already matched.
    if orphans and page is not None and any(s.get("ocr") for s in spans):
        found = _glyph_letters(page, orphan_rows, rotated)
        keep = []
        for i, (name, unit, colour) in enumerate(orphans):
            if i in found:
                out.append((name, unit, colour, found[i]))
            else:
                keep.append(i)
        orphan_rows[:] = [orphan_rows[i] for i in keep]
        orphans[:] = [orphans[i] for i in keep]
    _adopt_orphans(out, orphans, spans)
    return out


def _adopt_orphans(out, orphans, spans):
    """Give a legend entry back the axis letter OCR dropped.

    An entry with no letter is discarded, and on an OCR'd page that is how a
    channel disappears while its neighbours read perfectly: 00973 p117 prints
    four series and OCR returns the letter for only two, so Slurry Rate and
    BH Proppant Conc were dropped and the chart came back with pressure alone
    (#709, #711).

    Two pieces of evidence, neither of them the missing letter itself:

      - an entry measured in the same UNIT as one that DID keep its letter is
        plotted against that same axis. A page has one concentration ladder,
        not one per concentration.
      - failing that, if exactly one axis the PAGE prints is still unclaimed
        and exactly one entry still wants one, they are each other's.

    Anything less certain is left alone: a wrong axis is worse than a missing
    channel, because it exports a number that looks reasonable.
    """
    if not orphans:
        return
    by_unit = {}
    for name, unit, _c, ax in out:
        by_unit.setdefault(_norm_unit(unit), ax)
    still = []
    for name, unit, colour in orphans:
        ax = by_unit.get(_norm_unit(unit))
        if ax:
            out.append((name, unit, colour, ax))
        else:
            still.append((name, unit, colour))
    if len(still) != 1:
        return
    page_letters = set()
    for s in spans:
        if s["color"] != 0:
            continue
        letter = _axis_letter(s["t"])
        if letter:
            page_letters.add(letter)
    free = sorted(page_letters - {ax for *_x, ax in out})
    if len(free) == 1:
        name, unit, colour = still[0]
        out.append((name, unit, colour, free[0]))


def _norm_unit(unit):
    """OCR mangles the superscript, so kg/m3, kg/m? and kg/m* are one unit."""
    return re.sub(r"[^a-z/]", "", (unit or "").lower())


def _color_close(stroke, legend_int):
    lr = ((legend_int >> 16) & 255) / 255
    lg = ((legend_int >> 8) & 255) / 255
    lb = (legend_int & 255) / 255
    return sum((a - b) ** 2 for a, b in zip(stroke, (lr, lg, lb))) < 0.02


def _pen_resample(t, v, spans, samples, sample_sec=1.0):
    """Stroked segments -> the sample grid, WITHOUT inventing anything.

    frac_core._resample is written for MView, where every series is drawn
    across the whole plot and the chart merely omits the leading flatline. It
    does two things that are wrong on an IFS page:

      * np.interp draws a straight line across ANY hole in the curve. An IFS
        concentration series is pen-down only while proppant is being pumped,
        so the hole is most of the interval and the export carried a straight
        ramp through it — Carmine's "straight line extending past the chart"
        (#75-#77) and "pen up down issues" (#65);
      * it holds the first value back to t=0. The grid starts when the FIRST
        series starts (pressure), so a concentration curve that begins 38
        minutes later was exported as a flat line at its opening value for
        those 38 minutes — 00001 stage 1 drew exactly that at 0.19 kg/m3.

    A segment IS the pen being down, so the union of the segments' time spans
    is where this series has data. Everything else is blank, which the
    exporter writes as an empty cell.
    """
    uniq, inv = np.unique(np.round(t, 6), return_inverse=True)
    vu = np.bincount(inv, weights=v) / np.bincount(inv)
    out = np.interp(samples, uniq, vu, left=np.nan, right=np.nan)
    if not len(spans):
        return out
    tol = max(float(sample_sec), 1.0)
    order = np.argsort(spans[:, 0], kind="stable")
    cov = np.zeros(len(samples), dtype=bool)
    lo, hi = spans[order[0]]
    for a, b in spans[order[1:]]:
        if a <= hi + tol:                     # same pen-down stretch
            hi = max(hi, b)
            continue
        cov |= (samples >= lo - tol) & (samples <= hi + tol)
        lo, hi = a, b
    cov |= (samples >= lo - tol) & (samples <= hi + tol)
    out[~cov] = np.nan
    return out


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {column: values}, channel_info) for an IFS chart page."""
    rotated = page_rotated(page)
    spans = _spans(page, rotated)
    text = _page_text(page)
    vis_cut, vis_box = visible_plot_box(page)
    tfit, date = _time_axis(spans)
    if tfit is None and any(s.get("ocr") for s in spans):
        # The page pass reads the whole sheet at one resolution and one turn,
        # and on this template it loses clock labels to the date line printed
        # under them: 00973 p107 prints 06:00/06:20/06:40/07:00 and the pass
        # returned two of them, which is one short of an axis. The interval
        # was not reported as failed either — the pipeline gate wants three
        # clock labels before it calls this at all — so Interval 1 simply
        # produced nothing (#699, #711).
        #
        # The band is re-read on its own, and it REPLACES the page pass's
        # reading of the same labels rather than joining it. They are two
        # readings of one row, and the page pass's is the one that just
        # failed: 00973 p112 read "41:00" for 11:00, and averaging that into
        # the fit would have made a clock 30 hours wide out of a chart that
        # runs an hour.
        strip = _clock_strip_spans(page, rotated, spans, vis_box)
        if strip:
            tfit, date = _time_axis(
                strip + [s for s in spans if not _CLOCK.fullmatch(s["t"])])
    if tfit is None:
        raise ValueError("IFS: time axis labels not found")
    ta, tb = tfit
    legend = _legend(spans, page, rotated)
    if not legend:
        raise ValueError("IFS: legend not found")
    columns = _axis_columns(spans, vis_box)
    if not columns:
        raise ValueError("IFS: no axis tick columns")
    # axis letters -> columns: A = leftmost; remaining right-side columns in
    # x order take B, C, D...  (IFS convention)
    letters_used = sorted({ax for *_, ax in legend})
    mapping = {}

    # ...except that the page SAYS which column is which. IFS prints the axis
    # letter directly above its own tick column — on 00148 p136 a black "A" at
    # cx -700 over the pressure ladder and a black "B" at cx -133 over the
    # rate — and reading that beats inferring it from left-to-right order.
    # Order is what put Slurry Rate on the concentration axis at 628 against a
    # printed 0..20: OCR had dropped the rate column entirely, so "B" became
    # whatever happened to be second. A letter matched to the column beneath
    # it cannot slide like that, and a letter with no column near it maps to
    # nothing, which is the honest answer.
    placed = {}
    for s_ in spans:
        if s_["color"] != 0:
            continue
        letter = _axis_letter(s_["t"])
        if letter is None:
            continue
        near = min(columns, key=lambda c: abs(c["x"] - s_["cx"]))
        if abs(near["x"] - s_["cx"]) <= 40:
            placed.setdefault(letter, near)
    for ax in letters_used:
        if ax in placed:
            mapping[ax] = placed[ax]
    if len(mapping) == len(letters_used):
        pass                                # the page named every one of them
    elif "A" in letters_used and "A" not in mapping:
        mapping["A"] = columns[0]
    rest = [ax for ax in letters_used if ax != "A" and ax not in mapping]
    right = [c for c in columns[1:] if c not in mapping.values()] or \
        [c for c in columns if c not in mapping.values()]
    for i, ax in enumerate(rest):
        if i >= len(right):
            # There is no column for this letter. The clamp that used to sit
            # here — right[min(i, len(right) - 1)] — pinned every surplus
            # letter to the LAST column, which on an OCR'd page silently read
            # the rate and the concentration off the PRESSURE axis: 00148 p136
            # returned Slurry Rate 62.8 against a printed 0..20 and BH Prop
            # Conc 22.7 against 0..1000, both of which are exactly their true
            # value as a percentage of full scale on A. A peak outside its own
            # axis is this project's clearest tell that something not on the
            # curve is being read as data, and the guard has to refuse rather
            # than guess. The channel is dropped; the chart keeps what it can
            # prove.
            if any(x.get("ocr") for x in spans):
                continue
            mapping[ax] = right[-1]
            continue
        mapping[ax] = right[i]
    legend = [e for e in legend if e[3] in mapping]
    if not legend:
        raise ValueError("IFS: no legend series could be tied to an axis")

    # collect stroked SEGMENTS per legend color. Segments, not loose points:
    # a segment is one stretch of pen-down, and the union of their time spans
    # is the only honest statement of where this series has data at all. See
    # _pen_resample.
    pts_by_color = defaultdict(list)
    for _i, d in enumerate(page.get_drawings()):
        # ink drawn before the last full-plot white fill is painted over and
        # never seen by a reader — see visible_plot_box
        if _i < vis_cut:
            continue
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        if r.width < 10 and r.height < 10:
            continue                       # event-marker glyphs, not curves
        for name, unit, cint, ax in legend:
            if _color_close(c, cint):
                lst = pts_by_color[cint]
                for item in d["items"]:
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        if cint == 0:
                            # black series shares ink with axes/grid: drop long
                            # axis-aligned segments (frame + gridlines)
                            if (abs(p1.x - p2.x) < 0.01 or abs(p1.y - p2.y) < 0.01) and \
                               max(abs(p1.x - p2.x), abs(p1.y - p2.y)) > 5:
                                continue
                        pp = [(p1.x, p1.y), (p2.x, p2.y)]
                    elif item[0] == "c":
                        pp = [(item[1].x, item[1].y), (item[4].x, item[4].y)]
                    else:
                        continue
                    if rotated:
                        pp = [_unrotate(x, y) for x, y in pp]
                    lst.append(pp)
                break

    # plot time-range: clip to the plot FRAME, not the time-label span. IFS
    # (like BJ/Liberty) insets its first/last time labels from the frame
    # edges, so each interval's opening ramp sits between the frame and the
    # first labeled gridline and a label-based window clips it. The frame is
    # the outermost full-height vertical gridlines (in the unrotated frame);
    # the per-column value band and legend-color match already exclude
    # off-plot strokes, so widening to the frame only recovers real points.
    t_row = [s for s in spans if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    lab_lo = min(s["cx"] for s in t_row)
    lab_hi = max(s["cx"] for s in t_row)
    vgrid = []
    for d in page.get_drawings():
        if d.get("color") is None or d["type"] not in ("s", "fs"):
            continue
        for item in d["items"]:
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            ax, ay = (_unrotate(p1.x, p1.y) if rotated else (p1.x, p1.y))
            bx, by = (_unrotate(p2.x, p2.y) if rotated else (p2.x, p2.y))
            if abs(ax - bx) < 0.6 and abs(ay - by) > 100:
                vgrid.append((ax + bx) / 2)
    if vgrid:
        # never narrower than the old label-based window (stay a superset)
        x_lo = min(min(vgrid) - 2, lab_lo - 30)
        x_hi = max(max(vgrid) + 2, lab_hi + 30)
    else:
        x_lo, x_hi = lab_lo - 30, lab_hi + 30

    meta = PageMeta()
    m = re.search(r"UWI:\s*(1[0-9A-F]\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups())
    # An interval identifier is not always a bare number: 00001 files a re-frac
    # of interval 4 as "Interval 4A" and its first treatment as "Interval 4".
    # Reading only the digits gave both charts stage "4", so two distinct
    # treatments merged under one key and one of them was lost \u2014 the same
    # defect class as BJ's "Stage 06 Plug Slip" and Canyon's re-attempts. The
    # trailing lookahead keeps a longer number from being cut short: "Interval
    # 1234" fails to match rather than reporting interval 123.
    m = re.search(r"Interval\s+(\d{1,3}[A-Za-z]?)(?![A-Za-z0-9])", text)
    if m:
        meta.stage = m.group(1)
    meta.date = date
    t = re.search(r"Interval\s+\d{1,3}[A-Za-z]?\s*[-\u2013\u2014]\s*[A-Za-z ]+", text)
    _head = text.strip().splitlines()
    meta.title = (t.group(0).strip() if t
                  else " ".join(_head[0].split()) if _head else "")[:60]

    # The PLOT FRAME, in the same coordinates the points are read in. Every
    # tick column brackets the same frame vertically except where its labels
    # stop short of it, so the median pair is the frame and an individual
    # column's extent is not.
    used = []
    for c in mapping.values():
        if c not in used:
            used.append(c)
    lo_s = sorted(c["y_lo"] for c in used)
    hi_s = sorted(c["y_hi"] for c in used)
    v_top = float(lo_s[len(lo_s) // 2])
    v_bot = float(hi_s[len(hi_s) // 2])
    if v_bot < v_top:
        v_top, v_bot = v_bot, v_top

    t_min_all, t_max_all = None, None
    series = {}
    series_axis = {}                 # (name, unit) -> the tick column it reads
    info = {}
    for name, unit, cint, ax in legend:
        segs = pts_by_color.get(cint)
        col = mapping.get(ax)
        if not segs or col is None:
            continue
        # Clip to the FRAME, not to this column's own tick extent ±12pt. That
        # slack was wrong in both directions on every IFS file sampled:
        #  - too generous above. The legend key is drawn in the series' own
        #    colour a few points above the frame, so its swatch line entered
        #    the data as two points at a value ABOVE the axis maximum — which
        #    is how 00001 stage 1 reported WH Prop Conc 829.85 on a 0..800
        #    scale (#75), and why the Lab drew a straight line diving in from
        #    off the top of the chart: np.interp ran from that phantom point
        #    to the first real one.
        #  - too strict below. The concentration column labels 100..800, so
        #    y_hi is the 100 gridline and everything the curve does under
        #    ~44 kg/m3 fell outside the window: 622 and 704 real points cut
        #    from the two concentration series on that page alone, each cut
        #    leaving a hole np.interp then bridged with a straight line.
        arr = np.array(segs, dtype=float)          # (m, 2, 2)
        inside = ((arr[:, :, 0] >= x_lo) & (arr[:, :, 0] <= x_hi) &
                  (arr[:, :, 1] >= v_top - 2) & (arr[:, :, 1] <= v_bot + 2))
        arr = arr[inside.all(axis=1)]
        if arr.size < 60:
            continue
        t = ta + tb * arr[:, :, 0]
        v = col["a"] + col["b"] * arr[:, :, 1]
        span = np.stack([t.min(axis=1), t.max(axis=1)], axis=1)
        t, v = t.reshape(-1), v.reshape(-1)
        order = np.argsort(t, kind="stable")
        series[(name, unit)] = (t[order], v[order], span)
        series_axis[(name, unit)] = col
        lo, hi = t.min(), t.max()
        t_min_all = lo if t_min_all is None else min(t_min_all, lo)
        t_max_all = hi if t_max_all is None else max(t_max_all, hi)
    if not series:
        raise ValueError("IFS: no series curves matched the legend colors")

    n = int(t_max_all - t_min_all)
    if not (60 < n < 100000):
        raise ValueError(f"IFS: implausible duration {n}s")
    meta.duration_min = n / 60.0
    samples = np.arange(int(n / sample_sec)) * sample_sec

    def std_name(raw):
        low = raw.lower()
        for keys, std in STD_NAMES:
            if any(k in low for k in keys):
                return std
        return raw[:24]

    # --- chart geometry in PAGE coordinates, for the Lab's synced view ---
    # Everything above works in the CANONICAL frame, which _unrotate maps a
    # 90°-filed page into: canonical x is page x when the page is filed
    # upright and page -y when it is filed rotated, and canonical y is page y
    # / page x to match. That is exactly the axis "x"/"y" distinction the Lab
    # encodes, so the rotated case is a sign flip on tb and nothing else.
    #
    # Two things this has to get right, both silent when wrong:
    #  - `ta` is relative to the STAGE start. The samples below begin at
    #    t_min_all, so quoting the absolute clock fit here would slide the
    #    backdrop by however far into the job this interval sat.
    #  - v0/v1 and every channel's axes_frame are read at the SAME page
    #    coordinates. Quoting a curve against its own tick extent while the
    #    page is placed by a different pair leaves it a constant distance off
    #    its own ink (the concentration column labels 100..800, not 0..800,
    #    so its extent is not the frame's).
    meta.geom = {"axis": "y" if rotated else "x",
                 "ta": float(ta - t_min_all),
                 "tb": float(-tb if rotated else tb),
                 "v0": v_top, "v1": v_bot}

    data, chinfo, axes, axes_frame = {}, {}, {}, {}
    for (name, unit), (t, v, span) in series.items():
        col = std_name(name)
        if col in data:
            continue
        vals = _pen_resample(t - t_min_all, v, span - t_min_all, samples,
                             sample_sec)
        data[col] = vals
        chinfo[col] = {"label": name, "unit": unit}
        acol = series_axis.get((name, unit))
        if acol:
            p_lo = acol["a"] + acol["b"] * acol["y_hi"]
            p_hi = acol["a"] + acol["b"] * acol["y_lo"]
            axes[col] = (float(min(p_lo, p_hi)), float(max(p_lo, p_hi)))
            axes_frame[col] = (float(acol["a"] + acol["b"] * v_top),
                               float(acol["a"] + acol["b"] * v_bot))
    # AN AXIS THAT CANNOT BELONG TO THIS CHANNEL. Checking the value against
    # the axis it was READ from cannot work — a mis-mapped channel is inside
    # that axis by construction, which is why 00148 p271's Slurry Rate of 721
    # sat happily within the 0..1000 it had been read against while the check
    # threw away 12 legitimate rates whose curves touch their own top tick.
    #
    # What IS knowable is that a slurry rate is never drawn on a 0..1000 axis.
    # These are the printed ranges this corpus actually uses — pressure 0..80
    # and 0..100, rate 0..20 and 0..24, concentration 0..1000 — widened well
    # past them so only an axis belonging to a DIFFERENT channel is refused.
    # Same idea as step1.impossible_axis, which does this for STEP.
    for col in list(data):
        rng = axes.get(col)
        if not rng:
            continue
        top = max(abs(rng[0]), abs(rng[1]))
        lim = {"Tr Press": (10.0, 300.0), "Backside Pressure": (10.0, 300.0),
               "GORV Press": (10.0, 300.0), "Slurry Rate": (2.0, 100.0),
               "BH Prop Conc": (50.0, 5000.0),
               "WH Prop Conc": (50.0, 5000.0)}.get(col)
        if lim and not (lim[0] <= top <= lim[1]):
            del data[col]
            chinfo.pop(col, None)
            axes.pop(col, None)
            axes_frame.pop(col, None)
    meta.axes = axes
    meta.axes_frame = axes_frame
    # start time of day for DATETIME column
    if meta.date:
        # The printed date labels the FIRST TICK, not the first sample, and a
        # stage that starts just before midnight is drawn with its ticks on
        # the next day. 00328 p227 is the case: ticks 00:00, 00:10, 00:20 all
        # labelled 2021-11-10, while the chart's own data begins 23:54:55 —
        # six minutes earlier, on the 9th. Read verbatim, that stage was filed
        # a day late, and one stage out of order is enough to make the whole
        # well's clock non-monotonic, which is exactly what sends FracView to
        # its synthetic axis and takes every void off the Real Time view.
        #
        # t_min_all is in the SAME seconds the tick fit produced, with midnight
        # already unwrapped, so it goes negative when the data starts before
        # the first tick. Its floor-division by a day IS the correction, and
        # the time below has always been right — Python's floor semantics
        # already turn -305 into 23:54:55. Only the date was missing the shift.
        meta.date, meta.start_time = _start_stamp(meta.date, t_min_all)
    return meta, samples, data, chinfo


# The treatment phases that count as a stage's own chart. "Breakdown",
# "Ball Action", "Stage Summary" and "Chemical Additives" are the other
# sections of the same interval and are not the treatment.
TREATMENT_PHASES = ("Main Treatment", "Entire Treatment")

_SECTION = re.compile(r"^(\d{1,2})\.(\d{1,2})$")


def section_stage(page):
    """-> (interval, phase) for IFS v4.2.0 pages, else None.

    v4.3.1 and v4.6.3 title the chart "Interval 7 – Main Treatment". v4.2.0
    names neither: it prints the section number and the phase on their own
    lines ("7.3" then "Main Treatment"), leaving the interval implied by the
    section's major number. The pipeline gate looked for the newer wording, so
    every chart in these reports was skipped and the file came back with no
    extractable data (Carmine's report on 00003).

    The phase must follow the section line — a bare "N.M" is also how this
    template prints ordinary measurements ("56.86"), and taking the first one
    on the page would match those.
    """
    try:
        lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    except Exception:
        return None
    for i, line in enumerate(lines[:-1]):
        m = _SECTION.match(line)
        if m and lines[i + 1] in TREATMENT_PHASES:
            return int(m.group(1)), lines[i + 1]
    return None
