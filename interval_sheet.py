"""Per-interval frac summary sheets — one page per stage, chart below.

Six filings (00900-00905, all filed 2021-12-23) came back "no extractable
charts or tables found ... no page in it draws a plotted curve". That note was
honest about the charts and wrong about the file: each of these documents
carries one summary sheet per interval — 52 to 57 of them — and every sheet
prints the stage's roll-up as ordinary text above an embedded RASTER chart.
Nothing drew a vector curve, so nothing looked at the text either.

The sheet is operator-assembled around a Liberty job (the daily narrative in
00900 reads "Liberty pumped 34 slickwater frac ... stages #2 - 35"), and it is
not the Liberty STIMULATION SUMMARY that liberty_summary.py reads: that page
does not exist in these filings.

Layout is a machine-generated grid, so it is read POSITIONALLY rather than by
walking the text stream:

    BLACK SWAN HZ NIG CREEK B-A010-B/094-H-04
    INT 1                       Clean Fluid: 282.0 m3   Total Sand Placed: 30.0 tonne
    Sleeve Depth: 5111 m        Ball Max:      0.0 MPa   40/70 Sand:        15.0 tonne
    Start Date: 4:14:00 AM 25-Nov-2021  Pump Time:  Avg Press: 73.0 MPa ...
    End Date:   5:09:00 AM 25-Nov-2021  55 mins     Max rate:   8.8 m3/min ...

The FIELD SET IS NOT FIXED and must not be hard-coded: the proppant meshes
differ from well to well ("30/50 PrimePlus" is on some sheets and not others),
so a label list built from one file loses columns on the next. Labels are
discovered instead — a text cell whose right-hand neighbour on the same row is
a number — and the columns are the union over the document, the same approach
trican2.columns_for takes for the same reason.

Two things are deliberately not read here. The chart is a bitmap and belongs to
the raster reader, not to a table parser. And "Pump Time" is taken from the
page rather than computed from the two clocks, because printed and computed
disagreeing is a signal worth keeping rather than smoothing over.
"""
import datetime
import re

# Both marks, because neither alone is the sheet. "Total Sand Placed" also
# appears on the operator's daily pages (p40 of 00901), and matching it alone
# read a daily report as an interval sheet.
_SAND = re.compile(r"(?i)total\s+sand\s+placed")
_PUMP_TIME = re.compile(r"(?i)pump\s+time\s*:")

# "INT 1", and "INT9" with no space at all — 30 of 00901's 53 sheets print it
# closed up, and requiring the space lost every one of them.
_INT = re.compile(r"(?i)\bINT\s*(\d{1,3}[A-Za-z]?)\b")

# "55 mins" — the sheet's own pump time. "Pump Time:" labels it on the Start
# Date row and the value sits on the End Date row below, the only vertical
# label/value pair on the sheet, so it is read from THAT ROW.
#
# Not from the page: a search over the whole text takes whichever "N mins"
# comes first, and interval 6 of 00905 carries the operator's note
# "(~15mins to reset)" above a printed pump time of 240 — so the stage came
# out claiming 15 minutes for a four-hour interval, and the cross-check
# against its own clocks is what caught it.
_MINS = re.compile(r"\b(\d{1,4})\s*mins?\b", re.I)

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

# Anchored at the START of the cell, not over the whole of it. The date and
# the label beside it are sometimes ONE span — "22-Nov-2021 Pump Time:" on
# p100 of 00904, "22-Nov-2021 36 mins" on the row below — and requiring the
# cell to be nothing but a date read no clock at all on those sheets.
_DATE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})[a-z]*-(\d{4})\b")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\b\.?")
# A value cell: a number, then ONE unit token and nothing else. The tail is
# bounded on purpose. Written as "number then anything", it swallowed labels
# that START with a digit — "40/70 Sand:", "30/50 Sand:", "30/50 PrimePlus:"
# — so the three proppant-mesh columns, which are most of what an interval
# sheet is FOR, were read as values and dropped from every row. A unit has no
# space in it and no colon; a label like that has both.
_VALUE = re.compile(r"^(-?[\d,]+(?:\.\d+)?)\s*([^\s:]*)$")
_HAS_LETTER = re.compile(r"[A-Za-z]")


def detect(page):
    """True for one interval summary sheet."""
    try:
        t = page.get_text() or ""
    except Exception:
        return False
    return bool(_SAND.search(t)) and bool(_PUMP_TIME.search(t))


def detect_document(doc):
    """True when the filing carries these sheets at all.

    Bounded like the other document gates: a 400-page scan is the cost of
    saying no, and it is paid once.
    """
    for p in range(min(doc.page_count, 400)):
        try:
            if detect(doc[p]):
                return True
        except Exception:
            continue
    return False


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — the sheets, grouped for viewing."""
    pages = [p + 1 for p in range(doc.page_count) if detect(doc[p])]
    if not pages:
        return []
    return [{"kind": "interval_sheet",
             "title": "Interval summary sheets",
             "pages": pages}]


def _rows(page):
    """The page's spans as [[(x, text)]], one list per printed row.

    Rows are bucketed rather than clustered: this grid is machine-generated
    and its baselines are exact. The bucket is deliberately fine enough to
    keep "Start Date:" (y=76) apart from "Max Press:" (y=80) — merging them
    is harmless for the label/value walk, since two labels never pair, but
    keeping them apart makes the parse easier to read when it goes wrong.
    """
    buckets = {}
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                x0, y0 = span["bbox"][0], span["bbox"][1]
                buckets.setdefault(round(y0 / 4.0), []).append((x0, t))
    return [sorted(buckets[k]) for k in sorted(buckets)]


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _stamp(clock, date):
    """('4:14:00 AM', '25-Nov-2021') -> '2021-11-25 04:14:00', or None."""
    c, d = _CLOCK.match(clock or ""), _DATE.match(date or "")
    if not c or not d:
        return None
    mon = _MONTHS.get(d.group(2).lower())
    if not mon:
        return None
    h, mi, se = int(c.group(1)), int(c.group(2)), int(c.group(3) or 0)
    if not (1 <= h <= 12 and mi < 60 and se < 60):
        return None
    half = c.group(4).lower()
    h = (h % 12) + (12 if half == "p" else 0)
    return (f"{int(d.group(3)):04d}-{mon:02d}-{int(d.group(1)):02d} "
            f"{h:02d}:{mi:02d}:{se:02d}")


def parse_page(page):
    """-> {field: value} for one sheet, or None when it is not one.

    Field names carry their printed unit ("Avg Press (MPa)") because that is
    the only place the unit is written down, and a pressure column with no
    unit on it is the thing Carmine's channel tables exist to catch.
    """
    if not detect(page):
        return None
    rows = _rows(page)
    text = page.get_text() or ""
    out = {}

    m = _INT.search(text)
    if m:
        out["Stage"] = m.group(1)

    for cells in rows:
        vals = [t for _x, t in cells]
        # the two clocks first, and their cells are then out of the way of the
        # generic walk below
        for i, t in enumerate(vals):
            key = t.strip().rstrip(":").strip().lower()
            if key in ("start date", "end date") and i + 2 < len(vals) + 1:
                stamp = _stamp(vals[i + 1] if i + 1 < len(vals) else "",
                               vals[i + 2] if i + 2 < len(vals) else "")
                if stamp:
                    out["Start" if key == "start date" else "End"] = stamp
                    vals[i] = vals[i + 1] = vals[i + 2] = ""
                if key == "end date":
                    m = _MINS.search(" ".join(t for _x, t in cells))
                    if m:
                        out["Pump Time (min)"] = m.group(1)

        j = 0
        while j < len(vals) - 1:
            label, nxt = vals[j].strip(), vals[j + 1].strip()
            # "Sleeve Depth:   5111 m" — label and value in ONE span
            if ":" in label:
                head, _, tail = label.partition(":")
                if _VALUE.match(tail.strip()) and _HAS_LETTER.search(head):
                    v = _VALUE.match(tail.strip())
                    name = head.strip()
                    unit = v.group(2).strip()
                    out[f"{name} ({unit})" if unit else name] = v.group(1)
                    j += 1
                    continue
            v = _VALUE.match(nxt)
            # A label may print no colon at all — "Avg Rate" does — so the
            # label is whatever text sits immediately left of a number.
            if v and _HAS_LETTER.search(label) and not _VALUE.match(label):
                name = label.rstrip(":").strip()
                unit = v.group(2).strip()
                out[f"{name} ({unit})" if unit else name] = v.group(1)
                j += 2
                continue
            j += 1

    return out or None


def columns_for(rows):
    """The column order for these rows: identity first, then whatever the
    document actually printed, in first-seen order.

    Union rather than a fixed list — see the module docstring. Sorting the
    tail alphabetically would split "40/70 Sand" from "30/50 Sand"; first-seen
    keeps the sheet's own grouping, which is how the operator reads it.
    """
    lead = ["Stage", "Start", "End", "Pump Time (min)"]
    seen = [c for c in lead if any(c in r for r in rows)]
    for r in rows:
        for k in r:
            if k not in seen:
                seen.append(k)
    return seen


_TOL_MIN = 2.0


def reconcile(rec):
    """Fix an End that the sheet printed wrong, using the sheet's own third
    number. -> True when something was changed.

    Two errors, both the sheet's and both common:

      * the date is not rolled at midnight. 00900's interval 27 prints
        "11:36:00 PM 26-Nov-2021" to "12:14:00 AM 26-Nov-2021" and 38 mins.
        Read literally the stage ends 23 hours 22 minutes before it starts.
      * "12:0x AM" is printed PM. 00901's interval 4 prints 10:49 PM to
        "12:01:00 PM" the next day, and 72 mins — so the end is 00:01, and
        the hour is the only ambiguous one on a 12-hour clock.

    Not inferred from the direction of travel, which is the mistake lib1's
    _walk comment documents: the sheet PRINTS the pump time, so there is a
    third measurement to test each reading against. The candidate closest to
    start + printed minutes wins, and only if it lands within two minutes and
    after the start. Anything else is left exactly as printed — an end before
    its start is then still visible, which is the point.
    """
    a, b, pm = rec.get("Start"), rec.get("End"), rec.get("Pump Time (min)")
    if not (a and b and pm):
        return False
    f = "%Y-%m-%d %H:%M:%S"
    try:
        t0 = datetime.datetime.strptime(a, f)
        t1 = datetime.datetime.strptime(b, f)
        want = float(pm)
    except (ValueError, TypeError):
        return False
    if abs((t1 - t0).total_seconds() / 60.0 - want) <= _TOL_MIN:
        return False                                   # already consistent
    best, err = None, None
    for days in (0, 1):
        for hours in (0, 12, -12):
            # the 12-hour flip is offered only for the hour that is actually
            # ambiguous in practice — a 12 printed for a 00
            if hours and t1.hour % 12 != 0:
                continue
            c = t1 + datetime.timedelta(days=days, hours=hours)
            if c <= t0:
                continue
            e = abs((c - t0).total_seconds() / 60.0 - want)
            if err is None or e < err:
                best, err = c, e
    if best is None or err > _TOL_MIN:
        return False
    rec["End"] = best.strftime(f)
    return True


def parse_document(path_or_doc):
    """-> {columns, rows} — one row per interval sheet, in stage order."""
    doc = path_or_doc
    recs, seen = [], set()
    for p in range(doc.page_count):
        try:
            rec = parse_page(doc[p])
        except Exception:
            continue
        if not rec:
            continue
        # A sheet printed twice is one stage. Pages 100 and 101 of 00904 are
        # the same interval-49 sheet field for field, and kept as two rows
        # they put stage 49 in the export twice. Compared on the WHOLE record
        # rather than on the stage, so a genuine re-treat of one interval —
        # which prints different clocks and different numbers — still comes
        # through as its own row.
        fp = tuple(sorted(rec.items()))
        if fp in seen:
            continue
        seen.add(fp)
        reconcile(rec)
        recs.append(rec)
    if not recs:
        return None

    def key(r):
        n = _num(re.sub(r"[A-Za-z]", "", r.get("Stage") or ""))
        return (n if n is not None else 1e9, r.get("Stage") or "")

    recs.sort(key=key)
    cols = columns_for(recs)
    return {"columns": cols,
            "rows": [[r.get(c, "") for c in cols] for r in recs]}
