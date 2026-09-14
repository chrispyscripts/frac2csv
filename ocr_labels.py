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
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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


# How many pages to OCR at once, and why it is not "as many as possible".
#
# Measured on a 10-core machine over 12 pages of 00339: sequential 0.95s a
# page, a pool of 3 0.39s (2.4x), of 6 0.24s (3.9x), of 9 0.22s (4.4x). Past
# six the curve is nearly flat, and every extra worker is one more tesseract
# competing for the same memory bandwidth. One core is left for the renderer
# and the UI.
_POOL_CAP = 8
# How many pages may be rendered ahead of the pool.
#
# Set from a MEASUREMENT, after an estimate sent this the wrong way twice.
# The arithmetic said a 200 dpi page is ~11 MB, so 280 of them would be 3 GB
# and had to be bounded tightly. Rendering all 279 pages of 00148 up front
# actually peaks at 1071 MB — LOWER than the run bounded to 16 (1207 MB) and
# the batched one (1296 MB), because the bounded versions run longer and hold
# more of everything else instead.
#
# Four, because the memory is measurable and the speed difference is not.
# Three runs of the same file, same load, one process each:
#
#     lookahead=4    545.4s   1384 MB
#     lookahead=6    548.6s   1492 MB
#     lookahead=12   552.0s   1941 MB
#
# 1.2% apart in time and 557 MB apart in peak memory, so there is nothing to
# buy by rendering further ahead. (An earlier run appeared to show a large
# speed penalty at lookahead=2; it was taken under different load and does not
# reproduce. Timings on a busy machine were the single biggest source of wrong
# conclusions in this work — the output signature never moved.)
_LOOKAHEAD = 4
# Above this the machine is already busy — another window, or anything else
# he is running — and piling more tesseract processes on makes every one of
# them slower. Checked once per document, not per page.
_BUSY_FRAC = 0.80


def _machine_busy():
    """Is the machine already loaded? -> True / False / None when unknown.

    None matters: a reading we could not take must not be read as "idle".
    Windows has no getloadavg, so the EXE will mostly answer None here and
    fall back to the core count alone — which is the behaviour to degrade to,
    not a reason to refuse to parallelise at all.
    """
    try:
        one, _five, _fifteen = os.getloadavg()
    except (AttributeError, OSError):
        return None
    cores = os.cpu_count() or 1
    return one > cores * _BUSY_FRAC


def pool_size(want=None):
    """How many pages to OCR at once on this machine, right now."""
    if want:
        return max(1, int(want))
    cores = os.cpu_count() or 1
    n = min(_POOL_CAP, max(1, cores - 1))
    if _machine_busy():
        n = max(1, n // 2)
    return n


def prefetch(pages, dpi=DPI, workers=None, on_page=None):
    """Warm the OCR cache for `pages`, several at a time.

    The whole point of the split above: rendering is 5% of the cost and is
    NOT thread-safe, OCR is the other 95% and is a subprocess, so the render
    runs here on one thread and the reading runs in a pool. Nothing about
    extraction changes — the per-document cache simply already holds the
    answer by the time the sequential pass asks for it, which is what keeps
    every order-dependent rule (a Bottom Hole sheet borrowing the zones of
    the Surface sheet printed before it) working exactly as it did.

    Best-effort throughout. A page that fails here is not cached, and the
    sequential pass renders and reads it the old way.
    """
    if not available():
        return 0
    todo = []
    for page in pages:
        store = _cache(page)
        if store is None or (page.number, dpi) in store:
            continue
        try:
            if not garbled(page):
                continue              # a readable text layer needs no OCR
        except Exception:
            continue
        todo.append(page)
    if not todo:
        return 0
    n = pool_size(workers)
    if n <= 1:
        return 0
    done = 0
    # Bounded, but WITHOUT a barrier, and the difference is the whole speedup.
    #
    # A rendered page at 200 dpi is about 11 MB, so rendering a 400-page
    # filing up front would hold roughly 4 GB at once. The obvious fix —
    # render a batch, wait for it, render the next — gives the memory back
    # and hands back the speed with it: measured on 00148, sequential 477s,
    # unbounded pool 330s, BATCHED 451s. The barrier idles the renderer
    # waiting for the slowest page in each batch and then idles the workers
    # waiting for the next batch to be rendered.
    #
    # A semaphore bounds what is alive without ever stopping the flow: the
    # renderer runs ahead until `inflight` pages are outstanding and then
    # blocks on the next one, which a finishing worker immediately unblocks.
    inflight = max(2, n * _LOOKAHEAD)
    room = threading.Semaphore(inflight)
    futures = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        for page in todo:
            room.acquire()
            store = _cache(page)
            try:
                store[("img", page.number, dpi)] = _render(page, dpi)
            except Exception:
                room.release()
                continue
            fut = pool.submit(words, page, dpi)
            fut.add_done_callback(lambda _f: room.release())
            futures.append(fut)
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                pass
            done += 1
            if on_page is not None:
                try:
                    on_page(done, len(futures))
                except Exception:
                    pass

    # anything left unrendered would otherwise hold a page's bitmap for the
    # life of the document
    for page in todo:
        store = _cache(page)
        if store is not None:
            store.pop(("img", page.number, dpi), None)
    return done


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


# A page can be drawn sideways without saying so. /Rotate 90 is honoured by
# the renderer and handled by the derotation below, but Halliburton's IFS
# report lays its charts out rotated INSIDE an upright page — 00971 p119 is
# a landscape chart on a portrait sheet — and tesseract reads a column of
# turned letters as "Us Ze Ga =o Ox aO". Three passes, and the turn that
# reads best wins; only garbled pages pay for it, and only the good pass's
# boxes are kept.
_TURNS = (0, 1, 3)
# what "reads best" means: total confidence over words that are actually
# words. A page of turned text still returns plenty of one-character noise.
_SCORE_MIN_CONF = 60.0
_SCORE_MIN_LEN = 3
# ...and when the upright pass has already read this many real words, the
# page is upright and the other two turns are not worth their second and
# third of a second on every chart page of a 382-page filing.
_UPRIGHT_ENOUGH = 8


def _words_read(boxes):
    return sum(1 for b in boxes
               if b["conf"] >= _SCORE_MIN_CONF and len(b["text"]) >= _SCORE_MIN_LEN)


def _score(boxes):
    return sum(b["conf"] for b in boxes
               if b["conf"] >= _SCORE_MIN_CONF and len(b["text"]) >= _SCORE_MIN_LEN)


def _unturn(box, k, w, h):
    """A box read off np.rot90(img, k) -> the same box in img's pixels."""
    x0, y0, x1, y1 = box
    if k == 0:
        return x0, y0, x1, y1
    if k == 1:      # counter-clockwise: rotated (x, y) came from (w-1-y, x)
        pts = [(w - 1 - y, x) for x in (x0, x1) for y in (y0, y1)]
    else:           # k == 3, clockwise: rotated (x, y) came from (y, h-1-x)
        pts = [(y, h - 1 - x) for x in (x0, x1) for y in (y0, y1)]
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _render(page, dpi):
    """The page as an RGB array. MUST run on the thread that owns the doc:
    a fitz.Document is not thread-safe and rendering one from two threads
    crashes rather than returning wrong data."""
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[..., :3]
    elif pix.n == 1:
        img = np.repeat(img, 3, axis=2)
    return img


def _render_and_read(page, dpi):
    pre = _cache(page)
    key = ("img", page.number, dpi)
    img = None
    if pre is not None:
        img = pre.pop(key, None)          # rendered ahead by prefetch()
    if img is None:
        img = _render(page, dpi)
    h, w = img.shape[0], img.shape[1]
    # No whitelist: these are chart titles, legends and captions, and
    # restricting the alphabet on running text costs more than it buys.
    boxes = ar.ocr_boxes(img.astype(int), psm=PSM, whitelist="")
    best_k = 0
    if _words_read(boxes) < _UPRIGHT_ENOUGH:
        best = _score(boxes)
        for k in _TURNS[1:]:
            alt = ar.ocr_boxes(np.rot90(img, k).astype(int), psm=PSM,
                               whitelist="")
            got = _score(alt)
            if got > best:
                best_k, best, boxes = k, got, alt
    for b in boxes:
        # Tesseract reports the INK; a PDF span reports the LINE BOX, which
        # is taller by the ascent and descent the glyphs happen not to use.
        # The difference is not cosmetic: frac_core groups tick labels into
        # rows by whether their boxes abut, and this chart stacks its three
        # value axes 6.1pt apart — spans overlap there, bare digit ink sits
        # 2.2pt clear, and the three axes came back as one column of 900
        # with the rate axis reading 900 m3/min. Restore the line box, in
        # the pass's OWN orientation, where the text runs left to right.
        pad = _LINE_BOX_PAD * (b["y1"] - b["y0"])
        b["y0"] -= pad
        b["y1"] += pad
        if best_k:
            b["x0"], b["y0"], b["x1"], b["y1"] = _unturn(
                (b["x0"], b["y0"], b["x1"], b["y1"]), best_k, w, h)
    scale = 72.0 / dpi
    derot = page.derotation_matrix
    out = []
    for b in boxes:
        r = fitz.Rect(b["x0"] * scale, b["y0"] * scale,
                      b["x1"] * scale, b["y1"] * scale)
        r = r * derot
        r.normalize()
        out.append({"text": b["text"], "rect": r, "conf": b["conf"],
                    "line": b["line"], "i": len(out),
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
        # Reading order is the order tesseract emitted the words in, and
        # nothing else. Sorting by position spelt every title on a /Rotate 90
        # page in reverse ("Surface ... (Surf: Paramount"), and on a page
        # whose content is drawn sideways inside an upright sheet there is no
        # page-space axis that runs the right way at all.
        ws.sort(key=lambda w: w["i"])
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
    ws = words(page, dpi)
    heads = [w for w in ws if _STAGE_WORD.fullmatch(w["text"].strip(" :."))]
    scale = 72.0 / dpi
    for head in heads[:3]:
        # The number is the next word or two ON THE SAME LINE. Taking "the
        # box to the right" instead only works while the page is upright,
        # and IFS draws its charts sideways inside a portrait sheet.
        mates = sorted((w for w in ws if w["line"] == head["line"]
                        and w["i"] > head["i"]), key=lambda w: w["i"])[:2]
        x0, y0, x1, y1 = head["rbox"]
        h = max(1.0, y1 - y0)
        for m in mates:
            mx0, my0, mx1, my1 = m["rbox"]
            x0, y0 = min(x0, mx0), min(y0, my0)
            x1, y1 = max(x1, mx1), max(y1, my1)
        if not mates:
            x1 += h * _STAGE_REACH
        pad = h * 0.4
        clip = fitz.Rect((x0 - pad) * scale, (y0 - pad) * scale,
                         (x1 + pad) * scale, (y1 + pad) * scale)
        try:
            img = _clip_image(page, clip, _STAGE_DPI)
        except Exception:
            continue
        seen = set()
        for psm in (6, 7):
            got = " ".join(w[0] for w in ar.ocr_words(img, psm=psm,
                                                      whitelist=_STAGE_WL))
            m = _STAGE_RE.search(got)
            if m:
                seen.add(str(int(m.group(1))))
        # A mode that read no number at all has not contradicted anything —
        # "Zone l" is a failure, not a second opinion. A mode that read a
        # DIFFERENT number has, and then neither is used.
        if len(seen) == 1:
            return seen.pop()
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


# A tick ladder printed SIDEWAYS, read by standing the strip up.
#
# The MView portrait sheets print their time axis rotated: "0 5 10 15 20 25"
# runs bottom-to-top up the right-hand side of the plot. The full-page pass
# reads those digits unreliably — on 00339 it got 6 of them on page 61 and 2
# on page 238 — and the reason it does not simply retry rotated is
# _UPRIGHT_ENOUGH: these pages read plenty of OTHER numbers upright, so the
# rotated retry never fires.
#
# Two ticks is not an axis. Page 238's stage came out with no duration at all
# and was thrown away, and 97 of 00339's chart pages failed the same way —
# more than three times every other cause put together.
#
# Cropping the strip and rotating it so the digits stand up reads the ladder
# whole: 5 ticks on p238 where the page pass found 2, 8 on p61 where it found
# 6, and the durations it fits agree exactly with the ones the page pass gets
# right (40 on p61, 120 on p86).
_TICK_STRIP_DPI = 260
_TICK_STRIP_PAD = 40           # _clip_image's own white matting
_TICK_NUM = re.compile(r"-?\d{1,4}")


def rotated_tick_column(page, clip, dpi=_TICK_STRIP_DPI, turn=3):
    """[(page-axis position, value)] for a tick ladder printed sideways.

    `clip` is the strip the ticks sit in. `turn` is the np.rot90 count that
    stands the digits up — 3 for a ladder reading bottom-to-top, which is
    what these sheets print.

    Positions come back in PAGE units along the clip's long axis, so the
    caller fits them exactly as it fits the ones read from the page itself.
    """
    if not available():
        return []
    try:
        img = np.asarray(_clip_image(page, clip, dpi), dtype=np.uint8)
    except Exception:
        return []
    if turn % 2 == 0:
        return []                       # a half turn leaves them sideways
    height = img.shape[0]
    try:
        boxes = ar.ocr_boxes(np.rot90(img, turn).astype(int), psm=6,
                             whitelist="0123456789")
    except Exception:
        return []
    scale = 72.0 / dpi
    out = []
    for b in boxes:
        text = b["text"].strip()
        if not _TICK_NUM.fullmatch(text) or b["conf"] < NUMBER_CONF:
            continue
        # rot90(.., 3) sends original row r to rotated column height-1-r
        mid = (b["x0"] + b["x1"]) / 2.0
        row = height - 1 - mid if turn == 3 else mid
        out.append((clip.y0 + (row - _TICK_STRIP_PAD) * scale, float(text)))
    out.sort()
    return out


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
