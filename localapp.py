#!/usr/bin/env python3
"""Frac2CSV local app — the web Lab UI running against the local engine.

Serves the SAME lab/public/index.html the web version uses (identical
layout), backed by a 127.0.0.1-only server with direct disk access:

  - raster/scanned templates work (local tesseract), unlike the web
  - TXT drive lists resolve server-side — no folder picker, any browser
  - exports write straight into each PDF's own folder
  - no upload chunking; original-chart pages served from disk

This is the desktop entrypoint frozen into the Windows EXE.
"""
import base64
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "_MEIPASS", None):          # PyInstaller onefile
    PUBLIC = os.path.join(sys._MEIPASS, "lab", "public")
else:
    PUBLIC = os.path.join(HERE, "lab", "public")
sys.path.insert(0, HERE)

import fitz                     # noqa: E402
import numpy as np              # noqa: E402

import aliases                  # noqa: E402
import pipeline                 # noqa: E402
import pipeline_export as pe    # noqa: E402

PALETTE = ["#1d5bd8", "#b02e2e", "#1e7a34", "#7a3b9b", "#b0731f", "#0f7d7d",
           "#5a5f6e", "#8a2f5e"]
KNOWN = {"Tr Press": "#1d5bd8", "Slurry Rate": "#b02e2e",
         "WH Prop Conc": "#1e7a34", "BH Prop Conc": "#7a3b9b"}

# paths the client may read back (Original chart) — filled by manifest and
# process-path requests so /api/file can't be pointed anywhere else
ALLOWED_FILES = set()


def _channels_payload(data, units=None, labels=None):
    out, seen = [], set()
    for i, (key, vals) in enumerate(data.items()):
        canonical = aliases.canon(key)
        col = canonical if canonical and canonical not in seen else key
        seen.add(col)
        unit = (units or {}).get(key) or \
            (aliases.canon_unit(canonical) if canonical else "") or ""
        out.append({
            "key": col,
            "label": (labels or {}).get(key, key),
            "unit": unit,
            "color": KNOWN.get(col, PALETTE[i % len(PALETTE)]),
            "values": [None if (v is None or not np.isfinite(v))
                       else round(float(v), 4) for v in vals],
        })
    return out


def serialize(results, notes):
    stages, tables = [], []
    for r in results:
        if r["type"] == "series":
            stages.append({
                "kind": "vector", "meta": r["meta"],
                "n": int(len(r["samples"])), "sample_sec": 1.0,
                "channels": _channels_payload(r["data"], r.get("units"),
                                              r.get("labels")),
                "source": r["source"], "page": r.get("page"), "geom": r.get("geom"),
            })
        else:
            tables.append({
                "title": r["title"], "well": r.get("well", ""),
                "uwi": r.get("uwi", ""), "formation": r.get("formation", ""),
                "columns": r["columns"], "rows": r["rows"],
                "source": r.get("source", ""),
            })
    return stages, tables, notes


def process_bytes(data, filename):
    doc = fitz.open(stream=data, filetype="pdf")
    results, notes = pipeline.extract_document(doc, filename=filename)
    doc.close()
    return serialize(results, notes)


def process_path(path, fmt="both", tabs=True, seq=False):
    doc = fitz.open(path)
    results, notes = pipeline.extract_document(
        doc, filename=os.path.basename(path))
    doc.close()
    stages, tables, notes = serialize(results, notes)

    series = [r for r in results if r["type"] == "series"]
    written = []
    folder = os.path.dirname(path)
    base = os.path.splitext(os.path.basename(path))[0]
    if series:
        model = pe.build_well(series, fallback_uwi=pe.filename_uwi(
            os.path.basename(path)), seq=seq)
        if fmt != "xlsx":
            with open(os.path.join(folder, base + ".csv"), "w",
                      newline="") as f:
                f.write(pe.well_csv(model))
            written.append(base + ".csv")
        if fmt != "csv":
            with open(os.path.join(folder, base + ".xlsx"), "wb") as f:
                f.write(pe.well_xlsx(model, tabs))
            written.append(base + ".xlsx")
    for i, t in enumerate(r for r in results if r["type"] == "table"):
        nm = base + ("-stages-table.csv" if i == 0
                     else f"-stages-table-{i + 1}.csv")
        import csv as _csv
        with open(os.path.join(folder, nm), "w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(t["columns"])
            for row in t["rows"]:
                w.writerow(row)
        written.append(nm)
    return stages, tables, notes, written


_ROOT_CACHE = {}


def find_drive_roots(manifest_path):
    """Locate the manifest path's top folder (e.g. 'BCER-Frac') on any
    mounted volume (mac) or drive letter (windows) — the drive letter in
    Carmine's lists never has to match the machine."""
    segs = [s for s in re.split(r"[\\/]+", manifest_path) if s]
    if segs and re.fullmatch(r"[A-Za-z]:", segs[0]):
        segs = segs[1:]
    if not segs:
        return []
    name = segs[0]
    if name in _ROOT_CACHE:
        return _ROOT_CACHE[name]
    roots = []
    if sys.platform == "darwin":
        for base in ("/Volumes",):
            if os.path.isdir(base):
                for v in os.listdir(base):
                    p = os.path.join(base, v, name)
                    if os.path.isdir(p):
                        roots.append(p)
    elif os.name == "nt":
        import string
        for d in string.ascii_uppercase:
            p = f"{d}:\\{name}"
            if os.path.isdir(p):
                roots.append(p)
    home = os.path.join(os.path.expanduser("~"), name)
    if os.path.isdir(home):
        roots.append(home)
    _ROOT_CACHE[name] = roots
    return roots


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # quiet
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/local-info":
            return self._json(200, {"local": True,
                                    "raster": pipeline.raster_available()})
        if p == "/api/file":
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            m = re.search(r"path=([^&]+)", q)
            import urllib.parse
            path = urllib.parse.unquote(m.group(1)) if m else ""
            if path not in ALLOWED_FILES:
                return self._json(403, {"error": "path not allowed"})
            try:
                data = open(path, "rb").read()
            except OSError as e:
                return self._json(404, {"error": str(e)})
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", "inline")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        # static: the shared web UI
        rel = "index.html" if p in ("/", "") else p.lstrip("/")
        full = os.path.normpath(os.path.join(PUBLIC, rel))
        if not full.startswith(os.path.normpath(PUBLIC)) or \
                not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(full)[0]
                         or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
        except Exception as e:
            return self._json(400, {"error": f"bad request: {e}"})
        try:
            if self.path == "/api/extract":
                data = base64.b64decode(req["data"])
                if data[:5] != b"%PDF-":
                    return self._json(422, {"error": "Not a PDF."})
                stages, tables, notes = process_bytes(
                    data, req.get("filename", "file.pdf"))
                return self._json(200, {"stages": stages, "tables": tables,
                                        "notes": notes})
            if self.path == "/api/manifest":
                rows = pe.parse_manifest(req.get("text", ""))
                indexes = {}
                out = []
                for uwi, path in rows:
                    real = os.path.exists(path) and path or None
                    if real is None:
                        # the list's drive letter isn't this machine's —
                        # find the named root on any mounted volume/drive
                        for root in find_drive_roots(path):
                            real = pe.resolve_manifest_path(path, root)
                            if real is None:
                                if root not in indexes:
                                    indexes[root] = pe.index_pdfs(root)
                                real = pe.resolve_manifest_path(
                                    path, root, indexes[root])
                            if real:
                                break
                    if real:
                        ALLOWED_FILES.add(real)
                    out.append({"uwi": uwi, "path": path, "real": real})
                return self._json(200, {"rows": out})
            if self.path == "/api/process-path":
                path = req.get("path", "")
                if path not in ALLOWED_FILES:
                    return self._json(403, {"error": "path not allowed"})
                stages, tables, notes, written = process_path(
                    path, req.get("format", "both"),
                    bool(req.get("xlsxTabs", True)),
                    req.get("stageLabel") == "seq")
                return self._json(200, {"stages": stages, "tables": tables,
                                        "notes": notes, "written": written})
            return self._json(404, {"error": "unknown endpoint"})
        except Exception as e:
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Frac2CSV local — {url}  (raster/OCR: "
          f"{'on' if pipeline.raster_available() else 'OFF'})")
    print("Close this window to stop the app.")
    if not os.environ.get("F2C_NO_BROWSER"):
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
