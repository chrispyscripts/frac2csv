"""Trican 'STAGE INFORMATION' report parser (Trican-2 in Carmine's codes).

One page per stage: Designed vs As-Pumped columns for time, surface
pressures (breakdown/max/avg/min/ISIP), downhole rate/conc, slurry
volumes, fluid, chemicals and proppant. Values are label-line then
as-pumped-line in the text stream. Stage pages carry no stage number, so
stages are numbered sequentially in document order.
"""
import csv
import re

import fitz

VAL = re.compile(r"^-?[\d,.]+\s*(MPa|m³/min|kg/m³|m³|min|tonne|L|kg|%)\s*$")
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


def parse_page(page):
    lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    row = {}
    section = None
    prop_t = 0.0
    prop_types = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.upper() in SECTIONS:
            section = line.upper()
            i += 1
            continue
        m = re.match(r"(.+?):\s*(.*)$", line)
        if m and section:
            label, designed = m.group(1).strip(), m.group(2).strip()
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            pumped = None
            if VAL.match(nxt) or re.match(r"^[A-Z][a-z]{2} \d{1,2},", nxt):
                pumped = nxt
                i += 1
            val_src = pumped if pumped is not None else designed
            if section == "TIME":
                if label == "Start Time" and pumped:
                    row["start"] = pumped
                elif label == "Finish Time" and pumped:
                    row["finish"] = pumped
                elif label == "Total Time":
                    v = _num(val_src)
                    if v: row["total_time_min"] = v
            elif section == "PROPPANT":
                v = _num(val_src)
                if v is not None and "tonne" in val_src:
                    prop_t += v
                    prop_types.append(label)
            else:
                key = FIELD_MAP.get((section, label))
                if key:
                    v = _num(val_src)
                    if v is not None:
                        row[key] = v
        i += 1
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
