"""BJ "Fracturing-Acidizing Treatment" sheets — the pumped schedule, as text.

00058 is 218 pages that reported "No extractable data" for weeks (#332, #360,
#361). It is not empty and it is not scanned: it carries NO treatment charts at
all — measured, zero pages hold plotted-curve ink — and 66 pages of structured
tables that nothing read. Each frac prints across three sheets:

    page 1   header fields, INTERVALS, WELL GEOMETRY, TREATMENT SCHEDULE
    page 2   the schedule continued, then fluid and proppant totals
    page 3   additives, and the pressure summary

The schedule is the prize: one row per pump step with clean and slurry volume,
rate, proppant type, start/end concentration and mass. That is the same thing
SCHEDULES.md went looking for across every provider, printed in a text layer
and needing no OCR.

Two tables come out of a document: the schedule, one row per step across every
frac, and a per-frac summary. The other blocks are left for a later pass rather
than half-read.
"""
import re

TITLE = "Fracturing-Acidizing Treatment"

# The schedule header wraps over five rows ("Clean" / "Vol." / "(m³)"), so it is
# named here rather than reassembled from the cells — the wrap differs between
# filings and a reassembled name would too.
SCHEDULE_COLUMNS = [
    "Frac", "Step", "Placement", "Fluid System", "Clean Vol (m³)",
    "Slurry Vol (m³)", "Rate (m³/min)", "Proppant 1", "Proppant 2",
    "Start Conc (kg/m³)", "End Conc (kg/m³)",
    "Prop Mass Surface (t)", "Prop Mass In Formation (t)",
]
SUMMARY_COLUMNS = [
    "Frac", "Zone", "Start Date", "End Date", "Well",
    "Depth TVD/TMD (m)", "District", "State/Province", "Completion Type",
]
_HEADER_KEYS = {
    "Start Date": "Start Date", "End Date": "End Date", "Well": "Well",
    "Depth(TVD/TMD)": "Depth TVD/TMD (m)", "Zone": "Zone",
    "District": "District", "State/Province": "State/Province",
    "Completion Type": "Completion Type",
}


def detect(page_or_doc):
    """True for a page carrying a Fracturing-Acidizing sheet, or a document
    holding at least one."""
    if hasattr(page_or_doc, "page_count"):
        for p in range(page_or_doc.page_count):
            if TITLE in (page_or_doc[p].get_text() or ""):
                return True
        return False
    return TITLE in (page_or_doc.get_text() or "")


def _frac_no(page):
    """The sheet names its frac on the line under the title: 'Frac 7'."""
    m = re.search(r"^\s*Frac\s+(\S+)\s*$", page.get_text() or "", re.M)
    return m.group(1) if m else ""


# The header block merges a cell now and then, so "Completion Type" comes back
# with the timing paragraph that follows it stuck on the end ("Plug & Perf
# Total Time (hrs): 9.2 Non-Pump Time…"). Cut at the first of those labels
# rather than shipping a paragraph in a column that holds two words everywhere
# else.
_BLEED = re.compile(r"\s+(?:Total Time|Non-Pump Time|Standby|Pump Time)\b.*$",
                    re.I | re.S)


def _cell(v):
    """Table cells arrive with soft wraps in them and thousands separators on
    the numbers. Neither belongs in a CSV."""
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if re.fullmatch(r"-?[\d,]+(\.\d+)?", s):
        return s.replace(",", "")
    return s


def _tables(page):
    try:
        return page.find_tables().tables
    except Exception:
        return []


def _is_schedule_head(rows):
    return bool(rows) and _cell(rows[0][0]) == "#" and \
        any(_cell(c) == "Placement" for c in rows[0])


def _schedule_rows(rows, start):
    """Data rows only — a step is a row whose first cell is a step number."""
    out = []
    for r in rows[start:]:
        cells = [_cell(c) for c in r]
        if not re.fullmatch(r"\d+", cells[0] or ""):
            continue
        cells = (cells + [""] * 12)[:12]
        out.append(cells)
    return out


def _header_fields(page):
    """The key/value block at the top of a frac's first sheet."""
    got = {}
    for t in _tables(page):
        rows = t.extract()
        if not rows or len(rows[0]) < 2:
            continue
        for r in rows:
            cells = [_cell(c) for c in r]
            for i in range(0, len(cells) - 1, 2):
                key = _HEADER_KEYS.get(cells[i])
                if key and cells[i + 1]:
                    got.setdefault(key, cells[i + 1])
    return got


def parse_document(doc):
    """-> {"schedule": {columns, rows} | None, "summary": {columns, rows} | None}"""
    sched, summary = [], []
    frac = ""
    seen_summary = set()
    for pno in range(doc.page_count):
        page = doc[pno]
        if not detect(page):
            continue
        this = _frac_no(page)
        if this:
            frac = this
        for t in _tables(page):
            rows = t.extract()
            if not rows:
                continue
            if _is_schedule_head(rows):
                # a frac's first sheet: header block, then the schedule
                if frac and frac not in seen_summary:
                    f = _header_fields(page)
                    if f:
                        seen_summary.add(frac)
                        row = [f.get(c, "") for c in SUMMARY_COLUMNS[1:]]
                        ct = SUMMARY_COLUMNS.index("Completion Type") - 1
                        row[ct] = _BLEED.sub("", row[ct]).strip()
                        summary.append([frac] + row)
                sched += [[frac] + r for r in _schedule_rows(rows, 1)]
            elif len(rows[0]) == 12:
                # the same sheet continued overleaf: no header, same 12 columns
                sched += [[frac] + r for r in _schedule_rows(rows, 0)]
    out = {"schedule": None, "summary": None}
    if sched:
        out["schedule"] = {"columns": SCHEDULE_COLUMNS, "rows": sched}
    if summary:
        out["summary"] = {"columns": SUMMARY_COLUMNS, "rows": summary}
    return out
