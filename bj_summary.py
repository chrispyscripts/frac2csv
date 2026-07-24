"""BJ / WellView summary-table extraction (the "Summary Data" screen).

BJ frac reports bundle the operator's WellView export. Two things are pulled
out here:

  - find_summary_pages(doc): the document's summary/table pages grouped for
    viewing — the per-interval "Totals" frac summary, "Well Completion
    History", "OGC/OGC Chronological Summary", etc. Each group carries its
    page numbers so the Lab can render them with pdf.js.

  - parse_totals(page): the per-interval Totals table parsed into a
    structured {columns, rows} grid — one row per frac interval, columns
    read positionally so the variable proppant/chemical columns survive.

The Totals table is the one that parallels the seconds stages: interval,
start time, depth, breakdown/max/avg pressure, clean/slurry volumes, rates,
ISIP, proppant by mesh, min/max concentration.
"""
import re

# first-line headings that mark each kind of summary page, in display order
SUMMARY_KINDS = [
    ("totals", r"^Totals\s*$"),
    ("completion-history", r"^Well Completion History"),
    ("chronological", r"Chronological Summary"),
    ("regulatory", r"^DC & Workover"),
    ("schematic", r"^Schematic"),
]
KIND_TITLES = {
    "totals": "Totals (frac summary)",
    "completion-history": "Well Completion History",
    "chronological": "Chronological Summary",
    "regulatory": "WellOps Regulatory Report",
    "schematic": "Wellbore Schematic",
}


def _page_kind(text):
    head = next((l.strip() for l in text.splitlines() if l.strip()), "")
    for kind, pat in SUMMARY_KINDS:
        if re.search(pat, head) or (kind == "chronological"
                                    and re.search(pat, text[:200])):
            return kind
    return None


def find_summary_pages(doc):
    """[{kind, title, pages:[...]}] — consecutive pages of the same kind are
    grouped into one entry (a multi-page report views as one item)."""
    groups = []
    for p in range(doc.page_count):
        kind = _page_kind(doc[p].get_text())
        if kind is None:
            continue
        page1 = p + 1                     # 1-based, matching stage/table pages
        if groups and groups[-1]["kind"] == kind and \
                page1 - groups[-1]["pages"][-1] <= 2:
            groups[-1]["pages"].append(page1)
        else:
            groups.append({"kind": kind, "title": KIND_TITLES.get(kind, kind),
                           "pages": [page1]})
    return groups


def is_totals_page(page):
    t = page.get_text()
    return (re.search(r"^Totals\s*$", t, re.M) is not None
            and "Interval #" in t
            and re.search(r"(Breakdown|Max\.?\s*Pressure)", t) is not None)


def _spans(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if t:
                    x0, y0, x1, y1 = sp["bbox"]
                    out.append((x0, (y0 + y1) / 2, t))
    return out


def _clean_name(name):
    """Repair the header fragments WellView emits: the superscript 3 of a m³
    / kg/m³ unit lands in its own span, an empty Bottom-Hole-Temperature
    column bleeds its label into the next column, and proppant columns can
    pick up a stray leading number. Only fold a '3' into a '³' where a real
    '3' span is present — a bare '(m)' must stay '(m)'."""
    n = re.sub(r"\s+", " ", name).strip()
    n = re.sub(r"^Bottom Hole Temperature \(°C\)\s*", "", n)   # empty BHT col
    n = re.sub(r"^[\d,]+\.\d+\s+", "", n)                       # stray number
    n = n.replace("- ", "-")                                    # (CO- WC100)
    # WellView prints the m³/kg/m³ superscript '3' in its own span, landing
    # just before the unit paren: 'Clean 3 (m )' -> 'Clean (m³)'
    n = re.sub(r"\b3\s*\((m|kg/m)\s*(/min)?\s*\)",
               lambda m: "(" + m.group(1) + "³" + (m.group(2) or "") + ")", n)
    n = re.sub(r"(m|kg/m)\s+3\b", r"\1³", n)
    # a leftover lone '3' with a bare (m)/(kg/m) unit -> fold it in. The
    # closing paren may still be missing (it can land in another column), so
    # match the unit with an optional ')'.
    if re.search(r"\b3\b", n) and re.search(r"\(\s*(?:m|kg/m)\b", n):
        n = re.sub(r"\s*\b3\b\s*", " ", n, count=1)
        n = re.sub(r"\(\s*(m|kg/m)\s*\)?", r"(\1³)", n, count=1)
    n = re.sub(r"\)\s*\)+", ")", n)
    n = re.sub(r"\(\s+", "(", n)
    # any standalone '3' left after unit-folding is a stray superscript
    # (e.g. proppant 'SAND, 50/140 3 WHITE'); drop it, but never touch a
    # digit that is part of a number/mesh like 30/70
    n = re.sub(r"\s+3\b(?![\d/])", "", n)
    if "(" not in n:
        n = n.replace(")", "")                                 # orphan close
    n = re.sub(r"\s{2,}", " ", n).strip(" -")
    if n.count("(") == n.count(")") + 1:
        n += ")"
    return n


def parse_totals(page):
    """-> {columns, rows} for the per-interval Totals table, or None."""
    if not is_totals_page(page):
        return None
    spans = _spans(page)
    iy = next((y for x, y, t in spans if "Interval" in t and "#" in t), None)
    if iy is None:
        return None
    dates = sorted(y for x, y, t in spans
                   if re.match(r"20\d\d-\d\d-\d\d", t) and y > iy)
    if len(dates) < 2:
        return None
    first_data = dates[0]

    # column x-anchors: interval numbers + start-times + numeric data cells
    # in the table body define the columns; cluster their left-x.
    body = [(x, y, t) for x, y, t in spans if y >= first_data - 3
            and (re.fullmatch(r"-?[\d,]+(\.\d+)?", t)
                 or re.match(r"20\d\d-\d\d-\d\d", t)
                 or re.fullmatch(r"\d{1,3}", t))]
    xs = sorted(x for x, y, t in body)
    anchors = []
    for x in xs:
        if not anchors or x - anchors[-1] > 10:
            anchors.append(x)
        else:
            anchors[-1] = (anchors[-1] + x) / 2  # running merge
    anchors = sorted(set(round(a) for a in anchors))

    def col_of(x):
        return min(range(len(anchors)), key=lambda i: abs(anchors[i] - x))

    # column names: header spans above the first data row, joined per column
    names = {i: [] for i in range(len(anchors))}
    for x, y, t in spans:
        if iy - 42 <= y < first_data - 3:
            names[col_of(x)].append((y, t))
    columns = []
    for i in range(len(anchors)):
        nm = _clean_name(" ".join(t for _y, t in sorted(names[i])))
        columns.append(nm or f"col{i + 1}")

    # rows: anchor on each start-time datetime; gather the interval number
    # and cells within a tight y-band, drop each into its column
    rows = []
    date_spans = sorted(((y, x, t) for x, y, t in spans
                         if re.match(r"20\d\d-\d\d-\d\d", t) and y > iy),
                        key=lambda s: s[0])
    for dy, dx, dt in date_spans:
        cells = [None] * len(anchors)
        for x, y, t in spans:
            if abs(y - dy) <= 6 and y >= first_data - 3:
                if re.fullmatch(r"-?[\d,]+(\.\d+)?", t) or \
                        re.match(r"20\d\d-\d\d-\d\d", t) or \
                        re.fullmatch(r"\d{1,3}", t):
                    ci = col_of(x)
                    if cells[ci] is None:
                        cells[ci] = t
        if any(c is not None for c in cells):
            rows.append(cells)

    # de-dupe rows that share the same interval+datetime (span y jitter can
    # double-count) and require an interval number in the first column
    seen, clean = set(), []
    for r in rows:
        key = tuple(r[:2])
        if key in seen:
            continue
        seen.add(key)
        clean.append(r)
    if not clean:
        return None
    return {"columns": columns, "rows": clean}
