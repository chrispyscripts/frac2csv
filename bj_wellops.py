"""BJ / WellView 'DC & Workover - WellOps Regulatory Report' — the
"Stimulation Intervals" section.

BJ completion PDFs bundle the operator's WellView *daily* regulatory report
(one 3-6 page report per operations day, repeated for every day of the job).
Most of those pages are perf/time-log narrative, but the days on which a
treatment was pumped carry a "Stimulation Intervals" section: one block per
frac interval, laid out as a form — label line, then value line — exactly
like the Peloton 'Regulatory Frac Stage Details' report this parser is
modelled on (peloton_frac.py). It is a different report, though: the Peloton
marker never appears in these documents and peloton_frac.parse_document
returns 0 rows on them.

What the section carries that the BJ "Totals" table (bj_summary.parse_totals)
does not:

  - Linked Zone (the geological interval name)
  - Bottom Depth (Totals prints only Top Depth)
  - Treat Pressure Min, Slurry Rate Min
  - BH Conc Max
  - Frac Gradient Post Treat
  - per-fluid Name / Type / Volume  (Totals gives one lumped clean volume)
  - proppant description and sand size
  - the Pad / Proppant / Flush step breakdown with per-step proppant mass

Six more cells are LABELLED in every block and, in every file measured so
far, are printed EMPTY — the operator does not populate them: 5 minute
Shut-In Pressure, BH Breakdown Pressure, Volume Clean Total OR, proppant
Design Amount, per-step BH Proppant Conc Avg, and Comment.  They are parsed
anyway (they cost nothing and a different operator may fill them), but
parse_intervals drops any column that is empty across every row, so a table
built from these documents simply will not carry them.  Do not plan a
design-vs-actual proppant comparison or a 5-minute-SIP series on this report
without checking the fill rate first.

Grain: one row per stimulation interval.

INTERVAL NUMBERING.  The section itself prints no interval number — each
block is headed only "Stage on  YYYY-MM-DD HH:MM", the treatment start.  That
is the same clock the Totals table's "Start time" column prints, so the
interval number is recovered by joining on it (see _totals_index /
assign_intervals); Top Depth is the fallback key and the cross-check.  Rows
that find no Totals row keep a blank interval number instead of being
renumbered — the bundled daily reports usually start part-way into the job,
so the first block in the document is very often NOT interval 1.

Because no identifier is printed, the printed stage suffixes bj1.py now keeps
("6 Plug Slip", "10.1") CANNOT appear here: WellView records one stimulation
block per interval, the treatment that counts, with no qualifier.  Joining a
suffixed chart key to this table therefore has to be done on the numeric head
of the key ("6 Plug Slip" -> 6); the aborted run itself has no row here.
"""
import csv
import re
from datetime import datetime

import fitz

MARKER = "DC & Workover - WellOps Regulatory Report"
SECTION = "Stimulation Intervals"

# heading of the block that opens each interval: "Stage on  2024-03-26 02:35"
_STAGE_ON = re.compile(r"^Stage on\s+(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})\s*$")

# page furniture stripped before the label/value walk
_PAGE_NO = re.compile(r"^Page\s+\d+\s*/\s*\d+\s*$")
_REPORT_NO = re.compile(r"^Report\s*#\s*([\d.]+)\s*,\s*Report Date:\s*(\S+)")
_HEADER_JUNK = (re.compile(r"^www\."), re.compile(r"^Report Printed:"),
                _REPORT_NO, _PAGE_NO)

# section headings that end an interval block. The walk already stops at any
# line that is not a known label, so this list only has to protect the two
# free-text fields from swallowing the heading that follows them.
STOP_HEADINGS = {
    "other in hole", "stimulations summary", "stimulation intervals",
    "perfs", "perforations", "time log", "jobs", "wellbores",
    "casing set depth", "kick offs & key depths", "ops forecast",
    "active rig(s)", "surface legal location", "downhole equipment",
    "tubulars", "formations", "surveys", "pressure tests", "remedial",
}


def _norm(label):
    """Label lookup key: case/space/punctuation-insensitive. WellView prints
    'Instant. Shut-in Pressure' and '5 minute Shut-In Pressure' with vintage-
    dependent capitalisation, and the superscript in (m³) survives text
    extraction but the spacing around it does not."""
    s = re.sub(r"\s+", " ", str(label)).strip().lower()
    return s.replace(".", "").replace(" ", "")


# ---- field maps: normalised label -> (key, kind) ---------------------------
# kinds: num = numeric cell, text = one line (plus continuation lines for the
# fields WellView wraps), int = integer.
STAGE_FIELDS = {
    "Linked Zone": ("linked_zone", "text"),
    "Volume Clean Total OR (m³)": ("clean_vol_or_m3", "num"),
    "Volume Clean Total (m³)": ("clean_vol_m3", "num"),
    "Volume Slurry Total (m³)": ("slurry_vol_m3", "num"),
    "Top Depth (mKB)": ("top_depth_m", "num"),
    "Bottom Depth (mKB)": ("bottom_depth_m", "num"),
    "Breakdown Pressure (MPa)": ("breakdown_mpa", "num"),
    "BH Breakdown Pressure (MPa)": ("bh_breakdown_mpa", "num"),
    "Treat Pressure Min (MPa)": ("min_mpa", "num"),
    "Treat Pressure Avg (MPa)": ("avg_mpa", "num"),
    "Treat Pressure Max (MPa)": ("max_mpa", "num"),
    "Slurry Rate Min (m³/min)": ("rate_min_m3min", "num"),
    "Slurry Rate Avg (m³/min)": ("rate_avg_m3min", "num"),
    "Slurry Rate Max (m³/min)": ("rate_max_m3min", "num"),
    "Instant. Shut-in Pressure (MPa)": ("isip_mpa", "num"),
    "5 minute Shut-In Pressure (MPa)": ("sip5_mpa", "num"),
    "BH Conc Max (kg/m³)": ("bh_conc_max_kgm3", "num"),
    "Frac Gradient Post Treat (kPa/m)": ("frac_gradient_post_kpam", "num"),
    "Comment": ("comment", "text"),
}
FLUID_FIELDS = {
    "Fluid Name": ("name", "text"),
    "Fluid Type": ("type", "text"),
    "Untreated pH (m³/min)": ("untreated_ph", "num"),
    "Volume (m³)": ("volume_m3", "num"),
    "Comment": ("comment", "text"),
}
PROP_FIELDS = {
    "Type": ("type", "text"),
    "Desciption": ("description", "text"),      # WellView's own typo
    "Description": ("description", "text"),
    "Amount (tonnes)": ("amount_t", "num"),
    "Design Amount (tonnes)": ("design_amount_t", "num"),
    "Sand Size": ("sand_size", "text"),
    "Comment": ("comment", "text"),
}
STEP_FIELDS = {
    "Step Number": ("number", "int"),
    "Step Type": ("type", "text"),
    "BH Proppant Conc Avg (kg/m³)": ("bh_conc_avg_kgm3", "num"),
    "Proppant Mass (tonnes)": ("mass_t", "num"),
    "Comment": ("comment", "text"),
}
# group openers: seeing this label starts a new sub-record
_OPENERS = {_norm("Fluid Name"): "fluid", _norm("Type"): "prop",
            _norm("Step Number"): "step"}

_MAPS = {"stage": STAGE_FIELDS, "fluid": FLUID_FIELDS,
         "prop": PROP_FIELDS, "step": STEP_FIELDS}
_NMAPS = {mode: {_norm(k): v for k, v in m.items()} for mode, m in _MAPS.items()}
# every label the walk recognises, in any mode — used for the blank-field
# guard (a label sitting where a value should be means the field is empty)
_ALL_LABELS = set()
for _m in _NMAPS.values():
    _ALL_LABELS |= set(_m)
# which sub-record a label belongs to, for labels that name exactly one of
# them. 'Comment' names all four, so it stays with whatever record is open.
# This is what lets a sub-record survive a blank opener: a proppant whose
# 'Type' cell is empty still starts at 'Desciption' instead of derailing the
# walk and truncating the interval.
_LABEL_MODE = {}
for _mode, _m in _NMAPS.items():
    for _k in _m:
        _LABEL_MODE[_k] = _mode if _k not in _LABEL_MODE else None
_LABEL_MODE = {k: v for k, v in _LABEL_MODE.items() if v}

# how many wrapped continuation lines a text field may absorb. WellView wraps
# long proppant descriptions ('50/140 WHITE SAND\n(OTTAWA TYPE)'); a comment is
# kept to a single line so it cannot eat the heading of the next section.
_CONTINUE = {"description": 3, "linked_zone": 1, "name": 1, "comment": 0}

_NUMBER = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


def _num(s):
    s = str(s).replace(",", "").strip()
    if not _NUMBER.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---- page selection --------------------------------------------------------

def detect(page):
    """True for any page of the bundled WellOps regulatory report."""
    return MARKER in page.get_text()


def detect_intervals(page):
    """True for a page that opens a Stimulation Intervals section."""
    t = page.get_text()
    return MARKER in t and re.search(r"^%s\s*$" % SECTION, t, re.M) is not None


def find_report_pages(doc):
    """1-based page numbers of the bundled WellOps report."""
    return [p + 1 for p in range(doc.page_count) if detect(doc[p])]


# labels that sit next to 'Stim/Treat Company' in the Stimulations Summary
# block; when the company cell is blank the next line is one of these, and
# reading it as the company reported 'Engineer' as a service provider.
_CO_NEIGHBOURS = {"engineer", "starddate", "startdate", "enddate",
                  "stimulationtype", "wellbore", "comment", "stimtreatcompany"}


def service_company(doc):
    """The 'Stim/Treat Company' the report names, e.g. 'BJ Energy' /
    'BJ SERVICES COMPANY'. Provider must be read off the page, never assumed
    from a file index."""
    names = []
    for p in range(doc.page_count):
        t = doc[p].get_text()
        if MARKER not in t:
            continue
        for m in re.finditer(r"Stim/Treat Company\s*\n(.+)", t):
            v = m.group(1).strip()
            k = _norm(v)
            if v and v not in names and k not in _ALL_LABELS \
                    and k not in _CO_NEIGHBOURS:
                names.append(v)
    return names


# ---- text stream -----------------------------------------------------------

def _body_lines(doc):
    """[(line, page1, report_no, report_date, well)] over the WellOps pages,
    with the repeated page furniture removed so a section that runs onto the
    next page reads as one continuous stream."""
    out = []
    for p in range(doc.page_count):
        page = doc[p]
        text = page.get_text()
        if MARKER not in text:
            continue
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        well, rno, rdate = "", "", ""
        i = 0
        if lines and lines[0].startswith(MARKER):
            i = 1
        if i < len(lines) and _PAGE_NO.match(lines[i]):
            i += 1
            if i < len(lines) and not any(r.match(lines[i]) for r in _HEADER_JUNK):
                well = lines[i]
                i += 1
        while i < len(lines):
            m = _REPORT_NO.match(lines[i])
            if m:
                rno, rdate = m.group(1), m.group(2)
                i += 1
                continue
            if any(r.match(lines[i]) for r in _HEADER_JUNK):
                i += 1
                continue
            break
        for l in lines[i:]:
            out.append((l, p + 1, rno, rdate, well))
    return out


# ---- block walk ------------------------------------------------------------

def _parse_block(lines, start):
    """Walk one 'Stage on' block. lines is the plain text list; start indexes
    the heading. -> (record, next_index)."""
    rec = {"start": None, "fluids": [], "proppants": [], "steps": []}
    m = _STAGE_ON.match(lines[start])
    rec["start"] = m.group(1) if m else None
    i = start + 1
    mode, cur = "stage", rec

    def open_group(kind):
        g = {}
        rec[{"fluid": "fluids", "prop": "proppants", "step": "steps"}[kind]].append(g)
        return g

    while i < len(lines):
        line = lines[i]
        if _STAGE_ON.match(line):
            break
        key = _norm(line)
        if key in STOP_HEADINGS:
            break
        opener = _OPENERS.get(key)
        owner = _LABEL_MODE.get(key)
        if opener:
            mode, cur = opener, open_group(opener)
        elif owner == "stage":
            mode, cur = "stage", rec           # fell back out of a sub-record
        elif owner and (owner != mode or
                        _NMAPS[owner][key][0] in cur):
            # a sub-record label arriving out of its group (blank opener) or a
            # field repeating inside one: start the next sub-record of that kind
            mode, cur = owner, open_group(owner)
        elif key not in _NMAPS[mode]:
            break                              # unknown line: block is over
        field = _NMAPS[mode].get(key)
        if field is None:
            break
        col, kind = field
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        nkey = _norm(nxt)
        if not nxt or nkey in _ALL_LABELS or nkey in STOP_HEADINGS \
                or _STAGE_ON.match(nxt):
            i += 1                             # blank field
            continue
        if kind in ("num", "int"):
            v = _num(nxt)
            if v is None:
                i += 1                         # not a number: field is blank
                continue
            cur[col] = int(v) if kind == "int" else v
            i += 2
            continue
        # text (possibly wrapped over the next line or two)
        parts, j = [nxt], i + 2
        for _ in range(_CONTINUE.get(col, 0)):
            if j >= len(lines):
                break
            k = _norm(lines[j])
            if k in _ALL_LABELS or k in STOP_HEADINGS or _STAGE_ON.match(lines[j]):
                break
            parts.append(lines[j])
            j += 1
        cur[col] = re.sub(r"\s+", " ", " ".join(parts)).strip()
        i = j
    return rec, i


# ---- record -> flat row ----------------------------------------------------

def _flatten(rec):
    r = {k: v for k, v in rec.items()
         if k not in ("fluids", "proppants", "steps")}
    fl = [f for f in rec["fluids"] if f]
    pr = [p for p in rec["proppants"] if p]
    st = [s for s in rec["steps"] if s]
    if fl:
        r["fluid_count"] = len(fl)
        r["fluid_names"] = "; ".join(f.get("name", "") for f in fl)
        r["fluid_types"] = "; ".join(f.get("type", "") for f in fl)
        r["fluid_volumes_m3"] = "; ".join(
            _fmt(f.get("volume_m3")) for f in fl)
        vols = [f["volume_m3"] for f in fl if f.get("volume_m3") is not None]
        if vols:
            r["fluid_vol_total_m3"] = round(sum(vols), 2)
    if pr:
        r["proppant_count"] = len(pr)
        r["proppant_types"] = "; ".join(p.get("type", "") for p in pr)
        r["proppant_desc"] = "; ".join(p.get("description", "") for p in pr)
        r["proppant_sizes"] = "; ".join(p.get("sand_size", "") for p in pr)
        amt = [p["amount_t"] for p in pr if p.get("amount_t") is not None]
        des = [p["design_amount_t"] for p in pr
               if p.get("design_amount_t") is not None]
        if amt:
            r["proppant_amount_t"] = round(sum(amt), 3)
        if des:
            r["proppant_design_t"] = round(sum(des), 3)
    if st:
        r["step_count"] = len(st)
        r["steps"] = "; ".join(
            "%s %s%s" % (s.get("number", ""), s.get("type", ""),
                         "" if s.get("mass_t") is None
                         else " " + _fmt(s["mass_t"]) + "t")
            for s in st).strip()
        mass = [s["mass_t"] for s in st if s.get("mass_t") is not None]
        if mass:
            r["step_proppant_mass_t"] = round(sum(mass), 3)
        conc = [s["bh_conc_avg_kgm3"] for s in st
                if s.get("bh_conc_avg_kgm3") is not None]
        if conc:
            r["step_bh_conc_avg_kgm3"] = "; ".join(_fmt(c) for c in conc)
    return r


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return "%g" % v
    return str(v)


# ---- interval numbering (join to the BJ Totals table) ----------------------

_DT_IN = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
          "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S")


def _dtkey(s):
    """'2024-03-26 2:35' and '2024-03-26 02:35' -> the same key."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    for f in _DT_IN:
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return None


def _totals_index(doc):
    """[(interval#, start-datetime key, top_depth)] from the BJ Totals table.
    Read-only use of bj_summary; returns [] when the document has no Totals
    page (some BJ bundles carry the WellOps report and no Totals table)."""
    try:
        import bj_summary
    except ImportError:
        return []
    for p in range(doc.page_count):
        try:
            if not bj_summary.is_totals_page(doc[p]):
                continue
            tab = bj_summary.parse_totals(doc[p])
        except Exception:
            continue
        if not tab or not tab.get("rows"):
            continue
        cols = [str(c) for c in tab["columns"]]

        def ci(pat):
            for j, c in enumerate(cols):
                if re.search(pat, c, re.I):
                    return j
            return None
        c_int, c_start = ci(r"Interval"), ci(r"Start")
        c_top = ci(r"Top\s*Depth")
        if c_int is None or c_start is None:
            continue
        idx = []
        for row in tab["rows"]:
            if c_start >= len(row):
                continue
            k = _dtkey(row[c_start])
            iv = row[c_int] if c_int < len(row) else None
            if iv in (None, ""):
                continue
            top = _num(row[c_top]) if c_top is not None and c_top < len(row) else None
            idx.append((str(iv).strip(), k, top))
        if idx:
            return idx
    return []


def _tdiff_h(a, b):
    """Hours between two _dtkey values, or None if either is unusable."""
    try:
        da = datetime.strptime(a, "%Y-%m-%d %H:%M")
        db = datetime.strptime(b, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None
    return abs((da - db).total_seconds()) / 3600.0


def assign_intervals(rows, index):
    """Stamp each row with the Totals table's interval number.

    Pass 1 matches the treatment start datetime exactly (the two reports print
    the same clock, one zero-padded and one not).  Pass 2 catches the interval
    whose two reports disagree on the clock — the service company's Totals row
    and the operator's daily report can be a few hours apart on the same
    treatment — by matching Top Depth, which is unique per interval in the
    Totals table.  A depth match is only taken when that depth appears exactly
    once on each side and the two start times are within 48 h.

    Rows that match nothing keep interval "": the daily reports bundled in a
    BJ PDF routinely begin part-way into the job (interval 1 is very often
    missing), so renumbering by document order would mislabel every row.
    """
    notes = []
    by_dt = {}
    for iv, k, top in index:
        if k:
            by_dt.setdefault(k, (iv, top))
    used = set()
    for r in rows:
        r["interval"] = ""
        k = _dtkey(r.get("start"))
        hit = by_dt.get(k) if k else None
        if hit and hit[0] not in used:
            r["interval"] = hit[0]
            used.add(hit[0])
            if hit[1] is not None and r.get("top_depth_m") is not None and \
                    abs(hit[1] - r["top_depth_m"]) > 0.5:
                notes.append("interval %s: Totals top depth %.2f m vs WellOps "
                             "%.2f m" % (hit[0], hit[1], r["top_depth_m"]))

    # pass 2 — top depth, for the rows the clock disagreed on
    left = [r for r in rows if not r.get("interval")]
    if left:
        depth_ct = {}
        for _iv, _k, top in index:
            if top is not None:
                depth_ct[round(top, 1)] = depth_ct.get(round(top, 1), 0) + 1
        row_ct = {}
        for r in rows:
            d = r.get("top_depth_m")
            if d is not None:
                row_ct[round(d, 1)] = row_ct.get(round(d, 1), 0) + 1
        for r in left:
            d = r.get("top_depth_m")
            if d is None or depth_ct.get(round(d, 1)) != 1 or \
                    row_ct.get(round(d, 1)) != 1:
                continue
            for iv, k, top in index:
                if top is None or round(top, 1) != round(d, 1) or iv in used:
                    continue
                gap = _tdiff_h(k, _dtkey(r.get("start")) or "") if k else None
                if gap is not None and gap > 48:
                    continue
                r["interval"] = iv
                used.add(iv)
                notes.append(
                    "interval %s matched on top depth %.2f m: Totals starts "
                    "%s, WellOps %s" % (iv, d, k, r.get("start")))
                break
    return notes


# ---- document parse --------------------------------------------------------

def parse_document(path_or_doc):
    """-> (header, rows). One row per stimulation interval, ordered by start
    datetime. Values are floats/strings; missing fields are simply absent."""
    doc = path_or_doc if isinstance(path_or_doc, fitz.Document) \
        else fitz.open(path_or_doc)
    stream = _body_lines(doc)
    lines = [s[0] for s in stream]
    recs = []
    i = 0
    while i < len(lines):
        if _STAGE_ON.match(lines[i]):
            rec, j = _parse_block(lines, i)
            if rec.get("start"):
                rec["page"] = stream[i][1]
                rec["report_no"] = stream[i][2]
                rec["report_date"] = stream[i][3]
                recs.append(rec)
            i = max(j, i + 1)
        else:
            i += 1
    rows = [_flatten(r) for r in recs]

    # A daily report can be re-issued (Report # 8.0 then 8.1) and both copies
    # ride in the same PDF, so the same interval appears twice. Keep the most
    # complete copy of each start datetime, latest report wins a tie.
    best = {}
    for r in rows:
        k = _dtkey(r.get("start")) or r.get("start")
        cur = best.get(k)
        if cur is None or _filled(r) >= _filled(cur):
            best[k] = r
    rows = [best[k] for k in sorted(best, key=lambda k: (k is None, k))]

    header = {}
    well = next((s[4] for s in stream if s[4]), "")
    if well:
        header["well"] = well
    co = service_company(doc)
    if co:
        header["service_company"] = "; ".join(co)
    header["report_pages"] = len(find_report_pages(doc))

    notes = assign_intervals(rows, _totals_index(doc))
    if notes:
        header["notes"] = notes
    unmatched = sum(1 for r in rows if not r.get("interval"))
    if unmatched:
        header["unmatched"] = unmatched
    if not isinstance(path_or_doc, fitz.Document):
        doc.close()
    return header, rows


def _filled(row):
    return sum(1 for v in row.values() if v not in (None, "", []))


# ---- grid form, for the pipeline -------------------------------------------
# (key, display name) in report order. Display names carry the unit, matching
# bj_summary / liberty_summary.
COLUMNS = [
    ("interval", "Interval #"),
    ("start", "Start time"),
    ("linked_zone", "Linked Zone"),
    ("top_depth_m", "Top Depth (m)"),
    ("bottom_depth_m", "Bottom Depth (m)"),
    ("breakdown_mpa", "Breakdown Pressure (MPa)"),
    ("bh_breakdown_mpa", "BH Breakdown Pressure (MPa)"),
    ("min_mpa", "Treat Pressure Min (MPa)"),
    ("avg_mpa", "Treat Pressure Avg (MPa)"),
    ("max_mpa", "Treat Pressure Max (MPa)"),
    ("rate_min_m3min", "Slurry Rate Min (m³/min)"),
    ("rate_avg_m3min", "Slurry Rate Avg (m³/min)"),
    ("rate_max_m3min", "Slurry Rate Max (m³/min)"),
    ("isip_mpa", "Instantaneous Shut-In Pressure (MPa)"),
    ("sip5_mpa", "5 minute Shut-In Pressure (MPa)"),
    ("bh_conc_max_kgm3", "BH Conc Max (kg/m³)"),
    ("frac_gradient_post_kpam", "Frac Gradient Post Treat (kPa/m)"),
    ("clean_vol_m3", "Volume Clean Total (m³)"),
    ("clean_vol_or_m3", "Volume Clean Total OR (m³)"),
    ("fluid_vol_total_m3", "Fluid Volume Total (m³)"),
    ("fluid_names", "Fluid Names"),
    ("fluid_types", "Fluid Types"),
    ("fluid_volumes_m3", "Fluid Volumes (m³)"),
    ("proppant_amount_t", "Proppant Amount (tonnes)"),
    ("proppant_design_t", "Proppant Design Amount (tonnes)"),
    ("proppant_types", "Proppant Type"),
    ("proppant_desc", "Proppant Description"),
    ("proppant_sizes", "Sand Size"),
    ("steps", "Steps (# type mass)"),
    ("step_proppant_mass_t", "Step Proppant Mass Total (tonnes)"),
    ("step_bh_conc_avg_kgm3", "Step BH Proppant Conc Avg (kg/m³)"),
    ("comment", "Comment"),
    ("report_no", "Report #"),
    ("report_date", "Report Date"),
    ("page", "Page"),
]


# the join keys: kept even when blank, so a consumer joining this table to
# the Totals grid always finds the column it expects
_ALWAYS = ("interval", "start")


def parse_intervals(path_or_doc):
    """-> {columns, rows, header} for the Stimulation Intervals section, or
    None. {columns, rows} matches bj_summary.parse_totals / liberty_summary.
    parse_stimulation, so the pipeline can append it as a table directly.
    Columns empty in every row are dropped (six of them always are — see the
    module docstring), except the two join keys."""
    header, rows = parse_document(path_or_doc)
    if not rows:
        return None
    keep = [(k, n) for k, n in COLUMNS
            if k in _ALWAYS or any(r.get(k) not in (None, "", []) for r in rows)]
    grid = [[_fmt(r.get(k)) for k, _n in keep] for r in rows]
    return {"columns": [n for _k, n in keep], "rows": grid, "header": header}


def write_csv(path, header, rows):
    keep = [(k, n) for k, n in COLUMNS]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["well", header.get("well", ""),
                    "service_company", header.get("service_company", "")])
        w.writerow([n for _k, n in keep])
        for r in rows:
            w.writerow([_fmt(r.get(k)) for k, _n in keep])
    return len(rows)
