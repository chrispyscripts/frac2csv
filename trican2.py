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
    ("DH RATE", "Average"): "rate_avg_m3min",
    ("DH RATE", "Minimum"): "rate_min_m3min",
    ("DH CONC", "Maximum"): "conc_max_kgm3",
    ("DH CONC", "Average"): "conc_avg_kgm3",
    ("DH SLURRY VOLUME", "Pad"): "pad_vol_m3",
    ("DH SLURRY VOLUME", "Proppant"): "prop_vol_m3",
    ("FLUID", "Water"): "water_m3",
    ("TIME", "Total Time"): "total_time_min",
}
COLUMNS = ["stage", "start", "finish", "total_time_min", "breakdown_mpa",
           "max_mpa", "avg_mpa", "min_mpa", "isip_mpa", "avg_pad_mpa",
           "avg_prop_mpa", "rate_max_m3min", "rate_avg_m3min", "rate_min_m3min",
           "conc_max_kgm3", "conc_avg_kgm3", "pad_vol_m3", "prop_vol_m3",
           "water_m3", "proppant_t", "proppant_types"]


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
