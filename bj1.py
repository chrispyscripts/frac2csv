"""BJ / Baker Hughes chart template (BJ-1 in Carmine's codes).

One vector chart page per stage: title "UWI - Well X - Stage NN", time
axis labeled "Mon-DD HH:MM" (slanted black spans), stacked y-axes whose
numeric tick columns sit left/right of the plot with rotated axis-name
spans beside them (a shared axis names two series in one span). Legend
names are black text with a colored dash stroke to the left, so the
color↔series map comes from the dash nearest each name (Canyon-style).
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta, _resample

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
TIME_RE = re.compile(r"([A-Z][a-z]{2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")


# A well is named two ways in this corpus and the template must know both.
# DLS  "100/12-15-081-18W6"      — the prairie township grid
# NTS  "200/C-022-C-094-G-01"    — northeast BC, and what 01215 prints
# Requiring the DLS form alone failed detect on every page of an NTS-named
# filing, so 35 chart pages read as nothing and the file came back tables-only
# (#371, "there are charts stages for these BJ that are only reporting
# tables"). "Stage" and a time label still have to be on the page too.
# ...and the separator after the licence prefix is a slash on some filings and
# a HYPHEN on others: 00633 titles its charts "100-12-27-079-16W6 - Well D -
# Stage 03 Plug Wash" and matched nothing, so its 10 chart pages read as an
# empty file with no failure note at all — detect simply never fired.
# ...and the township is printed with its leading zero dropped on some
# filings: 00634 titles its charts "102-09-28-79-16W6 - Well E - Stage 01"
# where every table on the same book says 102/09-28-079-16W6/00. Two digits
# matched nothing, so its four chart pages were skipped as schematics and the
# file came back empty (#644). The UWI is padded back to three below.
# the 2022 Chevron books (00440-00442) print the meridian in lower case,
# "100/14-31-062-16w5 - Well 5 - Stage 01"; the id is the same id
_WELL_ID = re.compile(r"\d{3}[-/]\d{2}-\d{2}-\d{2,3}-\d{2}[Ww]\d"
                      r"|\d{3}[-/][A-Z]-\d{3}-[A-Z]-\d{3}-[A-Z]-\d{2}")


def unnumbered_title(page):
    """The title of a BJ chart page that names no stage -> the line, or None.

    00634 p72-73 are titled "102-09-28-79-16W6 - Well E - plug erosion":
    a well id, the word Well, a time axis, and no stage. Not a treatment
    stage and not read as one — but not a schematic either, and the skip
    note should say what it is.
    """
    t = page.get_text()
    if TIME_RE.search(t) is None:
        return None
    for line in t.splitlines():
        if " - Well " in line and "Stage" not in line \
                and _WELL_ID.search(line) is not None:
            return line.strip()
    return None


def parse_title(text):
    """-> (uwi, stage) from the chart title's well id and stage number, or
    ("", "") when the text has neither shape."""
    m = re.search(r"(\d{3})[-/](\d{2})-(\d{2})-(\d{2,3})-(\d{2})[Ww](\d)"
                  r".*?Stage\s*(\d+)", text, re.S)
    if m:
        g = list(m.groups()[:6])
        g[3] = g[3].zfill(3)               # "79" on the title, 079 on the well
        return "{}{}{}{}{}W{}00".format(*g), str(int(m.group(7)))
    # The NTS-named filings ("200/C-022-C-094-G-01 - Well D - Stage 14")
    # matched neither half of that pattern, so every chart came back as
    # stage "?" even once detect let them through (#371). The UWI is the
    # id with its separators dropped, which is the same shape the DLS
    # branch above builds and what canon_uwi would make of it anyway.
    mn = re.search(r"(\d{3})[-/]([A-Z]-\d{3}-[A-Z]-\d{3}-[A-Z]-\d{2})"
                   r".*?Stage\s*(\d+)", text, re.S)
    if mn:
        return mn.group(1) + re.sub(r"-", "", mn.group(2)) + "00", str(int(mn.group(3)))
    return "", ""


def detect(page):
    """Is this a BJ-1 chart page?

    The well id and the word Stage have to share ONE LINE, because that line
    is the chart's own title: "100-12-27-079-16W6 - Well D - Stage 01". The
    time label stays a whole-page test — it is down the axis, not in the
    title. Asked of the page as a whole all three marks are evidence of
    nothing: a spreadsheet printed to PDF carries hundreds of rows and dozens
    of columns, and somewhere among them is a well id, the word Stage and a
    Mon-DD HH:MM. That is the whole of what
    fired on the last page of 00440, 00441, 00442, 00443 and 00461: the final
    sheet of each is an Excel dump 1,545 lines long, it was read as a chart,
    it failed with "time labels not found", and the failure was the only
    thing those five files ever produced.

    Measured before changing: over the 11 files in the corpus that actually
    yield BJ charts, all 878 detected pages carry the combined title line and
    none is lost. All five spreadsheet pages lose it.
    """
    t = page_text(page)
    if is_jobmaster(t):
        return True
    if TIME_RE.search(t) is None:
        return False                   # no time axis anywhere on the page
    return any("Stage" in line and _WELL_ID.search(line) is not None
               for line in t.splitlines())


def _rgb(c):
    """A span's colour as the (r, g, b) triple drawings use, rounded 2."""
    try:
        c = int(c)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)
    return tuple(round(((c >> sh) & 255) / 255.0, 2) for sh in (16, 8, 0))


def _upright(page):
    """The matrix that stands a rotated page up, or None.

    The JobMaster books (BJ, 2019 Duvernay) are landscape pages stored
    portrait with /Rotate 90: the viewer shows them upright, but every
    span and drawing comes back in the stored frame, time running DOWN the
    page. Everything here is read in the frame the viewer shows.
    """
    if page.rotation:
        return page.rotation_matrix
    # 00030 (Husky, Spirit River) draws the landscape chart SIDEWAYS inside
    # an upright page with no /Rotate at all: "Elapsed Time (min)" runs up
    # the page and the tick ladders sit in rows. The caption's own line
    # direction says which way the content is turned; the matrix stands it
    # up exactly as rotation_matrix would.
    d = _content_dir(page)
    if d is None:
        return None
    W, H = page.rect.width, page.rect.height
    if d[1] < 0:                                 # text runs upward
        return fitz.Matrix(0, 1, -1, 0, H, 0)    # (x, y) -> (H - y, x)
    return fitz.Matrix(0, -1, 1, 0, 0, W)        # (x, y) -> (y, W - x)


def _content_dir(page):
    """The direction of the "Elapsed Time" caption's line when it is not
    horizontal — (0, -1) or (0, 1) — else None."""
    try:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                if any("Elapsed Time" in _unshift(sp["text"]) for sp in line["spans"]):
                    d = line.get("dir", (1.0, 0.0))
                    return None if abs(d[0]) >= 0.5 else (0.0, -1.0 if d[1] < 0 else 1.0)
    except Exception:
        return None
    return None


# 00030 (Husky, Spirit River) embeds its JobMaster font with every character
# code 29 below the character it draws: "JobMaster" arrives as "-RE0DVWHU",
# "Zone 1" as "=RQH\x03\x14". The page's OTHER fonts are normal, so the page
# does not read as garbled and no OCR fires; the title, the tick labels and
# the axis names are all in the shifted font. Adding 29 to every code puts
# the text back, and only a span that holds control characters is touched.
_SHIFT = 29


def _unshift(t):
    """A span's text with the +29 font offset undone, or the text itself."""
    if not t or not any(ord(c) < 32 and c not in "\n\r\t" for c in t):
        return t
    out = "".join(chr(ord(c) + _SHIFT) for c in t)
    return out if all(c.isprintable() for c in out) else t


def _garbled(page):
    """A page whose text layer is not text (00575: a Type0 font with no
    character map, every span control characters)."""
    try:
        import ocr_labels
        return ocr_labels.garbled(page)
    except Exception:
        return False


# A JobMaster chart page carries thirty to sixty spans. A daily-report
# page in the same character-less font carries hundreds, and reading each
# one off the ink is a tesseract call apiece — 00584 spent its whole
# 1,500 s budget on such pages before reaching a chart. Past this many
# spans a garbled page is not a chart and is left unread.
JM_OCR_MAX_SPANS = 120


def _spans(page):
    out = []
    M = _upright(page)
    garbled = _garbled(page)
    if garbled:
        import ocr_labels
        n_spans = sum(len(l["spans"]) for b in page.get_text("dict")["blocks"]
                      if b.get("type") == 0 for l in b.get("lines", []))
        if n_spans > JM_OCR_MAX_SPANS:
            return out
    raw = [(span, line.get("dir", (1.0, 0.0)))
           for block in page.get_text("dict")["blocks"]
           for line in block.get("lines", []) for span in line["spans"]]
    texts = [_unshift(span["text"]).strip() for span, _d in raw]
    if garbled:
        # the box and colour are the page's; the text is read off the
        # ink, because the font names no characters — all spans in one
        # tesseract call (ocr_labels.span_texts)
        want = [k for k, t in enumerate(texts) if t]
        got = ocr_labels.span_texts(page, [(raw[k][0]["bbox"], raw[k][1]) for k in want])
        for k, t in zip(want, got):
            texts[k] = t
    for (span, _d), t in zip(raw, texts):
        if True:
            if True:
                if t:
                    r = fitz.Rect(span["bbox"])
                    if M is not None:
                        r = (r * M).normalize()
                    x0, y0, x1, y1 = r
                    out.append({"t": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                                "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                                "color": _rgb(span.get("color", 0))})
    return out


def _drawings(page):
    """page.get_drawings(), stood upright on a rotated page."""
    drawings = page.get_drawings()
    M = _upright(page)
    if M is None:
        return drawings
    out = []
    for d in drawings:
        e = dict(d)
        e["rect"] = (d["rect"] * M).normalize()
        items = []
        for it in d["items"]:
            kind = it[0]
            if kind in ("l", "c"):
                items.append((kind,) + tuple(p * M for p in it[1:]))
            elif kind == "re":
                items.append((kind, (it[1] * M).normalize()) + tuple(it[2:]))
            elif kind == "qu":
                items.append((kind, it[1] * M) + tuple(it[2:]))
            else:
                items.append(it)
        e["items"] = items
        out.append(e)
    return out


# BJ's JobMaster charts (2019 Duvernay): one page per zone, titled "Well 2
# Zone 1" under a "Well Name: 102/05-26-062-21W5" header, plotted against
# "Elapsed Time (min)" with no clock and no legend — each series is named
# by its axis title, printed in the series' own colour.
# 2019: "Well 2 Zone 1" under "Well Name: 102/05-26-062-21W5". 2018 (00575,
# Rife): "RIFE 100/01-24 Zone 6" under "UWI: 100/01-24-032-24W4" — the
# well named by its operator and location, no "Well N".
# Murphy's books (00017, 00018) say "Well A interval 1" / "Well B Interval
# 3" for the same page; zone and interval are the same word here.
# Husky's (00106): "Husky 100/06-24-048-19W5 Frac #2", and the aborted run
# "… Frac #2 Ball Seat Attempt" — the qualifier stays in the stage key, as
# it does for "- Stage 06 Plug Slip" below, so the attempt and the frac
# stay separate charts.
# Vesta's 2018 Joffre books (00071, 00136, 00143) write "Zone #1"; Chevron's
# 2019 pad (00191-00196) writes "102/16-11-062-22W5  Well 3 - Stage 1".
_JM_ZONE = re.compile(r"\bWell\s+(\d+)\s+(Zone|Interval)\s*#?\s*(\d+)\b", re.I)
_JM_ZONE_2018 = re.compile(r"^\s*(\S.{0,40}?)\s+(Zone|Interval|Int|Frac|Stage)\s*#?\s*(\d+)\b"
                           r"\s*([A-Za-z][A-Za-z0-9 ]{0,30})?\s*$", re.M | re.I)
# "Well Name: 102/05-26-062-21W5" — or "Well Name: VESTA SYLAKE 100/10-20-
# 037-01W5" (00009) and "Well Name: 16-14-064-21W5 100/10-22-064-21W5"
# (00017): the UWI is somewhere on the line, not necessarily first
# the township is two digits on 00071's "102/01-27-37-01W5" and 00136's
# "100/08-06-40-27W4"; the UWI wants three (037, 040), as parse_title does
_JM_WELL = re.compile(r"Well Name:[^\n]*?(\d{3})/(\d{2})-(\d{2})-(\d{2,3})-(\d{2})W(\d)")
_JM_UWI = re.compile(r"UWI:\s*(\d{3})/(\d{2})-(\d{2})-(\d{2,3})-(\d{2})W(\d)")


def _jm_uwi(m):
    g = list(m.groups())
    g[3] = g[3].zfill(3)
    return "{}{}{}{}{}W{}00".format(*g)


def jm_title(text, word=False):
    """-> (well label, zone number) from a JobMaster page's title line, or
    None: ("Well 2", 1) for the 2019 books, ("RIFE 100/01-24", 6) for 2018.
    With `word`, two more: the page's own word for the stage — "Zone",
    "Interval" (Murphy's 00017/00018), "Frac #" (Husky's 00106) — and the
    qualifier printed after the number ("Ball Seat Attempt"), or ""."""
    z = _JM_ZONE.search(text)
    if z:
        out = (f"Well {int(z.group(1))}", int(z.group(3)))
        return out + (z.group(2).capitalize(), "") if word else out
    z = _JM_ZONE_2018.search(text)
    if z:
        # "Vesta 100/10-20  Well 1 - Zone 1" (00009), "102/04-26-062-21W5
        # Well1 Zone 1" (00015): the label plain, the well's own number
        # spaced and the dash before the zone dropped
        well = re.sub(r"\s*-\s*$", "", " ".join(z.group(1).split()))
        well = re.sub(r"\bWell(\d+)\b", r"Well \1", well)
        out = (well, int(z.group(3)))
        w = z.group(2)
        w = "Frac #" if w.lower().startswith("frac") else w.capitalize()
        if w == "Int":
            w = "Interval"                   # JobMaster 5.00 abbreviates (00232)
        if "#" in z.group(0) and w != "Frac #":
            w += " #"                        # "Zone #1" keeps its own spelling
        return out + (w, " ".join((z.group(4) or "").split())) if word else out
    return None


def page_text(page, spans=None):
    """The page's text — its own, or the OCR of each span's box when the
    font names no characters (see _spans)."""
    if not _garbled(page):
        # unshifted span by span: 00030's "Well Name:" line mixes a normal
        # font with the shifted one, and shifting the whole line would turn
        # the normal half into printable nonsense
        try:
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    t = "".join(_unshift(sp["text"]) for sp in line["spans"])
                    if t.strip():
                        lines.append(t)
            return "\n".join(lines)
        except Exception:
            return page.get_text()
    if spans is None:
        spans = _spans(page)
    return "\n".join(s["t"] for s in spans)
_JM_START = re.compile(r"Job Start:\s*(?:\w+,\s*)?([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})")


def is_jobmaster(text):
    return "JobMaste" in text and "Elapsed Time" in text and jm_title(text) is not None


def _fit(pairs):
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    A = np.vstack([np.ones_like(c), c]).T
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(a), float(b)


def _doc_year_map(doc):
    """{(month, day): year} harvested from full 'YYYY-MM-DD' dates anywhere
    in the document — the frac charts label only 'Mon-DD', so the year comes
    from the per-stage data tables. Cached on the document."""
    cached = getattr(doc, "_bj1_year_map", None)
    if cached is not None:
        return cached
    m = {}
    for p in range(len(doc)):
        text = doc[p].get_text()
        for mo in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text):
            m[(int(mo.group(2)), int(mo.group(3)))] = int(mo.group(1))
        # the 2022 Chevron books (00440-00442) date their daily reports
        # "8/23/2022" and their summary "August 11, 2022" and print no ISO
        # date anywhere, so every chart landed in 2000
        for mo in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text):
            m[(int(mo.group(1)), int(mo.group(2)))] = int(mo.group(3))
        for mo in re.finditer(r"\b([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s*(20\d{2})\b", text):
            mon = MONTHS.get(mo.group(1)[:3])
            if mon:
                m[(mon, int(mo.group(2)))] = int(mo.group(3))
    try:
        doc._bj1_year_map = m
    except Exception:
        pass
    return m


def filename_year(name):
    """Year from a COMP filename ('..._COMP_2024JAN22_...') — survives the
    Lab's client-side page chunking, where the chart page and the dated
    tables can land in different chunks."""
    if not name:
        return None
    m = re.search(r"COMP[_-]?(20\d{2})", name) or re.search(r"\b(20\d{2})\b", name)
    return int(m.group(1)) if m else None


def _resolve_year(doc, mon, day):
    """Best year for a chart's start (month, day): an exact date-table match
    first; then the filename COMP-date hint (more reliable than a chunk that
    may hold only drilling-era dates under the Lab's page splitting); then
    the most common year in the doc; else 2000."""
    ymap = _doc_year_map(doc)
    if (mon, day) in ymap:
        return ymap[(mon, day)]
    hint = getattr(doc, "_bj1_year_hint", None)
    if hint:
        return hint
    if ymap:
        years = list(ymap.values())
        return max(set(years), key=years.count)
    return 2000


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    text = page_text(page, spans)

    meta = PageMeta()
    uwi, stage = parse_title(text)
    if uwi:
        meta.uwi, meta.stage = uwi, stage
    title = next((s["t"] for s in spans if " - Stage" in s["t"]), "")
    meta.title = title[:60]
    jobmaster = is_jobmaster(text)
    if jobmaster:
        well, zone, word, qual = jm_title(text, word=True)
        w = _JM_WELL.search(text) or _JM_UWI.search(text)
        if w is None:
            # 00232's "Well Name: 15-01-62-19W5 11-14-62-19W5" names no
            # UWI; the title "100/11-14-62-19W5 Well 6 Int 4" does
            w = re.search(r"(\d{3})/(\d{2})-(\d{2})-(\d{2,3})-(\d{2})[Ww](\d)", well)
        meta.stage = f"{zone} {qual}" if qual else str(zone)
        meta.title = f"{well} {word}{'' if word.endswith('#') else ' '}{zone}" + (f" {qual}" if qual else "")
        if w:
            meta.uwi = _jm_uwi(w)

    # A stage can be charted MORE THAN ONCE. BJ names the aborted run in the
    # title — "- Stage 06 Plug Slip", "- Stage 17 HRF", "- Stage 41 Winterize"
    # — and numbers a re-pump "- Stage 10.1"; the treatment that actually
    # counts keeps the bare "- Stage 06". Reading the number alone filed both
    # under one stage, and every consumer merges same-stage charts by sample
    # index (pipeline_export.build_well, the Lab's stageItems). A 10-minute
    # plug slip and the 96-minute frac that followed it therefore fused into
    # one block: rate and pressure came from the slip, the concentrations from
    # the frac, over a row count belonging to neither — the plot filled a tenth
    # of a 96-minute grid and the header read "10 min · 5,758 samples".
    # Keep the printed suffix in the stage key so each treatment stays its own
    # chart, exactly as Liberty does for "Attempt 1/2" and STEP for "1.2".
    # Conservative by construction: the suffix must start with a letter and
    # hold only plain word/number text, and the number must be the one already
    # read above, or nothing changes. The space before the word is optional —
    # the operators also type "Stage 36.2HRF" with no gap.
    ms = re.search(r"-\s*Stage\s*(\d+(?:\.\d+)?)"
                   r"(?:\s*([A-Za-z][A-Za-z0-9. ]{0,19}))?\s*$", title)
    if ms:
        head, _dot, sub = ms.group(1).partition(".")
        stage = str(int(head)) + (f".{sub}" if sub else "")
        qual = " ".join((ms.group(2) or "").split())
        if qual:
            stage += " " + qual
        if meta.stage == str(int(head)) and stage != meta.stage:
            meta.stage = stage

    # time axis: slanted "Mon-DD HH:MM" labels; right bbox edge sits on
    # the gridline they annotate
    tpts = []
    daytags = []
    tlabels = []
    for s in spans:
        m = TIME_RE.fullmatch(s["t"])
        if m:
            mon, day, hh, mm = m.groups()
            if mon not in MONTHS:
                continue
            secs = ((MONTHS[mon] * 31 + int(day)) * 86400
                    + int(hh) * 3600 + int(mm) * 60)
            tpts.append((secs, s["x1"], s["cy"]))
            daytags.append((secs, MONTHS[mon], int(day)))
            # re-printed, not the raw span text: TIME_RE tolerates "Apr-6"
            # and a run of spaces, and two pages of ONE chart must not look
            # different because of typesetting
            tlabels.append((secs, f"{mon}-{int(day):02d} "
                                  f"{int(hh):02d}:{mm}"))
    if len(tpts) < 3 and jobmaster:
        # "Elapsed Time (min)" under the plot, its labels the row above it
        cap = next((s for s in spans if "Elapsed Time" in s["t"]), None)
        if cap is not None:
            # The row of elapsed labels ("100", "200") sits just above the
            # caption — and so do the four value axes' "0" ticks, nine pixels
            # higher, which read as t=0 at four x positions and made the
            # first fit run 0.07 min per pixel. The labels are the row with
            # the most members nearest the caption; the zeros stay with
            # their tick columns.
            rows = {}
            for s in spans:
                if not re.fullmatch(r"\d+(?:\.\d+)?", s["t"]):
                    continue
                if cap["cy"] - 30 < s["cy"] < cap["cy"] - 2:
                    key = next((k for k in rows if abs(k - s["cy"]) <= 3), None)
                    rows.setdefault(s["cy"] if key is None else key, []).append(s)
            best = max(rows.values(), key=lambda r: (len(r) >= 2, -abs(r[0]["cy"] - cap["cy"])),
                       default=[])
            for s in best:
                tpts.append((float(s["t"]) * 60.0, s["cx"], s["cy"]))
            tpts.sort(key=lambda p: p[1])
        if len(tpts) < 2:
            raise ValueError("bj1: elapsed-time labels not found")
        m = _JM_START.search(text)
        if m and m.group(1)[:3] in MONTHS:       # "May 31" and "June 01" alike
            meta.date = f"{int(m.group(3)):04d}-{MONTHS[m.group(1)[:3]]:02d}-{int(m.group(2)):02d}"
        tlabels = [(t, f"{t / 60:g} min") for t, _x, _y in tpts]
    elif len(tpts) < 3:
        raise ValueError("bj1: time labels not found")
    # year rollover inside a stage: "Dec-31 ... Jan-01" labels wrap the
    # month*31+day clock backwards — push the new-year cluster up a
    # synthetic year (372 days) so time keeps increasing
    lo = min(p[0] for p in tpts)
    if daytags and max(p[0] for p in tpts) - lo > 186 * 86400:
        YEAR = 372 * 86400
        tpts = [(s + YEAR, x, cy) if s - lo < 186 * 86400 else (s, x, cy)
                for s, x, cy in tpts]
        daytags = [(s + YEAR, mo, d) if s - lo < 186 * 86400 else (s, mo, d)
                   for s, mo, d in daytags]
        tlabels = [(s + YEAR, lab) if s - lo < 186 * 86400 else (s, lab)
                   for s, lab in tlabels]
    # year is absent from the chart — resolve it from the document's tables
    if daytags:
        _, start_mon, start_day = min(daytags)
        year = _resolve_year(page.parent, start_mon, start_day)
        meta.date = f"{year:04d}-{start_mon:02d}-{start_day:02d}"

    # A stage can be charted twice with the SAME printed title — a zoomed
    # detail view beside the full treatment, or two genuinely separate
    # treatments — so the suffix rule above has nothing to read and both
    # charts land under one stage key. The only thing on the page that tells
    # them apart is this axis: every page of ONE chart (the main plot and the
    # single-series auxiliaries that follow it) prints exactly the same
    # "Mon-DD HH:MM" label set, and two charts of the same stage never do.
    # Publish the set so the document-level pass in pipeline can separate
    # them; a stage charted once is unaffected.
    meta.axis_window = "|".join(lab for _s, lab in sorted(set(tlabels)))
    tfit = _fit([(v, x) for v, x, _ in tpts])
    if tfit[1] <= 0:
        raise ValueError("bj1: bad time fit")
    time_y = min(cy for _, _, cy in tpts)

    # y-axis tick columns: numeric spans above the time labels, clustered
    # by right-edge x
    nums = [s for s in spans if re.fullmatch(r"-?[\d,]+(\.\d+)?", s["t"])
            and s["cy"] < time_y - 5]
    # Ticks align on their right edge on BJ-1, on their LEFT edge on the
    # right-hand axes of a JobMaster page ("0", "500", "1000" all start at
    # x=712): a column is a run that shares either edge.
    cols = defaultdict(list)
    lefts = {}
    for s in nums:
        placed = False
        for key in list(cols):
            if abs(key - s["x1"]) < 8 or abs(lefts[key] - s["x0"]) < 8:
                cols[key].append(s)
                placed = True
                break
        if not placed:
            cols[round(s["x1"])].append(s)
            lefts[round(s["x1"])] = s["x0"]
    fits = {}          # col_x -> (a, b, y_lo, y_hi)
    for key, ss in cols.items():
        if len(ss) < 3:
            continue
        a, b = _fit([(float(s["t"].replace(",", "")), s["cy"]) for s in ss])
        if abs(b) > 1e-9:
            ys = [s["cy"] for s in ss]
            fits[key] = (a, b, min(ys) - 10, max(ys) + 10)
    if not fits:
        raise ValueError("bj1: no axis tick columns")

    # Tick labels are NOT consistently aligned: on some pages the '0' of an
    # axis sits ~11pt left of its '2000' (right edges 726 vs 743), so the
    # 8pt right-edge clustering above orphans it into a 1-member column that
    # gets dropped. The column then loses its bottom tick, its band starts
    # part-way up the axis, and every sample below that is clipped away —
    # which surfaced as concentration channels sitting on a flat raised
    # baseline (~373 kg/m³) instead of zero through the pad.
    # Re-attach an orphan only when it lands on an existing column's own
    # fitted line, so a genuinely unrelated number can't be absorbed.
    orphans = [s for _k, ss in cols.items() if len(ss) < 3 for s in ss]
    for s in orphans:
        try:
            v = float(s["t"].replace(",", ""))
        except ValueError:
            continue
        for key in list(fits):
            a, b, y_lo, y_hi = fits[key]
            if abs(key - s["x1"]) > 40:
                continue
            axis_span = abs(b) * max(1.0, y_hi - y_lo)
            if abs(a + b * s["cy"] - v) <= max(1e-6, 0.02 * axis_span):
                cols[key].append(s)
                pts = [(float(z["t"].replace(",", "")), z["cy"]) for z in cols[key]]
                a2, b2 = _fit(pts)
                ys = [z["cy"] for z in cols[key]]
                fits[key] = (a2, b2, min(ys) - 10, max(ys) + 10)
                break

    # rotated axis-name spans (taller than wide) -> nearest tick column
    axis_names = {}
    for s in spans:
        if (s["y1"] - s["y0"]) > (s["x1"] - s["x0"]) * 1.5 and \
                re.search(r"[A-Za-z]{3}", s["t"]):
            key = min(fits, key=lambda k: abs(k - s["cx"]))
            axis_names[s["t"]] = key

    # legend: black names with a short colored dash stroke to the left
    drawings = _drawings(page)
    dashes = []
    for d in drawings:
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        c = tuple(round(x, 2) for x in c)
        if c == (0.0, 0.0, 0.0) or len(d["items"]) > 4:
            continue
        r = d["rect"]
        if r.width < 40 and r.height < 4:
            dashes.append((c, r))
    name_color = {}
    for s in spans:
        if not re.search(r"\([^)]+\)", s["t"]) or (s["y1"] - s["y0"]) > 20:
            continue
        best, bestd = None, 25
        for c, r in dashes:
            dy = abs((r.y0 + r.y1) / 2 - s["cy"])
            dx = s["x0"] - r.x1
            if dy < 6 and 0 < dx < bestd:
                best, bestd = c, dx
        if best:
            name_color.setdefault(s["t"], best)

    # match each legend name to the axis whose name span mentions it
    def name_axis(name):
        # The 2022 filings append the axis SIDE to the legend label — "CMB SLR
        # Rate (m3/min) (left)", "WH Press (MPa) (outer l.)" — while the axis
        # itself is titled without it. The test below asks whether the legend
        # name sits inside the axis name, and the qualifier makes it longer, so
        # every treatment curve on 01359 and 00633 failed to find an axis and
        # the page raised "no curves matched" with the ink sitting right there
        # (#319-#329: 47 treatment pages in one file). Strip the side, keep the
        # unit — the unit is what distinguishes two curves on one axis.
        base = re.sub(r"\s+", " ", name)
        base = re.sub(r"\s*\((?:left|right|outer|inner)[^)]*\)\s*$", "",
                      base, flags=re.I).strip()
        for ax_text, key in axis_names.items():
            if base in re.sub(r"\s+", " ", ax_text):
                return key
        return None

    # a black series (e.g. Comb FR Ratio) has a black legend dash, so it never
    # matched a colored sample above. Assign it the black stroke color when
    # exactly one un-coloured legend series maps to an axis (more than one black
    # curve would be indistinguishable). This has to run BEFORE the empty-legend
    # guard below: the auxiliary single-series pages BJ emits alongside each
    # stage plot their only curve in black, so bailing out first threw them all
    # away as "no legend colors".
    # JobMaster prints no legend: each axis title IS its series' name, in
    # the series' own colour, so the title's text colour names the stroke
    if jobmaster and not name_color:
        blacks = []
        for s in spans:
            if s["t"] not in axis_names:
                continue
            if max(s["color"]) - min(s["color"]) > 0.2:
                name_color[s["t"]] = s["color"]
            elif max(s["color"]) < 0.25:
                blacks.append(s["t"])
        # one black-titled series (Comb ThinFrac HV) draws in black too; two
        # would be indistinguishable from each other and from the grid
        if len(blacks) == 1:
            name_color[blacks[0]] = (0.0, 0.0, 0.0)
    legend_names = {s["t"] for s in spans
                    if re.search(r"\([^)]+\)", s["t"]) and (s["y1"] - s["y0"]) <= 20}
    black_cands = [n for n in legend_names
                   if n not in name_color and name_axis(n) is not None]
    if len(black_cands) == 1:
        name_color[black_cands[0]] = (0.0, 0.0, 0.0)
    if not name_color:
        raise ValueError("bj1: no legend colors")

    # Clip curves to the plot FRAME (the full-height vertical gridlines), not
    # the time-label span. BJ prints its first/last time labels inset from the
    # frame edges, so each stage's opening ramp (and tail) sits between the
    # frame and the outermost labels — a label-based window clips it. The
    # per-series y-band and the >=5-item stroke length filter below already
    # exclude off-plot strokes, so widening to the frame only recovers real
    # curve points (verified: never drops points, only adds contiguous ramp).
    vgrid = [(d["rect"].x0 + d["rect"].x1) / 2 for d in drawings
             if d.get("color") is not None and d["type"] in ("s", "fs")
             and abs(d["rect"].x1 - d["rect"].x0) < 0.6
             and (d["rect"].y1 - d["rect"].y0) > 100]
    if vgrid:
        x_lo, x_hi = min(vgrid) - 2, max(vgrid) + 2
    else:
        x_lo = min(x for _, x, _ in tpts) - 15
        x_hi = max(x for _, x, _ in tpts) + 15
    series, units = {}, {}
    axes = {}          # label -> (axis_min, axis_max) from the printed ticks
    axis_fit = {}      # label -> (a, b) so the axis can be read AT the frame
    for name, color in name_color.items():
        key = name_axis(name)
        if key is None:
            continue
        a, b, y_lo, y_hi = fits[key]
        pts = []
        for d in drawings:
            c = d.get("color")
            if c is None or d["type"] not in ("s", "fs"):
                continue
            # The title's colour and the stroke's are the same ink and can
            # still differ in the second decimal: 00017 titles its rate
            # (1.0, 0.24, 0.15) and draws it (1.0, 0.23, 0.15), and an exact
            # comparison lost the rate on every page. Nearest hundredths
            # are the same colour; BJ's palette keeps its series 0.2 apart.
            if max(abs(x - y) for x, y in zip(c, color)) > 0.03:
                continue
            # A curve is normally one long path, and a path under five items
            # is a legend dash or a tick. The JobMaster books other than
            # 00013 (00009, 00012, 00015, 00017, 00018, 00024) draw every
            # segment of a curve as its own one-item path — 9,500 blue paths
            # of one line each — and the filter threw the whole curve away
            # ("no curves matched" on every page). Those pages print no
            # legend, and the frame clip below keeps their ticks out.
            if len(d["items"]) < 5 and not jobmaster:
                continue
            for item in d["items"]:
                if item[0] == "l":
                    p1, p2 = item[1], item[2]
                    if color == (0.0, 0.0, 0.0):
                        # black series shares ink with axes/grid: drop long
                        # axis-aligned segments (frame + gridlines)
                        if (abs(p1.x - p2.x) < 0.01 or abs(p1.y - p2.y) < 0.01) and \
                           max(abs(p1.x - p2.x), abs(p1.y - p2.y)) > 5:
                            continue
                    pts.append((p1.x, p1.y))
                    pts.append((p2.x, p2.y))
                elif item[0] == "c":
                    pts.append((item[1].x, item[1].y))
                    pts.append((item[4].x, item[4].y))
        if len(pts) < 40:
            continue
        arr = np.array(pts)
        keep = ((arr[:, 0] >= x_lo) & (arr[:, 0] <= x_hi) &
                (arr[:, 1] >= y_lo) & (arr[:, 1] <= y_hi))
        arr = arr[keep]
        if len(arr) < 40:
            continue
        t = tfit[0] + tfit[1] * arr[:, 0]
        v = a + b * arr[:, 1]
        order = np.argsort(t, kind="stable")
        mn = re.match(r"(.+?)\s*\(([^)]+)\)", name)
        label = mn.group(1).strip() if mn else name
        series[label] = (t[order], v[order])
        units[label] = mn.group(2).strip() if mn else ""
        # the chart's OWN printed axis for this curve, so the Lab plots
        # against the report's range instead of guessing one from the data
        tvals = [float(z["t"].replace(",", "")) for z in cols.get(key, [])]
        if tvals:
            axes[label] = (float(min(tvals)), float(max(tvals)))
            axis_fit[label] = (float(a), float(b))
    if not series:
        raise ValueError("bj1: no curves matched")

    t_lo = min(t.min() for t, _ in series.values())
    t_hi = max(t.max() for t, _ in series.values())
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"bj1: implausible duration {n}s")
    meta.duration_min = n / 60.0

    # geometry for the Lab's synced "Compare Original" view. Time runs along
    # x here (no page rotation), and the stacked value axes share one frame,
    # so the horizontal gridlines give its vertical extent.
    hgrid = []
    for d in drawings:
        if d.get("color") is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        if abs(r.y1 - r.y0) < 0.6 and (r.x1 - r.x0) > 100:
            hgrid.append((r.y0 + r.y1) / 2)
    # Ghost stretches the page so v0..v1 fills our plot rect, and the Lab
    # draws each curve against its printed tick range — so v0/v1 must be the
    # page coords where the axis READS those ticks. Gridline extremes are not
    # that (there is no gridline at the axis zero), which shifted the whole
    # backdrop. Invert each series' own fit and take the median.
    edges_lo, edges_hi = [], []
    for _n, (fa, fb) in axis_fit.items():
        if abs(fb) < 1e-12:
            continue
        lo_v, hi_v = axes[_n]
        edges_lo.append((lo_v - fa) / fb)
        edges_hi.append((hi_v - fa) / fb)
    if edges_lo and edges_hi:
        edges_lo.sort(); edges_hi.sort()
        p_lo = edges_lo[len(edges_lo) // 2]
        p_hi = edges_hi[len(edges_hi) // 2]
        v0, v1 = min(p_lo, p_hi), max(p_lo, p_hi)
    elif hgrid:
        v0, v1 = min(hgrid), max(hgrid)
    else:
        v0 = min(f[2] for f in fits.values())
        v1 = max(f[3] for f in fits.values())
    meta.geom = {"axis": "x", "ta": float(tfit[0] - t_lo),
                 "tb": float(tfit[1]), "v0": float(v0), "v1": float(v1)}

    day_sec = t_lo % 86400
    if jobmaster:
        day_sec = 0.0            # elapsed minutes name no clock; the Totals table may
    meta.start_time = (f"{int(day_sec // 3600):02d}:"
                       f"{int(day_sec % 3600 // 60):02d}:"
                       f"{int(day_sec % 60):02d}")
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {name: _resample(t - t_lo, v, samples)
            for name, (t, v) in series.items()}
    # printed axis range per curve, so the Lab's y axis matches the report;
    # axes_frame is the same axis read AT the geom frame edges — ghost
    # stretches the page between those, so any gap is visible misalignment
    meta.axes = axes
    meta.axes_frame = {n: (af[0] + af[1] * v0, af[0] + af[1] * v1)
                       for n, af in axis_fit.items()}
    return meta, samples, data, units
