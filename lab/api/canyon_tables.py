"""Canyon Technical Services table extraction (the "Summary Data" screen for
Canyon).

canyon.py traces Canyon's stacked Pressure/Rate/Concentration chart pages.
The same filings also carry printed tables, and three of them are worth
parsing:

  - find_summary_pages(doc): the document's table pages grouped for viewing
    (Treatment Log, Treatment Interval Summary, the operator's Treatment
    Summary), each with page numbers so the Lab can render them with pdf.js.

  - parse_treatment_log(doc): Canyon's "TREATMENT LOG (Conventional
    Fracturing)" — one row per SUBSTAGE (schedule step) of every interval,
    at printed precision: wall-clock time, mainline/monitor pressure,
    blender clean rate+volume, proppant concentration+mass, slurry
    rate+volume, N2, CO2, wellhead combined rate+volume and wellhead
    proppant concentration. This tabulates the same quantities the chart
    curves trace, so it doubles as ground truth for the chart extraction.

  - parse_interval_summary(doc): Canyon's "TREATMENT INTERVAL SUMMARY" —
    one row per interval: start/end clock time, breakdown/max/average/ISIP
    pressure, average combined rate, the clean-fluid volume split, N2/CO2
    volumes, proppant off surface vs in formation, max downhole
    concentration.

  - parse_treatment_summary(doc): the OPERATOR's landscape "... Treatment
    Summary" page (not Canyon's own form — it is bound into some filings
    and absent from others). One row per stage, 19 columns, including three
    free-text columns. Those free-text columns are the only place in the
    filing that records a stage being SKIPPED ("Did not see ball seat ...
    Decision was made to skip zone") and the per-stage ball-seat
    differential, so they are carried through verbatim.

All three parsers read the page positionally: column anchors come from the
printed units row (or the header spans), so they survive the page-size and
vintage changes between 2014 and 2017 filings, and the /Rotate 90 pages that
Canyon's report writer emits for some sections.
"""
import re
from datetime import datetime, timedelta

import fitz

# ---------------------------------------------------------------- page kinds

SUMMARY_KINDS = [
    # The operator's landscape sheet stands alone. Everything else — cover,
    # treatment log, interval summary — is one Canyon report printed across
    # consecutive sheets, and the report header repeats on every one of them,
    # so it groups as a single viewable item the way the other providers'
    # multi-page reports do.
    ("treatment-summary", r"Treatment Summary"),
    ("frac-report", r"Conventional Frac Treatment Report"),
]
KIND_TITLES = {
    "treatment-summary": "Treatment Summary (operator)",
    "frac-report": "Conventional Frac Treatment Report",
}


def _page_kind(text):
    for kind, pat in SUMMARY_KINDS:
        if re.search(pat, text):
            return kind
    return None


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — consecutive same-kind pages grouped
    into one entry, matching the other providers' summary modules."""
    groups = []
    for p in range(doc.page_count):
        kind = _page_kind(doc[p].get_text())
        if kind is None:
            continue
        page1 = p + 1
        if groups and groups[-1]["kind"] == kind and \
                page1 - groups[-1]["pages"][-1] <= 2:
            groups[-1]["pages"].append(page1)
        else:
            groups.append({"kind": kind, "title": KIND_TITLES.get(kind, kind),
                           "pages": [page1]})
    return groups


# ------------------------------------------------------------------ plumbing

def _spans(page):
    """[{t, x0, x1, cx, y0, cy}] in DISPLAY coordinates.

    Canyon's report writer emits some sheets with /Rotate 90 — the treatment
    log and interval summary both show up rotated in the 2014 filings. Their
    span bboxes come back in unrotated space, so every x/y here is pushed
    through the page's rotation matrix; without that the columns of a rotated
    sheet look like rows and the whole page parses as nothing."""
    m = page.rotation_matrix
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if not t:
                    continue
                r = fitz.Rect(sp["bbox"]) * m
                out.append({"t": t, "x0": r.x0, "x1": r.x1,
                            "cx": (r.x0 + r.x1) / 2,
                            "y0": r.y0, "cy": (r.y0 + r.y1) / 2})
    return out


def _rows(spans, tol=2.5):
    """spans -> [(y, [span,...])] grouped by y-centre, top to bottom."""
    rows = {}
    for s in sorted(spans, key=lambda s: (s["cy"], s["cx"])):
        key = next((k for k in rows if abs(k - s["cy"]) < tol), s["cy"])
        rows.setdefault(key, []).append(s)
    return [(y, sorted(v, key=lambda s: s["cx"])) for y, v in sorted(rows.items())]


_UNIT = re.compile(r"^\((MPa|kPa/m|m³/min|m3/min|sm³/min|m³|m3|sm³|sm3|"
                   r"kg/m³|kg/m3|tonne|°C|m|L)\)$")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)$", re.I)
_NUMISH = re.compile(r"^-?[\d,]+(\.\d+)?$")
_CELL = re.compile(r"^(-?[\d,]+(\.\d+)?|n/a|N/A|-)$")
_MONTH_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),\s*(20\d\d)\b")


def _num(t):
    return t.replace(",", "").replace(" ", "")


def _unit_row(spans):
    """[(y, [unit spans left→right])] for every printed units row on the page,
    top to bottom. Each one heads a table block."""
    out = []
    for y, cells in _rows([s for s in spans if _UNIT.match(s["t"])], tol=2.0):
        if len(cells) >= 8:
            out.append((y, cells))
    return out


def _as_date(txt):
    m = _MONTH_DATE.search(txt or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                 "%B %d %Y")
    except ValueError:
        return None


def _treatment_date(page, spans=None):
    """The 'Treatment Date:' printed in the report header, as a date.

    Read off the label's own line rather than by scanning the page text: the
    comments columns are full of other dates ('Frac commenced October 12,
    2014 ...') and on the /Rotate 90 sheets the text stream order is no guide
    to which one is the header."""
    spans = _spans(page) if spans is None else spans
    lab = next((s for s in spans if s["t"].startswith("Treatment Date")), None)
    if lab is not None:
        near = [s for s in spans if abs(s["cy"] - lab["cy"]) < 6
                and s["x0"] >= lab["x1"] - 2]
        for s in sorted(near, key=lambda s: s["x0"]):
            d = _as_date(s["t"])
            if d:
                return d
    return _as_date(page.get_text())


def _same_anchors(a, b, tol=3.0):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def _drop_empty(tab):
    """Drop columns that no row populates.

    Canyon prints a fixed form, so a well that pumped no reverse-circulating
    stage still gets a 'Reverse Circulating' heading with nothing under it,
    and a run with no per-interval notes still gets an empty 'Comments'.
    Measured over the eight-file corpus: 'Reverse Circulating Volume' is 0%
    filled on 00009/00010/00011/00012 and 'Comments' on those four plus
    00204 — yet both are populated on 00146/00170/00264, so neither is a
    parser miss. An all-empty column is a heading with no data behind it and
    must not ship."""
    if not tab or not tab.get("rows"):
        return tab
    keep = [j for j in range(len(tab["columns"]))
            if any(j < len(r) and r[j] not in (None, "") for r in tab["rows"])]
    if len(keep) == len(tab["columns"]):
        return tab
    return {"columns": [tab["columns"][j] for j in keep],
            "rows": [[r[j] if j < len(r) else None for j in keep]
                     for r in tab["rows"]]}


def _label_attempts(rows, attempts=None, idx=0):
    """'12' printed twice -> '12 (attempt 1)' / '12 (attempt 2)'.

    Canyon re-prints the SAME interval number when a zone is re-attempted
    after an abort — 00009 interval 12 is an eight-minute try at 03:50 and
    then the real treatment at 09:13, interval 25 likewise, and the pattern
    recurs on 00011/00012 (interval 22), 00170 and 00204: ten such rows over
    the eight-file corpus. Unlike the BJ 'Stage 06 Plug Slip' and IFS
    'Interval 4A/4B' cases there is no printed suffix being discarded — the
    report genuinely prints one number for two treatments — so the label has
    to be synthesised or the two ship under one key. Intervals treated once
    keep their bare number, so ordinary joins are unaffected."""
    if attempts is None:
        attempts = []
        counts = {}
        for r in rows:
            counts[r[idx]] = counts.get(r[idx], 0) + 1
        seen = {}
        for r in rows:
            seen[r[idx]] = seen.get(r[idx], 0) + 1
            attempts.append(seen[r[idx]])
        totals = counts
    else:
        totals = {}
        for r, a in zip(rows, attempts):
            totals[r[idx]] = max(totals.get(r[idx], 1), a)
    for r, a in zip(list(rows), list(attempts)):
        if totals.get(r[idx], 1) > 1:
            r[idx] = f"{r[idx]} (attempt {a})"


def _bands(anchors):
    """anchor centres -> [(lo, hi)] half-open x bands, split at midpoints."""
    out = []
    for i, a in enumerate(anchors):
        lo = (anchors[i - 1] + a) / 2 if i else a - 40
        hi = (a + anchors[i + 1]) / 2 if i + 1 < len(anchors) else a + 40
        out.append((lo, hi))
    return out


def _leaf_names(spans, unit_y, anchors, depth=34):
    """Header text sitting directly above each unit anchor, joined top-down.

    A heading counts as this column's own only if it FITS INSIDE the column's
    band. Group headings ('Blender Proppant' over Conc.+Mass, 'Clean Fluid
    Volume' over five volume columns) are wider than one band and get dropped
    here — the caller re-attaches them from its own name map. Centring alone
    is not enough to tell the two apart: 'Wellhead Combined' happens to sit
    dead-centre over its own Volume column."""
    bands = _bands(anchors)
    picks = [[] for _ in anchors]
    for s in spans:
        if not (unit_y - depth < s["cy"] < unit_y - 2):
            continue
        for i, (lo, hi) in enumerate(bands):
            if lo <= s["cx"] < hi:
                if s["x0"] >= lo - 1 and s["x1"] <= hi + 1:
                    picks[i].append((s["cy"], s["t"]))
                break
    return [" ".join(t for _y, t in sorted(p)).strip() for p in picks]


# --------------------------------------------------- TREATMENT LOG (substage)

# leaf headers of Canyon's treatment log, left to right, and the full column
# names they carry once the group headings above them are folded back in.
# The parser refuses the page if the printed leaves do not match — better no
# table than fifteen mislabelled numeric columns.
_LOG_LEAVES = ["Mainline", "Monitor", "Rate", "Volume", "Conc.", "Mass",
               "Rate", "Volume", "Rate", "Volume", "Rate", "Volume",
               "Rate", "Volume", "Proppant Conc."]
_LOG_UNITS = ["MPa", "MPa", "m³/min", "m³", "kg/m³", "tonne", "m³/min", "m³",
              "sm³/min", "sm³", "m³/min", "m³", "m³/min", "m³", "kg/m³"]
_LOG_NAMES = ["Mainline Pressure", "Monitor Pressure",
              "Blender Clean Rate", "Blender Clean Volume",
              "Blender Proppant Conc.", "Blender Proppant Mass",
              "Blender Slurry Rate", "Blender Slurry Volume",
              "N2 Rate", "N2 Volume", "CO2 Rate", "CO2 Volume",
              "Wellhead Combined Rate", "Wellhead Combined Volume",
              "Wellhead Proppant Conc."]

# leaf headers of the interval summary. Canyon prints the clean-fluid split
# out of reading order (Reverse Circulating before Pad), so these are matched
# as a set, not assumed positionally; the map below renames the ambiguous ones.
_IVL_RENAME = {
    "Breakdown": "Breakdown Pressure",
    "Maximum": "Maximum Pressure",
    "Average": "Average Pressure",
    "ISIP": "ISIP",
    "Combined Rate Average": "Average Combined Rate",
    "Combined Average Rate": "Average Combined Rate",
    "Reverse Circulating": "Reverse Circulating Volume",
    "Pad": "Pad Volume",
    "Proppant Stages": "Proppant Stage Volume",
    "Flush": "Flush Volume",
    "Total": "Total Clean Fluid",
    "Off Surface": "Proppant Off Surface",
    "In Formation": "Proppant In Formation",
    "Max DH Conc.": "Max DH Proppant Conc.",
}


def _blocks(page, spans):
    """[(kind, unit_y, anchors, units)] for every table block on the page.

    kind is 'log' for the substage treatment log, 'interval' for the treatment
    interval summary, 'other' for anything else with a units row. A sheet can
    carry two (the tail of the log plus the interval summary underneath), and
    continuation sheets carry none — those inherit the previous sheet's
    geometry, which is why the blocks have to be located rather than assumed."""
    out = []
    for y, cells in _unit_row(spans):
        anchors = [c["cx"] for c in cells]
        units = [c["t"].strip("()") for c in cells]
        leaves = _leaf_names(spans, y, anchors)
        # Some sheets print the units row with no column headings above it at
        # all (the log runs on from the previous sheet but the report writer
        # still re-emits the units). Those are recognised by their unit
        # signature, which is unique to the log.
        sig = [u.replace("3", "³") for u in units]
        if len(anchors) == len(_LOG_LEAVES) and (
                leaves == _LOG_LEAVES
                or (sig == _LOG_UNITS and "ISIP" not in leaves)):
            out.append(("log", y, anchors, units))
        elif "Breakdown" in leaves and "ISIP" in leaves:
            out.append(("interval", y, anchors, units, leaves))
        else:
            out.append(("other", y, anchors, units))
    return out


def is_treatment_log_page(page):
    """True for a sheet that carries treatment-log DATA rows (header sheets
    and continuation sheets both)."""
    t = page.get_text()
    if "Conventional Frac Treatment Report" not in t:
        return False
    return sum(1 for ln in t.splitlines() if _CLOCK.match(ln.strip())) >= 3


# Row-label headings left of the data columns. Some sheets break 'Stage
# Number' over two lines, which used to lose the whole document's log.
_LEFT_ALIASES = {
    "Interval": ("Interval",),
    "Stage Number": ("Stage Number", "Stage", "Number"),
    "Time": ("Time",),
    "Start": ("Start",),
    "End": ("End",),
    "Comments": ("Comments",),
}


def _left_anchors(spans, unit_y, labels, depth=40):
    """{label: cx} for the row-label headings printed left of the data
    columns. Multi-line headings average to one centre."""
    hits = {}
    for s in spans:
        if not (unit_y - depth < s["cy"] < unit_y + 2):
            continue
        for lab in labels:
            if s["t"] in _LEFT_ALIASES.get(lab, (lab,)):
                hits.setdefault(lab, []).append(s["cx"])
    return {k: sum(v) / len(v) for k, v in hits.items()}


def _clock_to_dt(day, txt, prev):
    """'01:25:57 PM' on `day` -> datetime, rolled past midnight as needed."""
    m = _CLOCK.match(txt)
    if not m:
        return None
    h, mn, sc, ap = int(m.group(1)), int(m.group(2)), int(m.group(3)), \
        m.group(4).upper()
    h = 0 if (h == 12 and ap == "AM") else (h + 12 if (ap == "PM" and h != 12)
                                            else h)
    if day is None:
        return f"{h:02d}:{mn:02d}:{sc:02d}"
    dt = day + timedelta(hours=h, minutes=mn, seconds=sc)
    if prev is not None:
        # the log is chronological; a clock that runs backwards means the
        # sheet's printed Treatment Date has rolled over.
        for _ in range(2):
            if dt >= prev:
                break
            dt += timedelta(days=1)
    return dt


def parse_treatment_log(doc):
    """-> {columns, rows} for Canyon's per-substage TREATMENT LOG, or None.

    One row per printed schedule step, in printed order. 'Time' is the printed
    wall clock resolved against the sheet's Treatment Date, so it lines up
    with the chart pages' HH:MM axis."""
    columns = None
    rows = []
    geom = None          # (anchors, left) inherited by continuation sheets
    prev_dt = None
    for p in range(doc.page_count):
        page = doc[p]
        if not is_treatment_log_page(page):
            continue
        spans = _spans(page)
        blocks = _blocks(page, spans)
        logs = [b for b in blocks if b[0] == "log"]
        day = _treatment_date(page, spans)
        if logs:
            _k, _y, anchors, us = logs[0]
            left = _left_anchors(spans, _y, {"Interval", "Stage Number",
                                             "Time"})
            if len(left) < 3 and geom is not None and \
                    _same_anchors(anchors, geom[0]):
                # headingless continuation sheet, same form: keep the row
                # labels we already have. A block whose numeric columns sit
                # somewhere else is a different form and gets no rows rather
                # than rows read out of the wrong x positions.
                left = geom[1]
            if len(left) >= 3:
                geom = (anchors, left)
            if columns is None and len(left) >= 3:
                columns = (["Interval", "Stage Number", "Time", "Comments"]
                           + [f"{n} ({u})" for n, u in zip(_LOG_NAMES, us)])
        if geom is None:
            continue
        anchors, left = geom
        new = _log_rows(spans, anchors, left, day, prev_dt, blocks)
        rows.extend(new)
        for r in reversed(new):
            if isinstance(r[2], str) and re.match(r"^20\d\d-", r[2]):
                prev_dt = datetime.strptime(r[2], "%Y-%m-%d %H:%M:%S")
                break
    if not rows or columns is None:
        return None
    _label_attempts(rows, _log_attempts(rows))
    return _drop_empty({"columns": columns, "rows": rows})


def _log_attempts(rows):
    """[attempt number] per log row, from the PRINTED Stage Number.

    Canyon restarts the step count at 1 for a re-attempt (00009 interval 12
    prints steps 1,2 and then 1..9), so a step that fails to advance opens a
    new attempt. That is a printed signal rather than a time-gap guess, which
    matters: interval 13 of 00009 contains a three-hour shut-in inside a
    SINGLE attempt — a gap rule would split it wrongly."""
    out = []
    cur_ivl, cur_step, cur_att = object(), None, 1
    for r in rows:
        try:
            step = int(r[1]) if r[1] is not None else None
        except (TypeError, ValueError):
            step = None
        if r[0] != cur_ivl:
            cur_ivl, cur_att, cur_step = r[0], 1, step
        elif step is not None and cur_step is not None and step <= cur_step:
            cur_att += 1
            cur_step = step
        elif step is not None:
            cur_step = step
        out.append(cur_att)
    return out


def _log_rows(spans, anchors, left, day, prev, blocks):
    """the data rows of one treatment-log sheet."""
    bands = _bands(anchors)
    first_num = bands[0][0]
    time_cx = left["Time"]
    ivl_cx, stg_cx = left["Interval"], left["Stage Number"]
    # a sheet that also carries the interval summary must not bleed its rows
    # into the log: the summary's End-time column sits at the same x as the
    # log's Time column, so only the y bound separates them.
    top = min([b[1] for b in blocks if b[0] == "log"], default=-1e9)
    stop = min([b[1] for b in blocks if b[0] != "log" and b[1] > top],
               default=None)
    header_ys = [b[1] for b in blocks]

    clocks = [s for s in spans if _CLOCK.match(s["t"])
              and abs(s["cx"] - time_cx) < 22
              and (stop is None or s["cy"] < stop - 4)]
    clocks.sort(key=lambda s: s["cy"])
    out = []
    for i, c in enumerate(clocks):
        y = c["cy"]
        if any(abs(y - hy) < 5 for hy in header_ys):
            continue
        nxt = clocks[i + 1]["cy"] if i + 1 < len(clocks) else y + 12
        cells = [None] * (4 + len(anchors))
        dt = _clock_to_dt(day, c["t"], prev)
        if isinstance(dt, datetime):
            prev = dt
            cells[2] = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            cells[2] = dt
        comments = []
        for s in spans:
            if abs(s["cy"] - y) <= 3.0:
                if abs(s["cx"] - ivl_cx) < 12 and _NUMISH.match(s["t"]):
                    cells[0] = _num(s["t"])
                    continue
                if abs(s["cx"] - stg_cx) < 12 and _NUMISH.match(s["t"]):
                    cells[1] = _num(s["t"])
                    continue
            if s["x0"] > time_cx + 6 and s["x1"] < first_num - 2:
                # comments wrap, so take the whole band down to the next row
                if y - 4 <= s["cy"] < nxt - 4 and re.search(r"\S", s["t"]):
                    comments.append((s["cy"], s["x0"], s["t"]))
                continue
            if abs(s["cy"] - y) > 3.0:
                continue
            if not _CELL.match(s["t"]):
                continue
            for j, (lo, hi) in enumerate(bands):
                if lo <= s["cx"] < hi:
                    if cells[4 + j] is None:
                        cells[4 + j] = _num(s["t"])
                    break
        if comments:
            cells[3] = " ".join(t for _y, _x, t in sorted(comments))
        # a log row can be a bare timestamped note ('5:52:30 PM  flow back
        # well') with no measurements at all — those are printed rows too.
        if cells[0] or cells[3] or any(c is not None for c in cells[4:]):
            out.append(cells)
    return out


# ------------------------------------------------ TREATMENT INTERVAL SUMMARY

def is_interval_summary_page(page):
    return "TREATMENT INTERVAL SUMMARY" in page.get_text()


def units_of(cols):
    """['Pad Volume (m³)', ...] -> ['m³', ...] — the shape check that says two
    sheets are printing the same form."""
    return [(re.search(r"\(([^()]*)\)\s*$", c) or [None, ""])[1] for c in cols]


def parse_interval_summary(doc):
    """-> {columns, rows} for Canyon's per-interval TREATMENT INTERVAL
    SUMMARY, or None. One row per treated interval, stitched across the
    sheets the report splits it over."""
    # A well can print the interval summary in more than one shape (a section
    # with no N2/CO2 columns drops them). Bucket the blocks by column shape
    # and return the shape that carries the most intervals rather than
    # stacking mismatched cells under one set of headings.
    buckets = {}
    for p in range(doc.page_count):
        page = doc[p]
        if not is_interval_summary_page(page):
            continue
        spans = _spans(page)
        for blk in _blocks(page, spans):
            if blk[0] != "interval":
                continue
            _k, y, anchors, us, leaves = blk
            left = _left_anchors(spans, y, {"Interval", "Start", "End",
                                            "Comments"})
            if "Interval" not in left or "Start" not in left:
                continue
            names = [_IVL_RENAME.get(l, l) or f"col{i + 1}"
                     for i, l in enumerate(leaves)]
            cols = (["Interval", "Start Time", "End Time", "Comments"]
                    + [f"{n} ({u})" for n, u in zip(names, us)])
            key = tuple(units_of(cols))
            b = buckets.setdefault(key, {"columns": cols, "seen": set(),
                                         "rows": []})
            # some sheets clip a heading word; keep the fullest reading
            b["columns"] = [a if len(a) >= len(c) else c
                            for a, c in zip(b["columns"], cols)]
            day = _treatment_date(page, spans)
            for r in _ivl_rows(spans, anchors, left, y, day):
                k = (r[0], r[1])
                if k in b["seen"]:
                    continue
                b["seen"].add(k)
                b["rows"].append(r)
    if not buckets:
        return None
    best = max(buckets.values(), key=lambda b: len(b["rows"]))
    if not best["rows"]:
        return None
    # interval number then start time: a re-attempted zone prints the same
    # number twice, so the number alone is not a total order.
    best["rows"].sort(key=lambda r: (int(re.sub(r"\D", "", r[0] or "0") or 0),
                                     str(r[1] or "")))
    _label_attempts(best["rows"])
    return _drop_empty({"columns": best["columns"], "rows": best["rows"]})


def _ivl_rows(spans, anchors, left, unit_y, day):
    bands = _bands(anchors)
    first_num = bands[0][0]
    ivl_cx = left["Interval"]
    start_cx = left["Start"]
    end_cx = left.get("End", start_cx + 32)
    out = []
    starts = [s for s in spans if _CLOCK.match(s["t"])
              and abs(s["cx"] - start_cx) < 20 and s["cy"] > unit_y + 2]
    starts.sort(key=lambda s: s["cy"])
    prev = None
    for i, c in enumerate(starts):
        y = c["cy"]
        nxt = starts[i + 1]["cy"] if i + 1 < len(starts) else y + 12
        cells = [None] * (4 + len(anchors))
        dt = _clock_to_dt(day, c["t"], prev)
        if isinstance(dt, datetime):
            prev = dt
            cells[1] = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            cells[1] = dt
        comments = []
        for s in spans:
            if abs(s["cy"] - y) <= 3.5:
                if abs(s["cx"] - ivl_cx) < 12 and _NUMISH.match(s["t"]):
                    cells[0] = _num(s["t"])
                    continue
                if abs(s["cx"] - end_cx) < 20 and _CLOCK.match(s["t"]):
                    e = _clock_to_dt(day, s["t"], prev)
                    cells[2] = e.strftime("%Y-%m-%d %H:%M:%S") \
                        if isinstance(e, datetime) else e
                    continue
            if s["x0"] > end_cx + 6 and s["x1"] < first_num - 2:
                if y - 4 <= s["cy"] < nxt - 4 and re.search(r"\S", s["t"]):
                    comments.append((s["cy"], s["x0"], s["t"]))
                continue
            if abs(s["cy"] - y) > 3.5 or not _CELL.match(s["t"]):
                continue
            for j, (lo, hi) in enumerate(bands):
                if lo <= s["cx"] < hi:
                    if cells[4 + j] is None:
                        cells[4 + j] = _num(s["t"])
                    break
        if comments:
            cells[3] = " ".join(t for _y, _x, t in sorted(comments))
        if cells[0] and any(c is not None for c in cells[4:]):
            out.append(cells)
    return out


# ----------------------------------------- OPERATOR "... Treatment Summary"

# The operator's own landscape sheet. Column headings are stacked three deep
# and centred, so they are read as a block per column rather than per line.
_TS_UNIT = re.compile(r"^\((m|MPa|m3|m3/min|kg/m3|Tonne|Minutes)\)$")


def is_treatment_summary_page(page):
    t = page.get_text()
    return ("Treatment Summary" in t and re.search(r"Port\s*\n?\s*Opening", t)
            is not None and "Breakdown" in t and "Zone" in t)


def parse_treatment_summary(doc):
    """-> {columns, rows} for the operator's per-stage Treatment Summary, or
    None.

    19 columns, one row per stage. The last three are free text — the planned
    proppant, the 'Frac commenced <date> at <time>' note and the operational
    comment that carries the ball-seat differential and, where it happened,
    the record that the zone was SKIPPED. They are joined across their wrapped
    lines and kept verbatim."""
    for p in range(doc.page_count):
        page = doc[p]
        if not is_treatment_summary_page(page):
            continue
        tab = _parse_ts_page(page)
        if tab:
            return tab
    return None


def _merge_intervals(spans, gap=3.0):
    """[(x0, x1)] — x ranges of overlapping/adjacent spans merged together."""
    out = []
    for s in sorted(spans, key=lambda s: s["x0"]):
        if out and s["x0"] <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], s["x1"])
        else:
            out.append([s["x0"], s["x1"]])
    return [(a, b) for a, b in out]


def _parse_ts_page(page):
    spans = _spans(page)
    # Anchor the numeric columns on the stage rows themselves: every stage row
    # is a run of numbers on one baseline, and the widest such run gives the
    # column centres. The heading is three lines deep and centred, so it makes
    # a poor anchor; the data does not.
    stage_rows = []
    for y, cells in _rows(spans, tol=2.5):
        nums = [c for c in cells if _CELL.match(c["t"])]
        if len(nums) >= 10:
            stage_rows.append((y, nums))
    if len(stage_rows) < 2:
        return None
    width = max(len(n) for _y, n in stage_rows)
    anchors = []
    for _y, nums in stage_rows:
        if len(nums) == width:
            anchors = [n["cx"] for n in nums]
            break
    if not anchors:
        return None
    top_y, bot_y = stage_rows[0][0], stage_rows[-1][0]

    # Free-text columns are found from the DATA, not the heading: the operator
    # variants differ (one puts 'Planned Proppant Type and Quantity' between
    # two numeric columns, another puts it after all of them), so the text
    # bands are the x ranges where prose actually lands.
    prose = [s for s in spans
             if top_y - 8 <= s["cy"] <= bot_y + 60
             and s["cx"] > anchors[0] + 10
             and re.search(r"[A-Za-z]{3}", s["t"]) and not _CELL.match(s["t"])]
    text_bands = [(a, b) for a, b in _merge_intervals(prose)
                  if b - a > 25 and not any(a - 4 < x < b + 4 for x in anchors)]

    # one ordered column list: numeric anchors and text bands interleaved
    cols = [("num", a, a, a) for a in anchors] + \
           [("text", (a + b) / 2, a, b) for a, b in text_bands]
    cols.sort(key=lambda c: c[1])
    edges = []
    for i, c in enumerate(cols):
        if i == 0:
            lo = c[2] - 40
        else:
            p = cols[i - 1]
            lo = (p[1] + c[1]) / 2 if (p[0] == "num" and c[0] == "num") \
                else (p[3] if p[0] == "text" else c[2])
        if i + 1 == len(cols):
            hi = c[3] + 60
        else:
            n = cols[i + 1]
            hi = (c[1] + n[1]) / 2 if (n[0] == "num" and c[0] == "num") \
                else (c[3] if c[0] == "text" else n[2])
        edges.append((lo, hi))

    # column names: every heading span above the first data row, dropped into
    # the band it sits over and joined top-down. The page's own title line is
    # far wider than any column, so it is excluded by width.
    names = [[] for _ in cols]
    for s in spans:
        if s["cy"] >= top_y - 8 or s["cy"] < top_y - 42:
            continue
        if s["x1"] - s["x0"] > 250:
            continue
        for i, (lo, hi) in enumerate(edges):
            if lo <= s["cx"] < hi:
                names[i].append((s["cy"], s["cx"], s["t"]))
                break
    columns = []
    for i, parts in enumerate(names):
        txt = re.sub(r"\s+", " ",
                     " ".join(t for _y, _x, t in sorted(parts))).strip()
        columns.append(txt or f"col{i + 1}")

    rows = []
    for i, (y, _nums) in enumerate(stage_rows):
        nxt = stage_rows[i + 1][0] if i + 1 < len(stage_rows) else y + 60
        cells = [None] * len(cols)
        for j, (kind, _c, _a, _b) in enumerate(cols):
            lo, hi = edges[j]
            if kind == "num":
                hit = [s for s in spans if lo <= s["cx"] < hi
                       and abs(s["cy"] - y) <= 3.5 and _CELL.match(s["t"])]
                if hit:
                    cells[j] = _num(hit[0]["t"])
                else:
                    # a numeric column can carry a printed cell that is not one
                    # number: 00009 stage 13 prints '43.8 / 48.81' for sand in
                    # formation (the stage screened out and was reported as two
                    # figures). Dropping it left the column 96.2% filled and
                    # lost a printed value, so the raw text is kept instead.
                    raw = [s for s in spans if lo <= s["cx"] < hi
                           and abs(s["cy"] - y) <= 3.5 and s["t"].strip()]
                    if raw:
                        cells[j] = " ".join(
                            s["t"] for s in sorted(raw, key=lambda s: s["x0"]))
            else:
                # prose wraps over several lines and can start a line above
                # its own row's baseline; take the whole band down to the
                # next stage.
                parts = [s for s in spans if lo <= s["cx"] < hi
                         and y - 8 <= s["cy"] < nxt - 8]
                parts.sort(key=lambda s: (round(s["cy"], 1), s["x0"]))
                joined = re.sub(r"\s{2,}", " ",
                                " ".join(s["t"] for s in parts)).strip()
                cells[j] = joined or None
        # the sheet ends with 'Averages:' and 'Totals:' lines that share the
        # data columns but carry no stage number — those are not stage rows.
        if cells[0] and re.fullmatch(r"\d{1,3}", cells[0]):
            rows.append(cells)
    if not rows:
        return None
    return _drop_empty({"columns": columns, "rows": rows})
