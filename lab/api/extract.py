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
import frac_core as fc         # noqa: E402
import pipeline                # noqa: E402  shared engine (same as desktop EXE)

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


def _stage(kind, meta_dict, samples, channels, source, page=None, geom=None):
    return {"kind": kind, "meta": meta_dict, "n": int(len(samples)),
            "sample_sec": 1.0, "channels": channels, "source": source,
            "page": page, "geom": geom}


def process_pdf(data, filename):
    """Run the shared extraction engine (same pipeline as the desktop EXE) and
    serialize its results to the Lab's JSON shape. Raster/scanned templates
    (Step-1, Halliburton treatment plots) need the tesseract OCR engine, which
    isn't available on the serverless runtime, so they are skipped here."""
    doc = fitz.open(stream=data, filetype="pdf")
    results, notes = pipeline.extract_document(doc, filename=filename)
    doc.close()

    stages, tables, summary = [], [], []
    for r in results:
        if r["type"] == "series":
            stages.append(_stage("vector", r["meta"], r["samples"],
                                 _channels_payload(r["data"], r.get("units"),
                                                   r.get("labels")),
                                 r["source"], r.get("page"),
                                 r.get("geom")))
        elif r["type"] == "summary":
            summary.extend(r.get("groups", []))
        else:
            tables.append({
                "title": r["title"], "well": r.get("well", ""),
                "uwi": r.get("uwi", ""), "formation": r.get("formation", ""),
                "columns": r["columns"], "rows": r["rows"],
                "source": r.get("source", ""), "page": r.get("page"),
            })
    return stages, tables, notes, summary


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
            stages, tables, notes, summary = process_pdf(
                data, req.get("filename", "file.pdf"))
            self._send(200, {"stages": stages, "tables": tables,
                             "notes": notes, "summary": summary})
        except Exception as e:
            self._send(400, {"error": f"{type(e).__name__}: {e}"})
