"""Directional Survey tool: a well's survey stations (MD, inclination,
azimuth) read from a survey report PDF or a plain table, the well path
worked out again by minimum curvature, and the stations saved as CSV.

A survey report PDF is read from its text: the station table's columns
come from where its numbers line up, and each column is named from the
header words above it ("Measured Depth", "Inc", "+N/-S" ...). Reports
repeat the table on every page and often add a short annotation table
(KOP, landing point, TD) beside a plot; the longest table family wins and
its pages are joined in MD order. A PDF whose text is in a font with no
readable characters is reported as such: there is no OCR here.

The path is worked out from MD, inclination and azimuth alone. When the
report gives TVD (and N/S, E/W) at its first station, that station is the
tie-in; otherwise the hole is taken as vertical from the surface to it.
The report's own TVD at each station is kept, so the tool can show how
far its TVD and ours differ: a report worked out by minimum curvature
agrees to a few centimetres.

Vertical section is along the closure azimuth: the direction from the
surface to the last station. Dogleg severity is in degrees per 30 m.
"""
import csv
import io
import math
import os
import re
import statistics

CSV_HEADER = ["UWI", "MD (m)", "Inc (deg)", "Azi (deg)", "TVD (m)", "N/S (m)",
              "E/W (m)", "DLS (deg/30 m)", "VS (m)"]
FT = 0.3048

# a number as a survey table prints it: 1,234.56  -0.95  12  .5
_NUM = re.compile(r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?$")


def _isnum(s):
    return bool(s) and any(c.isdigit() for c in s) and bool(_NUM.match(s))


def _num(s):
    return float(s.replace(",", ""))


# ---------------------------------------------------------------- the UWI
# 100/01-02-003-04W5/00, also written 100/1-2-3-4W5, 100/01-02-03-04W5M
_UWI_DLS = re.compile(r"(?<!\d)([1-9]\d\d)\s*/\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{2,3})\s*-\s*"
                      r"(\d{1,2})\s*W\s*(\d)\s*M?(?:\s*/\s*(\d{1,2}))?(?!\d)", re.I)
_UWI_16 = re.compile(r"(?<![0-9A-Z])([1-9]\d\d)(\d\d)(\d\d)(\d\d\d)(\d\d)W(\d)(\d\d)(?![0-9])", re.I)


def _uwi(m):
    a, lsd, sec, twp, rge, mer, ev = m.groups()
    return f"{a}/{int(lsd):02d}-{int(sec):02d}-{int(twp):03d}-{int(rge):02d}W{mer}/{int(ev or 0):02d}"


def find_uwi(text):
    """The well's Canadian DLS UWI in the text, as 100/01-02-003-04W5/00:
    one labelled UWI first, else the one the text gives most often (a
    report's own well is on every page; offset wells on a plot are not),
    else None."""
    if not text:
        return None
    for m in re.finditer(r"UWI\b", text, re.I):
        near = text[m.end():m.end() + 40]
        u = _UWI_DLS.search(near) or _UWI_16.search(near)
        if u:
            return _uwi(u)
    found = [_uwi(u) for u in _UWI_DLS.finditer(text)] or [_uwi(u) for u in _UWI_16.finditer(text)]
    if not found:
        return None
    count = {}
    for u in found:
        count[u] = count.get(u, 0) + 1
    return max(found, key=lambda u: (count[u], -found.index(u)))


# ------------------------------------------------------ minimum curvature
def min_curvature(stations, tie=None):
    """TVD, N/S, E/W and dogleg severity (deg/30 m) at each station, by
    minimum curvature, from MD (m), inclination and azimuth (degrees).

    tie: (tvd, ns, ew) at the first station; None = the hole is vertical
    from MD 0 down to it (so a first station at MD 0 starts at 0, 0, 0).
    Returns new dicts with tvd, ns, ew, dls set."""
    out = []
    if not stations:
        return out
    s0 = stations[0]
    if tie is not None:
        tvd, ns, ew = tie
        out.append(dict(s0, tvd=tvd, ns=ns, ew=ew, dls=0.0))
        prev = s0
    else:
        prev = {"md": 0.0, "inc": 0.0, "azi": s0["azi"]}
        tvd = ns = ew = 0.0
        if s0["md"] <= 0:
            out.append(dict(s0, tvd=0.0, ns=0.0, ew=0.0, dls=0.0))
            prev = s0
    for s in stations[len(out):]:
        dmd = s["md"] - prev["md"]
        i1, i2 = math.radians(prev["inc"]), math.radians(s["inc"])
        a1, a2 = math.radians(prev["azi"]), math.radians(s["azi"])
        c = math.cos(i2 - i1) - math.sin(i1) * math.sin(i2) * (1 - math.cos(a2 - a1))
        dl = math.acos(max(-1.0, min(1.0, c)))
        rf = 1.0 if dl < 1e-9 else 2.0 / dl * math.tan(dl / 2)
        ns += dmd / 2 * (math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2)) * rf
        ew += dmd / 2 * (math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2)) * rf
        tvd += dmd / 2 * (math.cos(i1) + math.cos(i2)) * rf
        dls = math.degrees(dl) / dmd * 30.0 if dmd > 0 else 0.0
        out.append(dict(s, tvd=tvd, ns=ns, ew=ew, dls=dls))
        prev = s
    return out


def closure_azimuth(path):
    """The direction (degrees from north) from the surface to the last
    station; 0 for a vertical hole."""
    if not path:
        return 0.0
    n, e = path[-1]["ns"], path[-1]["ew"]
    if abs(n) < 1e-9 and abs(e) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(e, n)) % 360.0


def add_vertical_section(path, azimuth):
    a = math.radians(azimuth)
    for s in path:
        s["vs"] = s["ns"] * math.cos(a) + s["ew"] * math.sin(a)
    return path


# --------------------------------------------------- the table's columns
def field_of(label, seen):
    """The survey field a column header names, or None. seen: the fields
    already taken on this table (a second bare "Depth" is the TVD)."""
    t = " ".join(label.lower().split())
    if not t:
        return None
    if "closure" in t or "departure" in t or "target" in t or "dip" in t:
        return None
    if "northing" in t or "easting" in t or "latitude" in t or "longitude" in t:
        return None
    if "annotation" in t or "comment" in t or "remark" in t:
        return "note"
    if "dogleg" in t or re.search(r"\bdls\b", t):
        return "dls"
    if "build" in t:
        return "build"
    if "turn" in t:
        return "turn"
    if "subsea" in t or "sub-sea" in t or re.search(r"\bss\b", t) or "elevation" in t \
            or "tvdss" in t:
        return "ss"
    if "section" in t or "vsect" in t or re.search(r"\bv\.?\s?s(ec)?\b", t):
        return "vs"
    if "n/s" in t or "n/-s" in t or re.search(r"\bnorth", t) or re.search(r"\bns\b", t):
        return "ns"
    if "e/w" in t or "e/-w" in t or re.search(r"\beast", t) or re.search(r"\bew\b", t):
        return "ew"
    if "tvd" in t or ("vertical" in t and "depth" in t) or "true vertical" in t:
        return "tvd"
    if "measured" in t or re.match(r"^md\b", t) or re.search(r"\bmd\b", t):
        return "md"
    if re.search(r"\binc", t):
        return "inc"
    if re.search(r"\baz", t) or "direction" in t or "azimuth" in t:
        return "azi"
    if re.match(r"^(\(?m\)?\s*)?depth\b", t) or t.startswith("depth"):
        return "tvd" if "md" in seen else "md"
    return None


def _feet(label):
    t = label.lower()
    return "(ft)" in t or re.search(r"\bft\b|\bfeet\b|\(usft\)", t) is not None


def _rows(words, tol=2.0):
    """words -> rows: [(y, [word, ...] by x)], merging bands tol apart."""
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows = []
    for w in words:
        y = (w[1] + w[3]) / 2
        if rows and y - rows[-1][0] <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([y, [w]])
    return [(y, sorted(ws, key=lambda w: w[0])) for y, ws in rows]


def _columns(data_rows):
    """Column extents from where the numbers of the data rows sit: numbers
    are right-aligned, so they are grouped by their right edge."""
    edges = sorted((w[2], w[0]) for _, ws in data_rows for w in ws if _isnum(w[4]))
    cols = []
    for x1, x0 in edges:
        if cols and x1 - cols[-1]["x1max"] <= 6:
            c = cols[-1]
            c["x1max"] = max(c["x1max"], x1)
            c["x0"] = min(c["x0"], x0)
            c["n"] += 1
        else:
            cols.append({"x1min": x1, "x1max": x1, "x0": x0, "n": 1})
    # a column has numbers on a good share of the rows
    need = max(2, len(data_rows) // 4)
    return [c for c in cols if c["n"] >= need]


def wws_all(block):
    """the numeric words of a block of rows"""
    return [w[4] for _, ws in block for w in ws if _isnum(w[4])]


OCR_DPI = 300


def _ocr_words(page, dpi=OCR_DPI):
    """the page's words read off its picture by Tesseract (a PDF whose text
    has no usable characters, or a scan with none): PyMuPDF's word tuples,
    in points, in the page's upright frame (the picture is drawn turned as
    the page is shown). [] when Tesseract is not to be found."""
    import fitz
    import numpy as np
    import auto_raster as ar
    if not ar.available():
        return []
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    k = 72.0 / dpi
    return [(w["x0"] * k, w["y0"] * k, w["x1"] * k, w["y1"] * k, w["text"]) + tuple(w["line"])
            for w in ar.ocr_boxes(img, psm=6, whitelist="") if w["text"].strip()]


def _ocr_text(words):
    """the words as lines of text (for the UWI, well name and the like)"""
    lines = {}
    for w in words:
        lines.setdefault(tuple(w[5:8]), []).append(w)
    return "\n".join(" ".join(x[4] for x in sorted(ws, key=lambda x: x[0]))
                     for _k, ws in sorted(lines.items(), key=lambda kv: (kv[1][0][1], kv[1][0][0])))


def _page_tables(page, words=None):
    """The station tables on one page: [{fields: {col: field}, rows: [...]}].
    words: the page's words read some other way (OCR), upright already."""
    if words is not None:
        return _tables_from_words(words)
    words = [w for w in page.get_text("words") if w[4].strip()]
    if page.rotation:
        # a page printed turned: its words in the page's upright frame
        import fitz
        m = page.rotation_matrix
        turned = []
        for w in words:
            r = fitz.Rect(w[:4]) * m
            turned.append((r.x0, r.y0, r.x1, r.y1) + tuple(w[4:]))
        words = turned
    return _tables_from_words(words)


def _tables_from_words(words):
    rows = _rows(words)
    out = []
    i = 0
    while i < len(rows):
        y, ws = rows[i]
        if sum(1 for w in ws if _isnum(w[4])) < 4:
            i += 1
            continue
        # a block of data rows (label rows such as "KOP" may sit between)
        j = i
        block = []
        while j < len(rows):
            yy, wws = rows[j]
            n = sum(1 for w in wws if _isnum(w[4]))
            if n >= 4:
                block.append(rows[j])
            elif n == 0 and len(" ".join(w[4] for w in wws)) < 40 and block and \
                    yy - block[-1][0] < 30:
                pass                                   # a label between rows
            else:
                break
            j += 1
        cols = _columns(block)
        if len(cols) >= 3:
            top = block[0][0]
            head = [w for (yy, wws) in rows if top - 50 < yy < top - 1 for w in wws
                    if not _isnum(w[4]) or re.fullmatch(r"\(?\d+\s*m\)?", w[4])]
            labels = {k: [] for k in range(len(cols))}
            for w in head:
                xc = (w[0] + w[2]) / 2
                best, bd = None, None
                for k, c in enumerate(cols):
                    lo, hi = c["x0"] - 10, c["x1max"] + 10
                    d = 0 if lo <= xc <= hi else min(abs(xc - lo), abs(xc - hi))
                    if d <= 12 and (bd is None or d < bd):
                        best, bd = k, d
                if best is not None:
                    labels[best].append(w)
            fields, seen, units = {}, set(), {}
            for k in range(len(cols)):
                lab = " ".join(w[4] for w in sorted(labels[k], key=lambda w: (round(w[1]), w[0])))
                f = field_of(lab, seen)
                if f and f not in seen:
                    fields[k] = f
                    seen.add(f)
                    units[f] = "ft" if _feet(lab) else "m"
            # no header words above (a page that runs on): the usual order
            if not fields and len(cols) >= 3:
                for k, f in enumerate(("md", "inc", "azi", "tvd")[:len(cols)]):
                    fields[k] = f
                    units[f] = "m"
                seen = set(fields.values())
                guessed = True
            else:
                guessed = False
            if {"md", "inc", "azi"} <= seen:
                got = []
                for yy, wws in block:
                    vals, note = {}, []
                    for w in wws:
                        if not _isnum(w[4]):
                            note.append(w[4])
                            continue
                        x1 = w[2]
                        k = min(range(len(cols)), key=lambda k: min(
                            abs(x1 - cols[k]["x1max"]), abs(x1 - cols[k]["x1min"])))
                        if min(abs(x1 - cols[k]["x1max"]), abs(x1 - cols[k]["x1min"])) > 8:
                            continue
                        f = fields.get(k)
                        if f and f not in vals:
                            vals[f] = _num(w[4])
                    if {"md", "inc", "azi"} <= set(vals):
                        if note:
                            vals["note"] = " ".join(note)
                        got.append(vals)
                mds = [r["md"] for r in got]
                rising = all(b > a for a, b in zip(mds, mds[1:]))
                # columns guessed with no header: only a run of real stations
                # (rising MD, decimals), not a plot's grid labels
                vals = [str(v) for r in got for k, v in r.items() if k != "note"]
                dec = sum(1 for w in wws_all(block) if "." in w) / max(1, len(vals))
                if got and rising and (not guessed or (len(got) >= 5 and dec >= 0.5)):
                    out.append({"sig": tuple(sorted(seen - {"note"})), "rows": got,
                                "units": units, "guessed": guessed})
        i = max(j, i + 1)
    return out


def _scrambled(text):
    """True when a PDF's text is mostly characters with no meaning (a font
    without a usable character map)."""
    t = [c for c in text if c not in " \n\r\t"]
    if len(t) < 50:
        return False
    bad = sum(1 for c in t if ord(c) < 32 or 0xE000 <= ord(c) <= 0xF8FF or c == "�")
    if bad / len(t) > 0.3:
        return True
    # plenty of text but none of a survey's words: the characters stand
    # for other letters (a font whose codes are not its letters)
    words = re.search(r"\b(depth|survey|azimuth|inclination|well|north|vertical)\b", text, re.I)
    return len(t) > 500 and not words and bad / len(t) > 0.05


def _first(rx, text):
    m = re.search(rx, text, re.I | re.M)
    return m.group(1).strip() if m else None


_BORE = re.compile(r"^[ \t]*(?:Wellbore|Well[ \t]*bore)[ \t]*:?[ \t]*(\S.*?)[ \t]*(?:Survey Calculation|"
                   r"North Reference|MD Reference|TVD Reference|Database|Local Co-?ordinate|$)", re.I | re.M)


def _bore(text):
    """the wellbore a page's header names, on the label's own line (a
    sidetrack's pages name theirs); None where the label stands alone or
    is followed by another label"""
    m = _BORE.search(text or "")
    if not m:
        return None
    v = re.sub(r"\s+", " ", m.group(1)).strip()
    return None if not re.search(r"[A-Za-z0-9]", v) or re.match(r"^[A-Za-z ]+:$", v) else v


def _same_bores(tables):
    """tables' wellbore names put together where they are one wellbore:
    names that differ only in spacing or punctuation, or whose tables do
    not cover the same depths (a table that carries on under a header
    worded another way). Two wellbores list the same depths over again: a
    sidetrack's report repeats the hole above its kick-off."""
    key = lambda b: re.sub(r"[^a-z0-9]", "", b.lower()) if b else ""     # "": pages before any name
    mds = {}
    for t in tables:
        mds.setdefault(key(t["bore"]), []).extend(r["md"] for r in t["rows"])
    names = [b for b in mds if mds[b]]
    same = {b: b for b in names}
    def root(b):
        while same[b] != b:
            b = same[b]
        return b
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            lo_a, hi_a, lo_b, hi_b = min(mds[a]), max(mds[a]), min(mds[b]), max(mds[b])
            inside = sum(1 for m in mds[b] if lo_a < m < hi_a) + sum(1 for m in mds[a] if lo_b < m < hi_b)
            if inside <= 3:
                same[root(b)] = root(a)
    label = {}
    for t in tables:
        k = key(t["bore"])
        if k in same and (t["bore"] or root(k) not in label):
            label[root(k)] = label.get(root(k)) or t["bore"]
    for t in tables:
        k = key(t["bore"])
        t["bore"] = label.get(root(k)) if k in same else t["bore"]
    return tables


def _tables_by_bore(doc, texts, words=None):
    """every page's station tables, each tagged with the wellbore its page
    names (a page that names none goes on with the one before it)"""
    out, bore = [], None
    for i, p in enumerate(doc):
        bore = _bore(texts[i]) or bore
        for t in _page_tables(p, words[i] if words is not None else None):
            t["bore"] = bore
            out.append(t)
    return _same_bores(out)


def _ocr_ready():
    try:
        import auto_raster as ar
        return ar.available()
    except Exception:  # noqa: BLE001 - no numpy / Pillow: no OCR
        return False


def read_pdf(data, name="survey.pdf"):
    """A survey report PDF -> the survey (see read())."""
    import fitz
    doc = fitz.open(stream=bytes(data), filetype="pdf")
    texts = [p.get_text() for p in doc]
    text = "\n".join(texts)
    tables = _tables_by_bore(doc, texts)
    warnings = []
    ocr_read = False
    scrambled = _scrambled(text)
    textless = len(text.split()) < 20 * len(doc)          # a scan: next to no text of its own
    if not tables and (scrambled or textless):
        # the pages' pictures read instead (the EXE carries Tesseract)
        ocr = [_ocr_words(p) for p in doc]
        tables = _tables_by_bore(doc, [_ocr_text(w) for w in ocr], ocr)
        if tables:
            ocr_read = True
            text = "\n".join(_ocr_text(words) for words in ocr)
            warnings.append("The PDF's text " + ("is in a font with no readable characters" if scrambled
                            else "is a picture (a scan)") + ", so its table was read by OCR: "
                            "check the stations against the report.")
    if not tables:
        if scrambled:
            raise NotASurvey("The PDF's text is in a font with no readable characters, so its "
                             "table cannot be read" + ("." if _ocr_ready() else " (it would need OCR)."))
        raise NotASurvey("No survey station table (MD, inclination, azimuth) found in the PDF.")
    # the family of tables with the most rows (the station table on every
    # page), not the short annotation tables beside a plot; a report of
    # more than one wellbore (an original hole and its sidetrack) keeps
    # each one's tables apart
    fam = {}
    for t in tables:
        fam.setdefault((t["sig"], t["bore"]), []).append(t)
    best = max(fam.values(), key=lambda ts: (sum(len(t["rows"]) for t in ts),
                                             len(ts[0]["sig"])))
    bore = best[0]["bore"]
    bores = sorted({t["bore"] for t in tables if t["bore"] and len(t["rows"]) >= 5})
    if len(bores) > 1:
        warnings.append("The report holds the surveys of %d wellbores (%s): the one with the most "
                        "stations (%s) is used." % (len(bores), "; ".join(bores), bore))
    tables = [t for t in tables if t["bore"] == bore]
    units = best[0]["units"]
    rows = sorted((r for t in best for r in t["rows"]), key=lambda r: r["md"])
    # a page whose table came out with other columns (no header above it,
    # say) fills a gap the main table leaves; it does not add stations
    # between the main table's own
    mds = [r["md"] for r in rows]
    steps = sorted(b - a for a, b in zip(mds, mds[1:]) if b > a)
    gap = max(60.0, 3 * steps[len(steps) // 2]) if steps else 60.0
    extra = []
    for t in tables:
        if any(t is b for b in best):
            continue
        for r in t["rows"]:
            k = next((i for i, m in enumerate(mds) if m > r["md"]), None)
            lo = mds[k - 1] if k else None
            hi = mds[k] if k is not None else None
            if (lo is None or hi is None or hi - lo > gap) and \
                    all(abs(r["md"] - m) > 0.5 for m in mds):
                extra.append(r)
    if extra:
        rows = sorted(rows + extra, key=lambda r: r["md"])
    seen, stations = set(), []
    for r in rows:
        k = round(r["md"], 2)
        if k in seen:
            continue
        seen.add(k)
        stations.append(r)
    if any(t["guessed"] for t in best):
        warnings.append("Some pages had no column names above the table: their columns were "
                        "taken as MD, inclination, azimuth, TVD.")
    uwi = find_uwi(bore or "") or find_uwi(text)         # a sidetrack's label carries its own UWI
    in_name = find_uwi(os.path.basename(name))
    if uwi and in_name and uwi != in_name:
        warnings.append(f"The report's UWI ({uwi}) is not the one in the file name ({in_name}): "
                        "the report's is used.")
    uwi = uwi or in_name
    well = _first(r"^\s*Well(?:\s*Name)?\s*:\s*(.+)$", text)
    vs_az = _first(r"Vertical Section (?:at|Azimuth\s*:?)\s*([\d.]+)", text)
    final = re.search(r"\bfinal\b", text[:3000], re.I) is not None
    return _finish(stations, units, name, uwi, well, "pdf", warnings,
                   report_vs_azimuth=float(vs_az) if vs_az else None, final=final, ocr=ocr_read)


def read_table(text, name="survey.csv"):
    """A plain CSV / TXT survey table -> the survey (see read()). The first
    row naming MD, inclination and azimuth is the header; with none, the
    columns are taken as MD, Inc, Azi[, TVD]."""
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    if not lines:
        raise NotASurvey("The file is empty.")
    sample = "\n".join(lines[:20])
    delim = "\t" if "\t" in sample else ";" if sample.count(";") > sample.count(",") else \
        "," if "," in sample else None
    def split(l):
        return [c.strip().strip('"') for c in (l.split(delim) if delim else l.split())]
    uwi = None
    head, start, fields, units = None, 0, {}, {}
    for i, l in enumerate(lines[:30]):
        cells = split(l)
        if not uwi:
            uwi = find_uwi(l)
        seen = set()
        f = {}
        for k, c in enumerate(cells):
            g = field_of(c, seen)
            if g and g not in seen and g != "note":
                f[k] = g
                seen.add(g)
                units[g] = "ft" if _feet(c) else "m"
        if {"md", "inc", "azi"} <= seen:
            head, start, fields = cells, i + 1, f
            break
    uwi_col = None
    if head:
        for k, c in enumerate(head):
            if c.strip().upper() == "UWI":
                uwi_col = k
    else:
        fields = {0: "md", 1: "inc", 2: "azi", 3: "tvd"}
        units = {f: "m" for f in fields.values()}
        start = 0
    stations = []
    for l in lines[start:]:
        cells = split(l)
        vals = {}
        for k, f in fields.items():
            if k < len(cells) and _isnum(cells[k]):
                vals[f] = _num(cells[k])
        if {"md", "inc", "azi"} <= set(vals):
            stations.append(vals)
            if uwi_col is not None and not uwi and uwi_col < len(cells):
                uwi = find_uwi(cells[uwi_col]) or cells[uwi_col] or None
    if not stations:
        raise NotASurvey("No survey stations (MD, inclination, azimuth) found in the table.")
    stations.sort(key=lambda r: r["md"])
    uwi = uwi or find_uwi(os.path.basename(name))
    return _finish(stations, units, name, uwi, None, "table", [])


class NotASurvey(ValueError):
    pass


def _finish(stations, units, name, uwi, well, source, warnings, report_vs_azimuth=None,
            final=None, ocr=False):
    # feet to metres
    for f, u in units.items():
        if u == "ft" and f in ("md", "tvd", "ns", "ew", "vs", "ss"):
            for s in stations:
                if f in s:
                    s[f] *= FT
    if any(u == "ft" for f, u in units.items() if f in ("md", "tvd")):
        warnings.append("The table is in feet: depths and offsets are converted to metres.")
    for s in stations:
        s["azi"] = s["azi"] % 360.0
    bad = [s for s in stations if not (0 <= s["inc"] <= 180)]
    if bad:
        warnings.append(f"{len(bad)} stations with an inclination outside 0-180 degrees were "
                        "left out.")
        stations = [s for s in stations if 0 <= s["inc"] <= 180]
    rep = [{k: s.get(k) for k in ("tvd", "ns", "ew", "vs", "dls")} for s in stations]
    base = [{"md": s["md"], "inc": s["inc"], "azi": s["azi"],
             **({"note": s["note"]} if s.get("note") else {})} for s in stations]
    s0 = stations[0]
    tie = None
    if s0.get("tvd") is not None and s0["md"] > 0:
        tie = (s0["tvd"], s0.get("ns") or 0.0, s0.get("ew") or 0.0)
    path = min_curvature(base, tie)
    az = closure_azimuth(path)
    add_vertical_section(path, az)
    for s, r in zip(path, rep):
        s["rep"] = {k: v for k, v in r.items() if v is not None}
    if ocr:
        # OCR drops a thin minus sign now and then: a report's offset that is
        # the path's own with the sign turned is that, not a disagreement
        signs = 0
        for s in path:
            for k in ("ns", "ew", "vs"):
                v = s["rep"].get(k)
                if v is not None and abs(s[k]) > 0.05 and abs(v - s[k]) > 0.05 and abs(v + s[k]) <= 0.02:
                    s["rep"][k] = -v
                    signs += 1
        if signs:
            warnings.append(f"OCR left the minus sign off {signs} of the report's offsets: they are "
                            "put back where the path agrees with them but for the sign.")
    diffs = [s["tvd"] - s["rep"]["tvd"] for s in path if "tvd" in s["rep"]]
    hd = [math.hypot(s["ns"] - s["rep"]["ns"], s["ew"] - s["rep"]["ew"]) for s in path
          if "ns" in s["rep"] and "ew" in s["rep"]]
    check = None
    if diffs:
        check = {"n": len(diffs), "tvd_max": max(abs(d) for d in diffs),
                 "tvd_median": statistics.median(abs(d) for d in diffs),
                 "tvd_end": diffs[-1],
                 "offset_max": max(hd) if hd else None}
    if s0["md"] > 0 and tie is None:
        warnings.append(f"The survey starts at {s0['md']:.1f} m MD with no TVD given there: "
                        "the hole is taken as vertical from the surface to it.")
    out = {"file": os.path.basename(name), "uwi": uwi, "well": well, "source": source,
           "stations": path, "closure_azimuth": az, "report_vs_azimuth": report_vs_azimuth,
           "tie": "report" if tie else "surface", "check": check, "warnings": warnings,
           "final": final,
           "md_range": [path[0]["md"], path[-1]["md"]] if path else None,
           "reach": math.hypot(path[-1]["ns"], path[-1]["ew"]) if path else 0.0}
    out["csv"] = to_csv([out])
    return out


def _r(v, nd):
    return "" if v is None else f"{v:.{nd}f}"


def to_csv(surveys):
    """One CSV for one or more surveys: UWI, MD, Inc, Azi, TVD, N/S, E/W,
    DLS, VS, units in the header."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for s in surveys:
        uwi = s.get("uwi") or os.path.splitext(s.get("file") or "")[0]
        for p in s["stations"]:
            w.writerow([uwi, _r(p["md"], 2), _r(p["inc"], 2), _r(p["azi"], 2),
                        _r(p["tvd"], 2), _r(p["ns"], 2), _r(p["ew"], 2), _r(p["dls"], 2),
                        _r(p["vs"], 2)])
    return buf.getvalue()


def read(data, name="survey"):
    """A survey file (PDF report, or a CSV / TXT table) -> {file, uwi,
    well, source, stations [{md, inc, azi, tvd, ns, ew, dls, vs, rep, note}],
    closure_azimuth, report_vs_azimuth, tie, check, warnings, csv}.
    Raises NotASurvey with a plain reason when no survey is in it."""
    data = bytes(data)
    if data[:5] == b"%PDF-":
        return read_pdf(data, name)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return read_table(text, name)


def api(req):
    """/api/survey: {data: base64, filename} -> (code, survey or error)"""
    import base64
    try:
        data = base64.b64decode(req.get("data") or "")
    except Exception:  # noqa: BLE001
        return 400, {"error": "The file could not be read."}
    name = os.path.basename(req.get("filename") or "survey")
    try:
        return 200, read(data, name)
    except NotASurvey as e:
        return 422, {"error": str(e), "file": name}
    except Exception as e:  # noqa: BLE001
        return 422, {"error": f"Not read: {type(e).__name__}: {e}", "file": name}
