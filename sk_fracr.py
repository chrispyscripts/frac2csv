"""Saskatchewan frac-report parser (Iron Bird-style 'FracR' documents).

One page per stage: a small chart plus the stage's engineering numbers as
TEXT (pressures incl. ISIP, rates, fluid totals, proppant). Also handles
the 'Complete Job' summary variant. Values are paired to their labels by
line position, since the PDF text stream is scrambled.

Output: one row per stage with every tabulated number — no chart
extraction needed for the summary data.
"""
import csv
import re

import fitz

FIELDS = [
    # (csv column, label text, value regex)
    ("breakdown_mpa",  "Breakdown",       r"([\d,.]+)\s*Mpa"),
    ("max_mpa",        "Maximum",         r"([\d,.]+)\s*Mpa"),
    ("min_mpa",        "Minimum",         r"([\d,.]+)\s*Mpa"),
    ("avg_mpa",        "Average",         r"([\d,.]+)\s*Mpa"),
    ("isip_mpa",       "ISIP",            r"([\d,.]+)\s*Mpa"),
    ("pad_m3",         "Pad",             r"([\d,.]+)\s*m"),
    ("sand_m3",        "Sand",            r"([\d,.]+)\s*m"),
    ("flush_m3",       "Flush",           r"([\d,.]+)\s*m"),
    ("load_fluid_m3",  "Load Fluid",      r"([\d,.]+)\s*m"),
    ("reverse_m3",     "Reverse",         r"([\d,.]+)\s*m"),
    ("surface_conc_kgm3",  "Surface",     r"([\d,.]+)\s*kg/m"),
    ("downhole_conc_kgm3", "Downhole",    r"([\d,.]+)\s*kg/m"),
    ("proppant_pumped_t",  "Pumped",      r"([\d,.]+)\s*tonnes"),
    ("proppant_in_formation_t", "In Formation", r"([\d,.]+)\s*tonnes"),
    ("proppant_placed_pct", "Proppant Placed", r"([\d,.]+)\s*%"),
]


def detect(page):
    t = page.get_text()
    return ("Stage Pressures" in t and "Frac #" in t) or \
           ("Average Frac Pressures" in t and "Complete Job" in t)


def _spans(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    x0, y0, x1, y1 = span["bbox"]
                    out.append({"t": t, "x": x0, "cy": (y0 + y1) / 2})
    return out


def _value_right_of(spans, label, vre, y_tol=4):
    """Value matching vre on the same line, right of (or containing) label."""
    for s in spans:
        if s["t"] == label or s["t"].startswith(label):
            inline = re.search(vre, s["t"])
            if inline:
                return float(inline.group(1).replace(",", ""))
            cands = [c for c in spans if abs(c["cy"] - s["cy"]) <= y_tol
                     and c["x"] > s["x"] and re.search(vre, c["t"])]
            if cands:
                cands.sort(key=lambda c: c["x"])
                return float(re.search(vre, cands[0]["t"]).group(1).replace(",", ""))
    return None


def _rates(spans):
    """Stage Rates block: Fluid / Downhole rows carry m3/min values."""
    out = {}
    for key, label in (("fluid_rate_m3min", "Fluid"), ("downhole_rate_m3min", "Downhole")):
        # 'Downhole' also appears in conc block (kg/m3) — require m³/min
        v = _value_right_of(spans, label, r"([\d,.]+)\s*m³/min")
        if v is not None:
            out[key] = v
    return out


def parse_page(page):
    text = page.get_text()
    spans = _spans(page)
    row = {}
    m = re.search(r"Frac\s*#(\d+):\s*([\d,.]+)\s*m", text)
    if m:
        row["stage"] = int(m.group(1))
        row["depth_m"] = float(m.group(2).replace(",", ""))
    elif "Complete Job" in text:
        row["stage"] = "JOB"
    m = re.search(r"(?:Stage|Total Frac) Time:?\s*\n?(\d{1,2}:\d{2})\s*\n?-\s*\n?(\d{1,2}:\d{2})", text)
    if m:
        row["start"], row["end"] = m.group(1), m.group(2)
    for col, label, vre in FIELDS:
        v = _value_right_of(spans, label, vre)
        if v is not None:
            row[col] = v
    row.update(_rates(spans))
    return row


def parse_document(path):
    doc = fitz.open(path)
    header = {}
    rows = []
    for pno in range(len(doc)):
        page = doc[pno]
        if not detect(page):
            continue
        if not header:
            for line in page.get_text().splitlines():
                m = re.search(r"(.+?)\s+(19[12]/[\d-]+W\d)\s*(\w*)", line)
                if m:
                    header = {"well": m.group(1).strip(), "uwi": m.group(2),
                              "formation": m.group(3)}
                    break
        row = parse_page(page)
        if row.get("stage") is not None:
            row["page"] = pno + 1
            rows.append(row)
    doc.close()
    return header, rows


def write_csv(path, header, rows):
    cols = ["stage", "depth_m", "start", "end", "fluid_rate_m3min",
            "downhole_rate_m3min"] + [c for c, *_ in FIELDS] + ["page"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["well", header.get("well", ""), "uwi", header.get("uwi", ""),
                    "formation", header.get("formation", "")])
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
    return len(rows)
