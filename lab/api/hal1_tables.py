"""Halliburton "WELL STIMULATION REPORT" table extraction (the Hal-1 bundle).

Hal-1 documents (Halliburton InSite / PJR report bundled inside a BCER
COMPLETION WORKOVER REPORT) carry a whole engineering report behind the
treatment plots that hal1.py digitises. It is vector text — no OCR — and it
is where the numbers the plots only *draw* are actually printed.

Every section below is one named, ruled grid keyed on "Treatment Interval",
laid out identically: a page title, a stacked multi-line header, an optional
units line, then one row per interval. Cells — including the text ones — are
CENTRE-aligned on a stable x, which is what makes a single positional parser
work across all of them: cluster the data cells' centre-x into column
anchors, then drop the header spans onto those anchors (a group header such
as "FR Water (Other)", centred over its Proposed/Pumped pair, lands on both
by band overlap).

Two shapes of page split have to be stitched back together, and both occur
in the same document:

  - by rows    — AVG / MAX TECHNICAL DATA p29 covers intervals 1..22, p30
                 covers 23..43.
  - by columns — ADDITIVE SUMMARY p25/26 carry seven additives for intervals
                 1..22 and 23..43, p27/28 carry three *different* additives
                 for the same intervals.

So sections are stitched on their key columns with a union of columns, not
by concatenating pages.

Thirteen sections plus the per-interval EVENT LOG are parsed; ACTUAL DESIGN
is listed for viewing only (see DEFERRED).

  - detect(doc): is this a Halliburton stimulation report?
  - find_summary_pages(doc): the report's table pages grouped for viewing.
  - well_header(doc): the well name and UWI the report prints on every page.
  - parse_section(doc, key): one named section as {columns, rows}.
  - parse_sections(doc): every section this module parses, in report order.
  - parse_event_logs(doc): the per-interval EVENT LOG as one long table.
  - event_log_index(doc): the same events keyed by interval, with the
    absolute clock re-expressed in hal1's own time-axis units so the events
    can be laid over the treatment-plot curves (see chart_offset).
  - stage_clock(doc): per-interval start/end datetimes from TREATMENT TIME
    TECHNICAL DATA — the wall clock hal1's plots do not carry.
"""
import re

# ---------------------------------------------------------------- sections
# key      -> (page title as printed, display title, key column count)
# key column count is how many leading columns identify a row: 1 for the
# interval-major tables, 2 for CLUSTER DATA (interval + cluster) and ACTUAL
# DESIGN (interval + stage), 0 for TUBULAR DATA which has no interval at all.
SECTIONS = [
    ("well-completion", "WELL COMPLETION DATA", "Well Completion Data", 1),
    ("fluid-system", "FLUID SYSTEM SUMMARY", "Fluid System Summary", 1),
    ("proppant", "PROPPANT SUMMARY", "Proppant Summary", 1),
    ("additive", "ADDITIVE SUMMARY", "Additive Summary", 1),
    ("avg-max", "AVG / MAX TECHNICAL DATA", "Avg / Max Technical Data", 1),
    ("breakdown", "BREAKDOWN TECHNICAL DATA", "Breakdown Technical Data", 1),
    ("pressure", "PRESSURE TECHNICAL DATA", "Pressure Technical Data", 1),
    ("treatment-time", "TREATMENT TIME TECHNICAL DATA",
     "Treatment Time Technical Data", 1),
    ("qa-qc", "QA / QC TECHNICAL DATA", "QA / QC Technical Data", 1),
    ("tubular", "TUBULAR DATA", "Tubular Data", 0),
    ("custom-vars", "TREATMENT CUSTOM VARIABLES",
     "Treatment Custom Variables", 1),
    ("cluster", "CLUSTER DATA", "Cluster Data", 2),
    ("stage-description", "STAGE DESCRIPTION", "Stage Description", 1),
]
_BY_KEY = {k: (t, d, n) for k, t, d, n in SECTIONS}

# Detected and page-listed, but NOT parsed into a grid.
#
# ACTUAL DESIGN is the per-stage pump schedule — one row per pumping step
# (Pad / PLF / Spacer / Flush), with fluid, proppant type, start and end
# proppant concentration, slurry rate, and clean/slurry/cumulative volumes.
# It is the single richest table in the report and also the only one whose
# Treatment Interval cell is vertically MERGED across the stage's rows
# instead of repeated on each, so its rows have no key of their own. _grid's
# y-nearest fallback is not enough on its own: run over 00382 it returns 738
# rows that collapse to 395 distinct (interval, step) keys, and summing each
# interval's Actual Clean Volume matches FLUID SYSTEM's pumped total for
# only 3 intervals of 30 (1 of 17 on 00407). So the merged cell needs a real
# interval-boundary rule — most likely the Stage Number resetting to 1,
# carried across page breaks — and its own verification pass. Until then
# this section is listed for viewing rather than parsed wrong.
DEFERRED = [
    ("actual-design", "ACTUAL DESIGN", "Actual Design (pump schedule)"),
]

_VIEW_ONLY = [
    ("stimulation-summary", r"^STIMULATION SUMMARY", "Stimulation Summary"),
    ("report-info", r"^REPORT INFORMATION", "Report Information"),
]

_EVENT_TITLE = re.compile(r"EVENT LOG\s*:\s*TREATMENT INTERVAL\s*(\d+)", re.I)


# ------------------------------------------------------------- primitives
_NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2})?$")
_HMS = re.compile(r"^\d{1,3}:\d{2}:\d{2}$")

# Header fragments that are units rather than words. Anything matched here
# is wrapped in parentheses when it lands at the tail of a column name, so
# "Average Pressure" + "MPa" reads "Average Pressure (MPa)" like every other
# table the app ships.
_UNIT = re.compile(
    r"^(m³?|m³/min|m³/m|kg|Kg|L|t|T|tonne|metric tonne|MPa|Mpa|kPa|kPa/m|"
    r"kg/m³|kg/m|mm|%|°C|c|C|spf|inches|deg|count|scm|scm/min|hh:mm|"
    r"hh:mm:ss|min|sec|ppm|SG)$")


def _spans(page):
    """[(x0, x1, cx, cy, text)] for every non-empty span on the page."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                out.append((x0, x1, (x0 + x1) / 2, (y0 + y1) / 2, t))
    return out


def _rows(spans, tol=3.0):
    """spans -> [(cy, [span...])] grouped by baseline, top to bottom."""
    rows = {}
    for sp in sorted(spans, key=lambda s: (s[3], s[0])):
        key = next((k for k in rows if abs(k - sp[3]) < tol), sp[3])
        rows.setdefault(key, []).append(sp)
    return [(y, sorted(v, key=lambda s: s[0])) for y, v in sorted(rows.items())]


def _cellish(t):
    return bool(_NUM.match(t) or _DT.match(t) or _HMS.match(t))


def _is_data_row(cells):
    """A body row: at least two cells, most of them numbers or stamps.

    Header rows fail this because their fragments are words — even the ones
    that carry digits ("7.5% HCl", "100 Mesh Premium White", "30/50 Premium
    White", "(YYYY-MM-DD)") are not bare numbers, and a stacked header line
    contributes at most one fragment per column.

    Two cells, not three: TREATMENT CUSTOM VARIABLES degenerates to a single
    Pad Volume column on some wells (00535), and a three-cell floor threw
    the whole section away there.
    """
    if len(cells) < 2:
        return False
    hits = sum(1 for c in cells if _cellish(c[4]))
    return hits >= max(2, int(0.5 * len(cells)))


def _title_y(page, spans, title):
    """cy of the section-title line, or None. The title is what separates
    the table from the well name and UWI printed above it. It is normally
    one span, but a title that gets split across spans still has to be
    found, so fall back to matching the assembled line."""
    up = title.upper()
    for x0, x1, cx, cy, t in spans:
        if t.strip().upper() == up:
            return cy
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            joined = "".join(s["text"] for s in ln["spans"]).strip().upper()
            if joined == up and ln["spans"]:
                bb = ln["spans"][0]["bbox"]
                return (bb[1] + bb[3]) / 2
    return None


def _anchors(data_rows, tol=4.0):
    """Column centres, from the body cells only.

    Support >= 2 drops the one-off centre a stray comment or footnote would
    otherwise contribute — but a table with only one body row has no centre
    that can reach 2, and TUBULAR DATA is a single Casing row on 45 of the
    71 Hal-1 documents. With one row every cell is a column.
    """
    need = 2 if len(data_rows) > 1 else 1
    hits = {}
    for _y, cells in data_rows:
        for c in cells:
            key = next((k for k in hits if abs(k - c[2]) < tol), c[2])
            hits.setdefault(key, []).append(c[2])
    keep = [sum(v) / len(v) for v in hits.values() if len(v) >= need]
    return sorted(keep)


def _bands(anchors):
    """[(lo, hi)] — each anchor's horizontal territory."""
    out = []
    for i, a in enumerate(anchors):
        lo = -1e9 if i == 0 else (anchors[i - 1] + a) / 2
        hi = 1e9 if i == len(anchors) - 1 else (anchors[i + 1] + a) / 2
        out.append((lo, hi))
    return out


def _header_columns(anchors, head, wide=1.7, edge=0.35):
    """Anchors plus one per header fragment stranded in an over-wide gap."""
    gaps = sorted(anchors[i + 1] - anchors[i] for i in range(len(anchors) - 1))
    pitch = gaps[len(gaps) // 2]
    extra = []
    for _x0, _x1, cx, _cy, _t in head:
        if cx < anchors[0] - 0.75 * pitch or cx > anchors[-1] + 0.75 * pitch:
            extra.append(cx)
            continue
        lo = max([a for a in anchors if a <= cx], default=None)
        hi = min([a for a in anchors if a >= cx], default=None)
        if lo is None or hi is None or hi - lo <= wide * pitch:
            continue
        if min(cx - lo, hi - cx) > edge * (hi - lo):
            extra.append(cx)
    out = list(anchors)
    for cx in sorted(extra):
        if all(abs(a - cx) > 6 for a in out):
            out.append(cx)
    return sorted(out)


_CTRL = re.compile(r"^[\x00-\x08\x0b-\x1f\x7f-\x9f�]+$")


def _fmt_name(parts):
    """['Average', 'Pressure', 'MPa'] -> 'Average Pressure (MPa)'."""
    # The superscript of an m³ unit is sometimes set as its own span in a
    # font whose encoding does not map it, so it arrives as a lone C1
    # control byte sitting just right of the 'm' (00535 p28, Calibri-Bold
    # '\x81'). Fold it back into the unit rather than printing a column
    # called "Pad Volume m \x81".
    clean = []
    for p in parts:
        if p and _CTRL.match(p):
            if clean and clean[-1].endswith("m"):
                clean[-1] += "³"
            continue
        clean.append(p)
    parts = [p for p in clean if p]
    if not parts:
        return ""
    tail = ""
    if len(parts) > 1 and _UNIT.match(parts[-1]):
        tail = " (" + parts.pop() + ")"
    elif len(parts) > 1 and re.fullmatch(r"\(.+\)", parts[-1]):
        tail = " " + parts.pop()
    name = " ".join(parts)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name + tail


def _grid(page, title):
    """One section page -> (columns, rows) or None.

    Columns come from the body cells' centre-x; the header block above the
    first body row is then dropped onto them. A header fragment sitting on
    an anchor belongs to that column alone; one that does not (a group
    header spanning a Proposed/Pumped pair) is given to every column whose
    band it materially overlaps.
    """
    spans = _spans(page)
    ty = _title_y(page, spans, title)
    if ty is None:
        return None
    below = [s for s in spans if s[3] > ty + 2]
    rows = _rows(below)
    data = [(y, c) for y, c in rows if _is_data_row(c)]
    if not data:
        return None
    first_y = data[0][0]
    anchors = _anchors(data)
    if len(anchors) < 2:
        return None
    head = [s for s in below if s[3] < first_y - 4]

    # A column whose cells are nearly all blank leaves no body centre to
    # cluster — QA / QC's "Interval Comments" is filled on 1 interval in 43 —
    # so it has to be recovered from its header alone. The test is the size
    # of the hole: a header fragment stranded inside a gap much wider than
    # the table's own column pitch, and not hugging either side of it, is a
    # column with no data. A *group* header ("7.5% HCl", "Total Fluid")
    # always sits mid-way inside a single ordinary pitch, so it never
    # qualifies — which matters, because "Total Fluid" lands 25.1pt from its
    # nearest anchor in a 50.8pt gap and a flat half-pitch threshold splits
    # the Fluid System table in two.
    if len(anchors) >= 3:
        anchors = _header_columns(anchors, head)
    bands = _bands(anchors)

    def col_of(cx):
        return min(range(len(anchors)), key=lambda i: abs(anchors[i] - cx))

    # --- header: everything between the title and the first body row
    parts = {i: [] for i in range(len(anchors))}
    for x0, x1, cx, cy, t in head:
        i = col_of(cx)
        if abs(anchors[i] - cx) < 4.5:
            parts[i].append((cy, cx, t))
            continue
        for j, (lo, hi) in enumerate(bands):
            if min(x1, hi) - max(x0, lo) > 3:
                parts[j].append((cy, cx, t))
    columns = []
    for i in range(len(anchors)):
        nm = _fmt_name([t for _y, _x, t in sorted(parts[i])])
        columns.append(nm or "col%d" % (i + 1))

    # --- body. A key cell can be vertically merged across the rows it
    # covers (ACTUAL DESIGN does this); when column 0 is empty on a row,
    # fall back to the nearest column-0 span in y, which is the midpoint
    # rule a merged cell implies. It is a floor, not a solution — measured
    # on ACTUAL DESIGN it mis-keys most rows (see DEFERRED) — but on the
    # sections this module does parse every row carries its own key, so the
    # fallback never fires and costs nothing.
    key_spans = [(cy, t) for _y, cells in data for x0, x1, cx, cy, t in cells
                 if abs(cx - anchors[0]) < 4.5]
    out = []
    for y, cells in data:
        row = [None] * len(anchors)
        for x0, x1, cx, cy, t in cells:
            i = col_of(cx)
            if row[i] is None:
                row[i] = t.replace(",", "") if _NUM.match(t) else t
            else:
                row[i] = row[i] + " " + t
        if row[0] is None and key_spans:
            row[0] = min(key_spans, key=lambda k: abs(k[0] - y))[1]
        out.append(row)
    return columns, out


# ------------------------------------------------------------- discovery
_TITLE_CACHE = {}


def _page_titles(doc):
    """[(page_index, TITLE)] for every section page in the report.

    Cached per document: the section sweep asks for this once per section
    and a 254-page Hal-1 bundle carries fourteen of them, so an uncached
    scan re-extracts every page's text fourteen times over.
    """
    ck = (id(doc), getattr(doc, "name", ""), doc.page_count)
    if ck in _TITLE_CACHE:
        return _TITLE_CACHE[ck]
    known = [t for _k, t, _d, _n in SECTIONS] + [t for _k, t, _d in DEFERRED]
    out = []
    for p in range(doc.page_count):
        t = doc[p].get_text()
        head = [l.strip() for l in t.splitlines() if l.strip()][:6]
        for line in head:
            up = line.upper()
            if up in known:
                out.append((p, up))
                break
            if _EVENT_TITLE.match(up):
                out.append((p, "EVENT LOG"))
                break
    if len(_TITLE_CACHE) > 8:
        _TITLE_CACHE.clear()
    _TITLE_CACHE[ck] = out
    return out


def detect(doc):
    """True when this document bundles a Halliburton stimulation report.

    "Halliburton" alone is not enough — the Halliburton IFS reports that
    halliburton_ifs.py handles carry the name too, and they have none of
    these tables. The cover sheet plus the vendor name, or three of the
    named sections, is what identifies this bundle.
    """
    cover = vendor = False
    for p in range(min(doc.page_count, 80)):
        t = doc[p].get_text()
        if "WELL STIMULATION REPORT" in t.upper():
            cover = True
        if "Halliburton" in t:
            vendor = True
        if cover and vendor:
            return True
    return len(_page_titles(doc)) >= 3


_UWI = re.compile(r"\b(\d{3}/[A-Z0-9-]{2,}/\d{2}|\d{3}/[\dA-Z-]+/\d{2})\b")


def well_header(doc):
    """{well, uwi} from the report's own page header. Every section page
    repeats the well name and the UWI above the table, so a table can carry
    its own identity instead of leaning on the filename."""
    for p, _t in _page_titles(doc)[:4]:
        lines = [l.strip() for l in doc[p].get_text().splitlines() if l.strip()]
        if len(lines) >= 2 and _UWI.search(lines[1]):
            return {"well": lines[0], "uwi": lines[1]}
    return {"well": "", "uwi": ""}


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — the report's table pages grouped
    for viewing, in the order they appear. Same contract as bj_summary /
    liberty_summary / calfrac_summary."""
    titles = {t: (k, d) for k, t, d, _n in SECTIONS}
    titles.update({t: (k, d) for k, t, d in DEFERRED})
    groups = []
    for p in range(doc.page_count):
        text = doc[p].get_text()
        head = [l.strip() for l in text.splitlines() if l.strip()][:6]
        kind = title = None
        for line in head:
            up = line.upper()
            if up in titles:
                kind, title = titles[up]
                break
            if _EVENT_TITLE.match(up):
                kind, title = "event-log", "Event Log"
                break
        if kind is None:
            for k, pat, disp in _VIEW_ONLY:
                if re.search(pat, text, re.M):
                    kind, title = k, disp
                    break
        if kind is None:
            continue
        page1 = p + 1
        # The event logs are not consecutive: each interval prints TREATMENT
        # PLOT, CHEMISTRY PLOT, EVENT LOG, so its logs sit three pages apart
        # and the usual 2-page grouping would list 43 separate items.
        gap = 4 if kind == "event-log" else 2
        if groups and groups[-1]["kind"] == kind and \
                page1 - groups[-1]["pages"][-1] <= gap:
            groups[-1]["pages"].append(page1)
        else:
            groups.append({"kind": kind, "title": title, "pages": [page1]})
    return groups


# --------------------------------------------------------------- sections
def parse_section(doc, key):
    """One named section as {columns, rows}, or None.

    Pages are stitched on the section's key columns with a union of the
    data columns, because the same section is split by rows on one pair of
    pages and by columns on the next (ADDITIVE SUMMARY does both).
    """
    if key not in _BY_KEY:
        return None
    title, _disp, nkey = _BY_KEY[key]
    pages = [p for p, t in _page_titles(doc) if t == title]
    if not pages:
        return None

    order, seen = [], {}          # column name -> position
    keyed, plain = {}, []         # key tuple -> {col: val} / row dicts
    korder = []
    for p in pages:
        got = _grid(doc[p], title)
        if not got:
            continue
        cols, rows = got
        for c in cols:
            if c not in seen:
                seen[c] = len(order)
                order.append(c)
        for r in rows:
            rec = {c: v for c, v in zip(cols, r) if v is not None}
            if nkey == 0:
                plain.append(rec)
                continue
            kt = tuple(r[:nkey])
            if any(v is None for v in kt):
                continue
            if kt not in keyed:
                keyed[kt] = {}
                korder.append(kt)
            keyed[kt].update(rec)
    recs = plain if nkey == 0 else [keyed[k] for k in _sorted_keys(korder)]
    if not recs:
        return None
    return {"columns": order,
            "rows": [[r.get(c) for c in order] for r in recs]}


def _sorted_keys(keys):
    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return float("inf")
    return sorted(keys, key=lambda k: tuple(num(v) for v in k))


def parse_sections(doc):
    """[(key, display title, {columns, rows})] for every section present."""
    out = []
    for key, _title, disp, _n in SECTIONS:
        try:
            tab = parse_section(doc, key)
        except Exception:
            tab = None
        if tab and tab.get("rows"):
            out.append((key, disp, tab))
    return out


# -------------------------------------------------------------- event log
def parse_event_logs(doc):
    """Every EVENT LOG page as one long table, or None.

    One row per event, with the interval the page names prepended, so the
    43 per-interval logs read as a single timeline.
    """
    pages = [p for p, t in _page_titles(doc) if t == "EVENT LOG"]
    if not pages:
        return None
    order, seen, rows = [], set(), []
    for p in pages:
        text = doc[p].get_text()
        m = _EVENT_TITLE.search(text)
        if not m:
            continue
        interval = m.group(1)
        title = next(l.strip() for l in text.splitlines()
                     if _EVENT_TITLE.match(l.strip().upper()))
        got = _grid(doc[p], title)
        if not got:
            continue
        cols, prows = got
        for c in cols:
            if c not in seen:
                seen.add(c)
                order.append(c)
        for r in prows:
            rows.append((interval, {c: v for c, v in zip(cols, r)}))
    if not rows:
        return None
    columns = ["Treatment Interval"] + order
    return {"columns": columns,
            "rows": [[iv] + [d.get(c) for c in order] for iv, d in rows]}


def _axis_seconds(stamp):
    """'2024-08-09 01:26:25' -> day*86400 + seconds-of-day.

    That is hal1's own time origin. auto_raster.time_calibration OCRs the
    Hal-1 axis labels, which are printed "DD HH:MM"; the space is lost in
    OCR, so the fit is built on int(DD)*86400 + HH*3600 + MM*60 and
    hal1.extract_image reports it as info['t0_seconds']. Putting the event
    clock in the same units makes the two directly comparable.
    """
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})",
                 str(stamp or ""))
    if not m:
        return None
    _y, _mo, dd, hh, mi, ss = (int(g) for g in m.groups())
    return dd * 86400 + hh * 3600 + mi * 60 + ss


def event_log_index(doc):
    """{interval: [{name, time, axis_s, offset_s}]} for chart annotation.

    axis_s is the event on hal1's plot-axis clock (see _axis_seconds);
    offset_s is seconds from that interval's "Start Pumping" event.

    Measured over 142 treatment plots in 00382/00383/00407/00408: of the 136
    whose axis hal1 reads plausibly, 130 have EVERY logged event inside the
    chart's own time window, and 1167 of 1266 events land inside overall.
    "Start Pumping" sits a median 725s after the chart's left edge and ISIP
    a median 8922s in — the plot opens a few minutes before the job and
    closes a few minutes after, exactly as drawn. So these offsets can be
    laid straight onto hal1's curves as an annotation track.
    """
    tab = parse_event_logs(doc)
    if not tab:
        return {}
    cols = tab["columns"]
    try:
        i_iv = cols.index("Treatment Interval")
    except ValueError:
        return {}
    i_nm = next((i for i, c in enumerate(cols) if c.startswith("Event Name")),
                None)
    i_tm = next((i for i, c in enumerate(cols) if c.startswith("Event Time")),
                None)
    if i_nm is None or i_tm is None:
        return {}
    out = {}
    for r in tab["rows"]:
        out.setdefault(int(r[i_iv]), []).append(
            {"name": r[i_nm], "time": r[i_tm],
             "axis_s": _axis_seconds(r[i_tm])})
    for iv, evs in out.items():
        base = next((e["axis_s"] for e in evs
                     if str(e["name"]).lower().startswith("start pumping")),
                    None)
        if base is None:
            base = next((e["axis_s"] for e in evs
                         if e["axis_s"] is not None), None)
        for e in evs:
            e["offset_s"] = (None if e["axis_s"] is None or base is None
                             else e["axis_s"] - base)
    return out


def chart_offset(events, t0_seconds):
    """Seconds between a treatment plot's digitised time origin and the
    interval's first logged event.

    Normally a few minutes negative: the plot opens before the first event
    (median -588s on 00382, -473s on 00407). A large positive number is not
    a mis-alignment but a giveaway that hal1's time axis was misread — the
    six pages in the four sampled documents that fail this test all report a
    ~5-minute treatment for a stage the log says ran for hours. Used that
    way the event log is an independent check on hal1's own axis, which
    nothing else in the pipeline provides."""
    if not events or t0_seconds is None:
        return None
    firsts = [e["axis_s"] for e in events if e["axis_s"] is not None]
    if not firsts:
        return None
    return float(t0_seconds) - min(firsts)


# ------------------------------------------------------------- stage clock
def stage_clock(doc):
    """{interval: {start, end, well_open, shut_in, pump_time}} from
    TREATMENT TIME TECHNICAL DATA — the wall clock the treatment plots do
    not carry, so a digitised stage can be dated."""
    tab = parse_section(doc, "treatment-time")
    if not tab:
        return {}
    cols = tab["columns"]

    def col(*words):
        for i, c in enumerate(cols):
            if all(w.lower() in c.lower() for w in words):
                return i
        return None
    i_iv, i_st = 0, col("Start", "Time")
    i_en, i_wo = col("End", "Time"), col("Well", "Open")
    i_si, i_pt = col("Shut", "In"), col("Pump", "Time")
    out = {}
    for r in tab["rows"]:
        try:
            iv = int(str(r[i_iv]).strip())
        except (TypeError, ValueError):
            continue
        def g(i):
            return None if i is None else r[i]
        out[iv] = {"start": g(i_st), "end": g(i_en), "well_open": g(i_wo),
                   "shut_in": g(i_si), "pump_time": g(i_pt)}
    return out
