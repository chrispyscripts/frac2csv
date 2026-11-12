"""The local app's WellSight endpoints. localapp.py routes /api/wellsight*
here; this keeps the decoded logs and their stitched printouts in memory for
the Lab and the stacked view (logstack.html).

POST /api/wellsight            {filename, data, printout?}  decode (+ stitch)
POST /api/wellsight-printout   {id, data}                    stitch a dropped printout
POST /api/wellsight-logviewer  {id}                          print with LogViewer, stitch
POST /api/wellsight-save       {id, folder, destFolder}      write LAS, CSV, JSON, strip
GET  /api/wellsight-status                                    can LogViewer print here?
GET  /api/wellsight-view?id=                                  what the stacked view draws
GET  /api/wellsight-strip?id=&d0=&d1=&ppm=                    PNG of the strip, by depth
GET  /api/wellsight-strip.pdf?id=                             the stitched PDF
"""
import base64
import collections
import os
import shutil
import tempfile
import threading
import uuid

import wellsight_app as wa
import wellsight_print as wp
import wellsight_logviewer as lv

_KEEP = 24                      # logs held at once; the oldest goes first
_STORE = collections.OrderedDict()
_LOCK = threading.Lock()


def _put(rec):
    with _LOCK:
        _STORE[rec["id"]] = rec
        while len(_STORE) > _KEEP:
            _STORE.popitem(last=False)


def _get(i):
    with _LOCK:
        rec = _STORE.get(i or "")
        if rec:
            _STORE.move_to_end(rec["id"])
        return rec


def _strip_name(rec):
    return rec["payload"]["file"] + ".printout-stitched.pdf"


def _stitch(rec, pdf_bytes, source):
    p = rec["payload"]
    if p["top"] is None:
        raise wp.NoDepthScale("this log stores no depth range, so its printout cannot be placed")
    data, info = wp.stitch(pdf_bytes, p["top"], p["bottom"])
    info["source"] = source
    info["file"] = _strip_name(rec)
    rec["strip"], rec["strip_info"] = data, info
    rec["strip_doc"] = None
    return info


def _public(rec):
    return {"id": rec["id"], "payload": rec["payload"], "printout": rec.get("strip_info")}


def decode(req):
    data = base64.b64decode(req["data"])
    name = os.path.basename(req.get("filename") or "log.sl6")
    out = wa.read(data, name)
    rec = {"id": uuid.uuid4().hex[:12], "payload": out["payload"], "files": out["files"],
           "native": data, "strip": None, "strip_info": None}
    resp = _public(rec)
    if req.get("printout"):
        try:
            _stitch(rec, base64.b64decode(req["printout"]),
                    os.path.basename(req.get("printoutName") or "printout.pdf"))
            resp["printout"] = rec["strip_info"]
        except Exception as e:  # noqa: BLE001
            resp["printoutError"] = str(e)
    _put(rec)
    return 200, resp


def printout(req):
    rec = _get(req.get("id"))
    if not rec:
        return 404, {"error": "that log is no longer loaded; drop it again"}
    data = base64.b64decode(req["data"])
    if data[:5] != b"%PDF-":
        return 422, {"error": "not a PDF"}
    try:
        info = _stitch(rec, data, os.path.basename(req.get("filename") or "printout.pdf"))
    except wp.NoDepthScale as e:
        return 422, {"error": str(e)}
    return 200, {"printout": info}


def logviewer(req):
    rec = _get(req.get("id"))
    if not rec:
        return 404, {"error": "that log is no longer loaded; drop it again"}
    tmp = tempfile.mkdtemp(prefix="f2c-lv-")
    try:
        native = os.path.join(tmp, rec["payload"]["file"])
        with open(native, "wb") as f:
            f.write(rec["native"])
        pdf = lv.print_to_pdf(native, os.path.join(tmp, "printout.pdf"))
        with open(pdf, "rb") as f:
            data = f.read()
        rec["printout_raw"] = data
        info = _stitch(rec, data, "LogViewer")
        return 200, {"printout": info}
    except (lv.LogViewerError, wp.NoDepthScale) as e:
        return 422, {"error": str(e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def save(req, export_folder):
    rec = _get(req.get("id"))
    if not rec:
        return 404, {"error": "that log is no longer loaded; drop it again"}
    folder = req.get("folder") or os.path.join(os.path.expanduser("~"), "Downloads")
    folder, skipped = export_folder(folder, req.get("destFolder", ""))
    written = []
    files = dict(rec["files"])
    if rec.get("strip"):
        files[_strip_name(rec)] = rec["strip"]
    if rec.get("printout_raw"):
        files[rec["payload"]["file"] + ".printout.pdf"] = rec["printout_raw"]
    for name, data in files.items():
        dest = os.path.join(folder, os.path.basename(name))
        with open(dest, "wb") as f:
            f.write(data)
        written.append(os.path.basename(name))
    return 200, {"written": written, "folder": folder, "skipped": skipped or ""}


def status():
    return 200, lv.status()


def view(q):
    rec = _get(q.get("id"))
    if not rec:
        return 404, {"error": "that log is no longer loaded; drop it again"}
    return 200, _public(rec)


def strip_png(q):
    rec = _get(q.get("id"))
    if not rec or not rec.get("strip"):
        return 404, None
    info = rec["strip_info"]
    if rec.get("strip_doc") is None:
        import fitz
        rec["strip_doc"] = fitz.open(stream=rec["strip"], filetype="pdf")
    d0, d1 = float(q.get("d0", info["top"])), float(q.get("d1", info["bottom"]))
    ppm = min(max(float(q.get("ppm", 20)), 1.0), 400.0)
    if d1 - d0 > 400 or d1 <= d0:
        return 400, None
    return 200, wp.render(rec["strip_doc"], d0, d1, info["top"], info["pt_per_m"], ppm)


def strip_pdf(q):
    rec = _get(q.get("id"))
    if not rec or not rec.get("strip"):
        return 404, None
    return 200, rec["strip"]
