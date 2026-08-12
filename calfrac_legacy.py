"""Calfrac pre-2024 summary-table extraction (the two legacy layouts).

`calfrac_summary.parse_treatment_summary` only reads the modern zone-major
"Treatment Summary" grid, so everything Calfrac printed before it arrived
with charts but no table at all. There are two older layouts and this module
reads both:

  - 2013-2015 — a per-treatment data sheet titled "Treatment Summary" whose
    first text block is "GENERAL INFORMATION", laid out as labelled panels
    (WELLBORE DATA / PERFORATIONS / TREATMENT DATA > RATES / PRESSURES /
    JOB FLUID VOLUMES / FLUID TANK VOLUMES / PROPPANT / BALL-SEALERS) with a
    "Treatment Summary Details" companion page (CHEMICAL DATA / NITROGEN
    DATA / CO2 DATA / ACID DATA). One sheet per frac treatment, 9-24 sheets
    per well. -> `parse_datasheets`.

  - 2016-2017 — "Multiple Zone Frac Treatment Summary", a zone-major grid
    headed "ZONE #:" shaped much like the modern one: zones across, fields
    down, ten zones to a page, several pages per well.
    -> `parse_multizone`.

GRAIN. Both legacy layouts are emitted ONE ROW PER ZONE — the same grain as
the modern layout, where "zone" is Calfrac's word for one pumped frac stage.
The two zone-major layouts (2016-2017 and modern) print the zone number, so
the row key is the report's own. The 2013-2015 data sheets print no zone or
stage number anywhere, so `Zone` there is the 1-based position of the sheet
in the document. That is the pumping sequence in every file checked: sheet
order runs toe-to-heel, perforation depth decreasing monotonically sheet
over sheet, the same direction the modern grid numbers its zones. Wells with
a re-treat repeat an interval, so `Interval Top (m)` / `Interval Bottom (m)`
/ `Service Order #` / `Job Date` ride on every row as the real join keys.

COLUMN NAMES. A field keeps the label the report prints, except for the ~30
in CANON, which are renamed to the modern grid's column name so the three
layouts stack. Every rename is like-for-like — same measurement, same unit.
Nothing is derived, summed or converted; a cell the report left blank, or
printed as "N/A", is emitted as empty rather than guessed at.
"""
import re

# ---------------------------------------------------------------- helpers

_NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_NULL = {"N/A", "n/a", "NA", "N/a", "-", "--", "None", "none", ".0"}
_UNIT = re.compile(r"^(m³|m|T|t|L|MPa|kPa|kPa/m|kg/m³|m³/min|m³/m|mm|kg/m|kg|"
                   r"kW|Kw|%|°C|hh:mm|scm|scm/min|SCF|e3m3|SG|#|L/m³|m³/m³)$")


def _rows(page, tol=3.0):
    """spans grouped into visual rows by y-centre -> [(y, [(x0, x1, text)])].

    Span-level, not line-level: these forms put a label, its value and its
    unit in three separate spans of one PDF line, and the legacy sheets
    interleave three or four panels across a single row. x1 is kept because
    a value has to be matched to the label immediately left of it, and a
    long label ("Total Tonnage Pumped") starts far further left than a
    short one."""
    runs = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                t = sp["text"].strip()
                if t:
                    bb = sp["bbox"]
                    runs.append(((bb[1] + bb[3]) / 2, bb[0], bb[2], t))
    rows = {}
    for y, x0, x1, t in sorted(runs):
        key = next((k for k in rows if abs(k - y) < tol), y)
        rows.setdefault(key, []).append((x0, x1, t))
    return [(y, _join(sorted(v))) for y, v in sorted(rows.items())]


def _join(cells, gap=0.75):
    """Glue back the cells these sheets shred mid-number. A perforation depth
    is emitted as three touching spans — '3' '698' '.0' — so reading the
    columns literally turned 3698.0 into a depth of 3. Only spans that
    actually abut are joined; every real cell boundary on these forms is
    several points wide."""
    out = []
    for x0, x1, t in cells:
        if out and x0 - out[-1][1] <= gap:
            out[-1] = (out[-1][0], x1, out[-1][2] + t)
        else:
            out.append((x0, x1, t))
    return out


def _clean(v):
    """a printed cell -> the value to store, or None where the report left
    the cell blank or printed a placeholder. '1,730.6' -> '1730.6'."""
    if v is None:
        return None
    v = v.strip()
    if not v or v in _NULL:
        return None
    return v.replace(",", "") if _NUM.match(v) else v


def _named(base, unit):
    return f"{base} ({unit})" if unit else base


# --------------------------------------------- shared canonical vocabulary

# (label the legacy report prints, column name the modern grid uses, unit).
# Matched on the label alone or on the label followed by its unit in
# parentheses, so the 2016-2017 sheet's clipped labels ("Maximum Fluid Rate
# (m³/m") still land. Longest prefix wins, so "Average Rate" beats "Average".
CANON = [
    # identity / interval, common to all three layouts
    ("Job Date", "Job Date", ""),
    ("Service Order #", "Service Order #", ""),
    ("Formation", "Formation", ""),
    ("Formation Treated", "Formation", ""),
    ("Job Type", "Fluid System", ""),
    ("Fluid Type", "Fluid System", ""),
    ("Top Perf", "Interval Top", "m"),
    ("Start Time", "Start Time", "hh:mm"),
    ("Stop Time", "Stop Time", "hh:mm"),
    # rates
    ("Min Fluid Rate", "Slurry Rate Minimum", "m³/min"),
    ("Max Fluid Rate", "Slurry Rate Maximum", "m³/min"),
    ("Average Rate", "Slurry Rate Average", "m³/min"),
    ("Minimum Fluid Rate", "Slurry Rate Minimum", "m³/min"),
    ("Maximum Fluid Rate", "Slurry Rate Maximum", "m³/min"),
    ("Average Fluid Rate", "Slurry Rate Average", "m³/min"),
    # pressures
    ("Breakdown", "Breakdown", "MPa"),
    ("Min Treating", "Minimum", "MPa"),
    ("Max Treating", "Maximum", "MPa"),
    ("Average", "Average", "MPa"),
    ("Minimum Pressure", "Minimum", "MPa"),
    ("Maximum Pressure", "Maximum", "MPa"),
    ("Average Pressure", "Average", "MPa"),
    ("ISIP", "ISIP", "MPa"),
    ("Final Treatment ISIP Press", "ISIP", "MPa"),
    ("Frac Gradient", "Frac Gradient", "kPa/m"),
    # volumes
    ("Pad", "Pad", "m³"),
    ("Proppant", "Proppant", "m³"),
    ("Sweep", "Sweep", "m³"),
    ("Flush", "Flush", "m³"),
    ("TOTAL", "Slurry Total", "m³"),
    ("TOTAL PUMPED", "Slurry Total", "m³"),
    ("TOTAL SLURRY", "Slurry Total", "m³"),
    # proppant mass / power
    ("Total Tonnage Pumped", "Pumped Proppant Total", "T"),
    ("Pumped", "Pumped Proppant Total", "T"),
    ("In Formation", "In Formation Proppant Total", "T"),
    ("KW Used", "Fluid Power", "kW"),
    ("Fluid Power", "Fluid Power", "kW"),
]
_CANON = sorted(CANON, key=lambda e: -len(e[0]))


def _canon(label):
    """printed label (already carrying its unit, if the sheet prints one) ->
    the column name to emit. Case-insensitive: the same row is headed 'TOTAL
    (m³):' on one page of a multiple-zone report and 'Total (m³)' on the
    next."""
    low = label.lower()
    for pref, name, unit in _CANON:
        p = pref.lower()
        if low == p or low.startswith(p + " ("):
            return _named(name, unit)
    return label


def _merge_clipped(order, data):
    """The 2016-2017 sheet clips row labels to the cell width, and the width
    changes page to page, so one field arrives as both '50/140 Domestic
    Proppa' and '50/140 Domestic Proppant (t)' — and 'Fuel Used per Zone (L)'
    on one page is 'Fuel Used Per Zone (L)' on the next. Fold a name into a
    longer one it is a prefix of, and case-variants into one another.

    A name that already ends in its unit is complete, so it is never treated
    as a clipped prefix of something longer; that keeps a genuinely shorter
    field from being swallowed by a longer one that merely starts the same
    way."""
    names = sorted(set(order), key=lambda s: (-len(s), s))
    alias = {}
    for i, short in enumerate(names):
        for long in names[:i]:          # strictly longer, or same length and
            if not long.lower().startswith(short.lower()):   # sorted before
                continue
            if len(long) > len(short) and \
                    (short.endswith(")") or len(short) < 6):
                continue
            alias[short] = long
            break
    if not alias:
        return order, data

    def root(name):                     # aliases only ever point earlier in
        while name in alias:            # `names`, so this cannot loop
            name = alias[name]
        return name

    out_order = []
    for f in order:
        f = root(f)
        if f not in out_order:
            out_order.append(f)
    for vals in data.values():
        for name in [k for k in vals if k in alias]:
            vals.setdefault(root(name), vals.pop(name))
    return out_order, data


def _grid(zone_data, field_order, first=()):
    """{zone -> {field: value}} -> {columns, rows}, zones in numeric order,
    columns that came back empty for every zone dropped."""
    if not zone_data:
        return None
    first = [c for c in first if any(c in v for v in zone_data.values())]
    cols = [f for f in field_order
            if f not in first and any(f in v for v in zone_data.values())]
    rows = []
    for z in sorted(zone_data, key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        v = zone_data[z]
        rows.append([z] + [v.get(f) for f in first] + [v.get(f) for f in cols])
    return {"columns": ["Zone"] + first + cols, "rows": rows}


# ------------------------------ 2016-2017 "Multiple Zone Frac Treatment ..."

_MZ_TITLE = "Multiple Zone Frac Treatment Summary"
# job-level header fields; a zone inherits them from the page it was pumped on
_MZ_IDENT = ["Job Date", "Service Order #", "Program Number"]
_MZ_HEAD = {"Job Date:": "Job Date", "Service Order #:": "Service Order #",
            "Program Number:": "Program Number", "Job Type:": "Fluid System",
            "Well License:": "Well License", "Customer:": "Customer"}
# panel headings: they sit in the label gutter but are not fields, and the
# scribbled annotations that share their row ("150kg") are not zone values
_MZ_SECTION = {"WELL INFORMATION", "TIME INFO", "FLUID/GAS INFO", "SAND INFO",
               "TREATMENT SUMMARY", "CHEMICAL INFO", "CHEMICAL DATA",
               "TREATMENT DATA", "PROPPANT DATA", "GENERAL INFORMATION",
               "TOTAL", "AVERAGE"}
# where the grid ends and the sign-off block begins. The names on that block
# sit right under zone 1's column and would otherwise be read as data.
_MZ_END = re.compile(r"^(REMARKS|C?ustomer Representative|Calfrac Supervisor"
                     r"|Date)\b", re.I)
# the two clock columns, and what a clock has to look like. A zone already
# pumped on an earlier sheet has its time struck out and re-stamped "FRACED"
# on every later reprint, and that is not a time.
_MZ_TIME = ("Start Time (hh:mm)", "Stop Time (hh:mm)")
_TIME = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
# fields every zone column inherits from the page it is printed on rather
# than earning: a row carrying only these was planned, never pumped.
_MZ_INHERITED = {"Job Date", "Service Order #", "Program Number",
                 "Fluid System", "Customer", "Well License"}


def is_multizone_page(page):
    t = page.get_text()
    return _MZ_TITLE in t and "ZONE #" in t and "Calfrac" in t


def _mz_header(rows):
    out = {}
    for _y, cells in rows:
        for i, (_x0, _x1, t) in enumerate(cells):
            if t in _MZ_HEAD and i + 1 < len(cells):
                v = _clean(cells[i + 1][2])
                if v:
                    out.setdefault(_MZ_HEAD[t], v)
    return out


def _parse_multizone_page(page):
    """one multiple-zone page -> (header, {zone label: {column: value}},
    field order) or None."""
    rows = _rows(page)
    hdr = next(((y, c) for y, c in rows
                if any(t.startswith("ZONE #") for _a, _b, t in c)), None)
    if hdr is None:
        return None
    hy, hcells = hdr
    zone_x = [(x0 + x1) / 2 for x0, x1, t in hcells if re.fullmatch(r"\d{1,3}", t)]
    zone_lab = [t for _a, _b, t in hcells if re.fullmatch(r"\d{1,3}", t)]
    if len(zone_x) < 2:
        return None
    # half the column pitch: keeps the TOTAL / AVERAGE column that sits to the
    # right of the last zone out of the last zone's cell
    pitch = min(b - a for a, b in zip(zone_x, zone_x[1:]))
    tol = min(pitch * 0.55, 24.0)
    label_x = min(zone_x) - pitch * 0.75

    def zone_of(x):
        i = min(range(len(zone_x)), key=lambda i: abs(zone_x[i] - x))
        return i if abs(zone_x[i] - x) < tol else None

    out, order = {}, []
    for y, cells in rows:
        if y <= hy + 2:
            continue
        label = " ".join(t for x0, _x1, t in cells if x0 < label_x).strip(" :")
        if _MZ_END.match(label):
            break
        if len(label) < 3 or _NUM.match(label) or label.upper() in _MZ_SECTION:
            continue
        col = _canon(label)
        if col not in order:
            order.append(col)
        for x0, x1, t in cells:
            if x0 < label_x:
                continue
            # A cell wide enough to span two zone centres is free text the
            # operator wrote across the row — the ball sizes scrawled along
            # "Formation Treated" overflow their cells and _join glues the
            # neighbours into one run. It belongs to no single zone, so it is
            # dropped rather than credited to whichever zone its midpoint
            # happens to fall in.
            if sum(1 for zx in zone_x if x0 - 2 <= zx <= x1 + 2) > 1:
                continue
            v = _clean(t)
            if v is None:
                continue
            if col in _MZ_TIME and not _TIME.fullmatch(v):
                continue
            zi = zone_of((x0 + x1) / 2)
            if zi is not None:
                out.setdefault(zone_lab[zi], {}).setdefault(col, v)
    return _mz_header(rows), out, order


def parse_multizone(doc):
    """2016-2017 "Multiple Zone Frac Treatment Summary" -> {columns, rows},
    one row per zone, stitched across the well's pages. None if absent."""
    pages = [doc[p] for p in range(doc.page_count)
             if is_multizone_page(doc[p])]
    if not pages:
        return None
    zone_data, order = {}, []
    for pg in pages:
        parsed = _parse_multizone_page(pg)
        if not parsed:
            continue
        head, zvals, forder = parsed
        for f in forder:
            if f not in order:
                order.append(f)
        for z, vals in zvals.items():
            slot = zone_data.setdefault(z, {})
            # FIRST sheet to print a value wins. Every sheet reprints the
            # whole zone plan, but a zone's measured cells stay blank until
            # it is pumped and are then left alone, so the earliest sheet
            # carrying a value is the one that measured it. Overwriting
            # instead cost 00023 its zones 1-2 start times: they are pumped
            # and timed on p47, and p52 reprints them struck out as "FRACED"
            # with every other cell on those two columns blank.
            for k, v in vals.items():
                slot.setdefault(k, v)
            # every page reprints the whole zone plan, so a zone's job date /
            # service order is the one on the page where it was really pumped
            # — the page that carries a start time for it.
            pumped = "Start Time (hh:mm)" in vals
            for k in _MZ_IDENT:
                if head.get(k):
                    if pumped:
                        slot[k] = head[k]
                    else:
                        slot.setdefault(k, head[k])
    # Drop the zones that were planned and never pumped. Ten zone columns are
    # printed whether or not the well has ten stages, so 00023 — a seven-stage
    # well — otherwise reports zones 8, 9 and 10 carrying nothing but the job
    # date and program number every column inherits from its page header.
    zone_data = {z: v for z, v in zone_data.items()
                 if any(k not in _MZ_INHERITED for k in v)}
    order, zone_data = _merge_clipped(order, zone_data)
    return _grid(zone_data, _MZ_IDENT + order, first=_MZ_IDENT)


# ---------------------------- 2013-2015 per-treatment "GENERAL INFO" sheet

# printed label -> column base name. Numeric unless the label is in _DS_TEXT.
_DS_LABELS = {
    "Calfrac Rep:": "Calfrac Rep", "Time On:": "Time On",
    "Time Off:": "Time Off", "LSD:": "LSD", "Customer:": "Customer",
    "Job Date:": "Job Date", "Job Type:": "Job Type",
    "Program Number:": "Program Number",
    "Service Order #:": "Service Order #",
    "Calfrac Service Line:": "Service Line",
    "BHT": "BHT", "PBTD": "PBTD", "Packers": "Packers", "TVD": "TVD",
    "MD": "MD", "HOLE FILL:": "HOLE FILL",
    "Prg Fluid Rate": "Prg Fluid Rate", "Min Fluid Rate": "Min Fluid Rate",
    "Max Fluid Rate": "Max Fluid Rate", "Average Rate": "Average Rate",
    "Average DH Rate": "Average DH Rate", "N2 Rate": "N2 Rate",
    "Frac Gradient:": "Frac Gradient",
    "Frac Gradient Mini Frac:": "Frac Gradient Mini Frac",
    "Mini Frac/Acid ISIP Press": "Mini Frac/Acid ISIP Press",
    "Final Treatment ISIP Press": "Final Treatment ISIP Press",
    "1 Minute Shut In Press": "1 Minute Shut In Press",
    "Initial Well:": "Initial Well", "Breakdown:": "Breakdown",
    "Average:": "Average", "Max Treating:": "Max Treating",
    "Min Treating:": "Min Treating",
    "On Loc.": "Pump Power On Loc.", "KW Used": "KW Used",
    "Acid": "Acid", "Hole Fill": "Hole Fill", "Spacer": "Spacer",
    "Sweep": "Sweep", "Sweep 1": "Sweep 1", "Sweep 2": "Sweep 2",
    "Pre-Pad": "Pre-Pad", "Pad": "Pad",
    "Proppant 1": "Proppant 1", "Proppant 2": "Proppant 2",
    "Proppant 3": "Proppant 3", "Proppant 4": "Proppant 4",
    "Flush": "Flush", "Flush Density": "Flush Density",
    "TOTAL PUMPED": "TOTAL PUMPED", "TOTAL CLEAN": "TOTAL CLEAN",
    "TOTAL SLURRY": "TOTAL SLURRY",
    "TOTAL CLEAN PUMPED": "TOTAL CLEAN",
    "TOTAL SLURRY PUMPED": "TOTAL SLURRY",
    "Total Tonnage Pumped": "Total Tonnage Pumped",
    "Pre-Job": "Tank Pre-Job", "Post-Job": "Tank Post-Job",
    # "Treatment Summary Details" companion page
    "N2 Rate:": "N2 Rate", "N2 Pumped:": "N2 Pumped",
    "N2 Losses:": "N2 Losses", "Total N2:": "Total N2",
    "N2 Space Factor For Job:": "N2 Space Factor For Job",
    "N2 Space Factor For Flush:": "N2 Space Factor For Flush",
    "CO2 Rate:": "CO2 Rate", "Average CO2:": "Average CO2",
    "CO2 Pumped:": "CO2 Pumped", "CO2 Losses:": "CO2 Losses",
    "Total CO2:": "Total CO2", "Total CO2 Gas:": "Total CO2 Gas",
}
_DS_TEXT = {"Calfrac Rep", "Time On", "Time Off", "LSD", "Customer",
            "Job Date", "Job Type", "Program Number", "Service Order #",
            "Service Line"}
# row labels of the wellbore string table and the side tables: never fields
# themselves, but they must stop a value scan running on past its panel
_DS_STOP = {"Tubing:", "Casing:", "Interm Casing:", "Liner:", "Annulus:",
            "C-Ring", "Type", "Conc", "Total", "Amount", "Name", "Size",
            "No.of Balls", "Weight", "Used", "Losses"}
_DS_INLINE = {"Formation:": "Formation", "Treatment Mode:": "Treatment Mode"}
_DS_PROP_ROWS = {"Pumped", "In Formation", "Initial Conc @ Perfs",
                 "Min Conc @ Perfs", "Final Conc @ Perfs", "Max Conc @ Perfs"}
_DS_PROP_UNIT = {"Pumped": "T", "In Formation": "T"}
# how far right of a label's right edge its value may sit
_DS_GAP = 60.0


def is_datasheet_page(page):
    t = page.get_text()
    return ("GENERAL INFORMATION" in t and "PERFORATIONS" in t
            and "WELLBORE DATA" in t and "TREATMENT DATA" in t
            and "Calfrac" in t)


def is_datasheet_detail_page(page):
    t = page.get_text()
    return ("GENERAL INFORMATION" in t and "Treatment Summary Details" in t
            and "Calfrac" in t)


def _scan_labels(rows, out, ymax=None):
    """label / value / unit triplets, panel by panel, across a sheet's rows."""
    for y, cells in rows:
        if ymax is not None and y > ymax:
            break
        for i, (x0, x1, t) in enumerate(cells):
            for pref, name in _DS_INLINE.items():
                if t.startswith(pref):
                    v = _clean(t[len(pref):])
                    if v:
                        out.setdefault(name, v)
            label = _DS_LABELS.get(t)
            if label is None and t == "Minute SIP" and i and \
                    re.fullmatch(r"\d{1,2}", cells[i - 1][2]):
                label = cells[i - 1][2] + " Minute SIP"
            if label is None:
                continue
            text_valued = label in _DS_TEXT
            val, unit = None, ""
            for vx, _vx1, vt in cells[i + 1:]:
                if vt in _DS_LABELS or vt in _DS_STOP or \
                        vt.split(":")[0] + ":" in _DS_INLINE:
                    break
                if val is None and vx - x1 > _DS_GAP:
                    break
                if val is None:
                    if vt in _NULL:
                        break
                    if _NUM.match(vt) or (text_valued and not _UNIT.match(vt)):
                        val = vt
                    continue
                if _UNIT.match(vt):
                    unit = vt
                break
            v = _clean(val)
            if v is not None:
                out.setdefault(_named(label, unit), v)


def _scan_perforations(rows, out):
    """the PERFORATIONS panel: TOP (m) / BTTM. (m) / SPM, one line per
    perforated interval in the treatment."""
    hdr = next(((y, c) for y, c in rows
                if any(t.startswith("TOP (m") for _a, _b, t in c)), None)
    if hdr is None:
        return
    hy, hc = hdr

    def col(pfx):
        return next((x0 for x0, _x1, t in hc if t.startswith(pfx)), None)

    tx, bx, sx = col("TOP (m"), col("BTTM"), col("SPM")
    if tx is None:
        return
    perfs = []
    for y, cells in rows:
        if y <= hy + 2 or y > hy + 130:
            continue
        got = {}
        for x0, _x1, t in cells:
            if not _NUM.match(t):
                continue
            for key, cx, tol in (("top", tx, 14), ("btm", bx, 16),
                                 ("spm", sx, 16)):
                if cx is not None and abs(x0 - cx) < tol:
                    got.setdefault(key, t.replace(",", ""))
        if "top" in got:
            perfs.append(got)
        elif got:
            break
    if not perfs:
        return
    tops = [float(p["top"]) for p in perfs]
    btms = [float(p.get("btm", p["top"])) for p in perfs]
    out["Interval Top (m)"] = f"{min(tops):g}"
    out["Interval Bottom (m)"] = f"{max(btms):g}"
    out["Perf Intervals"] = str(len(perfs))
    out["Perforations (m)"] = "; ".join(
        p["top"] + ("-" + p["btm"] if "btm" in p else "")
        + (" @" + p["spm"] + "spm" if "spm" in p else "") for p in perfs)


def _scan_proppant(rows, out):
    """the PROPPANT panel: proppant type + mesh across the top, Pumped / In
    Formation / concentration-at-perfs down the side."""
    idx = next((i for i, (_y, c) in enumerate(rows)
                if any(t == "PROPPANT" for _a, _b, t in c)), None)
    if idx is None:
        return
    types = [(x0, t) for x0, _x1, t in rows[idx][1]
             if t != "PROPPANT" and x0 < 400]
    mesh = []
    for _y, cells in rows[idx + 1:idx + 3]:
        cand = [(x0, t) for x0, _x1, t in cells
                if re.fullmatch(r"\d{2,3}/\d{2,3}", t) and x0 < 400]
        if cand:
            mesh = cand
            break
    if not mesh:
        return
    names = []
    for x, m in mesh:
        ty = min(types, key=lambda c: abs(c[0] - x)) if types else None
        names.append(ty[1] + " " + m if ty and abs(ty[0] - x) < 25 else m)
    xs = [x for x, _m in mesh]

    def slot(x):
        i = min(range(len(xs)), key=lambda i: abs(xs[i] - x))
        return i if abs(xs[i] - x) < 25 else None

    for _y, cells in rows[idx + 1:idx + 12]:
        label = next((t for _a, _b, t in cells if t in _DS_PROP_ROWS), None)
        if label is None:
            continue
        unit = _DS_PROP_UNIT.get(label, "kg/m³")
        for x0, _x1, t in cells:
            if not _NUM.match(t):
                continue
            i = slot(x0)
            if i is not None:
                out.setdefault(_named(f"{names[i]} {label}", unit),
                               t.replace(",", ""))


def _scan_chemicals(rows, out):
    """the details page's CHEMICAL DATA table -> per-chemical pumped/total.
    Losses and '# of Pumps' are deliberately left out: only the volume that
    reached the well is comparable with the modern grid's chemical row."""
    hdr = next(((y, c) for y, c in rows
                if any(t == "Chemical Name" for _a, _b, t in c)), None)
    if hdr is None:
        return
    hy, hc = hdr
    cols = {}
    for want in ("Pumped", "Total"):
        x = next((x0 for x0, _x1, t in hc if t == want), None)
        if x is not None:
            cols[want] = x
    if "Pumped" not in cols:
        return
    left = min(x0 for x0, _x1, _t in hc)
    for y, cells in rows:
        if y <= hy + 2 or y > hy + 90:
            continue
        name = " ".join(t for x0, _x1, t in cells
                        if x0 < left - 4 and not _NUM.match(t)).strip()
        if not name or name in _DS_STOP:
            continue
        for key, cx in cols.items():
            v = _clean(next((t for x0, _x1, t in cells
                             if _NUM.match(t) and abs(x0 - cx) < 20), None))
            if v is not None:
                out.setdefault(_named(f"{name} {key}", "L"), v)


def _scan_acid(rows, out):
    """the details page's ACID DATA panel: one acid type and its volume."""
    hdr = next(((y, c) for y, c in rows
                if any(t == "Type" for _a, _b, t in c)
                and any(t == "Amount" for _a, _b, t in c)), None)
    if hdr is None:
        return
    hy, hc = hdr
    tx = next(x0 for x0, _x1, t in hc if t == "Type")
    ax = next(x0 for x0, _x1, t in hc if t == "Amount")
    for y, cells in rows:
        if y <= hy - 12 or y > hy + 40:
            continue
        name = next((t for x0, _x1, t in cells
                     if abs(x0 - tx) < 45 and not _NUM.match(t)
                     and t not in ("Type", "Amount")), None)
        amt = _clean(next((t for x0, _x1, t in cells
                           if _NUM.match(t) and abs(x0 - ax) < 30), None))
        if name and amt:
            out.setdefault("Acid Type", name)
            out.setdefault("Acid Amount (m³)", amt)
            return


def _sheet_ymax(rows):
    """the y where the sheet stops being a form and becomes a chart."""
    for y, cells in rows:
        if any(t == "Surface Conditions" for _a, _b, t in cells):
            return y - 4
    return 500.0


def _parse_datasheet(page):
    rows = _rows(page)
    out = {}
    _scan_labels(rows, out, ymax=_sheet_ymax(rows))
    _scan_perforations(rows, out)
    _scan_proppant(rows, out)
    return out


def _parse_detail(page):
    rows = _rows(page)
    out = {}
    _scan_labels(rows, out)
    _scan_chemicals(rows, out)
    _scan_acid(rows, out)
    text = page.get_text()
    for pat, name in ((r"REMARKS:[ \t]*(.+)", "Remarks"),
                      (r"Customer Representative:[ \t]*(.+)",
                       "Customer Representative"),
                      (r"Calfrac Supervisor:[ \t]*(.+)", "Calfrac Supervisor")):
        m = re.search(pat, text)
        if m and m.group(1).strip():
            out.setdefault(name, m.group(1).strip())
    return out


# columns pushed to the front of every data-sheet row, in this order
_DS_FIRST = ["Job Date", "Service Order #", "Program Number", "Formation",
             "Fluid System", "Interval Top (m)", "Interval Bottom (m)",
             "Perf Intervals", "Perforations (m)"]


def parse_datasheets(doc):
    """2013-2015 per-treatment "GENERAL INFORMATION" data sheets ->
    {columns, rows}, one row per sheet in document order. See the module
    docstring for how `Zone` is assigned. None if absent."""
    sheets, details = [], []
    for p in range(doc.page_count):
        pg = doc[p]
        if is_datasheet_page(pg):
            sheets.append((p, _parse_datasheet(pg)))
        elif is_datasheet_detail_page(pg):
            details.append((p, _parse_detail(pg)))
    if not sheets:
        return None
    # Attach each details page to its sheet: same service order number when
    # that number picks out exactly ONE sheet, otherwise the nearest
    # preceding sheet. A well that runs every stage on a single service
    # order prints the same number on all of its sheets, and matching on it
    # then piled every stage's chemical and nitrogen totals onto stage 1 and
    # left the rest without any.
    by_so, seen = {}, set()
    for _p, s in sheets:
        so = s.get("Service Order #")
        if not so:
            continue
        if so in seen:
            by_so.pop(so, None)
        else:
            seen.add(so)
            by_so[so] = s
    for p, d in details:
        target = by_so.get(d.get("Service Order #"))
        if target is None:
            prev = [s for q, s in sheets if q < p]
            target = prev[-1] if prev else None
        if target is not None:
            for k, v in d.items():
                target.setdefault(k, v)

    zone_data, order = {}, []
    for i, (_p, s) in enumerate(sheets):
        row = {}
        for k, v in s.items():
            col = _canon(k)
            row.setdefault(col, v)
            if col not in order:
                order.append(col)
        zone_data[str(i + 1)] = row
    return _grid(zone_data, _DS_FIRST + order, first=_DS_FIRST)


# ------------------------------------------------------------- entry point

def detect(doc):
    """True when the document prints either legacy Calfrac summary layout.

    This module's OWN gate, so the tables are read whether or not the chart
    side recognised the plots on the same sheets.
    """
    for p in range(doc.page_count):
        page = doc[p]
        if is_multizone_page(page) or is_datasheet_page(page):
            return True
    return False


def parse_legacy(doc):
    """the best per-zone grid a pre-2024 Calfrac document can give: the
    2016-2017 multiple-zone sheet, else the 2013-2015 data sheets."""
    return parse_multizone(doc) or parse_datasheets(doc)
