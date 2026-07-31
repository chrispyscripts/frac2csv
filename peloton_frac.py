"""Peloton WellView 'Regulatory Frac Stage Details' parser.

Operator-side report, one page per stage, filed in BC completion reports by
many operators (Trican-pumped PETRONAS wells, Hal-1 docs, etc.). The text
stream is strictly label-then-value, so parsing is a linear walk: a known
label consumes the next line as its value unless that line is itself a
label (blank field).
"""
import csv
import re

import fitz

MARKER = "Regulatory Frac Stage Details"

# A date cell holds a date. WellView leaves one blank when the interval has no
# end recorded, and the parser then read the FOLLOWING row's first cell as the
# value — stage 1 of 00604 ended up with "Pumpdown Volume … Link" where a
# timestamp belongs. The blank-field guard only catches a next line that is
# itself a known label, which a link cell is not.
_DATE_CELL = re.compile(r"^\s*\d{1,4}[/-]\d{1,2}[/-]\d{1,4}(?:\s+\d{1,2}:\d{2})?")

# label -> (csv column, value kind)
FIELDS = {
    "Int#": ("stage", "int"),
    "Start Date": ("start", "date"),
    "End Date": ("end", "date"),
    "Top Depth (mKB)": ("top_depth_m", "num"),
    "Bottom Depth (mKB)": ("bottom_depth_m", "num"),
    "Pre Treat SIP (MPa)": ("pre_treat_sip_mpa", "num"),
    "Instant Shut In Pressure (MPa)": ("isip_mpa", "num"),
    "Volume Clean Total (m³)": ("clean_vol_m3", "num"),
    "Volume Slurry Total (m³)": ("slurry_vol_m3", "num"),
    "Volume N2 Total (m³)": ("n2_vol_m3", "num"),
    "Volume CO2 Total (m³)": ("co2_vol_m3", "num"),
    "Breakdown Pressure (MPa)": ("breakdown_mpa", "num"),
    "Treat Pressure Max (MPa)": ("max_mpa", "num"),
    "Treat Pressure Avg (MPa)": ("avg_mpa", "num"),
    "Treat Pressure Min (MPa)": ("min_mpa", "num"),
    "Slurry Rate Avg (m³/min)": ("rate_avg_m3min", "num"),
    "Slurry Rate Max (m³/min)": ("rate_max_m3min", "num"),
    "Sleeve Shift Pressure (MPa)": ("sleeve_shift_mpa", "num"),
    "Proppant Placed (tonnes)": ("proppant_placed_t", "num"),
    "Proppant Pumped (tonnes)": ("proppant_pumped_t", "num"),
    "Proppant Total (tonnes)": ("proppant_total_t", "num"),
    "BreakDown Gradient (kPa/m)": ("breakdown_gradient_kpam", "num"),
    "Frac Gradient (kPa/m)": ("frac_gradient_kpam", "num"),
}
HEADER_FIELDS = {
    "Well Name:": ("well", "inline"),
    "Bottom Hole UWI": ("bh_uwi", "text"),
    "Surface UWI": ("surface_uwi", "text"),
    "License #": ("licence", "text"),
    "Total Depth (mKB)": ("total_depth_m", "num"),
}
COLUMNS = ["stage", "start", "end", "top_depth_m", "bottom_depth_m",
           "breakdown_mpa", "max_mpa", "avg_mpa", "min_mpa", "isip_mpa",
           "pre_treat_sip_mpa", "sleeve_shift_mpa", "rate_avg_m3min",
           "rate_max_m3min", "clean_vol_m3", "slurry_vol_m3", "n2_vol_m3",
           "co2_vol_m3", "proppant_placed_t", "proppant_pumped_t",
           "proppant_total_t", "breakdown_gradient_kpam", "frac_gradient_kpam"]


def detect(page):
    return MARKER in page.get_text()


def _num(s):
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_page(page):
    lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    labels = set(FIELDS) | {l for l in HEADER_FIELDS if not l.endswith(":")}
    row, header = {}, {}
    i = 0
    while i < len(lines):
        line = lines[i]
        for lab, (col, kind) in HEADER_FIELDS.items():
            if kind == "inline" and line.startswith(lab):
                header[col] = line[len(lab):].strip()
        target = FIELDS.get(line) or \
            (HEADER_FIELDS.get(line) if line in HEADER_FIELDS else None)
        if target:
            col, kind = target
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt in labels:            # blank field
                i += 1
                continue
            if kind == "date":
                if _DATE_CELL.match(nxt):
                    (header if col in [c for c, _ in HEADER_FIELDS.values()]
                     else row)[col] = nxt
                    i += 2
                else:
                    i += 1          # not a date: the field is blank, re-scan
                continue
            if kind == "int":
                v = _num(nxt)
                if v is not None:
                    row[col] = int(v)
            elif kind == "num":
                v = _num(nxt)
                if v is not None:
                    header[col] = v if col in [c for c, _ in HEADER_FIELDS.values()] else None
                    if col in [c for c, _ in FIELDS.values()]:
                        row.setdefault(col, v)
            else:
                (header if col in [c for c, _ in HEADER_FIELDS.values()] else row)[col] = nxt
            i += 2
            continue
        i += 1
    return header, row


def parse_document(path_or_doc):
    doc = path_or_doc if isinstance(path_or_doc, fitz.Document) else fitz.open(path_or_doc)
    header, rows = {}, []
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect(page):
            continue
        h, row = parse_page(page)
        for k, v in h.items():
            if v is not None and v != "":
                header.setdefault(k, v)
        if row.get("stage") is not None:
            row["page"] = pno + 1
            rows.append(row)
    if not isinstance(path_or_doc, fitz.Document):
        doc.close()
    # de-dup (SUBMITTED/PROCESSED copies can repeat stages): keep first per stage
    seen, out = set(), []
    for r in rows:
        if r["stage"] not in seen:
            seen.add(r["stage"])
            out.append(r)
    return header, out


FD_COLS = [
    ("Stg", "stage"), ("Date", "date"), ("Start Time", "start_time"),
    ("Depth", "depth_m"), ("Avg Treat", "avg_mpa"), ("Avg Slurry", "rate_avg_m3min"),
    ("Max\nSlurry", "rate_max_m3min"), ("Proppant SIze", "prop_size"),
    ("Total\nProppant", "proppant_placed_t"), ("Max\nConcentration", "max_conc_kgm3"),
    ("Total\nStage", "stage_vol_m3"),
]


def detect_frac_detail(page):
    t = page.get_text()
    return "Frac Detail" in t and "Avg Treat" in t


def _page_spans(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    x0, y0, x1, y1 = span["bbox"]
                    out.append({"t": t, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def parse_frac_detail(path_or_doc):
    """Span-position parse of the WellView 'Frac Detail' per-stage table
    (handles multi-page continuation; header repeats per page)."""
    import fitz as _f
    doc = path_or_doc if isinstance(path_or_doc, _f.Document) else _f.open(path_or_doc)
    rows = []
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect_frac_detail(page):
            continue
        spans = _page_spans(page)
        # locate header anchors
        anchors = {}
        for key, col in (("Stg", "stage"), ("Avg Treat", "avg_mpa"),
                         ("Avg Slurry", "rate_avg_m3min"),
                         ("Proppant SIze", "prop_size")):
            hit = [s for s in spans if s["t"].startswith(key)]
            if hit:
                anchors[col] = hit[0]
        if "stage" not in anchors or "avg_mpa" not in anchors:
            continue
        header_y = anchors["stage"]["cy"]
        # column x-centers from full header set
        heads = [("stage", "Stg"), ("date", "Date"), ("start_time", "Start Time"),
                 ("depth_m", "Depth"), ("avg_mpa", "Avg Treat"),
                 ("rate_avg_m3min", "Avg Slurry"), ("rate_max_m3min", "Max"),
                 ("prop_size", "Proppant SIze"), ("proppant_placed_t", "Total"),
                 ("max_conc_kgm3", "Max"), ("stage_vol_m3", "Total")]
        # simpler: sort all header-row spans by x, map known sequence
        hdr = sorted([s for s in spans if abs(s["cy"] - header_y) < 30 and s["cy"] >= header_y - 30],
                     key=lambda s: s["cx"])
        # data rows: spans below the header block, clustered by cy
        body = [s for s in spans if s["cy"] > header_y + 25]
        rows_by_y = {}
        for s in body:
            key = round(s["cy"] / 9)
            rows_by_y.setdefault(key, []).append(s)
        import re as _re
        for key in sorted(rows_by_y):
            cells = sorted(rows_by_y[key], key=lambda s: s["cx"])
            vals = [c["t"] for c in cells]
            if len(vals) < 8:
                continue
            if not _re.fullmatch(r"\d{1,3}", vals[0]):
                continue
            if not _re.fullmatch(r"\d{2}-\d{2}-\d{2}", vals[1]):
                continue
            def num(x):
                try:
                    return float(x.replace(",", ""))
                except ValueError:
                    return None
            row = {"stage": int(vals[0]), "date": vals[1], "start_time": vals[2]}
            rest = vals[3:]
            # prop size is the lone non-numeric token in the tail
            nums, prop = [], ""
            for v in rest:
                if _re.search(r"[A-Za-z/]", v) and num(v) is None:
                    prop = (prop + " " + v).strip()
                else:
                    n = num(v)
                    if n is not None:
                        nums.append(n)
            keys = ["depth_m", "avg_mpa", "rate_avg_m3min", "rate_max_m3min",
                    "proppant_placed_t", "max_conc_kgm3", "stage_vol_m3"]
            for k, n in zip(keys, nums):
                row[k] = n
            if prop:
                row["prop_size"] = prop
            row["page"] = pno + 1
            rows.append(row)
    if not isinstance(path_or_doc, _f.Document):
        doc.close()
    # the table repeats cumulatively across daily reports: keep the LAST
    # occurrence of each stage (most complete)
    best = {}
    for r in rows:
        best[r["stage"]] = r
    return [best[k] for k in sorted(best)]


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["well", header.get("well", ""), "bh_uwi", header.get("bh_uwi", ""),
                    "surface_uwi", header.get("surface_uwi", ""),
                    "licence", header.get("licence", "")])
        w.writerow(COLUMNS + ["page"])
        for r in sorted(rows, key=lambda r: r["stage"]):
            w.writerow([r.get(c, "") for c in COLUMNS] + [r.get("page", "")])
    return len(rows)
