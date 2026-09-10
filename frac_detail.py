"""The "Frac Detail" grid on a Resource Energy Solutions daily completion.

Carmine, #615, on 01340: "you are getting the rotation on this test well but
it is not getting all the stage PDF shows they are there". Both halves are
true and they are about different things. The file carries 290 pages, and only
26 of them are vector chart pages covering 13 zones — the charts for the other
zones are simply not in this PDF, and no amount of chart reading will find
them. What IS in it, on 67 pages, is this table:

    Frac Detail
    Stg  Date      Start Time    Depth  Avg Treat  Avg Slurry  Max Slurry ...
                                 (m)    Press(MPa) Rate        Rate
     26  11-02-25  06:49:00 AM   3638   76.4       7.2         8.3        ...
     27  11-02-25  05:04:00 PM   3540   76         7.7         8.3        ...
    Daily Total                                                      1547

one row per stage pumped that day, with the numbers the charts would have
given. That is what he can see in the PDF.

Read positionally. The header spans up to four printed lines ("Avg Treat" /
"Press" / "(MPa)") and the column NAMES are assembled from them rather than
hard-coded, so a filing that prints a different column set still comes
through with its own headings.

The date is mm-dd-yy, which is not a guess: page 57 prints "Oct 31, 2025" in
its own header beside a row reading "10-31-25", and 31 is not a month. Every
row is checked against the page's own long-form date and dropped if they
disagree — the one thing worse than no date here is a confident wrong one.
"""
import datetime
import re

MARKER = "Frac Detail"

# the row that opens the grid — "Stg" is its first column
_STG = re.compile(r"^Stg\b", re.I)
# a data row starts with a bare stage number
_STAGE_CELL = re.compile(r"^\d{1,3}[A-Za-z]?$")
# "Daily Total" closes the grid; "Time Log" is the section after it
_END = re.compile(r"(?i)^(daily\s+total|time\s+log|total)\b")
_SHORT_DATE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{2})$")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?$")
_LONG_DATE = re.compile(r"\b([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2}),\s*(20\d\d)\b")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}
# how far a data cell may sit from its column's anchor and still belong to it
_COL_TOL = 34.0


def detect(page):
    try:
        return MARKER in (page.get_text() or "")
    except Exception:
        return False


def detect_document(doc):
    for p in range(min(doc.page_count, 400)):
        try:
            if detect(doc[p]):
                return True
        except Exception:
            continue
    return False


def _rows(page):
    """[(y, [(x, text)])] for the page, one entry per printed line."""
    buckets = {}
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                x0, y0 = span["bbox"][0], span["bbox"][1]
                buckets.setdefault(round(y0 / 3.0), []).append((x0, t))
    return [(k * 3.0, sorted(v)) for k, v in sorted(buckets.items())]


def _page_dates(text):
    """Every long-form date printed on the page, as (y,m,d) — the report's own
    'Date:' among them. Used only to check the grid's mm-dd-yy reading."""
    out = []
    for mon, day, year in _LONG_DATE.findall(text or ""):
        m = _MONTHS.get(mon.lower())
        if m:
            out.append((int(year), m, int(day)))
    return out


def _stamp(short, clock, page_dates):
    """('11-02-25', '06:49:00 AM') -> '2025-11-02 06:49:00', or None.

    mm-dd-yy, and only when the page itself prints that day somewhere. A
    filing that ever switches to dd-mm-yy would fail this check rather than
    silently move every stage to another month.
    """
    d = _SHORT_DATE.match(short or "")
    if not d:
        return None
    mo, dy, yr = int(d.group(1)), int(d.group(2)), 2000 + int(d.group(3))
    if not (1 <= mo <= 12 and 1 <= dy <= 31):
        return None
    if page_dates and (yr, mo, dy) not in page_dates:
        return None
    c = _CLOCK.match(clock or "")
    if not c:
        return f"{yr:04d}-{mo:02d}-{dy:02d}"
    h, mi, se = int(c.group(1)), int(c.group(2)), int(c.group(3) or 0)
    if not (1 <= h <= 12 and mi < 60 and se < 60):
        return f"{yr:04d}-{mo:02d}-{dy:02d}"
    h = (h % 12) + (12 if c.group(4).lower() == "p" else 0)
    return f"{yr:04d}-{mo:02d}-{dy:02d} {h:02d}:{mi:02d}:{se:02d}"


def _columns(rows, i):
    """-> ([anchor x], [name]) from the header block starting at row i.

    The header runs over as many printed lines as the longest heading needs.
    The FIRST of them fixes the anchors; the rest are folded onto the nearest
    anchor to build the full name, so "Avg Treat" + "Press" + "(MPa)" becomes
    one column heading without a table of them living here.
    """
    anchors = [x for x, _t in rows[i][1]]
    names = [t for _x, t in rows[i][1]]
    for j in range(i + 1, min(i + 5, len(rows))):
        cells = rows[j][1]
        # a data row ends the header
        if cells and _STAGE_CELL.match(cells[0][1]):
            break
        for x, t in cells:
            k = min(range(len(anchors)), key=lambda n: abs(anchors[n] - x))
            if abs(anchors[k] - x) <= _COL_TOL:
                names[k] = f"{names[k]} {t}"
    return anchors, [" ".join(n.split()) for n in names]


def parse_page(page):
    """-> ([column names], [row values]) for one page's grid, or None."""
    if not detect(page):
        return None
    rows = _rows(page)
    at = next((i for i, (_y, cells) in enumerate(rows)
               if any(c[1] == MARKER for c in cells)), None)
    if at is None:
        return None
    hdr = next((i for i in range(at + 1, min(at + 4, len(rows)))
                if rows[i][1] and _STG.match(rows[i][1][0][1])), None)
    if hdr is None:
        return None
    anchors, names = _columns(rows, hdr)
    if len(anchors) < 3:
        return None
    page_dates = _page_dates(page.get_text() or "")
    out = []
    for _y, cells in rows[hdr + 1:]:
        if not cells:
            continue
        first = cells[0][1]
        if _END.search(first) or (len(cells) > 1 and _END.search(cells[1][1])):
            break
        if not _STAGE_CELL.match(first):
            continue
        row = [""] * len(anchors)
        for x, t in cells:
            k = min(range(len(anchors)), key=lambda n: abs(anchors[n] - x))
            if abs(anchors[k] - x) <= _COL_TOL:
                row[k] = f"{row[k]} {t}".strip() if row[k] else t
        out.append((row, page_dates))
    if not out:
        return None
    return names, out


def parse_document(path_or_doc):
    """-> {columns, rows} — one row per stage, Date and Start Time folded into
    a single stamp so the exporter's DATETIME formatting applies."""
    doc = path_or_doc
    names = None
    seen, recs = set(), []
    for p in range(doc.page_count):
        try:
            got = parse_page(doc[p])
        except Exception:
            continue
        if not got:
            continue
        cols, rows = got
        if names is None:
            names = cols
        elif cols != names:
            continue                   # a different grid; leave it alone
        for row, page_dates in rows:
            fp = tuple(row)
            if fp in seen:
                continue
            seen.add(fp)
            recs.append((row, page_dates))
    if not recs or not names:
        return None

    # fold Date + Start Time into one stamp
    di = next((i for i, n in enumerate(names) if n.strip().lower() == "date"),
              None)
    ti = next((i for i, n in enumerate(names)
               if n.strip().lower() in ("start time", "starttime")), None)
    out_cols, out_rows = None, []
    for row, page_dates in recs:
        if di is not None and ti is not None:
            stamp = _stamp(row[di], row[ti], page_dates)
            keep = [v for i, v in enumerate(row) if i not in (di, ti)]
            hdr = [n for i, n in enumerate(names) if i not in (di, ti)]
            row = keep[:di] + [stamp or ""] + keep[di:]
            hdr = hdr[:di] + ["Start"] + hdr[di:]
        else:
            hdr = list(names)
        out_cols = hdr
        out_rows.append(row)

    def key(r):
        m = re.match(r"\d+", str(r[0] or ""))
        return (int(m.group()) if m else 10 ** 9, str(r[0]))

    out_rows.sort(key=key)
    return {"columns": out_cols, "rows": out_rows}
