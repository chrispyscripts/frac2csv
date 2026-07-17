"""Carmine's Lab API: frac report PDF in, structured data out.

POST /api/extract  { filename, data: base64-pdf }
  -> { stages: [...time-series stages...], tables: [...metric tables...],
       notes: [...] }

Detects and runs every supported template on each document:
  - Leucrotta-style acquisition charts (rotated, per-series colored axes)
  - Halliburton IFS interval charts (Shell/Vermilion/Ovintiv filings)
  - MView charts (Paramount-style)
  - SK 'FracR' text reports (per-stage engineering tables)

Files are processed in memory and never stored.
"""
import base64
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz                    # noqa: E402
import numpy as np             # noqa: E402

import aliases                 # noqa: E402
import canyon                  # noqa: E402
import frac_core as fc         # noqa: E402
import halliburton_ifs as ifs  # noqa: E402
import leucrotta as lc         # noqa: E402
import lib1                    # noqa: E402
import peloton_frac as pel     # noqa: E402
import sk_fracr as sk          # noqa: E402
import trican2                 # noqa: E402

PALETTE = ["#1d5bd8", "#b02e2e", "#1e7a34", "#7a3b9b", "#b0731f", "#0f7d7d",
           "#5a5f6e", "#8a2f5e"]


def _channels_payload(data, units=None, labels=None):
    """Channels normalized through Carmine's alias table: vendor curve
    names become his canonical columns; the raw name survives as the
    label. Unmapped series keep their own name."""
    out = []
    known = {"Tr Press": "#1d5bd8", "Slurry Rate": "#b02e2e",
             "WH Prop Conc": "#1e7a34", "BH Prop Conc": "#7a3b9b"}
    seen = set()
    for i, (key, vals) in enumerate(data.items()):
        canonical = aliases.canon(key)
        col = canonical if canonical and canonical not in seen else key
        seen.add(col)
        unit = (units or {}).get(key) or \
            (aliases.canon_unit(canonical) if canonical else "") or \
            fc.UNITS.get(col, "")
        out.append({
            "key": col,
            "label": (labels or {}).get(key, key),
            "unit": unit,
            "color": known.get(col, PALETTE[i % len(PALETTE)]),
            "values": [None if np.isnan(v) else round(float(v), 4) for v in vals],
        })
    return out


def _stage(kind, meta_dict, samples, channels, source):
    return {"kind": kind, "meta": meta_dict, "n": int(len(samples)),
            "sample_sec": 1.0, "channels": channels, "source": source}


def process_pdf(data, filename):
    doc = fitz.open(stream=data, filetype="pdf")
    stages, tables, notes = [], [], []

    # --- Leucrotta acquisition charts (whole-document, stitched by stage)
    if any(lc.detect(doc[p]) for p in range(len(doc))):
        groups = lc.extract_document(doc)
        for g in groups:
            t0 = g["t0_seconds"]
            start = f"{int(t0 // 3600) % 24:02d}:{int(t0 % 3600 // 60):02d}:{int(t0 % 60):02d}"
            meta = {"title": f"Stage {g['stage']}", "uwi": g["well"],
                    "stage": str(g["stage"]), "date": g["date"],
                    "start_time": start, "duration_min": len(g["samples"]) / 60.0,
                    "warnings": []}
            stages.append(_stage("vector", meta, g["samples"],
                                 _channels_payload(g["data"], g["units"]),
                                 "acquisition chart (Leucrotta-style)"))
        if groups:
            notes.append(f"{len(groups)} stage(s) from acquisition chart pages.")

    # --- per-page templates
    sk_pages = 0
    for pno in range(len(doc)):
        page = doc[pno]
        text = page.get_text()
        if lc.detect(page):
            continue
        if sk.detect(page):
            sk_pages += 1
            continue
        if "(IFS v" in text:
            if re.search(r"Interval\s+\d+\s*[-–]\s*Entire Treatment", text) and \
               len(re.findall(r"\b\d{1,2}:\d{2}\b", text)) >= 3:
                try:
                    meta, samples, data, chinfo = ifs.extract_page(page)
                    md = {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
                          "date": meta.date, "start_time": meta.start_time,
                          "duration_min": meta.duration_min, "warnings": meta.warnings}
                    units = {k: v["unit"] for k, v in chinfo.items()}
                    labels = {k: v["label"] for k, v in chinfo.items()}
                    stages.append(_stage("vector", md, samples,
                                         _channels_payload(data, units, labels),
                                         "Halliburton IFS chart"))
                except Exception as e:
                    notes.append(f"p{pno + 1}: IFS chart failed — {e}")
            continue
        if lib1.detect(page):
            try:
                meta, samples, data, lunits = lib1.extract_page(page)
                md = {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
                      "date": meta.date, "start_time": meta.start_time,
                      "duration_min": meta.duration_min, "warnings": meta.warnings}
                stages.append(_stage("vector", md, samples,
                                     _channels_payload(data, lunits),
                                     "Liberty chart"))
            except Exception as e:
                notes.append(f"p{pno + 1}: Liberty chart failed — {e}")
            continue
        if canyon.detect(page):
            try:
                meta, samples, data, cunits = canyon.extract_page(page)
                md = {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
                      "date": meta.date, "start_time": meta.start_time,
                      "duration_min": meta.duration_min, "warnings": meta.warnings}
                stages.append(_stage("vector", md, samples,
                                     _channels_payload(data, cunits),
                                     "Canyon chart"))
            except Exception as e:
                notes.append(f"p{pno + 1}: Canyon chart failed — {e}")
            continue
        if fc.page_kind(page) == "vector":
            try:
                meta, samples, data = fc.extract_page(page)
                md = {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
                      "date": meta.date, "start_time": meta.start_time,
                      "duration_min": meta.duration_min, "warnings": meta.warnings}
                stages.append(_stage("vector", md, samples,
                                     _channels_payload(data), "MView chart"))
            except Exception as e:
                notes.append(f"p{pno + 1}: vector chart failed — {e}")

    # --- SK text tables (document-level)
    if sk_pages:
        header, rows = {}, []
        for pno in range(len(doc)):
            page = doc[pno]
            if not sk.detect(page):
                continue
            if not header:
                for line in page.get_text().splitlines():
                    m = re.search(r"(.+?)\s+(19[12]/[\d-]+W\d)\s*(\w*)", line)
                    if m:
                        header = {"well": m.group(1).strip(), "uwi": m.group(2),
                                  "formation": m.group(3)}
                        break
            row = sk.parse_page(page)
            if row.get("stage") is not None:
                rows.append(row)
        if rows:
            cols = ["stage", "depth_m", "start", "end", "fluid_rate_m3min",
                    "downhole_rate_m3min"] + [c for c, *_ in sk.FIELDS]
            used = [c for c in cols if any(c in r for r in rows)]
            tables.append({
                "title": f"{header.get('well', filename)} — per-stage engineering data",
                "well": header.get("well", ""), "uwi": header.get("uwi", ""),
                "formation": header.get("formation", ""),
                "columns": used,
                "rows": [[r.get(c, "") for c in used] for r in rows],
            })
            notes.append(f"{len(rows)} stage row(s) parsed from report tables.")

    # --- Peloton WellView reports (Regulatory Frac Stage Details / Frac Detail)
    try:
        ph, preg = pel.parse_document(doc)
    except Exception:
        ph, preg = {}, []
    try:
        pfd = pel.parse_frac_detail(doc)
    except Exception:
        pfd = []
    prows = preg if len(preg) >= len(pfd) else pfd
    if len(prows) >= 2:
        cols = sorted({k for r in prows for k in r if k != "page"},
                      key=lambda c: (c != "stage", c))
        tables.append({
            "title": (ph.get("well") or filename) + " — per-stage engineering data (WellView)",
            "well": ph.get("well", ""), "uwi": ph.get("bh_uwi", ""),
            "formation": "", "columns": cols,
            "rows": [[r.get(c, "") for c in cols] for r in sorted(prows, key=lambda r: r.get("stage", 0))],
        })
        notes.append(f"{len(prows)} stage row(s) parsed from WellView report tables.")

    # --- Trican 'STAGE INFORMATION' reports
    try:
        th, trows = trican2.parse_document(doc)
    except Exception:
        th, trows = {}, []
    if len(trows) >= 2:
        cols = [c for c in trican2.COLUMNS if any(c in r for r in trows)]
        tables.append({
            "title": (th.get("well") or filename) + " — per-stage engineering data (Trican)",
            "well": th.get("well", ""), "uwi": th.get("uwi", ""),
            "formation": "", "columns": cols,
            "rows": [[r.get(c, "") for c in cols] for r in trows],
        })
        notes.append(f"{len(trows)} stage row(s) parsed from Trican stage reports "
                     f"(stages numbered by document order).")

    n_pages = len(doc)
    doc.close()
    if not stages and not tables:
        notes.append(f"No extractable charts or tables found in {n_pages} pages "
                     f"(scanned documents aren't supported here yet).")
    return stages, tables, notes


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(307)
        self.send_header("Location", "/index.html")
        self.end_headers()

    def _send(self, code, obj):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 6_000_000:
                return self._send(413, {"error": "Chunk too large."})
            req = json.loads(self.rfile.read(length))
            data = base64.b64decode(req["data"])
            if data[:5] != b"%PDF-":
                return self._send(422, {"error": "Not a PDF."})
            stages, tables, notes = process_pdf(data, req.get("filename", "file.pdf"))
            self._send(200, {"stages": stages, "tables": tables, "notes": notes})
        except Exception as e:
            self._send(400, {"error": f"{type(e).__name__}: {e}"})
