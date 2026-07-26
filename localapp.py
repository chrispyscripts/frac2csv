#!/usr/bin/env python3
"""Frac2CSV local app — the web Lab UI running against the local engine.

Serves the SAME lab/public/index.html the web version uses (identical
layout), backed by a 127.0.0.1-only server with direct disk access:

  - raster/scanned templates work (local tesseract), unlike the web
  - TXT drive lists resolve server-side — no folder picker, any browser
  - exports write straight into each PDF's own folder (or, when that folder
    is read-only, the destination folder set in Settings)
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
from version import VERSION     # noqa: E402
import pipeline                 # noqa: E402
import pipeline_export as pe    # noqa: E402

PALETTE = ["#1d5bd8", "#b02e2e", "#1e7a34", "#7a3b9b", "#b0731f", "#0f7d7d",
           "#5a5f6e", "#8a2f5e"]
KNOWN = {"Tr Press": "#b02e2e", "Slurry Rate": "#1d5bd8",
         "WH Prop Conc": "#1e7a34", "BH Prop Conc": "#7a3b9b"}

# paths the client may read back (Original chart) — filled by manifest and
# process-path requests so /api/file can't be pointed anywhere else
ALLOWED_FILES = set()


def pick_folder():
    """Open the OS's native folder chooser and return the picked path (or
    None if cancelled). macOS uses osascript; Windows a PowerShell dialog;
    otherwise tkinter."""
    import subprocess
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose folder with prompt '
                 '"Choose the export destination folder")'],
                capture_output=True, text=True, timeout=120)
            return out.stdout.strip() or None
        if os.name == "nt":
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "if($f.ShowDialog() -eq 'OK'){$f.SelectedPath}")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=120)
            return out.stdout.strip() or None
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        path = filedialog.askdirectory()
        root.destroy()
        return path or None
    except Exception:
        return None


_WRITABLE = {}


def dir_writable(folder):
    """Can we actually create a file in `folder`? Probed for real (and cached
    per folder) rather than trusting os.access — Carmine's charts live on an
    NTFS external drive macOS mounts read-only, and the write only fails at
    open() time with Errno 30."""
    if not folder:
        return False
    if folder in _WRITABLE:
        return _WRITABLE[folder]
    ok = False
    # thread id in the name: two requests may probe the same folder at once
    # and must not delete each other's probe
    probe = os.path.join(folder, f".frac2csv-writetest-{os.getpid()}-"
                                 f"{threading.get_ident()}")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(probe, "w"):
            pass
        ok = True
    except OSError:
        ok = False
    if ok:
        try:
            os.remove(probe)
        except OSError:
            pass
    _WRITABLE[folder] = ok
    return ok


def export_folder(preferred, dest_folder=""):
    """Where exports actually land: `preferred` (normally the PDF's own
    folder) when it is writable, else the folder configured in Settings, else
    ~/Downloads, else home. -> (folder, skipped) where skipped is the
    unwritable folder we had to give up on ("" when none)."""
    if dir_writable(preferred):
        return preferred, ""
    home = os.path.expanduser("~")
    for cand in (dest_folder, os.path.join(home, "Downloads"), home):
        if cand and dir_writable(cand):
            return cand, preferred
    raise OSError(f"no writable export folder — tried {preferred}, "
                  f"{dest_folder or '(no destination set)'}, {home}")


def _channels_payload(data, units=None, labels=None, scales=None):
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
            # the chart axis this channel was drawn against, when the
            # template knows it — the ghost overlay plots against it so it
            # lands on the printed ink instead of being auto-normalised
            # the chart's OWN printed axis for this curve. A pair means the
            # axis is not zero-based (some are inverted or offset), so both
            # ends travel; a bare number is a 0..max axis.
            "axisMin": (lambda v: float(v[0]) if isinstance(v, (list, tuple))
                        else 0.0)((scales or {}).get(key) or 0.0),
            "axisMax": (lambda v: float(v[1]) if isinstance(v, (list, tuple))
                        else (float(v) if v else None))((scales or {}).get(key)),
            "values": [None if (v is None or not np.isfinite(v))
                       else round(float(v), 4) for v in vals],
        })
    return out


def serialize(results, notes):
    stages, tables, summary = [], [], []
    for r in results:
        if r["type"] == "series":
            stages.append({
                "kind": "vector", "meta": r["meta"],
                "n": int(len(r["samples"])), "sample_sec": 1.0,
                "channels": _channels_payload(r["data"], r.get("units"),
                                              r.get("labels"), r.get("scales")),
                "source": r["source"], "page": r.get("page"), "geom": r.get("geom"),
            })
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


def process_bytes(data, filename):
    doc = fitz.open(stream=data, filetype="pdf")
    results, notes = pipeline.extract_document(doc, filename=filename)
    doc.close()
    return serialize(results, notes)


def process_path(path, fmt="both", tabs=True, seq=False, dest_folder=""):
    doc = fitz.open(path)
    results, notes = pipeline.extract_document(
        doc, filename=os.path.basename(path))
    doc.close()
    stages, tables, notes, summary = serialize(results, notes)

    series = [r for r in results if r["type"] == "series"]
    written = []
    src_dir = os.path.dirname(path)
    folder, skipped = export_folder(src_dir, dest_folder)
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
    if written and skipped:
        notes.append(f"{skipped} is read-only — exports saved to {folder} "
                     "instead.")
    return stages, tables, notes, written, summary, folder


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
            return self._json(200, {"local": True, "version": VERSION,
                                    "raster": pipeline.raster_available()})
        if p == "/api/screenshot":
            shot, why = grab_screen()
            if not shot:
                return self._json(200, {"ok": False, "error": why})
            return self._json(200, {"ok": True, "image": shot})
        if p == "/api/pick-folder":
            return self._json(200, {"path": pick_folder() or ""})
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
            if self.path == "/api/save":
                # write one export file into a folder on disk (desktop only).
                folder = req.get("folder", "") or os.path.join(
                    os.path.expanduser("~"), "Downloads")
                name = os.path.basename(req.get("name", "export.csv"))
                try:
                    # a TXT-batch entry's own folder can be a read-only volume
                    folder, _ = export_folder(folder,
                                              req.get("destFolder", ""))
                    dest = os.path.join(folder, name)
                    if "b64" in req:
                        with open(dest, "wb") as f:
                            f.write(base64.b64decode(req["b64"]))
                    else:
                        with open(dest, "w", newline="") as f:
                            f.write(req.get("text", ""))
                    return self._json(200, {"written": dest})
                except OSError as e:
                    return self._json(500, {"error": str(e)})
            if self.path == "/api/extract":
                data = base64.b64decode(req["data"])
                if data[:5] != b"%PDF-":
                    return self._json(422, {"error": "Not a PDF."})
                stages, tables, notes, summary = process_bytes(
                    data, req.get("filename", "file.pdf"))
                return self._json(200, {"stages": stages, "tables": tables,
                                        "notes": notes, "summary": summary})
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
                stages, tables, notes, written, summary, out_dir = process_path(
                    path, req.get("format", "both"),
                    bool(req.get("xlsxTabs", True)),
                    req.get("stageLabel") == "seq",
                    req.get("destFolder", ""))
                return self._json(200, {"stages": stages, "tables": tables,
                                        "notes": notes, "written": written,
                                        "summary": summary, "outDir": out_dir})
            return self._json(404, {"error": "unknown endpoint"})
        except Exception as e:
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})


def grab_screen(max_edge=1800):
    """Full-screen PNG as a data URL -> (dataurl, None) or (None, reason).

    The desktop build runs its own server on the user's machine, so it can
    capture the screen directly — no browser picker, no extra click. That is
    the point: a report should carry what the user was actually looking at,
    including the source PDF open beside the app.

    The user still sees the image in the dialog before sending, and nothing
    leaves the machine until they press Send.

    Windows grabs via GDI and needs no permission. macOS gates screen capture
    behind Screen Recording (TCC), so say so rather than failing blankly.
    """
    try:
        from PIL import ImageGrab
    except Exception:
        return None, "Pillow is not available in this build"
    img = None
    try:
        # all_screens spans multiple monitors on Windows; ignored elsewhere.
        try:
            img = ImageGrab.grab(all_screens=True)
        except TypeError:
            img = ImageGrab.grab()
    except Exception as e:
        if sys.platform == "darwin":
            return None, ("macOS is blocking screen capture — allow it under "
                          "System Settings > Privacy & Security > Screen "
                          "Recording, then reopen the app")
        return None, f"{type(e).__name__}: {e}"[:120]
    if img is None:
        return None, "screen capture returned nothing"
    try:
        w, h = img.size
        if max(w, h) > max_edge:             # keep it under the 3MB cap
            k = max_edge / float(max(w, h))
            img = img.resize((max(1, int(w * k)), max(1, int(h * k))))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        kind = "png"
        # A detail-dense 4K desktop can push PNG past the endpoint's ceiling.
        # JPEG keeps a screenshot readable at a fraction of the size, so fall
        # back rather than have the report arrive with no image at all.
        if buf.tell() > 2_400_000:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85,
                                    optimize=True)
            kind = "jpeg"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:120]
    return (f"data:image/{kind};base64,"
            + base64.b64encode(buf.getvalue()).decode()), None


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
