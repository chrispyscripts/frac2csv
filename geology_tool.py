"""Geology tool: a geologist's well report read for its sample descriptions
and formation tops, saved as CSV.

Reports put the descriptions in a section headed "Sample Descriptions"
("w/ Formation Tops", "Detailed ...", "Lithology & Comments" ...), one
depth interval after another:

    812.5-835m: SANDSTONE (20%): light gray ...        interval, then text
    700-740  SHALE(85%) medium gray ...                interval column, text column
    790 - 810                                          interval on its own line,
    SHALE (60%) gray ...                               the text below it
    1181.4-  SHALE (75%): gray ...                     interval over two lines
    1205m    silty in part ...

and the formation tops between them or above them:

    Upper Shale: 512.40m MD, 505.1m TVD, 150.2m SS.
    Upper Shale at 471.20 m MD; (470.30 m TVD; +210.40 m SS)
    668.2  Lower Shale: 610.5 m TVD, +82.0 m MSL

A report whose section has no tops gets them from its formation tops
table ("Formation Top Summary": the Actual MD / TVD / SS columns) when
it has one. Points that are not formations (KOP, landing point, bottom
hole, sample point ...) are kept apart as markers.

Each interval is given the formation it lies in: the last top at or above
its top depth, "A / B" when a top falls inside it.
"""
import io
import csv
import os
import re

from survey_tool import find_uwi

_HEAD = re.compile(r"sample\s+desc|litholog(?:y|ical)\s*(?:&|and)?\s*comments?|"
                   r"lithological\s+desc|detailed\s+sample|sample\s+log\b", re.I)
_TOC = re.compile(r"table\s+of\s+contents|^\s*contents\s*$", re.I | re.M)
# a depth: 812.5  835m  1,205
_D = r"\d{1,2},?\d{2,3}(?:\.\d+)?|\d{2,4}(?:\.\d+)?"
_RANGE = re.compile(rf"^\s*({_D})\s*m?\s*(?:-|–|—|to)\s*({_D})\s*(?:m\s*MD|mMD|m)?\s*[:.]?\s*(.*)$",
                    re.I)
_OPEN = re.compile(rf"^\s*({_D})\s*m?\s*(?:-|–|—|to)\s*$", re.I)      # "1181.4-"
_CLOSE = re.compile(rf"^\s*({_D})\s*(?:m\s*MD|mMD|m)?\s*[:.]?\s*(.*)$", re.I)  # "1205m ..."
_NUMU = r"[-+]?\d{1,4}(?:,\d{3})*(?:\.\d+)?"
_TOP_NAME_FIRST = re.compile(
    rf"^\s*(?P<name>[A-Za-z][A-Za-z0-9 ./#&'()\-]*?)\s*(?::|\s+at\b|\s+@)\s*(?P<md>{_NUMU})\s*m?\s*"
    rf"(?:MD|mMD|KB)?\b(?P<rest>.*)$", re.I)
_TOP_MD_FIRST = re.compile(
    rf"^\s*(?P<md>{_NUMU})\s*m?\s+(?P<name>[A-Za-z][A-Za-z0-9 ./#&'()\-]*?)\s*:\s*(?P<rest>.*)$", re.I)
_TVD = re.compile(rf"({_NUMU})\s*m?\s*TVD", re.I)
_SS = re.compile(rf"({_NUMU})\s*m?\s*(?:SS|MSL|subsea|sub-sea)\b", re.I)
_MD = re.compile(rf"({_NUMU})\s*m?\s*MD\b", re.I)

_MARKERS = re.compile(
    r"^(kop|kick[\s-]*off(\s+point)?|landing(\s+point)?|lp|bottom\s*hole|bh|bhl|td|total\s+depth|"
    r"sample\s+point|target\s+entry(\s+point)?|tep|(intermediate|surface|production)?\s*casing"
    r"(\s+point)?|icp|core\s+point|heel|toe|end\s+of\s+build|eob|section\s+td|"
    r"start\s+of\s+lateral|lateral|build|curve|spud|drill\s*out|re-?entry|"
    r"ghost\s+hole|sidetrack(\s+point)?|whipstock|window|kick\s*off)\b", re.I)

CSV_SAMPLES = ["UWI", "Depth Range", "Description"]
CSV_TOPS = ["UWI", "Formation", "MD (m)", "TVD (m)", "SS (m)"]


class NotAReport(ValueError):
    pass


def _f(s):
    try:
        return float(str(s).replace(",", "").replace("+", ""))
    except ValueError:
        return None


def _lines(page, tol=3.0):
    """a page's text lines: [(y, x0, text, words)] top to bottom, words
    in one line when their middles are within tol points"""
    ws = [w for w in page.get_text("words") if w[4].strip()]
    ws.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows = []
    for w in ws:
        y = (w[1] + w[3]) / 2
        if rows and y - rows[-1][0] <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([y, [w]])
    out = []
    for y, line in rows:
        line.sort(key=lambda w: w[0])
        out.append((y, line[0][0], " ".join(w[4] for w in line), line))
    return out


def _clean_name(name):
    n = " ".join(name.split()).strip(" .:-;,")
    n = re.sub(r"\s*\b(formation\s+)?tops?\b\s*$", "", n, flags=re.I)
    n = re.sub(r"^top\s+(of\s+)?(?=[A-Za-z])", "", n, flags=re.I)
    parts = [p.strip() for p in re.split(r"\s*/\s*", n) if p.strip()]
    keep = [p for p in parts if not _MARKERS.match(p)]
    return (" / ".join(keep) if keep else n), not keep


def parse_top(text):
    """A formation top (or a marker) in a line of text -> {name, md, tvd,
    ss, marker}, or None."""
    t = " ".join(text.split())
    if len(t) > 140 or _RANGE.match(t):
        return None
    m = _TOP_NAME_FIRST.match(t)
    md = None
    if m and (re.search(r"\bMD\b|TVD|\bSS\b|MSL", t, re.I)):
        name, md, rest = m.group("name"), _f(m.group("md")), m.group("rest")
    else:
        m = _TOP_MD_FIRST.match(t)
        if not m or not re.search(r"TVD|\bSS\b|MSL|\bMD\b", m.group("rest"), re.I):
            return None
        name, md, rest = m.group("name"), _f(m.group("md")), m.group("rest")
    if md is None or not re.search(r"[A-Za-z]{2}", name):
        return None
    # a sentence ("Samples were caught at 5 m intervals ...") is not a top
    if len(name.split()) > 6:
        return None
    tvd = _TVD.search(rest)
    ss = _SS.search(rest)
    clean, marker = _clean_name(name)
    return {"name": clean, "md": md, "tvd": _f(tvd.group(1)) if tvd else None,
            "ss": _f(ss.group(1)) if ss else None, "marker": marker}


_OTHER = re.compile(r"\b(surveys?|deviation|directional|bit\s+(record|summary|data)|mud\s+(data|"
                    r"properties|record)|casing|daily|drilling\s+(summary|activity)|well\s*path|"
                    r"appendix|strip\s*log|slide\s+sheets?|time\s+(log|breakdown)|chromatograph|"
                    r"electric(al)?\s+logs?|work\s+schedule|well\s+(summary|abstract|data)|"
                    r"cross[\s-]+section|plots?)\b", re.I)


def _valid_ranges(text):
    n = 0
    for l in text.split("\n"):
        m = _RANGE.match(l)
        if m and _ok_range(_f(m.group(1)), _f(m.group(2))) and not _tabular(l):
            n += 1
        elif _OPEN.match(l) and (_f(_OPEN.match(l).group(1)) or 0) >= 50:
            n += 1
    return n


def _tabular(t):
    """a row of a table (a survey, a bit record): many numbers, few words"""
    toks = t.split()
    nums = sum(1 for x in toks if re.fullmatch(r"[-+]?[\d,]*\.?\d+%?", x))
    return nums >= 5 and nums >= 0.6 * len(toks)


def _section_pages(doc):
    """indexes of the pages of the sample description section(s): from a
    page headed as one, through the pages that go on with intervals (or
    tops), to the next page headed as something else"""
    pages, on = [], False
    for i, p in enumerate(doc):
        t = p.get_text()
        h = p.rect.height
        top = " ".join(w[4] for w in p.get_text("words") if w[1] < 0.22 * h)
        heading = bool(_HEAD.search(top)) and not _TOC.search(t) and "....." not in t
        ranges = _valid_ranges(t)
        if heading:
            on = True
        elif on:
            other = _OTHER.search(top) and not _HEAD.search(top)
            if other and ranges < 3:
                on = False                     # the next section
            elif ranges == 0 and not any(parse_top(l) for l in t.split("\n")):
                on = False                     # no intervals and no tops
        if on:
            pages.append(i)
    return pages


def _repeated(doc, pages):
    """header / footer lines: the same text near the top or bottom of two
    or more of the section's pages"""
    seen = {}
    for i in pages:
        p = doc[i]
        h = p.rect.height
        for y, x0, text, _ in _lines(p):
            if y < 0.13 * h or y > 0.9 * h:
                k = re.sub(r"\d+", "#", text.strip())
                seen.setdefault(k, set()).add(i)
    return {k for k, v in seen.items() if len(v) >= 2}


def read_pdf(data, name="report.pdf"):
    import fitz
    doc = fitz.open(stream=bytes(data), filetype="pdf")
    full = "\n".join(p.get_text() for p in doc)
    if not full.strip():
        raise NotAReport("The PDF has no text (a scan would need OCR).")
    uwi = find_uwi(full[:20000]) or find_uwi(os.path.basename(name))
    pages = _section_pages(doc)
    rep = _repeated(doc, pages)
    samples, tops, markers, notes = [], [], [], []
    cur = None

    def close():
        nonlocal cur
        if cur:
            cur["text"] = _join(cur["parts"])
            del cur["parts"]
            samples.append(cur)
        cur = None

    for i in pages:
        p = doc[i]
        h = p.rect.height
        for y, x0, text, words in _lines(p):
            t = " ".join(text.split())
            if not t:
                continue
            if (y < 0.13 * h or y > 0.9 * h) and re.sub(r"\d+", "#", t) in rep:
                continue
            if re.fullmatch(r"(page\s*)?\d{1,3}(\s*(of|/)\s*\d{1,3})?", t, re.I):
                continue
            if _HEAD.search(t) and len(t) < 70 and not _RANGE.match(t):
                continue                                   # the section's heading
            if re.fullmatch(r"(depth\s*(\(m\))?|interval)\s*(\(m\))?\s*(description|lithology.*)?", t,
                            re.I):
                continue                                   # a table's column names
            if _tabular(t):
                continue                                   # a table row, not text
            if len(t) <= 40 and re.fullmatch(r"[A-Za-z][A-Za-z &/#()\-]+", t) and _OTHER.search(t) \
                    and not _HEAD.search(t):
                close()                                    # another section's heading
                continue
            if cur is not None and cur["base"] is None:
                # the base of an interval begun on the line above
                m = _CLOSE.match(t)
                if m and _ok_range(cur["top"], _f(m.group(1))):
                    cur["base"] = _f(m.group(1))
                    cur["parts"].append(m.group(2))
                    continue
            m = _RANGE.match(t)
            if m and _ok_range(_f(m.group(1)), _f(m.group(2))):
                close()
                cur = {"top": _f(m.group(1)), "base": _f(m.group(2)), "parts": [m.group(3)]}
                continue
            # "1181.4- SHALE ..." or "790 -": the interval's base is on the
            # next line ("1205m silty ...")
            toks = t.split()
            head = None
            if _OPEN.match(t):
                head = t
            elif _OPEN.match(toks[0]):
                head = toks[0]
            elif len(toks) > 1 and toks[1] in ("-", "–", "—") and _OPEN.match(" ".join(toks[:2])):
                head = " ".join(toks[:2])
            if head and (_f(_OPEN.match(head).group(1)) or 0) >= 50:
                close()
                cur = {"top": _f(_OPEN.match(head).group(1)), "base": None,
                       "parts": [t[len(head):].strip()]}
                continue
            top = parse_top(t)
            if top:
                (markers if top["marker"] else tops).append(top)
                continue
            if re.fullmatch(r"[A-Z0-9 +&/#\-]+:", t) and len(t) < 60:
                continue                                   # "VERTICAL + BUILD SECTION:"
            if len(t) < 120 and re.search(rf":\s*{_NUMU}\s*m?\s*(TVD|MD)\b", t, re.I):
                continue                                   # a depth note ("Bit at TD: 705.3 m TVD")
            if cur is not None:
                cur["parts"].append(t)
            elif re.search(r"no samples", t, re.I):
                notes.append(t)
    close()
    samples = [s for s in samples if s["base"] is not None and s["text"]]
    tops_from = "section" if tops else None
    if not tops:
        tops = _tops_table(doc)
        tops_from = "table" if tops else None
    tops = _dedupe(tops)
    _formations(samples, tops)
    warnings = []
    if not pages:
        warnings.append("No sample descriptions section found in the report.")
    elif not samples:
        warnings.append(notes[0] if notes else "The sample descriptions section has no depth "
                        "intervals that could be read.")
    if not tops:
        warnings.append("No formation tops found in the report.")
    out = {"file": os.path.basename(name), "uwi": uwi, "samples": samples, "tops": tops,
           "markers": _dedupe(markers), "tops_from": tops_from,
           "pages": [i + 1 for i in pages], "warnings": warnings}
    out["samples_csv"] = samples_csv([out])
    out["tops_csv"] = tops_csv([out])
    return out


def _ok_range(a, b):
    return a is not None and b is not None and 50 <= a < b <= 9999 and b - a <= 1000


def _join(parts):
    text = ""
    for p in parts:
        p = " ".join(str(p).split())
        if not p:
            continue
        if text.endswith("-") and not text.endswith(" -"):
            text = text + p                     # a word broken over two lines
        else:
            text = (text + " " + p) if text else p
    return text.strip()


def _dedupe(tops):
    out, seen = [], set()
    for t in tops:
        k = (t["name"].lower(), round(t["md"], 1))
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return sorted(out, key=lambda t: t["md"])


def _formations(samples, tops):
    forms = sorted((t for t in tops if not t.get("marker")), key=lambda t: t["md"])
    for s in samples:
        at = [t for t in forms if t["md"] <= s["top"] + 0.01]
        inside = [t for t in forms if s["top"] + 0.01 < t["md"] < s["base"] - 0.01]
        names = ([at[-1]["name"]] if at else []) + [t["name"] for t in inside]
        s["formation"] = " / ".join(names)


def _tops_table(doc):
    """tops from a formation tops table: the row's name, and the numbers
    in the columns headed Actual MD / TVD / SS (or MD / TVD / SS)"""
    import survey_tool as st
    found = []
    for p in doc:
        h = p.rect.height
        top = " ".join(w[4] for w in p.get_text("words") if w[1] < 0.3 * h)
        if not re.search(r"formation\s+tops?|tops?\s+summary|geological\s+(?:tops|markers)", top, re.I):
            continue
        if _TOC.search(p.get_text()) or "....." in p.get_text():
            continue
        lines = _lines(p)
        # a formation's row: its name, then three or more numbers (not a
        # "KB: 702.1  GL: 697.6" line)
        rows = [(y, ws) for y, x0, t, ws in lines
                if re.match(r"^[A-Za-z]", t) and ":" not in t.split()[0]
                and sum(1 for w in ws if st._isnum(w[4])) >= 3]
        if len(rows) < 2:
            continue
        cols = st._columns([(y, ws) for y, ws in rows])
        if not cols:
            continue
        first = rows[0][0]
        head = [w for y, x0, t, ws in lines if first - 70 < y < first - 1 for w in ws]
        labels = {k: [] for k in range(len(cols))}
        for w in head:
            xc = (w[0] + w[2]) / 2
            k = min(range(len(cols)), key=lambda k: abs(xc - (cols[k]["x0"] + cols[k]["x1max"]) / 2))
            if cols[k]["x0"] - 14 <= xc <= cols[k]["x1max"] + 14:
                labels[k].append(w[4].lower())
        def heads(want, lab):
            """a column's label names it (MD, or written out: Measured Depth,
            True Vertical Depth, Mean Sea Level)"""
            w = set(re.findall(r"[a-z]+", lab))
            if want == "md":
                return "md" in w or "measured" in w
            if want == "tvd":
                return "tvd" in w or ("vertical" in w and "section" not in w)
            return "ss" in w or "msl" in w or "subsea" in w or "sea" in w
        def pick(want):
            best = None
            for k, ws in labels.items():
                lab = " ".join(ws)
                if not heads(want, lab):
                    continue
                score = 2 if "actual" in lab else 0 if "prog" in lab else 1
                if best is None or score > best[0]:
                    best = (score, k)
            return best[1] if best and best[0] >= 1 else None
        kmd, ktvd, kss = pick("md"), pick("tvd"), pick("ss")
        if kmd is None:
            continue
        for y, ws in rows:
            name = " ".join(w[4] for w in ws if not st._isnum(w[4]) and w[0] < cols[0]["x0"])
            # a name printed on the line below its numbers
            if not name:
                near = [t for yy, x0, t, wws in lines if abs(yy - y) < 8 and re.match(r"^[A-Za-z]", t)
                        and not any(st._isnum(w[4]) for w in wws)]
                name = near[0] if near else ""
            vals = {}
            for w in ws:
                if not st._isnum(w[4]):
                    continue
                k = min(range(len(cols)), key=lambda k: abs(w[2] - cols[k]["x1max"]))
                if abs(w[2] - cols[k]["x1max"]) <= 8:
                    vals[k] = st._num(w[4])
            md = vals.get(kmd)
            if not name or md is None:
                continue
            clean, marker = _clean_name(name)
            if marker:
                continue
            found.append({"name": clean, "md": md, "tvd": vals.get(ktvd) if ktvd is not None else None,
                          "ss": vals.get(kss) if kss is not None else None, "marker": False})
        if found:
            break
    return found


def _q(s):
    return '"' + str(s).replace('"', '""') + '"'


def samples_csv(reports):
    """UWI, Depth Range, Description; the description always in double
    quotes (a quote inside it doubled)."""
    buf = io.StringIO()
    buf.write(",".join(CSV_SAMPLES) + "\r\n")
    cw = io.StringIO()
    w = csv.writer(cw, lineterminator="")
    for r in reports:
        uwi = r.get("uwi") or os.path.splitext(r.get("file") or "")[0]
        for s in r["samples"]:
            cw.seek(0)
            cw.truncate()
            w.writerow([uwi, f"{_fmt(s['top'])}-{_fmt(s['base'])}"])
            buf.write(cw.getvalue() + "," + _q(s["text"]) + "\r\n")
    return buf.getvalue()


def tops_csv(reports):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_TOPS)
    for r in reports:
        uwi = r.get("uwi") or os.path.splitext(r.get("file") or "")[0]
        for t in r["tops"]:
            w.writerow([uwi, t["name"], _fmt(t["md"]), _fmt(t.get("tvd")), _fmt(t.get("ss"))])
    return buf.getvalue()


def _fmt(v):
    if v is None:
        return ""
    return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else f"{v:.1f}"


def read(data, name="report.pdf"):
    data = bytes(data)
    if data[:5] != b"%PDF-":
        raise NotAReport("The Geology tool reads a geologist's report PDF.")
    return read_pdf(data, name)


def api(req):
    """/api/geology: {data: base64, filename} -> (code, report or error)"""
    import base64
    try:
        data = base64.b64decode(req.get("data") or "")
    except Exception:  # noqa: BLE001
        return 400, {"error": "The file could not be read."}
    name = os.path.basename(req.get("filename") or "report.pdf")
    try:
        return 200, read(data, name)
    except NotAReport as e:
        return 422, {"error": str(e), "file": name}
    except Exception as e:  # noqa: BLE001
        return 422, {"error": f"Not read: {type(e).__name__}: {e}", "file": name}
