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


def is_treatment_page(page):
    t = page.get_text()
    head = next((l.strip() for l in t.splitlines() if l.strip()), "")
    return head == "Treatment Summary" and "Zone" in t


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
        elif re.fullmatch(r"\d{1,2}", t):
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
