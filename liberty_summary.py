"""Liberty summary-table extraction (the "Summary Data" screen for Liberty).

Liberty COMP PDFs carry a text "STIMULATION SUMMARY" page — one block per
stage with the treatment roll-up (interval depths, proppant, volume, ISIP,
average/max treating pressure, injection rate) plus job totals. Text, not a
positional grid, so it parses with regex.

  - find_summary_pages(doc): the document's summary/table pages grouped for
    viewing (Stimulation Summary, Proppant Summary, TimeTracker log, Cement
    Report) with page numbers, so the Lab can render them with pdf.js.
  - parse_stimulation(doc): the per-stage Stimulation Summary parsed into a
    structured {columns, rows} grid — one row per stage.
"""
import re

SUMMARY_KINDS = [
    ("stimulation", r"STIMULATION SUMMARY"),
    ("proppant", r"PROPPANT SUMMARY|^Stage No\b"),
    ("timetracker", r"^LIBERTY\s*$|TimeTracker"),
    ("cement", r"^Cement Report"),
]
KIND_TITLES = {
    "stimulation": "Stimulation Summary",
    "proppant": "Proppant Summary",
    "timetracker": "TimeTracker Log",
    "cement": "Cement Report",
}

# order matters: label -> (column name, unit). Interval Base before Top would
# still work (regex is anchored on the label), but keep report order.
FIELDS = [
    (r"Interval Top", "Interval Top", "m"),
    (r"Interval Base", "Interval Base", "m"),
    (r"Prop", "Proppant", "tonne"),
    (r"Total Vol", "Total Volume", "m³"),
    (r"ISIP", "ISIP", "kPa"),
    (r"Average pressure", "Avg Pressure", "kPa"),
    (r"Inj Rate Avg", "Avg Inj Rate", "m³/min"),
    (r"Max\.?\s*treatment pressure", "Max Treatment Pressure", "kPa"),
]


def _page_kind(text):
    for kind, pat in SUMMARY_KINDS:
        if re.search(pat, text, re.M):
            return kind
    return None


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — consecutive same-kind pages grouped."""
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


def is_stimulation_page(page):
    return "STIMULATION SUMMARY" in page.get_text()


_NUM = r"([-\d,]+(?:\.\d+)?)"


def _val(block, label):
    """the number following 'label:' in a stage block, or None."""
    m = re.search(label + r"\s*:?\s*" + _NUM, block)
    if not m:
        return None
    return m.group(1).replace(",", "")


def parse_stimulation(doc):
    """-> {columns, rows, totals} for the per-stage Stimulation Summary,
    or None. One row per stage."""
    text = ""
    for p in range(doc.page_count):
        t = doc[p].get_text()
        if "STIMULATION SUMMARY" in t or (text and "Stage:" in t):
            text += "\n" + t
            # keep appending while the stimulation blocks continue
            if "Stage:" not in t and text:
                break
    if "Stage:" not in text:
        return None

    # split into per-stage blocks on "Stage: N"
    parts = re.split(r"Stage:\s*(\d+)", text)
    # parts = [pre, stageNo, block, stageNo, block, ...]
    rows = []
    for i in range(1, len(parts) - 1, 2):
        stage = parts[i].strip()
        block = parts[i + 1]
        row = [stage]
        for _pat, _name, _unit in FIELDS:
            row.append(_val(block, _pat))
        if any(c is not None for c in row[1:]):
            rows.append(row)
    if not rows:
        return None
    columns = ["Stage"] + [f"{n} ({u})" for _p, n, u in FIELDS]

    totals = {}
    mf = re.search(r"Total Fluid All Fracs\s*:?\s*" + _NUM, text)
    mp = re.search(r"Total Proppant All Fracs\s*:?\s*" + _NUM, text)
    md = re.search(r"Pumped Down\s*:?\s*([A-Za-z ]+)", text)
    if mf:
        totals["Total Fluid All Fracs (m³)"] = mf.group(1).replace(",", "")
    if mp:
        totals["Total Proppant All Fracs (tonne)"] = mp.group(1).replace(",", "")
    if md:
        totals["Pumped Down"] = md.group(1).strip()
    return {"columns": columns, "rows": rows, "totals": totals}
