"""WellSight StripLog / HorizontalLog files dropped on the Lab -> LAS.

The decoding is wellsight-convert's, copied unchanged into wellsight_convert/
(see its SOURCE.md). This module only runs it on one dropped file and hands
the Lab what it needs:

  read(data, filename) -> {"payload": ..., "files": {name: bytes}}

payload is what the Lab and the stacked view draw: the header, every curve on
the 0.2 m export grid, and the lithology intervals. files are the converter's
own outputs, written only when the user saves:

  <file>.las                 LAS 2.0, every curve at its recorded step
  <file>.curves-0.2m.las     curve-track data on a regular 0.2 m step
  <file>.csv / .json         the same table, and everything else in the file
  <file>.lithology.csv, .survey.csv, .accessories.csv, .picture-N.png
                             where the log has them

Standard library only, like the converter.
"""
import hashlib
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "wellsight_convert")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import wellsight as ws        # noqa: E402
import convert as cv          # noqa: E402
import export_las as el       # noqa: E402

# The four the converter reads (StripLog / HorizontalLog, v5 and v6). The
# extension is only a hint: the 32-byte signature inside the body decides,
# and a .slg that is really a HorizontalLog reads the same.
EXTS = (".sl6", ".slg", ".hl6", ".hlg")
# LogViewer 8's own formats and MudLog: offered to the reader so the user
# hears why one does not read, rather than seeing it refused as "not a PDF".
MAYBE = (".sl8", ".hl8", ".ml8", ".ml6", ".mlg")
STEP = 0.2          # the regular-step export the stacked view draws


def is_wellsight_name(name):
    n = (name or "").lower()
    return n.endswith(EXTS + MAYBE)


def looks_like_wellsight(data):
    """An AACS container, or a raw 6.5 body that names its program."""
    head = bytes(data[:256])
    return head[:4] == b"AACS" or b"STRIP.LOG" in head or b"HORIZONTAL.LOG" in head \
        or b"MUD.LOG" in head


class NotWellSight(Exception):
    pass


def _rock(code):
    return ws.ROCK_NAMES.get((code or "").upper(), code or "")


def read(data, filename):
    """Decode one dropped file. Raises NotWellSight with a sentence the user
    can act on when the file is not one the converter reads."""
    name = os.path.basename(filename or "log.sl6")
    try:
        log = ws.read_log(bytes(data))
    except ws.NotReadable as ex:
        raise NotWellSight(f"{name} is not a WellSight log this reader knows ({ex}).")
    tmp = tempfile.mkdtemp(prefix="f2c-ws-")
    try:
        src = os.path.join(tmp, "src")
        out = os.path.join(tmp, "out")
        os.makedirs(src)
        with open(os.path.join(src, name), "wb") as f:
            f.write(data)
        row = cv.convert_one((src, out, name))
        if row.get("status") not in ("ok", "no_curves"):
            raise NotWellSight(f"{name}: {row.get('reason') or row.get('status')}")
        erow = el.export_one((src, os.path.join(tmp, "x"), name, "curves", STEP))
        files = {}
        for fn in sorted(os.listdir(out)):
            with open(os.path.join(out, fn), "rb") as f:
                files[fn] = f.read()
        x = os.path.join(tmp, "x", name + ".las")
        if erow.get("status") == "ok" and os.path.exists(x):
            with open(x, "rb") as f:
                files[name + ".curves-%gm.las" % STEP] = f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    h = log["header"] or {}
    axis, basis = ws.decide_axis(log.get("axis_votes") or (0, 0), name)
    curves = []
    exp = el.export_curves(log, STEP) if log["top"] is not None else None
    if exp:
        (grid, step), cols, meta, _notes = exp
        for (mn, c), col in zip(meta, cols):
            curves.append({"mnemonic": mn, "name": c.get("name") or mn,
                           "unit": c.get("units") or "", "track": c.get("track") or "",
                           "recorded_step": c["step"],
                           "values": [None if v is None else round(v, 4) for v in col]})
        depth0, nrows = grid[0], len(grid)
    else:
        depth0, nrows = log["top"], 0
    lith = log.get("lithology") or {}
    _extra, intervals = cv.lith_curves(log, lith)
    lith_iv = [{"top": iv["top_m"], "base": iv["base_m"], "code": iv["code"],
                "rock": iv.get("name") or _rock(iv["code"])} for iv in intervals]
    payload = {
        "file": name,
        "sha1": hashlib.sha1(data).hexdigest(),
        "app": log["app"], "version": log["version"],
        "well": h.get("well_name", ""), "licence": h.get("licence", ""),
        "uwi": h.get("well_id", ""), "location": h.get("location", ""),
        "operator": h.get("operator", ""),
        "header": {k: v for k, v in h.items() if v},
        "top": log["top"], "bottom": log["bottom"], "scale": log["scale"],
        "axis": axis, "axis_basis": basis,
        "step": STEP, "depth0": depth0, "rows": nrows,
        "curves": curves, "lithology": lith_iv,
        "warnings": list(log["warnings"]),
        "files": sorted(files),
    }
    return {"payload": payload, "files": files}
