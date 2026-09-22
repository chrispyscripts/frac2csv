"""The BC OGC "Frac Fluid and Additive Treatment Report" — the Data Capture
sheet, an Excel printout bound into the back of a Liberty filing.

One page, one table, one row per stage, and every number the regulator asks
for: the clock, the interval, the pressures, the rates, the fluid split, the
proppant placed/pumped/designed, thirteen named chemical additives and the
OGC's own tracer/acid/energizer questions. 00915 p103 (#706) is 1855 words
of live text and came back "no table data", which is the one case in that
batch where the client was right and we were wrong — the other three really
are pictures of tables.

It read as nothing for two reasons, and both are about geometry:

  * THE PAGE IS TURNED — sometimes. 00915 p103 is /Rotate 90, every line
    drawn with dir (0, -1), and MuPDF hands span bboxes back in UNROTATED
    space, so a spreadsheet COLUMN looks like a page row: group the words
    by y and you get ['BY', 'Tracer', 'N', 'N', 'N', ...] — a column letter,
    its header, then one value per stage. get_text("text") linearises it
    differently again (29 row numbers, then 70 column letters, then the
    body) and agrees with neither, which is why reading the flat text says
    there is nothing there.

    SOMETIMES, and that is the point: of the sixteen filings carrying this
    sheet in a 1202-file sweep of both corpora, 00915 p103, 01079 p95 and
    01553 p33 are turned and 00919 p108, 01011 p147 and 00999 p106 are
    upright. So nothing here assumes an orientation — every coordinate is
    pushed through page.rotation_matrix, the same way canyon_tables._spans
    does it for its turned 2014 sheets, and on an upright page that matrix
    is the identity.

  * IT IS AN EXCEL PRINTOUT, and prints its own furniture. Row numbers 1..29
    run down the left margin and column letters A..CC across the top, and
    they are not data. They are, however, the best column model in the
    corpus: Excel centres a column's letter on the column, so the letter
    strip IS the set of anchors, exact, including which columns the sheet
    has hidden (Q..S, AJ/AK, AO..AT are absent from 00915 and so is their
    data). A column the sheet prints values in but gives no heading is named
    for its letter rather than dropped — 01011 has two, and one of them is
    the well name.

Cells are centred on those anchors — everything on 00915 lands within 3pt of
one — so a cell goes to its nearest letter. Two shapes need care and both are
handled in _cells:

  * a MERGED cell ("Perforation Intervals (m)", and the "5368.17 - 5368.07"
    under it) is centred on the merge, not on a column, and lands 2.6pt off
    anchor O. Nearest-anchor gets it right; nothing needs splitting.
  * a FUSED span. Two neighbouring cells whose ink touches come back from
    MuPDF as ONE span: 00915's header prints "CO-WC100 ACI-90WL" as a single
    span across anchors BB and BC, and taken whole it names BB twice and BC
    not at all. Split only when every piece lands within 2pt of its own
    anchor, which "Perforation Intervals (m)" never does.

  - detect(doc) / detect_page(page): is this the Data Capture sheet?
  - find_summary_pages(doc): the sheet listed for viewing.
  - parse_document(doc): the stage grid as {columns, rows} — one row per
    stage, in sheet column order.
  - parse_job_summary(doc): the label/value block above the grid (service
    company, well, licence, job totals) as a one-row table.

Checked against the sheets' own arithmetic on all sixteen, 374 stage rows:
Designed Sand minus Pumped Total comes to the printed Difference on 372 of
372 rows that print one, and End minus Start comes to the printed Job
Duration on 371 of 374. Those need six and five columns respectively to be
filed correctly, so a shift of one anywhere breaks them.

The three that miss are the sheets contradicting themselves, not a misread,
and they say so by the size of the miss: 01388 stage 6 and 01550 stage 11 are
out by exactly 1440 minutes and 00461 stage 7 by exactly 5760, whole days
every time. 00461 p75 prints "14-Jan-23 21:26" to "18-Jan-23 22:26" against a
Job Duration of 60 while every other row on the sheet starts and ends the
same day. A digit read wrong would not land on a multiple of a day.
"""
import re

import fitz

# ------------------------------------------------------------------ the stamp
#
# What makes detection specific. This workbook stamps its own version in the
# top-right corner of every sheet it prints, and carries the OGC's version
# gate as red text across the header block. Either one, on its own, is a
# string no other layout in the corpus prints — but neither is asked to
# carry detection alone (see detect_page): a bare "Treatment Report" nearly
# anywhere is exactly the substring match that made canyon_tables claim 44
# Peloton section bars it had no business claiming (#705/#710).
_STAMP = re.compile(r"Data[\s\xa0]*Capture[\s\xa0]*version[\s\xa0]*[\d.]+",
                    re.I)
_GATE = re.compile(r"FOR USE WITH TREATMENT REPORT VERSION\s*[\d.]+", re.I)

# Header labels, as the sheet prints them on their own line. Eight of these
# on one page, together with the stamp and the printed column letters, is
# the evidence. They are deliberately multi-word: "Stage", "Frac" and "Total"
# appear on half the corpus.
_HEADERS = [
    "Stage Description", "Job Duration", "Hole Vol", "Interval Bottom",
    "Interval Top", "Bridge Plug", "Perforation Intervals", "Avg. Press",
    "Pre-Job", "Avg. Rate", "Max. Rate", "Fluid Type", "Total Clean",
    "Base Fluid", "Acid Type", "Total Pump Time",
]
_MIN_HEADERS = 8

# The job block above the grid: label printed in one cell, value in the next
# one to its right on the same line. Only these, and in this order — the
# block also holds the workbook's buttons ("Pull Data From TR", "CREATE
# XML"), the red version gate, and a "Brand Name" whose value is stacked
# BELOW it over three rows rather than beside it, none of which pair.
_JOB_FIELDS = [
    "Service Company", "Company", "Job Type", "Well Name", "Well License",
    "Formation", "Total Volume", "Total Proppant", "Max Pressure",
    "Total Pump Time", "Max Rate", "Average Rate",
]

# The sheet, as the OGC's form names it, and the two tables it yields. The
# tables say what they are as well as what printed them, so table_kind can
# file both under "summary" — a title that is only the form's name classifies
# as "other" and the Lab has nowhere to put it.
TITLE = "Frac Fluid and Additive Treatment Report"
TABLE_TITLE = TITLE + " (per-stage summary)"
JOB_TITLE = TITLE + " (job totals)"

_LETTER = re.compile(r"^[A-Z]{1,2}$")
_INT = re.compile(r"^\d{1,3}$")
_MIN_LETTERS = 20           # A..T on the narrowest sheet this could print


def _col_index(letter):
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27. Excel's own column numbering."""
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - 64)
    return n


# ------------------------------------------------------------------- geometry
def _spans(page):
    """[{t, x0, x1, cx, cy}] for every span, in DISPLAY coordinates.

    The sheet is /Rotate 90 and MuPDF hands back unrotated bboxes, so the
    page's own rotation matrix is what stands it up — without it a stage is
    a page column and the parse finds nothing. Same treatment canyon_tables
    gives its turned 2014 sheets."""
    m = page.rotation_matrix
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                t = sp["text"].replace("\xa0", " ").strip()
                if not t:
                    continue
                r = fitz.Rect(sp["bbox"]) * m
                r.normalize()
                out.append({"t": t, "x0": r.x0, "x1": r.x1,
                            "cx": (r.x0 + r.x1) / 2,
                            "cy": (r.y0 + r.y1) / 2})
    return out


def _words(page):
    """[(cx, cy, x0, x1, text)] — whitespace-split, with real boxes.

    Only used to take a fused span apart; a span's own bbox cannot say where
    inside it the words sit."""
    m = page.rotation_matrix
    out = []
    for x0, y0, x1, y1, t, _b, _l, _n in page.get_text("words"):
        t = t.replace("\xa0", " ").strip()
        if not t:
            continue
        r = fitz.Rect(x0, y0, x1, y1) * m
        r.normalize()
        out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, r.x0, r.x1, t))
    return out


def _lines(spans, tol=2.0):
    """spans -> [(cy, [span, ...] left to right)], top to bottom."""
    rows = {}
    for s in sorted(spans, key=lambda s: (s["cy"], s["cx"])):
        key = next((k for k in rows if abs(k - s["cy"]) < tol), s["cy"])
        rows.setdefault(key, []).append(s)
    return [(y, sorted(v, key=lambda s: s["cx"]))
            for y, v in sorted(rows.items())]


def _letter_strip(spans):
    """(cy, [(letter, cx)]) for the printed column-letter row, or (0.0, []).

    The line that is nothing but single/double capitals running in Excel's
    own column order. Being a RUN matters: three stray capitals in a chart
    legend are not a column strip. Its cy is the sheet's top edge — nothing
    above the letters belongs to the grid."""
    best, at = [], 0.0
    for y, line in _lines(spans):
        letters = [(s["t"], s["cx"]) for s in line if _LETTER.match(s["t"])]
        if len(letters) < _MIN_LETTERS or len(letters) < len(line) - 1:
            continue
        idx = [_col_index(t) for t, _ in letters]
        if any(b <= a for a, b in zip(idx, idx[1:])):
            continue
        if len(letters) > len(best):
            best, at = letters, max(s["cy"] for s in line)
    return at, best


def _row_number_band(spans, first_cx):
    """(x0, x1) of the printed row-number margin, or None.

    Excel prints 1, 2, 3 ... down the left of column A, and on 00915 they
    sit 13.4pt left of anchor A against a 28pt A-to-B pitch — near enough
    that nearest-anchor would file all 24 of them as stage numbers. They are
    found as what they are instead: a stack of small integers, left of the
    first column, sharing an x."""
    cand = [s for s in spans if s["cx"] < first_cx - 2 and _INT.match(s["t"])]
    if len(cand) < 5:
        return None
    cand.sort(key=lambda s: s["cx"])
    best = []
    for i, s in enumerate(cand):
        run = [c for c in cand[i:] if c["cx"] - s["cx"] < 4]
        if len(run) > len(best):
            best = run
    if len(best) < 5:
        return None
    return min(c["x0"] for c in best) - 1, max(c["x1"] for c in best) + 1


def _rules(page):
    """Display-y of every horizontal cell border the sheet draws.

    Excel draws its borders as hairline rectangles, not lines. They are used
    for one thing only — saying where the header ROW starts and stops, which
    is the one thing clustering the text cannot do: the header's wrapped
    lines sit 1.4pt apart and the note above it 4.4pt, and no rule about
    gaps is worth trusting on that margin when the sheet prints the answer.
    """
    m = page.rotation_matrix
    ys = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] != "re":
                continue
            r = fitz.Rect(it[1]) * m
            r.normalize()
            if r.y1 - r.y0 < 1.5 and r.x1 - r.x0 > 3:
                ys.append((r.y0 + r.y1) / 2)
    ys.sort()
    out = []
    for y in ys:
        if not out or y - out[-1] > 1.0:
            out.append(y)
    return out


def _heading_cy(lines, anchors):
    """the y of the line that names the first column "Stage", or None.

    The one label on the sheet whose position says what it is: "Stage"
    centred on the first printed column. Above it is the job block, below it
    the stages — and both of them print a "Well Name"."""
    for cy, line in lines:
        for s in line:
            if s["t"] == "Stage" and abs(s["cx"] - anchors[0][1]) < 3:
                return cy
    return None


def _band(rules, cy):
    """(top, bottom) of the ruled band holding cy, or None."""
    for a, b in zip(rules, rules[1:]):
        if a <= cy <= b:
            return a, b
    return None


def _median(vals):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else 0.0


def _gap_band(lines, head_cy, pitch):
    """(top, bottom) of the heading, when the sheet draws no cell borders.

    The heading's wrapped lines sit a fraction of a row apart and the rows
    around it a whole row away: measured on 00915, 2.8pt between the
    heading's own lines, 4.4pt up to the note above it and 7.4pt down to the
    first stage, against a 9.1pt row pitch. So the band is grown outwards
    from the "Stage" line for as long as the next line is nearer than a
    third of a row. Only reached on a sheet printed without borders; every
    copy in the corpus draws them."""
    gap = 0.35 * pitch if pitch else 3.0
    ys = [cy for cy, _line in lines]
    top = bottom = head_cy
    for cy in reversed([y for y in ys if y < head_cy]):
        if top - cy > gap:
            break
        top = cy
    for cy in [y for y in ys if y > head_cy]:
        if cy - bottom > gap:
            break
        bottom = cy
    return top - 0.1, bottom + 0.1


# ------------------------------------------------------------------ the cells
def _nearest(anchors, cx):
    """index of the anchor nearest cx."""
    return min(range(len(anchors)), key=lambda i: abs(anchors[i][1] - cx))


def _split_fused(span, words, anchors, tol=2.0):
    """A span covering two or more anchors, taken apart — or [span].

    Neighbouring cells whose ink touches come back as one span: 00915's
    header prints "CO-WC100 ACI-90WL" across anchors BB and BC. A split is
    only accepted when EVERY piece is centred within tol of its own anchor,
    which is what a printed cell is and what a merged cell is not — the
    three words of "Perforation Intervals (m)" miss by 3.7, 2.0 and 8.2 and
    it stays whole."""
    inside = [w for w in words
              if abs(w[1] - span["cy"]) < 2.0
              and w[2] >= span["x0"] - 0.5 and w[3] <= span["x1"] + 0.5]
    if len(inside) < 2:
        return [span]
    inside.sort(key=lambda w: w[2])
    if "".join(w[4] for w in inside) != span["t"].replace(" ", ""):
        return [span]
    pieces, used, i = [], set(), 0
    while i < len(inside):
        for j in range(i + 1, len(inside) + 1):
            grp = inside[i:j]
            cx = (grp[0][2] + grp[-1][3]) / 2
            k = _nearest(anchors, cx)
            if abs(anchors[k][1] - cx) <= tol and k not in used:
                pieces.append({"t": " ".join(w[4] for w in grp),
                               "x0": grp[0][2], "x1": grp[-1][3],
                               "cx": cx, "cy": span["cy"]})
                used.add(k)
                i = j
                break
        else:
            return [span]
    return pieces if len(pieces) > 1 else [span]


def _cells(spans, words, anchors):
    """spans -> {anchor index: [span, ...]}, fused spans taken apart first."""
    out = {}
    for s in spans:
        covered = sum(1 for _l, cx in anchors if s["x0"] <= cx <= s["x1"])
        parts = _split_fused(s, words, anchors) if covered > 1 else [s]
        for p in parts:
            out.setdefault(_nearest(anchors, p["cx"]), []).append(p)
    return out


def _text(parts):
    """the cells filed under one anchor, read top-to-bottom then left-to-
    right — how a wrapped header cell is meant to be read.

    Excel wraps a header inside its cell and the break is not always a word
    break: 00915 prints SCI-B702 as "SCI-" / "B702" and WORK (MWt*Hr) as
    "WORK (MWt" / "*Hr)". A line ending in a hyphen, or one starting with
    punctuation, is rejoined with nothing between. A break mid-WORD cannot
    be told from a break at a space — "AQUCAR GA 25" comes back as "AQUCA R
    GA 25" and is left that way rather than guessed at."""
    parts = sorted(parts, key=lambda s: (round(s["cy"], 1), s["cx"]))
    out = ""
    for p in parts:
        t = p["t"]
        if out and not (out.endswith("-") or t[0] in "*).,"):
            out += " "
        out += t
    return re.sub(r"\s+", " ", out).strip()


# ------------------------------------------------------------------ detection
def detect_page(page):
    """True for a Data Capture sheet, and it takes all three to say so.

    The stamp (or the OGC's version gate) says which workbook printed the
    page; eight of the header labels say the page is the treatment grid and
    not, say, this workbook's instructions tab; the column-letter strip says
    the sheet really did print with row and column headings, which is what
    the whole parse is built on. #705 is what one substring on its own is
    worth."""
    text = page.get_text() or ""
    if not (_STAMP.search(text) or _GATE.search(text)):
        return False
    if sum(1 for h in _HEADERS if h in text) < _MIN_HEADERS:
        return False
    return bool(_letter_strip(_spans(page))[1])


_FOUND = "_ogc_datacapture_pages"


def _pages(doc):
    """[0-based page index] of every Data Capture sheet, found once.

    Whole document, not a leading window: 00915 buries its sheet on page 103
    of 151 behind 100 scanned pages, and every other table module in here
    that guessed at a window (#330) had to be widened later.

    The answer is kept on the document because finding it is not cheap and
    the pipeline asks four times — gate, page list, grid, job header. A page
    of scanned paper costs 1.2s to prove empty (MuPDF decodes the image to
    run the text device) and 00915 has a hundred of them: 27s a pass, so
    four passes would cost the run a minute and a half for one table."""
    hit = getattr(doc, _FOUND, None)
    if hit is not None:
        return hit
    hit = [p for p in range(doc.page_count) if detect_page(doc[p])]
    try:
        setattr(doc, _FOUND, hit)
    except Exception:                   # pragma: no cover - not a fitz doc
        pass
    return hit


def detect(doc):
    """True when the document carries a Data Capture sheet."""
    return bool(_pages(doc))


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — the sheet listed for viewing."""
    pages = _pages(doc)
    if not pages:
        return []
    return [{"kind": "datacapture", "title": TITLE,
             "pages": [p + 1 for p in pages]}]


# --------------------------------------------------------------------- parse
def parse_page(page):
    """The stage grid on one sheet as {columns, rows}, or None."""
    spans = _spans(page)
    top, anchors = _letter_strip(spans)
    if not anchors:
        return None
    # Excel's own row and column headings, and neither is data. The row
    # numbers matter most: on 00915 they sit 13.4pt left of anchor A against
    # a 28pt A-to-B pitch, and row 6's "6" is INSIDE the heading's ruled
    # band, so keeping them names the first column "Stage 6".
    margin = _row_number_band(spans, anchors[0][1])

    def _furniture(cx, cy):
        return cy <= top or (margin is not None
                             and margin[0] <= cx <= margin[1])

    body = [s for s in spans if not _furniture(s["cx"], s["cy"])]
    words = [w for w in _words(page) if not _furniture(w[0], w[1])]

    head_cy = _heading_cy(_lines(body), anchors)
    if head_cy is None:
        return None

    # A stage row is a line below the heading whose FIRST column holds a
    # stage number, and the stage numbers run UP the sheet. That ascent is
    # the guard, rather than a minimum cell count: it is the sheet's own
    # structure and it costs nothing on a page that is not one.
    data = []
    for cy, line in _lines(body):
        if cy <= head_cy:
            continue
        cells = _cells(line, words, anchors)
        stage = _text(cells.get(0, []))
        if not _INT.match(stage) or len(cells) < 3:
            continue
        if data and int(stage) <= int(_text(data[-1][1].get(0, []))):
            continue
        data.append((cy, cells))
    if len(data) < 2:
        return None

    # The heading is ONE spreadsheet row and its cells wrap inside it —
    # "Bridge Plug" / "Set Depth" / "(m)" are three lines of one cell. The
    # sheet's own cell borders say where that row starts and stops, which is
    # the one thing clustering the text cannot: 1.4pt between the heading's
    # wrapped lines, 4.4pt up to the note in the row above.
    ys = [cy for cy, _c in data]
    band = _band(_rules(page), head_cy) or _gap_band(
        _lines(body), head_cy, _median(b - a for a, b in zip(ys, ys[1:])))

    names = _cells([s for s in body if band[0] <= s["cy"] <= band[1]],
                   words, anchors)
    columns, keep = [], []
    for i, (letter, _cx) in enumerate(anchors):
        name = _text(names.get(i, []))
        # A column with neither a heading nor a value is a spacer. One with
        # values and no heading is data and is named for its letter: 01011
        # prints the well name under a blank heading.
        if not name and not any(i in c for _cy, c in data):
            continue
        keep.append(i)
        columns.append(name or "Column " + letter)

    rows = [[_text(c.get(i, [])) for i in keep] for _cy, c in data]
    return {"columns": columns, "rows": rows}


def parse_document(doc):
    """Every Data Capture sheet in the filing, stacked into one grid.

    Every filing in the corpus prints exactly one, but the sheets differ
    between filings — 60 columns on 01553, 68 on 01011 — so a second one is
    stacked BY COLUMN NAME under the union of both, rather than positionally
    or not at all."""
    out = None
    for p in _pages(doc):
        tab = parse_page(doc[p])
        if not tab:
            continue
        if out is None:
            out = tab
            continue
        for name in tab["columns"]:
            if name not in out["columns"]:
                out["columns"].append(name)
                for row in out["rows"]:
                    row.append("")
        here = dict(zip(tab["columns"], range(len(tab["columns"]))))
        for row in tab["rows"]:
            out["rows"].append([row[here[n]] if n in here else ""
                                for n in out["columns"]])
    return out


def parse_job_summary(doc):
    """The label/value block above the grid as a one-row {columns, rows}.

    Read only ABOVE the grid's heading, because the grid has a Well Name
    column of its own and the job block is what this is for."""
    for p in _pages(doc):
        spans = _spans(doc[p])
        _top, anchors = _letter_strip(spans)
        if not anchors:
            continue
        lines = _lines(spans)
        head_cy = _heading_cy(lines, anchors)
        found = {}
        for cy, line in lines:
            if head_cy is not None and cy >= head_cy:
                break
            for a, b in zip(line, line[1:]):
                if a["t"] in _JOB_FIELDS and a["t"] not in found:
                    found[a["t"]] = b["t"]
        cols = [f for f in _JOB_FIELDS if f in found]
        if cols:
            return {"columns": cols, "rows": [[found[f] for f in cols]]}
    return None
