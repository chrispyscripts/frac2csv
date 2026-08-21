"""Trican 'STAGE INFORMATION' report parser (Trican-2 in Carmine's codes).

One page per stage: Designed vs As-Pumped columns for time, surface
pressures (breakdown/max/avg/min/ISIP), downhole rate/conc, slurry
volumes, fluid, chemicals and proppant. Stage pages carry no stage
number, so stages are numbered sequentially in document order.

ONLY the As-Pumped column is exported. The page lays the two columns out
side by side and cells are routinely blank on one side or the other, so
the columns are told apart by span geometry (each table's "Designed" and
"As Pumped" headers give the cut), not by position in the text stream.
Reading the stream instead — label line, then "the next value line" —
silently promoted a Designed figure to As-Pumped every time the
As-Pumped cell was empty, which is most PROPPANT rows: e.g. 00056 stage 1
pumped 0.17 t of 50/140 but the design table lists 5 t Prime Plus + 20 t
40/70 + 5 t 50/140, and the old reader exported 25.17 t. A blank
As-Pumped cell must stay blank.
"""
import csv
import re
from datetime import date

import fitz

SECTIONS = ("TIME", "SURFACE PRESSURE", "DH RATE", "DH CONC",
            "DH SLURRY VOLUME", "FLUID", "CHEMICAL", "PROPPANT")

FIELD_MAP = {
    ("SURFACE PRESSURE", "Breakdown/Open"): "breakdown_mpa",
    ("SURFACE PRESSURE", "Maximum"): "max_mpa",
    ("SURFACE PRESSURE", "Average"): "avg_mpa",
    ("SURFACE PRESSURE", "Minimum"): "min_mpa",
    ("SURFACE PRESSURE", "ISIP"): "isip_mpa",
    ("SURFACE PRESSURE", "Average Pad"): "avg_pad_mpa",
    ("SURFACE PRESSURE", "Average Proppant"): "avg_prop_mpa",
    ("DH RATE", "Maximum"): "rate_max_m3min",
    # Printed and populated on 137 of 140 stage pages measured, and dropped
    # for want of a key — the section walk only keeps what FIELD_MAP names.
    ("DH RATE", "Average Pad"): "rate_avg_pad_m3min",
    ("DH RATE", "Average"): "rate_avg_m3min",
    ("DH RATE", "Minimum"): "rate_min_m3min",
    ("DH CONC", "Maximum"): "conc_max_kgm3",
    ("DH CONC", "Average"): "conc_avg_kgm3",
    ("DH SLURRY VOLUME", "Pad"): "pad_vol_m3",
    ("DH SLURRY VOLUME", "Proppant"): "prop_vol_m3",
    ("DH SLURRY VOLUME", "Flush/Spacer"): "flush_spacer_m3",
    ("FLUID", "Water"): "water_m3",
    ("TIME", "Total Time"): "total_time_min",
}
COLUMNS = ["stage", "start", "finish", "total_time_min", "breakdown_mpa",
           "max_mpa", "avg_mpa", "min_mpa", "isip_mpa", "avg_pad_mpa",
           "avg_prop_mpa", "rate_max_m3min", "rate_avg_m3min", "rate_min_m3min",
           "rate_avg_pad_m3min", "conc_max_kgm3", "conc_avg_kgm3",
           "pad_vol_m3", "prop_vol_m3", "flush_spacer_m3",
           "water_m3", "proppant_t", "proppant_types"]


def _slug(name):
    """'Sand 50/140' -> 'sand_50_140', 'CRC-C 30/50' -> 'crc_c_30_50'."""
    out = re.sub(r"[^0-9A-Za-z]+", "_", name.strip().lower()).strip("_")
    return out or "x"


def columns_for(rows):
    """The fixed schema, plus whatever per-product columns these rows carry.

    A chemical or a proppant is named by the JOB, not by the template — this
    sample alone prints Busan 94, CC-7, FR-9 and S-2 as additives and six
    different proppants — so they cannot live in a fixed list. They were
    handled by not being emitted at all (chemicals) or by being summed into
    one number and a names string (proppant), which is why a report that
    prints 0.17 t of 50/140 beside 48 t of 40/70 came out as one figure.

    Per-product columns instead, appended in a stable order so two files of
    the same job line up: the fixed schema first, then chemicals, then
    proppants, each alphabetically.
    """
    have = {k for r in rows for k in r}
    fixed = [c for c in COLUMNS if c in have]
    chem = sorted(k for k in have if k.startswith("chem_"))
    prop = sorted(k for k in have if k.startswith("prop_") and k.endswith("_t"))
    return fixed + chem + prop


def detect(page):
    t = page.get_text()
    return "STAGE INFORMATION" in t and "As Pumped" in t


def _num(s):
    m = re.search(r"-?[\d,.]+", s)
    if not m or m.group() in ("-", "."):
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _spans(page):
    """Flat list of non-empty spans as (y0, x0, x1, text)."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for line in b.get("lines", ()):
            for s in line.get("spans", ()):
                t = s["text"].strip()
                if t:
                    x0, y0, x1, _ = s["bbox"]
                    out.append((y0, x0, x1, t))
    return out


def _cuts(spans):
    """Column model for each side-by-side table, as (cut, pitch).

    Trican prints the stage twice over — one table for
    time/pressure/rate/conc, a second for fluid/chemical/proppant — so
    there are normally two. Each pair of "Designed" / "As Pumped"
    headers gives one table: `cut` is the x below which a cell is
    Designed and at/above which it is As-Pumped, and `pitch` (the
    header centres' spacing) is how wide the As-Pumped column runs
    before the next table's Designed column starts.
    """
    hdr = sorted(((x0 + x1) / 2.0, t) for _y, x0, x1, t in spans
                 if t in ("Designed", "As Pumped"))
    out, i = [], 0
    while i < len(hdr) - 1:
        if hdr[i][1] == "Designed" and hdr[i + 1][1] == "As Pumped":
            out.append(((hdr[i][0] + hdr[i + 1][0]) / 2.0,
                        hdr[i + 1][0] - hdr[i][0]))
            i += 2
        else:
            i += 1
    return out


def parse_page(page):
    spans = _spans(page)
    cuts = _cuts(spans)
    if not cuts:
        return {}
    # Each table is walked on its own. The two tables' rows do NOT line up
    # — 00041 p52 puts the CHEMICAL row's FR-9 1.2pt above the SURFACE
    # PRESSURE row's Breakdown/Open — so one shared row grid mis-pairs
    # them, and the right table's Designed column would be read as the
    # left table's As-Pumped value.
    cells = []               # (section, label, [as-pumped span texts])
    for n, (cut, pitch) in enumerate(cuts):
        prev = cuts[n - 1][0] if n else -1e9
        heads, vals = [], []
        for y, x0, x1, t in spans:
            if t in ("Designed", "As Pumped"):
                continue
            if prev <= x1 < cut:             # label / section heading
                heads.append((y, t))
            elif cut <= x0 < cut + pitch:    # As-Pumped cell
                vals.append((y, x0, t))
        vals.sort()
        section = None
        for y, t in sorted(heads):
            if t.upper() in SECTIONS:
                section = t.upper()
            elif t.endswith(":") and section:
                cell = [section, t[:-1].strip(),
                        [vt for vy, _vx, vt in vals if abs(vy - y) <= 3.0]]
                cells.append(cell)

    row = {}
    prop_t = 0.0
    prop_types = []
    for sec, label, parts in cells:
        pumped = "".join(parts).strip()
        if not pumped or pumped in ("-", "–", "—"):
            continue           # blank As-Pumped cell stays blank
        if sec == "TIME":
            if label == "Start Time":
                row["start"] = pumped
            elif label == "Finish Time":
                row["finish"] = pumped
            elif label == "Total Time":
                v = _num(pumped)
                if v:
                    row["total_time_min"] = v
        elif sec == "PROPPANT":
            v = _num(pumped)
            if v is not None and "tonne" in pumped:
                prop_t += v
                prop_types.append(label)
                # ...and keep the product's OWN tonnage. The sum and the names
                # string stay exactly as they were, so nothing downstream that
                # reads them changes; this only adds the split they hide.
                row[f"prop_{_slug(label)}_t"] = v
        elif sec == "CHEMICAL":
            # Every additive row measured is populated on every stage page —
            # 141 of 141, four products — and not one of them reached the
            # output, because the section had no FIELD_MAP entry and the walk
            # keeps only what FIELD_MAP names.
            v = _num(pumped)
            if v is not None:
                row[f"chem_{_slug(label)}_l"] = v
        else:
            key = FIELD_MAP.get((sec, label))
            if key:
                v = _num(pumped)
                if v is not None:
                    row[key] = v
    if prop_t:
        row["proppant_t"] = round(prop_t, 2)
        row["proppant_types"] = "; ".join(prop_types)
    return row


def parse_document(path_or_doc):
    doc = path_or_doc if isinstance(path_or_doc, fitz.Document) else fitz.open(path_or_doc)
    header, rows = {}, []
    n = 0
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect(page):
            continue
        text = page.get_text()
        if not header:
            m = re.search(r"(\d{5})\s*:\s*(1[0-9A-F]\d/[\d-]+W\d/\d\d)", text)
            if m:
                header["wa"] = m.group(1)
                header["uwi"] = m.group(2)
            m = re.search(r"SERVICE ORDER #:\s*(\d+)", text)
            if m:
                header["service_order"] = m.group(1)
            m = re.search(r"([A-Z][A-Z .&-]+HZ[A-Z0-9 .-]+?)\s+WA\s+\d{5}", text)
            if m:
                header["well"] = " ".join(m.group(1).split())
        n += 1
        row = parse_page(page)
        row["stage"] = n            # pages carry no stage id; document order
        row["page"] = pno + 1
        rows.append(row)
    if not isinstance(path_or_doc, fitz.Document):
        doc.close()
    return header, rows


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["well", header.get("well", ""), "uwi", header.get("uwi", ""),
                    "wa", header.get("wa", ""), "service_order",
                    header.get("service_order", "")])
        w.writerow(COLUMNS + ["page"])
        for r in rows:
            w.writerow([r.get(c, "") for c in COLUMNS] + [r.get("page", "")])
    return len(rows)


# ---------------------------------------------------------------- the clock

_START_RE = re.compile(
    r"([A-Z][a-z]{2})\s+(\d{1,2})\s*,\s*(\d{1,2}):(\d{2})\s*([AP])\.?M\.?",
    re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec"]
# Dates the report prints about ITSELF — licence, submission, expiry. They are
# not the job, but they bracket it, which is all the year needs. See _year_for.
_DOC_DATE = re.compile(r"\b(20[0-2]\d)-(\d{2})-(\d{2})\b")
_DOC_DATE_MON = re.compile(r"\b(20[0-2]\d)-([A-Z]{3})-(\d{1,2})\b")


def _parse_start(text):
    """'Feb 10, 10:09 AM' -> (month, day, hour, minute), or None.

    These cells carry no year — measured across every STAGE INFORMATION page
    of the sample, not one prints a 4-digit year anywhere on it.
    """
    m = _START_RE.search(text or "")
    if not m:
        return None
    mon = _MONTHS.index(m.group(1).lower()[:3]) + 1
    day, hh, mm = int(m.group(2)), int(m.group(3)), int(m.group(4))
    if m.group(5).upper() == "P" and hh != 12:
        hh += 12
    elif m.group(5).upper() == "A" and hh == 12:
        hh = 0
    if not (1 <= day <= 31 and hh <= 23 and mm <= 59):
        return None
    return mon, day, hh, mm


def document_dates(doc, pages=6):
    """Every full date the report prints about itself, in its first pages.

    Both spellings occur, sometimes on the same sheet: 2021-01-12 on the
    completion form and 2021-JAN-11 in the licence block.
    """
    out = []
    for pno in range(min(pages, len(doc))):
        text = doc[pno].get_text()
        for m in _DOC_DATE.finditer(text):
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        for m in _DOC_DATE_MON.finditer(text):
            mon = m.group(2).lower()[:3]
            if mon in _MONTHS:
                out.append(date(int(m.group(1)), _MONTHS.index(mon) + 1,
                                int(m.group(3))))
    return sorted(set(out))


def _year_for(mon, day, doc_dates):
    """The year that puts this month/day inside the report's own date span.

    The STAGE INFORMATION table prints "Feb 10, 10:09 AM" and no year, so one
    has to come from somewhere. The report is full of dates about itself —
    licence issue, submission, expiry — and they are NOT the job, but a
    completion report is written around the job it describes, so the job falls
    inside their span. Measured on the sample: 00005 prints 2019-JAN-11 to
    2019-APR-30 and its first stage is Feb 10; 00156 prints 2019-OCT-19 to
    2020-JAN-30 for a Nov 14 start, which is the case a naive "use the
    filing year" rule gets wrong in the other direction; 00317 prints
    2021-JAN-11 to 2021-MAR-17 for Jan 19.

    So try each year the report mentions, and keep the one landing nearest the
    middle of that span. A span crossing New Year is handled by construction —
    both years are candidates and the nearer one wins. Returns None when the
    report prints no date at all, and the caller then has no year rather than
    a guessed one.
    """
    if not doc_dates:
        return None
    years = sorted({d.year for d in doc_dates}
                   | {d.year - 1 for d in doc_dates})
    lo, hi = doc_dates[0], doc_dates[-1]
    mid = date.fromordinal((lo.toordinal() + hi.toordinal()) // 2)
    best, best_d = None, None
    for y in years:
        try:
            cand = date(y, mon, day)
        except ValueError:
            continue                    # Feb 29 in a non-leap year
        dist = abs(cand.toordinal() - mid.toordinal())
        if best_d is None or dist < best_d:
            best, best_d = y, dist
    return best


def stage_clock(doc):
    """-> {stage number: {'date': 'YYYY-MM-DD'|'', 'start': 'HH:MM:SS'}}.

    Layout A prints, per stage, a chart page followed by its STAGE INFORMATION
    page, and that table's As-Pumped "Start Time" is when the stage was pumped.
    The chart itself is read for elapsed minutes only, so without this the
    whole template exports with no date and no clock: measured, 0 of 39 stages
    on 00005 and 0 of 28 on 00317.

    The join is stage number to stage number, and it is the data that says so
    rather than the page order. These charts are cut out of ONE job-long
    elapsed clock, so the gap between two charts' origins should equal the gap
    between the same two rows' Start Times — and it does, to the minute, for
    every stage from the second on: 00317's 27 stages agree within a constant
    306 min and 00156's 34 within 135 min, the constant being stage 1 alone,
    whose chart window opens partway through a long first stage rather than at
    its start. Stage 1 is exactly the stage a page-order join would get right
    and a data join reveals as different, which is why the offset is quoted
    from stage 2.

    NOT usable as a cross-check on every file: 00005's elapsed axis restarts
    mid-job (stages 17 and 22 both report origin 0), so the shared-clock
    identity holds per run of stages there, not across the document.
    """
    _hdr, rows = parse_document(doc)
    if not rows:
        return {}
    doc_dates = document_dates(doc)
    out = {}
    for r in rows:
        got = _parse_start(r.get("start"))
        if not got:
            continue
        mon, day, hh, mm = got
        y = _year_for(mon, day, doc_dates)
        out[r["stage"]] = {
            "date": f"{y:04d}-{mon:02d}-{day:02d}" if y else "",
            "start": f"{hh:02d}:{mm:02d}:00",
        }
    return out
