"""Chart labels read off the rendered page, for filings whose text layer lies.

A chart page can be perfectly drawn and still say nothing. Two shapes of it
turn up in the BCER/AER corpus:

  - the SCAN. No text layer at all: every page is a picture. The raster
    templates (step1, hal1, trican_charts, slb) already handle those — they
    OCR the axes themselves.

  - the TYPE3 FILING, which is the one this module is for. The page is
    ordinary vector artwork — the curves are real strokes, the frame is a
    real rectangle — but every string on it is set in an embedded Type3 font
    with no ToUnicode map. `page.get_text()` hands back the raw glyph codes,
    so the page LOOKS fine and extracts as control characters (00035, 00051
    on the Paramount well: 45 chart pages, 326 of 468 characters unprintable
    on the first of them). Nothing names the zone, the date, the axes or the
    curves, so frac_core drops the page and the whole file reports "no
    extractable data" — 45 charts of real vector curves, thrown away for
    want of a legend.

The geometry on those pages is exact and must stay that way: this module
reads LABELS ONLY. The page is rendered, tesseract is run over it, and the
word boxes are mapped back into the page's own coordinates so that the same
frac_core code that matches a PDF span to a legend swatch or a tick column
matches an OCR'd one. The curves themselves are never touched.

OCR output is not trusted anywhere it can become a number in a CSV. Words
below a confidence floor are dropped, and a tick column that does not fall on
a straight line is refused outright rather than repaired — see
axis_column_ok. A chart that comes back with no axis is a chart the client
sees is missing; a chart with an axis off by a factor of ten is one they do
not.
"""
import re

import fitz
import numpy as np

import auto_raster as ar

# Rendering resolution. 200 dpi puts a 6pt label at ~17px tall, which is
# comfortably above tesseract's floor, and costs ~0.15s to render and ~0.5s
# to read for a whole page — worth paying only on the pages that need it,
# which is why every entry point here is gated on `garbled`.
DPI = 200

# Page segmentation: 11 is "sparse text, no particular order", which is what
# a chart is — a title, a legend, two columns of tick numbers and a caption,
# with white space everywhere between. The paragraph modes weld the tick
# columns into running text.
PSM = 11

# Confidence floors. A misread NAME costs nothing: it fails the alias table
# and the curve is reported unnamed. A misread NUMBER becomes an axis full
# scale and rides into every value in the column, so it is held to a much
# higher bar and then still has to lie on the axis's own straight line.
TEXT_CONF = 30.0
NUMBER_CONF = 70.0

# Ink box -> line box: how much of its own height a word's box grows by at
# the top and at the bottom. Digits carry no descender and most caps no
# ascender, so their ink is about 0.7em against a 1.2em line; 0.25 each side
# lands on 1.5x the ink, close enough to make OCR'd boxes abut where PDF
# spans do without letting two lines of a legend touch.
_LINE_BOX_PAD = 0.25

# What counts as an unusable text layer. The same test frac_core's caller
# uses to explain an empty file (pipeline._why_nothing), kept in one place:
# more than a token amount of text, and more of it printable than not.
_MIN_PRINTABLE = 20


def available():
    """True when there is a tesseract to run (bundled, or on PATH)."""
    return ar.available()


def _cache(page):
    """Per-document store, so a 382-page filing renders each page once."""
    doc = getattr(page, "parent", None)
    if doc is None:
        return None
    try:
        store = doc._ocr_label_cache
    except AttributeError:
        store = {}
        try:
            doc._ocr_label_cache = store
        except Exception:
            return None
    return store


def garbled(page):
    """True when this page's text layer cannot be read as text.

    Both the empty case and the Type3 case: no printable characters worth
    the name, or more control characters than printable ones. Asked several
    times per page by the callers below, so the answer is cached with the
    OCR itself.
    """
    store = _cache(page)
    key = ("garbled", getattr(page, "number", None))
    if store is not None and key in store:
        return store[key]
    try:
        text = page.get_text() or ""
    except Exception:
        return False
    good = sum(1 for ch in text if ch.isprintable() and not ch.isspace())
    bad = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
    out = not (good > _MIN_PRINTABLE and good > bad)
    if store is not None:
        store[key] = out
    return out


def words(page, dpi=DPI):
    """[{text, rect, conf, line}] for the page, in PAGE coordinates.

    `rect` is a fitz.Rect in the same space `page.get_text` and
    `page.get_drawings` report — which for a /Rotate 90 page is NOT the space
    the render is in, so every box is put back through the page's own
    derotation matrix. Get that wrong and every label lands on the far side
    of the sheet from the thing it names.
    """
    store = _cache(page)
    key = (page.number, dpi)
    if store is not None and key in store:
        return store[key]
    out = []
    if available():
        try:
            out = _render_and_read(page, dpi)
        except Exception:
            out = []
    if store is not None:
        store[key] = out
    return out


def _render_and_read(page, dpi):
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[..., :3]
    elif pix.n == 1:
        img = np.repeat(img, 3, axis=2)
    # No whitelist: these are chart titles, legends and captions, and
    # restricting the alphabet on running text costs more than it buys.
    boxes = ar.ocr_boxes(img.astype(int), psm=PSM, whitelist="")
    scale = 72.0 / dpi
    derot = page.derotation_matrix
    out = []
    for b in boxes:
        # Tesseract reports the INK; a PDF span reports the LINE BOX, which
        # is taller by the ascent and descent the glyphs happen not to use.
        # The difference is not cosmetic: frac_core groups tick labels into
        # rows by whether their boxes abut, and this chart stacks its three
        # value axes 6.1pt apart — spans overlap there, bare digit ink sits
        # 2.2pt clear, and the three axes came back as one column of 900
        # with the rate axis reading 900 m3/min. Restore the line box.
        pad = _LINE_BOX_PAD * (b["y1"] - b["y0"])
        r = fitz.Rect(b["x0"] * scale, (b["y0"] - pad) * scale,
                      b["x1"] * scale, (b["y1"] + pad) * scale)
        r = r * derot
        r.normalize()
        out.append({"text": b["text"], "rect": r, "conf": b["conf"],
                    "line": b["line"],
                    # the box in the RENDER, kept because reading order and
                    # "the next word to the right" only exist there: on a
                    # /Rotate 90 page a line runs UP the page's own y axis
                    "rbox": (b["x0"], b["y0"], b["x1"], b["y1"])})
    return out


def _lines(page, dpi=DPI, min_conf=TEXT_CONF):
    """Words grouped back into the lines tesseract found them on."""
    groups = {}
    for w in words(page, dpi):
        if w["conf"] >= min_conf:
            groups.setdefault(w["line"], []).append(w)
    out = []
    for ws in groups.values():
        # Reading order is the RENDER's left-to-right, and on a /Rotate 90
        # page that is the page's own y axis running BACKWARDS. Sorting in
        # page space spelt every title in reverse ("Surface ... (Surf:
        # Paramount"), so the order tesseract emitted is kept instead.
        ws.sort(key=lambda w: w["rbox"][0])
        xs = [w["rect"] for w in ws]
        rect = fitz.Rect(min(r.x0 for r in xs), min(r.y0 for r in xs),
                         max(r.x1 for r in xs), max(r.y1 for r in xs))
        out.append((rect, " ".join(w["text"] for w in ws)))
    return out


# A leading apostrophe or bullet is the commonest OCR artefact on a legend
# entry drawn hard against its colour swatch ("'Combined Slurry Rate
# (m*/min)"), and it is enough to miss the alias table by.
_EDGE_JUNK = re.compile(r"^[^0-9A-Za-z(]+|[^0-9A-Za-z)%³]+$")


def text_spans(page):
    """[(bbox, text)] for every OCR'd line carrying a letter.

    The same shape frac_core._text_spans returns from the PDF, and at the
    same grain: a legend entry is ONE label, not the four words it OCRs
    into, because it has to be matched to the swatch beside it as a whole.
    """
    out = []
    for rect, text in _lines(page):
        t = _EDGE_JUNK.sub("", text).strip()
        if t and any(c.isalpha() for c in t):
            out.append((tuple(rect), t))
    return out


_NUMBER = re.compile(r"-?\d{1,7}(?:\.\d{1,3})?$")


def numeric_spans(page):
    """[(bbox, value)] for every OCR'd word that is a bare number.

    Word grain, not line grain: a tick label is one number, and the axis
    fitting downstream needs each one's own position.
    """
    out = []
    for w in words(page):
        if w["conf"] < NUMBER_CONF:
            continue
        t = w["text"].strip().replace(",", "")
        if _NUMBER.fullmatch(t):
            out.append((tuple(w["rect"]), float(t)))
    return out


# "Zone 1" is the single most valuable string on a CalFrac chart and the one
# the full-page pass is worst at: a lone "1" beside a word, in a proportional
# serif face, at 200 dpi, comes back as "|" or "I" about as often as as
# itself. Guessing at it is not an option — "Zone I" read as zone 1 is right
# until the day it is zone 7 — so the caption is READ AGAIN, from its own
# strip at 600 dpi, WITH the word in front of it.
#
# Keeping "Zone" in the crop is the whole trick. Cropped to the digit alone
# and given a digits-only alphabet, tesseract read "Zone 1" as 7 and "Zone
# 17" as 7 (and "Zone 3B" as 38, which would have invented a stage 38); with
# the word for company it read all 11 captions on the well correctly,
# suffix and all. Two page-segmentation modes must agree before the number
# is used at all.
_STAGE_WORD = re.compile(r"(?:zone|stage|interval)$", re.I)
# how far right of the caption word the number can be, in multiples of the
# word's own height
_STAGE_REACH = 4.0
_STAGE_DPI = 600
_STAGE_WL = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ")
_STAGE_RE = re.compile(r"(?:zone|stage|interval)\s*[:.]?\s*(\d{1,2})", re.I)


def stage_number(page, dpi=DPI):
    """The zone/stage number the page captions itself with, as a string.

    Digits only, dropping any re-treat letter, because that is exactly what
    frac_core.detect_text_meta takes off a readable page — an OCR'd chart
    and its vector twin must not disagree about what a stage is called.
    """
    heads = [w for w in words(page, dpi)
             if _STAGE_WORD.fullmatch(w["text"].strip(" :."))]
    scale = 72.0 / dpi
    for head in heads[:3]:
        x0, y0, x1, y1 = head["rbox"]
        h = max(1.0, y1 - y0)
        clip = fitz.Rect((x0 - h * 0.3) * scale, (y0 - h * 0.4) * scale,
                         (x1 + h * _STAGE_REACH) * scale, (y1 + h * 0.4) * scale)
        try:
            img = _clip_image(page, clip, _STAGE_DPI)
        except Exception:
            continue
        seen = set()
        for psm in (6, 7):
            got = " ".join(w[0] for w in ar.ocr_words(img, psm=psm,
                                                      whitelist=_STAGE_WL))
            m = _STAGE_RE.search(got)
            seen.add(str(int(m.group(1))) if m else None)
        if len(seen) == 1:
            only = seen.pop()
            if only is not None:
                return only
    return None


def _clip_image(page, clip, dpi):
    """One region of the page, rendered large and matted on white.

    The white margin is not cosmetic: tesseract's layout analysis needs
    somewhere to put a page and reads a glyph flush to the edge of its
    image far less reliably.
    """
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[..., :3]
    elif pix.n == 1:
        img = np.repeat(img, 3, axis=2)
    pad = np.full((img.shape[0] + 80, img.shape[1] + 80, 3), 255, np.uint8)
    pad[40:40 + img.shape[0], 40:40 + img.shape[1]] = img
    return pad.astype(int)


def page_text(page):
    """The page's text — OCR'd when the real one cannot be read.

    Line order follows the RENDER, top to bottom, so the first line is the
    chart's title exactly as a reader sees it. Templates key on that.
    """
    if not garbled(page):
        try:
            return page.get_text() or ""
        except Exception:
            return ""
    rot = page.rotation_matrix
    lines = [(rect * rot, text) for rect, text in _lines(page)]
    lines.sort(key=lambda lt: (round(lt[0].y0, 1), lt[0].x0))
    return "\n".join(text for _r, text in lines)


# ------------------------------------------------------------ axis guards

# How far off its own straight line a tick label may sit and still be
# believed. The ticks on these charts are evenly spaced by construction, so
# a reading that misses the line is a misread digit, not an unusual axis.
_AXIS_TOL_FRAC = 0.02


def axis_column_ok(pts):
    """Is this OCR'd tick column a real axis? -> the readings that are.

    `pts` is [(position, value)] for ONE column of tick labels, position in
    page units along the axis. Returns the subset lying on the column's own
    line, or None when no line fits at all.

    This is the guard that stands between a dropped digit and a client's
    CSV. "900" read as "9000" at the top of a concentration axis does not
    look wrong in a list of numbers — it looks like the axis maximum, which
    is exactly what the caller is about to use it as — but it does not sit
    on the line the other ticks make, and here it is thrown away.
    """
    pts = [(float(p), float(v)) for p, v in pts]
    if len(pts) < 3:
        return None
    fit = ar.fit_ticks([(v, p) for p, v in pts], min_inliers=3)
    if fit is None:
        return None
    a, b, _n = fit
    span = max(v for _p, v in pts) - min(v for _p, v in pts)
    tol = max(abs(b) * 4.0, span * _AXIS_TOL_FRAC, 1e-9)
    keep = [(p, v) for p, v in pts if abs(a + b * p - v) <= tol]
    return keep if len(keep) >= 3 else None
