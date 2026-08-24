"""Trican 'Post-Fracturing Report' parser — the 2024/25 layout (layout B).

Trican re-platformed its post-frac deliverable somewhere around 2023/24.
The old report (``trican2``) prints one landscape "STAGE INFORMATION"
page per stage with Designed/As-Pumped columns; this one prints a
different book entirely and ``trican2.detect`` never fires on it, so
these files used to yield zero rows (00456: 47 stages, 00421: 58
stages, both previously empty).

The layout-B book is, in order:

  * ``Post-Fracturing Report``  cover — UWI, surface location, formation,
    completion type, job type, start/finish date. All vector text.
  * ``Job Summary``            — rasterised charts only, no text.
  * ``Stage Summary``          — one consolidated table, all stages,
    continued over as many pages as it needs.
  * ``Chemical Summary``       — one row per stage, one column per
    chemical, also continued.
  * ``Stage N``                — one label/value page per stage.

The per-stage pages are the primary source: they are keyed by a printed
stage number (so no document-order guessing, unlike layout A), they
carry one more decimal than the consolidated table (Stage Summary rounds
pad/clean/slurry volume to whole m³ — 00456 stage 1 prints "25" there and
"25.1m³" on its own page), and their labels are unambiguous. The
consolidated Stage Summary is parsed too, and used for two things: it is
the report's own printed stage count (the number this parser is verified
against), and it is the fallback when a file ships the summary without
per-stage pages.

Chemicals only exist on the Chemical Summary, so those are parsed there
and merged onto the stage rows by stage number.

Geometry, not reading order, decides what a value belongs to. On a stage
page the label column is left of x≈660 and the value column right of it;
section headings ("Pressure", "Volume", "Proppant Total") are the bold
spans, and a non-bold label with no value on its own row is the first
line of a two-line proppant name ("Sand - Tier 1" / "30/50"), which is
joined to the line below it.
"""
import csv
import re

import fitz

# --- stage page ------------------------------------------------------

# label -> exported key. Keys deliberately match trican2's where the
# quantity is the same one, so a consumer can stack layout A and layout B
# rows in one frame.
STAGE_FIELDS = {
    ("", "Stage #"): "stage",
    ("", "Depth"): "depth_m",
    ("", "Interval Type"): "interval_type",
    ("", "Hole Volume"): "hole_vol_m3",
    ("", "Interval Date"): "date",
    ("", "Elapsed Time"): "elapsed_time",
    ("", "Start Time"): "start",
    ("", "Pumping Time"): "pumping_time",
    ("PRESSURE", "Average"): "avg_mpa",
    ("PRESSURE", "Maximum"): "max_mpa",
    ("WELLHEAD RATE", "Average"): "rate_avg_m3min",
    ("WELLHEAD RATE", "Maximum"): "rate_max_m3min",
    ("VOLUME", "Acid"): "acid_vol_m3",
    ("VOLUME", "Pad"): "pad_vol_m3",
    ("VOLUME", "Clean"): "clean_vol_m3",
    ("VOLUME", "Slurry"): "slurry_vol_m3",
    ("PROPPANT CONC", "Average"): "conc_avg_kgm3",
    ("PROPPANT CONC", "Maximum"): "conc_max_kgm3",
    ("PROPPANT TOTAL", "Surface"): "proppant_surface_t",
    ("PROPPANT TOTAL", "Downhole"): "proppant_dh_t",
}
TEXT_KEYS = ("interval_type", "date", "elapsed_time", "start",
             "pumping_time")

# Fixed part of the CSV, in print order. Per-mesh proppant and chemical
# columns are file-specific and are appended by columns().
COLUMNS = ["stage", "date", "interval_type", "depth_m", "hole_vol_m3",
           "start", "elapsed_time", "elapsed_min", "pumping_time",
           "pumping_min", "avg_mpa", "max_mpa", "rate_avg_m3min",
           "rate_max_m3min", "acid_vol_m3", "pad_vol_m3", "clean_vol_m3",
           "slurry_vol_m3",
           "conc_avg_kgm3", "conc_max_kgm3", "proppant_surface_t",
           "proppant_dh_t", "proppant_types"]

STAGE_TITLE = re.compile(r"^Stage (\d+)\s*$")


def _slug(s):
    s = re.sub(r"[^0-9A-Za-z]+", "_", s.strip().lower()).strip("_")
    return re.sub(r"_+", "_", s)


def _num(s):
    m = re.search(r"-?[\d,]*\.?\d+", s or "")
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


UNITS = {"L": "l", "kg": "kg", "tonne": "t", "m³": "m3", "m3": "m3",
         "m³/min": "m3min", "kg/m³": "kgm3", "MPa": "mpa", "min": "min"}


def _stage_unit(s):
    """'4.0m³' -> 'm3'; '43.7kg/m³' -> 'kgm3'."""
    m = re.match(r"\s*-?[\d,]*\.?\d+\s*(.*)$", s or "")
    if not m:
        return ""
    u = m.group(1).strip()
    return UNITS.get(u, _slug(u.replace("³", "3")))


def _hms_min(s):
    """'3:00:33' / '1:19:00' -> minutes."""
    m = re.match(r"\s*(\d+):(\d{2}):(\d{2})", s or "")
    if not m:
        return None
    h, mi, se = (int(g) for g in m.groups())
    return round(h * 60 + mi + se / 60.0, 2)


def _spans(page):
    """Non-empty spans as (y0, x0, x1, bold, text), upright.

    Roughly one layout-B report in fourteen (00468-00474, 00960-00962,
    00979 in this corpus) is filed as a portrait page with the landscape
    content rotated 90° inside it — /Rotate is 0, so PyMuPDF's bboxes come
    back sideways even though get_text() reads correctly. Every span here
    is rotated back into reading orientation using the line's own writing
    direction, otherwise the row/column clustering below sees one "row"
    per table column and the page yields nothing.
    """
    w, h = page.rect.width, page.rect.height
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for line in b.get("lines", ()):
            dx, dy = line.get("dir", (1.0, 0.0))
            for s in line.get("spans", ()):
                t = s["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                if dy < -0.7:                    # text runs up the page
                    x0, x1, y0 = h - y1, h - y0, x0
                elif dy > 0.7:                   # text runs down the page
                    x0, x1, y0 = y0, y1, w - x1
                elif dx < -0.7:                  # upside down
                    x0, x1, y0 = w - x1, w - x0, h - y1
                bold = bool(s.get("flags", 0) & 16) or \
                    "bold" in s.get("font", "").lower()
                out.append((y0, x0, x1, bold, t))
    out.sort()
    return out


def detect_stage(page):
    t = page.get_text()
    if not t:
        return False
    first = t.split("\n", 1)[0].strip()
    return bool(STAGE_TITLE.match(first)) and "Hole Volume" in t \
        and "Proppant Total" in t


def parse_stage_page(page):
    """One 'Stage N' page -> row dict.

    Everything below the page banner is a two-column label/value block
    pinned to the right of the page (the left two thirds are a chart
    image). The split is taken from the data itself — the value column
    starts at the smallest x of any span that sits on the same row as,
    and to the right of, a label — rather than from a hard-coded x, so a
    re-flowed template does not silently shift every value one column.
    """
    spans = [s for s in _spans(page) if s[0] > 60]      # drop the banner
    if not spans:
        return {}
    # Rows: cluster spans by y (labels and their values are printed 0.1pt
    # apart, section headings stand alone).
    rows = []
    for y, x0, x1, bold, t in spans:
        if rows and abs(rows[-1][0] - y) <= 3.0:
            rows[-1][1].append((x0, x1, bold, t))
        else:
            rows.append([y, [(x0, x1, bold, t)]])
    for _y, cells in rows:
        cells.sort()

    row, meshes, pending = {}, [], None
    section = ""
    for _y, cells in rows:
        if len(cells) >= 2:
            label = cells[0][3]
            value = "".join(c[3] for c in cells[1:]).strip()
        else:
            x0, x1, bold, t = cells[0]
            if bold:
                section = t.upper()
                pending = None
                continue
            pending = t          # e.g. 'Sand - Tier 1', mesh is next row
            continue
        if pending:
            label = pending + " " + label
            pending = None
        key = STAGE_FIELDS.get((section, label)) or \
            STAGE_FIELDS.get(("", label))
        if key:
            if key in TEXT_KEYS:
                row[key] = re.sub(r"\((?:h|hh|m)[^)]*\)$", "", value).strip()
            else:
                v = _num(value)
                if v is not None:
                    row[key] = v
            continue
        v = _num(value)
        if v is None:
            continue
        if section == "PROPPANT TOTAL":
            meshes.append((label, v))
        else:
            # Never silently drop a printed row: 00396's "Volume / Acid"
            # had no mapped name and used to vanish. Unmapped rows are
            # exported under a name slugged from section, label and unit.
            u = _stage_unit(value)
            row[_slug(section) + "_" + _slug(label) +
                ("_" + u if u else "")] = v
    if meshes:
        row["proppant_types"] = "; ".join(l for l, _v in meshes)
        for label, v in meshes:
            row["prop_" + _slug(label) + "_t"] = v
    # Stage pages print the interval date two-digit ("10/14/24"), the
    # Stage Summary four-digit. Emit one format so a column parsed by the
    # primary path and by the fallback path reads the same.
    d = row.get("date", "")
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", d)
    if m:
        row["date"] = "%s/%s/20%s" % m.groups()
    for src, dst in (("elapsed_time", "elapsed_min"),
                     ("pumping_time", "pumping_min")):
        v = _hms_min(row.get(src))
        if v is not None:
            row[dst] = v
    return row


# --- consolidated tables --------------------------------------------

def _table_rows(page, y_min=55.0):
    """(column centres, data rows) for a Stage/Chemical Summary page.

    A data row is one whose leftmost cell is a bare integer — the stage
    number — which is what separates the body from the two- and
    three-deep stacked header and from the 'Totals' line. Column centres
    are taken from the union of the body's cells so a cell that is blank
    on one row cannot shift the rest of that row left.
    """
    spans = [s for s in _spans(page) if s[0] > y_min]
    rows = []
    for y, x0, x1, bold, t in spans:
        if rows and abs(rows[-1][0] - y) <= 3.0:
            rows[-1][1].append((x0, x1, t))
        else:
            rows.append([y, [(x0, x1, t)]])
    for _y, cells in rows:
        cells.sort()
    body = [(y, c) for y, c in rows
            if c and re.fullmatch(r"\d+", c[0][2]) and len(c) >= 2]
    if not body:
        return [], []
    centres = []
    for _y, cells in body:
        for x0, x1, _t in cells:
            centres.append((x0 + x1) / 2.0)
    centres.sort()
    cols = []
    for c in centres:
        if cols and c - cols[-1][-1] <= 6.0:
            cols[-1].append(c)
        else:
            cols.append([c])
    cols = [sum(g) / len(g) for g in cols]

    top = body[0][0]
    heads = [(y, cells) for y, cells in rows if y < top - 3.0]
    out = []
    for _y, cells in body:
        rec = [""] * len(cols)
        for x0, x1, t in cells:
            c = (x0 + x1) / 2.0
            i = min(range(len(cols)), key=lambda k: abs(cols[k] - c))
            rec[i] = (rec[i] + " " + t).strip()
        out.append(rec)
    return (cols, heads), out


def _head_names(cols, heads):
    """Stack the multi-line header onto the column centres.

    A header cell that straddles two or more column centres is a group
    heading ("Pressure" over Avg|Max, "Proppant Total" over the mesh
    columns) and is dropped: nearest-centre would otherwise glue it onto
    whichever sub-column happened to be closest, which is how the mesh
    column of 00456 came out named "Proppant Total Sand - Tier 1 40/70"
    while its twin was plain "Sand - Tier 1 30/50".
    """
    names = [[] for _ in cols]
    for _y, cells in heads:
        for x0, x1, t in cells:
            if sum(1 for c in cols if x0 <= c <= x1) >= 2:
                continue
            c = (x0 + x1) / 2.0
            i = min(range(len(cols)), key=lambda k: abs(cols[k] - c))
            names[i].append(t)
    return [" ".join(n) for n in names]


def detect_stage_summary(page):
    t = page.get_text()
    return bool(t) and t.split("\n", 1)[0].strip() == "Stage Summary" \
        and "Pumping" in t


def detect_chem_summary(page):
    t = page.get_text()
    return bool(t) and t.split("\n", 1)[0].strip() == "Chemical Summary" \
        and "Stage #" in t


# The Stage Summary's column SET is not fixed: 00396/00397/00398 add a
# "Volume Acid" column and the proppant block is one column per mesh
# actually pumped, so positional column keys shift and silently mislabel
# every column after the insert. Columns are therefore named from the
# stacked header text plus the printed unit, which together disambiguate
# the three "Avg"/"Max" pairs.
SUMMARY_GROUPS = ("Proppant Total", "Proppant Conc.", "Proppant Conc",
                  "WH Rate", "Pressure", "Volume")
SUMMARY_KEYS = {
    ("avg", "mpa"): "avg_mpa", ("max", "mpa"): "max_mpa",
    ("avg", "m3_min"): "rate_avg_m3min", ("max", "m3_min"): "rate_max_m3min",
    ("avg", "kg_m3"): "conc_avg_kgm3", ("max", "kg_m3"): "conc_max_kgm3",
    ("pad", "m3"): "pad_vol_m3", ("clean", "m3"): "clean_vol_m3",
    ("slurry", "m3"): "slurry_vol_m3", ("acid", "m3"): "acid_vol_m3",
    ("hole volume", "m3"): "hole_vol_m3", ("depth", "m"): "depth_m",
    ("surface", "tonne"): "proppant_surface_t",
    ("down hole", "tonne"): "proppant_dh_t",
    ("stage #", ""): "stage", ("interval type", ""): "interval_type",
    ("interval date", "mm_dd_yy"): "date",
    ("elapsed time", "hh_mm_ss"): "elapsed_time",
    ("pumping time", "hh_mm_ss"): "pumping_time",
    ("start time", "hh_mm"): "start",
}


def _split_unit(name):
    """'Pressure Avg (MPa)' -> ('Pressure Avg', 'mpa')."""
    m = re.search(r"\(([^)]*)\)\s*$", name)
    if m:
        return name[:m.start()].strip(), _slug(m.group(1).replace("³", "3"))
    m = re.search(r"(?:^|\s)(kg|L)\s*$", name)
    if m:
        return name[:m.start()].strip(), m.group(1).lower()
    return name.strip(), ""


def _summary_key(name):
    label, unit = _split_unit(name)
    for g in SUMMARY_GROUPS:
        if label.startswith(g):
            label = label[len(g):].strip()
            break
    low = label.lower()
    k = SUMMARY_KEYS.get((low, unit))
    if k:
        return k
    if unit == "tonne":
        return "prop_" + _slug(label) + "_t"
    return _slug(label) + ("_" + unit if unit else "")


def parse_stage_summary(doc):
    """The report's own consolidated table -> list of row dicts."""
    out = []
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect_stage_summary(page):
            continue
        (cols, heads), body = _table_rows(page)
        if not body:
            continue
        keys = [_summary_key(n) for n in _head_names(cols, heads)]
        if keys:
            keys[0] = "stage"       # leftmost column is the stage number
        for rec in body:
            row = {"page": pno + 1}
            for k, v in zip(keys, rec):
                if not v:
                    continue
                if k in TEXT_KEYS:
                    row[k] = v
                else:
                    fv = _num(v)
                    if fv is not None:
                        row[k] = fv
            if "stage" in row:
                row["stage"] = int(row["stage"])
                out.append(row)
    return out


def parse_chem_summary(doc):
    """{stage number: {column key: value}} from the Chemical Summary."""
    out = {}
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect_chem_summary(page):
            continue
        # The chemical summary is a SECOND table, and a page that detects as
        # one without laying out like one returns nothing from _table_rows —
        # which unpacked as "not enough values to unpack" and took the whole
        # DOCUMENT down with it. 00569 prints 102 stages, parses all 102 stage
        # pages, and emitted no table at all because of this; so do 00724 and
        # 00737 at 51 stages each. The chemicals are worth having and are not
        # worth the stage table.
        try:
            (cols, heads), body = _table_rows(page)
        except (ValueError, TypeError, IndexError):
            continue
        if not body:
            continue
        names = _head_names(cols, heads)
        keys = [None]
        for i in range(1, len(cols)):
            nm, unit = _split_unit(names[i])
            nm2, u2 = _split_unit(nm)     # some headers stack name + unit
            if u2 and not unit:
                nm, unit = nm2, u2
            elif u2 == unit:
                nm = nm2
            keys.append("chem_" + _slug(nm) + ("_" + unit if unit else ""))
        for rec in body:
            st = _num(rec[0])
            if st is None:
                continue
            d = out.setdefault(int(st), {})
            for k, v in zip(keys[1:], rec[1:]):
                fv = _num(v)
                if k and fv is not None:
                    d[k] = fv
    return out


# --- cover page ------------------------------------------------------

def detect_cover(page):
    t = page.get_text()
    return bool(t) and t.split("\n", 1)[0].strip() == "Post-Fracturing Report"


def parse_cover(page):
    """Cover page is eight left-aligned lines in fixed order."""
    lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    h = {}
    if len(lines) < 2:
        return h
    m = re.match(r"([^\s(]+)\s*(?:\((.+)\))?$", lines[1])
    if m:
        h["uwi"] = m.group(1)
        if m.group(2):
            h["well"] = m.group(2)
    keys = ["surface", "formation", "completion_type", "job_type",
            "start_date", "finish_date"]
    for k, v in zip(keys, lines[2:]):
        h[k] = v
    return h


# --- document --------------------------------------------------------

def detect(doc):
    """True when this document carries a layout-B Trican post-frac book."""
    for pno in range(len(doc)):
        page = doc[pno]
        if detect_stage(page) or detect_stage_summary(page):
            return True
    return False


def parse_document(path_or_doc):
    doc = path_or_doc if isinstance(path_or_doc, fitz.Document) \
        else fitz.open(path_or_doc)
    header, rows = {}, []
    printed = parse_stage_summary(doc)
    for pno in range(len(doc)):
        page = doc[pno]
        if not header and detect_cover(page):
            header = parse_cover(page)
        if not detect_stage(page):
            continue
        row = parse_stage_page(page)
        m = STAGE_TITLE.match(page.get_text().split("\n", 1)[0].strip())
        if m:
            row["stage"] = int(m.group(1))
        row["page"] = pno + 1
        if "stage" in row:
            rows.append(row)
    # No per-stage pages: fall back on the consolidated table, which
    # carries the same fields one decimal coarser.
    if not rows:
        rows = printed
    chem = parse_chem_summary(doc)
    for r in rows:
        r.update(chem.get(int(r.get("stage", 0)), {}))
    header["printed_stages"] = len(printed)
    rows.sort(key=lambda r: r.get("stage", 0))
    if not isinstance(path_or_doc, fitz.Document):
        doc.close()
    return header, rows


def columns(rows):
    """Fixed columns present, then per-mesh proppant, then chemicals."""
    seen = {k for r in rows for k in r}
    out = [c for c in COLUMNS if c in seen]
    out += sorted(k for k in seen if k.startswith("prop_") and k not in out)
    out += sorted(k for k in seen if k.startswith("chem_"))
    out += sorted(k for k in seen if k not in out and k != "page")
    return out


def write_csv(path, header, rows):
    cols = columns(rows)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["well", header.get("well", ""),
                    "uwi", header.get("uwi", ""),
                    "surface", header.get("surface", ""),
                    "formation", header.get("formation", ""),
                    "job_type", header.get("job_type", ""),
                    "start_date", header.get("start_date", ""),
                    "finish_date", header.get("finish_date", ""),
                    "printed_stages", header.get("printed_stages", "")])
        w.writerow(cols + ["page"])
        for r in rows:
            w.writerow([r.get(c, "") for c in cols] + [r.get("page", "")])
    return len(rows)
