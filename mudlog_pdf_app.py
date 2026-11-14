"""A mudlog printout PDF dropped on the Lab alone (no log file): read with
mudlog_pdf.py and handed to the Lab the way a WellSight log is
(wellsight_app.read), so it opens in the same views, with the PDF itself
stitched beside it as its printout.

  looks_like_mudlog(pdf) -> (bool, why)
  read(pdf, filename, library=None) -> {"payload", "files", "header", "reading"}

looks_like_mudlog decides whether a dropped PDF goes here or to the frac
readers, from its first pages only, so a frac report is not held up: it
takes a column of depth labels that runs on from page to page (a frac
chart's axis prints the same numbers on every page), or one page of them
with a curve caption beside.

The readings are the printout's, read off its drawing: they are as good as
the drawing (about 1 % of a scale's width), and a reading past twice its
printed scale is not on the printout at all. The payload says so
("source": "pdf") and the Lab tells the user.
"""
import hashlib
import json
import math
import os
import re

import mudlog_pdf as M
import pdf_legend as L
import wellsight_descriptions as wdesc
import wellsight_symbols as wsym

STEP = 0.2              # the Lab's grid, as wellsight_app's
PAGES = 8               # pages looked at to decide


def looks_like_mudlog(pdf, pages=PAGES):
    """(True, why) when the PDF is a mudlog's printout, from its first
    pages. pdf: bytes or a path."""
    import fitz
    import wellsight_print as wp
    try:
        doc = fitz.open(stream=pdf, filetype="pdf") if isinstance(pdf, (bytes, bytearray)) else fitz.open(pdf)
    except Exception:  # noqa: BLE001 - not a PDF this can open: not ours
        return False, "not readable"
    axes = []
    for pno in range(min(pages, len(doc))):
        ax = wp.page_axis(doc[pno], 1, 99999)
        if ax and len(ax[3]) >= 5:
            ds = sorted(d for _c, d in ax[3])
            axes.append((pno, abs(ax[1]), ds[0], ds[-1], len(ds)))
    if not axes:
        return False, "no column of depth labels"
    # two pages of labels on one scale, the second further down the log
    for (p0, s0, a0, b0, _n0), (p1, s1, a1, b1, _n1) in zip(axes, axes[1:]):
        if abs(s0 - s1) <= 0.02 * s0 and a1 >= b0 - 1e-6 and b1 > b0:
            return True, "depth labels run on from page %d to page %d" % (p0 + 1, p1 + 1)
    # one page of them (a short log): a curve caption by them
    for pno, scale, _a, _b, n in axes:
        if n < 8:
            continue
        pg = doc[pno]
        if L.captions(pg, pno, lambda x, y: x):
            return True, "depth labels and curve captions on page %d" % (pno + 1)
    return False, "the depth labels do not run on down the pages"


# ---------------------------------------------------------------- payload

def _mnemonic(name, used):
    m = re.sub(r"[^A-Z0-9]+", "_", (name or "CURVE").upper()).strip("_")[:16] or "CURVE"
    out, k = m, 2
    while out in used:
        out, k = "%s_%d" % (m, k), k + 1
    used.add(out)
    return out


def _named(group, term):
    if (group, term) in wsym._NAMES:
        return wsym._NAMES[(group, term)]
    t = str(term or "")
    return (t.split(":", 1)[1] if ":" in t else t), None


def _grid(curve, depth0, rows):
    """a reading curve (0.1 m) on the Lab's grid (0.2 m) from depth0"""
    out = []
    vals, top, step = curve["values"], curve["top"], curve["step"]
    for i in range(rows):
        j = (depth0 + i * STEP - top) / step
        k = int(round(j))
        out.append(vals[k] if 0 <= k < len(vals) and abs(j - k) < 1e-6 else None)
    return out


def _wraps(values, depth0, sections):
    """where the readings run past their printed scale, as wellsight_scales
    reports a log's: [{top, base, wraps, peak, left, right}]"""
    import wellsight_scales as wscale
    c = {"values": values, "step": STEP, "first_depth": depth0}
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in w.items()}
            for w in wscale.wraps(c, [tuple(s) for s in sections])]


_NUMBERISH = re.compile(r"^[-+(]*\d[\d.,]*[)%]*$")


def _notes(text, tracks):
    """the reading's lines of text -> the log's notes: each line in the
    column it is printed in, lines that run on (no wider gap than the
    column's usual line spacing) joined into one note at the first one's
    depth"""
    cols = sorted(tracks or [], key=lambda t: t["x0"])

    def column(t):
        a = t.get("across")
        if not a:
            return None
        mid = (a[0] + a[1]) / 2
        for c in cols:
            if c["x0"] <= mid <= c["x1"]:
                return c
        return None

    by = {}
    for t in text or []:
        c = column(t)
        if c and set(c.get("keys") or []) & {"curves", "depth"}:
            continue                    # captions and depth labels, not notes
        if all(_NUMBERISH.match(w) for w in t["text"].split()):
            continue                    # a scale's or a depth label's numbers
        by.setdefault((c or {}).get("title") or "", []).append(t)
    out = []
    for col, lines in by.items():
        lines.sort(key=lambda t: t["depth"])
        gaps = sorted(b["depth"] - a["depth"] for a, b in zip(lines, lines[1:]) if b["depth"] > a["depth"])
        usual = gaps[len(gaps) // 4] if gaps else 0.0
        cur = None
        for t in lines:
            if cur and t["depth"] - cur["last"] <= max(1.6 * usual, 1.4 * (t.get("height") or 0)):
                cur["text"] += " " + t["text"]
                cur["last"] = t["depth"]
            else:
                cur = {"depth": t["depth"], "text": t["text"], "column": col, "last": t["depth"]}
                out.append(cur)
    for n in out:
        n.pop("last", None)
    out.sort(key=lambda n: n["depth"])
    return out


def _las(name, reading, curves, header):
    """LAS 2.0 of the curves as read, on the reading's own 0.1 m grid"""
    cs = [c for c in reading.get("curves") or []]
    top, step = reading["depth"]["top"], M.STEP
    n = max((len(c["values"]) for c in cs), default=0)
    lines = ["~Version", " VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0",
             " WRAP.    NO : ONE LINE PER DEPTH STEP", "~Well"]
    bottom = top + (n - 1) * step if n else top
    well = [("STRT", "M", "%.4f" % top, "START DEPTH"), ("STOP", "M", "%.4f" % bottom, "STOP DEPTH"),
            ("STEP", "M", "%.4f" % step, "STEP"), ("NULL", "", "-999.25", "NULL VALUE"),
            ("WELL", "", header.get("well_name", ""), "WELL"), ("LIC", "", header.get("licence", ""), "LICENCE"),
            ("UWI", "", header.get("uwi") or header.get("well_id", ""), "UNIQUE WELL ID"),
            ("LOC", "", header.get("location", ""), "LOCATION"), ("COMP", "", header.get("operator", ""), "COMPANY"),
            ("SRVC", "", "read from its printout by frac2csv (%s)" % reading.get("reader"), "SERVICE")]
    for mn, unit, val, desc in well:
        lines.append(" %-6s.%-4s %s : %s" % (mn, unit, " ".join(str(val).split()), desc))
    lines.append("~Curve")
    lines.append(" DEPT  .M    : DEPTH")
    for c, pc in zip(cs, curves):
        unit = re.sub(r"\s+", "", c.get("units") or "")
        lines.append(" %-6s.%-6s : %s" % (pc["mnemonic"], unit, c["name"]))
    lines.append("~Parameter")
    for c, pc in zip(cs, curves):
        for d, left, right in c.get("scale") or []:
            lines.append(" %-6s.     %s..%s : printed scale of %s from %.2f m" % (
                pc["mnemonic"][:6], left, right, c["name"], d))
    lines.append("~ASCII DEPT " + " ".join(pc["mnemonic"] for pc in curves))
    for i in range(n):
        row = ["%.4f" % (top + i * step)]
        for c in cs:
            v = c["values"][i] if i < len(c["values"]) else None
            row.append("-999.25" if v is None or not math.isfinite(v) else "%.4f" % v)
        lines.append(" ".join(row))
    return ("\n".join(lines) + "\n").encode()


def read(pdf, filename, library=None):
    """-> {"payload", "files", "header", "reading"}, as wellsight_app.read,
    from the printout alone. Raises ValueError with a sentence for the user
    when nothing could be read."""
    name = os.path.basename(filename or "printout.pdf")
    stem = name[:-4] if name.lower().endswith(".pdf") else name      # what it saves is named after it
    data = bytes(pdf) if not isinstance(pdf, str) else open(pdf, "rb").read()
    r = M.read(data, library=library)
    if r.get("error"):
        raise ValueError("%s: %s" % (name, r["error"]))
    top, bottom = r["depth"]["top"], r["depth"]["bottom"]
    h = dict(r.get("header") or {})
    depth0 = round(math.ceil(top / STEP - 1e-6) * STEP, 4)
    rows = int(math.floor((bottom - depth0) / STEP + 1e-6)) + 1
    used, curves = set(), []
    for c in r.get("curves") or []:
        vals = _grid(c, depth0, rows)
        secs = c.get("scale") or []
        curves.append({"mnemonic": _mnemonic(c["name"], used), "name": c["name"], "unit": c.get("units") or "",
                       "track": "", "recorded_step": c["step"], "scale": secs,
                       "wraps": _wraps(vals, depth0, secs) if secs else [],
                       "values": [None if v is None else round(v, 4) for v in vals],
                       "colour": c.get("colour"), "kind": c.get("kind")})
    rocks = []
    for iv in r.get("rocks") or []:
        t = iv["rock"]
        rec = {"top": iv["top"], "base": iv["base"], "rock": t, "name": _named("rock", t)[0], "mods": [],
               "raw": t, "color": wsym.rock_color(t)}
        if rocks and rocks[-1]["rock"] == t and abs(rocks[-1]["base"] - rec["top"]) < 0.06:
            rocks[-1]["base"] = rec["base"]
        else:
            rocks.append(rec)
    lith = [{"top": iv["top"], "base": iv["base"], "code": iv["rock"], "rock": iv["name"]} for iv in rocks]
    symbols = []
    for s in r.get("symbols") or []:
        n, rank = _named(s["group"], s["term"])
        symbols.append({"depth": s["depth"], "group": s["group"], "term": s["term"], "name": n, "rank": rank,
                        "raw": s["term"], "category": s["group"]})
    sym_iv = []
    for iv in r.get("intervals") or []:
        n, rank = _named(iv["group"], iv["term"])
        sym_iv.append({"top": iv["top"], "base": iv["base"], "group": iv["group"], "term": iv["term"], "name": n,
                       "rank": rank, "raw": iv["term"], "column": iv["group"]})
    analysis = wsym.analyse(top, bottom, rocks, symbols, sym_iv, curves, depth0 if rows else None, STEP, None)
    notes = _notes(r.get("text"), r.get("tracks"))
    described = wdesc.read(notes, top, bottom)
    analysis["descriptions"] = wdesc.analyse(described, rocks, symbols, analysis["show_zones"])

    files = {stem + ".las": _las(name, r, curves, h),
             stem + ".reading.json": json.dumps(r, indent=1).encode()}
    if h:
        files[stem + ".header.csv"] = wsym.csv_text([["field", "value"]] + [[k, v] for k, v in h.items()]).encode()
    if notes:
        files[stem + ".notes.csv"] = wsym.csv_text([["depth_m", "column", "text"]] + [
            [n["depth"], n["column"], n["text"]] for n in notes]).encode()
    if rocks:
        files[stem + ".rock-types.csv"] = wsym.csv_text(wsym.rows_rocks(rocks)).encode()
    if symbols:
        files[stem + ".symbols.csv"] = wsym.csv_text(wsym.rows_symbols(symbols)).encode()
    if sym_iv:
        files[stem + ".symbol-intervals.csv"] = wsym.csv_text(wsym.rows_columns(sym_iv)).encode()
    if analysis["show_zones"]:
        files[stem + ".show-zones.csv"] = wsym.csv_text(wsym.rows_zones(analysis)).encode()
    if rocks or symbols or sym_iv or described["samples"]:
        files[stem + ".analysis.json"] = json.dumps(analysis, indent=1).encode()
    warnings = ["Read from the printout alone: the curves are read off its lines (about 1 % of each scale's "
                "width), and a reading past twice its printed scale is not on the printout."]
    warnings += [n for n in r.get("notes") or [] if n]
    payload = {
        "file": name, "source": "pdf",
        "sha1": hashlib.sha1(data).hexdigest(),
        "app": "PDF printout", "version": r.get("reader"),
        "well": h.get("well_name", ""), "licence": h.get("licence", ""),
        "uwi": h.get("uwi") or h.get("well_id", ""), "location": h.get("location", ""),
        "operator": h.get("operator", ""),
        "header": {k: v for k, v in h.items() if v},
        "top": top, "bottom": bottom, "scale": None,
        "axis": "", "axis_basis": "the printout's depth labels",
        "step": STEP, "depth0": depth0, "rows": rows,
        "curves": curves, "lithology": lith,
        "rocks": rocks, "percent": None,
        "symbols": [{k: v for k, v in s.items() if k != "category"} for s in symbols],
        "symbolIntervals": sym_iv, "analysis": analysis,
        "descriptions": {"samples": [{k: v for k, v in sm.items() if k != "column"} for sm in described["samples"]],
                         "tops": [{k: v for k, v in t.items() if k != "column"} for t in described["tops"]],
                         "events": [{k: v for k, v in e.items() if k != "column"} for e in described["events"]],
                         "columns": {}},
        "warnings": warnings,
        "files": sorted(files),
    }
    head = {"source": "pdf", "boxes": [], "custom": None}
    return {"payload": payload, "files": files, "header": head, "reading": r}
