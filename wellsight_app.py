"""WellSight StripLog / HorizontalLog files dropped on the Lab -> LAS.

The decoding is wellsight-convert's, copied unchanged into wellsight_convert/
(see its SOURCE.md). This module only runs it on one dropped file and hands
the Lab what it needs:

  read(data, filename) -> {"payload": ..., "files": {name: bytes}}

payload is what the Lab and the stacked view draw: the header, every curve on
the 0.2 m export grid, and the lithology intervals. files are the converter's
own outputs, written only when the user saves:

  <file>.las                 LAS 2.0, every curve at its recorded step
  <file>.curve-track.las     the curve track only, on one regular step: the
                             finest any of its curves is recorded at, so no
                             reading is thinned out (what Save LAS writes);
                             with the log's Porosity and Grain Size cells as
                             curves after them (wellsight_cells.py)
  <file>.csv / .json         the same table, and everything else in the file
  <file>.lithology.csv, .survey.csv, .accessories.csv, .picture-N.png
                             where the log has them
  <file>.rock-types.csv, .symbols.csv, .symbol-intervals.csv,
  .show-zones.csv, .analysis.json
                             the rock types, accessories and other symbols
                             in one vocabulary, and what they add up to
                             (wellsight_symbols.py)

Standard library only, like the converter.
"""
import hashlib
import math
import os
import shutil
import sys
import tempfile
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "wellsight_convert")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import wellsight as ws        # noqa: E402
import convert as cv          # noqa: E402
import export_las as el       # noqa: E402
import json                   # noqa: E402

import wellsight_symbols as wsym   # noqa: E402
import wellsight_scales as wscale   # noqa: E402
import wellsight_descriptions as wdesc   # noqa: E402
import wellsight_cells as wcells   # noqa: E402

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


# The converter and the LAS exporter each decode the file again from its
# bytes. Decoding a long lateral takes seconds (its symbol library is found by
# scanning the whole body), so while they run they are handed the log this
# module has already decoded. Neither changes it: the decoded log hashes the
# same before and after both, on logs of every kind on the WellSight drive.
_DECODE_LOCK = threading.Lock()


def _rock(code):
    return ws.ROCK_NAMES.get((code or "").upper(), code or "")


def read(data, filename):
    """Decode one dropped file. Raises NotWellSight with a sentence the user
    can act on when the file is not one the converter reads."""
    name = os.path.basename(filename or "log.sl6")
    data = bytes(data)
    try:
        log = ws.read_log(data)
    except ws.NotReadable as ex:
        raise NotWellSight(f"{name} is not a WellSight log this reader knows ({ex}).")
    with _DECODE_LOCK:
        real = ws.read_log
        ws.read_log = lambda raw: log if raw == data else real(raw)
        try:
            files = _convert(data, name, las_step(log))
        finally:
            ws.read_log = real
    return _payload(log, data, name, files)


CURVE_LAS = ".curve-track.las"


def las_step(log):
    """the step the curve-track LAS is written on: the finest any curve in
    the curve track is recorded at (coarser curves repeat their nearest
    reading, as the converter writes them; none is thinned)"""
    steps = [c["step"] for c in el.curve_track_curves(log) if c.get("step")]
    return round(min(steps), 6) if steps else STEP


def _convert(data, name, las_step=STEP):
    """the converter's own outputs and the curve-track LAS, by file name"""
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
        files = {}
        for fn in sorted(os.listdir(out)):
            with open(os.path.join(out, fn), "rb") as f:
                files[fn] = f.read()
        las = _curve_track_las(data, name, las_step, os.path.join(tmp, name + CURVE_LAS))
        if las is not None:
            files[name + CURVE_LAS] = las
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return files


def _curve_track_las(data, name, las_step, path):
    """The LAS Save writes: the converter's curve-track export (export_las
    "curves", the same file it writes), with the log's Porosity and Grain
    Size cells as curves after the curves, on the same depths, the depth
    range stretched to take in every filled row. None when the log has no
    curve track to write."""
    try:
        log = ws.read_log(data)
        res = el.export_curves(log, las_step)
    except Exception:  # noqa: BLE001 -- as export_one: no file, the rest still saved
        return None
    if not res:
        return None
    table, cols, meta, notes = res
    try:
        table, cols, meta, notes = _with_cells(data, log, table, cols, meta, notes)
    except Exception as ex:  # noqa: BLE001 -- the cells are extra; never lose the curves over them
        notes = notes + ["Porosity / Grain Size cells could not be read (%s: %s)." % (type(ex).__name__, ex)]
    try:
        cv.write_las(path, log, name, hashlib.sha1(data).hexdigest(), table, cols, meta, notes=notes)
    except Exception:  # noqa: BLE001 -- as export_one
        return None
    with open(path, "rb") as f:
        return f.read()


def _with_cells(data, log, table, cols, meta, notes):
    body, _ = ws.inflate(data, [])
    titles = {t[2] for t in ws.tracks(body) if t[2]} | set(log.get("columns") or [])
    found = wcells.grids(body, titles)
    if not found:
        return table, cols, meta, notes
    grid, step = table
    top = log["top"]
    k0 = int(round((grid[0] - top) / step))
    k1 = int(round((grid[-1] - top) / step))
    span = wcells.span(found, top)
    if span:
        a = int(math.floor((span[0] - top) / step + 1e-9))
        b = int(math.ceil((span[1] - top) / step - 1e-9)) - 1
        if a < k0 or b > k1:
            n0, n1 = min(k0, a), max(k1, b)
            cols = [[None] * (k0 - n0) + list(c) + [None] * (n1 - k1) for c in cols]
            grid = [top + k * step for k in range(n0, n1 + 1)]
            k0, k1 = n0, n1
    curves, left_out = wcells.las_curves(found, top, grid, step)
    used = {mn for mn, _ in meta}
    meta, cols = list(meta), list(cols)
    for mn, unit, desc, vals in curves:
        m, i = mn, 2
        while m in used:
            m, i = "%s_%d" % (mn, i), i + 1
        used.add(m)
        meta.append((m, {"mnem": m, "name": mn, "source_mnemonic": "", "units": unit, "step": step,
                         "description": desc}))
        cols.append(vals)
    notes = list(notes)
    if curves:
        notes = [x.replace("Content: curve-track data only (no lithology, text or survey).",
                           "Content: curve-track data, then the log's Porosity / Grain Size cells as curves "
                           "(no lithology, text or survey).") for x in notes]
        notes.append("Cell curves (%s): read from the log's own cells; each depth holds the cell row it is in. "
                     "See each curve's description." % ", ".join(c[0] for c in curves))
    notes += left_out
    return (grid, step), cols, meta, notes


def _most_common_column(items):
    c = {}
    for it in items:
        if it.get("column"):
            c[it["column"]] = c.get(it["column"], 0) + 1
    return max(c, key=c.get) if c else None


def _payload(log, data, name, files):
    h = log["header"] or {}
    axis, basis = ws.decide_axis(log.get("axis_votes") or (0, 0), name)
    curves = []
    exp = el.export_curves(log, STEP) if log["top"] is not None else None
    # each curve's printed scale and where the printout wraps it
    # (wellsight_scales): the readings are the file's, the printout's line
    # can be a scale width away from them
    try:
        scales = wscale.scales(data, log["curves"])
    except Exception:  # noqa: BLE001 -- the scales are extra; the curves stand without them
        scales = {}
    by_offset = {c["offset"]: i for i, c in enumerate(log["curves"])}
    if exp:
        (grid, step), cols, meta, _notes = exp
        for (mn, c), col in zip(meta, cols):
            secs = scales.get(by_offset.get(c.get("offset")))
            curves.append({"mnemonic": mn, "name": c.get("name") or mn,
                           "unit": c.get("units") or "", "track": c.get("track") or "",
                           "recorded_step": c["step"],
                           "scale": [[d, l, r] for d, l, r in secs] if secs else None,
                           "wraps": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in w.items()}
                                     for w in wscale.wraps(c, secs)] if secs else [],
                           "values": [None if v is None else round(v, 4) for v in col]})
        depth0, nrows = grid[0], len(grid)
    else:
        depth0, nrows = log["top"], 0
    lith = log.get("lithology") or {}
    _extra, intervals = cv.lith_curves(log, lith)
    lith_iv = [{"top": iv["top_m"], "base": iv["base_m"], "code": iv["code"],
                "rock": iv.get("name") or _rock(iv["code"])} for iv in intervals]

    # rock types, accessories and other symbols, in one vocabulary
    rocks = wsym.rocks_from(lith_iv)
    symbols = wsym.symbols_from(log.get("accessories") or [])
    sym_iv = wsym.columns_from(lith.get("symbol_columns") or [])
    percent = None
    pc = lith.get("percent")
    if pc and log["top"] is not None:
        lsyms = lith.get("_lith_symbols") or {}
        terms = [wsym.rock_term(lsyms.get(r, (str(r), ""))[0])[0] for r in pc["rocks"]]
        percent = {"rocks": terms, "codes": [lsyms.get(r, (str(r), ""))[0] for r in pc["rocks"]],
                   "names": [wsym._NAMES.get(("rock", t), (t[4:] if t.startswith("raw:") else t,))[0]
                             for t in terms],
                   "colors": [wsym.rock_color(t) for t in terms],
                   "depth0": log["top"], "step": pc["step_m"], "values": pc["values"]}
    analysis = wsym.analyse(log["top"], log["bottom"], rocks, symbols, sym_iv, curves,
                            depth0 if nrows else None, STEP, percent)
    # the geologist's written descriptions, formation tops and events
    described = wdesc.read(log.get("annotations") or [], log["top"], log["bottom"])
    desc_an = wdesc.analyse(described, rocks, symbols, analysis["show_zones"])
    analysis["descriptions"] = desc_an
    if described["samples"]:
        files[name + ".descriptions.csv"] = wsym.csv_text(wdesc.rows_samples(described)).encode()
    if described["tops"]:
        files[name + ".formation-tops.csv"] = wsym.csv_text(wdesc.rows_tops(described)).encode()
    if any(c["scale"] for c in curves):
        files[name + ".printed-scales.csv"] = wsym.csv_text(wscale.rows_scales(curves)).encode()
    if any(c["wraps"] for c in curves):
        files[name + ".wraps.csv"] = wsym.csv_text(wscale.rows_wraps(curves)).encode()
    if rocks:
        files[name + ".rock-types.csv"] = wsym.csv_text(wsym.rows_rocks(rocks)).encode()
    if symbols:
        files[name + ".symbols.csv"] = wsym.csv_text(wsym.rows_symbols(symbols)).encode()
    if sym_iv:
        files[name + ".symbol-intervals.csv"] = wsym.csv_text(wsym.rows_columns(sym_iv)).encode()
    if analysis["show_zones"]:
        files[name + ".show-zones.csv"] = wsym.csv_text(wsym.rows_zones(analysis)).encode()
    if rocks or symbols or sym_iv or described["samples"]:
        files[name + ".analysis.json"] = json.dumps(analysis, indent=1).encode()
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
        "rocks": rocks, "percent": percent,
        "symbols": [{k: v for k, v in s_.items() if k != "category"} for s_ in symbols],
        "symbolIntervals": sym_iv, "analysis": analysis,
        "descriptions": {"samples": [{k: v for k, v in sm.items() if k != "column"} for sm in described["samples"]],
                         "tops": [{k: v for k, v in t.items() if k != "column"} for t in described["tops"]],
                         "events": [{k: v for k, v in e.items() if k != "column"} for e in described["events"]],
                         # the column each kind of note is written in, to find it on the printout
                         "columns": {k: _most_common_column(described[k]) for k in ("samples", "tops", "events")}},
        "warnings": list(log["warnings"]),
        "files": sorted(files),
    }
    # the header page beyond its fields: the titled boxes (OPERATOR,
    # GEOLOGIST, DRILLING ...) and a custom header page's lines, for the
    # header window (wellsight_server.header)
    head = {"source": log.get("header_source"),
            "boxes": [{"title": b.get("title") or "", "kind": b.get("kind"), "fields": b.get("fields") or [],
                       "text": b.get("text") or ""} for b in log.get("boxes") or []],
            "custom": (log.get("custom_header") or {}).get("lines")}
    return {"payload": payload, "files": files, "header": head}
