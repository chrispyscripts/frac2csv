"""STEP Energy Services summary-table extraction (the "Summary Data" screen
for STEP).

Every STEP COMP PDF carries a "Treatment Report - Daily Stage Summary" sheet
whose per-stage grid is *transposed*: the treatment fields are the ROWS and
the stages are the COLUMNS, ten stages to a page-block, with a trailing
Cum / Max / "10 stg Avg" summary column that is **not** a stage.  Nothing
else in the document prints top/bottom depth, ball size, the volume
breakdown, per-mesh pumped-vs-placed proppant, screen-out flags, the
pressure family or the bi-fuel block, so this is the only place ~40
per-stage fields exist.

  - find_summary_pages(doc): the summary/table pages grouped for viewing.
  - parse_stage_summary(doc): the transposed grid parsed into
    {columns, rows}, TRANSPOSED BACK to one row per stage — the shape the
    rest of the app expects.

Every layout generation seen in the BCER corpus is handled, and all of them
are vector text — only the *charts* in the 2017 books are raster, this sheet
never is, so no OCR is involved:

  Version: 3.1  2017   section title " Stage Summary", header cell "Stage #",
                       left gutter = a numeric field id, "Fluid Total" /
                       "Flush/Spacer", "Sleeve Shift", "Average Fluid Rate",
                       Bi-Fuel block.
  Version: 3.4  2017   as 3.1 plus "Open Well/Sleeve Shift", DH rates,
                       "Actual Seat Volume" and a "Screen Out (Y/N)" row.
  Version: 4    2017   as 3.4 plus Acid and more named additives.
  Version: 1    2024+  section title "Interval Summary", header cell reads
                       "Interval #", left gutter = a clipped word ("Inte",
                       "CON", "Max"), splits the volumes into Spacer / Flush
                       / Pump Down Total / Clean Total, always prints
                       "Screen Out (Y/N)", and a Dual-Fuel block.

Note the sheet is an Excel export a field engineer fills in per DAY, so the
same physical row can be relabelled between pages of one book — 00183 page 1
says "Clean Total" and pages 2-4 say "Fluid Total"; 00269 page 3 says
"Proppant Volume" where the others say "Proppant".  Labels are kept verbatim
(two sparse columns) rather than aliased: the 2024 layout really does print
"Clean Total" and "Proppant" as two different rows, so a global alias would
corrupt it.

The grid is read positionally: the stage-number header row fixes the column
centres, every body row is split into <field label | unit | per-stage
cells>, and cells are dropped into the nearest stage column.  Reading order
is not usable — plenty of rows are sparse (00244 prints Over-Flush Pressure
for 4 of its 10 stages), so the Nth printed number is rarely the Nth stage.
The template also always prints one MORE stage heading than it has data for
(block 11-20 is headed 11,12..20 *and* 21; the last block can head it
"#VALUE!"), and the Cum/Max/Avg roll-up sits just to the right of it, so a
phantom column is rejected three ways: its label must be numeric, it must
sit on the same arithmetic pitch as the real columns, and it must actually
receive data.

Not captured, on purpose: the roll-up column (Cum / Max / "10 stg Avg" /
Count and the "Avg mins /10 stg" box) — those are block aggregates, not
stage values; the left gutter (the workbook's internal row id / clipped
description); the sheet header block (License #, UWI #, Job #, Program #,
Version); and the separate cover sheet that shares the title but carries
only job-level Well/Product Information.  The cover sheet is still listed by
find_summary_pages() so it can be viewed.
"""
import re

TITLE = "Treatment Report - Daily Stage Summary"

SUMMARY_KINDS = [
    ("stage-summary", None),        # decided by is_stage_summary_page()
    ("daily", None),                # the Daily title page, no grid
    ("interval", r"STEP Energy Services Interval Summary"),
]
KIND_TITLES = {
    "stage-summary": "Daily Stage Summary (per-stage grid)",
    "daily": "Treatment Report — Daily",
    "interval": "Interval Summary (per-stage sheets)",
}

# the roll-up column header: '1-10 Totals', '11-20 Totals', '110-111 Totals'.
# A re-stage gets a fractional number, so the block can read '1-10.1 Totals'.
_TOTALS = re.compile(r"^\d{1,4}(?:\.\d{1,2})?\s*-\s*\d{1,4}(?:\.\d{1,2})?"
                     r"\s+Totals$", re.M)
# a stage heading: '11', '1.0', '110.0', '10.1'  (the template also emits
# a phantom trailing heading, and on the last block sometimes '#VALUE!')
_STAGENO = re.compile(r"^\d{1,4}(?:\.\d{1,2})?$")
# anything that counts as real data in a cell
_VALUE = re.compile(r"^(?:-?[\d,]+(?:\.\d+)?|\d{1,2}:\d{2}(?::\d{2})?|"
                    r"\d{4}[-/]\d{2}[-/]\d{2}|[YN])$")

# --------------------------------------------------------------- page kinds

def is_stage_summary_page(page):
    """True for a Daily-Stage-Summary sheet that actually carries the grid
    (the first sheet of the set is a well/product cover with the same
    title and no grid at all)."""
    t = page.get_text()
    if TITLE not in t:
        return False
    if not _TOTALS.search(t):
        return False
    # the label-column heading ('Stage #' in 2017, 'Interval #' in 2024+) or,
    # failing that, the section title above the grid
    return (re.search(r"^\s*(?:Stage|Interval)\s*#\s*$", t, re.M) is not None
            or re.search(r"^\s*(?:Stage|Interval) Summary\s*$", t, re.M)
            is not None)


def detect(doc):
    """True when the book carries a STEP Daily-Stage-Summary grid.

    Used as the pipeline's provider gate.  The other summary modules gate on
    the chart provider already found in the document, but STEP's charts only
    surface when OCR/raster is enabled (and not at all in the Lab), so the
    grid page has to speak for itself.  Its title is STEP's alone, so this is
    safe: no other vendor prints it."""
    return any(is_stage_summary_page(doc[p]) for p in range(doc.page_count))


def _page_kind(page):
    t = page.get_text()
    if TITLE in t:
        return "stage-summary" if is_stage_summary_page(page) else "daily"
    if re.search(r"STEP Energy Services Interval Summary", t):
        return "interval"
    return None


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — consecutive same-kind pages are
    grouped into one entry so a multi-page grid views as one item."""
    groups = []
    for p in range(doc.page_count):
        try:
            kind = _page_kind(doc[p])
        except Exception:
            kind = None
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


# ------------------------------------------------------------------ geometry

def _cells(page):
    """[(y, x0, x1, text)] — spans merged into table cells.  Spans that sit
    on one PDF line but are separated by a real gap (label vs unit) stay
    separate cells; spans split only by a font change are re-joined."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            cur = None
            for sp in ln["spans"]:
                t = sp["text"]
                if not t.strip():
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                y = (y0 + y1) / 2
                if cur and x0 - cur[2] < 6:
                    cur = (min(cur[0], y), cur[1], max(cur[2], x1),
                           cur[3] + t)
                else:
                    if cur:
                        out.append(cur)
                    cur = (y, x0, x1, t)
            if cur:
                out.append(cur)
    return [(y, x0, x1, t.strip()) for y, x0, x1, t in out if t.strip()]


def _rows(cells, tol=2.5):
    """cells grouped into rows by y-centre -> [(y, [cells sorted by x])]."""
    rows = {}
    for c in sorted(cells):
        key = next((k for k in rows if abs(k - c[0]) < tol), c[0])
        rows.setdefault(key, []).append(c)
    return [(y, sorted(v, key=lambda c: c[1])) for y, v in sorted(rows.items())]


def _clean_unit(u):
    """'/l' -> 'L', '(Y/N)' -> 'Y/N', 'YYYY-MM-DD' kept as-is."""
    u = re.sub(r"\s+", " ", u).strip()
    if u.startswith("(") and u.endswith(")"):
        u = u[1:-1].strip()
    if u in ("#N/A", "#VALUE!", "#REF!", "-"):
        return ""                       # the workbook leaked an error cell
    if re.fullmatch(r"/\s*[lL]", u):
        return "L"
    return u


def _num(t):
    return t.replace(",", "")


# -------------------------------------------------------------------- parser

def _parse_page(page):
    """one grid sheet -> (stage_labels, [(field, unit, {stage_idx: value})])
    or None."""
    cells = _cells(page)
    rows = _rows(cells)

    hdr = None
    for y, rc in rows:
        tot = next((c for c in rc if _TOTALS.match(c[3])), None)
        if tot is not None:
            hdr = (y, rc, tot[1])
            break
    if hdr is None:
        return None
    hy, hrow, tot_x0 = hdr

    cand = [((c[1] + c[2]) / 2, c[3]) for c in hrow
            if c[2] < tot_x0 - 2 and _STAGENO.match(c[3])]
    if not cand:
        return None
    cand.sort()

    # The template heads one column more than it ever fills (block 11-20 is
    # headed 11..20 *and* 21) and parks the Cum/Max/Avg roll-up immediately
    # to its right.  Two cheap sanity filters here — the heading must sit
    # roughly on the arithmetic run (the sheets drift a few points mid-row,
    # so this is deliberately loose) and must stay clear of the roll-up
    # header — and the real test (does the column receive data?) below.
    pitch = (cand[1][0] - cand[0][0]) if len(cand) > 1 else 75.0
    if pitch <= 1:
        return None
    tol = max(6.0, pitch * 0.25)
    keep = [(cx, lab) for i, (cx, lab) in enumerate(cand)
            if abs(cx - (cand[0][0] + i * pitch)) <= tol
            and cx < tot_x0 - pitch / 2]
    if not keep:
        return None
    centres = [c for c, _l in keep]
    labels = [_stage_label(l) for _c, l in keep]
    half = pitch / 2

    fields = []          # [(label, unit, {col_idx: value})]
    hits = [0] * len(centres)
    body = [(y, rc) for y, rc in rows if y > hy + 4]

    # the field-label column: right-aligned; the unit column sits between it
    # and the first stage column; the left gutter (field id / clipped word)
    # ends far short of the label column.
    left = [c for _y, rc in body for c in rc
            if (c[1] + c[2]) / 2 < centres[0] - half]
    if not left:
        return None
    unit_x1 = max(c[2] for c in left)
    # the gutter is separated from the label column by a wide blank band;
    # find the first such gap in the left-region right edges (label cells
    # are right-aligned but to two or three different merged widths, so a
    # fixed offset from the label edge is not safe).
    edges = sorted({round(c[2], 1) for c in left})
    gutter_x1 = -1e9
    for a, b in zip(edges, edges[1:]):
        if b - a > 40:
            gutter_x1 = a
            break

    for y, rc in body:
        label, unit = [], ""
        vals = {}
        for c in rc:
            cx = (c[1] + c[2]) / 2
            if cx < centres[0] - half:
                if c[2] <= gutter_x1 + 0.5:
                    continue                       # left gutter: id / clip
                if c[2] >= unit_x1 - 3 and label:
                    unit = c[3]
                else:
                    label.append(c[3])
                continue
            i = min(range(len(centres)), key=lambda i: abs(centres[i] - cx))
            if abs(centres[i] - cx) > half:
                continue                           # roll-up column
            if i not in vals and c[3]:
                vals[i] = _num(c[3])
                if _VALUE.match(c[3]):
                    hits[i] += 1
        name = re.sub(r"\s+", " ", " ".join(label)).strip(" :")
        if not name or not vals:
            continue                               # section header / blank
        fields.append((name, _clean_unit(unit), vals))

    good = [i for i in range(len(centres)) if hits[i] >= 2]
    if not good:
        return None
    remap = {old: new for new, old in enumerate(good)}
    stages = [labels[i] for i in good]
    out = []
    for name, unit, vals in fields:
        v = {remap[i]: t for i, t in vals.items() if i in remap}
        if v:
            out.append((name, unit, v))
    return stages, out


def _numeric(t):
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def _stage_label(t):
    t = t.strip()
    if re.fullmatch(r"\d+\.0+", t):
        t = t.split(".")[0]
    return str(int(t)) if t.isdigit() else t


def parse_stage_summary(doc):
    """-> {columns, rows} with one row per stage, or None.  Stitches the
    stage columns across every Daily-Stage-Summary grid sheet in the book."""
    pages = [doc[p] for p in range(doc.page_count)
             if is_stage_summary_page(doc[p])]
    if not pages:
        return None

    order, units = [], {}
    data = {}            # stage label -> {field: value}
    seq = []             # stage labels in document order
    job, prev_first = 1, None
    for pg in pages:
        try:
            parsed = _parse_page(pg)
        except Exception:
            parsed = None
        if not parsed:
            continue
        stages, fields = parsed
        # a book that staples two jobs together restarts the stage numbers;
        # tag the second set so it cannot silently overwrite the first
        first = _numeric(stages[0])
        if prev_first is not None and first is not None and first <= prev_first:
            job += 1
        if first is not None:
            prev_first = first
        if job > 1:
            stages = [f"{s} ({job})" for s in stages]
        for name, unit, vals in fields:
            if name not in units or (not units[name] and unit):
                units[name] = unit
            if name not in order:
                order.append(name)
            for i, v in vals.items():
                s = stages[i]
                if s not in data:
                    data[s] = {}
                    seq.append(s)
                data[s][name] = v
    if not data:
        return None

    columns = ["Stage"] + [n + (f" ({units[n]})" if units.get(n) else "")
                           for n in order]
    # de-duplicate identical column names (a bare 'Max'/'Avg' can repeat)
    seen, cols = {}, []
    for c in columns:
        if c in seen:
            seen[c] += 1
            c = f"{c} #{seen[c]}"
        else:
            seen[c] = 1
        cols.append(c)

    def _key(s):
        m = re.match(r"(\d+(?:\.\d+)?)(?:\s+\((\d+)\))?$", s)
        if m:
            return (int(m.group(2) or 1), float(m.group(1)), "")
        return (99, 0.0, s)

    rows = [[s] + [data[s].get(n) for n in order] for s in sorted(seq, key=_key)]
    return {"columns": cols, "rows": rows}
