"""Schlumberger summary sheets — the printed tables, read positionally.

SLB files carry their per-stage numbers on summary sheets that `slb.py` never
read: it does charts only. Two layouts, matching the client's own two codes:

  * SCHLUM-2 — "Zone N Summary". 48 of his 199 files.
  * SCHLUM-1 — "Interval N Summary". 151 files, and the richer sheet: it adds
    ISIPs, frac gradient, acid pressure drop, fuel and water figures, and
    splits its rate block into CLEAN and SLURRY columns.

Both are real text on every page measured — 543 Interval and 400 Zone sheets
in the sample, all with a text layer — so none of this needs OCR.

THE ONE THING THAT MATTERS: the text stream is in DRAWING order, not reading
order. On a Zone sheet the values "7/29/2018 ... 08:49:45 ... 10:33:44" are
emitted before the labels "END DATE / START DATE" they belong to, so anything
that walks the stream pairs them wrongly and looks plausible doing it.
slb._zone_sheet_times already says this about the four timestamps. Everything
here is therefore keyed on (x, y): a label takes the value to ITS RIGHT, in
the value band belonging to its own column of the form.

The form is two columns side by side. Measured on the sample, labels sit at
x~60-160 and x~290-460 and their values at x~200-270 and x~460-540; a row is
a set of spans sharing a y to within a few points. Section headers matter
because both halves reuse the same words — PRESSURES (MPa) and SLURRY RATES
(m3/min) each have an AVERAGE, a MAXIMUM and a MINIMUM — so a bare label is
qualified by whichever section heads its own column.
"""
import re

_NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")

# A row is spans sharing a y within this many points. The sheets set their
# rows ~11pt apart, so 3 separates neighbours while still gathering a row
# whose cells are typeset a fraction of a point off each other.
ROW_TOL = 3.0

# Where a column's values live, relative to its label. Two bands because the
# sheet is two forms side by side; a label at x < SPLIT takes a value in the
# left band, one at x >= SPLIT takes the right.
SPLIT = 280.0
LEFT_VALUES = (190.0, 285.0)
RIGHT_VALUES = (455.0, 560.0)

ZONE_TITLE = re.compile(r"\bZone\s+(\d{1,3})\s+Summary\b", re.I)
INTERVAL_TITLE = re.compile(r"\bInterval\s+(\d{1,3})\s+Summary\b", re.I)

# Labels whose value is simply the next cell to the right on their own row.
_PLAIN = [
    "START DATE", "END DATE", "START TIME", "END TIME",
    "FRAC PORT TOP DEPTH (m)", "ACTUAL BALL SEAT VOL (M3)",
    "DISPLACEMENT VOL (m3)", "DISP VOL (m3)", "HORSEPOWER (kW)",
    "DIESEL USED, L", "NATURAL GAS USED, DEC", "WATER SPECIFIC GRAVITY",
    "PRODUCED WATER VOL, M3", "BALL SEAT TIME", "BALL SEAT VOLUME",
    "BALL SEAT PRESSURE", "ACID PRESSURE DROP", "POST-FRAC ISIP",
    "1 MIN ISIP", "FRAC GRADIENT (kPa/m)",
]

# Labels that mean different things under different section headings, so they
# are only reported qualified by the section heading above them in their own
# column. Both sheets reuse all three.
_SECTIONS = ("PRESSURES (MPa)", "SLURRY RATES (m3/min)", "RATES (m3/min)")
_AMBIGUOUS = ("AVERAGE", "MAXIMUM", "MINIMUM", "PORT OPEN", "BREAKDOWN",
              "OPEN WELL")

_FLUID_HEAD = "FLUID"
_PROPPANT_HEAD = "PROPPANT"


def rows_of(page):
    """Page spans grouped into rows by y. -> [(y, [(x, text), ...])], each
    row's cells sorted left to right."""
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                t = s["text"].strip()
                if t:
                    spans.append((s["bbox"][1], s["bbox"][0], t))
    spans.sort()
    rows, cur, last = [], [], None
    for y, x, t in spans:
        if last is None or abs(y - last) > ROW_TOL:
            if cur:
                rows.append((last, sorted(cur)))
            cur, last = [], y
        cur.append((x, t))
    if cur:
        rows.append((last, sorted(cur)))
    return rows


def _is_num(t):
    return bool(_NUM.match(t.replace(" ", "")))


# Values that carry no digit. The sheets use these where a figure does not
# apply, and dropping them would silently turn "measured, not applicable" into
# "not read".
_WORD_VALUES = {"NA", "N/A", "TOE", "NONE", "-"}


def _looks_like_value(t):
    return bool(re.search(r"\d", t)) or t.upper() in _WORD_VALUES


def _value_for(cells, lx, labels):
    """The value belonging to the label at x=lx.

    Deliberately NOT a fixed x band. The two layouts put their values in
    different places — a Zone sheet's left column reads its value around
    x=220, an Interval sheet's around x=316 — and hardcoding either drops
    every field of the other: measured, START TIME, END TIME and DISP VOL all
    vanished from SCHLUM-1 against bands fitted to SCHLUM-2.

    So walk right from the label and take the first cell that looks like a
    value, stopping at the next label, which is where this column's own space
    ends and the neighbouring form begins.
    """
    for x, t in sorted(cells):
        if x <= lx:
            continue
        if t.rstrip(":").strip() in labels:
            return None                 # ran into the next column's label
        if _looks_like_value(t):
            return t
    return None


_ALL_LABELS = set(_PLAIN) | set(_AMBIGUOUS) | set(_SECTIONS) | {
    _FLUID_HEAD, _PROPPANT_HEAD, "COMMENTS", "STAGE", "FLUID TYPE",
    "PROP TYPE", "TOTAL"}


_SUBCOLS = ("CLEAN", "SLURRY")


def _subcolumns(rows):
    """x of the CLEAN / SLURRY sub-headers, when a sheet splits its rate block.

    SCHLUM-1 heads its rate block with two columns, so AVERAGE, MAXIMUM and
    MINIMUM each carry TWO figures — clean rate and slurry rate. Taking the
    first drops the slurry rate, which is the one the chart plots and the one
    the client's own notes are about.
    """
    for _y, cells in rows:
        texts = {t: x for x, t in cells}
        if all(s in texts for s in _SUBCOLS):
            return [(texts[s], s) for s in _SUBCOLS]
    return []


def _values_right(cells, lx, labels):
    """Every value-like cell to the right of a label, before the next label."""
    out = []
    for x, t in sorted(cells):
        if x <= lx:
            continue
        if t.rstrip(":").strip() in labels:
            break
        if _looks_like_value(t):
            out.append((x, t))
    return out


def _fields(rows):
    """The label/value pairs of the form, section-qualified where needed."""
    out, sect_left, sect_right = {}, None, None
    subs = _subcolumns(rows)
    for _y, cells in rows:
        for x, t in cells:
            if t in _SECTIONS:
                if x < SPLIT:
                    sect_left = t
                else:
                    sect_right = t
        for x, t in cells:
            key = t.rstrip(":").strip()
            if key in _PLAIN:
                val = _value_for(cells, x, _ALL_LABELS)
                if val is not None:
                    out.setdefault(key, val)
            elif key in _AMBIGUOUS:
                sec = sect_right if x >= SPLIT else sect_left
                if not sec:
                    continue
                vals = _values_right(cells, x, _ALL_LABELS)
                if not vals:
                    continue
                placed = False
                if subs and len(vals) > 1:
                    for vx, vt in vals:
                        near = min(subs, key=lambda s: abs(s[0] - vx))
                        if abs(near[0] - vx) <= 40:
                            out.setdefault(f"{sec} {key} {near[1]}", vt)
                            placed = True
                if not placed:
                    out.setdefault(f"{sec} {key}", vals[0][1])
    return out


def _column_table(rows, start):
    """A headed column table starting just after rows[start].

    The header may be spread over several printed lines — SCHLUM-1's PROPPANT
    block sets "PLACED (T) / COUNTERS" and "PLACED (T) / LOAD TICKETS" across
    three of them — so every row before the first row carrying a number is
    treated as header, and header cells are clustered by x into columns. Data
    cells then go to the nearest column.
    """
    head_cells, i = [], start + 1
    while i < len(rows):
        y, cells = rows[i]
        if any(_is_num(t) for _x, t in cells):
            break
        if len(cells) == 1 and cells[0][1] in (_FLUID_HEAD, _PROPPANT_HEAD):
            break
        head_cells.extend((y, x, t) for x, t in cells)
        i += 1
    if not head_cells:
        return None, start + 1

    data_rows = []
    j = i
    while j < len(rows):
        cells = rows[j][1]
        texts = [t for _x, t in cells]
        if any(t in (_FLUID_HEAD, _PROPPANT_HEAD) for t in texts) \
                or any(t in _SECTIONS for t in texts):
            break
        if not any(_is_num(t) for _x, t in cells):
            break
        data_rows.append(cells)
        j += 1
    if not data_rows:
        return None, i

    # Columns come from where the DATA sits, not where the headers sit. The
    # two are not aligned: on a Zone sheet the STAGE header is at x=100 while
    # its values (PAD, SLURRY, SPACER ...) centre on x=147, close enough to
    # the FLUID TYPE header at x=213 that nearest-header assignment put "PAD"
    # in the fluid-type column. Clustering the data and then labelling those
    # clusters from the headers cannot make that mistake, because every data
    # cell is measured against other data.
    xs_all = sorted(x for cells in data_rows for x, _t in cells)
    centres = []
    for x in xs_all:
        if centres and x - centres[-1][-1] <= 30:
            centres[-1].append(x)
        else:
            centres.append([x])
    xs = [sum(c) / len(c) for c in centres]

    names = [""] * len(xs)
    for _y, hx, ht in sorted(head_cells):        # by y, then x: reading order
        k = min(range(len(xs)), key=lambda m: abs(xs[m] - hx))
        names[k] = f"{names[k]} {ht}".strip() if names[k] else ht

    data = []
    for cells in data_rows:
        row = [""] * len(xs)
        for x, t in cells:
            k = min(range(len(xs)), key=lambda m: abs(xs[m] - x))
            row[k] = f"{row[k]} {t}".strip() if row[k] else t
        data.append(row)
    return {"columns": names, "rows": data}, j


def _blocks(rows):
    """The FLUID and PROPPANT column tables, when the sheet prints them."""
    out = {}
    i = 0
    while i < len(rows):
        texts = [t for _x, t in rows[i][1]]
        if len(texts) == 1 and texts[0] in (_FLUID_HEAD, _PROPPANT_HEAD):
            tab, i = _column_table(rows, i)
            if tab and tab["rows"]:
                out[texts[0]] = tab
            continue
        i += 1
    return out


def detect(page):
    """True for a sheet this module can read."""
    t = page.get_text()
    return bool(ZONE_TITLE.search(t) or INTERVAL_TITLE.search(t))


def sheet_kind(page):
    t = page.get_text()
    if ZONE_TITLE.search(t):
        return "zone"
    if INTERVAL_TITLE.search(t):
        return "interval"
    return None


def parse_page(page):
    """-> {'kind', 'number', 'fields', 'tables'} for one summary sheet."""
    text = page.get_text()
    m = ZONE_TITLE.search(text)
    kind = "zone"
    if not m:
        m = INTERVAL_TITLE.search(text)
        kind = "interval"
    if not m:
        return None
    rows = rows_of(page)
    return {"kind": kind, "number": int(m.group(1)),
            "fields": _fields(rows), "tables": _blocks(rows)}


def parse_document(doc):
    """-> [parse_page(...)] for every summary sheet, in page order."""
    out = []
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect(page):
            continue
        rec = parse_page(page)
        if rec:
            rec["page"] = pno + 1
            out.append(rec)
    return out
