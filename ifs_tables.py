"""Halliburton IFS table extraction — the pumped schedule, not the charts.

`halliburton_ifs.py` reads the IFS *charts* (one page per treatment interval).
This reads the IFS *tables*, which no other module touched: every IFS report in
the corpus prints a "Stage Summary" grid per interval, one row per PUMP STAGE
(Circulate / Acid / Pad / a proppant ramp step / Spacer / Flush / Shut-In) with
that stage's start time, pressures, rates, clean & slurry volumes, proppant
concentration and proppant mass. That is the actual pumped schedule.

  - find_summary_pages(doc): the table pages grouped for viewing.
  - parse_stage_summary(doc): every interval's Stage Summary (plus the v4.4.0
    "Foam Stage Summary" companion, joined on the same stage) stitched into one
    {columns, rows} grid — ONE ROW PER PUMP STAGE.
  - parse_treatment_summary(doc): the v4.6.3 whole-well roll-up, a genuinely
    different table — one row per INTERVAL — returned on its own.

GRAIN AND THE JOIN.  A Stage Summary row is *inside* an interval, so it does
not line up 1:1 with anything the chart side emits. The join key is the
`Interval` column: `halliburton_ifs.extract_page` sets `meta.stage` to the
interval number, which the pipeline carries into every series row, so

    stage-summary row.Interval  ==  series meta.stage        (same UWI)

gives each interval's chart the list of pump stages that produced it, and
`Start Time` (clock time of day, the same clock the chart's time axis is
calibrated against in `_time_axis`) places each pump stage on that chart. In
other words: the chart says what the well did, this table says what was pumped
to make it do that, and `Interval` + `Start Time` is the seam.

FOUR BUILDS, FOUR HEADINGS.  Section numbering is NOT stable — v4.2.0 prints
"1.1 Stage Summary" under "1.0 INTERVAL 1", v4.3.1 prints "2.3 Stage Summary"
(section 2 == interval 1) or "4.1" in the per-interval bundles, v4.4.0 "1.1",
v4.6.3 "1.1" — so nothing here anchors on a section number. Pages are found by
the heading TEXT plus the "(IFS v" footer, and the interval is resolved from
whichever of four independent signals the build actually prints (see
`_interval_for_page`).
"""
import re

# ---------------------------------------------------------------- page finding

SUMMARY_KINDS = [
    ("stage", r"^(?:\d{1,3}\.\d{1,2}\s+)?(?:ACTUAL\s+)?Stage Summary\s*$"),
    ("foam", r"^(?:\d{1,3}\.\d{1,2}\s+)?(?:ACTUAL\s+)?Foam Stage Summary\s*$"),
    ("treatment", r"^TREATMENT SUMMARY\s*$"),
    ("schedule", r"^(?:\d{1,3}\.\d{1,2}\s+)?(?:Proposed\s+)?Pumping Schedule\s*$"),
    ("chemicals", r"^(?:\d{1,3}\.\d{1,2}\s+)?Chemical (?:Additives|Summary)\s*$"),
]
KIND_TITLES = {
    "stage": "Stage Summary (pumped schedule)",
    "foam": "Foam Stage Summary (N₂)",
    "treatment": "Treatment Summary (per-interval roll-up)",
    "schedule": "Pumping Schedule (design)",
    "chemicals": "Chemical Additives",
}

# IFS prints the heading either as its own line under a bare section number
# ("4.1" / "Stage Summary") or as one line ("10.3 Stage Summary"). Both, plus
# the Foam variant, and one file lower-cases it ("8.2 Foam Stage summary").
# THE SECTION MAJOR IS NOT TWO DIGITS. One section per interval means a
# hundred-interval well numbers its sections past 99: Shell's 102-interval
# v7.0.0 report prints "100.1 Stage Summary", "101.1", "102.1", and a
# two-digit major silently dropped those three intervals — the parse looked
# complete (99 clean pages, every printed total reconciling) because the pages
# were never seen at all. Three digits everywhere a section number is read.
_HEADS = {
    "stage": re.compile(r"^\s*(?:(\d{1,3})\.(\d{1,2})\s+)?Stage Summary\s*$",
                        re.I),
    "foam": re.compile(r"^\s*(?:(\d{1,3})\.(\d{1,2})\s+)?Foam Stage Summary\s*$",
                       re.I),
}
_SECTION_ONLY = re.compile(r"^\s*(\d{1,3})\.(\d{1,2})\s*$")
# a table of contents line: "... Stage Summary ......... 89"
_TOC = re.compile(r"\.{5,}")


def detect(doc_or_page):
    """True for an IFS document/page (the footer every build prints).

    Scans the WHOLE document. It used to stop at page 40, on the assumption
    that a filing leads with its IFS pages — and #330 is the filing that does
    not: 00056 carries "(IFS v" on 129 of its 180 pages and the first is page
    52, so the marker was there in bulk and the detector never saw it. The
    charts still came out, because those detect per page, which is why it read
    as "tables not showing up" rather than as a file that failed.

    any() short-circuits, so a real IFS document costs a page or two; only a
    document that is not IFS at all pays for the full scan, and that is the
    case where being sure is worth it.
    """
    if hasattr(doc_or_page, "page_count"):
        return any("(IFS v" in doc_or_page[p].get_text()
                   for p in range(doc_or_page.page_count))
    return "(IFS v" in doc_or_page.get_text()


def build_version(doc):
    """-> the IFS build string(s) printed in the footer, e.g. '4.6.3'."""
    seen = []
    for p in range(doc.page_count):
        for m in re.finditer(r"\(IFS v\s*([\d.]+)\)", doc[p].get_text()):
            if m.group(1) not in seen:
                seen.append(m.group(1))
        if seen and p > 20:
            break
    return seen


def _page_kind(text):
    if _TOC.search(text) and "Table of Contents" in text:
        return None
    for line in text.splitlines():
        s = line.strip()
        if not s or _TOC.search(s):
            continue
        for kind, pat in SUMMARY_KINDS:
            if re.match(pat, s, re.I):
                return kind
    return None


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — consecutive same-kind pages grouped,
    matching the shape bj_summary/liberty_summary/calfrac_summary return."""
    groups = []
    for p in range(doc.page_count):
        text = doc[p].get_text()
        if "(IFS v" not in text:
            continue
        kind = _page_kind(text)
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


# ------------------------------------------------------------------- geometry
# Most IFS table pages are filed /Rotate 90, and PyMuPDF hands back span boxes
# in the *unrotated* media box, so a "row" reads as a column of x values.
# halliburton_ifs solves the same problem for charts with page_rotated() +
# _unrotate(); the identical transform is repeated here rather than imported so
# this module stays free of the chart module's numpy/frac_core dependencies
# (it is mirrored into lab/api, where imports are the deployment surface).


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


def _spans(page, rotated=None):
    """-> [{t, x0, x1, cx, cy}] in CANONICAL (reading) orientation."""
    if rotated is None:
        rotated = _rotated(page)
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for sp in line["spans"]:
                t = sp["text"].replace("\xa0", " ").replace(" ", " ").strip()
                if not t:
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                if rotated:
                    # (x, y) -> (-y, x): the same map halliburton_ifs uses
                    x0, x1, y0, y1 = -y1, -y0, x0, x1
                out.append({"t": t, "x0": x0, "x1": x1,
                            "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def _lines(spans, tol=2.5):
    """spans -> [(cy, [spans left-to-right])], one entry per visual text line."""
    rows = {}
    for s in sorted(spans, key=lambda s: (s["cy"], s["x0"])):
        key = next((k for k in rows if abs(k - s["cy"]) < tol), None)
        rows.setdefault(s["cy"] if key is None else key, []).append(s)
    return [(y, sorted(v, key=lambda s: s["x0"])) for y, v in sorted(rows.items())]


# ------------------------------------------------------------ header / columns

_UNIT_FIX = [
    (re.compile(r"\bKg\s*/\s*m\s*3\b", re.I), "kg/m³"),
    (re.compile(r"\bkg\s*/\s*m³"), "kg/m³"),
    (re.compile(r"\bm\s*3\s*/\s*min\b"), "m³/min"),
    (re.compile(r"\bm\s*3\b"), "m³"),
    (re.compile(r"\bscmm\b", re.I), "scmm"),
]
_UNIT_TOKENS = ("MPa", "kPa", "m³/min", "m³", "m", "tonne", "kg/m³", "min",
                "scmm", "scm", "%", "Hours", "hr", "kg")


def _squash(text):
    """Whitespace-free form, for matching a heading that the PDF split into
    small-caps runs: v4.6.3 emits TREATMENT SUMMARY as the four spans
    'T','REATMENT','S','UMMARY', which no amount of joining puts back."""
    return re.sub(r"\s+", "", text or "")


def _clean(text):
    t = re.sub(r"\s+", " ", text).strip()
    for pat, rep in _UNIT_FIX:
        t = pat.sub(rep, t)
    return t


def _columns(header_spans):
    """Header spans -> [{name, unit, lo, hi}] left-to-right.

    Columns are found by x-overlap, not by clustering a single header row:
    IFS stacks a heading over two to four lines ("Avg" / "Treating" /
    "Pressure" / "MPa") and the stack is centred, so the words in one column
    overlap each other in x and never reach the next column.
    """
    if not header_spans:
        return []
    groups = []
    for s in sorted(header_spans, key=lambda s: s["x0"]):
        if groups and s["x0"] <= groups[-1]["hi"] + 1.2:
            groups[-1]["hi"] = max(groups[-1]["hi"], s["x1"])
            groups[-1]["spans"].append(s)
        else:
            groups.append({"lo": s["x0"], "hi": s["x1"], "spans": [s]})
    cols = []
    for g in groups:
        words = [sp["t"] for sp in sorted(g["spans"],
                                          key=lambda s: (round(s["cy"], 1), s["x0"]))]
        raw = _clean(" ".join(words))
        unit = ""
        for u in _UNIT_TOKENS:
            if raw.endswith(" " + u) or raw == u:
                unit = u
                raw = raw[:-len(u)].strip()
                break
        cols.append({"name": raw, "unit": unit,
                     "lo": g["lo"], "hi": g["hi"]})
    _widen(cols)
    return cols


def _widen(cols):
    """Grow every column to the midpoint of the gap to its neighbours, so a
    data cell wider than its heading ("30/50 @ 75-100" under "Description")
    still lands in the right place. Reads the ORIGINAL edges, never the
    already-widened ones, or each column creeps right and leaves an unclaimed
    strip between itself and its neighbour."""
    edges = [(c["lo"], c["hi"]) for c in cols]
    for i, c in enumerate(cols):
        lo, hi = edges[i]
        left = edges[i - 1][1] if i else lo - 40
        right = edges[i + 1][0] if i + 1 < len(edges) else hi + 40
        c["lo"] = (left + lo) / 2
        c["hi"] = (hi + right) / 2


def _columns_from_data(cells, header_spans):
    """Columns derived from the data cells' x positions, named from whatever
    header spans sit over each one. The counterpart to `_columns`, for the
    dense portrait Treatment Summary where the headings are too crowded to
    separate but the data is not."""
    if not cells:
        return []
    groups = []
    for s in sorted(cells, key=lambda s: s["cx"]):
        if groups and s["cx"] - groups[-1]["cx"] <= 5:
            groups[-1]["lo"] = min(groups[-1]["lo"], s["x0"])
            groups[-1]["hi"] = max(groups[-1]["hi"], s["x1"])
            groups[-1]["cx"] = s["cx"]
        else:
            groups.append({"lo": s["x0"], "hi": s["x1"], "cx": s["cx"]})
    cols = [{"name": "", "unit": "", "lo": g["lo"], "hi": g["hi"]}
            for g in groups]
    _widen(cols)
    words = {i: [] for i in range(len(cols))}
    for s in header_spans:
        i = next((i for i, c in enumerate(cols)
                  if c["lo"] <= s["cx"] <= c["hi"]), None)
        if i is None:
            i = min(range(len(cols)),
                    key=lambda i: abs((cols[i]["lo"] + cols[i]["hi"]) / 2 - s["cx"]))
        words[i].append(s)
    for i, c in enumerate(cols):
        raw = _clean(" ".join(s["t"] for s in sorted(
            words[i], key=lambda s: (round(s["cy"], 1), s["x0"]))))
        for u in _UNIT_TOKENS:
            if raw.endswith(" " + u) or raw == u:
                c["unit"] = u
                raw = raw[:-len(u)].strip()
                break
        c["name"] = raw or f"col{i + 1}"
    return cols


# ---------------------------------------------------------- canonical naming
# Every build words the same quantity differently ("Avg Treating Pressure" vs
# "Avg Treat Pr", "Avg Slurry Prop Conc" vs "Avg Prop Conc"). Charts already do
# this with halliburton_ifs.STD_NAMES; the same idea, one entry per column, so
# a v4.2.0 file and a v4.6.3 file produce the same CSV header.
STD_COLUMNS = [
    (("stage number",), "Stage Number", ""),
    (("description",), "Description", ""),
    (("start time",), "Start Time", ""),
    (("pump time",), "Pump Time", "min"),
    (("time",), "Stage Time", "min"),
    # keys carry the quantity, not just "avg treat": the Treatment Summary
    # prints "Avg Treating Rate" right beside "Avg Treating Pressure", and a
    # prefix key silently relabelled the rate as a pressure (in MPa)
    (("max treat pr", "max treating pressure", "max treat pressure"),
     "Max Treating Pressure", "MPa"),
    (("avg treat pr", "avg treating pressure", "avg treat pressure"),
     "Avg Treating Pressure", "MPa"),
    (("avg treating rate", "avg treat rate"), "Avg Treating Rate", "m³/min"),
    (("avg clean rate",), "Avg Clean Rate", "m³/min"),
    (("avg slurry rate",), "Avg Slurry Rate", "m³/min"),
    (("clean volume",), "Clean Volume", "m³"),
    (("slurry volume",), "Slurry Volume", "m³"),
    (("avg slurry prop conc", "avg prop conc"), "Avg Prop Conc", "kg/m³"),
    (("prop mass",), "Prop Mass", "tonne"),
    # v4.4.0 foam companion
    (("max well head rate",), "Max WH Rate", "m³/min"),
    (("avg well head rate",), "Avg WH Rate", "m³/min"),
    (("wh volume",), "WH Volume", "m³"),
    (("max n2 standard rate",), "Max N2 Rate", "scmm"),
    (("avg n2 standard rate",), "Avg N2 Rate", "scmm"),
    (("avg clean quality",), "Avg Clean Quality", "%"),
    (("n2 standard volume",), "N2 Volume", "scm"),
]


# IFS only ever totals the EXTENSIVE columns — it prints no total under a
# pressure, a rate or a concentration. That is what makes the printed Total
# line readable without trusting its x positions, which is necessary: 00003
# reorders its columns mid-document (p9 puts Prop Conc after the volumes, p79
# puts it before them) and prints the total line in the OLD order both times,
# so on p79 the clean-volume total sits under the Prop Conc heading. Reading
# the total cells in x order onto the summable columns recovers it exactly.
SUMMABLE = ("Stage Time", "Pump Time", "Clean Volume", "Slurry Volume",
            "Prop Mass", "WH Volume", "N2 Volume")


def _std(name, unit):
    low = re.sub(r"\s+", " ", name).strip().lower()
    for keys, std, std_unit in STD_COLUMNS:
        if any(low == k or low.startswith(k) for k in keys):
            return std, (std_unit or unit)
    # a heading word can be split across two spans that land on different
    # header lines ("WH" / "Volum" / "e" on 00080 p77, one page in the corpus),
    # which no amount of x-grouping repairs. Retry ignoring whitespace.
    tight = re.sub(r"\s+", "", low)
    for keys, std, std_unit in STD_COLUMNS:
        if any(tight == re.sub(r"\s+", "", k) for k in keys):
            return std, (std_unit or unit)
    return _clean(name), unit


def _label(name, unit):
    return f"{name} ({unit})" if unit else name


# ------------------------------------------------------------------- row scan

_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_TIMEISH = re.compile(r"^\d{1,2}:\d{2}")
# "1 - 7", but the dash is not always a hyphen: 00107 p127 prints one row of
# an otherwise ordinary table as "17 – 12" with an EN DASH, and an ASCII-only
# pattern dropped that row and the one after it AND mistook the row for the
# table's Total line, which silently truncated the interval.
_STAGENO = re.compile(r"^(\d{1,3})\s*[-‐‑‒–—]\s*(\d{1,3})$")
_NUM = re.compile(r"^-?[\d,]+(\.\d+)?$")


def _dense(cells):
    return sum(1 for s in cells if _NUM.match(s["t"]) or _TIMEISH.match(s["t"]))


def _snap_time_column(cols, time_cells):
    """Pin the Start-Time column's edges to the actual HH:MM:SS cells.

    Column bands otherwise come from the heading text alone, and a Description
    cell is centred in a box far wider than the word "Description": on 00109
    p84 "Spacer" is printed 40 pt right of its own heading and landed in Start
    Time, producing 'Spacer04:57:14'; on 00116 p74 "Pad" missed the boundary by
    0.05 pt. The time cells are the one class of cell whose column is never in
    doubt, so they are what the boundary should be measured from.
    """
    if not time_cells or len(cols) < 2:
        return
    lo = min(s["x0"] for s in time_cells)
    hi = max(s["x1"] for s in time_cells)
    mid = (lo + hi) / 2
    i = min(range(len(cols)),
            key=lambda i: abs((cols[i]["lo"] + cols[i]["hi"]) / 2 - mid))
    # the time column IS its cells; its neighbours own everything up to them
    cols[i]["lo"], cols[i]["hi"] = lo - 0.5, hi + 0.5
    if i:
        cols[i - 1]["hi"] = cols[i]["lo"]
    if i + 1 < len(cols):
        cols[i + 1]["lo"] = cols[i]["hi"]


def _table_body(spans, head_cy):
    """-> (columns, row_lines, totals_line) for the table under `head_cy`.

    A row is anchored on its leading STAGE-NUMBER cell ("7" or "1 - 7") on a
    numerically dense line. Anchoring on the start time instead was the obvious
    choice and it is wrong: in 00002 the Start-Time column is narrow enough
    that IFS wraps the cell itself, printing "00:09:3" and then "6" on the next
    line, so a whole interval's table parsed as nothing at all. The stage
    number never wraps.

    Everything that is not an anchor line belongs to the anchor ABOVE it, but
    ONLY if it is the kind of thing that wraps: a description, or the tail of a
    wrapped start time. Both live in the label columns, so any stray line that
    reaches into a numeric column is the report's own Total instead — which
    v4.6.3 and v4.5.1 print with no "Total" label at all, and which v4.5.1 can
    print with as few as three numbers on it, so counting numbers is not enough
    to recognise it (00118 p184 has a two-row table whose three-number total
    line was absorbed into row 2, giving a Pump Time of "18.3719.45161").
    """
    below = [s for s in spans if s["cy"] > head_cy + 1]
    lines = _lines(below)
    first_i = next((i for i, (_cy, c) in enumerate(lines) if _dense(c) >= 4), None)
    if first_i is None:
        return None
    header = [s for _cy, c in lines[:first_i] for s in c
              if not _TIMEISH.match(s["t"])]
    if not header:
        return None
    cols = _columns(header)
    if len(cols) < 5:
        return None
    _snap_time_column(cols, [s for _cy, c in lines[first_i:] for s in c
                             if _TIME.match(s["t"])])
    col0_hi = cols[0]["hi"]
    # the label columns: everything up to and including Start Time. Only these
    # ever hold a wrapped fragment.
    label_hi = next((c["hi"] for c, (n, _u) in
                     zip(cols, (_std(c["name"], c["unit"]) for c in cols))
                     if n == "Start Time"), cols[min(2, len(cols) - 1)]["hi"])

    def is_anchor(cells):
        if _dense(cells) < 4:
            return False
        lead = cells[0]
        return lead["cx"] <= col0_hi and (
            re.fullmatch(r"\d{1,3}", lead["t"]) or _STAGENO.match(lead["t"]))

    # the page-number footer sits hundreds of points below the last row and is
    # a "line" like any other; nothing more than a few row pitches below the
    # last stage can belong to the table
    anchors = [cy for cy, c in lines[first_i:] if is_anchor(c)]
    if not anchors:
        return None
    gaps = sorted(b - a for a, b in zip(anchors, anchors[1:]))
    pitch = gaps[len(gaps) // 2] if gaps else 12.0
    cutoff = anchors[-1] + 3 * max(pitch, 6.0)

    rows, totals = [], None
    for cy, cells in lines[first_i:]:
        if cy > cutoff:
            break
        if is_anchor(cells):
            rows.append(list(cells))
            continue
        if not rows:
            continue
        if all(s["cx"] <= label_hi for s in cells):
            rows[-1].extend(cells)           # wrapped description / time tail
            continue
        totals = cells                       # the printed Total line: stop
        break
    return cols, rows, totals


def _join(acc, frag):
    """Append a wrapped fragment to the cell it continues.

    Two different things wrap into one cell and they need opposite treatment.
    A wrapped START TIME must be glued with nothing between it and its tail —
    00002 prints "00:09:3" and then "6" — while a wrapped DESCRIPTION breaks at
    a SPACE, and gluing it welded the words either side of the break: 30349 p245
    printed "... (Ramp abandoned at approx 200 kg/m3 ...)" and the parse read
    "(Rampabandoned at approx 200kg/m3 ...)". Four of that report's 987 rows
    carried a description mangled this way.

    A digit on both sides of the break is a split token (a time, a number);
    anything else is a word break, which is what the space belongs to.
    """
    if not acc:
        return frag
    if _TIMEISH.match(acc) or (acc[-1].isdigit() and frag[:1].isdigit()):
        return acc + frag
    return acc + " " + frag


def _assign(cells, cols):
    """cells -> [text per column]; a cell goes to the column its centre lands
    in, and repeat hits in one column are joined (wrapped descriptions)."""
    out = [None] * len(cols)
    for s in sorted(cells, key=lambda s: (s["cy"], s["x0"])):
        ci = None
        for i, c in enumerate(cols):
            if c["lo"] <= s["cx"] <= c["hi"]:
                ci = i
                break
        if ci is None:
            ci = min(range(len(cols)),
                     key=lambda i: abs((cols[i]["lo"] + cols[i]["hi"]) / 2 - s["cx"]))
        v = s["t"].replace(",", "") if _NUM.match(s["t"]) else s["t"]
        out[ci] = v if out[ci] is None else _join(out[ci], v)
    return out


# -------------------------------------------------------- interval resolution

# Interval identifiers are not always bare integers: 00001 files a re-frac as
# "Interval 4A" and 00002 gives interval 4's flush its own section headed
# "6.0 INTERVAL 4 FLUSH". Both are captured as a LABEL alongside the numeric
# interval, so the number still joins to the charts while the label keeps two
# stage tables that share an interval distinguishable.
_IV_HEAD = re.compile(r"^\s*(\d{1,3})\.0\s+INTERVAL\s+"
                      r"(\d{1,3}[A-Z]?)((?:\s+[A-Z]+)*)", re.I | re.M)
_IV_TITLE = re.compile(r"Interval\s+(\d{1,3}[A-Z]?)\s*[-–‐]\s*"
                       r"(?:Entire|Main|Breakdown|ISIP|Chemical)", re.I)
_IV_PLAIN = re.compile(r"Interval\s+(\d{1,3}[A-Z]?)((?:\s+[A-Za-z]+)?)")
_STOPWORDS = ("M", "MONTNEY", "CONSISTED", "OF")
# "Interval 4A" — a single letter welded to the number, no space. Used only to
# recover a suffix the stage-number prefix cannot carry (see _suffixed).
_IV_SUFFIXED = re.compile(r"Interval\s+(\d{1,3})([A-Za-z])(?![A-Za-z0-9])")


def _iv_label(num, tail):
    tail = " ".join(w for w in (tail or "").split()
                    if w.upper() not in _STOPWORDS)
    return (num + (" " + tail if tail else "")).strip()


def _iv_num(label):
    m = re.match(r"(\d{1,3})", label or "")
    return int(m.group(1)) if m else None


def _iv_key(interval, label):
    """The value that joins a table row to a CHART's `meta.stage`.

    halliburton_ifs now reports an interval as printed, suffix included ("4A"),
    so the bare number no longer identifies a treatment: 00001's re-frac 4A and
    its first treatment 4 would both join to 4, which is the merge this pairing
    exists to stop. Take the label's leading identifier where it is one, which
    leaves "4 FLUSH" — a section OF interval 4, charted as plain 4 — joining on
    "4" exactly as before.
    """
    m = re.match(r"\s*(\d{1,3}[A-Za-z]?)(?![A-Za-z0-9])", label or "")
    if m:
        return m.group(1)
    return "" if interval is None else str(interval)


def _suffixed(text, num):
    """-> "4A" if this page prints interval `num` with a letter suffix, else "".

    The stage-number prefix ("4 - 1") carries the interval NUMBER and nothing
    else. On 00001 that is the signal that wins — the Stage Summary pages print
    no "N.0 INTERVAL ..." opener — so a report that files a re-frac as
    `Interval 4A` and its first treatment as `Interval 4` handed back the bare
    "4" for both, and the two collapsed into one interval group holding both
    treatments' stages. Same defect as the BJ `Stage 06 Plug Slip` merge fixed
    in `bj1.py`, and fixed the same way: keep the printed suffix in the key.

    Conservative by construction, exactly as bj1 is: the suffix must be a
    SINGLE letter welded to the number, the number must be the one the stage
    prefixes already agreed on, and if the page prints two different suffixes
    for that number (a contents page, a bundle cover) nothing changes. A plain
    numeric interval prints no suffix and is therefore untouched.
    """
    found = ""
    for m in _IV_SUFFIXED.finditer(text):
        if int(m.group(1)) != num:
            continue
        lab = m.group(1) + m.group(2)
        if found and found != lab:
            return ""
        found = lab
    return found


def _section_map(doc):
    """{section major -> interval}. v4.3.1 (and only v4.3.1) prints Stage
    Summary pages that name no interval at all — "2.3 Stage Summary" with bare
    stage numbers 1..26 — so the interval has to come from the section opener
    ("2.0 INTERVAL 1: 4282 M") or from a chart title elsewhere in the same
    section. Anchoring on the section NUMBER is exactly what does not port
    between builds, which is why this is a per-document lookup built from the
    document's own headings rather than a constant."""
    smap = {}
    for p in range(doc.page_count):
        text = doc[p].get_text().replace("\xa0", " ")
        if "(IFS v" not in text:
            continue
        for m in _IV_HEAD.finditer(text):
            smap.setdefault(int(m.group(1)),
                            (_iv_label(m.group(2), m.group(3)),
                             _interval_depth(text)))
        sec = None
        for line in text.splitlines():
            m = re.match(r"^\s*(\d{1,3})\.(\d{1,2})\b", line)
            if m:
                sec = int(m.group(1))
                break
        if sec is None or _TOC.search(text):
            continue
        m = _IV_TITLE.search(text)
        if m:
            smap.setdefault(sec, (m.group(1), ""))
    return smap


def _interval_for_page(page_text, section, stage_nums, smap):
    """-> (interval number, label, depth, source) for a Stage Summary page.

    Four builds, four different places the interval is printed — tried
    strongest first so one build's fallback never overrides another's fact:
      1. "1.0 INTERVAL 1: 2645.06 M" on this very page (v4.2.0/4.4.0/4.6.3)
      2. the stage-number prefix, "1 - 7" -> interval 1 (same three builds)
      3. "... SEPTIMUS A4-5-82-19W6 Interval 4A" in the page header (v4.3.1
         per-interval bundles)
      4. section major -> interval, from the document's own headings (v4.3.1
         single-document reports, the only build that prints nothing local)
    """
    text = page_text.replace("\xa0", " ").replace(" ", " ")
    depth = _interval_depth(text)
    m = _IV_HEAD.search(text)
    if m:
        lab = _iv_label(m.group(2), m.group(3))
        return _iv_num(lab), lab, depth, "heading"
    if stage_nums:
        pre = {n for n in stage_nums if n is not None}
        if len(pre) == 1:
            n = pre.pop()
            return n, _suffixed(text, n) or str(n), depth, "stage-number"
    m = _IV_PLAIN.search(text)
    if m:
        lab = _iv_label(m.group(1), m.group(2))
        return _iv_num(lab), lab, depth, "page-header"
    if section is not None and section in smap:
        # v4.3.1 keeps the depth on the section opener a page or two before the
        # Stage Summary ("2.0 INTERVAL 1: 4282 M" on p11, "2.3 Stage Summary"
        # on p13), so it rides along with the section lookup
        lab, sdepth = smap[section]
        return _iv_num(lab), lab, depth or sdepth, "section-map"
    return None, "", depth, ""


_UWI = re.compile(r"UWI:?\s*([0-9A-Za-z]{2,3}[/\-][0-9A-Za-z\-]+[/\-][0-9A-Za-z\-/]+)")


def _page_uwi(text):
    """The page-header UWI, canonicalised the way pipeline.canon_uwi does.

    Chinook's v4.4.0 header omits the two-digit event sequence
    ("UWI:200/A-073-L/094-H-03"), which canonicalises to 14 characters and
    would then fail to join the 16-character UWI the seconds export writes —
    halliburton_ifs.extract_page already appends the same "00" for the same
    reason."""
    m = _UWI.search(text)
    if not m:
        return ""
    u = re.sub(r"[^0-9A-Za-z]", "", m.group(1)).upper()
    return u + "00" if len(u) == 14 else u


_DEPTH_TAIL = re.compile(r"\s*[:(]?\s*([\d,]+\.?\d*)\s*(?:-\s*[\d,.]+\s*)?M\b",
                         re.I)


def _interval_depth(text):
    """The interval depth IFS prints beside the heading, when it prints one:
    "1.0 INTERVAL 1: 2645.06 M" / "1.0 INTERVAL 1 (4046.6M)". Several builds
    print "1.0 INTERVAL 1:" with nothing after it — v4.6.3 and v7.0.0 both do,
    and so does their table of contents, so on those the depth is not a missed
    read, it is not in the document (see `_interval_depths`).

    The interval identifier can carry a letter ("INTERVAL 4A: 2645.06 M"); an
    integer-only pattern failed to match those and lost a depth that WAS
    printed.
    """
    m = re.search(r"\d{1,3}\.0\s+INTERVAL\s+\d{1,3}[A-Za-z]?\s*[:(]?\s*"
                  r"([\d,]+\.?\d*)\s*(?:-\s*[\d,.]+\s*)?M", text, re.I)
    return m.group(1).replace(",", "") if m else ""


def _interval_depths(doc):
    """{interval label -> depth} from every "N.0 INTERVAL x: DDDD M" opener in
    the document.

    A Stage Summary page does not always carry its own opener: v4.3.1 prints it
    on the section's first page, one or two pages earlier, and a table that
    runs onto a second page repeats no heading at all. `_interval_for_page`
    already rides the section map for that case, but only on the ONE branch
    that consults the section map — a page that resolved its interval from its
    own heading or from the stage-number prefix got no depth even when the
    document printed one elsewhere. Depth belongs to the interval, not to the
    page, so it is read once per document and joined on the interval label.
    """
    out = {}
    for p in range(doc.page_count):
        text = doc[p].get_text().replace("\xa0", " ")
        if "(IFS v" not in text or _TOC.search(text):
            continue
        for m in _IV_HEAD.finditer(text):
            lab = _iv_label(m.group(2), m.group(3))
            if lab in out:
                continue
            d = _DEPTH_TAIL.match(text, m.end())
            if d:
                out[lab] = d.group(1).replace(",", "")
    return out


# ------------------------------------------------------------- page-level API

def is_stage_summary_page(page, kind="stage"):
    text = page.get_text()
    if "(IFS v" not in text or "Table of Contents" in text:
        return False
    lines = [l.replace("\xa0", " ").strip() for l in text.splitlines()]
    for pat in (_HEADS[kind], _HEADS_ACTUAL[kind]):
        for i, s in enumerate(lines):
            if _TOC.search(s):
                continue                      # a contents entry, not a table
            if pat.match(s):
                return True
            # "4.1" on its own line with "Stage Summary" on the next
            if _SECTION_ONLY.match(s) and i + 1 < len(lines) and \
                    pat.match(lines[i + 1]):
                return True
    return False


_HEADS_TIGHT = {
    "stage": re.compile(r"^(?:(\d{1,3})\.(\d{1,2}))?StageSummary$", re.I),
    "foam": re.compile(r"^(?:(\d{1,3})\.(\d{1,2}))?FoamStageSummary$", re.I),
}
# The SECTION title, "4.0 ACTUAL STAGE SUMMARY", which v4.3.1 prints above the
# sub-heading "4.1 Stage Summary". On most pages both are there and the
# sub-heading is the one to anchor on — it sits lower, so anchoring on the
# section title instead would feed "4.1" and "Stage Summary" into the column
# header and shred the grid. But three of 00001's ten interval tables (6A, 6B
# and 7, pages 101/114/127) print the section title and NO sub-heading, and
# with only the sub-heading pattern those three pages were never recognised as
# tables at all: 30% of that report's pumped schedule was missing and nothing
# said so. Tried strictly second, so a page carrying both is unaffected.
_HEADS_ACTUAL = {
    "stage": re.compile(
        r"^\s*(?:(\d{1,3})\.(\d{1,2})\s+)?ACTUAL\s+Stage Summary\s*$", re.I),
    "foam": re.compile(
        r"^\s*(?:(\d{1,3})\.(\d{1,2})\s+)?ACTUAL\s+Foam Stage Summary\s*$",
        re.I),
}
_HEADS_TIGHT_ACTUAL = {
    "stage": re.compile(r"^(?:(\d{1,3})\.(\d{1,2}))?ACTUALStageSummary$", re.I),
    "foam": re.compile(r"^(?:(\d{1,3})\.(\d{1,2}))?ACTUALFoamStageSummary$",
                       re.I),
}


def _heading(spans, kind):
    """-> (cy, section major) of the Stage/Foam Summary heading, or None."""
    lines = _lines(spans)
    for pat, tight in ((_HEADS[kind], _HEADS_TIGHT[kind]),
                       (_HEADS_ACTUAL[kind], _HEADS_TIGHT_ACTUAL[kind])):
        hit = _heading_pass(lines, kind, pat, tight)
        if hit is not None:
            return hit
    return None


def _heading_pass(lines, kind, pat, tight):
    others = (_HEADS["stage" if kind == "foam" else "foam"],
              _HEADS_ACTUAL["stage" if kind == "foam" else "foam"])
    other_tights = (_HEADS_TIGHT["stage" if kind == "foam" else "foam"],
                    _HEADS_TIGHT_ACTUAL["stage" if kind == "foam" else "foam"])
    for cy, cells in lines:
        joined = _clean(" ".join(s["t"] for s in cells))
        if _TOC.search(joined):
            continue
        if kind == "stage" and (any(o.match(joined) for o in others)
                                or any(o.match(_squash(joined))
                                       for o in other_tights)):
            continue
        # the BOTTOM of the heading line, not the line key: v4.3.1 sets
        # "ACTUAL STAGE SUMMARY" in small caps, which the PDF emits as the runs
        # 'A' 'CTUAL' 'S' 'TAGE' 'S' 'UMMARY' at two different font sizes and
        # so two different span centres (81.9 and 83.1 on 00001 p101). _lines
        # groups them into one line on the smaller key, and everything below
        # `head_cy + 1` is taken to be table — so the small-caps runs fell
        # through into the column header and named two columns
        # "CTUAL TAGE Stage Description Number" and "UMMARY Start Time".
        low = max(s["cy"] for s in cells)
        m = pat.match(joined) or tight.match(_squash(joined))
        if m:
            return low, (int(m.group(1)) if m.group(1) else None)
        # section number alone in the left cell, title in the next cell
        if _SECTION_ONLY.match(cells[0]["t"]) and len(cells) > 1:
            rest = _clean(" ".join(s["t"] for s in cells[1:]))
            if kind == "stage" and any(o.match(rest) for o in others):
                continue
            if pat.match(rest):
                return low, int(_SECTION_ONLY.match(cells[0]["t"]).group(1))
    return None


def parse_page(page, kind="stage", smap=None):
    """One Stage Summary (or Foam Stage Summary) page ->
    {interval, interval_src, depth, uwi, section, columns, rows, totals}
    with one row per pump stage, or None.

    `columns` are canonical `(name, unit)` pairs; `rows` are lists of strings
    aligned to them. `totals` is the report's own printed total line, kept so a
    caller (or the test harness) can check the parse against the page.

    `smap` is `_section_map(doc)`, needed only by the v4.3.1 pages that name no
    interval of their own; without it those pages parse but report no interval.
    """
    if "(IFS v" not in page.get_text():
        return None
    spans = _spans(page)
    head = _heading(spans, kind)
    if head is None:
        return None
    head_cy, section = head
    body = _table_body(spans, head_cy)
    if body is None:
        return None
    cols, row_lines, tot_line = body

    raw_rows = [_assign(cells, cols) for cells in row_lines]
    if not raw_rows:
        return None

    # the leading stage-number cell is either "7" or "1 - 7"; split the
    # interval prefix off so both builds expose the same Stage Number
    prefixes = []
    for r in raw_rows:
        m = _STAGENO.match((r[0] or "").strip())
        if m:
            prefixes.append(int(m.group(1)))
            r[0] = m.group(2)
        else:
            prefixes.append(None)

    text = page.get_text()
    interval, label, depth, src = _interval_for_page(
        text, section, prefixes, smap or {})
    named = [_std(c["name"], c["unit"]) for c in cols]
    totals = {}
    if tot_line:
        nums = [s["t"].replace(",", "") for s in
                sorted(tot_line, key=lambda s: s["x0"]) if _NUM.match(s["t"])]
        summable = [(n, u) for n, u in named if n in SUMMABLE]
        if nums and len(nums) == len(summable):
            for (n, u), v in zip(summable, nums):
                totals[_label(n, u)] = v
        else:                                # fall back to reading positions
            for (n, u), v in zip(named, _assign(tot_line, cols)):
                if v and _NUM.match(v):
                    totals[_label(n, u)] = v
    # Cross-check every summable column against the page's own printed Total.
    # This is the report grading the parse, and it is worth surfacing rather
    # than hiding: 00003 p79 prints its last two rows in a column order it
    # abandoned earlier on the same page, and this is what catches it.
    warnings = []
    for i, (n, u) in enumerate(named):
        key = _label(n, u)
        if key not in totals:
            continue
        try:
            got = sum(float(r[i]) for r in raw_rows if r[i])
            want = float(totals[key])
        except (TypeError, ValueError):
            continue
        if abs(got - want) > max(0.05, abs(want) * 0.001):
            warnings.append(f"{key}: rows sum to {got:.3f}, "
                            f"the page prints {want:.3f}")
    return {"interval": interval, "interval_label": label, "interval_src": src,
            "depth": depth, "uwi": _page_uwi(text),
            "section": section, "columns": named, "rows": raw_rows,
            "totals": totals, "warnings": warnings}


# --------------------------------------------------------- document-level API

def _page_tables(doc, kind, smap):
    out = []
    for p in range(doc.page_count):
        page = doc[p]
        if not is_stage_summary_page(page, kind):
            continue
        try:
            tab = parse_page(page, kind, smap)
        except Exception:
            tab = None
        if tab and tab["rows"]:
            tab["page"] = p + 1
            out.append(tab)
    return out


def parse_stage_summary(doc):
    """-> {columns, rows, totals, pages} — every interval's Stage Summary in
    the document stitched into ONE grid, one row per pump stage.

    The v4.4.0 "Foam Stage Summary" is not a separate table: it is the same
    pump stages with the N₂/foam channels the base grid has no room for, so it
    is joined onto the base rows on (interval, stage number) and its columns
    are appended. A v4.4.0 report that had them split would make a consumer
    join two tables to answer one question about one stage.
    """
    smap = _section_map(doc)
    base = _page_tables(doc, "stage", smap)
    if not base:
        return None
    foam = _page_tables(doc, "foam", smap)
    # An interval whose stage table runs onto a second page repeats no header,
    # so that page carries no UWI. Carry the previous page's forward — the UWI
    # has to travel with the row (00123 files 38 intervals of 100/12-15 under a
    # licence named for 100/15-17, so the filename cannot supply it).
    for group in (base, foam):               # each already in page order
        carry = ""
        for tab in group:
            if tab["uwi"]:
                carry = tab["uwi"]
            elif carry:
                tab["uwi"] = carry

    # depth belongs to the interval, not the page it happens to be printed on
    depths = _interval_depths(doc)
    for tab in base + foam:
        if not tab["depth"]:
            tab["depth"] = depths.get(tab["interval_label"], "")

    # column order = first appearance across pages, with Interval/UWI in front
    order, seen = [], set()
    for tab in base + foam:
        for n, u in tab["columns"]:
            if n in ("Stage Number", "Description", "Start Time"):
                continue
            if n not in seen:
                seen.add(n)
                order.append((n, u))
    # `Interval` is the numeric join key (it is what halliburton_ifs puts in
    # meta.stage). `Interval Label` is the report's own wording for the same
    # thing and is what separates two Stage Summaries that legitimately share
    # an interval number — 00002 prints "5.3 Stage Summary" under "5.0
    # INTERVAL 4" and then "6.2 Stage Summary" under "6.0 INTERVAL 4 FLUSH",
    # each restarting its stage numbers at 1, and 00001 files a re-frac as
    # "Interval 4A". Section numbers would not do this job: they differ
    # between builds, which is the whole reason nothing here anchors on them.
    lead = [("Interval", ""), ("Interval Label", ""), ("Interval Depth", "m"),
            ("Stage Number", ""), ("Description", ""), ("Start Time", "")]
    columns = [_label(n, u) for n, u in lead + order]

    foam_by_key = {}
    for tab in foam:
        for r in tab["rows"]:
            key = (tab["interval_label"], (r[0] or "").strip())
            foam_by_key[key] = dict(zip([n for n, _u in tab["columns"]], r))

    # the UWI travels with the ROW, not the document: a single IFS PDF can
    # bundle more than one well (00123 carries 102/15-17 and 100/12-15)
    rows, totals = [], {}
    for tab in base:
        for r in tab["rows"]:
            d = dict(zip([n for n, _u in tab["columns"]], r))
            d.update(foam_by_key.get((tab["interval_label"],
                                      (r[0] or "").strip()), {}))
            rows.append([tab["uwi"],
                         _iv_key(tab["interval"], tab["interval_label"]),
                         tab["interval_label"], tab["depth"]]
                        + [d.get(n) or "" for n, _u in lead[3:] + order])
        for k, v in tab["totals"].items():
            try:
                totals[k] = round(float(totals.get(k, 0)) + float(v), 3)
            except (TypeError, ValueError):
                pass
    if not rows:
        return None
    warnings = [f"p{t['page']}: {w}" for t in base + foam for w in t["warnings"]]
    all_columns = ["UWI"] + columns
    # CNRL's v4.3.1 header prints no UWI at all, and several builds (v4.6.3,
    # v7.0.0) print "1.0 INTERVAL 1:" with no depth after the colon — in the
    # v7.0.0 report measured here the depth is absent from the table of
    # contents too, so it is not in the document at all. Emitting either as an
    # all-empty column ships a field that is never populated, and an empty UWI
    # column additionally defeats pipeline._normalise_tables, which fills one in
    # from the COMP filename only when the table has none. Drop any column the
    # document never fills, and keep every column it does.
    keep = [i for i, _c in enumerate(all_columns)
            if any((r[i] or "").strip() for r in rows)]
    out = {"columns": [all_columns[i] for i in keep],
           "rows": [[r[i] for i in keep] for r in rows],
           "totals": {k: str(v) for k, v in totals.items()},
           "warnings": warnings, "pages": [t["page"] for t in base + foam]}
    return out


# ------------------------------------------------- v4.6.3 whole-well roll-up

def is_treatment_summary_page(page):
    t = page.get_text()
    return ("(IFS v" in t and re.search(r"^TREATMENT SUMMARY\s*$", t, re.M)
            is not None and "Table of Contents" not in t)


# An interval identifier: "7", or a name like "C Well-12" / "NCS 3". The
# numeric-width test below is what actually keeps non-rows out (the page-number
# footer is a bare integer on a line of its own), so this only has to be loose
# enough to admit a label and tight enough to exclude a units row ("m", "MPa").
_TSUM_LEAD = re.compile(r"\d{1,3}|[A-Za-z][A-Za-z0-9 .\-/]{0,23}")


def _is_tsum_row(cells):
    """A Treatment Summary data line: an interval identifier on the left and at
    least five numeric (or "x" = not-measured) cells across."""
    if not cells:
        return False
    if not _TSUM_LEAD.fullmatch(cells[0]["t"]):
        return False
    return sum(1 for s in cells
               if _NUM.match(s["t"]) or s["t"].lower() == "x") >= 5


def parse_treatment_summary(doc):
    """-> {columns, rows, uwi} for the v4.6.3 whole-well "TREATMENT SUMMARY",
    one row per INTERVAL, or None.

    This is deliberately NOT folded into parse_stage_summary. It is a different
    grain (interval, not pump stage), a different page geometry (portrait, not
    the landscape stage grid), it is printed once for the whole well rather than
    once per interval, several of its columns exist nowhere in the Stage
    Summary (Breakdown Pressure, Sleeve Shift Pressure, Surface ISIP, Ball Seat
    Volume, gel-vs-slickwater split), and in the two v4.6.3 files here it can
    even carry a DIFFERENT UWI from the stage pages in the same PDF. Merging
    the two would either duplicate every interval-level value across that
    interval's pump stages or throw the pump-stage grain away; it joins to the
    stage rows on `Interval`, exactly like the charts do.

    The interval identifier is NOT always a number and the table is NOT always
    one page: Shell's v7.0.0 names its 99 intervals "C Well-1" .. "C Well-99"
    and runs them over four pages, only the first of which repeats the heading.
    Requiring a bare-integer first cell rejected every row of it and the table
    came back empty; requiring the heading stopped the read after page one.
    """
    for p in range(doc.page_count):
        page = doc[p]
        if not is_treatment_summary_page(page):
            continue
        spans = _spans(page)
        lines = _lines(spans)
        head_i = next((i for i, (_cy, c) in enumerate(lines)
                       if _squash(" ".join(s["t"] for s in c)).upper()
                       == "TREATMENTSUMMARY"), None)
        if head_i is None:
            continue
        # data rows start at the first line headed by an interval identifier
        # and carrying several numeric (or "x" = not-measured) cells
        first_i = next((i for i, (_cy, c) in enumerate(lines[head_i + 1:],
                                                       head_i + 1)
                        if _is_tsum_row(c)), None)
        if first_i is None:
            continue
        data = [(cy, c) for cy, c in lines[first_i:] if _is_tsum_row(c)]
        # continuation pages carry the rows and nothing else — no heading, no
        # column titles — so they are taken while they keep yielding rows and
        # print no summary heading of their own. Guarded on GEOMETRY as well:
        # "looks like a data row" is not enough to identify a continuation.
        # 00123 p23 is a WELL INFORMATION page whose Pipe Information rows
        # ("Upper Casing  0  2524.19  114.30  97.18  22.47  P-110EC") satisfy
        # the row test on their own merits, and taking them appended two junk
        # rows with an empty interval to a 38-interval table. A real
        # continuation row starts at the same x as the rows above it and is
        # the same number of cells wide.
        lead_x = sorted(c[0]["x0"] for _cy, c in data)[len(data) // 2]
        width = sorted(len(c) for _cy, c in data)[len(data) // 2]
        pages = [p + 1]
        for q in range(p + 1, doc.page_count):
            nxt = doc[q]
            text = nxt.get_text()
            if "(IFS v" not in text or _page_kind(text) is not None:
                break
            more = [(cy, c) for cy, c in _lines(_spans(nxt))
                    if _is_tsum_row(c) and abs(c[0]["x0"] - lead_x) <= 5
                    and abs(len(c) - width) <= 1]
            if not more:
                break
            data += more
            pages.append(q + 1)
        # Columns come from the DATA here, not the header. This page is
        # portrait and 14 columns wide, so the stacked headings ("Breakdown" /
        # "Pressure" over "Avg" / "Treating" / "Pressure") do overlap their
        # neighbours in x and header-driven grouping fuses them; 39 interval
        # rows of consistently placed cells do not.
        cols = _columns_from_data([s for _cy, c in data for s in c],
                                  [s for _cy, c in lines[head_i + 1:first_i]
                                   for s in c])
        if len(cols) < 5:
            continue
        rows = [_assign(c, cols) for _cy, c in data]
        if not rows:
            continue
        named = [_std(c["name"], c["unit"]) for c in cols]
        names = [_label(n, u) for n, u in named]
        if names and names[0].lower().startswith("interval"):
            names[0] = "Interval"
        uwi = _page_uwi(page.get_text())
        body = [[c if c is not None else "" for c in r] for r in rows]
        if not uwi:                          # let the pipeline fill it in
            return {"columns": names, "rows": body, "uwi": "",
                    "page": p + 1, "pages": pages}
        return {"columns": ["UWI"] + names,
                "rows": [[uwi] + r for r in body],
                "uwi": uwi, "page": p + 1, "pages": pages}
    return None
