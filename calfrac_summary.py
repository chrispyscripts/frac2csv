"""Calfrac summary-table extraction (the "Summary Data" screen for Calfrac).

Calfrac COMP PDFs carry a zone-major "Treatment Summary" page: columns are
the frac zones (1..N), rows are the treatment fields (interval, times,
volumes, pressures, rates, proppant, chemicals). This reads that grid
positionally and TRANSPOSES it to one row per zone/stage — the shape the
rest of the app expects.

  - find_summary_pages(doc): the summary/table pages grouped for viewing.
  - parse_treatment_summary(doc): the modern "Treatment Summary" parsed into
    {columns, rows}, one row per zone. (The older "Multiple Zone Frac
    Treatment Summary" layout is not parsed yet — its pages still render.)
"""
import re

SUMMARY_KINDS = [
    ("treatment", r"^Treatment Summary\s*$"),
    ("multizone", r"^Multiple Zone Frac Treatment Summary"),
    ("general", r"^GENERAL INFORMATION"),
]
KIND_TITLES = {
    "treatment": "Treatment Summary",
    "multizone": "Multiple-Zone Treatment Summary",
    "general": "General Information",
}


def _page_kind(text):
    head = next((l.strip() for l in text.splitlines() if l.strip()), "")
    for kind, pat in SUMMARY_KINDS:
        if re.search(pat, head):
            return kind
    return None


def find_summary_pages(doc):
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


_CALFRAC_MARK = re.compile(r"Calfrac\s+Service\s+Line", re.I)
# a zone column label: "7", "24", or a re-treat attempt "9A"
_ZONE_COL = re.compile(r"\d{1,2}[A-Za-z]?")


def is_treatment_page(page):
    t = page.get_text()
    head = next((l.strip() for l in t.splitlines() if l.strip()), "")
    if head == "Treatment Summary" and "Zone" in t:
        return True
    # The 2018-vintage reports print the same zone-major grid but lead the
    # page with the UWI line, so the title test misses every one of them and
    # 00082/00087 came back with no summary at all — no Tables tab, and no
    # zone times. Fall back to the grid's own shape: a Calfrac page whose
    # "Zone" header row has real zone columns under it. Zone labels are one or
    # two digits, so the daily-report sheets (where "Zone" heads a cell
    # holding a phone number) cannot supply a column here.
    if not _CALFRAC_MARK.search(t):
        return False
    for _y, cells in _rows(page):
        if not any(c == "Zone" for _x, c in cells):
            continue
        # one column is enough — a well's last summary sheet often carries a
        # single leftover zone, and dropping it loses that zone's whole row
        if any(_ZONE_COL.fullmatch(c.strip()) for _x, c in cells):
            return True
    return False


def detect(doc):
    """True when the document prints the modern zone-major grid.

    This module's OWN gate. The dispatch used to ask for these tables only
    where the chart side had already recognised an MView plot, which reads
    the summary out of a filing's plots rather than out of the summary.
    """
    for p in range(doc.page_count):
        if is_treatment_page(doc[p]):
            return True
    return False


_START_COL = re.compile(r"^Start Time\b", re.I)
_JOBDATE_COL = re.compile(r"^Job Date\b", re.I)
_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _col(columns, pat):
    for i, c in enumerate(columns):
        if pat.match(c):
            return i
    return None


def zone_clock(doc):
    """-> {zone label: {'start': 'HH:MM:SS', 'date': 'YYYY-MM-DD' | None}}.

    These reports chart one zone per page against an x axis in elapsed minutes
    with no clock anywhere on the plot, so every stage was exported starting
    00:00:00 and the stages sharing a day landed on identical date ranges —
    00304's thirty stages collapsed onto seven, seven of them all claiming
    2021-04-01 00:00 to 01:00. The zone's real start is printed in the
    Treatment Summary grid, one column per zone, and so is the date it ran:
    00304's zone 1 is dated 3/17/2021, ten days before zone 2, so a job date
    taken once for the whole well would be wrong for 29 of its 30 stages.

    A zone whose start the grid does not print is omitted rather than given a
    default — the caller is expected to leave such a stage's clock blank, and
    the time axis to fall back to elapsed time. A wrong clock is worse than
    no clock.
    """
    parsed = parse_treatment_summary(doc)
    if not parsed:
        return {}
    cols = parsed["columns"]
    si, di = _col(cols, _START_COL), _col(cols, _JOBDATE_COL)
    if si is None:
        return {}
    out = {}
    for row in parsed["rows"]:
        raw = str(row[si]).strip() if si < len(row) and row[si] else ""
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
        if not m:
            continue
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            continue
        date = None
        if di is not None and di < len(row) and row[di]:
            d = _MDY.match(str(row[di]).strip())
            if d:
                mon, day, yr = int(d.group(1)), int(d.group(2)), int(d.group(3))
                if 1 <= mon <= 12 and 1 <= day <= 31:
                    date = f"{yr:04d}-{mon:02d}-{day:02d}"
        out[str(row[0]).strip()] = {"start": f"{h:02d}:{mi:02d}:00", "date": date}
    return out


def zone_clock_for(clocks, stage):
    """The entry for a chart's printed stage label, or None.

    Charts label the zone "04" where the grid's row key is "4", and some
    carry a suffix ("12 Attempt 2"), so match on the leading digits.
    """
    if not clocks or stage in (None, ""):
        return None
    s = str(stage).strip()
    if s in clocks:
        return clocks[s]
    m = re.match(r"\d+", s)
    if not m:
        return None
    base = int(m.group(0))
    if str(base) in clocks:
        return clocks[str(base)]
    # a re-treated zone is keyed per attempt ("9A", "9B"); the chart draws one
    # zone 9, so take the first attempt — the order parse_treatment_summary
    # already sorted the rows into
    for k, v in clocks.items():
        km = re.match(r"\d+", k)
        if km and int(km.group(0)) == base:
            return v
    return None


def zone_start_times(doc):
    """-> {zone label: 'HH:MM:SS'} — the start half of zone_clock()."""
    return {z: v["start"] for z, v in zone_clock(doc).items()}


def _rows(page):
    """spans grouped into rows by y-centre -> [(y, [(x, text)])]."""
    runs = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if not t:
                continue
            bb = ln["spans"][0]["bbox"]
            runs.append(((bb[1] + bb[3]) / 2, bb[0], t))
    rows = {}
    for y, x, t in sorted(runs):
        key = next((k for k in rows if abs(k - y) < 3), y)
        rows.setdefault(key, []).append((x, t))
    return [(y, sorted(v)) for y, v in sorted(rows.items())]


_UNIT = re.compile(r"^(m³?|m|T|t|L|MPa|kPa/m|kg/m³|m³/min|m³/m|mm|kg/m|kW|Kw|"
                   r"%|°C|hh:mm|scm|scm/min|SCF|e3m3|Yes\?|SG)$")
_NUMISH = re.compile(r"^[\d,.\s/:%+-]*$")


def _parse_page(page):
    """one Treatment-Summary page -> (zone_labels, {field: {zone: value}},
    {field: unit}) or None."""
    rows = _rows(page)
    hdr = next(((y, cells) for y, cells in rows
                if any(t == "Zone" for _x, t in cells)), None)
    if hdr is None:
        return None
    hy, hcells = hdr
    # zone columns: the numeric labels after 'Zone'/'U of M' on the header row
    zone_x, zone_lab, uom_x = [], [], None
    for x, t in hcells:
        if t == "U of M":
            uom_x = x
        elif _ZONE_COL.fullmatch(t):
            zone_x.append(x); zone_lab.append(t)
    if len(zone_x) < 1:
        return None
    if uom_x is None:
        uom_x = (max(x for x, _ in hcells if _ != "Zone") + zone_x[0]) / 2

    def nearest_zone(x):
        i = min(range(len(zone_x)), key=lambda i: abs(zone_x[i] - x))
        return i if abs(zone_x[i] - x) < 26 else None

    fields, units = {}, {}
    order = []
    for y, cells in rows:
        if y <= hy + 2:
            continue
        # label = text left of the U-of-M column
        label = " ".join(t for x, t in cells if x < uom_x - 6).strip(" :")
        if not label or _NUMISH.match(label):
            # could be a units-only sub-line; attach to the previous field
            for x, t in cells:
                if _UNIT.match(t) and order:
                    units.setdefault(order[-1], t)
            continue
        if label in fields:
            continue
        vals = {}
        unit = ""
        for x, t in cells:
            if x < uom_x - 6:
                continue
            if _UNIT.match(t):
                unit = t; continue
            zi = nearest_zone(x)
            if zi is not None and re.search(r"\d", t):
                vals.setdefault(zi, t.replace(",", ""))
        if vals:
            fields[label] = vals
            units[label] = unit
            order.append(label)
    return zone_lab, fields, units, order


def parse_treatment_summary(doc):
    """-> {columns, rows} with one row per zone, or None. Stitches the zone
    columns across the well's Treatment-Summary pages."""
    pages = [doc[p] for p in range(doc.page_count) if is_treatment_page(doc[p])]
    if not pages:
        return None
    # collect (zone_label -> {field: value}) across pages
    zone_data = {}   # zone label -> {field: value}
    field_order, unit_map = [], {}
    for pg in pages:
        parsed = _parse_page(pg)
        if not parsed:
            continue
        zone_lab, fields, units, order = parsed
        for f in order:
            if f not in field_order:
                field_order.append(f)
            unit_map.setdefault(f, units.get(f, ""))
        for f, zvals in fields.items():
            for zi, v in zvals.items():
                if zi < len(zone_lab):
                    z = zone_lab[zi]
                    zone_data.setdefault(z, {})[f] = v
    if not zone_data:
        return None
    columns = ["Zone"] + [f + (f" ({unit_map[f]})" if unit_map.get(f) else "")
                          for f in field_order]
    rows = []
    for z in sorted(zone_data, key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        row = [z] + [zone_data[z].get(f) for f in field_order]
        rows.append(row)
    return {"columns": columns, "rows": rows}
