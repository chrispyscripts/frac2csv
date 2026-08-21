"""Liberty Energy chart template (Lib-1 in Carmine's codes).

Rotated per-stage pages, one stage per page: each series has a COLORED
name span ("Treating Pressure (MPa)") and a matching colored tick row
(value along x). Time labels are date+HH:MM pairs along y, so absolute
time needs no midnight unwrapping. Structure is the Leucrotta family;
this template supplies Liberty's detection, metadata and time axis.
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta, _resample
import ocr_labels
import daily_ops
from leucrotta import _fit, _close, _spans as _text_spans

# Max seconds a time label may disagree with the gridline/frame-edge fit
# before that fit is rejected. Labels are minute-rounded and their gridline
# spacing is uneven by up to a minute, so this has to sit above 60.
FRAME_FIT_TOL = 75


# Liberty writes the stage token two ways: "Stage 13" on most filings and
# "STG 1" on the newer ones (01397/01398 title theirs "Upper Montney - STG 1").
# Only the spelling differs — same PRC/Chem Plot template underneath — so
# matching one and not the other cost those files every chart they had.
# The KEYWORD is case-insensitive; the capture groups that follow are not, on
# purpose — the second pattern below reads a trailing ALL-CAPS token as part of
# the stage name ("1A HRF"), so it cannot simply be given re.I. ARC's Alberta
# filings print "MIDDLE MONTNEY - STAGE 2" in caps and matched neither spelling,
# which left 32 of 56 charts on 00269 with no stage at all: they collapsed under
# one blank key and showed as a single "Stage ?" (#346).
_STAGE = r"(?i:Stage|STG)"


# The company renamed. Filings before it print "Liberty Oilfield Services LLC"
# and nothing else identifies them, so requiring "Liberty Energy" left 85 chart
# pages on 00313 unread and the whole file reporting no extractable data
# (#372-#375, and the same across the ARC Liberty set). Same template either
# way — only the name on the sheet changed.
_LIBERTY = re.compile(r"Liberty\s+(?:Energy|Oilfield)", re.I)


# Below this many characters the page is drawing its labels rather than
# writing them, and every gate in this module has to be asked of the render.
_OCR_TEXT_MIN = 40


def _page_text(page):
    """The page's text, OCR'd when it has none of its own.

    00913 is 198 pages of Liberty charts — "ARCRES HZ DOE 16-15-080-15 Stage
    10", four chemical concentrations, the time axis printed 2022/04/28 01:36
    to 02:16 — and 195 of those pages carry NOT ONE readable character. detect
    fired on 0 of 198 while the chart sat there in saturated vector art, so
    the whole file reported "no extractable data".
    """
    t = page.get_text()
    if len(t.strip()) > _OCR_TEXT_MIN or not ocr_labels.available():
        return t
    try:
        return ocr_labels.page_text(page) or t
    except Exception:
        return t


def _outline_colour(page):
    """[(rect, int_rgb)] for the filled paths that DRAW the glyphs.

    A Liberty legend is keyed by colour exactly as an IFS one is — the series
    name is printed in its own curve's ink — and OCR returns words with no
    colour. An outlined glyph is a filled path that still carries the colour
    the text had, so the word's colour is the dominant fill inside its box.
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


def _spans(page):
    """Text spans, from the page or — when it has none — from OCR."""
    out = _text_spans(page)
    if out or not ocr_labels.available():
        return out
    try:
        words = ocr_labels.words(page)
    except Exception:
        return out
    fills = _outline_colour(page)
    for w in words:
        t = (w.get("text") or "").strip()
        if not t:
            continue
        r = fitz.Rect(w["rect"])
        tally = defaultdict(int)
        for rect, rgb in fills:
            # CONTAINED in the word, not merely touching it. Legend entries
            # sit close together and a glyph from the neighbour overlaps the
            # box: sampling on intersection gave "CONC" of the green XE363
            # entry a RED colour and the red J475 entry a green one, which is
            # the difference between naming a channel and mislabelling it.
            inter = rect & r
            area = max(rect.width, 0.01) * max(rect.height, 0.01)
            iarea = max(inter.width, 0.0) * max(inter.height, 0.0)
            if iarea / area < 0.7:
                continue
            if rect.width > r.width or rect.height > r.height * 1.2:
                continue
            tally[rgb] += 1
        out.append({"t": t, "cx": (r.x0 + r.x1) / 2, "cy": (r.y0 + r.y1) / 2,
                    "color": (max(tally.items(), key=lambda kv: kv[1])[0]
                              if tally else 0),
                    "ocr": True})
    return out


# OCR mangles the superscript and the brackets: "(kg/m³)" comes back
# "(kg/m?)", "(L/m³)" as "{ Lim?)" or "(Lim". These are the only two units a
# Liberty chemical legend prints, so the repair is a lookup, not a guess.
def _fix_unit(txt):
    low = txt.lower()
    if "kg" in low:
        return "kg/m3"
    if "l" in low and "m" in low:
        return "L/m3"
    return txt.strip("()[]{} ")


def _ocr_legend_spans(spans):
    """Rebuild one 'NAME (unit)' span per colour from OCR words.

    lib1 keys the legend by COLOUR — a series' name is printed in its own
    curve's ink — and matches a single span shaped "NAME (unit)". OCR returns
    the words separately, so nothing matched and 00913's 88 charts came back
    "no extractable data".

    Colour is trustworthy here only because the sampler was fixed to count
    fills CONTAINED in a word rather than merely touching it. Before that the
    green entry's "CONC" came back red and the red entry's words came back
    green, and joining on colour would have swapped two channel names.

    ORIENTATION-FREE, and it has to be: extract_page swaps cx and cy for a
    chart whose time runs along X, so any rule phrased as "the legend sits
    above the ladders" reads the wrong axis on half the corpus and returned
    nothing at all. A legend word is simply a coloured span that is NOT part
    of a tick ladder — a ladder member has same-coloured numeric siblings
    lined up with it, and a legend word does not, whichever way the page is
    turned. That also recovers "475": OCR drops the J from "J475 CONC", and
    the bare number is a legend word precisely because no ladder claims it.
    """
    def _ladder(s_):
        if not re.fullmatch(r"-?[\d,]+(\.\d+)?", s_["t"]):
            return False
        return sum(1 for o in spans
                   if o is not s_ and o["color"] == s_["color"]
                   and re.fullmatch(r"-?[\d,]+(\.\d+)?", o["t"])
                   and (abs(o["cx"] - s_["cx"]) <= 12
                        or abs(o["cy"] - s_["cy"]) <= 12)) >= 2

    by = defaultdict(list)
    for s_ in spans:
        if s_["color"] == 0 or _ladder(s_):
            continue
        by[s_["color"]].append(s_)
    out = []
    for colour, items in by.items():
        if len(items) < 2:
            continue
        # A legend entry's words sit on ONE line. Anything else in the same
        # ink is not part of the name, and letting it in does more than add a
        # word: OCR turns a stroke of chart ink into "|" three hundred points
        # below the legend row, that outlier makes the vertical spread the
        # larger one, and the words get sorted DOWN the page instead of along
        # it. On a row they all share a coordinate, so that sort is a tie and
        # falls back to whatever order the spans arrived in — which is how
        # "475 CONC" reaches the CSV as "CONC 475" on 28 pages, and as a bare
        # "CONC" where the code word is lost with it.
        #
        # So find the line first and read along it. Whichever coordinate the
        # words agree on is the one they are lined up on.
        med = lambda k: sorted(x[k] for x in items)[len(items) // 2]
        my, mx = med("cy"), med("cx")
        row = [x for x in items if abs(x["cy"] - my) <= 6]
        col = [x for x in items if abs(x["cx"] - mx) <= 6]
        # Decided BEFORE the sort, and it has to be. `items` IS `row` here,
        # and CPython empties a list while list.sort() runs so that mutation
        # during the sort is caught — so a key function that asks len(row)
        # gets 0, takes the else branch, and silently sorts by the wrong
        # coordinate. That reads a legend row DOWN the page, where every word
        # shares a coordinate and the sort is a tie.
        along_x = len(row) >= len(col)
        items = row if along_x else col
        if len(items) < 2:
            continue
        items.sort(key=lambda x: x["cx"] if along_x else x["cy"])
        words = [x["t"] for x in items]
        cut = next((i for i, w in enumerate(words)
                    if any(ch in w for ch in "(){}[]/")), None)
        if cut is None or cut == 0:
            continue
        name = " ".join(words[:cut]).strip()
        unit = _fix_unit(" ".join(words[cut:]))
        if len(name) < 3 or not unit:
            continue
        out.append({"t": f"{name} ({unit})", "cx": items[0]["cx"],
                    "cy": items[0]["cy"], "color": colour, "ocr": True})
    return out


def detect(page):
    t = _page_text(page)
    if _LIBERTY.search(t) is None or \
            re.search(rf"{_STAGE}\s+(?:[A-Z]{{2,4}}\s+)?\d", t, re.I) is None:
        return False
    # The OPERATOR's daily sheet names the service company and the stage it
    # fracced, which is both of the things above, so it came through here as a
    # Liberty chart and then failed for having no time axis — 00915 p50 is an
    # ARC Resources daily completion report reported as a broken chart page.
    # A page with a time LOG on it is not a page with a time AXIS on it, and
    # an honest "no chart here" beats a failure on a chart that never existed.
    return not daily_ops.is_daily_report(t)


def _parse_date(txt):
    """'YYYY/MM/DD', 'MM/DD/YYYY' or 'MM/DD/YY' (2025 Vermilion-operated
    filings use the short US form) -> (year, month, day)."""
    a, b, c = (int(x) for x in txt.split("/"))
    if a > 1900:
        return a, b, c
    if c > 1900:
        return c, a, b
    return 2000 + c, a, b


def _day_repair(rows):
    """Make the DAYS agree with the clock they are printed beside.

    A chart is a contiguous recording, so between two labels the day advances
    exactly when the clock wraps past midnight and not otherwise. The repair
    that was here needed three readable date labels and a strict majority
    among them; OCR routinely leaves two, because the third is mangled into a
    year like 9929 and thrown out before this — so on the pages that needed it
    most it never ran. 00915 p123 prints 2022/04/29 three times, reads the
    last as 2022/04/28, and the clock beside them runs 20:40, 21:10, 21:40 —
    no wrap anywhere, so no day may change. It died with "implausible duration
    161320s". p107 is the same fault with a real wrap in it: 23:17, 00:22,
    01:27 against days 23, 24, 20.

    Direction is NOT inferred from a wrap count. Counting rollovers picks the
    wrong order — read backwards, 01:27, 00:22, 23:17 never steps backwards
    and so scores zero against the correct order's one. That mistake is
    already written up in _walk below; making it here turned p106, a page that
    worked, into an implausible-duration failure.

    So no direction is chosen at all. Both walks are built, the labels as READ
    are kept as a third candidate, and the one that spans the least time wins.
    A frac chart is minutes to hours long; every wrong day assignment adds a
    whole day to the span, so the shortest consistent reading is the chart's.
    Where the labels are already right, they span the least and are returned
    untouched.
    """
    if len(rows) < 2:
        return rows
    import datetime as _dt

    def _span(days):
        secs = [(d - _dt.date(2000, 1, 1)).days * 86400 + r[4]
                for d, r in zip(days, rows)]
        return max(secs) - min(secs)

    def _walk_days(seq):
        """Anchor on seq's first label and let the clock place the rest."""
        out, cur = {}, _dt.date(seq[0][1], seq[0][2], seq[0][3])
        out[id(seq[0][0])] = cur
        for prev, row in zip(seq, seq[1:]):
            if row[4] < prev[4]:                  # the clock wrapped
                cur = cur + _dt.timedelta(days=1)
            out[id(row[0])] = cur
        return [out[id(r[0])] for r in rows]

    fwd = sorted(rows, key=lambda r: r[0]["cy"])
    cands = [[_dt.date(r[1], r[2], r[3]) for r in rows],   # exactly as read
             _walk_days(fwd), _walk_days(list(reversed(fwd)))]
    best = min(cands, key=_span)
    return [(r[0], d.year, d.month, d.day, r[4]) for d, r in zip(best, rows)]


def _time_axis(spans, time_frame=None, time_grid=None):
    """date + 'HH:MM' span pairs -> abs seconds = a + b*cy. Label anchors
    snap to the time gridlines when the page provides them — edge labels
    shift inward from their gridline, which skews a label-only fit."""
    dates = [s for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{2,4}/\d{2}/\d{2,4}", s["t"])]
    times = [s for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    # Three clock labels, or TWO on a page whose labels came from OCR. Two
    # points determine the line; the third is a consistency check, and on an
    # outlined page the choice is two points or nothing at all — 00914, 01074,
    # 01075 and 01077 print three and OCR returns two, so all four files came
    # back "time labels not found". The implausible-duration check downstream
    # still refuses a fit built on a misread label.
    _need = 2 if any(x.get("ocr") for x in spans) else 3
    if len(times) < _need:
        return None, "", None
    import datetime as dt
    # Drop a misread date BEFORE pairing, not after. 00913 p140 prints
    # "2022/04/28" three times and OCR returns one as "9929/04/28"; that bad
    # label sits nearest in y to every clock on the axis, so pairing first and
    # validating second threw away all three points and left the chart with no
    # date at all.
    def _sane(dsp):
        try:
            y, mo, dd = _parse_date(dsp["t"])
        except (ValueError, TypeError):
            return False
        return 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= dd <= 31
    sane = [x for x in dates if _sane(x)]
    # When every readable label agrees on the day, a misread one is a misread
    # of THAT day — the axis here spans forty minutes. So repair it rather
    # than drop it: dropping left the first clock with no label within reach,
    # two points instead of three, and the chart fell through to the undated
    # path. 00913 p140 prints 2022/04/28 three times and OCR returns one as
    # "9929/04/28".
    # A misread DAY passes the sanity check above — 00915 p118 prints
    # 2022/04/28 three times and OCR returns the last as 2022/04/20. Eight
    # days across an eighty-minute chart is what "implausible duration
    # 708316s" was. A stage runs for hours and may legitimately cross
    # midnight, so a label within a day of the majority is kept and one
    # further out is a misread of the majority's day.
    if len(sane) >= 3:
        import collections as _c
        import datetime as _dt
        days = [_parse_date(x["t"]) for x in sane]
        top, n = _c.Counter(days).most_common(1)[0]
        if n > len(days) / 2:
            ref = _dt.date(*top)
            good = next(x for x, dd in zip(sane, days) if dd == top)
            sane = [x if abs((_dt.date(*_parse_date(x["t"])) - ref).days) <= 1
                    else {**x, "t": good["t"]} for x in sane]
            dates = [x if _sane(x) else x for x in sane]
    if sane and len(sane) < len(dates):
        days = {_parse_date(x["t"]) for x in sane}
        if len(days) == 1:
            good = sane[0]["t"]
            dates = [x if _sane(x) else {**x, "t": good} for x in dates]
        else:
            dates = sane
    else:
        dates = sane
    pts = []
    date0 = None
    _first = (float("inf"), "")
    _rows = []              # (ts, y, mo, dd, tod_secs) before the day repair
    for ts in times:
        # nearest date label
        best = min(dates, key=lambda d: abs(d["cy"] - ts["cy"])) if dates else None
        if best is None or abs(best["cy"] - ts["cy"]) > 40:
            continue
        try:
            y, mo, dd = _parse_date(best["t"])
        except (ValueError, TypeError):
            continue
        # OCR misreads a digit in the year and the chart lands in the year
        # 9929: 00913 p140 prints "2022/04/28" three times and one comes back
        # "9929/04/28", which made the fit report a duration of 250,886,258,313
        # seconds. A date label outside living memory is a misread, not a date.
        if not (1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= dd <= 31):
            continue
        parts = [int(p) for p in ts["t"].split(":")]
        tod = parts[0] * 3600 + parts[1] * 60 + \
            (parts[2] if len(parts) > 2 else 0)
        _rows.append((ts, y, mo, dd, tod))
    _rows = _day_repair(_rows) if any(x.get("ocr") for x in spans) else _rows
    for ts, y, mo, dd, tod in _rows:
        # absolute days (fixed epoch), NOT day-of-year — a stage crossing
        # Dec 31 -> Jan 1 must keep increasing (Carmine: day/month/year can
        # all change inside one chart)
        secs = (dt.date(y, mo, dd) - dt.date(2000, 1, 1)).days * 86400 + tod
        pts.append((secs, ts["cy"]))
        # The chart's date is the date it STARTS on, which is the earliest
        # label's — not whichever label happened to come first out of the span
        # list. On a chart that crosses midnight those are different days, and
        # taking the wrong one dates the whole stage a day late: 00915 p107
        # runs 23:17 -> 01:27 and came back 2022-04-24, putting stage 2 after
        # stage 3 on a well whose stages are in order.
        if date0 is None or secs < _first[0]:
            _first = (secs, f"{y:04d}-{mo:02d}-{dd:02d}")
            date0 = _first[1]
    if len(pts) < _need and len(times) >= _need:
        # No usable date labels. Liberty's 2021 vintage prints a bare "Time"
        # axis — 00928/00929/00930 carry twelve clock labels a page and no
        # date anywhere on the sheet, in any format — and every one of those
        # labels was being skipped for want of a date partner, so the page
        # raised "time labels not found" when the times were right there.
        #
        # The clock alone fixes the axis, provided midnight is unwrapped:
        # 00930 p115 runs 22:56 -> 00:10. Direction is not assumed — a
        # rotated sheet can run time either way down the page — so both
        # orders are unwrapped and judged.
        #
        # Judged on MONOTONICITY, not on rollover count. Counting rollovers
        # picks the wrong order here: read backwards the labels are 00:10,
        # 23:55, 23:40 … which never steps backwards by an hour, so it scores
        # ZERO rollovers against the correct order's one, wins, and fits a
        # negative slope — p115 came out as a 926-minute stage against 18-95
        # for every other stage on the well. Whichever order is chronological
        # is non-decreasing once unwrapped; the reverse is not.
        def _walk(seq):
            out, day, prev, bad = [], 0, None, 0
            for ts in seq:
                q = [int(x) for x in ts["t"].split(":")]
                sod = q[0] * 3600 + q[1] * 60 + (q[2] if len(q) > 2 else 0)
                if prev is not None and sod < prev - 3600:
                    day += 1                      # midnight
                v = day * 86400 + sod
                if out and v < out[-1][0]:
                    bad += 1                      # went backwards anyway
                prev = sod
                out.append((v, ts["cy"]))
            span = (out[-1][0] - out[0][0]) if out else 0
            return out, bad, span

        by_cy = sorted(times, key=lambda s: s["cy"])
        fwd = _walk(by_cy)
        rev = _walk(list(reversed(by_cy)))
        # fewest backward steps, then the tighter span — a wrongly ordered
        # read inflates the span rather than shortening it
        pts = min((fwd, rev), key=lambda r: (r[1], r[2]))[0]
        # date stays unknown: it is not printed on these sheets, and the file
        # name carries the REPORT date, which is not the stage's.
        date0 = ""
    if len(pts) < _need:
        return None, "", None
    # Liberty prints the first/last time labels AT the plot frame edges, but
    # the label TEXT sits several points inside the frame — a label-only fit
    # maps the first ~1-2 minutes of ink to negative time, which the export
    # window then cuts (Carmine's missing ramp starts). When the frame's
    # time extent is known, calibrate on the two edges and keep that fit only
    # if every label still lands on a gridline or edge under it.
    if time_frame:
        lo_e, hi_e = time_frame
        anchors = list(time_grid or []) + [lo_e, hi_e]
        by_cy = sorted(pts, key=lambda p: p[1])
        first, last = by_cy[0], by_cy[-1]
        span_lbl = abs(last[1] - first[1])
        if span_lbl > 1 and \
                abs(first[1] - lo_e) < span_lbl * 0.1 and \
                abs(last[1] - hi_e) < span_lbl * 0.1:
            a2, b2 = _fit([(first[0], lo_e), (last[0], hi_e)])
            if abs(b2) > 1e-12:
                # every label must sit on a gridline/edge under this fit.
                # Labels are minute-rounded and their spacing is uneven by
                # up to a minute, so judge at that scale — a tighter bound
                # rejects good fits and the window falls back to the label
                # span, which clips the stage's opening ramp.
                ok = all(abs(a2 + b2 * min(anchors, key=lambda g: abs(g - cy))
                             - secs) <= FRAME_FIT_TOL for secs, cy in pts)
                if ok:
                    win = tuple(sorted((a2 + b2 * lo_e, a2 + b2 * hi_e)))
                    return (a2, b2), (date0 or ""), win
    a, b = _fit(pts)
    if abs(b) < 1e-12:
        return None, "", None
    return (a, b), (date0 or ""), None


def _horizontal(spans):
    """True when the time axis runs along X (landscape charts, page rotation 0)
    rather than Y (the rotated pages this template was first built for)."""
    tl = [s for s in spans if s["color"] == 0 and
          re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    # TWO labels are enough to say which way they spread, and on an OCR'd page
    # two is often all there are. Requiring three sent 00914, 01074, 01075 and
    # 01077 down the rotated path on a landscape chart: their clocks pair on a
    # CONSTANT coordinate, the fit degenerates, and the page died with
    # "implausible duration 487965257s" — fifteen years across eighty minutes.
    if len(tl) < 2:
        return False
    cxs = [s["cx"] for s in tl]
    cys = [s["cy"] for s in tl]
    return (max(cxs) - min(cxs)) > (max(cys) - min(cys))


def _axis_column(pts):
    """True when [(value, cx, cy)] is a printed value axis rather than stray
    black text. A tick column is one row along the time axis, monotonic in
    position, and evenly stepped in BOTH value and position — a page number,
    a well name's digits or a stage number satisfies none of those."""
    if len(pts) < 4:
        return False
    cys = [p[2] for p in pts]
    if max(cys) - min(cys) > 2.0:            # scattered text, not one column
        return False
    order = sorted(pts, key=lambda p: p[1])
    xs = [p[1] for p in order]
    vals = [p[0] for p in order]
    if vals != sorted(vals) and vals != sorted(vals, reverse=True):
        return False
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    steps = [abs(b - a) for a, b in zip(vals, vals[1:])]
    if min(gaps) <= 0 or min(steps) <= 0:
        return False
    return (max(gaps) - min(gaps)) <= 0.06 * max(gaps) and \
           (max(steps) - min(steps)) <= 1e-6 * max(steps)


# The channel names a Liberty treatment chart prints. Chemical additives
# (XE363, J475, AQUGAR, B702) are NOT here and are never snapped: their names
# are arbitrary product codes, so a near-match to one of these would be a
# coincidence, not a correction.
_CANON_NAMES = ("Treating Pressure", "Backside Pressure", "GORV Pressure",
                "Slurry Rate", "Clean Rate", "Prop Conc", "BH Prop Conc",
                "Btm Prop Conc", "WH Prop Conc")


def _snap_name(name):
    """Pull an OCR'd channel name back to the one the chart meant.

    OCR returns "Treatin Foressure", "Slurry ate", "H Prop Conc",
    "en GORV Pressure" — close enough to read by eye and useless to an alias
    table, which has to enumerate each variant (alias_table.txt already
    carries a hand-added "Treatin Pressure"). A column named
    "Prop Bint Con Sn" reaches the CSV as its own channel and no downstream
    mapping will ever claim it.

    Only for names that are ALREADY close to a printed one — the cutoff is
    high enough that an additive's product code cannot be dragged onto a
    treatment channel, which would be a mislabel rather than a repair.
    """
    import difflib
    bare = re.sub(r"[^A-Za-z ]", " ", name)
    bare = re.sub(r"\s+", " ", bare).strip()
    if not bare:
        return name
    # Compared in ONE case, because the vocabulary is not written in one.
    # This titled the OCR'd name and matched it against the printed list, so
    # "GORV Pressure" — the only entry that is not title case — could not be
    # reached by any variant of itself: "Gorv Pressure" is not "GORV
    # Pressure", and "en GORV Pressure" scored nothing at all. Lowering both
    # sides also recovers the rate on pages where OCR eats more than one
    # letter ("Slur ate", "§lurr ate" -> 0.84 against "slurry rate", where
    # titling scored below the cutoff and left them as their own channels).
    #
    # It does not loosen what the cutoff protects: every additive code on
    # this template — B702 CONC, 475 CONC, AQUGAR CONC, XE363 CONC — still
    # matches nothing at all, measured, even at 0.70.
    low = {c.lower(): c for c in _CANON_NAMES}
    key = bare.lower()
    hits = difflib.get_close_matches(key, list(low), n=2, cutoff=0.78)
    if not hits:
        return name
    # Two plausible answers means no answer. OCR drops a letter from
    # "BH Prop Conc" and the remains sit exactly as close to "WH Prop Conc" —
    # bottomhole and wellhead are different measurements, and guessing which
    # one a curve is would be a mislabel, not a repair.
    if len(hits) > 1:
        r = [difflib.SequenceMatcher(None, key, h).ratio() for h in hits]
        if abs(r[0] - r[1]) < 0.08:
            return name
    return low[hits[0]]


def _clean_name(name):
    """Drop a leading wellbore/leg prefix like 'B: ' or 'B :' so the curve
    name matches Carmine's alias table (e.g. 'B: Treating Pressure')."""
    return re.sub(r"^[A-Za-z]\s*:\s*", "", name).strip()


def _arith_ladder(pts):
    """Is a THREE-label tick row a real ladder, or three OCR misreads?

    Four labels is the safe minimum on a page whose text was guessed at, and
    it costs whole channels. 00915 p108 reads the rate ladder as [12, 16, 20]
    — evenly stepped, evenly spaced, unmistakably an axis — gets no fit, and
    Slurry Rate is dropped from the page entirely. Twenty-two of that file's
    twenty-four treatment charts lose it the same way, and nothing in the
    output says a channel went missing.

    Two points already determine a line; the fourth label was never about the
    arithmetic, it was about not trusting OCR. So ask for the evidence
    directly instead: three labels whose VALUES step evenly and whose
    POSITIONS step evenly, in the same direction, are an axis. Three bad reads
    do not land on both grids at once.
    """
    if len(pts) != 3:
        return False
    q = sorted(pts, key=lambda p: p[1])          # by position along the axis
    v = [p[0] for p in q]
    x = [p[1] for p in q]
    dv1, dv2 = v[1] - v[0], v[2] - v[1]
    dx1, dx2 = x[1] - x[0], x[2] - x[1]
    if abs(dv1) < 1e-9 or abs(dx1) < 1e-9 or abs(dx2) < 1e-9:
        return False
    if (dv1 > 0) != (dv2 > 0):                   # values must not turn around
        return False
    return (abs(dv2 - dv1) <= 0.05 * abs(dv1)          # even in value
            and abs(dx2 - dx1) <= 0.05 * abs(dx1))     # and even in position


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    text = _page_text(page)
    # landscape charts run time along X; swap axes so the (rotated) logic below
    # — which expects time along Y — applies unchanged
    horizontal = _horizontal(spans)
    if horizontal:
        spans = [{**s, "cx": s["cy"], "cy": s["cx"]} for s in spans]
    # frame time extent: the value gridlines run the full time width of the
    # plot, so their span along the time axis marks the frame edges
    t_edges = []
    for d in page.get_drawings():
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        gx0, gy0, gx1, gy1 = (r.y0, r.x0, r.y1, r.x1) if horizontal \
            else (r.x0, r.y0, r.x1, r.y1)
        if abs(gx1 - gx0) < 0.5 and (gy1 - gy0) > 100:
            t_edges.append((gy0, gy1))
    time_frame = None
    if t_edges:
        time_frame = (min(e[0] for e in t_edges), max(e[1] for e in t_edges))
    # time gridlines (constant along time coord, long across values) anchor
    # the interior labels when validating the frame fit
    time_grid = []
    for d in page.get_drawings():
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        gx0, gy0, gx1, gy1 = (r.y0, r.x0, r.y1, r.x1) if horizontal \
            else (r.x0, r.y0, r.x1, r.y1)
        if abs(gy1 - gy0) < 0.5 and (gx1 - gx0) > 100:
            time_grid.append(round((gy0 + gy1) / 2, 2))
    time_grid = sorted(set(time_grid))
    tfit, date, frame_win = _time_axis(spans, time_frame, time_grid)
    if tfit is None:
        raise ValueError("lib1: time labels not found")
    ta, tb = tfit

    # colored series: name span "<Name> (<unit>)" + same-color numeric ticks
    named = {}
    legend_spans = spans
    if any(x.get("ocr") for x in spans) and not any(
            re.fullmatch(r"(.+?)\s*\(([^)]+)\)", x["t"]) for x in spans
            if x["color"] != 0):
        legend_spans = list(spans) + _ocr_legend_spans(spans)
    for s in legend_spans:
        if s["color"] == 0:
            continue
        m = re.fullmatch(r"(.+?)\s*\(([^)]+)\)", s["t"])
        if m and len(m.group(1)) > 3:
            _nm = _clean_name(m.group(1).strip())
            if s.get("ocr"):
                _nm = _snap_name(_nm)
            named.setdefault(s["color"], {"name": _nm,
                                          "unit": m.group(2).strip()})
    # a black series (e.g. a chemical CONC drawn in black) shares ink with
    # axes/grid, so all black curves are indistinguishable — accept one only
    # when the page has EXACTLY one black-named series (else they'd merge into
    # garbage) and its unit matches a colored series' axis (shared via unit_fit).
    colored_units = {v["unit"] for v in named.values()}
    black = []
    for s in spans:
        if s["color"] != 0:
            continue
        m = re.fullmatch(r"(.+?)\s*\(([^)]+)\)", s["t"])
        if m and len(m.group(1)) > 3 and m.group(2).strip() in colored_units:
            cand = {"name": _clean_name(m.group(1).strip()), "unit": m.group(2).strip()}
            if cand not in black:
                black.append(cand)
    if len(black) == 1:
        named[0] = black[0]
    ticks = defaultdict(list)
    for s in spans:
        # Liberty prints the zero tick of several axes as '-0' (the charting
        # tool's negative zero). Without the optional sign that tick was
        # dropped, so e.g. Treating Pressure came out 15..75 instead of 0..75
        # and Slurry Rate 4..20 instead of 0..20 — every curve on those axes
        # was then placed against the wrong range. '+ 0.0' normalises -0.0.
        if s["color"] != 0 and re.fullmatch(r"-?[\d,]+(\.\d+)?", s["t"]):
            # On an OCR'd page a tick has to LOOK like one: aligned with at
            # least two same-coloured siblings. OCR drops the "J" from the
            # legend's "J475 CONC" and the bare "475" was collected as a tick
            # on the red axis — [475, 1.0, 0.8, 0.6, 0.4, 0.2, 0.0] — which
            # destroys the fit and left the page with no axes at all. A
            # printed tick always has a ladder around it; a legend word does
            # not.
            if s.get("ocr"):
                kin = sum(1 for o in spans
                          if o is not s and o["color"] == s["color"]
                          and re.fullmatch(r"-?[\d,]+(\.\d+)?", o["t"])
                          and (abs(o["cx"] - s["cx"]) <= 12
                               or abs(o["cy"] - s["cy"]) <= 12))
                if kin < 2:
                    continue
            ticks[s["color"]].append((float(s["t"].replace(",", "")) + 0.0,
                                      s["cx"], s["cy"]))
    # A black series with its OWN printed tick column. Black numerics are
    # excluded above because axis, grid and title ink is black too, so a black
    # series borrows a colored axis of the same unit (unit_fit below). That
    # borrow is only right when the two axes agree, and on 01397 they do not:
    # Hydr Pressure prints 10..110 running DOWNWARD beside a red 0..100
    # running upward, so reading it off red put a ~14 MPa curve at 90-100 MPa
    # and pinned it to the axis top. Accept a black column only when it looks
    # like a printed axis — see _axis_column — and leave the borrow in place
    # otherwise.
    black_ticks = [(float(s["t"].replace(",", "")) + 0.0, s["cx"], s["cy"])
                   for s in spans
                   if s["color"] == 0 and
                   re.fullmatch(r"-?[\d,]+(\.\d+)?", s["t"])]
    if 0 in named and _axis_column(black_ticks):
        ticks[0] = black_ticks
    # value gridlines: long constant-x strokes. Tick LABELS sit ~12pt off
    # the gridline they annotate (left-aligned text), which biased every
    # value by a constant few units — snap each label to its gridline and
    # fit on true geometry (Carmine's 0422 comparison caught this).
    grid_xs = []
    for d in page.get_drawings():
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        gx0, gy0, gx1, gy1 = (r.y0, r.x0, r.y1, r.x1) if horizontal \
            else (r.x0, r.y0, r.x1, r.y1)
        if abs(gx1 - gx0) < 0.5 and (gy1 - gy0) > 100:
            grid_xs.append(round((gx0 + gx1) / 2, 2))
    grid_xs = sorted(set(grid_xs))
    snap_tol = min((b - a for a, b in zip(grid_xs, grid_xs[1:])),
                   default=0) * 0.45

    fits = {}
    # OCR pages only. A text-layer page reads every label it prints, so it
    # never needs this — and the v1.5.0 release was gated on those files
    # coming back bit-identical.
    _ocr_page = any(x.get("ocr") for x in spans)
    for color, pts in ticks.items():
        if len(pts) < 4 and not (_ocr_page and _arith_ladder(pts)):
            continue
        cys = sorted(p[2] for p in pts)
        split = (cys[0] + cys[-1]) / 2
        side = [p for p in pts if p[2] < split] or pts
        if len(side) < 3:
            side = pts
        anchors = [(v, x) for v, x, _ in side]
        if grid_xs and snap_tol > 0:
            snapped = []
            for v, x in anchors:
                g = min(grid_xs, key=lambda gx: abs(gx - x))
                snapped.append((v, g if abs(g - x) <= snap_tol else x))
            # only trust the snap when it stays one-to-one and ordered
            xs = [x for _, x in snapped]
            if len(set(xs)) == len(xs) and \
                    (sorted(xs) == xs or sorted(xs, reverse=True) == xs):
                anchors = snapped
        a, b = _fit(anchors)
        if abs(b) > 1e-9:
            vals = [v for v, _, _ in pts]
            lo_v, hi_v = min(vals), max(vals)
            # The clip below uses these as the axis' own range, and on an
            # OCR'd page the ladder is missing ticks — almost always the ZERO,
            # which is the smallest and sits hard against the frame. 00919
            # p111 found [10,15,20,25] for the rate and [300..1500] for the
            # concentrations, so a curve correctly traced FLAT AT ZERO was
            # clipped UP to 300 and reported as 300 kg/m3 of proppant that the
            # chart plainly does not show.
            #
            # An arithmetic ladder says where it starts: if the step divides
            # the lowest label, zero is on this axis and the labels for it
            # were simply not read. Extend to it rather than clip against a
            # floor the chart does not have.
            if any(x.get("ocr") for x in spans) and lo_v > 0:
                steps = sorted({round(abs(vals[i] - vals[i - 1]), 6)
                                for i in range(1, len(vals))} - {0.0})
                if steps and abs(lo_v % steps[0]) < 1e-6:
                    lo_v = 0.0
            fits[color] = (a, b, lo_v, hi_v)
    if not named or not fits:
        raise ValueError("lib1: legend or tick rows not found")
    # share an axis by unit for series without their own tick row (black series).
    # Colored axes only: a black fit is the borrower's own axis, never a donor,
    # so a colored series missing its ticks cannot inherit the black range.
    unit_fit = {}
    for color, f in fits.items():
        if color == 0:
            continue
        u = named.get(color, {}).get("unit", "")
        if u and u not in unit_fit:
            unit_fit[u] = f

    meta = PageMeta()
    # stage labels carry re-frac suffixes/prefixes ("4A", "5B", "HRF 5A",
    # "14A - HRF") — capture the whole token, not just the leading digits,
    # or distinct treatments collide into one stage. The "Stage X of N"
    # chart title is the most explicit form; fall back to a bare token.
    # keep a "Part I/II" continuation tag distinct — same-key charts merge
    # by sample index, which would silently drop the later part. Carmine's
    # naming: "Part I/II" (roman or arabic) -> "Attempt 1/2".
    m = (re.search(rf"{_STAGE}\s+([A-Za-z0-9][A-Za-z0-9\- ]*?)\s+of\s+\d+"
                   r"(?:\s+Part\s+(\w+))?", text, re.I)
         # A trailing ALL-CAPS token belongs to the stage name — Liberty
         # prints "Stage 1A HRF" and "Stage 6A PW", and dropping it merged
         # distinct stages under one label. Uppercase-only and 2-4 letters, so
         # the lowercase "of" in "Stage 01 of 47" (handled above) and ordinary
         # words after the name are not swallowed.
         or re.search(rf"{_STAGE}\s+((?:[A-Z]{{2,4}}\s+)?\d+[A-Z]?"
                      r"(?:\s*-\s*[A-Z]{2,4})?(?:[ \t]+[A-Z]{2,4})?)\b()",
                      text))
    if m:
        stage = " ".join(m.group(1).split())
        part = m.group(2)
        if part:
            roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
            n = roman.get(part.lower()) or (int(part) if part.isdigit() else None)
            stage += f" Attempt {n}" if n else f" Attempt {part}"
        meta.stage = stage
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    m = re.search(r"^(.*?)\s+Stage\s+", first, re.I)
    meta.title = (m.group(1) if m else first)[:60]
    meta.date = date

    tick_x = [x for pts in ticks.values() for _, x, _ in pts]
    x_lo, x_hi = min(tick_x) - 10, max(tick_x) + 10
    # Smaller cx is a HIGHER value, so that -10 admits ink ten points above
    # the topmost tick — above the axis maximum by construction. On a page
    # with a text layer that slack is harmless padding. On an OCR'd one it is
    # where the legend's colour swatch and the frame's own top edge live, and
    # it is the whole of the remaining overshoot: 00919 p111 put Slurry Rate's
    # peak at 26.63, which is exactly the value this bound maps to (cx 125.4),
    # against a chart that peaks at 14. Btm Prop Conc reached 1598 the same
    # way while its curve lies flat on zero.
    #
    # Nothing real is lost. Curve ink above the top tick was being clipped to
    # the top tick anyway, so dropping it changes a reported "axis maximum"
    # into the true peak inside the axis.
    if any(x.get("ocr") for x in spans):
        x_lo = min(tick_x)
    tl_cy = [s["cy"] for s in spans if s["color"] == 0 and
             re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    # Clip curve ink to the plot FRAME, not to the time-LABEL span. The last
    # label sits inside the frame, so a label-span clip threw away every point
    # after it while the export window (taken from the frame) still ran to the
    # frame edge — the stage's last minutes came out empty. Measured on 00374:
    # 110-220s lost off the tail of every stage, 0 off the head, which is
    # exactly what Carmine reported ("the start looks ok").
    if time_frame:
        y_lo, y_hi = time_frame[0] - 10, time_frame[1] + 10
    else:
        y_lo, y_hi = min(tl_cy) - 10, max(tl_cy) + 10

    series = {}
    units = {}
    axes = {}          # name -> (axis_min, axis_max) from the printed ticks
    axis_fit = {}      # name -> (a, b) so the axis can be read AT the frame
    for color_int, info in named.items():
        fit = fits.get(color_int) or unit_fit.get(info["unit"])
        if fit is None:
            continue
        a, b, v_lo_ax, v_hi_ax = fit
        pts = []
        for d in page.get_drawings():
            c = d.get("color")
            if c is None and d["type"] in ("f", "fs"):
                # The 2025-era filings stroke nothing: each curve is a FILLED
                # ribbon — the pen outline as a closed path, fill set and
                # color None. Reading only stroked ink skipped every curve and
                # the whole file reported no data (Carmine's 197 "No
                # extractable data" reports; 01103 draws 6 curves this way,
                # 88,613 items, all six fills matching the legend exactly).
                c = d.get("fill")
            if c is None or d["type"] not in ("s", "fs", "f"):
                continue
            if not _close(c, color_int):
                continue
            # curves are dense polylines (hundreds of items per drawing); an
            # isolated 1-2 item drawing that is one long axis-aligned line is
            # axis/marker ink in the series color — it puts phantom spikes on
            # the curve (Carmine's 00374 rate spikes). Real flat stretches
            # live inside the dense drawings, so they survive this filter.
            sparse = len(d["items"]) <= 2
            for item in d["items"]:
                if item[0] == "l":
                    x1, y1, x2, y2 = item[1].x, item[1].y, item[2].x, item[2].y
                    if horizontal:            # match the swapped span coords
                        x1, y1, x2, y2 = y1, x1, y2, x2
                    aligned = abs(x1 - x2) < 0.01 or abs(y1 - y2) < 0.01
                    seg = max(abs(x1 - x2), abs(y1 - y2))
                    if color_int == 0:
                        # black series shares ink with axes/grid: drop long
                        # axis-aligned segments (frame + gridlines)
                        if aligned and seg > 5:
                            continue
                    elif sparse and aligned and seg > 10:
                        continue
                    pts.append((x1, y1)); pts.append((x2, y2))
                elif item[0] == "c":
                    ax, ay, bx, by = item[1].x, item[1].y, item[4].x, item[4].y
                    if horizontal:
                        ax, ay, bx, by = ay, ax, by, bx
                    pts.append((ax, ay)); pts.append((bx, by))
        if len(pts) < 40:
            continue
        arr = np.array(pts)
        # x_lo is the GLOBAL top tick across every colour, so ink above THIS
        # series' own top still gets in — GORV read 80.22 against a printed
        # 0..75 because magenta's own 75 sits below the page's highest tick.
        # Each series is bounded by its own ladder: the position its maximum
        # tick occupies, with a point of slack for pen width.
        x_lo_c, x_hi_c = x_lo, x_hi
        if any(x.get("ocr") for x in spans) and abs(b) > 1e-9:
            x_lo_c = max(x_lo, (v_hi_ax - a) / b - 1.0)
            # ...and the same at the BOTTOM, which was missing.
            #
            # x_hi stops ten points below the lowest tick anyone READ, and on
            # an outlined page the tick nobody reads is almost always the
            # zero: 00913 p133 prints 0 on all five ladders and OCR returns
            # none of them, so red comes back [16..80] and the greens
            # [300..1500]. The axis is already extended down to zero — that
            # is what the step-divides-the-lowest-label rule above does — but
            # the INK was still cut off a step higher, so every curve lost its
            # bottom. Treating Pressure bottomed at 13.5 on a chart that
            # starts at 2, and both proppant concentrations read a floor of
            # ~193 kg/m3 through the third of the stage where the sheet plainly
            # draws them flat at zero.
            #
            # So bound each series at the position its own axis MINIMUM
            # occupies, the mirror of the line above. Ink below that is still
            # clipped to v_lo_ax, so the frame edge cannot push a curve
            # negative.
            x_hi_c = max(x_hi, (v_lo_ax - a) / b + 1.0)
        keep = ((arr[:, 0] >= x_lo_c) & (arr[:, 0] <= x_hi_c) &
                (arr[:, 1] >= y_lo) & (arr[:, 1] <= y_hi))
        arr = arr[keep]
        if len(arr) < 40:
            continue
        t = ta + tb * arr[:, 1]
        # clamp to the axis' own tick range: ink at the frame edge maps a
        # hair outside the scale and shows up as impossible negatives in
        # the CSV (Carmine's 0422 sample never goes below the axis)
        v = np.clip(a + b * arr[:, 0], v_lo_ax, v_hi_ax)
        order = np.argsort(t, kind="stable")
        # Two colours can arrive under ONE name when OCR drops a word: 00915
        # p108 reads both greens as "Prop Conc" because the second one's "Btm"
        # was never read, and this dict silently kept one of them. A whole
        # traced channel disappeared with nothing to say it had.
        #
        # The missing word is not recoverable — it is not on the page in any
        # form we read — and this module refuses to guess a name it cannot
        # see ("H Prop Conc" stays ambiguous rather than being called BH).
        # So keep the data and number the clash: a channel Carmine can see and
        # rename beats one he never learns existed. OCR pages only, so a
        # text-layer file cannot change.
        _name = info["name"]
        if _name in series and _ocr_page:
            _k = 2
            while f"{_name} #{_k}" in series:
                _k += 1
            _name = f"{_name} #{_k}"
        series[_name] = (t[order], v[order])
        units[_name] = info["unit"]
        # This channel is one the black-axis fix changed. Say so ON the chart,
        # because the correction reaches data the client already has: builds
        # before 1.0.0 read a black series off a coloured axis of the same
        # unit, so any CSV exported earlier carries wrong numbers for it. The
        # value being shown NOW is right — it is the old export that is not,
        # The chart's OWN axis range for this curve, straight off its printed
        # tick labels. The Lab plots against this instead of guessing a top
        # from the data, so our y axis reads the same as the source report.
        axes[_name] = (float(v_lo_ax), float(v_hi_ax))
        axis_fit[_name] = (float(a), float(b))
    if not series:
        raise ValueError("lib1: no curves matched")

    # window = the labeled time span, matching Carmine's own exports: his
    # sample starts exactly at the first time label, not at the first ink
    if frame_win:
        t_lo, t_hi = frame_win
    else:
        label_ts = [ta + tb * cy for cy in tl_cy]
        t_lo, t_hi = min(label_ts), max(label_ts)
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        t_lo = min(t.min() for t, _ in series.values())
        t_hi = max(t.max() for t, _ in series.values())
        n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"lib1: implausible duration {n}s")
    meta.duration_min = n / 60.0
    # The date and the clock now come from the SAME instant.
    #
    # start_time has always been read off t_lo, the window's own start, while
    # the date came from whichever label the axis fit happened to anchor on.
    # On a chart that crosses midnight those are different days: 00915 p107
    # runs 23:17 -> 01:27, its 23:17 label has no date beside it, and the page
    # came back "2022-04-24 23:16" — a day after the chart it belongs to, and
    # after the stage that follows it. t_lo is absolute seconds on the same
    # epoch the labels were converted into, so the day is simply read back
    # out of it and the two can no longer disagree.
    if date:
        import datetime as _dt0
        _d0 = _dt0.date(2000, 1, 1) + _dt0.timedelta(days=int(t_lo // 86400))
        meta.date = f"{_d0.year:04d}-{_d0.month:02d}-{_d0.day:02d}"
    day_sec = t_lo % 86400
    meta.start_time = (f"{int(day_sec // 3600):02d}:{int(day_sec % 3600 // 60):02d}"
                       f":{int(day_sec % 60):02d}")
    # chart geometry in PAGE coordinates for the synced original-chart view:
    # elapsed seconds e -> page coord along `axis` = (t_lo + e - ta) / tb;
    # v0/v1 span the plot across the other dimension. (For landscape pages
    # the swapped span coords mean the time map applies to page-x and the
    # tick extent to page-y — which is exactly what axis/v0/v1 encode.)
    # Ghost/compare stretches the page so v0..v1 fills our plot rect, and the
    # Lab draws each curve against its printed tick range. Those only agree if
    # v0/v1 are the page coords where the axis READS those tick values.
    # min/max of the gridlines is not that: there is no gridline at the axis
    # zero, so the lowest one sits ~11% of the span above it and the backdrop
    # rode up by that much. Invert each series' own fit instead and take the
    # median, so one noisy axis can't drag the frame.
    edges_lo, edges_hi = [], []
    for _n, (fa, fb) in axis_fit.items():
        if abs(fb) < 1e-12:
            continue
        lo_v, hi_v = axes[_n]
        edges_lo.append((lo_v - fa) / fb)
        edges_hi.append((hi_v - fa) / fb)
    if edges_lo and edges_hi:
        edges_lo.sort(); edges_hi.sort()
        p_lo = edges_lo[len(edges_lo) // 2]
        p_hi = edges_hi[len(edges_hi) // 2]
        v_lo_f, v_hi_f = min(p_lo, p_hi), max(p_lo, p_hi)
    else:
        v_lo_f = min(grid_xs) if grid_xs else x_lo
        v_hi_f = max(grid_xs) if grid_xs else x_hi
    meta.geom = {"axis": "x" if horizontal else "y",
                 "ta": float(ta - t_lo), "tb": float(tb),
                 "v0": float(v_lo_f), "v1": float(v_hi_f)}
    samples = np.arange(int(n / sample_sec)) * sample_sec
    # diagnostic: where each curve's INK actually starts/ends relative to the
    # export window, so truncated heads/tails can be measured rather than eyeballed
    meta.ink = {name: (float(t.min() - t_lo), float(t.max() - t_lo))
                for name, (t, _v) in series.items()}
    meta.window = float(n)
    data = {name: _resample(t - t_lo, v, samples) for name, (t, v) in series.items()}
    # The plot frame runs a little past the last recorded point, and the window
    # is taken from the frame so the opening ramp is never clipped. That left
    # 1-3 minutes of EMPTY rows at the end of every stage — what Carmine saw as
    # "not getting the ends of the pressure and rates". Trim to the last sample
    # any channel actually reaches. The head is deliberately untouched: t=0
    # must stay at the frame edge or the ramp start comes back off.
    if data:
        fin = np.zeros(len(samples), dtype=bool)
        for v in data.values():
            fin |= np.isfinite(np.asarray(v, dtype=float))
        if fin.any():
            last = int(np.nonzero(fin)[0][-1]) + 1
            if last < len(samples):
                samples = samples[:last]
                data = {k: np.asarray(v)[:last] for k, v in data.items()}
                meta.duration_min = (last * sample_sec) / 60.0
                meta.window = float(last)
    # printed axis range per curve; the Lab plots against these so its y
    # axis matches the source report instead of a value-derived guess.
    # axes_frame is the same axis read AT the plot-frame edges (what geom
    # v0/v1 spans) — ghost mode stretches the page between those edges, so
    # this is the range our curves must be placed against to sit on the ink.
    meta.axes = axes
    meta.axes_frame = {n: (af[0] + af[1] * v_lo_f, af[0] + af[1] * v_hi_f)
                       for n, af in axis_fit.items()}
    return meta, samples, data, units
