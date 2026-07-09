"""Vercel serverless function: extract frac chart data from an uploaded file.

POST JSON: { filename, data (base64), fallback: {duration, pmax, ratemax,
concmax, uwi, stage, date}, sample_sec }
Returns JSON: { stages: [ {kind, meta, n, sample_sec, channels: [...]}, ... ],
notes: [...] }

Files are processed entirely in memory and never written to disk.
"""
import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

import fitz
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frac_core as fc          # noqa: E402
import raster_core as rc        # noqa: E402

MAX_PAGES = 8          # per request
MAX_RASTER_PAGES = 4   # pixel tracing is the slow path

CHANNEL_STYLE = {
    "Tr Press": ("Treating Pressure", "MPa", "#1d5bd8"),
    "Slurry Rate": ("Slurry Rate", "m3/min", "#c8372d"),
    "WH Prop Conc": ("Prop Conc @ Blender (WH)", "kg/m3", "#1e7a34"),
    "BH Prop Conc": ("Prop Conc @ Formation (BH)", "kg/m3", "#7a3b9b"),
}
IMAGE_TYPES = {"png", "jpg", "jpeg", "bmp", "tif", "tiff"}


def _fallback_meta(fb):
    meta = fc.PageMeta(uwi=str(fb.get("uwi", "") or ""),
                       stage=str(fb.get("stage", "") or ""),
                       date=str(fb.get("date", "") or ""))
    def num(k, d):
        try:
            return float(fb.get(k, d) or d)
        except (TypeError, ValueError):
            return d
    meta.duration_min = num("duration", 80.0)
    meta.pressure_max = num("pmax", 90.0)
    meta.rate_max = num("ratemax", 18.0)
    meta.conc_max = num("concmax", 900.0)
    return meta


def _stage_payload(kind, meta, samples, data, sample_sec, quality=None):
    channels = []
    for key, (label, unit, color) in CHANNEL_STYLE.items():
        if key not in data:
            continue
        q = quality.get(key) if quality else None
        channels.append({
            "key": key, "label": label, "unit": unit, "color": color,
            "values": [None if np.isnan(v) else round(float(v), 4) for v in data[key]],
            "gaps": [[round(a, 1), round(b, 1)] for a, b in q.gaps] if q else [],
            "overlaps": [[round(a, 1), round(b, 1), o] for a, b, o in q.overlaps] if q else [],
            "caveats": q.caveats() if q else [],
        })
    return {
        "kind": kind,
        "meta": {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
                 "date": meta.date, "duration_min": meta.duration_min,
                 "warnings": meta.warnings},
        "n": int(len(samples)), "sample_sec": float(sample_sec),
        "channels": channels,
    }


def _extract_raster_img(img, meta, sample_sec):
    fullscale = {"pressure": meta.pressure_max, "rate": meta.rate_max,
                 "conc": meta.conc_max}
    samples, data, quality = rc.trace(img, meta.duration_min, fullscale,
                                      sample_sec=sample_sec)
    return _stage_payload("raster", meta, samples, data, sample_sec, quality)


def sniff_type(data, filename):
    """Identify the file by content (magic bytes), not extension."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:2] == b"BM":
        return "bmp"
    return None


def extract_bytes(data, filename, fallback, sample_sec=1.0):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    stages, notes = [], []

    real = sniff_type(data, filename)
    if real is None:
        raise ValueError("unrecognized file content — expected a PDF or a "
                         "PNG/JPG/TIFF/BMP image")
    expected = "pdf" if ext == "pdf" else ("jpeg" if ext in ("jpg", "jpeg") else ext)
    if ext and expected != real:
        notes.append(f"Note: file is named .{ext} but its content is "
                     f"{real.upper()} — processing as {real.upper()}.")
    if real != "pdf":
        # Pixmap(stream) decodes at native pixel size; get_pixmap() on an
        # image document would downscale DPI-tagged files (e.g. 300-dpi
        # scans render at 24% resolution and the trace quality collapses)
        img = rc.pixmap_to_array(fitz.Pixmap(data))
        meta = _fallback_meta(fallback)
        notes.append(f"Detected input type: raster {real.upper()} image "
                     f"({img.shape[1]}x{img.shape[0]} px) — pixel tracing "
                     "(axis scales from the fallback settings).")
        stages.append(_extract_raster_img(img, meta, sample_sec))
        return stages, notes

    doc = fitz.open(stream=data, filetype="pdf")
    if len(doc) > MAX_PAGES:
        notes.append(f"Document has {len(doc)} pages; processing the first "
                     f"{MAX_PAGES} (split the PDF for the rest).")
    raster_done = 0
    for pno in range(min(len(doc), MAX_PAGES)):
        page = doc[pno]
        try:
            if fc.page_kind(page) == "vector":
                n_seg = sum(len(d["items"]) for d in page.get_drawings()
                            if d.get("color") in fc.SERIES)
                meta, samples, chans = fc.extract_page(page, sample_sec=sample_sec)
                notes.append(f"Page {pno + 1}: VECTOR chart — {n_seg:,} curve "
                             f"segments in series colors; lossless geometry.")
                stages.append(_stage_payload("vector", meta, samples, chans, sample_sec))
            else:
                if raster_done >= MAX_RASTER_PAGES:
                    notes.append(f"Page {pno + 1}: raster page skipped "
                                 f"(max {MAX_RASTER_PAGES} raster pages per request).")
                    continue
                raster_done += 1
                meta = _fallback_meta(fallback)
                meta = fc.detect_text_meta(page, meta)
                notes.append(f"Page {pno + 1}: no vector curve geometry on this page "
                             f"— raster/flattened PDF, pixel tracing "
                             f"(reduced fidelity; see flagged spans).")
                img = rc.pixmap_to_array(page.get_pixmap(dpi=300))
                stages.append(_extract_raster_img(img, meta, sample_sec))
        except Exception as e:  # keep other pages alive
            notes.append(f"Page {pno + 1}: skipped — {e}")
    return stages, notes


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # the catch-all function route swallows "/" — send it to the static page
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
                return self._send(413, {"error": "File too large (3 MB max)."})
            req = json.loads(self.rfile.read(length))
            data = base64.b64decode(req["data"])
            stages, notes = extract_bytes(
                data, req.get("filename", "upload.pdf"),
                req.get("fallback", {}) or {},
                float(req.get("sample_sec", 1.0) or 1.0))
            if not stages:
                return self._send(422, {"error": "No extractable chart found.",
                                        "notes": notes})
            self._send(200, {"stages": stages, "notes": notes})
        except Exception as e:
            self._send(400, {"error": f"{type(e).__name__}: {e}"})
