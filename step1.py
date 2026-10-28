"""STEP Energy Services template (Step-1 in Carmine's codes).

Pages are born-digital image renders with no text layer: each page is a
vertical stack of full-width image tiles that composite into one 1820px
canvas holding two charts (Treatment Analysis, Chemical Analysis). Chart
frames are solid black bars, so the plot boxes come from strict-dark
column runs and each chart is fed to auto_raster with an explicit plot
box. Time axis is "Time (min)" numerals; series are color-keyed
(red=Surface Pressure, cyan=Slurry Rate, green=Prop Conc, orange=Btm
Prop Conc).
"""
import fitz
import math
import re
import numpy as np

import aliases
import auto_raster as ar
import curve_trace as ct

SERIES_NAMES = {
    # treatment chart
    ("t", "red"): ("Surface Pressure", "MPa"),
    ("t", "cyan"): ("Slurry Rate", "m3/min"),
    ("t", "green"): ("Prop Conc", "kg/m3"),
    ("t", "orange"): ("Btm Prop Conc", "kg/m3"),
    # chemical chart
    ("c", "cyan"): ("Combined Clean Rate", "m3/min"),
    ("c", "magenta"): ("SSI-3 Conc", "L/m3"),
    ("c", "red"): ("Aqucar 742 Conc", "L/m3"),
    ("c", "green"): ("SFR-202 B Conc", "L/m3"),
}


def detect(page):
    """Old format: image-only page tiled by >=3 full-width images.
    New format (2018+): text info table + 1-2 large chart images."""
    return _detect_tiled(page) or _detect_new(page)


def _detect_tiled(page):
    # The tiling is what identifies this layout — several equal-width images
    # stacked to make one chart. A text layer is incidental: some of these
    # pages carry the info table as real text, and requiring the page to be
    # text-free sent them to _detect_new, which treats each TILE as a whole
    # chart. A tile is a horizontal slice with no time axis in it, so every
    # page failed with "time axis unreadable" and the file yielded nothing.
    ims = page.get_images(full=True)
    if len(ims) < 3:
        return False
    # The 2019 books tile the WHOLE page — title, interval, the info table —
    # and park a 102x7 pt logo and two hairline rules among the tiles.
    # Those are not tiles; the uniform full-width stripes are (00180-1021).
    widths = set()
    tiles = 0
    for im in ims:
        rects = _rects(page, im[0])
        if not rects:
            continue
        w = rects[0].width
        if w < page.rect.width * 0.3:
            continue
        widths.add(round(w))
        tiles += 1
    return tiles >= 3 and len(widths) == 1 and widths.pop() > page.rect.width * 0.9


def _glyph_ids(text):
    """True when a page's text layer holds its font's glyph NUMBERS.

    A Type0 font embedded with no ToUnicode map hands back each glyph's index
    in the font as though it were a character. For Calibri that is printable
    nonsense: "Surface Chart" and "Interval 1" come back as runs of Latin
    Extended and Greek letters (Calibri's lower case and digits sit at glyph
    258 and up), so nothing matched and three 2024 STEP filings (00745,
    00746, 00747) reported no extractable charts in 179 pages (#809). A page
    where those outnumber plain letters is not text."""
    chars = [ch for ch in text if not ch.isspace()]
    if len(chars) < 20:
        return False
    odd = sum(1 for ch in chars if 0x100 <= ord(ch) < 0x400 or ord(ch) < 32)
    return odd > 0.4 * len(chars)


def _outlined_charts(page):
    """No text, and two or more chart-sized images: a chart page whose own
    lettering is drawn as outlines (see _page_text)."""
    try:
        return len(_big_images(page)) >= 2
    except Exception:
        return False


def _page_text(page):
    """Page text with the separators these filings actually use.

    STEP's own generator sets every space in its captions as a NO-BREAK SPACE
    (U+00A0) and every hyphen as a non-breaking hyphen (U+2011), so a literal
    "Surface Treatment Plot" never matches the text layer. Normalise once,
    here, rather than in each caller.

    A text layer of glyph numbers (see _glyph_ids) is replaced by an OCR of
    the page, cached per document by ocr_labels — and so is no text layer at
    all on a page carrying two chart images: 00349 (#811) draws every letter
    of its Interval Summary pages as outlines."""
    text = page.get_text()
    if _glyph_ids(text) or (not text.strip() and _outlined_charts(page)):
        try:
            import ocr_labels
            if ocr_labels.available():
                lines = ocr_labels._lines(page)
                lines.sort(key=lambda lt: (round(lt[0].y0, 1), lt[0].x0))
                text = "\n".join(t for _r, t in lines)
        except Exception:
            pass
    return (text.replace("\u00a0", " ").replace("\u2011", "-")
            .replace("\u2010", "-"))


def _detect_new(page):
    big = _big_images(page)
    if not big:
        return False
    t = _page_text(page)
    if "LSD:" in t and ("Surface Chart" in t or "Interval" in t):
        return True
    # 2024 filings (01078/01079) print the SAME two charts — same frame, same
    # colour key, same stacked value axes — under a bare "Interval N.M" title
    # with no LSD line, so the clause above missed every one of them and both
    # files reported no extractable data. The two chart captions plus an
    # Interval title are what identify the page; the surrounding tour text
    # names other vendors and cannot be used.
    if ("Surface Chart" in t and "Chemical Chart" in t
            and re.search(r"Interval\s+\d+", t) is not None):
        return True
    # A page whose text is an OCR (see _glyph_ids) has the captions to the
    # OCR's mercy: 00745 p162 read "Interval 7" and not "Surface Chart" or
    # "LSD:". There, the interval title over two chart images is enough.
    # 00347's 2017 pages title themselves "Interval Summary" over "Treatment
    # N", and the OCR keeps the header but can lose the number: p99, p100 and
    # p103 (stages 23, 24, 27) were passed over as no chart at all, while
    # their neighbours got through only on an "LSD:" the OCR happened to read.
    if (len(big) >= 2
            and (re.search(r"Interval\s+\d+", t) is not None
                 or ("STEP Energy Services" in t and "Interval Summary" in t))
            and (_glyph_ids(page.get_text()) or not page.get_text().strip())):
        return True
    # Pacific Canbriam 2020 (00322, 00337): the SAME renderer again — two
    # 989x764 chart images, the same colour key, the same stacked value axes,
    # the same clock time axis — but the page carries no info table at all, so
    # there is no "LSD:" line, and the two captions are worded "<operator>
    # Surface Treatment Plot" / "... Chemical Treatment Plot" instead of
    # "Surface Chart" / "Chemical Chart" (those two words are printed INSIDE
    # the image, where no text search can see them). Both files reported no
    # extractable data across 376 pages for that wording alone.
    return ("STEP Energy Services" in t
            and "Surface Treatment Plot" in t
            and "Chemical Treatment Plot" in t
            and re.search(r"Interval\s+\d+", t) is not None)


def _rects(page, xref):
    """page.get_image_rects, or [] for a picture MuPDF cannot decode."""
    try:
        return page.get_image_rects(xref)
    except Exception:
        return []


def _big_images(page):
    """The page's chart-sized images, PLACED ones only, top to bottom.

    get_images lists the whole resource dictionary, which on the 2024 filings
    holds every chart in the document (83 entries on a page that draws two).
    An unplaced entry has no rect, and sorting on rect[0] raised IndexError
    before any chart was read."""
    out = []
    for im in page.get_images(full=True):
        if im[2] < 500 or im[3] < 300:
            continue
        # get_image_rects decodes the image, and 00490 (Halliburton, 2022)
        # carries one MuPDF cannot ("not enough data to determine image
        # format"); it took the whole 247-page book down from inside
        # detect. A picture that will not decode is not a chart.
        rects = _rects(page, im[0])
        if rects:
            out.append((rects[0].y0, im))
    out.sort(key=lambda p: p[0])
    return [im for _y, im in out]


def composite(page):
    """The page's image tiles laid back where the page puts them, at the
    tiles' own resolution; top-to-bottom stacking as the fallback.

    The 2019 books tile the whole page and park a 102x7 pt logo and two
    hairline rules among the stripes: stacked and stretched to the common
    width, the logo became a 1100-px block glued under the chemical chart
    and the title tiles (narrower than the chart's) never reached the rows
    page_meta reads (00180-1021). Placed by rect there is no stretching:
    each tile is scaled by the one factor the chart tiles set.
    """
    doc = page.parent
    placed = []
    for im in page.get_images(full=True):
        rects = _rects(page, im[0])
        if not rects:
            continue
        r = rects[0]
        if r.width < 4 or r.height < 2:
            continue                             # a rule, not a tile
        placed.append((r, im))
    wide = [r for r, _ in placed if r.width > page.rect.width * 0.5]
    if len(placed) >= 3 and wide:
        # px per pt from the chart tiles themselves
        scales = []
        for r, im in placed:
            if r.width > page.rect.width * 0.5:
                try:
                    scales.append(fitz.Pixmap(doc, im[0]).width / float(r.width))
                except Exception:
                    pass
        if scales:
            # Render the page at the tiles' own scale: the chart tiles land
            # 1:1, and the title, the interval and the info table — drawn as
            # vector outlines on these pages, in no tile and no text layer —
            # come with them, where page_meta reads them.
            sc = float(np.median(scales))
            pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
            return (np.frombuffer(pix.samples, dtype=np.uint8)
                    .reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int))
    ims = sorted((im for im in page.get_images(full=True) if _rects(page, im[0])),
                 key=lambda im: _rects(page, im[0])[0].y0)
    arrs = []
    for im in ims:
        pix = fitz.Pixmap(doc, im[0])
        if pix.colorspace is None:      # stencil/soft mask, not a tile
            continue
        if pix.alpha or pix.colorspace.n != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        arrs.append(np.frombuffer(pix.samples, dtype=np.uint8)
                    .reshape(pix.height, pix.width, 3))
    if not arrs:
        raise ValueError("step1: no image tiles")
    w = max(a.shape[1] for a in arrs)
    if any(a.shape[1] != w for a in arrs):
        from PIL import Image
        arrs = [a if a.shape[1] == w else
                np.array(Image.fromarray(a).resize(
                    (w, max(1, round(a.shape[0] * w / a.shape[1])))))
                for a in arrs]
    return np.vstack(arrs).astype(int)


def _runs(col, minlen, gap=0, trim=30):
    """[(start, end)] of the True runs at least `minlen` long. A break of up
    to `gap` pixels does not end a run; a piece shorter than `trim` at
    either end of a bridged run is not part of it — the tick mark or label
    stroke a frame rule's end sits a few pixels from (00184: bridging those
    pushed every frame bottom 6-20 px down, onto its time labels)."""
    pieces, start = [], None
    for y, v in enumerate(col):
        if v and start is None:
            start = y
        elif not v and start is not None:
            pieces.append((start, y))
            start = None
    if start is not None:
        pieces.append((start, len(col)))
    if not gap:
        return [(a, b) for a, b in pieces if b - a >= minlen]
    out, group = [], []
    for pc in pieces + [None]:
        if pc is not None and group and pc[0] - group[-1][1] <= gap:
            group.append(pc)
            continue
        if group:
            # a short end piece a pixel or two off is the same stroke (00243
            # p82's rule runs on 998-1025 after a 1 px break, to its floor)
            while (len(group) > 1 and group[0][1] - group[0][0] < trim
                   and group[1][0] - group[0][1] > 2):
                group.pop(0)
            while (len(group) > 1 and group[-1][1] - group[-1][0] < trim
                   and group[-1][0] - group[-2][1] > 2):
                group.pop()
            if group[-1][1] - group[0][0] >= minlen:
                out.append((group[0][0], group[-1][1]))
        group = [pc] if pc is not None else []
    return out


def find_charts(img):
    """-> [(x0, y0, x1, y1)] plot boxes, top chart first.

    A plot box is a PAIR of long vertical rules at the same height — the
    frame's left and right edges. This used to take the leftmost and rightmost
    columns carrying any long dark run, which fails on the 5-tile layout two
    ways at once: at a threshold dark enough to exclude the page border the
    frame rules themselves do not register, and at one loose enough to see them
    the border becomes the outermost column. Six wells extracted nothing.

    Three things make it hold up:
      - every qualifying run in a column counts, not just the longest. A column
        crosses BOTH charts, so keeping one run threw away an edge and left the
        other chart unpaired.
      - runs are grouped by vertical overlap, so a left edge is paired with the
        right edge at its own height rather than with whatever is furthest away.
      - the outer 4% of the width is ignored, which is where the page border
        lives; it is also longer than maxlen, but at a loose threshold it can
        break into shorter segments that would otherwise qualify.

    A rule has to be UNBROKEN over 10% of the page to register at all, and on
    a scan it sometimes is not: on 00274 p61 the treatment chart's right rule
    is chopped into sub-threshold pieces, so that chart was left with a left
    edge and nothing to pair it with and the whole box was dropped. The page
    then yielded ONE box where there are two — and since the survivor was the
    CHEMICAL chart, and position decides the tag when the title is illegible,
    its 0..2 L/m3 axis was exported as Surface Pressure (median 0.19 MPa).
    So a group that finds no partner gets a second look: within its own row
    band, the outermost columns that are dark over half the band's height. A
    broken rule is still dark for most of its height, and nothing else on the
    page is.
    """
    H, W = img.shape[:2]
    dark = img.sum(axis=2) < 300
    minlen, maxlen = int(H * 0.1), int(H * 0.7)
    lo, hi = int(W * 0.04), int(W * 0.96)
    runs = []
    for x in range(lo, hi):
        for r in _runs(dark[:, x], minlen):
            if r[1] - r[0] <= maxlen:
                runs.append((x, r[0], r[1]))
    if not runs:
        return []

    groups = []
    for x, ya, yb in runs:
        for g in groups:
            ov = min(yb, g["y1"]) - max(ya, g["y0"])
            if ov > 0.6 * min(yb - ya, g["y1"] - g["y0"]):
                g["xs"].append(x)
                g["y0"] = min(g["y0"], ya)
                g["y1"] = max(g["y1"], yb)
                break
        else:
            groups.append({"xs": [x], "y0": ya, "y1": yb})

    # A rule broken in the middle also splits ONE chart into two groups at the
    # same width and touching heights: 00271 p26 (an offset-analysis page) came
    # back as the bottom two thirds of its chart alone, and reading a 0..75
    # frame from its lower 60% gave a 0..50 axis and a 33 MPa median for a
    # curve printed at 50. Charts on these pages are separated by hundreds of
    # pixels, so a gap of a few is a break, not a boundary.
    groups.sort(key=lambda g: (g["y0"], g["y0"] - g["y1"]))
    merged = []
    for g in groups:
        p = merged[-1] if merged else None
        if p is not None and _xspan_overlap(p["xs"], g["xs"]) >= 0.8:
            if min(g["y1"], p["y1"]) - g["y0"] >= 0.8 * (g["y1"] - g["y0"]):
                # a band already held, seen again — one shorter run of the
                # same rule. Its columns are welcome; its extent is NOT. On
                # 00269 p49 letting it push the frame bottom down by a single
                # pixel moved the time-label strip off the labels.
                p["xs"] += g["xs"]
                continue
            if g["y0"] - p["y1"] <= max(20, H * 0.02):
                p["xs"] += g["xs"]
                p["y1"] = max(p["y1"], g["y1"])
                continue
        merged.append(dict(g))
    groups = merged

    out, orphans = [], []
    for g in groups:
        x0, x1 = min(g["xs"]), max(g["xs"])
        if x1 - x0 >= W * 0.3:
            out.append((x0, g["y0"], x1, g["y1"]))
        else:
            orphans.append(g)
    # Tallest first: the same broken rule also leaves short fragments of its
    # own chart behind, and a fragment must not become a second box for the
    # chart it is part of.
    for g in sorted(orphans, key=lambda g: g["y0"] - g["y1"]):
        x0, x1 = min(g["xs"]), max(g["xs"])
        x0, x1 = _band_edges(dark, g["y0"], g["y1"], lo, hi, x0, x1)
        if x1 - x0 < W * 0.3:
            continue                      # too narrow to be a plot
        b = (x0, g["y0"], x1, g["y1"])
        if any(_covered(b, o) for o in out):
            continue
        out.append(b)
    # Grown, two pieces of one broken frame become the same box: 00269 p35's
    # halves, as wide as each other, and 00053 p184's and 00182 p217's
    # fragments, which share their chart's rows. A box may not grow over
    # another chart, though — one that shares none of its rows and is not as
    # wide: on 00935's flattened pages the panel's lower box ran up the
    # panel's own border and swallowed the plot above it.
    def other_chart(o, b):
        apart = o[3] <= b[1] or o[1] >= b[3]
        same_width = abs(o[0] - b[0]) <= W * 0.02 and abs(o[2] - b[2]) <= W * 0.02
        return apart and not same_width

    # A pen drawn down the frame's own edge hides the rule: 00272 p56's blue
    # slurry rate runs along the left rule from 881 to the floor at 1012, the
    # rule's dark run stopped there, and the box lost its bottom 130 px with
    # the time labels under it ("time axis unreadable": stage 19 unread).
    # Asked only where the dark rules alone do not grow the box, and only the
    # BOTTOM may move; both sides must still agree where they end.
    a = np.asarray(img)
    pen = ((a.max(axis=2) - a.min(axis=2)) >= 60) & (a.sum(axis=2) < 600)

    def grow(b):
        g = _whole_rules(dark, b)
        if g == b:
            gp = _whole_rules(dark | pen, b)
            if gp[3] > b[3]:
                g = (b[0], b[1], b[2], gp[3])
        if g != b and any(o != b and _covered(o, g) and other_chart(o, b) for o in out):
            return b
        return g
    grown = []
    for b in sorted((grow(b) for b in out), key=lambda b: b[1] - b[3]):
        if not any(_covered(b, o) for o in grown):
            grown.append(b)
    out = sorted(grown, key=lambda b: b[1])
    return out


def _blank_body(img):
    """Is the page's upper chart area — where every STEP chart page draws its
    first plot — white? 00270 p30's is: not one pixel of ink between 15% and
    38% of the height and 15% and 85% of the width. Every page with a chart
    carries its curves and gridlines there (3-11% ink on 00184, 00243, 00270)."""
    H, W = img.shape[:2]
    c = np.asarray(img)[int(0.15 * H):int(0.38 * H), int(0.15 * W):int(0.85 * W)]
    return c.size > 0 and float((c.min(axis=2) < 200).mean()) < 0.002


def _side_by_side(img, rows_needed=3):
    """How many plots a row of this page prints side by side, from their
    horizontal gridlines: rules a fifth to a third of the page wide, two or
    more on one line, on three lines or more. 1 for an ordinary page.

    00241 p24 prints Treatment 1 — pumped in three attempts — as three
    surface charts in a row over three chemical charts, each squeezed to a
    third of the width. find_charts wants a frame 30% of the page wide and
    found none, so the page was skipped without a word and the file had no
    stage 1. Their labels are three or four pixels a character wide: the
    time labels read on two panels of the three and the value axes on none,
    so the page is reported rather than read."""
    H, W = img.shape[:2]
    dark = np.asarray(img).sum(axis=2) < 450
    lo, hi = int(W * 0.15), int(W * 0.36)
    best = 1
    hits = {}
    for y in range(H):
        segs = [(a, b) for a, b in _runs(dark[y], lo, gap=3, trim=0)
                if b - a <= hi]
        if len(segs) >= 2:
            key = tuple(round(a / 20.0) for a, _b in segs)
            hits[key] = hits.get(key, 0) + 1
    for key, n in hits.items():
        if n >= rows_needed:
            best = max(best, len(key))
    return best


def _whole_rules(dark, box, gap=8, agree=12):
    """A box grown to the full length of its own side rules, where they are
    printed broken.

    A rule printed barely darker than the cut-off breaks into pieces a pixel
    or a few apart, and no piece is long enough alone: 00269 p37's offset
    chart kept only its bottom 238 px of a 606 px frame (302-421, 428-549,
    550-669, 670-908), and every offset well above the lower third read
    blank. Only the box's own edge columns are asked, both sides must run on
    past the box and agree where they end, and a box only ever grows —
    bridging every column instead pulled 00184's frames down onto their
    time labels through a curve drawn beside the right-hand rule."""
    x0, y0, x1, y1 = box
    H, W = dark.shape

    def side(cols):
        best = None
        for x in cols:
            if not 0 <= x < W:
                continue
            for a, b in _runs(dark[:, x], (y1 - y0) // 2, gap=gap):
                if a <= y1 and b >= y0 and (best is None or b - a > best[1] - best[0]):
                    best = (a, b)
        return best

    left = side((x0, x0 + 1, x0 + 2))
    right = side((x1 - 2, x1 - 1, x1))
    if left is None or right is None:
        return box
    top = max(left[0], right[0])
    bottom = min(left[1], right[1])
    if abs(left[0] - right[0]) <= agree and top < y0 - agree:
        y0 = top
    if abs(left[1] - right[1]) <= agree and bottom > y1 + agree:
        y1 = bottom
    return (x0, y0, x1, y1)


def _xspan_overlap(xs_a, xs_b):
    """How much of the narrower x span the two share, 0..1. A one-column
    fragment (a broken rule with no partner) has no span of its own and counts
    as fully overlapping whatever contains it."""
    a0, a1, b0, b1 = min(xs_a), max(xs_a), min(xs_b), max(xs_b)
    ov = min(a1, b1) - max(a0, b0)
    w = min(a1 - a0, b1 - b0)
    if w <= 0:
        return 1.0 if ov >= 0 else 0.0
    return max(0.0, ov / float(w))


def _covered(b, o):
    """Is box b mostly inside box o? Charts on these pages stack, never
    overlap, so a box sharing most of another's rows AND columns is the same
    chart seen twice."""
    vov = min(b[3], o[3]) - max(b[1], o[1])
    hov = min(b[2], o[2]) - max(b[0], o[0])
    return (vov > 0.5 * (b[3] - b[1]) and hov > 0.5 * (b[2] - b[0]))


def _band_edges(dark, y0, y1, lo, hi, x0, x1):
    """Widen an unpaired frame edge using column darkness over its own rows.

    Only ever called for a group the run test could not pair, so it cannot
    move a box that was already found. A frame rule broken by scan noise still
    covers most of the band; gridlines, curves and text do not.
    """
    h = y1 - y0
    if h < 40:
        return x0, x1
    frac = dark[y0:y1, lo:hi].sum(axis=0) / float(h)
    cols = np.where(frac > 0.5)[0]
    if len(cols) < 2:
        return x0, x1
    return min(x0, int(cols[0]) + lo), max(x1, int(cols[-1]) + lo)


def page_meta(img):
    """OCR the header band -> {stage, interval, kind}. kind 'main' is the
    Treatment/Prop-Conc page; 'casing' is the Well Casing Pressure twin."""
    import re
    words = ar.ocr_words(img[:340], psm=6, whitelist="")
    text = " ".join(w[0] for w in words)
    meta = {"stage": None, "interval": "", "kind": "main"}
    m = re.search(r"Treatment\s+(\d+)", text)
    if m:
        meta["stage"] = int(m.group(1))
    m = re.search(r"([\d,]+\.\d+)\s*m\s*-\s*([\d,]+\.\d+)\s*m", text)
    if m:
        meta["interval"] = f"{m.group(1)}-{m.group(2)} m"
    if re.search(r"Treatment Analysis|Interval Summary|Prop Conc", text):
        meta["kind"] = "main"                # the 2019 tiled header names the page
    elif "Casing" in text.replace("Cacinn", "Casing"):
        meta["kind"] = "casing"
    elif "Prop Conc" not in text:
        # garbled OCR on the casing twin is common; main pages OCR cleanly
        meta["kind"] = "casing" if "Surface Pressure" not in text else "main"
    return meta


def _stage_titled_meta(img, box, meta):
    """Stage, interval and date of a page titled "<well> - Stage N", into
    `meta` (in place).

    00278 (Polar Star, 2017) heads every chart page "200/d-016-K/094-H-05 -
    Stage 1" over "3579.95 m - 3580.05 m", and prints the date in the info
    box under the top chart, "Date 2/12/2017". The pages are images with no
    text layer, and page_meta's read of the page's top band stops at the STEP
    header: all 60 charts came out "Interval ?" with no date. The lines sit
    just above the first chart's frame and are read from there. Only the
    word "Stage" is taken — the Shell books say "Treatment N", and their
    pages are numbered by the Daily Stage Summary when page_meta misses it.
    The date is month first (2/12 of a February job, filed 2017MAR15) unless
    the first number cannot be a month."""
    x0, y0, x1, y1 = box
    H, W = img.shape[:2]
    band = np.asarray(img)[max(0, y0 - 190):max(0, y0 - 20),
                           max(0, x0 - 150):min(W, x1 + 150)]
    if band.shape[0] < 20:
        return meta
    try:
        text = " ".join(w[0] for w in ar.ocr_words(band, psm=6, whitelist=""))
    except Exception:
        return meta
    m = re.search(r"\bStage\s*(\d{1,3})\b", text)
    if not m:
        return meta
    meta["stage"] = int(m.group(1))
    m = re.search(r"([\d,]+\.\d+)\s*m\s*-\s*([\d,]+\.\d+)\s*m", text)
    if m and not meta.get("interval"):
        meta["interval"] = f"{m.group(1)}-{m.group(2)} m"
    box_rows = np.asarray(img)[min(H, y1 + 40):min(H, y1 + 300), 0:x1]
    try:
        text = " ".join(w[0] for w in ar.ocr_words(box_rows, psm=6, whitelist=""))
    except Exception:
        text = ""
    m = re.search(r"\bDate\b\W*(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mo, d = (b, a) if a > 12 else (a, b)
        if 1 <= mo <= 12 and 1 <= d <= 31:
            meta["date"] = "%04d-%02d-%02d" % (y, mo, d)
    return meta


def _frame_bbox(img):
    """Plot box = bounding box of long strict-dark line runs (frame and
    gridlines are black in the new format).

    The BOTTOM cannot be found that way alone, because the frame's own bottom
    rule can be ANTI-ALIASED across two pixel rows and neither is dark enough
    to count. On 00344's surface chart:

        row 321, an interior gridline   (103,103,103)  sum 309   dark
        row 426, the frame's bottom     (170,170,170)  sum 510   not dark
        row 427, the rest of it         (143,143,143)  sum 429   not dark

    The rule is about 1.5 px tall, so it renders as two pale rows while a
    gridline that lands on one row renders darker than either. The lowest
    "dark" row was therefore the GRIDLINE. The box came back ending there,
    the clock strip was read from a band inside the plot, and all 32 surface
    charts died with "time axis unreadable" — the file exported its chemical
    traces and none of the four channels anyone wants (#693). The chemical
    chart on the same page has a crisply rendered floor and read fine, which
    is why the file looked half-alive rather than broken.

    The side rules do not have that problem: they are vertical, so a
    half-pixel of width darkens one column rather than splitting across two.
    The bottom is where they stop, taken as the contiguous run down from the
    top rule — contiguous because the rotated axis title ("Pressure (MPa)")
    puts more dark pixels in the same column well below the frame, and a
    plain min/max would swallow it.

    Only ever EXTENDS the row-based answer, so a page it already read
    correctly does not move.
    """
    H, W = img.shape[:2]
    dark = img.sum(axis=2) < 400
    col_ok = np.where(dark.sum(axis=0) > H * 0.6)[0]
    row_ok = np.where(dark.sum(axis=1) > W * 0.6)[0]
    if not len(col_ok) or not len(row_ok):
        return None
    x0, y0, x1, y1 = (int(col_ok[0]), int(row_ok[0]),
                      int(col_ok[-1]), int(row_ok[-1]))
    for x in (x1, x0):
        y = y0
        while y + 1 < H and dark[y + 1, x]:
            y += 1
        if y > y1:
            y1 = y
    return x0, y0, x1, y1


# colour family -> (series, unit, the QUANTITY its value axis measures).
# Keyed by quantity, not by axis position: these charts print Concentration as
# the inner right column and Rate as the outer one, and a position-keyed table
# ("right1"/"right2") had them exactly backwards — every concentration was
# exported on the rate scale and every rate on the concentration scale.
# Above this an axis is not a rate. Slurry rate on these charts tops out at
# 8-20 m3/min; a concentration axis starts in the hundreds. Used both to tell
# an unlabelled right-hand column apart and to refuse a rate title the numbers
# contradict.
RATE_AXIS_MAX = 50

# a pixel darker than this (R+G+B) is ink of some colour, not the page:
# the khaki where two pens blend at the floor sums to ~510, the palest
# column of an anti-aliased descent ~570, the paper 740+
INK_SUM = 700
INK_CHROMA = 20            # max(RGB) - min(RGB): below this it is grey or black, not a pen

NEW_SURFACE = {"red": ("Surface Pressure", "MPa", "pressure"),
               "blue": ("Slurry Rate", "m3/min", "rate"),
               "cyan": ("Slurry Rate", "m3/min", "rate"),
               "green": ("Prop Conc", "kg/m3", "conc"),
               "orange": ("Btm Prop Conc", "kg/m3", "conc")}


# An offset well's curve, as the legend of an offset chart names it:
# "F Well Casing Pressure (MPa)". The letter is the well's, and OCR reads an
# O as 0 (00248 p24's "0 Well"), so digits that look like letters are put back,
# and an E as "EE".
_OFFSET_WELL = re.compile(r"\b([A-Z0-9])\1?\s*W\s*[eo]\s*[l1I|]{2}\s+Casing\s+Pres",
                          re.IGNORECASE)        # "EE Well": a doubled letter
_WELL_LETTER = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z", "6": "G"}


# The fleet's own entries. "Amount of Units Running" is not one: 00185's
# treatment legend carries it too, and its chemical chart reprints that.
_FLEET = re.compile(r"Fleet\s+(?:Fuel|Avg|Load)", re.IGNORECASE)
_WELLS = re.compile(r"W\s*[eo]\s*[l1I|]{2}\s+Casing\s+Pres|Offset\s+Pres", re.IGNORECASE)
# a chemical legend: additive concentrations in L/m3, and the clean rate
_CHEM_LEGEND = re.compile(r"\(\s*L\s*/\s*m|Clean\s+Rate", re.IGNORECASE)


def _other_legend(img, box):
    """Does the legend over this plot name a pump fleet's quantities,
    neighbouring wells' pressures, or chemical additives? -> "fleet",
    "wells", "chemical" or "". An OCR of the
    band from just above the frame to the top of the plot, where the 2017
    books print their legend."""
    x0, y0, x1, y1 = box
    band = img[max(0, y0 - 80):min(y1, y0 + 120), x0:x1]
    try:
        text = " ".join(w[0] for w in ar.ocr_words(band, psm=6, whitelist=""))
    except Exception:
        return ""
    if len(_FLEET.findall(text)) >= 2:
        return "fleet"
    if len(_WELLS.findall(text)) >= 2:
        return "wells"
    if len(_CHEM_LEGEND.findall(text)) >= 2:
        return "chemical"
    return ""


def _offset_title(title):
    """Could this chart title be an offset chart's? Loosely: the OCR spells
    it "otfset" (00248 p96), and on some pages reads no title at all — just
    the interval and the legend — so a title naming no analysis also asks."""
    import difflib
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    near = lambda w, target, cut: difflib.SequenceMatcher(None, w, target).ratio() >= cut
    if any(near(w, "offset", 0.8) for w in words):
        return True
    return not any(near(w, "analysis", 0.75) for w in words)


def _offset_legend(img, box, band=150):
    """{colour family: (name, unit)} from an OFFSET chart's legend, or {}.

    The 2017 Shell books print, beside each stage's treatment and chemical
    charts, an offset chart: the stage's surface pressure and the casing
    pressures of the neighbouring wells, each a colour of its own, its axis
    ticks printed in that colour, and a legend of coloured text above the
    plot. ar.read_legend accepts only treatment names, so it named none of
    them, and the colour table named them as a treatment chart's: 00248 p24
    exported F Well's casing pressure as "Prop Conc", E Well's as "Slurry
    Rate", and C and O Wells as unnamed series. In a stage those are spliced
    with the treatment chart's curves of the same name — "bad end points for
    rate" on Stage 35 (#826) and a nameless "Series (magenta)" beside them.

    Each legend entry is found from ALL the ink in a band above the plot —
    one printed line, cut into entries where the ink leaves a wide gap —
    and only then given the colour most of its pixels carry. Masking by
    colour first does not work here: the anti-aliased edges of the BLACK
    entries ("A Well …") land in the blue, cyan and magenta masks and fuse
    the coloured lines either side of them. Each entry is read off the page
    itself, its colour turned to black on white.

    Fewer than two wells is not an offset chart, and returns {}.
    """
    from PIL import Image
    x0, y0, x1, y1 = box
    top = max(0, y0 - band)
    xa = max(0, x0 - 40)
    strip = np.asarray(img)[top:max(top, y0 - 2), xa:x1 + 40].astype(int)
    if strip.shape[0] < 12:
        return {}
    try:
        masks = ar.hue_masks(strip)
    except Exception:
        return {}
    lo = strip.min(axis=2)
    ink = lo < 170
    for m in masks.values():
        ink |= m
    # The lines are set tight — parentheses and descenders leave no blank row
    # between them — so cut at the valleys of the row profile instead.
    prof = ink.sum(axis=1)
    if not prof.any():
        return {}
    rows = np.flatnonzero(prof > max(3, 0.1 * np.percentile(prof[prof > 0], 90)))
    wells, named = {}, {}
    for ln in np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1):
        if len(ln) < 6:
            continue
        r0, r1 = ln[0], ln[-1] + 1
        cols = np.flatnonzero(ink[r0:r1].any(axis=0))
        for seg in np.split(cols, np.flatnonzero(np.diff(cols) > 40) + 1):
            if len(seg) < 40:
                continue
            c0, c1 = seg[0], seg[-1] + 1
            n_ink = int(ink[r0:r1, c0:c1].sum())
            counts = {f: int(m[r0:r1, c0:c1].sum()) for f, m in masks.items()}
            fam = max(counts, key=counts.get) if counts else None
            if fam is None or counts[fam] < 0.3 * n_ink:
                continue                    # a black entry: no colour to trace
            crop = lo[max(0, r0 - 2):r1 + 2, max(0, c0 - 2):c1 + 2]
            pil = Image.fromarray(np.clip(crop, 0, 255).astype(np.uint8))
            pil = pil.resize((pil.width * 4, pil.height * 4), Image.LANCZOS)
            raw = ar.ocr_line(np.array(pil), psm=7)
            mt = _OFFSET_WELL.search(raw)
            if mt:
                letter = mt.group(1).upper()
                letter = _WELL_LETTER.get(letter, letter)
                wells.setdefault(fam, (f"{letter} Well Casing Pressure", "MPa"))
                continue
            name = ar.match_legend_name(ar._legend_name(raw))
            if name:
                named.setdefault(fam, (name, "MPa" if "pressure" in name.lower()
                                       else ""))
    if len(wells) < 2:
        return {}
    for fam, v in named.items():
        wells.setdefault(fam, v)
    return wells


OFFSET_GROUP_LABEL = {"offset": "Offset Pressure", "abd": "ABD Pressure",
                      "casing": "Casing Pressure"}


def _offset_channels(img, box, rpress, main_cal, samples, ta, tb, t_start,
                     ink, sample_sec):
    """The offset and abandoned wells of an offset chart -> [channel].

    Each well is traced in its swatch's own colour — not a hue family: the
    legend's yellow, and the pale pink and pale green it uses for I and J
    Wells, are no family at all — and read against its group's axis, the
    offset wells against the inner right-hand pressure axis and the
    abandoned wells against the outer one. The legend box hides whatever is
    drawn under it, so it is cleared from every mask.
    """
    legend = _offset_inplot_legend(img, box)
    if not legend:
        return []
    x0, y0, x1, y1 = box
    cals = {}
    for group, seg in zip(("offset", "abd"), rpress):
        cal = ar.fit_ticks_guarded(seg) if seg else None
        if cal:
            cals[group] = cal
    plot = np.asarray(img)[y0:y1, x0:x1].astype(int)
    # A pale pen — I Well's pink, J Well's green — is the very colour of a
    # saturated pen's blended edge: where the red surface pressure falls
    # through I Well's line, its edges read as I Well and pulled it down
    # 3 MPa. So a pale pen keeps no pixel within 2 px of saturated ink.
    strong = (plot.max(axis=2) - plot.min(axis=2)) >= 100
    near_strong = np.zeros_like(strong)
    k = 2
    pad = np.pad(strong, k)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            near_strong |= pad[k + dy:k + dy + strong.shape[0],
                               k + dx:k + dx + strong.shape[1]]
    if main_cal:
        cals["main"] = main_cal
    out, used = [], set()
    for e in legend:
        cal = cals.get(e["group"])
        if cal is None or (e["group"] == "main" and not e.get("well")):
            continue                # the main group's own Surface Main is read already
        # a well on the main axis is still an offset well, and keeps the name
        # it has on the stages that plot it on the offset axis (00242)
        grp = "offset" if e["group"] == "main" else e["group"]
        rgb = np.asarray(e["rgb"], float)
        chroma = float(rgb.max() - rgb.min())
        tol = min(60.0, max(22.0, 0.35 * chroma))
        dist = np.sqrt(((plot - rgb) ** 2).sum(axis=2))
        sub = dist <= tol
        if chroma < 80:
            sub &= ~near_strong
        bx0, by0, bx1, by1 = e["box"]
        sub[by0:by1, bx0:bx1] = False
        cov = float(sub.any(axis=0).mean())
        if cov < 0.1:
            continue
        py = ar.curve_positions(sub, glyphs=True, edge_blank=True,
                                bracketed=True) + y0
        a, b, ntick = cal
        _vt, _vb, _sn = ar.snap_axis(a + b * y0, a + b * y1)
        if _sn and abs(y1 - y0) > 1:
            b = (_vb - _vt) / float(y1 - y0)
            a = _vt - b * y0
        vals = a + b * py
        if np.isfinite(vals).sum() < 50:
            continue
        t_cols = (ta + tb * (np.arange(sub.shape[1]) + x0)) - t_start
        v = ct.resample(samples, t_cols, vals)
        name = e["name"] if re.fullmatch(r"[A-Z] Well", e["name"]) else (
            "Well " + "#%02x%02x%02x" % tuple(int(c) for c in rgb))
        label = f"{name} {OFFSET_GROUP_LABEL[grp]}"
        if label in used:
            continue
        used.add(label)
        out.append({"key": "series-offset-" + re.sub(r"\W+", "-", label.lower()),
                    "label": label, "unit": "MPa",
                    "color": "#%02x%02x%02x" % tuple(int(c) for c in rgb),
                    "values": v, "ticks": ntick, "coverage": cov,
                    "axis_frame": (float(a + b * y0), float(a + b * y1)),
                    "filled_cols": 0,
                    "ends": _held_ends(ink, v, a, b, y0, tb, sample_sec),
                    # for the file-wide vote on the well's letter
                    # (pipeline._offset_well_names)
                    "offset": {"group": grp,
                               "rgb": [float(c) for c in rgb],
                               # (glyph alone, line, glyph settled by its
                               # shape) — see the vote's weights
                               "votes": list(e.get("votes", ("", "", False)))}})
    return out


def _offset_inplot_legend(img, box, top_frac=0.35):
    """An offset chart's legend drawn INSIDE its plot -> [entry], or [].

    The 2017 Shell books (00243-00245, 00269-00274) print an offset chart
    beside every stage: the stage's own surface pressure on the left axis,
    the offset wells' pressures on a second axis to the right, and the
    abandoned wells' on a third beyond it. The legend is a box in the plot's
    top left, one column per axis — "Pressure (Mpa)", "Offset Pressure
    (MPa)", "ABD Well Pressure (MPa)" — and under each a square swatch per
    well, "A Well (MPa)" beside it. Which well is which colour changes from
    file to file, so the legend is the only key. Only the surface pressure
    was read, and the rest of the chart was reported missing (#819).

    entry = {"rgb": swatch colour, "name": "A Well", "group": "offset" |
    "abd" | "main", "box": (x0, y0, x1, y1) of the whole legend, plot crop
    coordinates}. A swatch is a few pixels square, solid, with its label's
    dark text starting just right of it (as _drop_legend_swatches); its
    colour is the mean of its most saturated pixels, since the swatch's own
    edges are blended into the white around it.
    """
    from PIL import Image
    x0, y0, x1, y1 = box
    crop = np.asarray(img)[y0:y1, x0:x1].astype(int)
    H, W = crop.shape[:2]
    lim = max(20, int(H * top_frac))
    chroma = crop.max(axis=2) - crop.min(axis=2)
    lo = crop.min(axis=2)
    dark = lo < 200                 # the labels are grey type, not black
    found = ar._components(chroma[:lim] >= 25)
    if not found:
        return []
    sw = []
    for cp in found[0]:
        w = cp["c1"] - cp["c0"] + 1
        h = cp["y1"] - cp["y0"] + 1
        if not (3 <= w <= 16 and 3 <= h <= 16 and cp["n"] / float(w * h) >= 0.6):
            continue
        right = dark[cp["y0"]:cp["y1"] + 1, cp["c1"] + 2:cp["c1"] + 40]
        cols = np.flatnonzero(right.any(axis=0))
        if len(cols) < 5 or cols[0] > 26:
            continue
        px = crop[cp["y0"]:cp["y1"] + 1, cp["c0"]:cp["c1"] + 1].reshape(-1, 3)
        ch = px.max(axis=1) - px.min(axis=1)
        rgb = px[ch >= np.percentile(ch, 70)].mean(axis=0)
        sw.append({"c0": cp["c0"], "c1": cp["c1"], "y0": cp["y0"],
                   "y1": cp["y1"], "rgb": rgb})
    if len(sw) < 3:
        return []
    # columns of the legend: swatches stacked at (nearly) one x
    sw.sort(key=lambda e: (e["c0"], e["y0"]))
    columns = []
    for e in sw:
        if columns and abs(e["c0"] - columns[-1][0]["c0"]) <= 8:
            columns[-1].append(e)
        else:
            columns.append([e])
    for col in columns:
        col.sort(key=lambda e: e["y0"])

    def clean(r0, r1, c0, c1, scale=5):
        piece = lo[max(0, r0):r1, max(0, c0):min(W, c1)].astype(float)
        if piece.size == 0:
            return None
        # the plot's vertical gridlines run straight through the legend's
        # text (it is drawn over the grid, not on a blank box) and turn
        # "Well" into "Vvetl": a column dark from top to bottom is a gridline
        piece[:, (piece < 200).mean(axis=0) >= 0.7] = 255
        # grey type: stretch it to black on white
        mn = piece.min()
        if mn < 250:
            piece = np.clip((piece - mn) * 255.0 / (255.0 - mn), 0, 255)
        piece = np.pad(piece, 4, constant_values=255)
        pil = Image.fromarray(piece.astype(np.uint8))
        pil = pil.resize((pil.width * scale, pil.height * scale), Image.LANCZOS)
        return np.array(pil)

    def read(r0, r1, c0, c1):
        arr = clean(r0, r1, c0, c1)
        return ar.ocr_line(arr, psm=7) if arr is not None else ""

    def letter(e, c1):
        # The well's letter is one capital before "Well", and reading it in
        # the line ("& Vvell", "5S wel" for A and B) is what fails: read it
        # alone. It is the first glyph right of the swatch, up to the gap
        # before "Well". At 8 px tall two letters still need their shape: an
        # I is a bar too thin for tesseract to see at all, and a B reads as
        # S — told apart by B's straight left stroke, inked top to bottom.
        r0, r1 = max(0, e["y0"] - 3), e["y1"] + 4
        ink = lo[r0:r1, e["c1"] + 2:c1] < 200
        cols = np.flatnonzero(ink.any(axis=0))
        if not len(cols):
            return ""
        # the first glyph standing a letter tall: a column or two of the
        # swatch's blended edge comes before it
        for g in np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1):
            glyph = ink[:, g[0]:g[-1] + 1]
            rows = np.flatnonzero(glyph.any(axis=1))
            if len(rows) >= 5:
                break
        else:
            return ""
        if glyph.shape[1] <= 3:
            return "I*"                     # * = settled by shape, not OCR
        a, b = e["c1"] + 2 + g[0], e["c1"] + 2 + g[-1] + 1
        votes = {}
        for scale, binz, psm in ((4, False, 10), (4, False, 8), (6, False, 10),
                                 (4, True, 7), (8, True, 10)):
            arr = clean(r0, r1, a - 1, b + 1, scale=scale)
            if arr is None:
                return ""
            if binz:
                arr = np.where(arr < 150, 0, 255).astype(np.uint8)
            got = "".join(t for t, _x, _y in ar.ocr_words(
                arr, psm=psm, whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            if len(got) == 1:
                votes[got] = votes.get(got, 0) + 1
        if not votes:
            return ""
        ch = max(votes, key=votes.get)
        left = glyph[rows[0]:rows[-1] + 1, :2].any(axis=1)
        if ch == "S" and left.mean() >= 0.85:
            ch = "B*"
        return ch

    out = []
    seen_groups = []
    for k, col in enumerate(columns):
        right = columns[k + 1][0]["c0"] - 6 if k + 1 < len(columns) else min(W, col[0]["c0"] + 260)
        top = min(e["y0"] for e in col)
        head = read(top - 17, top - 1, col[0]["c0"] - 4, right).lower()
        group = ("abd" if "abd" in head or "aband" in head
                 else "offset" if "offset" in head else "main")
        raws = [read(e["y0"] - 4, e["y1"] + 5, e["c1"] + 2, right) for e in col]
        has_main = any(re.search(r"surf|main", r, re.I) for r in raws)
        if group == "main" and not has_main and "main" in seen_groups:
            # A column after the main one whose header did not read is not
            # the main axis's: 00241 p55's "ABD Well Pressure" header reads
            # as nothing, and its D and J Wells are the abandoned wells.
            group = "abd" if "offset" in seen_groups else "offset"
        seen_groups.append(group)
        for e, raw in zip(col, raws):
            name = ar._legend_name(raw)
            mw = re.search(r"(?:w|vv)\s*[eo]", raw, re.I)
            # From stage 26 on, 00242 lists A Well under "Pressure (Mpa)",
            # beside Surface Main: plotted on the main axis, and never read.
            # Only in the column that holds Surface Main.
            on_main = (group == "main" and has_main and mw is not None
                       and not re.search(r"surf|main", raw, re.I))
            if (group != "main" or on_main) and mw:
                # "X Well (MPa)": the letter as the line read it, and as the
                # glyph alone reads it. Each misses where the other does not
                # — the line gives "&" and "5S" for A and B on 00243's 8 px
                # type, the glyph alone nothing on 00269's — so take the
                # glyph's, else the line's.
                pre = raw[:mw.start()].strip()
                pre = {"|": "I", "l": "I", "1": "I", "0": "O"}.get(pre, pre)
                from_line = pre if re.fullmatch(r"[A-Z]", pre) else ""
                shaped = letter(e, right)
                glyph = shaped.rstrip("*")
                e["votes"] = (glyph, from_line, shaped.endswith("*"))
                ch = (glyph if shaped.endswith("*") else
                      from_line or glyph)
                name = (ch + " Well") if ch else ""
            out.append({"rgb": e["rgb"], "name": name, "group": group,
                        "row": (e["y0"], e["y1"]), "col": (e["c0"], right),
                        "votes": e.get("votes", ("", "")), "well": bool(on_main)})
    if not any(e["group"] != "main" for e in out):
        return []
    bx0 = min(e["col"][0] for e in out) - 10
    bx1 = max(e["col"][1] for e in out) + 10
    by0 = min(e["row"][0] for e in out) - 22
    by1 = max(e["row"][1] for e in out) + 10
    for e in out:
        e["box"] = (max(0, bx0), max(0, by0), min(W, bx1), min(H, by1))
    return out


# A neighbouring well's pen as the legend UNDER an offset chart names it:
# "E Well Casing (MPa)", and on one well "B well lower pop valve (MPa)". The
# OCR reads an a as s on 00198 p21: "E Well Cssing", "lower pop vsive".
_CASING_ENTRY = re.compile(r"^\W*([A-Z0-9])\s*[Ww]\s*[eo]\s*[l1I|]{2}\s+"
                           r"(C\w{2,3}ing|lower\s+pop)\b", re.IGNORECASE)


def _casing_legend(img, box, band=230):
    """[{"rgb", "label"}] for the wells an offset chart's legend names UNDER
    its plot, or [] (fewer than two wells: not an offset chart).

    The Shell 2017 books 00196-00201 print, after each stage's treatment and
    chemical pages, a page titled "Offset Analysis": one chart, one Pressure
    axis, and in a column under the time axis a swatch per pen — SURFACE Main
    in red, then "E Well Casing (MPa)", "C Well Casing", "B Well Casing", "A
    Well Casing", "F Well Casing", "B well lower pop valve", "D Well Casing"
    (00196 p19). Every pen is on the one pressure axis. Only the red was read
    — through the treatment colour table — so seven wells went missing on
    some fifty charts a file. Neither offset reader applied: the 00243 books
    put their legend inside the plot and the wells on their own right-hand
    axes (_offset_inplot_legend), the 00248 ones above it (_offset_legend).

    The legend is not the same from stage to stage: 00201 p20 lists F Well in
    magenta, p80 lists D Well in that dark orange and O Well in magenta. So
    each page's own legend names its pens, and the file-wide vote by colour
    (pipeline._offset_well_names) is not asked: at this type size the line
    reads whole.

    A swatch is a small solid square with a gap before its text (the header
    "Pressure (MPa)" starts with a letter of about the same size and none);
    the swatches stand in one column, three or more. The grey A Well swatch
    has no colour at all, so ink of any colour is looked for, not hue.
    """
    from PIL import Image
    x0, y0, x1, y1 = box
    H, W = img.shape[:2]
    top, bot = min(H, y1 + 20), min(H, y1 + band)
    xa, xb = max(0, x0 - 50), min(W, x1)
    reg = np.asarray(img)[top:bot, xa:xb].astype(int)
    if reg.shape[0] < 20 or reg.shape[1] < 40:
        return []
    lo = reg.min(axis=2)
    ink = lo < 215
    found = ar._components(ink)
    if not found:
        return []
    sw = []
    for cp in found[0]:
        w = cp["c1"] - cp["c0"] + 1
        h = cp["y1"] - cp["y0"] + 1
        if not (5 <= w <= 14 and 5 <= h <= 14 and abs(w - h) <= 3):
            continue
        if cp["n"] / float(w * h) < 0.7:
            continue
        right = ink[cp["y0"]:cp["y1"] + 1, cp["c1"] + 1:cp["c1"] + 30]
        gap = np.flatnonzero(right.any(axis=0))
        if not len(gap) or gap[0] < 3:
            continue
        # the colour of the swatch's middle: its edges are blended into the
        # white around it (JPEG), and a mean over them turns red to pink
        cy, cx = (cp["y0"] + cp["y1"]) // 2, (cp["c0"] + cp["c1"]) // 2
        rgb = reg[cy - 1:cy + 2, cx - 1:cx + 2].reshape(-1, 3).mean(axis=0)
        sw.append(dict(cp, rgb=rgb))
    columns = []
    for e in sorted(sw, key=lambda e: e["c0"]):
        if columns and abs(e["c0"] - columns[-1][0]["c0"]) <= 3:
            columns[-1].append(e)
        else:
            columns.append([e])
    out = []
    for col in columns:
        if len(col) < 3:
            continue
        for e in sorted(col, key=lambda e: e["y0"]):
            r0, r1 = max(0, e["y0"] - 4), e["y1"] + 5
            line = ink[r0:r1, e["c1"] + 3:]
            cs = np.flatnonzero(line.any(axis=0))
            if not len(cs):
                continue
            # the entry's own words: up to the first gap wider than a space
            cs = np.split(cs, np.flatnonzero(np.diff(cs) > 25) + 1)[0]
            c0, c1 = e["c1"] + 3 + cs[0], e["c1"] + 3 + cs[-1] + 1
            crop = lo[r0:r1, max(0, c0 - 3):c1 + 3].astype(float)
            mn = crop.min()
            if mn < 250:                    # grey type: stretch it to black
                crop = np.clip((crop - mn) * 255.0 / (255.0 - mn), 0, 255)
            crop = np.pad(crop, 6, constant_values=255)
            pil = Image.fromarray(crop.astype(np.uint8))
            pil = pil.resize((pil.width * 4, pil.height * 4), Image.LANCZOS)
            m = _CASING_ENTRY.search(ar.ocr_line(np.array(pil), psm=7))
            if not m:
                continue
            letter = m.group(1).upper()
            letter = _WELL_LETTER.get(letter, letter)
            what = ("Casing" if m.group(2)[0] in "Cc"
                    else "Lower Pop Valve")
            out.append({"rgb": e["rgb"], "label": f"{letter} Well {what} Pressure"})
    return out if len(out) >= 2 else []


def _swatch_family(rgb):
    """The hue family (auto_raster.hue_masks) a legend swatch's colour falls
    in, or None — yellow and grey are in none. The rules are hue_masks' own,
    applied to a patch of that one colour. A magenta, (242,33,189) on 00196
    p19, passes the red rule as well (red well above green and blue); a red
    swatch passes no other, so the other family is the one meant."""
    patch = np.tile(np.asarray(rgb, float).reshape(1, 1, 3), (21, 21, 1))
    fams = [f for f in ar.hue_masks(patch)]
    if len(fams) > 1 and "red" in fams:
        fams.remove("red")
    return fams[0] if len(fams) == 1 else None


def _casing_masks(img, box, legend, masks):
    """Each legend entry's pen as a plot-cropped mask, keyed like `legend`.

    A coloured pen is its hue family's ink — the swatch's own colour is too
    narrow a test, because the JPEG pales a two-pixel pen: 00196 p19's orange
    D Well is (245,189,40) in the swatch and (231,179,103) on the line. Where
    two entries share a family each takes the ink nearer its swatch. Yellow
    (B Well) falls in no family and is taken by the yellow pen's own rule
    (_yellow_pen). Grey (A Well, (136,135,140)) is ink without colour of
    middling darkness, clear of the black grid: the gridlines' blurred edges
    are grey too, and they are within a pixel of black.
    """
    x0, y0, x1, y1 = box
    plot = np.asarray(img)[y0:y1, x0:x1].astype(int)
    r, g, b = plot[..., 0], plot[..., 1], plot[..., 2]
    chroma = plot.max(axis=2) - plot.min(axis=2)
    fam_of = [_swatch_family(e["rgb"]) for e in legend]
    out = []
    for i, e in enumerate(legend):
        fam = fam_of[i]
        rgb = np.asarray(e["rgb"], float)
        if fam is not None:
            m = masks.get(fam)
            if m is None:
                out.append(None)
                continue
            sub = m[y0:y1, x0:x1].copy()
            rivals = [np.asarray(legend[j]["rgb"], float)
                      for j in range(len(legend)) if j != i and fam_of[j] == fam]
            if rivals:
                d_own = ((plot - rgb) ** 2).sum(axis=2)
                for rv in rivals:
                    sub &= d_own <= ((plot - rv) ** 2).sum(axis=2)
        elif float(rgb.max() - rgb.min()) < 25:
            mean = plot.mean(axis=2)
            sub = (chroma < 18) & (mean > 105) & (mean < 170)
            sub &= ~_grow(plot.sum(axis=2) < 200, 1)
            # nor beside a coloured pen: blue over orange blends to grey, and
            # on 00197 p19 E Well's blue edge on O Well's orange, (122,131,
            # 162), pulled A Well (at 0.4) up to 9.8 MPa in a third of the
            # columns
            hues = np.zeros_like(sub)
            for m in masks.values():
                hues |= m[y0:y1, x0:x1]
            sub &= ~_grow(hues, 1)
        elif rgb[0] > 200 and rgb[1] > 200 and rgb[2] < 120:
            # ...and a bright one: on 00196 p41 green C Well runs over orange
            # D Well at 9 MPa, and where the two blend the page is a dull
            # yellow, (206,211,67), that was read as B Well — which is at 0.4,
            # its line (240,226,101). Nor can it be "clear of green": there
            # its blend with the cyan beside it, (201,241,118), is green. And
            # red and green nearly equal: the top edge of 00197 p59's dark
            # orange O Well, (238,205,92), is bright and yellowish too.
            sub = (r > 225) & (g > 200) & (b < 130) & (np.abs(r - g) < 25)
        else:
            out.append(None)
            continue
        out.append(sub)
    return out


def _grow(mask, k):
    """`mask` dilated by k pixels (a square neighbourhood)."""
    pad = np.pad(mask, k)
    out = np.zeros_like(mask)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            out |= pad[k + dy:k + dy + mask.shape[0], k + dx:k + dx + mask.shape[1]]
    return out


def _pen_channel(sub, cal, box, ta, tb, t_start, samples, ink, sample_sec,
                 label, key, rgb, glyphs=True):
    """One pen's mask (plot-cropped) read against its axis -> channel, or
    None where too little of it is on the page. glyphs: see
    auto_raster.curve_positions."""
    x0, y0, x1, y1 = box
    cov = float(sub.any(axis=0).mean())
    if cov < 0.1:
        return None
    py = ar.curve_positions(sub, glyphs=glyphs, edge_blank=True,
                            bracketed=True) + y0
    a, b, ntick = cal
    _vt, _vb, _sn = ar.snap_axis(a + b * y0, a + b * y1)
    if _sn and abs(y1 - y0) > 1:
        b = (_vb - _vt) / float(y1 - y0)
        a = _vt - b * y0
    vals = a + b * py
    if np.isfinite(vals).sum() < 50:
        return None
    t_cols = (ta + tb * (np.arange(sub.shape[1]) + x0)) - t_start
    v = ct.resample(samples, t_cols, vals)
    return {"key": key, "label": label, "unit": "MPa",
            "color": "#%02x%02x%02x" % tuple(int(c) for c in rgb),
            "values": v, "ticks": ntick, "coverage": cov,
            "axis_frame": (float(a + b * y0), float(a + b * y1)),
            "filled_cols": 0,
            "ends": _held_ends(ink, v, a, b, y0, tb, sample_sec)}


def _casing_channels(img, box, cal, masks, samples, ta, tb, t_start, ink,
                     sample_sec):
    """The neighbouring wells of an offset chart whose legend is printed
    under the plot (see _casing_legend) -> [channel], each read against the
    chart's one pressure axis."""
    legend = _casing_legend(img, box)
    if not legend or cal is None:
        return []
    out, used = [], set()
    for e, sub in zip(legend, _casing_masks(img, box, legend, masks)):
        if sub is None or e["label"] in used:
            continue
        ch = _pen_channel(sub, cal, box, ta, tb, t_start, samples, ink,
                          sample_sec, e["label"],
                          "series-casing-" + re.sub(r"\W+", "-", e["label"].lower()),
                          e["rgb"])
        if ch is not None:
            used.add(e["label"])
            out.append(ch)
    return out


# "Coil Pressure", "COIL #1 CIRCULATING PRESSURE"; 00243 p77's 8 px type
# reads "Coe Pressure"
_COIL = re.compile(r"\bco[a-z1|]{0,3}\b.*\b(pres|circ)", re.IGNORECASE)


def _legend_names_coil(img, box):
    """Does a yellow swatch in this chart's legend name the coil's pressure?

    The coil-tubing stages of the Shell 2017 books draw a fifth pen, yellow,
    on the pressure axis: "Coil Pressure (MPa)" in the key inside the plot
    (00243 p77) or "COIL #1 CIRCULATING PRESSURE" in the one under it (00198
    p75). No colour table names yellow, so it was never read. A yellow pen
    is not always the coil — 00100 p173 draws a yellow "Well 3" — so the
    legend has to say so. The swatch is looked for where these books print
    their keys: the top third of the plot, and the band under it."""
    from PIL import Image
    x0, y0, x1, y1 = box
    a = np.asarray(img).astype(int)
    H, W = a.shape[:2]
    for ra, rb in ((y0, y0 + int(0.35 * (y1 - y0))), (min(H, y1 + 20), min(H, y1 + 230))):
        reg = a[ra:rb, max(0, x0 - 50):x1]
        if reg.shape[0] < 8:
            continue
        r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
        yel = (r > 170) & (g > 160) & (b < 140) & (np.abs(r - g) < 45)
        lo = reg.min(axis=2)
        found = ar._components(yel)
        if not found:
            continue
        for cp in found[0]:
            w = cp["c1"] - cp["c0"] + 1
            h = cp["y1"] - cp["y0"] + 1
            # 3 px: 00242 p72 renders the page smaller, and its swatch is 5x3
            if not (3 <= w <= 16 and 3 <= h <= 16 and abs(w - h) <= 4):
                continue
            if cp["n"] / float(w * h) < 0.6:
                continue
            r0, r1 = max(0, cp["y0"] - 4), cp["y1"] + 5
            ink = lo[r0:r1, cp["c1"] + 2:] < 200
            cs = np.flatnonzero(ink.any(axis=0))
            if len(cs) < 12 or cs[0] > 26:
                continue
            cs = np.split(cs, np.flatnonzero(np.diff(cs) > 25) + 1)[0]
            piece = lo[r0:r1, cp["c1"] + 2 + cs[0]:cp["c1"] + 3 + cs[-1]].astype(float)
            # the plot's gridlines run through an in-plot key's text
            piece[:, (piece < 200).mean(axis=0) >= 0.7] = 255
            mn = piece.min()
            if mn < 250:
                piece = np.clip((piece - mn) * 255.0 / (255.0 - mn), 0, 255)
            piece = np.pad(piece, 6, constant_values=255)
            # 6x for the smaller render: 00242 p72's "Coil" reads "Sou" at 4x
            for scale in (4, 6):
                pil = Image.fromarray(piece.astype(np.uint8))
                pil = pil.resize((pil.width * scale, pil.height * scale), Image.LANCZOS)
                if _COIL.search(ar.ocr_line(np.array(pil), psm=7)):
                    return True
    return False


def _bar_tag(tag, title, chans):
    """A titled chart's tag, put right where the bar over it is the wrong one
    -> (tag, note or None).

    00241 prints stage 31's offset chart (p84) under "Chemical Analysis" and
    its chemical chart (p85) under "Offset Analysis". Read as chemical, the
    offset chart lost its Surface Pressure (_name_chemical drops it), and the
    chemical chart's clean rate went out as the stage's Slurry Rate. A chart
    that carries offset wells is the offset chart, filed with the surface
    charts as every other one is; an "offset" chart with no pressure on it is
    a chemical chart."""
    if any(c.get("offset") for c in chans):
        return "t", None
    if tag == "t" and "offset" in (title or "") and not any(_is_pressure(c) for c in chans):
        return "c", ("a chemical chart under the \"Offset Analysis\" bar: its "
                     "axes are the chemical chart's, and it is read as one")
    return tag, None


_UNIT_KIND = {"mpa": "pressure", "kpa": "pressure", "psi": "pressure",
              "kg/m3": "conc", "l/m3": "conc", "m3/min": "rate"}


def _legend_unit_for(name, unit):
    """A legend entry's unit, or "" where it cannot be the unit of what the
    entry names. The OCR matches units loosely, and 00247 p23's "Prop Conc
    (kg/m3)" came back "kPa": a concentration exported in kPa, which also
    makes it a pressure to every check downstream. The table's unit for that
    name stands in where there is one."""
    low = (name or "").lower()
    kind = ("pressure" if "press" in low else "conc" if "conc" in low
            else "rate" if "rate" in low else None)
    got = _UNIT_KIND.get((unit or "").lower())
    if kind is None or got is None or got == kind:
        return unit
    for (_tag, _fam), (nm, u) in SERIES_NAMES.items():
        if nm == name:
            return u
    return ""


def _name_chemical(tag, chans):
    """Stop the SURFACE colour table naming a CHEMICAL chart's curves.

    NEW_SURFACE says what red/blue/green/orange mean on the treatment chart.
    The chemical twin reuses those inks for something else entirely: its left
    axis is Chem Conc and its green and orange are additive concentrations,
    not proppant. Named through the surface table they arrive as "Prop Conc"
    and "Btm Prop Conc", canonicalise to WH/BH Prop Conc, and land in the
    export beside — or on top of — the real ones off the surface chart. On
    00199 p37 the chemical chart offered both under a 0..10 axis.

    Rate is the one channel that survives the crossing, because the chemical
    chart's rate axis really is a rate; it is the CLEAN rate rather than the
    slurry rate, which is the same rename extract_page makes on the tiled
    layout. Concentrations get a colour-keyed name and no unit: which additive
    a curve is takes reading the legend, and this chart carries a dozen. An
    unnamed extra column is honest; a wrong canonical one is not.
    """
    if tag != "c":
        return
    # Nor does a chemical chart carry the surface pressure. Its left axis is
    # Chem Conc, and "Surface Pressure" means only that the axis title did not
    # read and the reader assumed pressure: 00745 p156's chemical chart sent a
    # 2.1 "MPa" curve to sit beside Stage 1's real 71 MPa one.
    chans[:] = [c for c in chans if c["label"] != "Surface Pressure"]
    for c in chans:
        if c["label"] == "Slurry Rate":
            c["label"] = "Combined Clean Rate"
        elif c["label"] in ("Prop Conc", "Btm Prop Conc"):
            c["label"] = "Chem Conc ({})".format(
                str(c.get("key", "")).split("-")[-1] or "?")
            c["unit"] = ""


def _right_columns(pts, gap=18):
    """Right-hand tick labels [(value, x, y)] -> one [(value, y, True)] list
    per column, cut on x gaps. A rotated axis title is a column of its own
    here, and drops out later because its OCR speckle admits no linear fit."""
    out, cur, prev = [], [], None
    for v, px, py in sorted(pts, key=lambda p: p[1]):
        if prev is not None and px - prev > gap:
            out.append(cur)
            cur = []
        cur.append((v, py, True))
        prev = px
    if cur:
        out.append(cur)
    return out


def _restore_hour_tens(got):
    """[(seconds, x)] clock labels -> the same, a dropped leading 1 or 2 put
    back on an hour. A label whose hour read as one digit carries +0.5 s
    (see _clock_axis's label()), and is otherwise as read.

    00935 p63 (Interval 14.1, #810) prints 15:08 .. 15:22 and read "5:08",
    "15:12", "5:16", "5:20": a ten-hour step between neighbours, and a fit
    through it gave a 37-hour stage. A one-digit hour within one of the last
    digit of a two-digit hour read on the same strip takes its tens."""
    twos = [int(sec // 3600) for sec, _x in got if sec % 1 == 0 and sec >= 36000]
    out = []
    for sec, x in got:
        if sec % 1:
            sec -= 0.5
            h = int(sec // 3600)
            near = [t for t in twos if abs(t % 10 - h) <= 1]
            if near:
                sec += (max(set(near), key=near.count) // 10) * 36000
        out.append((sec, x))
    return out


def _clock_axis(img, x0, x1, y1):
    """The "HH:MM" labels under the frame -> (seconds at x=0, sec/px), or
    None. Seconds are of the day, so t0 is the chart's wall-clock start."""
    from PIL import Image
    import trican_charts as tc
    H, W = img.shape[:2]
    ya, yb = min(H - 1, y1 + 2), min(H, y1 + 48)
    xa, xb = max(0, x0 - 30), min(W, x1 + 30)
    strip = np.asarray(img[ya:yb, xa:xb]).astype(np.uint8)
    if strip.size == 0:
        return None
    big = np.array(Image.fromarray(strip).resize((strip.shape[1] * 3, strip.shape[0] * 3),
                                                 Image.LANCZOS)).astype(int)

    def label(text):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            # the hour's digit count rides along: see _restore_hour_tens
            return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                    + (0.5 if len(m.group(1)) == 1 else 0.0))
        return None

    # Each label is read on its own. A three-hour stage prints its labels
    # forty pixels apart at this render, and one read over the whole strip
    # runs them together — "10:5011:0011:1011:20", one position for four
    # labels — so 00180-1021 p117 got one usable label from the nineteen
    # printed and fell to the numeric reader, which fitted a three-minute
    # stage. The ink separates cleanly at the gaps between labels (wider
    # than the gaps inside one), so the strip is cut there and each piece
    # read as a line, its position the piece's own centre.
    dark = big.sum(axis=2) < 450

    def cut_at(gap):
        got = []
        for a, b in ar._col_groups(dark, gap=gap, min_w=30):
            left = max(0, a - 6)
            sub = big[:, left:min(big.shape[1], b + 6)]
            for text, wx, _wy in ar.ocr_words(sub, psm=7, whitelist="0123456789:"):
                sec = label(text)
                if sec is not None:
                    # the word's own centre, not the piece's: a piece that
                    # takes in the legend's first word beside the axis put
                    # 00935 p69's 17:05 ninety pixels right, and its chart
                    # ran 73 minutes for the 69 its labels span
                    got.append((sec, xa + (left + wx) / 3.0))
                    break
        return got
    # A blurred render opens the gaps either side of the colon past the cut:
    # 00935 p41 (#810) came apart as "03", "04", the whole-strip read below
    # took 03:04 for 09:02, and stage 3 was clocked six hours late. Wider
    # cuts are tried only where the first reads too little.
    pts = cut_at(20)
    for gap in (45, 75):
        if len(pts) >= 3:
            break
        wider = cut_at(gap)
        if len(wider) > len(pts):
            pts = wider
    def whole():
        got = []
        for text, wx, _wy in ar.ocr_words(big, psm=6, whitelist="0123456789:"):
            sec = label(text)
            if sec is not None:
                got.append((sec, xa + wx / 3.0))
        return got

    def fitted(got):
        # The labels as read, and with their dropped tens put back, each
        # fitted; the line that passes more of them wins, the labels as read
        # on a tie. A tens put back can make a label plausible that was
        # misread twice over: 00935 p65 read 15:55 as "5:50", and as 15:50
        # it pulled a four-label fit to an 82-minute chart where the page
        # prints 59.
        cands = []
        raw = [(sec - 0.5 if sec % 1 else sec, x) for sec, x in got]
        for variant in (raw, _restore_hour_tens(got)):
            if len(variant) < 3:
                continue
            variant = sorted(variant, key=lambda p: p[1])
            f = tc._b_clock_fit(variant, x0, x1, as_read_first=True)
            if f is not None and f[1] > 0:
                on = sum(1 for sec, x in variant if abs(f[0] + f[1] * x - sec) <= 90)
                cands.append((on, f))
        return max(cands, key=lambda c: c[0])[1] if cands else None
    # the whole-strip read, for a strip the columns did not separate — or
    # separated into labels that fit nothing: 00935 p47 (stage 6) cut three
    # misread pieces, and its six good labels read whole were never asked
    fit = fitted(pts) or fitted(whole())
    if fit is None:
        return None
    a, b = float(fit[0]), float(fit[1])
    if a + b * x0 < 0:
        # a chart that opens before the midnight its labels count from
        # (00180-1021 p112 read -1:59:41): the same clock, the day before
        a += 86400.0
    return a, b


def _pale_titles(rows, xa, xb, ccw, only=None):
    """The axis titles of a strip whose plain reading found no title at all,
    read again with the ink stretched to black -> [(qty, x)].

    00272-00274 print "Main Pressure (MPa)", "Offset Pressure (MPa)", "Rate
    (m3/min)" and "Concentration (kg/m3)" in a pale, condensed brown that
    reads as speckle beside the page's border rule; stretched, they read.
    Without a left title the chart went to the colour-keyed reader, which read
    the red alone (single-pen charts: 00272 11, 00273 16, 00274 23), and
    without right titles 00273 p21's rate and concentration columns fitted
    nothing. On the left only `only` is taken (pressure): a chemical chart's
    "Clean Rate" or "Chem Conc" stays unread, so the chemical charts stay with
    the colour-keyed reader that names their curves from the legend (see the
    00271 note in _extract_new_chart). The right titles only delimit columns."""
    lo = np.asarray(rows).min(axis=2).astype(float)
    for a, b in ((90.0, 200.0), (60.0, 220.0)):
        # the darkest channel stretched, not cut: a hard threshold before the
        # 3x upscale leaves the condensed letters blocky and unread
        g = np.repeat(np.clip((lo - a) * 255.0 / (b - a), 0, 255)[..., None], 3, axis=2)
        try:
            got = [t for t in ar.read_axis_titles(g, xa, xb, ccw=ccw)
                   if only is None or t[0] == only]
        except Exception:
            got = []
        if got:
            return got
    return []


def _extract_new_chart(img, sample_sec=1.0, box=None, require_titles=False):
    """Chart with black tick labels on stacked value axes, each named by its
    own rotated title (Pressure / Rate / Concentration).

    `box` gives the plot frame explicitly. The new format renders one chart
    per image so the frame can be found from the image alone, but the SAME
    chart style also appears on the TILED layout (Shell 2017: 00269, 00271-4),
    where one composited page carries two of them and each must be read inside
    its own rows only. `require_titles` refuses the page when no axis title
    can be read, which is how the caller tells this style apart from the older
    tiled charts whose tick labels are colour-keyed instead (00183).
    """
    img = np.asarray(img).astype(int)
    if box is None:
        box = _frame_bbox(img)
    if box is None:
        raise ValueError("step1: no frame")
    x0, y0, x1, y1 = box
    # The 2019 tiled books label the axis with a wall clock — 13:40, 13:50
    # … — and nothing else. Read that first, the way layout B's is read
    # (trican_charts._b_clock_fit: misread hours put back on the minute
    # ladder), from the strip upscaled three times, which is what makes
    # this font's 7-pixel digits legible; the numeric reader, tried second,
    # took "13:50" for minutes on 00180-1021 p98 and fitted a 140-second
    # stage. A "Time (min)" axis has no colons and falls straight through.
    tcal = _clock_axis(img, x0, x1, y1)
    clock_axis = tcal is not None
    if tcal is None:
        tcal = ar.time_calibration(img, x0, x1, y1)
    if tcal is None:
        raise ValueError("step1: time axis unreadable")
    ta, tb = tcal
    t_start = ta + tb * x0
    n = int((ta + tb * x1) - t_start)
    if not (120 < n < 100000):
        raise ValueError(f"step1: implausible duration {n}s")

    # Every strip — ticks and titles alike — is read from THIS chart's rows
    # and no others. On a tiled page the chart above prints its own numbers in
    # the very same columns, and they are what a whole-height strip returns.
    ry0, ry1 = max(0, y0 - 30), min(img.shape[0], y1 + 30)
    rows = img[ry0:ry1]

    def strip_ticks(xa, xb, with_x=False, clean=False):
        # Read each column with BOTH page-segmentation modes and pool what
        # they return. They fail differently on these narrow ladders, and
        # neither alone gets a right-hand axis whole: on 00199 p37 psm 6 reads
        # the rate ladder as 0, 4, 16, 42 — the "42" is a misread "12", the
        # same one this file's axis-title comment already records — and only
        # 300, 900, 1200 of the concentration ladder; psm 11 reads the
        # concentration ladder complete (0, 300, 600, 900, 1200) and reads the
        # 12 correctly, but drops most of the rate ladder.
        #
        # Neither column could be fitted, so fit_ticks_guarded returned None
        # for rate AND conc, and every curve hanging off those axes was
        # dropped: that page exported treating pressure alone, and the client
        # reported it as "missing full data set" (#89). On 00196 the same
        # failure left the rate curve calibrated against the concentration
        # axis, which is the 0..1200 m3/min rate in #88.
        #
        # Pooling is safe because it only adds evidence — RANSAC still has to
        # find a line, and a misread that no line explains is still rejected.
        # Merged, the rate ladder fits on 0, 4, 12, 16 with the 42 thrown out,
        # and the concentration ladder on all five labels.
        #
        # clean=True reads the strip once more, padded with white and turned
        # to black on white, for a column the plain reading could not fit (see
        # reread below). A label set hard against the crop's edge loses its
        # first stroke: 00198 p75 reads the "12" topping its rate axis as
        # "42" and never sees the 6 or the 9, so the axis fitted nothing and
        # Slurry Rate was dropped; padded, the 12 reads, and binarised the 9
        # does. 00243 p43's brown 0..12 ladder reads 12, 9, 6, 3, 0 only so.
        from PIL import Image as _Im
        import re as _re

        def read(a, b):
            strip = rows[:, max(0, a):b]
            if strip.size == 0:
                return []
            if clean:
                strip = np.pad(strip, ((0, 0), (10, 10), (0, 0)),
                               constant_values=255)
            pil = _Im.fromarray(strip.astype(np.uint8))
            pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
            arr = np.array(pil).astype(int)
            if clean:
                arr = np.repeat(np.where(arr.min(axis=2) < 160, 0, 255)[..., None],
                                3, axis=2)
            pad = 10 if clean else 0
            got = []
            for psm in (6, 11):
                try:
                    words = ar.ocr_words(arr, psm=psm, whitelist="0123456789.-")
                except Exception:
                    continue
                for text, cx, cy in words:
                    t = text.replace(",", "").strip("-.")
                    if _re.fullmatch(r"\d+(\.\d+)?", t):
                        got.append((float(t), int(cx / 3) - pad + max(0, a),
                                    int(cy / 3) + ry0))
            return [g for g in got if y0 - 25 <= g[2] <= y1 + 25]
        out = read(xa, xb)
        # A whole column between two titles can come back with nothing: on
        # 00243 p33 the rate axis's own rule runs the full height of the strip
        # and the OCR returned no words at all, so Slurry Rate was dropped
        # from every chart of the file (Carmine, #818, #820, #821). Read
        # narrower windows across it instead and pool them; RANSAC still has
        # to find a line through what they return.
        if len(out) < 3 and xb - xa > 80:
            for a in range(xa, xb - 40, 20):
                out += read(a, min(xb, a + 70))
        return out if with_x else [(v, y, True) for v, x, y in out]

    W = img.shape[1]
    # Which axis is which comes from the axes' own rotated titles, not from
    # their order: these charts print Concentration INSIDE Rate, and a title
    # sits between its own numbers and the next axis, so it both names the
    # column and delimits it. Each column is then OCR'd on its own: read as one
    # wide strip the rotated title text lands among the digits, and the "12"
    # topping the rate axis came back as "42", which no RANSAC fit could use.
    try:
        rtitles = ar.read_axis_titles(rows, x1 + 3, W, ccw=True)
    except Exception:
        rtitles = []
    if not rtitles:
        rtitles = _pale_titles(rows, x1 + 3, W, ccw=True)
    cols = []                       # [(quantity, ticks)], one entry per axis
    if rtitles:
        lo = x1 + 3
        def fits_any(pts):
            if ar.fit_ticks_guarded([(v, y, True) for v, x, y in pts]):
                return True
            return any(ar.fit_ticks_guarded(seg) for seg in _right_columns(pts)
                       if len(seg) >= 3)

        for qty, tx in rtitles:
            if tx - 4 > lo:
                pts = strip_ticks(lo, tx - 4, with_x=True)
                if not fits_any(pts):
                    # a column the plain reading cannot fit is read again,
                    # cleaned (see strip_ticks), and the two pooled: 00198,
                    # 00199 and 00201 lost Slurry Rate on eight charts so
                    # and 00243 p43 on one. Only then: a column that fits
                    # already keeps exactly the reading it had.
                    pts = pts + strip_ticks(lo, tx - 4, with_x=True, clean=True)
                # Two ladders under one title: the title of the inner axis did
                # not read, so its numbers and the outer axis's came back as
                # one column. 01289 p202 (2025) prints Rate 0..16 beside the
                # frame and Concentration 0..800 outside it, read only the
                # "Concentration" title, and fitted the 0..16 ladder as
                # concentration — 7.9 kg/m3 where the page draws 420 — with
                # no Slurry Rate at all (Carmine, #829). Cut on the x gap
                # between them and name each by its reach, as the untitled
                # reading below does.
                #
                # The title sits just outside its OWN numbers, so the outer
                # ladder is the one it names; only the inner one is named by
                # its reach — and never the title's quantity again. 00095's
                # chemical chart reads only "Clean Rate" (outer, 0..20), and
                # its inner 0..4 L/m3 additive ladder, named "rate" by reach,
                # won the rate slot: clean rate 1.9 where the page draws 10.
                parts = [seg for seg in _right_columns(pts) if len(seg) >= 3]
                if len(parts) >= 2:
                    for k, seg in enumerate(parts):
                        cal = ar.fit_ticks_guarded(seg)
                        if not cal:
                            continue
                        if k == len(parts) - 1 and qty in ("rate", "conc"):
                            cols.append((qty, seg))
                            continue
                        top = max(abs(cal[0] + cal[1] * y0), abs(cal[0] + cal[1] * y1))
                        q = "conc" if top >= RATE_AXIS_MAX else "rate"
                        if q == qty:
                            q = "conc" if qty == "rate" else "rate"
                        cols.append((q, seg))
                else:
                    cols.append((qty, [(v, y, True) for v, x, y in pts]))
            lo = tx + 4
        # An outermost axis whose own title did not read sits beyond the last
        # title that did, and was never looked at: 00242 p72 (a coil-tubing
        # stage at the smaller render) read "Concentration" and not "Rate
        # (m3/min)" beyond it, and lost Slurry Rate. Numbers there that fit a
        # line are an axis; named by reach, as the untitled reading does, and
        # only for a quantity no titled column has.
        beyond = rows[y0 - ry0:y1 - ry0, lo:W]
        if beyond.size and (beyond.sum(axis=2) < 450).sum() >= 30:
            have = {q for q, _s in cols}
            pts = strip_ticks(lo, W, with_x=True)
            if not fits_any(pts):
                pts = pts + strip_ticks(lo, W, with_x=True, clean=True)
            for seg in _right_columns(pts):
                cal = ar.fit_ticks_guarded(seg) if len(seg) >= 3 else None
                if not cal:
                    continue
                top = max(abs(cal[0] + cal[1] * y0), abs(cal[0] + cal[1] * y1))
                q = "conc" if top >= RATE_AXIS_MAX else "rate"
                if q not in have:
                    cols.append((q, seg))
                    have.add(q)
    else:
        # Titles unreadable: fall back to reading the whole strip and telling
        # the columns apart by how far each axis reaches. A rate axis tops out
        # in the tens of m3/min, a proppant concentration axis in the hundreds
        # or thousands of kg/m3. A column that admits no fit is dropped rather
        # than guessed at — half the axes is better than two wrong ones.
        pts = []
        from PIL import Image as _Im
        strip = rows[:, x1 + 3:W]
        if strip.size:
            pil = _Im.fromarray(strip.astype(np.uint8))
            pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
            import re as _re
            for text, cx, cy in ar.ocr_words(np.array(pil).astype(int), psm=6,
                                             whitelist="0123456789.-"):
                t = text.replace(",", "").strip("-.")
                if _re.fullmatch(r"\d+(\.\d+)?", t):
                    px, py = int(cx / 3) + x1 + 3, int(cy / 3) + ry0
                    if y0 - 25 <= py <= y1 + 25:
                        pts.append((float(t), px, py))
        for seg in _right_columns(pts):
            cal = ar.fit_ticks_guarded(seg)
            if not cal:
                continue
            top = max(abs(cal[0] + cal[1] * y0), abs(cal[0] + cal[1] * y1))
            cols.append(("conc" if top >= RATE_AXIS_MAX else "rate", seg))
    try:
        ltitles = ar.read_axis_titles(rows, 0, x0, ccw=False)
    except Exception:
        ltitles = []
    if not ltitles:
        ltitles = _pale_titles(rows, 0, x0, ccw=False, only="pressure")
    if require_titles and not ltitles:
        # The LEFT title specifically, because the quantity it names is what
        # decides whether the colour table applies at all (below). With no
        # left title the code falls back to assuming pressure, which is right
        # for a surface chart and catastrophic for its chemical twin: 16 pages
        # exported the Aqucar concentration curve as "Surface Pressure 0.97
        # MPa". Refusing here sends the chart to the colour-keyed reader,
        # which names it from the legend and the chart title instead.
        raise ValueError("step1: left axis title unreadable")
    # The left side stacks axes too — some pages print "TP Rate (L/min)"
    # outside "Pressure (MPa)" — and there too the title is on the far side of
    # its own numbers, so a title's column runs from it to the NEXT title.
    #
    # ONE readable title still delimits a column, and it has to: 01396/01392
    # stack Rate (0..20) OUTSIDE Pressure (MPa) (0..100) on the left, and the
    # outer axis' rotated title is illegible on this scan (tesseract returns
    # "KA"). Reading the whole left strip as one column then handed RANSAC two
    # sets of ticks at once and it fitted the 0..20 one — so every page of both
    # wells exported Surface Pressure off the RATE axis, a 13.7 MPa median for
    # a curve printed at 68. Delimiting on the single title that IS readable
    # keeps only the numbers between it and the plot, which are its own.
    # An empty segment is NOT dropped: which title is innermost is what names
    # the chart's principal axis, and dropping the innermost one because
    # tesseract read nothing between it and the frame promoted an OUTER axis
    # to principal — on 00271 that renamed a chemical chart's whole channel
    # set (Aqucar 742 Conc became Combined Clean Rate). An empty segment
    # simply fits nothing, and the whole-strip fallback below covers it.
    lsegs = []
    if ltitles:
        edges = [t[1] - 4 for t in ltitles[1:]] + [x0 - 4]
        lsegs = [(q, strip_ticks(tx + 4, edges[i]), tx)
                 for i, (q, tx) in enumerate(ltitles)]
    if not lsegs:
        lsegs = [("pressure", strip_ticks(0, x0), None)]

    fits = {}

    def _use(qty, seg, only_if_free=False):
        # fit each axis on its own ticks: an offset chart prints two right-hand
        # PRESSURE axes, and one fit over both columns' numbers is meaningless
        if only_if_free and qty in fits:
            return
        cal = ar.fit_ticks_guarded(seg) if seg else None
        # A title says which quantity a column is; the numbers say whether it
        # can be. 00196 p90 prints THREE right-hand axes and read_axis_titles
        # calls two of them "rate", so the concentration ladder — 0, 300, 600,
        # 900, 1200 — was offered for the rate slot. It fits ten ticks against
        # the real rate column's four, and the better fit wins, so the rate
        # curve came out against a 0..1200 axis peaking at 373.93 m3/min (#88).
        # No slurry rate on these charts reaches 50; the title-less fallback
        # above already splits rate from conc on exactly that threshold, so
        # apply it here too rather than trusting a title the numbers refute.
        # Asymmetric on purpose: a chemical chart's Chem Conc axis legitimately
        # tops out at 5 or 10, so a small conc axis is NOT suspicious.
        if cal and qty == "rate":
            reach = lambda c: max(abs(c[0] + c[1] * y0), abs(c[0] + c[1] * y1))
            if reach(cal) >= RATE_AXIS_MAX:
                # Unless the ladder lost its decimal points: 00182 p218's
                # 0 / 2.5 / 5 / 7.5 / 10 read as 0, 2.5 AND 25 at one height,
                # 5, 75 and 100 — a straight 0..100 ladder of its own, and the
                # slurry rate went unread. Offered at a tenth, those labels
                # make the rate axis the title says this is. Only here: where
                # no slip is in doubt, a pair 20 / 2 is as often a dropped 0
                # (00095's 0..20 clean rate, 00420's conc).
                alt = ar.fit_ticks_guarded(seg, tenths=True)
                if not alt or reach(alt) >= RATE_AXIS_MAX:
                    # A ladder that reaches the hundreds is a concentration
                    # axis whatever its title read: 00935 p47 (#810) read
                    # both right-hand titles as "rate", the 0..1200 ladder was
                    # refused, and stage 6 lost both concentrations. It fills
                    # the concentration slot only if nothing else does.
                    if reach(cal) >= RATE_AXIS_MAX and "conc" not in fits \
                            and not any(q == "conc" for q, _s in cols):
                        fits["conc"] = cal
                    return
                cal = alt
        if cal and (fits.get(qty) is None or cal[2] > fits[qty][2]):
            fits[qty] = cal

    for qty, seg in cols:
        _use(qty, seg)
    right_axes = bool(cols)
    # an offset chart's right-hand PRESSURE axes, inner first: the offset
    # wells', and on the 00243-00245 books the abandoned wells' beyond it
    # (see _offset_inplot_legend)
    rpress = [seg for qty, seg in cols if qty == "pressure"]
    for qty, seg, _tx in lsegs[:-1]:
        # an outer left axis is an auxiliary channel ("TP Rate" in L/min, not
        # the slurry rate in m3/min) — it only fills a quantity nothing else has
        _use(qty, seg, only_if_free=True)
    # The axis nearest the plot on the left is the chart's principal one and
    # wins its quantity outright. An offset chart carries THREE pressure axes
    # (0..80 main, 0..40 offset wells, 0..4 abandoned wells) and taking
    # whichever fitted best put Surface Pressure on the offset scale.
    lqty, lseg, ltx = lsegs[-1]
    lcal = ar.fit_ticks_guarded(lseg) if lseg else None
    if ltx is not None:
        # Delimiting exists to settle a strip that holds MORE THAN ONE axis.
        # Where the whole strip fits nothing at all there is nothing to settle,
        # and a column crop that suddenly does fit only changes which reader
        # owns the chart: on 00271 it handed three chemical charts from the
        # colour-keyed reader (which names all five curves from the legend) to
        # this one, which on a non-pressure chart deliberately emits only the
        # single channel its left axis names. Both readings were right; the
        # colour-keyed one carried more of the chart.
        whole = ar.fit_ticks_guarded(strip_ticks(0, x0))

        # ...unless the strip holds two axes and that is WHY the whole of it
        # reads wrong. The coil-tubing stages print "TP Rate (L/min)" 0..1000
        # outside "Pressure (MPa)" 0..80. Together the two ladders fit nothing
        # (00243 p77; 00241 p74 and p94), and Surface Main was lost with only
        # the right-hand curves kept; or they fit the TP Rate ladder and
        # neither crop of the pressure column fits at all (00241 p84), and
        # Surface Main went out on the 0..1000 axis at 642 MPa. A PRESSURE
        # axis between its own title and the frame is the chart's own, and
        # the titles have already said this is a surface chart, so no reader
        # changes hands (the 00271 concern above is a chemical chart). Read
        # the column plain and cleaned, and without what sits under the
        # frame: the first time label, centred on the frame's corner, puts its
        # "21" or "12" into this column 10 px below the axis's 0.
        def own_column():
            def own(seg):
                return [p for p in seg if p[1] <= y1 + 5]
            col = own(strip_ticks(ltx + 4, x0)) + own(lseg)
            if ar.fit_ticks_guarded(col) is None:
                col += own(strip_ticks(ltx + 4, x0, clean=True))
            return ar.fit_ticks_guarded(col)
        two_axes = lqty == "pressure" and len(lsegs) >= 2
        if whole is None:
            lcal = own_column() if two_axes else None
        else:
            # Where to stop the innermost column is decided by the OCR, not by
            # a constant. Stopping 4px short of the frame is right on the big
            # renders — carried closer, 00269's strip picks up a stray "415"
            # and the 0..75 axis fits as 5..75 — and wrong on the 880x680 one,
            # where those 4px take the last digit off "60" and "40" and 0..100
            # fits as 0..10. Both crops read the SAME axis, so read both.
            #
            # Tick count alone cannot choose between them: on 00269 p29 and on
            # 01396 p335 the two crops tie at five ticks and opposite ones are
            # right. The whole-strip fit settles it. That fit is the ambiguous
            # reading this code exists to replace, but it is still a reading of
            # this axis stack, and a crop that lost a digit lands an order of
            # magnitude away from it while the intact crop lands on top of it.
            # So: prefer a crop whose span agrees with the whole strip's, then
            # the one with more ticks, then the tighter (historical) crop.
            alt = ar.fit_ticks_guarded(strip_ticks(ltx + 4, x0))
            wspan = abs(whole[1] * (y1 - y0))

            def _rank(cal):
                span = abs(cal[1] * (y1 - y0))
                agrees = abs(span - wspan) <= 0.05 * max(span, wspan)
                return (0 if agrees else 1, -cal[2])

            cands = [c for c in (lcal, alt) if c]
            if cands:
                lcal = min(cands, key=_rank)
            else:
                lcal = (own_column() if two_axes else None) or whole
    if lcal:
        fits[lqty] = lcal

    raw_masks = ar.hue_masks(img)
    # the surface chart's: on the chemical chart orange is an additive, and
    # there is no coil pressure to blend into it (00119 p167)
    masks = (_drop_yellow_red_blend(dict(raw_masks), img, box=(x0, y0, x1, y1))
             if lqty == "pressure" else dict(raw_masks))
    yel_pen = (_yellow_pen(img, raw_masks, (x0, y0, x1, y1))
               if lqty == "pressure" else None)
    samples = np.arange(int(n / sample_sec)) * sample_sec
    channels = []
    seen = set()
    traced = {}
    # the plot's dark pixels, for telling a legend swatch from the curve
    pdark = np.asarray(img)[y0:y1, x0:x1].astype(int).sum(axis=2) < 330
    for fam, mask in masks.items():
        base = fam.rstrip("2")
        conv = NEW_SURFACE.get(base)
        if conv is None or conv[0] in seen:
            continue
        name, unit, axis = conv
        # NEW_SURFACE names the colours of the SURFACE chart, which is the one
        # whose left axis is Pressure. A chemical chart puts Clean Rate there
        # and its colours mean something else entirely, so only the channel the
        # left axis itself names is trustworthy — the rest would be exported as
        # "Prop Conc (kg/m3)" off an L/m3 chemical axis.
        if lqty != "pressure" and axis != lqty:
            continue
        cal = fits.get(axis)
        if cal is None:
            continue
        sub = _drop_legend_swatches(mask[y0:y1, x0:x1], pdark)
        cov = float(sub.any(axis=0).mean())
        if cov < 0.1:
            continue
        # glyphs=True: these reports print the FracPro logo inside the frame,
        # in the series' own inks. See auto_raster.drop_glyph_islands.
        # bracketed=True: a dip the pen falls into and climbs out of is the
        # curve, however far off the trend it runs (#829, 01289 p202)
        py = ar.curve_positions(sub, glyphs=True, edge_blank=True,
                                bracketed=True)
        other = np.zeros_like(sub)
        for f2, m2 in raw_masks.items():
            if f2 != fam:
                other |= m2[y0:y1, x0:x1]
        py = _drop_fringe_blips(py, sub, other)
        if base == "orange" and yel_pen is not None:
            # the orange pen's own ink: clearly orange, or a tan pen's
            # (00227: (224,197,151)) — not the yellow's soft edge (250,203,99)
            cr = np.asarray(img)[y0:y1, x0:x1].astype(int)
            pen = sub & (((cr[..., 0] - cr[..., 1]) >= 55) | (cr[..., 2] >= 140))
            py = _drop_on_yellow(py, yel_pen, pen)
        py = _drop_floating_orphans(py, sub)
        seen.add(name)
        traced[base] = {"fam": fam, "name": name, "unit": unit, "cal": cal,
                        "sub": sub, "cov": cov, "py": py, "filled": 0}
    # Btm Prop Conc is painted UNDER Prop Conc. Where the two coincide the
    # page shows green and no orange at all, and the orange trace came back
    # blank there — 37.9% of a stage on 00349 (#112), 80% of one on 01316
    # (#627). Deduce it: see _fill_under.
    # …and only on the SURFACE chart, where orange and green are the same
    # concentration at the two ends of the pipe. On the chemical chart they
    # are two different additives, and 00324's Chem Conc (orange) was being
    # "deduced" from Chem Conc (green) on ten of thirty stages.
    if lqty == "pressure" and "orange" in traced and "green" in traced:
        o, g = traced["orange"], traced["green"]
        # every non-white pixel of the plot, for the floor walk: the pad
        # and the flush sit under whatever is at the floor, blends and the
        # other pens included (01316 p195, #627)
        # ...and every pixel a hue mask owns: the sphere reaches tints too
        # pale for the darkness test (the anti-aliased descent on p195)
        ink = _ink(img, y0, y1, x0, x1)
        for mk in masks.values():
            ink |= mk[y0:y1, x0:x1]
        cols = _fill_under(o["sub"], o["py"], g["sub"], g["py"], ink=ink)
        o["filled"] = len(cols)
        # ...and the other way round. The page does not always paint green
        # last: on 00244 p30 at 17:21 Btm Prop Conc steps up onto Prop Conc's
        # 79 kg/m3 hold and is drawn OVER it for six minutes, until the green
        # steps on to 145 — and the green, blank under it, was bridged as one
        # slant from 79 to 145 where the page draws a hold and a step (Carmine,
        # #822: "slight misses on the conc"). The same deduction, cover and
        # hidden swapped; the columns orange was just filled in are columns
        # green is visible in, so neither fill feeds the other.
        gcols = _fill_under(g["sub"], g["py"], o["sub"], o["py"], ink=ink)
        g["filled"] = len(gcols)
    seen = set()
    ends_ink = None
    for base, tr in traced.items():
        fam, name, unit, sub, cov, py = (tr["fam"], tr["name"], tr["unit"],
                                         tr["sub"], tr["cov"], tr["py"])
        a, b, ntick = tr["cal"]
        # the surface chart's pressure: where its climbs are read (#799)
        cx, py = _keep_excursions(sub, py, pressure=(
            lqty == "pressure" and NEW_SURFACE.get(base, (None, None, None))[2] == "pressure"))
        py = py + y0
        # same round-bound snap as the tiled path (see auto_raster.snap_axis):
        # applied before values are read so it reaches the exported numbers
        _vt, _vb, _sn = ar.snap_axis(a + b * y0, a + b * y1)
        if _sn and abs(y1 - y0) > 1:
            b = (_vb - _vt) / float(y1 - y0)
            a = _vt - b * y0
        vals = a + b * py
        t_cols = (ta + tb * (cx + x0)) - t_start
        if np.isfinite(vals).sum() < 50:
            continue
        # No ink means no reading: np.interp with no left/right clamps to the
        # edge value, so every gap and both tails carried a flat invented line.
        # ct.resample blanks them instead (see curve_trace.resample).
        v = ct.resample(samples, t_cols, vals)
        if ends_ink is None:
            ends_ink = _ink(img, y0, y1, x0, x1)
            for mk in masks.values():
                ends_ink |= mk[y0:y1, x0:x1]
        channels.append({"key": f"series-{fam}", "label": name, "unit": unit,
                         "color": ar.HUE_HEX.get(base, "#555577"),
                         "values": v, "ticks": ntick, "coverage": cov,
                         # axis read at the frame edges — see auto_raster
                         "axis_frame": (float(a + b * y0), float(a + b * y1)),
                         "filled_cols": tr["filled"],
                         "ends": _held_ends(ends_ink, v, a, b, y0, tb, sample_sec)})
        seen.add(name)
    if (lqty == "pressure" and yel_pen is not None and fits.get("pressure")
            and channels and _legend_names_coil(img, box)):
        # the coil's own pressure, on the chart's pressure axis: see
        # _legend_names_coil
        if ends_ink is None:
            ends_ink = _ink(img, y0, y1, x0, x1)
        # glyphs=False: the coil's thick, ragged plateaus look like the
        # logo's glyphs to that filter, and 00242 p72 lost its 58 MPa
        # stretches (22:52-23:12) to it. No logo is drawn in yellow.
        coil = _pen_channel(_drop_legend_swatches(yel_pen, pdark),
                            fits["pressure"], box, ta, tb, t_start, samples,
                            ends_ink, sample_sec, "Coil Pressure",
                            "series-yellow", (0, 0, 0), glyphs=False)
        if coil is not None:
            coil["color"] = ar.HUE_HEX["yellow"]
            channels.append(coil)
    if lqty == "pressure" and rpress and channels:
        if ends_ink is None:
            ends_ink = _ink(img, y0, y1, x0, x1)
        channels += _offset_channels(img, box, rpress, fits.get("pressure"),
                                     samples, ta, tb, t_start, ends_ink,
                                     sample_sec)
    elif lqty == "pressure" and not right_axes and channels and fits.get("pressure"):
        # no right-hand axis at all: 00196's offset chart, every well on the
        # one pressure axis and named in a legend under the plot
        if ends_ink is None:
            ends_ink = _ink(img, y0, y1, x0, x1)
        channels += _casing_channels(img, box, fits["pressure"], raw_masks,
                                     samples, ta, tb, t_start, ends_ink,
                                     sample_sec)
    if not channels:
        raise ValueError("step1: no channel calibrated")
    info = {"plot": box, "t0_seconds": float(t_start),
            "duration_s": int(n), "notes": []}
    if clock_axis:
        # the axis IS a wall clock: sample 0 sits at its first second, and
        # _place_on_clock adds the date from the footer where it agrees
        s0 = int(t_start) % 86400
        info["clock_start"] = "%02d:%02d:%02d" % (s0 // 3600, s0 // 60 % 60, s0 % 60)
    for c in channels:
        if c.get("filled_cols"):
            secs = c["filled_cols"] * tb
            top, over, under = (("Btm Prop Conc", "orange", "green")
                                if c["key"] == "series-green"
                                else ("Prop Conc", "green", "orange"))
            info["notes"].append(
                f"{c['label']}: {secs / 60:.1f} min read from under {top}, "
                f"where the page paints the {over} curve over the {under} one "
                f"and the two coincide — deduced, not traced")
    return samples, channels, info


HELD_WINDOW_S = 300.0   # among the readings nearest a curve's end...
HELD_SETTLED_S = 120.0  # ...for this much of it at the end's height
HELD_NEAR = 0.02        # within this share of the axis


def _held_ends(ink, v, a, b, y0, tb, sample_sec, slack=3):
    """Past a curve's last reading, and before its first: how far does the
    page keep ink at that reading's height? -> {"lead": first sample index
    still held, "trail": last sample index still held}, None where the row is
    blank straight away.

    A curve goes blank for one of two reasons, and the page tells them apart.
    Painted over by another pen at the same height, it is still there: on
    00108 p282 the orange Chem Conc runs at 0.1 under the pale yellow Bio
    Conc from 01:05 to 02:40, and the row stays inked the whole way. Gone
    down to the floor, it is under the frame's bottom rule and its row is
    blank: 50029 p154's rate falls from 7.5 to 0 at 01:29 and nothing is
    left at 7.5. `ink` is every coloured pixel of the plot, every pen mask
    included; grey gridlines and the frame are not in it. Up to `slack` blank
    columns are crossed, for the gaps between a dashed or anti-aliased
    pen's pixels.

    Only for a curve that was AT that height, though: HELD_SETTLED_S of
    readings within HELD_NEAR of it among its HELD_WINDOW_S of readings
    nearest the end. An
    end that is one short piece may not be this curve at all, and the row
    that holds it is then the very pen it was misread from: 00108 p291's
    green Prop Conc "starts" with a minute at 162 kg/m3 that is a piece of
    the yellow annulus line, and holding it back along that line put 162
    where the page has 25.
    """
    H, W = ink.shape
    fin = np.flatnonzero(np.isfinite(v))
    out = {"lead": None, "trail": None}
    if not len(fin) or not b or not tb:
        return out
    R = max(2, int(0.005 * H) + 1)
    near = HELD_NEAR * abs(b) * H
    win = int(round(HELD_WINDOW_S / sample_sec))
    for side, i, step in (("trail", fin[-1], 1), ("lead", fin[0], -1)):
        # the curve's own last (first) readings, however far apart: a curve
        # hidden for minutes at its level is still settled there (53560 p377,
        # 0.091 before and after five hidden minutes)
        w = v[fin[-win:]] if side == "trail" else v[fin[:win]]
        if np.sum(np.abs(w - v[i]) <= near) * sample_sec < HELD_SETTLED_S:
            continue
        row = (v[i] - a) / b - y0
        if not np.isfinite(row) or not (0 <= row < H):
            continue
        band = ink[max(0, int(round(row)) - R):int(round(row)) + R + 1].any(axis=0)
        c = int(np.floor(i * sample_sec / tb)) + step   # the reading's column, then on
        last, miss = None, 0
        while 0 <= c < W:
            if band[c]:
                last, miss = c, 0
            else:
                miss += 1
                if miss > slack:
                    break
            c += step
        if last is None:
            continue
        k = int(last * tb / sample_sec)
        k = min(len(v) - 1, max(0, k))
        if (side == "trail" and k > i) or (side == "lead" and k < i):
            out[side] = k
    return out


def _drop_legend_swatches(sub, dark):
    """Clear a legend's colour swatches from a plot-cropped colour mask.

    The Shell 2017 books draw their key INSIDE the frame, top left: a small
    solid square of each series' colour with its name printed beside it. Read
    as the curve, 00244 p96's green "Prop Conc" swatch put Prop Conc at 955
    kg/m3 for a minute at 10:50, and the bridging either side drew a spike to
    the top of the chart (Carmine, #814). A swatch is told from the curve by
    what is next to it: a few pixels square, nearly solid, with the dark text
    of its label starting just to its right across a dozen columns or more. A
    stretch of curve beside a gridline has one dark column there, not text.

    `dark` is the plot crop's dark-pixel mask. -> the mask, swatches cleared
    (the input itself when there are none)."""
    found = ar._components(sub)
    if not found:
        return sub
    comps, _runs = found
    out = None
    W = sub.shape[1]
    for cp in comps:
        w = cp["c1"] - cp["c0"] + 1
        h = cp["y1"] - cp["y0"] + 1
        if not (4 <= w <= 14 and 4 <= h <= 14 and 0.6 <= w / h <= 1.7):
            continue
        if cp["n"] / float(w * h) < 0.7:
            continue
        ca = cp["c1"] + 2
        right = dark[cp["y0"]:cp["y1"] + 1, ca:min(W, ca + 40)]
        cols = np.flatnonzero(right.any(axis=0))
        if len(cols) < 12 or cols[0] > 12:
            continue
        if out is None:
            out = np.array(sub, bool)
        out[cp["y0"]:cp["y1"] + 1, cp["c0"]:cp["c1"] + 1] = False
    return sub if out is None else out


def _drop_fringe_blips(py, sub, other, alone=10, touch=3):
    """Readings that are another pen's anti-aliased edge, not the curve.

    00244 p96: the green Prop Conc drops to the floor at 11:44 and is hidden
    there from then on, but one green pixel at row 528 — the washed edge of
    the orange line at 529-531 — was read as the curve at 11:53. As the
    curve's last reading it said the curve ended in mid-air at 318 kg/m3, and
    the pipeline held it there under the orange pen until 12:05 (Carmine,
    #814). A run of up to four columns each inked one or two pixels deep (that
    one was four columns at row 528), alone — no other reading of this colour
    within `alone` columns either side — and touching another pen's ink
    within `touch` rows, is that pen's fringe and is dropped.

    `py` per-column rows (NaN where none), `sub` this colour's plot mask,
    `other` every other pen's ink. -> py, NaN at the blips."""
    py = np.array(py, float)
    fin = np.isfinite(py)
    n = len(py)
    # the short runs that could be a fringe: up to four columns, every inked
    # column one or two pixels deep and touching another pen
    runs, cand = [], []
    i = 0
    while i < n:
        if not fin[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and fin[j + 1]:
            j += 1
        ok = j - i < 4
        inked = 0
        for c in range(i, j + 1) if ok else ():
            ys = np.flatnonzero(sub[:, c])
            if not len(ys):
                continue
            inked += 1
            a, b = max(0, ys[0] - touch), ys[-1] + touch + 1
            # a speck of one or two columns needs no neighbour to be one: a
            # curve cannot show for a column and vanish for ten either side
            # on an open plot (00244 p96's green after its drop, at 649, 658)
            if len(ys) > 2 or (j - i >= 2 and not other[a:b, c].any()):
                ok = False
                break
        runs.append((i, j))
        cand.append(ok and inked > 0)
        i = j + 1
    # ...and alone: no reading of the curve proper within `alone` columns, so
    # a scatter of fringe points does not vouch for itself
    real = np.zeros(n, bool)
    for (i, j), c in zip(runs, cand):
        if not c:
            real[i:j + 1] = True
    out = py.copy()
    for (i, j), c in zip(runs, cand):
        if c and not real[max(0, i - alone):min(n, j + 1 + alone)].any():
            out[i:j + 1] = np.nan
    # A curve that IS short runs — a chemical additive read in specks, 5% of
    # its chart (00119 p183) — would be dropped whole. Blips are a few columns
    # of a curve read elsewhere; past a third of its readings they are it.
    if np.isfinite(out).sum() < 0.7 * fin.sum():
        return py
    return out


def _drop_yellow_red_blend(masks, img, reach=2, box=None):
    """Orange that belongs to a yellow line, not to the orange pen.

    The Shell 2017 books draw Coil Pressure in yellow, and no hue family takes
    yellow — but its soft edge against white, (250,203,99), and its blend
    where it runs over the red Surface Main both fall in the orange family.
    After a shutdown the two pressures fall together and settle side by side,
    and that orange was read as Btm Prop Conc: 00244 p96's orange drops to the
    floor at 11:48, and the export climbed back up the yellow's descent to
    470 kg/m3 and ran along the pair at ~300 until 12:11 (Carmine, #814).
    An orange pixel with the yellow pen just above it and the red pen just
    below (or the other way round) is that blend; the orange pen itself is
    never caught between the two. -> masks, those pixels cleared from
    "orange" (in place)."""
    if "orange" not in masks:
        return masks
    a = np.asarray(img).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # Blue well below red and green. Looser, it took 00100's pale TAN Btm Prop
    # Conc pen, (233,202,171), for yellow — and the hue families take the same
    # tan for orange AND red, so the pen flanked itself and was cut away.
    yel = (r > 170) & (g > 160) & (b < 140) & (np.abs(r - g) < 45) & ((np.maximum(r, g) - b) > 80)
    org = masks["orange"]
    if not (org & ~yel).any() or not yel.any():
        return masks
    # Only on a page that draws a yellow PEN. Elsewhere "yellow" is the blend
    # of a green line beside an orange one — 00862 p164's two concentrations
    # run side by side for half an hour — and judged as a pen it nibbled the
    # orange curve into a saw. A pen is yellow clear of green and orange
    # across a fifth of the plot's width at least.
    near_go = org | masks.get("green", np.zeros_like(org))
    k = 2
    pad = np.pad(near_go, k)
    grown = np.zeros_like(near_go)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            grown |= pad[k + dy:k + dy + near_go.shape[0], k + dx:k + dx + near_go.shape[1]]
    pure = yel & ~grown
    if box is not None:
        bx0, by0, bx1, by1 = box
        pure = pure[by0:by1, bx0:bx1]
    if pure.size == 0 or float((pure.sum(axis=0) >= 2).mean()) < 0.2:
        return masks
    # Even on such a page, "yellow" beside green is that blend again: 00100
    # p173 draws a yellow Well 3 pen, and the orange Btm Prop Conc steps
    # running just under the green Prop Conc ones blend to a pale olive that
    # passes for yellow, with the orange's own dark edge passing for red under
    # it. Judged as yellow-over-red, 1,400 samples of a real Btm Prop Conc
    # were cut and bridged. The yellow that matters is clear of green.
    grn = masks.get("green", np.zeros_like(org))
    pad = np.pad(grn, k)
    near_g = np.zeros_like(grn)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            near_g |= pad[k + dy:k + dy + grn.shape[0], k + dx:k + dx + grn.shape[1]]
    yel = yel & ~near_g

    # Only orange BETWEEN the two pens goes here. A rule that also dropped
    # orange outweighed by yellow around it cut real Btm Prop Conc wherever it
    # ran beside a yellow pen — 00227 p72 lost 13% of its curve, 00420 p135 a
    # third. What is left of the ghost is ON the yellow line, and is read off
    # the trace instead (_drop_on_yellow).
    drop = np.zeros_like(org)
    # ...and orange with yellow on one side of it and red on the other, the
    # two pressures settled side by side after the shutdown: a band of blend
    # three rows deep under a yellow line two rows thin outweighs it, so it
    # is judged by what flanks it instead
    #
    # Flanked by the PENS, not by anything the hue families let in: 00100's
    # tan Btm Prop Conc pen has a darker core, (208,169,124), that passes the
    # yellow test and the red family both, and every column of it was a tan
    # pixel "between yellow and red". The yellow and red lines of a ghost are
    # the pens themselves, strongly coloured: the yellow well clear of blue,
    # the red well clear of green and blue (00244's settles as a red-brown,
    # (166,101,79); the tan core is (208,169,124)).
    if "red" in masks:
        yel = yel & (r > 200) & (g > 200) & (b < 120)
        red = masks["red"] & ((r - np.maximum(g, b)) > 50)
        H = yel.shape[0]
        k = reach + 2

        def near(m, up):
            out = np.zeros_like(m)
            for i in range(1, k + 1):
                if up:
                    out[i:] |= m[:H - i]
                else:
                    out[:H - i] |= m[i:]
            return out
        drop |= org & ((near(yel, True) & near(red, False)) | (near(red, True) & near(yel, False)))
    if drop.any():
        masks["orange"] = org & ~drop
    return masks


def _yellow_pen(img, masks, box):
    """The page's yellow PEN, strongly coloured and clear of green and orange,
    as a plot-cropped mask — or None where the page draws no yellow pen (less
    than a fifth of the plot's width carries it). See _drop_yellow_red_blend."""
    a = np.asarray(img).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    yel = (r > 200) & (g > 200) & (b < 120) & (np.abs(r - g) < 45)
    near = np.zeros_like(yel)
    for fam in ("orange", "green"):
        if fam in masks:
            near |= masks[fam]
    k = 2
    pad = np.pad(near, k)
    grown = np.zeros_like(near)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            grown |= pad[k + dy:k + dy + near.shape[0], k + dx:k + dx + near.shape[1]]
    x0, y0, x1, y1 = box
    pure = (yel & ~grown)[y0:y1, x0:x1]
    if pure.size == 0 or float((pure.sum(axis=0) >= 2).mean()) < 0.2:
        return None
    return yel[y0:y1, x0:x1]


def _drop_on_yellow(py, yel, pen, near=2):
    """Btm Prop Conc readings that are the yellow pen's line, not the orange.

    The yellow coil pressure reads as orange along its soft edge, and in a
    column where the orange curve is not that is the only "orange" there:
    after 00244 p96's job the export climbed the yellow's descent to 470
    kg/m3 (Carmine, #816), and 00227 p76 carried a Btm Prop Conc of 500 for
    fifteen minutes before the job had pumped any sand — the yellow line at
    50 MPa, read off the orange mask. A reading within `near` rows of yellow
    ink in its own column is dropped, unless the orange pen's own colour
    (`pen`) is there too: 00420 p135's real Btm Prop Conc rides its yellow
    Well 3 pressure for five minutes at 550 kg/m3, drawn over it. A real
    curve crossing the yellow line loses a few columns that the gap bridging
    fills from either side."""
    py = np.array(py, float)
    for c in np.flatnonzero(np.isfinite(py)):
        r0 = int(round(py[c]))
        a, b = max(0, r0 - near), r0 + near + 1
        if yel[a:b, c].any() and not pen[a:b, c].any():
            py[c] = np.nan
    return py


def _drop_floating_orphans(py, sub, max_len=8, gap=6, look=30):
    """A short cluster of readings floating between readings on the floor.

    A curve that has gone to the floor comes back up by drawing its rise:
    ink from the floor up. 00244 p96's orange drops to the floor at 11:48,
    and ten columns on, five columns of the yellow and red pressures' overlap
    hang 230-280 rows above it with nothing joining them to the floor and the
    floor again after them; bridged, they were a 384 kg/m3 Btm Prop Conc spike
    after the job had stopped (Carmine, #814). A cluster of up to `max_len`
    columns, `gap` empty columns after a reading on the floor, none of whose
    ink reaches the floor, and followed by the floor again (or by nothing)
    within `look` columns, is dropped. -> py, NaN there."""
    py = np.array(py, float)
    H = sub.shape[0]
    floor = H - 1 - max(6, H // 100)
    fin = np.isfinite(py)
    n = len(py)
    runs = []
    i = 0
    while i < n:
        if not fin[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and fin[j + 1]:
            j += 1
        runs.append((i, j))
        i = j + 1
    on_floor = lambda c: py[c] >= floor

    def floating(i, j):
        # short, clear of the floor by a fifth of the plot, no ink reaching it
        return (j - i < max_len and float(np.nanmin(py[i:j + 1])) < floor - 0.2 * H
                and not any(sub[floor:, c].any() for c in range(i, j + 1)))
    k = 0
    while k < len(runs):
        i, j = runs[k]
        if (k and on_floor(runs[k - 1][1]) and i - runs[k - 1][1] > gap and floating(i, j)):
            # the chain of floating clusters from here, each within `look`
            # columns of the last: it must end on the floor or at the chart's end
            m = k
            while (m + 1 < len(runs) and runs[m + 1][0] - runs[m][1] <= look
                   and floating(*runs[m + 1])):
                m += 1
            nxt = runs[m + 1] if m + 1 < len(runs) else None
            if nxt is None or nxt[0] - runs[m][1] > look or on_floor(nxt[0]):
                for a, b in runs[k:m + 1]:
                    py[a:b + 1] = np.nan
                k = m + 1
                continue
        k += 1
    return py


def _ink(img, y0, y1, x0, x1):
    """Every non-paper pixel of the plot, any colour -> bool (rows, cols).

    Summed in int: the composite is uint8, and a uint8 sum of three
    channels wraps at 256 — white (765) came out 253 and read as ink,
    which made the first measurement of the pad walk right by accident.
    """
    crop = np.asarray(img)[y0:y1, x0:x1].astype(int)
    dark = crop.sum(axis=2) < INK_SUM
    # ...and COLOURED: the frame's ticks, gridlines and the grey wash at the
    # right edge of 01316 p150's plot are dark too, and a floor walk that
    # took them for a stroke ran orange 230 s past where the well's own
    # curves end. Two pens blended read as khaki (chroma ~80), a pale
    # descent ~45-60, the greys 3-5.
    chroma = crop.max(axis=2) - crop.min(axis=2)
    return dark & (chroma > INK_CHROMA)


def _fill_under(sub_o, py_o, sub_g, py_g, tol_px=None, gap=2, ink=None):
    """Btm Prop Conc under Prop Conc — see curve_trace.fill_under."""
    return ct.fill_under(sub_o, py_o, sub_g, py_g, tol_px=tol_px, gap=gap,
                         ink=ink)


def _chosen_run(sub, py, gap=2):
    """Top and bottom row of the run curve_positions settled on, per column.

    curve_positions reports that run's MEDIAN row and nothing else, so the
    caller cannot tell a 3px stroke from a 300px near-vertical one. Rebuilt
    here with the same run split (contiguous ink, `gap`-pixel tolerance) and
    matched back by the median it returned, so a column whose ink was
    rejected as a contaminant stays rejected."""
    n = sub.shape[1]
    top = np.full(n, np.nan)
    bot = np.full(n, np.nan)
    for c in range(n):
        if not np.isfinite(py[c]):
            continue
        ys = np.flatnonzero(sub[:, c])
        if not len(ys):
            continue
        for r in np.split(ys, np.flatnonzero(np.diff(ys) > gap) + 1):
            if abs(float(np.median(r)) - py[c]) < 1e-9:
                top[c], bot[c] = float(r[0]), float(r[-1])
                break
    return top, bot


def _despeckle(py, join=2, island=3, need=40):
    """Blank islands of one to three columns standing on their own.

    hue_masks classifies the anti-aliased fringe where two curves cross, so a
    chart routinely carries a two-pixel fleck of one series' colour sitting in
    another series' territory. curve_positions keeps it — it is the only run
    in that column, and the rolling median it is checked against is built from
    the fleck itself when its neighbours are blank — and ct.resample then
    reports it as a reading. On 00322 that fleck IS the exported peak: Btm
    Prop Conc came out at 652 kg/m3 on stage 1 from two pixels at column 244,
    27 columns clear of where the curve actually starts, while the curve
    itself never passes 155. A plotted curve is hundreds of columns wide; an
    island three columns wide is not a reading of one.
    """
    out = np.array(py, dtype=float, copy=True)
    fin = np.flatnonzero(np.isfinite(out))
    if len(fin) < need:
        return out
    for grp in np.split(fin, np.flatnonzero(np.diff(fin) > join) + 1):
        if len(grp) <= island:
            out[grp] = np.nan
    return out


FLIP_REACH = 6      # columns either side whose readings bound a repair


def _off_the_dots(sub, py, med, tall):
    """A reading on a fleck of one or two pixels, in a column whose pen line
    runs well away from it, moves onto that line. -> py.

    Where a horizontal gridline crosses a vertical one the mask can keep a
    fleck of the crossing, and curve_positions can take it over the pen:
    Carmine's Chart 2 (00051 p150) reads rows 347-348 in cols 9-10 — the
    gridlines at row 344 — while the climbing stroke there runs 381-440, a
    spike of 6 MPa. Used on a trace's opening columns at the frame's edge
    only: elsewhere a "fleck" is as often a stroke's own tip, split off by a
    pale pixel (00048 p130's col 10). A fleck stands alone: two columns at most read its
    level, the width of a vertical gridline. A curve lying flat on the
    frame's floor is two pixels deep too, but every column along it reads
    that level, and it stays. And only where it lies clear beyond the ink of
    the columns either side: a stroke's own tip can be split off it by a pale
    pixel, and is level with its neighbours' edge (00048 p142's col 13). A
    pen hidden under another series can show as a dot of its own (00163
    p207's peak), and its column then has no line.
    """
    out = np.array(py, float)
    n = len(out)
    for c in range(n):
        if not np.isfinite(py[c]):
            continue
        ys = np.flatnonzero(sub[:, c])
        if not len(ys):
            continue
        runs = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)
        mine = next((g for g in runs if g[0] - 1 <= py[c] <= g[-1] + 1), None)
        if mine is None or len(mine) > 2:
            continue
        lines = [g for g in runs if len(g) >= max(4.0, med)]
        if not lines:
            continue
        gap = lambda g, r: 0.0 if g[0] <= r <= g[-1] else min(abs(g[0] - r), abs(g[-1] - r))
        line = min(lines, key=lambda g: gap(g, py[c]))
        if gap(line, py[c]) <= tall:
            continue
        a = b = c                              # the columns reading its level
        while a - 1 >= 0 and np.isfinite(py[a - 1]) and abs(py[a - 1] - py[c]) <= tall:
            a -= 1
        while b + 1 < n and np.isfinite(py[b + 1]) and abs(py[b + 1] - py[c]) <= tall:
            b += 1
        if b - a + 1 > 2:
            continue
        # and it lies clear beyond the ink of the columns either side, not
        # level with their edge: 00048 p142's col 13 reads a one-pixel tip
        # at 515, split off its stroke, where col 14's ink tops out at 513
        sides = []
        for j in (a - 1, b + 1):
            if 0 <= j < n:
                yj = np.flatnonzero(sub[:, j])
                if len(yj):
                    sides.append((yj[0], yj[-1]))
        if len(sides) < 2:
            continue
        if py[c] < line[0]:
            if not py[c] < min(t for t, _ in sides) - tall:
                continue
        elif not py[c] > max(u for _, u in sides) + tall:
            continue
        # the line's end on the fleck's side, a half-pen in — but between
        # the readings either side, not past them: on a slanted stroke that
        # end runs ahead of the curve (00049 p144's cols 10-11 would have
        # read 40 MPa between 33 and 36)
        lo, hi = float(line[0]), float(line[-1])
        v = min(lo + med / 2.0, (lo + hi) / 2.0) if py[c] < lo else max(hi - med / 2.0, (lo + hi) / 2.0)
        nb = [py[j] for j in (a - 1, b + 1) if 0 <= j < n and np.isfinite(py[j])]
        if len(nb) == 2:
            v = min(max(v, min(nb)), max(nb))
        out[c] = v
    return out


def _no_flip_back(sub, py, med, tall, pressure=True):
    """Inside a steep move, a column that reads back at the level the move
    started from — though its own ink reaches far past it — takes the
    move's leading edge instead. -> py, changed only there.

    The 2026 STEP books draw the pressure's opening rise (~1 to ~30 MPa) with
    a thick line that fills four pixel columns, each inked from the baseline
    up. curve_positions takes one END of each column's run (the end further
    from a lagging reference), and it took the top of the first column and
    the baseline of the next three: 00051 p156 read 18, 0.7, 0.7, 0.8, then
    the hold — a false spike before every rise on every well of the set
    (Carmine, #799). A column that falls back to where the move began, while
    its ink reaches past where the move has already been, is the same stroke
    read from the wrong end; it is read from the leading end. Nothing else
    moves: the first column, peaks, holds, needles and every ordinary column
    keep the reading they had.
    
    `pressure`: the surface chart's pressure trace. The repairs added for
    Carmine's charts in 1.11.43 — a climb read at its front throughout,
    flecks as no start, a speck just after a climb — apply to its climbs
    alone, and the opening's floor reads to its opening; every other
    channel, and every fall, reads as it did in 1.11.42. The broader rule
    changed nearly every channel and took 00051 p174's opening pressure
    test, a fall from the top of the frame.
    """
    n = len(py)
    py = np.array(py, float)
    # A trace that opens mid-move at the frame's own left edge — its first
    # reading in the first columns, nothing inked before, and that column's
    # ink already a stroke tall: the flecks off the pen in its opening go
    # first (Carmine's Chart 2, 00051 p150, cols 9-10; 00052 p150's col 7, a
    # fleck that also cut the opening move short). A trace that opens on a
    # flat line is left alone (00048 p130's baseline).
    fin = np.flatnonzero(np.isfinite(py))
    if len(fin) and fin[0] <= 3 and not sub[:, :fin[0]].any():
        ys0 = np.flatnonzero(sub[:, fin[0]])
        if len(ys0) and ys0[-1] - ys0[0] + 1 >= tall:
            head = min(n, fin[0] + 30)
            py[:head] = _off_the_dots(sub[:, :head], py[:head], med, tall)
    out = np.array(py, float)
    orig = np.array(py, float)

    def capped(k, v):
        # never past the furthest the curve itself reads within FLIP_REACH
        # columns: a column's ink can run on into something that is not the
        # curve, and its edge then invents a spike (00006 p144's Prop Conc
        # steps to ~470; its riser's ink ran to 691)
        w = orig[max(0, k - FLIP_REACH):k + FLIP_REACH + 1]
        w = w[np.isfinite(w)]
        if not len(w):
            return v
        return min(max(v, float(w.min())), float(w.max()))
    def pen_row(j):
        # the middle of a column's longest run: the pen line itself, not a
        # gridline dot or the other curve's fringe that the median of all
        # its ink would average in (00005 p181's conc mask put "where the
        # move began" at 715 kg/m3 that way, and a repair followed it there)
        ys = np.flatnonzero(sub[:, j])
        if not len(ys):
            return None
        runs_j = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)
        g = max(runs_j, key=len)
        return float(np.median(g))
    def run_len(j):
        # pixels in the run a column's reading sits on
        ys = np.flatnonzero(sub[:, j])
        runs_j = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1) if len(ys) else []
        g = next((g for g in runs_j if g[0] - 1 <= orig[j] <= g[-1] + 1), None)
        return 0 if g is None else len(g)
    # each reading's run, from either end (the envelope moves readings off
    # the middle), joining the breaks of a thin, anti-aliased stroke
    rtop, rbot = np.full(n, np.nan), np.full(n, np.nan)
    for c in range(n):
        if not np.isfinite(py[c]):
            continue
        ys = np.flatnonzero(sub[:, c])
        if not len(ys):
            continue
        if len(ys) >= 0.6 * (ys[-1] - ys[0] + 1):
            rtop[c], rbot[c] = float(ys[0]), float(ys[-1])
            continue
        cuts = np.flatnonzero(np.diff(ys) > 6) + 1
        for g in np.split(ys, cuts):
            if g[0] - 1 <= py[c] <= g[-1] + 1:
                rtop[c], rbot[c] = float(g[0]), float(g[-1])
                break
    tall_c = np.isfinite(py) & np.isfinite(rtop) & ((rbot - rtop + 1) >= tall)
    near = max(2.0, med)
    fin0 = int(np.flatnonzero(np.isfinite(py))[0]) if np.isfinite(py).any() else n

    def setup(c, e, pr):
        """Where the move over columns c..e began (p0) and where it lands
        (p1) -> None where there is no telling, else (p0, p1, margin,
        frame_edge, flat_rows), `flat_rows` the flat-topped entry's columns
        and the rows they take. `pr`: read with the 1.11.43 pressure rules."""
        # where the move began: the reading just before it, or — where
        # the trace starts on the move (the blank margin at the frame) —
        # the end opposite the one its first column reads
        before = c - 1
        # (a reading on a fleck of one or two pixels in the trace's first
        # columns is no reading: 00051 p163's col 0 reads one at row 440
        # over a floor at 713, and as "where the move began" it turned the
        # opening into a fall. Further on, a climb's thin tip reads one-
        # and two-pixel runs too — 00200 p168's 363, 314, 297.5, 248 — and
        # skipping those put its start back down the climb)
        while before >= 0 and (not np.isfinite(py[before])
                               or pr and before <= fin0 + 2 and run_len(before) <= 2):
            before -= 1
        # the ink of the columns just before, by pixel, not the one
        # reading there: 00049 p136's last reading before its rise is a
        # stray dot at row 516, the baseline it rose from is at 643
        pens = [pen_row(j) for j in range(max(0, c - 3), c)]
        pens = [r for r in pens if r is not None]
        margin = False
        frame_edge = False
        flat_rows = []
        if before >= 0 and c - before <= 3 and pens:
            p0 = float(np.median(pens))
            # ...but not where the curve's own readings just before, on
            # its line and not on a dot, all say otherwise. Where the pen
            # is hidden under another series, the longest run in those
            # columns is that series' fringe: 00163 p207's pressure peaks
            # at the frame top under the rate's yellow, its "began" came
            # out at row 466 (the orange curve), and the peak was taken
            # for a stray and pulled down 9 MPa.
            seen = [j for j in range(max(0, c - 12), c) if np.isfinite(orig[j])]
            # (two stroke-heights: 00051 p191's entry starts at its floor,
            # 580, against pens a few rows up at 560)
            # (and not at the frame's left edge: 00053 p138's col 0 holds a
            # scrap of ink at row 447 beside an entry from the floor)
            if ((c > 3 or not pr) and any(run_len(j) > 2 for j in seen)
                    and not any(abs(orig[j] - p0) <= (2 * tall if pr else tall)
                                for j in seen)):
                return None
        elif before >= 0 and c - before <= 3:
            p0 = py[before]
        else:
            # No reading just before: the frame's blank margin. The ink
            # in those columns still says where the curve was (00051
            # p156: its baseline at rows 708-713).
            lvl = [pen_row(j) for j in range(max(0, c - 6), c)]
            lvl = [r for r in lvl if r is not None]
            if len(lvl) >= 2:
                p0 = float(np.median(lvl))
            else:
                # With none there either, this is the frame's own left
                # edge with the trace already moving: Carmine's Chart 2
                # (00051 p150) enters from the floor and climbs, and its
                # first columns read 18, 16, 1, 13 ... 39 MPa. Nothing
                # before says where the move began, but where it lands
                # can: clear beyond all of the first column's ink, the
                # move began at that column's far end. Landing within
                # it, there is no telling — 00051 p179 opens on a
                # pressure test held at the top of the frame and then
                # dropped, and guessing turned it upside down — and
                # nothing is repaired.
                after = e + 1
                while after < n and not np.isfinite(py[after]):
                    after += 1
                q1 = py[after] if after < n and after - e <= 3 else np.nan
                ys = np.flatnonzero(sub[:, c])
                if (c > 3 or not len(ys) or not np.isfinite(q1)
                        or ys[0] - tall <= q1 <= ys[-1] + tall):
                    return None
                # the far end over its first few columns: the frame's
                # own line can break up the first (00052 p150's col 0
                # shows 485-530 of a climb from the floor at 722)
                ys = np.flatnonzero(sub[:, c:min(e + 1, c + 4)].any(axis=1))
                p0 = float(ys[-1] if q1 < ys[0] else ys[0])
                frame_edge = True
                # A flat-topped entry: where the ink's leading edge holds
                # the level the trace entered at until the climb sets
                # off, the block under it is the stroke's own corner, and
                # the trace is on that edge — Chart 2's cols 1-5 read
                # 16, then 13 three times, along the foot of a block whose
                # top stays at 19.5 MPa. Where the edge drops first, the
                # sag is drawn and stays (00052 p150's, 00050 p145's).
                sgn = 1 if q1 < p0 else -1         # +1: climbing (rows fall)
                edg = rtop if sgn == 1 else rbot
                first = [edg[j] for j in (c, c + 1) if j <= e and np.isfinite(edg[j])]
                if first:
                    lvl0 = min(first) if sgn == 1 else max(first)
                    flat, m = True, c
                    while m <= e and np.isfinite(edg[m]) and sgn * (lvl0 - edg[m]) <= tall:
                        if sgn * (edg[m] - lvl0) > tall / 2.0:
                            flat = False
                            break
                        m += 1
                    if flat:
                        for j in range(c, m):
                            if np.isfinite(out[j]) and sgn * (out[j] - edg[j]) > tall:
                                flat_rows.append((j, edg[j] + sgn * med / 2.0))
            margin = True
        # and where it ends up: the first reading after it. A move that
        # comes back to where it began is a needle, and is left alone.
        after = e + 1
        while after < n and not np.isfinite(py[after]):
            after += 1
        p1 = py[after] if after < n and after - e <= 3 else np.nan
        return p0, p1, margin, frame_edge, flat_rows

    c = 0
    while c < n:
        if not tall_c[c]:
            c += 1
            continue
        e = c
        while e + 1 < n and tall_c[e + 1]:
            e += 1
        if e > c:
            # The 1.11.43 pressure rules are for climbs alone: a move they
            # don't read as a climb is read as before, so every fall reads as
            # in 1.11.42 (they put a false dip just before 00107 p244's drop
            # from 45 to 24 MPa, and zigzags on 00100's shutdown steps)
            st = setup(c, e, True) if pressure else None
            prm = bool(st is not None and np.isfinite(st[1]) and st[1] < st[0] - tall)
            if not prm:
                st = setup(c, e, False)
            if st is None:
                c = e + 1
                continue
            p0, p1, margin, frame_edge, flat_rows = st
            for j, v in flat_rows:
                out[j] = v
            up = np.isfinite(p1) and p1 < p0 - tall        # rows grow downward
            down = np.isfinite(p1) and p1 > p0 + tall
            # Just before the move: a reading on a lone dot (a run of one or
            # two pixels) in a column that also carries ink at the level the
            # move starts from is a stray, and the curve is on that level —
            # 00049 p136 read a dot at row 516 (20 MPa) in the two columns
            # before its rise, over the baseline at 642-644.
            if up or down:
                for j in range(max(0, c - 3), c):
                    if not np.isfinite(out[j]):
                        continue
                    ys = np.flatnonzero(sub[:, j])
                    if not len(ys):
                        continue
                    runs_j = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)
                    mine = next((g for g in runs_j if g[0] - 1 <= out[j] <= g[-1] + 1), None)
                    if mine is None or len(mine) > 2 or abs(out[j] - p0) <= 2 * tall:
                        continue
                    # (a line at that level, not a tall stroke through it: 00053
                    # p132's col 4 reads the dotted top of its entry bar, and the
                    # bar's body, rows 489-572, reaches 71 rows up the move from
                    # where it began, no baseline; 00053 p163's floor ink at
                    # 680-717, 22 rows either side, is one)
                    base = [g for g in runs_j if abs(float(np.median(g)) - p0) <= near
                            and (max(p0 - g[0], g[-1] - p0) <= 2 * tall or not prm)]
                    if base:
                        out[j] = capped(j, float(np.median(np.concatenate(base))))
            # A repair is a reading back where the move began (`back`) AND
            # fallen more than `tall` behind the furthest the move has read
            # (`reached`): a steady climb whose readings lag at the foot of
            # their columns has not fallen back, and replacing those put a
            # bump in 00006 p152 (24.7 22.4 24.8 -> 30 37 46 50, then 35).
            # The repaired reading lies between what had been reached and
            # where the move lands (p1): it fills a false dip and draws no
            # peak (00048 p130 grew one at 31). And the move has to be a big
            # one (start to landing more than 3 x `tall`) that had got
            # somewhere (more than 2 x `tall`) before anything fell back from
            # it: a climb that has gained a couple of MPa and reads the
            # lagging edge of its own line is just climbing (00006 p152).
            reached = None                             # furthest row read so far
            reached_at = -1                            # the column that read it
            fixed = np.zeros(n, bool)                  # repaired in this move
            lead = np.zeros(n, bool)                   # read at its leading end
            new_far = np.zeros(n, bool)                # took the move further
            footed = np.zeros(n, bool)                 # repaired by foot_fix
            reached_now = np.full(n, np.nan)           # furthest, as column k came
            fr = rtop if up else rbot

            def foot_fix(k, nb):
                """Column k read at its foot next to column nb read on its
                front side (or repaired to it): read k at its front too, if
                its front holds. A climb read at the foot throughout is late
                but monotone, and is left alone (00052 p154)."""
                if not (prm and up):
                    return False
                recent = (reached is None or k - reached_at <= 6) if nb < k \
                    else bool(new_far[k + 1:k + 7].any())
                # (a front fallen back behind where the move had got is a dip
                # the page draws: 00048 p142's V at col 31, its front at 419
                # under the 256 the climb had reached)
                rn = reached_now[k]
                if np.isfinite(rn) and np.isfinite(fr[k]) and (fr[k] > rn + tall if up
                                                               else fr[k] < rn - tall):
                    return False
                if not ((up or down) and np.isfinite(out[k]) and np.isfinite(fr[k])
                        and recent
                        and (out[k] - fr[k] > tall if up else fr[k] - out[k] > tall)
                        and c <= nb <= e and (lead[nb] or fixed[nb] or (
                            np.isfinite(out[nb]) and np.isfinite(fr[nb])
                            and (out[nb] - fr[nb] <= tall if up else fr[nb] - out[nb] <= tall)))):
                    return False
                ha = hb = k                      # the columns holding this level
                while ha - 1 >= c and np.isfinite(orig[ha - 1]) and abs(orig[ha - 1] - orig[k]) <= tall:
                    ha -= 1
                while hb + 1 <= e and np.isfinite(orig[hb + 1]) and abs(orig[hb + 1] - orig[k]) <= tall:
                    hb += 1
                # A foot followed by a foot further down is a fall, not a
                # climb lagging: 00054 p159 falls into a V drawn after its
                # climb, 410, 422, 438 under a front the V's own arms hold
                # at 224; a climb read at its foot moves up with the climb
                nx = k + 1
                if (nx <= e and np.isfinite(orig[nx]) and np.isfinite(fr[nx])
                        and orig[nx] - fr[nx] > tall and orig[nx] > orig[k] + tall / 2.0):
                    return False
                held = hb - ha + 1
                nxt3 = [fr[j] for j in range(k, min(n, k + 3)) if np.isfinite(fr[j])]
                wb = out[max(0, c - 6):(k if margin else c)]
                wb = [p0, *wb[np.isfinite(wb)]]
                beyond = (out[k] > max(wb) + 1.5 * tall if up
                          else out[k] < min(wb) - 1.5 * tall)
                at_floor = (out[k] >= sub.shape[0] - 1 - tall if up else out[k] <= tall)
                if at_floor:
                    beyond = False
                # (three at the floor where the climb sets off from it: the
                # opening, or 00051 p167's first rise after the trace has lain
                # on the floor, 707, 715, 715 under ink up to 648, 475, 456)
                limit = 3 if at_floor and (k <= 8 or p0 >= sub.shape[0] - 1 - tall) else 2
                if (held > limit or beyond
                        or not (max(nxt3) <= fr[k] + tall / 2.0 if up
                                else min(nxt3) >= fr[k] - tall / 2.0)):
                    return False
                offs = []
                for j in (k - 2, k - 1, k + 1, k + 2):
                    if c <= j <= e and np.isfinite(orig[j]) and np.isfinite(fr[j]):
                        o = orig[j] - fr[j] if up else fr[j] - orig[j]
                        if 0 <= o <= tall:
                            offs.append(o)
                off = max(med / 2.0, float(np.median(offs))) if offs else med / 2.0
                out[k] = fr[k] + off if up else fr[k] - off
                fixed[k] = footed[k] = True
                return True

            for k in range(c, e + 1):
                at_top = abs(out[k] - rtop[k]) <= near
                at_bot = abs(out[k] - rbot[k]) <= near
                # back where it began: within two stroke-heights of it, or in
                # the first quarter of the move so far (00049 p136's false
                # readings sit 29 rows, ~5 MPa, off the floor of a 170-row rise)
                # — the first third where the move then lands at least as far
                # as it had got: 00051 p150's rebound to 61.6 MPa sits 26% of
                # the way down a fall from 72 that lands at 44. A real V after
                # a climb lands short of the top (00051 p199's falls 68% of the
                # way back and climbs again from there), and keeps its bottom.
                # And only just after the move got there, within four columns:
                # a noisy band thick enough that a whole stretch of chart is
                # one "move" (00163 p260's chem conc, 181 columns) is not a
                # stroke read from the wrong end, and a third invented a dip.
                span = abs(p0 - reached) if reached is not None else 0.0
                landed = reached is not None and k - reached_at <= 4 and (
                    p1 <= reached + tall if up else p1 >= reached - tall)
                back = abs(out[k] - p0) <= max(2 * tall, span / 3.0 if landed else 0.25 * span)
                if back and frame_edge:
                    # at the frame's edge, only one or two columns reading
                    # the far end: a level held longer is drawn (00050
                    # p145's opening sags to 402 for six columns)
                    a0 = b0 = k
                    while a0 - 1 >= c and np.isfinite(orig[a0 - 1]) and abs(orig[a0 - 1] - orig[k]) <= tall:
                        a0 -= 1
                    while b0 + 1 <= e and np.isfinite(orig[b0 + 1]) and abs(orig[b0 + 1] - orig[k]) <= tall:
                        b0 += 1
                    back = b0 - a0 + 1 <= 2
                # in the trailing half of its column's ink, not only at its
                # very end: 00009 p169's col 9 reads 14 rows above the foot of
                # the upright it is part of (5.8 MPa where the page holds 17).
                # And the column's OWN ink reaches the level already reached:
                # it is still the upright. A real V drawn after a climb has
                # left that level — 00048 p142's dip from 67 to 32 MPa at col
                # 31 inks rows 419-540, nowhere near the 256 it fell from.
                low_half = out[k] - rtop[k] > rbot[k] - out[k]
                high_half = rbot[k] - out[k] > out[k] - rtop[k]
                # Or right behind a column just repaired, falling back more
                # than `tall` from it onto the edge of the stroke: once the
                # move reads from its leading end, the next column read from
                # its trailing end puts the same zigzag one column on (00048
                # p130's rise read 20, 21.5, then 7 MPa; 00005 p203's fall 57,
                # 50, 60, 45). On the edge, that is — the trailing edge still
                # closing on the leading level by more than 1.5 x `tall` a
                # column (00048 p130's: 42, 76, 71, 59 rows, `tall` 24). A
                # notch drawn just after a rise has an edge that holds its
                # level (00048 p142's 582, 566, 566, 566), and a steady climb
                # one that creeps (00200 p189's 16 rows a column); both keep
                # their readings. The repaired column's reading counts as
                # reached when judging how far this one has fallen back, not
                # whether its ink reaches: 00052 p150's conc falls 320 -> 0
                # across columns each inked part way, and holding a column to
                # the one before's landing left its reading at the top.
                # And a column repaired this way reads no further on than
                # the two after it: on a slanted rise the top of a thick
                # stroke runs ahead of the curve, and 00590 p322 traded a
                # false dip to 27 MPa for a false peak at 44.
                ref = reached
                follow = False
                took = False
                # A column read at its foot — more than `tall` behind its own
                # front — is read at its front, while that front holds or keeps
                # advancing over this column and the next two. A long thick
                # climb read top, foot, top, foot zigzags its whole length
                # (Stage 6, 00051 p155: rows 523, 397, 482, 293, 463, 375 ... on
                # a front climbing 473, 397, 392, 293, 280, 216); a step's flat
                # top over the block of its corner reads the foot (00051 p170:
                # 647, 647, 503, 493 under a front held at 424); a trace rising
                # off the floor reads it before any column has read a front
                # (00051 p181: 713, 679, 663 under 496, 472, 472). Read at the
                # front, all three are monotone. A dip the page draws takes the
                # front down with it (00048 p142's notch, its front to 536) and
                # keeps its reading; so does a level held more than two columns
                # (00051 p156's 30 -> 23), and a reading beyond where the move
                # began. And only within six columns of the move's last new
                # furthest reading: a noisy band thick enough to be one long
                # "move" is not a stroke (00163 p260's chem conc).
                if reached is not None:
                    reached_now[k] = reached
                if foot_fix(k, k - 1):
                    if reached is None or (out[k] < reached if up else out[k] > reached):
                        reached, reached_at = out[k], k
                        new_far[k] = True
                    continue
                if not took and k > c and (fixed[k - 1] or frame_edge and lead[k - 1]) and k + 1 < n and (
                        out[k] > out[k - 1] + tall if up else out[k] < out[k - 1] - tall):
                    edge, nxt = (rbot[k], rbot[k + 1]) if up else (rtop[k], rtop[k + 1])
                    if np.isfinite(nxt) and (nxt < edge - 1.5 * tall if up
                                             else nxt > edge + 1.5 * tall):
                        # (only where the repair is this rule's alone)
                        follow = not (back and (out[k] > reached + tall if up
                                                else out[k] < reached - tall))
                        back = took = True
                        ref = (min(reached, out[k - 1]) if up
                               else max(reached, out[k - 1]))
                # Not past where it began, either: a column whose reading lies
                # beyond the start and the readings before it, away from the
                # move, is an overshoot the page draws. 00200 p189's pressure
                # tops out at 80 MPa on the stroke it falls by, 4 MPa over the
                # hold it fell from; 00006 p154's rate needles up to 13.4 on
                # its way down from 12.6. Judged against the readings before
                # the move, not the move's own (the needle's first column is
                # one of those) — except where the trace opens on the move:
                # there the start is a median of the margin's ink, 00048
                # p142's 77 rows short of the baseline its first columns read,
                # and the move's own readings so far count too.
                w = out[max(0, c - 6):(k if margin else c)]
                w = [p0, *w[np.isfinite(w)]]
                back = back and (out[k] <= max(w) + tall if up else out[k] >= min(w) - tall)
                ahead = orig[k + 1:k + 3]
                ahead = ahead[np.isfinite(ahead)]
                # a repair in a move opening at the frame's edge, too, reads
                # no further on than the furthest of the next three: the top
                # of a slanted stroke runs ahead of the curve, and 00049
                # p144's opening grew a peak at 40 MPa that way, 00050 p145's
                # one at 55
                ahead3 = orig[k + 1:k + 4]
                ahead3 = ahead3[np.isfinite(ahead3)]
                if up and at_top:
                    lead[k] = True
                    if reached is None or out[k] < reached:
                        reached, reached_at = out[k], k
                        new_far[k] = True
                elif down and at_bot:
                    lead[k] = True
                    if reached is None or out[k] > reached:
                        reached, reached_at = out[k], k
                        new_far[k] = True
                elif (reached is not None and back and up and low_half
                        and rtop[k] <= reached + tall and out[k] > ref + tall
                        and p0 - reached > 2 * tall and p0 - p1 > 3 * tall):
                    lo_r, hi_r = min(p1, reached), max(p1, reached)
                    out[k] = min(max(capped(k, rtop[k] + med / 2.0), lo_r), hi_r)
                    fixed[k] = True
                    if follow and len(ahead):
                        out[k] = max(out[k], float(np.min(ahead)))
                    elif frame_edge and len(ahead3):
                        out[k] = max(out[k], float(np.min(ahead3)))
                elif (reached is not None and back and down and high_half
                        and rbot[k] >= reached - tall and out[k] < ref - tall
                        and reached - p0 > 2 * tall and p1 - p0 > 3 * tall):
                    lo_r, hi_r = min(p1, reached), max(p1, reached)
                    out[k] = min(max(capped(k, rbot[k] - med / 2.0), lo_r), hi_r)
                    fixed[k] = True
                    if follow and len(ahead):
                        out[k] = min(out[k], float(np.max(ahead)))
                    elif frame_edge and len(ahead3):
                        out[k] = min(out[k], float(np.max(ahead3)))
            # and back the other way, for feet read before the first front
            # (00051 p181's entry: 713, 679, 663, then 472 at the front)
            for k in range(e - 1, c - 1, -1):
                if not fixed[k]:
                    foot_fix(k, k + 1)
            # Repairs from one of those on (the follow-on takes the columns
            # after it too) that end on a foot further back than the step
            # they took away are undone: after a thin tip read at the front,
            # a slow climb read at its foot is left late but monotone, and
            # lifting only its first columns moved the step back on and made
            # it bigger (00187 p192: 593, then 617 -> 568, 558, 522, then 586;
            # 00119 p141, 00232 p191 by one column each)
            k = c
            while k <= e:
                if not fixed[k]:
                    k += 1
                    continue
                a = k
                while k + 1 <= e and fixed[k + 1]:
                    k += 1
                b, k = k, k + 1
                f = next((j for j in range(a, b + 1) if footed[j]), None)
                if (f is not None and b + 1 < n and f - 1 >= 0
                        and np.isfinite(out[b + 1]) and np.isfinite(out[f - 1])
                        and out[b + 1] - out[b] > max(tall, orig[f] - out[f - 1])):
                    out[f:b + 1] = orig[f:b + 1]
                    fixed[f:b + 1] = footed[f:b + 1] = False
            # The stroke's trailing edge after the top: one or two columns
            # still reading the bottom of the thick upright, far below both
            # the reading before them and the one after (00051 p159: 26.5,
            # then 12.3 and 11.2 off the upright's edge, then 21-27 — the page
            # draws a small notch at ~22). A real dip after an overshoot is
            # shallower (p156's 30 -> 23 is drawn) and a hold is longer; both
            # keep their level.
            # Rises only: on a fall the stroke's trailing edge reads its top,
            # and so does a real spike — 00048 p139's Btm Prop Conc needle to
            # 304 was cut to 282 by this rule run on falls.
            if up:
                sign = 1
                k = c + 1
                while k <= e:
                    tail_end = k
                    while (tail_end <= e and tail_end - k < 3
                           and abs(out[tail_end] - (rbot[tail_end] if up else rtop[tail_end])) <= near):
                        tail_end += 1
                    run = tail_end - k
                    if 1 <= run <= 2 and tail_end <= e + 1:
                        # judged against the readings around it, three a side,
                        # not one: the column after p156's real dip to 23 is
                        # itself a tall column read at its top (31)
                        lft = [out[j] for j in range(k - 1, max(-1, k - 6), -1) if np.isfinite(out[j])][:3]
                        rgt = [out[j] for j in range(tail_end, min(n, tail_end + 6)) if np.isfinite(out[j])][:3]
                        prv = float(np.median(lft)) if lft else np.nan
                        nx = float(np.median(rgt)) if rgt else np.nan
                        if (np.isfinite(prv) and np.isfinite(nx)
                                and all(sign * (out[j] - prv) > 2 * tall
                                        and sign * (out[j] - nx) > 2 * tall
                                        and rtop[j] <= min(prv, nx) + tall   # still the upright
                                        for j in range(k, tail_end))):
                            for j in range(k, tail_end):
                                # up out of the dip, no higher than the lower
                                # of its two sides: a fill, not a peak
                                out[j] = min(max(capped(j, rtop[j] + med / 2.0), prv, nx), out[j])
                    k = max(tail_end, k + 1)
            # Just after the move, a reading on a speck of one or two pixels,
            # back behind where the move had got, in a column whose own
            # stroke carries the move on: a pixel of another line in the
            # mask, and the curve is on the stroke. 00100 p173 climbs from 9
            # to 89 MPa over cols 272-283, and cols 281-282 read a pixel of
            # the orange curve at row 680 under the red stroke at 80-235 — a
            # peak and a drop once the climb itself read right. Up to the
            # first reading off a speck, and no further on than it.
            far = np.nanmin(out[c:e + 1]) if prm and up else np.nan
            for j in range(e + 1, min(n, e + 7)) if np.isfinite(far) else ():
                if not np.isfinite(out[j]):
                    continue
                if run_len(j) > 2 or not (out[j] > far + tall if up else out[j] < far - tall):
                    break
                ys = np.flatnonzero(sub[:, j])
                on = [g for g in np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)
                      if len(g) >= tall and (g[0] <= far + tall if up else g[-1] >= far - tall)]
                if not on:
                    break
                v = (min(g[0] for g in on) + med / 2.0 if up
                     else max(g[-1] for g in on) - med / 2.0)
                ahead = [out[i] for i in range(j + 1, min(n, j + 4))
                         if np.isfinite(out[i]) and run_len(i) > 2]
                if ahead:
                    v = max(v, min(ahead)) if up else min(v, max(ahead))
                out[j] = v
        c = e + 1
    # Last, a trace's opening: one to three columns reading at (or within two
    # stroke-heights of) the frame's floor
    # between readings well clear of it are the foot of the bar the trace
    # comes in by — 00051 p163 reads 470, then the floor three times, then
    # 517 — where the move they sit in could not be judged. Each takes the
    # point of its own ink nearest the straight line between its sides. A
    # drop to the floor held longer is drawn (00051 p179's, five columns).
    fl = sub.shape[0] - 1
    fin = np.flatnonzero(np.isfinite(out))
    if pressure and len(fin):
        # First, the trace's first readings on a scrap of ink no thicker
        # than the pen, well up the chart, over a stroke rising from the floor
        # (in that column or the next): the pressure comes up off the floor,
        # and starts from it. 00051 p163 (Carmine, #808) read 440 and 470 on
        # scraps of 2 and 4 rows over the stroke rising from the floor — and
        # began at 39 MPa instead of 0. A pen line along the top with only
        # the frame's own line at the floor stays (00107 p253's 355)
        def runs_of(j):
            ys = np.flatnonzero(sub[:, j])
            return np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1) if len(ys) else []
        flr = [out[j] for j in fin[:8] if out[j] >= fl - 2 * tall]
        for j in fin[:2]:
            runs_j = runs_of(j)
            mine = next((g for g in runs_j if g[0] - 1 <= out[j] <= g[-1] + 1), None)
            rising = [g for jj in (j, j + 1) if jj < n for g in runs_of(jj)
                      if g[-1] >= fl - tall and len(g) >= tall]
            if mine is not None and len(mine) <= med and out[j] < fl - 3 * tall and rising:
                out[j] = float(np.median(flr)) if flr else fl - med / 2.0
        j = fin[0]
        while j < min(n, fin[0] + 10):
            if not (np.isfinite(out[j]) and out[j] >= fl - 2 * tall):
                j += 1
                continue
            b = j
            while b + 1 < n and np.isfinite(out[b + 1]) and out[b + 1] >= fl - 2 * tall:
                b += 1
            lj = next((i for i in range(j - 1, max(-1, j - 4), -1) if np.isfinite(out[i])), None)
            rj = next((i for i in range(b + 1, min(n, b + 4)) if np.isfinite(out[i])), None)
            if (b - j + 1 <= 3 and lj is not None and rj is not None
                    and out[lj] < fl - 3 * tall and out[rj] < fl - 3 * tall):
                for i in range(j, b + 1):
                    ys = np.flatnonzero(sub[:, i])
                    want = out[lj] + (out[rj] - out[lj]) * (i - lj) / float(rj - lj)
                    if len(ys) and ys[0] < fl - 3 * tall:
                        out[i] = float(ys[np.argmin(np.abs(ys - want))])
            j = b + 1
    return out


def _keep_excursions(sub, py, min_px=6, factor=3.0, split=0.25, pressure=True):
    """Curve rows -> (column positions, rows), splitting near-vertical strokes.

    One reading per column is right while the curve is drawn as a stroke: the
    run is the pen's thickness and its median is the value. It is wrong the
    moment the curve moves faster than the render's resolution. STEP's charts
    are ~6 seconds per pixel column (00030 stage 30: 4,937 s across 827
    columns), so a spike, a step riser or the ramp at the start of pumping is
    drawn as ONE tall run — and its median is the MIDDLE of that move. The
    export then shows a spike half as deep as the page draws it, which is the
    flattening reported in #66: on that page the green Prop Conc needle at
    07:59 reads 223 kg/m3 where the chart draws it running from 407 down to 3.

    So where the run is much taller than this chart's own stroke, emit BOTH
    of its ends — a quarter of a column apart, in the order that continues
    the trace — instead of their midpoint. Nothing is invented: both rows are
    ink the page actually printed, and the pair spans the same column it
    always did. Ordinary columns are untouched and come out bit-identical.
    """
    n = sub.shape[1]
    py = _despeckle(py)
    top, bot = _chosen_run(sub, py)
    height = bot - top + 1.0
    med = float(np.nanmedian(height)) if np.isfinite(height).any() else 1.0
    tall = max(min_px, factor * med)
    # nearest finite reading on each side, to say which end continues the trace
    prev = np.full(n, np.nan)
    nxt = np.full(n, np.nan)
    last = np.nan
    for c in range(n):
        prev[c] = last
        if np.isfinite(py[c]):
            last = py[c]
    last = np.nan
    for c in range(n - 1, -1, -1):
        nxt[c] = last
        if np.isfinite(py[c]):
            last = py[c]
    py = _no_flip_back(sub, py, med, tall, pressure=pressure)
    xs, rows = [], []
    for c in range(n):
        if not np.isfinite(py[c]):
            continue
        if not np.isfinite(height[c]) or height[c] < tall:
            xs.append(float(c))
            rows.append(py[c])
            continue
        hi, lo = top[c], bot[c]
        if np.isfinite(prev[c]):
            first, second = ((hi, lo) if abs(hi - prev[c]) <= abs(lo - prev[c])
                             else (lo, hi))
        elif np.isfinite(nxt[c]):
            second, first = ((hi, lo) if abs(hi - nxt[c]) <= abs(lo - nxt[c])
                             else (lo, hi))
        else:
            xs.append(float(c))
            rows.append(py[c])
            continue
        xs.append(c - split)
        rows.append(first)
        xs.append(c + split)
        rows.append(second)
    return np.asarray(xs, dtype=float), np.asarray(rows, dtype=float)


def _page_geom(info, scale_x, scale_y, off_x=0.0, off_y=0.0):
    """Chart geometry in PAGE coordinates, so the Lab can lay the source page
    behind our curves (ghost mode) the same way it does for vector templates.

    STEP is scanned, so everything upstream works in IMAGE pixels. The page
    embeds those images at a known rect, which makes the conversion a plain
    scale + offset. Convention matches lib1/frac_core: elapsed second e sits at
    page coord (e - ta) / tb along `axis`, and v0/v1 bracket the plot on the
    other axis in mupdf (y-down) units. STEP charts run time left-to-right, so
    the axis is x and v0/v1 are the frame's top and bottom.
    """
    box = info.get("plot")
    if not box or not scale_x or not scale_y:
        return None
    x0, y0, x1, y1 = box
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    dur = float(info.get("duration_s") or 0)
    if dur <= 0:
        return None
    tb_img = dur / float(x1 - x0)               # seconds per image pixel
    ta_img = float(info.get("t0_seconds") or 0) - tb_img * x0
    tb_page = tb_img * scale_x                  # seconds per page unit
    ta_page = ta_img - tb_img * scale_x * off_x
    if abs(tb_page) < 1e-12:
        return None
    return {"axis": "x",
            "ta": float(ta_page - float(info.get("t0_seconds") or 0)),
            "tb": float(tb_page),
            "v0": float(off_y + y0 / scale_y),
            "v1": float(off_y + y1 / scale_y)}


# ---------- the span the chart prints under itself ----------

# "11/21/2017 19:26:12 - 11/21/2017 20:32:46. Range: 1 hr. 6 min."
_SPAN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*(\d{1,2}):(\d{2}):(\d{2})")

# How far the printed start may sit from the time axis' own fitted origin and
# still be a reading of the same instant. Measured across 00199 pages 17-40:
# the fit lands 9-16s EARLY on every chart (the frame's black border is a few
# pixels wide, and x0 is its outer edge), never further. 120s leaves room for
# a coarser render while still refusing a coincidence.
CLOCK_TOL = 120.0


def _last_ink_rows(band, floor=0.002):
    """(top, bottom) of the LAST text line in `band`, or None. A run of rows
    carrying any ink at all, no taller than a line of type."""
    dark = band.sum(axis=2) < 400
    hit = dark.mean(axis=1) > floor
    runs, start = [], None
    for i, v in enumerate(hit):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(hit)))
    runs = [r for r in runs if 4 <= r[1] - r[0] <= 40]
    return runs[-1] if runs else None


def _footer_strip(img, box):
    """The one text line under a plot that could be its printed span, ready
    to OCR, or None.

    The strip below the frame holds the tick labels, then the legend, then —
    on the layouts that print one — the chart's own date-time span, always
    last. Cropping to that last line keeps the OCR to a few hundred pixels
    and keeps the legend's "(L/m³)" clutter out of it."""
    if not box:
        return None
    x0, y0, x1, y1 = box
    H, W = img.shape[:2]
    ph = max(1, y1 - y0)
    band = img[min(H - 1, y1 + 2):min(H, y1 + int(0.32 * ph)),
               0:min(W, x0 + int(0.60 * (x1 - x0)))]
    if band.size == 0:
        return None
    row = _last_ink_rows(band)
    if row is None:
        return None
    crop = band[max(0, row[0] - 4):min(band.shape[0], row[1] + 4)]
    if crop.size == 0:
        return None
    from PIL import Image as _Im
    pil = _Im.fromarray(crop.astype(np.uint8))
    pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
    return np.array(pil).astype(int)


def _printed_span(strip, psm):
    """-> (iso_date, start_seconds, span_seconds|None), or None.

    FracPro stamps the plotted window under every chart it draws — the two
    calendar instants and a "Range: N hr M min" restating them. That line is
    the report's own answer to "when did this stage run", printed to the
    second, and on the 2024 layout it is the only place a date appears at
    all. It is also seven pixels tall, and no page-segmentation mode reads it
    reliably: psm 6 read 00199 p37's chemical chart as 19:20:30 and psm 11 as
    19:28:30 against a printed 19:29:30, and on 00664 p128 psm 6 lost a digit
    where psm 11 did not. Nothing this returns is trusted on its own — the
    caller checks it against the time axis it fitted independently, and asks
    for the other mode when it fails.
    """
    if strip is None:
        return None
    try:
        text = " ".join(t for t, _cx, _cy in ar.ocr_words(
            strip, psm=psm, whitelist="0123456789/:.- "))
    except Exception:
        return None
    got = _SPAN.findall(text)
    if not got:
        return None
    a = got[0]
    mo, dy, yr = int(a[0]), int(a[1]), int(a[2])
    if not (1 <= mo <= 12 and 1 <= dy <= 31 and 1990 <= yr <= 2100):
        return None
    s0 = int(a[3]) * 3600 + int(a[4]) * 60 + int(a[5])
    if not 0 <= s0 < 86400:
        return None
    # The closing instant is the weaker read of the two — one eaten separator
    # ("07104/2024") takes the whole of it — so the span it implies is
    # corroboration where it survives, not a condition of reporting a start.
    span = None
    if len(got) > 1:
        b = got[1]
        s1 = int(b[3]) * 3600 + int(b[4]) * 60 + int(b[5])
        if 0 <= s1 < 86400:
            span = (s1 - s0) % 86400
    return (f"{yr:04d}-{mo:02d}-{dy:02d}", s0, span)


def _place_on_clock(img, info):
    """Stamp a chart with the calendar instant its own footer prints.

    Only when the time axis agrees. The axis fit and the footer are two
    independent readings of the same left-hand edge, so agreement inside
    CLOCK_TOL is what says the axis is a wall clock rather than elapsed
    minutes — and on a chart whose axis IS elapsed minutes they cannot agree
    except by a coincidence a 120-second window will not supply.

    The axis fit, not the footer, is what the clock is set to. It is the same
    number geom and sample 0 are already quoted against, it is fitted from
    every tick on the axis rather than OCR'd from one 7-pixel line, and it is
    what the 2024 layout has always reported. The footer's contribution is
    the DATE — which no other part of these pages prints — and the proof.
    """
    t0 = float(info.get("t0_seconds") or 0) % 86400
    dur = float(info.get("duration_s") or 0)
    strip = _footer_strip(img, info.get("plot"))
    ok = []
    # psm 11 is only paid for when psm 6 came back with nothing usable. Every
    # chart in the corpus is one of these calls, and a whole 2024 book is 250
    # of them.
    for psm in (6, 11):
        got = _printed_span(strip, psm)
        if got is not None:
            date, s0, span = got
            off = min(abs(s0 - t0), 86400 - abs(s0 - t0))
            # Where the closing instant was read too, the range it implies
            # must be the range we measured — otherwise one of the two was
            # misread, and the date printed beside them is no more
            # trustworthy than they are.
            if off <= CLOCK_TOL and not (
                    span is not None and dur > 0
                    and abs(span - dur) > max(90.0, 0.05 * dur)):
                ok.append(date)
        if ok:
            break
    already = bool(info.get("clock_start"))
    if not ok:
        return already
    info["clock_date"] = ok[0]
    if not already:
        s = int(float(info.get("t0_seconds") or 0)) % 86400
        info["clock_start"] = "%02d:%02d:%02d" % (s // 3600, s // 60 % 60,
                                                  s % 60)
    return True


# These pages caption each plot in their own text layer, directly above it —
# "Surface Chart" at y56 over the image at y92, "Chemical Chart" at y399 over
# the image at y410, on every one of 00344's 32 chart pages.
_CHART_CAPTIONS = (("Surface Chart", "t"), ("Surface Treatment Plot", "t"),
                   ("Chemical Chart", "c"), ("Chemical Treatment Plot", "c"))


def _caption_tag(page, rect):
    """Which chart is this image, read from the caption printed above it?

    The alternative — and what this replaces — is to call the first image that
    EXTRACTS the treatment chart and the next one chemical. That holds only
    while both succeed. On 00344 the surface plot raises "time axis
    unreadable" on all 32 chart pages, so the chemical plot arrived first,
    inherited the treatment tag, and was exported under the surface chart's
    channel names: its D-Clean Rate curve went out as "Slurry Rate" against
    the chemical chart's own 0..16 axis, which is a legal rate scale and so
    passed impossible_axis untouched (#585). A failure upstream turned into
    wrong data downstream, which is the worst shape a bug can take here.

    Position within the page is not the test either — the tiled path's own
    comment records 00184/00185 putting a second TREATMENT chart where the
    chemical one usually sits. The caption is the page's own answer.
    """
    best, bestd = None, 1e9
    for phrase, tag in _CHART_CAPTIONS:
        try:
            hits = page.search_for(phrase)
        except Exception:
            continue
        for r in hits:
            gap = rect.y0 - r.y1
            if -2.0 <= gap < min(bestd, 120.0):
                bestd, best = gap, tag
    return best


def _extract_new(page, sample_sec=1.0):
    doc = page.parent
    text = _page_text(page)
    meta = {"stage": None, "interval": "", "kind": "main", "uwi": "",
            "date": "", "clock": False}
    # These pages number the stage as "Treatment N"; only some spell it
    # "Interval N". Looking for Interval alone left every page of a file with
    # stage None, so they all grouped under one nameless stage and the Lab
    # showed a single "Stage ?". This is the page's real text layer, not OCR.
    #
    # The 2024 filings number it "Interval N.M": N is the interval and M a
    # separate treatment OF that interval — 1.1, 1.2 and 1.3 are three
    # attempts on interval 1, pumped on two different days at three different
    # clock times, each with its own row in the printed stage summary. Reading
    # N alone fused all three into one stage, so the sub-number is kept and
    # the stage becomes the string "1.2". A bare "Interval 7" still yields the
    # integer 7 exactly as before.
    #
    # Neither number may run on into a depth. Where the OCR of an outlined
    # page loses the stage number, "Treatment" sits straight above the
    # interval, and "Treatment\n3,053.50 m" read as Treatment 3 (00347 p81).
    # No number at all is better: the Daily Stage Summary numbers the chart
    # by its depth (pipeline._step_stage_from_depth).
    m = re.search(r"Interval\s+(\d+)(?:\.(\d+))?(?![\d,])", text)
    if m:
        meta["stage"] = (int(m.group(1)) if m.group(2) is None
                         else f"{int(m.group(1))}.{m.group(2)}")
    else:
        m = re.search(r"Treatment\s+(\d+)(?![\d,.])", text)
        if m:
            meta["stage"] = int(m.group(1))
    m = re.search(r"([\d,]+\.\d+)\s*m\s*-\s*([\d,]+\.\d+)\s*m", text)
    if m:
        meta["interval"] = f"{m.group(1)}-{m.group(2)} m"
    # 2024 layout only: the page prints its own well and date, and its time
    # axis is a wall clock rather than elapsed minutes.
    if "Surface Chart" in text and "Chemical Chart" in text:
        meta["clock"] = True
    # Pacific Canbriam 2020 (00322/00337) plots the same wall clock — the
    # axis reads 23:15, 23:20 … and the chart footer prints the calendar span
    # — so sample 0 is a time of day here too. The page names no well and no
    # date, so only the clock is taken.
    elif ("Surface Treatment Plot" in _page_text(page)
            and "Chemical Treatment Plot" in _page_text(page)):
        meta["clock"] = True
        m = re.search(r"UWI\s+(\d{3})/([A-Z])-(\d{3})-([A-Z])/(\d{3})-([A-Z])"
                      r"-(\d{2})", text)
        if m:
            meta["uwi"] = "{}{}{}{}{}{}{}00".format(*m.groups())
        m = re.search(r"Date\s+(\d{4}-\d{2}-\d{2})", text)
        if m:
            meta["date"] = m.group(1)
    out = []
    done = set()
    for im in _big_images(page):
        if im[0] in done:
            continue
        done.add(im[0])
        pix = fitz.Pixmap(doc, im[0])
        if pix.colorspace is None:
            continue
        if pix.alpha or pix.colorspace.n != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3)
        try:
            r = page.get_image_rects(im[0])[0]
        except Exception:
            r = None
        # The page says which chart this is; ordinal position only says which
        # one got here first, and that is a different question the moment one
        # of them fails. See _caption_tag.
        cap = _caption_tag(page, r) if r is not None else None
        tag = cap or ("t" if not out else "c")
        try:
            samples, chans, info = _extract_new_chart(img, sample_sec)
        except ValueError as e:
            # A plot that cannot be read is a plot the report HAS and we do
            # not, so it is worth a line. 00344 loses its surface chart on all
            # 32 pages to "time axis unreadable" and said nothing at all.
            meta.setdefault("skipped", []).append(
                f"{'surface' if tag == 't' else 'chemical'} chart — {e}")
            continue
        _name_chemical(tag, chans)
        try:
            if r is not None and r.width > 1 and r.height > 1:
                info["geom"] = _page_geom(info, pix.width / r.width,
                                          pix.height / r.height, r.x0, r.y0)
        except Exception:
            pass
        if meta["clock"]:
            # Sample 0 is the plot frame's LEFT EDGE, not the printed start of
            # pumping, so the clock this stage is stamped with has to be the
            # edge too — anything else slides every reading along the day.
            # _page_geom already quotes ta relative to this same instant.
            s = int(info.get("t0_seconds") or 0) % 86400
            info["clock_start"] = "%02d:%02d:%02d" % (s // 3600, s // 60 % 60,
                                                      s % 60)
        # The wording tests above are the only thing that has ever set that
        # flag, and they are a list of the captions we happened to have seen:
        # "Surface Chart"/"Chemical Chart" (2024), "Surface Treatment Plot"
        # (Pacific Canbriam). The Shell 2017 books head the very same charts
        # "Shell Canada Limited Treatment Analysis", so 00196 and 00199 never
        # matched and exported 00:00:00 on every page — while their axes read
        # 19:30, 19:35 … 20:30, a wall clock already fitted to the second and
        # then thrown away. Ask the CHART instead of the caption.
        if _place_on_clock(img, info):
            meta["clock"] = True
        out.append((tag, samples, chans, info))
    return meta, out


def _is_pressure(c):
    if (c.get("unit") or "").lower() in ("mpa", "kpa", "psi"):
        return True
    return "pressure" in (c.get("label") or "").lower()


def _is_floored(c):
    """Concentration or rate — a quantity with a hard floor at zero."""
    if (c.get("unit") or "").lower() in ("kg/m3", "l/m3", "m3/min", "g/m3",
                                         "kg/min", "l/min", "%"):
        return True
    lab = (c.get("label") or "").lower()
    return "conc" in lab or "rate" in lab


def _axis_note(c, fr, what):
    return (f"{c.get('label')}: axis ({fr[0]:.2f}, {fr[1]:.2f}) is "
            f"not a possible {what} scale — channel dropped")


def impossible_axis(c):
    """-> a note if this channel's axis frame cannot be its own axis.

    A wrong number here is invisible downstream, a missing channel is not,
    so both the pressure test and the can't-go-negative test are refusals.
    See auto_raster.plausible_pressure_axis / plausible_floor_axis.
    """
    fr = c.get("axis_frame")
    if not fr:
        return None
    if _is_pressure(c):
        if c.get("key", "").startswith("series-offset-"):
            # A neighbouring well's pressure, read off an axis whose own title
            # says pressure. The abandoned wells' runs 0..4 MPa (00243 p42), a
            # span the treating-pressure test refuses as "a chemical scale".
            # Only the floor test applies.
            lo, hi = min(fr), max(fr)
            if not (hi > lo and lo >= -0.05 * (hi - lo)):
                return _axis_note(c, fr, "pressure")
        elif not ar.plausible_pressure_axis(*fr):
            return _axis_note(c, fr, "pressure")
    elif _is_floored(c) and not ar.plausible_floor_axis(*fr):
        return _axis_note(c, fr, "concentration/rate")
    # A PROPPANT concentration is printed in the hundreds of kg/m3 — every
    # STEP chart in the corpus tops that axis at 800 or 1,000. A chemical
    # chart's left axis is an ADDITIVE concentration in L/m3 topping out at 1
    # or 2, and because the colour table only knows the surface chart's
    # colours, its curves came out named "Prop Conc (kg/m3)" reading 0.83 —
    # 00322/00337 ship 143 such pages. No proppant axis is that small, so the
    # frame itself says the name cannot belong to it.
    if (c.get("unit") or "").lower() == "kg/m3" and abs(fr[0] - fr[1]) < 10:
        return _axis_note(c, fr, "proppant-concentration")
    return None


# A channel whose axis is this many times its same-unit siblings' has not
# found a different axis — it has lost a decimal point.
DECIMAL_SLIP = 50.0


def _fix_decimal_slip(charts):
    """Rescale a channel whose axis is a power of ten out of step with the
    channels sharing its unit on the same chart.

    A chemical chart prints every additive against the same small ladder, and
    tesseract reads "2.000" as "2000" when the decimal point is a single faint
    pixel. auto_raster already repairs a lost point that shows up as an OUTLIER
    inside one ladder, but here the WHOLE ladder reads 0, 500, 1000, 1500, 2000
    and is perfectly self-consistent, so nothing in that column looks wrong.
    On 00184 chart 17 SSI-3 Conc came out on a 0..2000 axis peaking at 1,244
    beside Aqucar 742 and SFR-202 B on 0..2 peaking at 0.22 and 0.32.

    It also defeats the plausibility test next door, which asks whether a
    channel's frame can be its own axis: 1,244 sits comfortably INSIDE 0..2000,
    so the axis check sees nothing to refuse. The evidence is not in the
    channel, it is in its siblings — hence a separate pass.

    Deliberately conservative. It needs three channels sharing a unit before a
    median means anything, the offender must be a clean power of ten out (a
    dropped point, not a different axis), and the correction must land it near
    its siblings. Anything else is left alone and, if it is genuinely
    impossible, refused downstream.
    """
    for _tag, _samples, chans, info in charts:
        by_unit = {}
        for c in chans:
            u = (c.get("unit") or "").strip().lower()
            fr = c.get("axis_frame")
            if u and fr:
                by_unit.setdefault(u, []).append(c)
        for unit, group in by_unit.items():
            if len(group) < 3:
                continue
            spans = [abs(c["axis_frame"][0] - c["axis_frame"][1])
                     for c in group]
            med = float(np.median(spans))
            if med <= 0:
                continue
            for c, span in zip(group, spans):
                if span < DECIMAL_SLIP * med:
                    continue
                p = round(math.log10(span / med))
                if p < 2 or abs(span / med / (10.0 ** p) - 1.0) > 0.05:
                    continue          # not a clean power of ten: leave it
                k = 10.0 ** p
                c["values"] = np.asarray(c["values"], dtype=float) / k
                c["axis_frame"] = (c["axis_frame"][0] / k,
                                   c["axis_frame"][1] / k)
                info.setdefault("notes", []).append(
                    "{}: axis read {:g}x its {} siblings' — a lost decimal "
                    "point; rescaled".format(c.get("label", "?"), k, unit))
    return charts


def _drop_impossible_axes(charts):
    """Refuse to export a channel read off an axis that cannot be its own."""
    out = []
    for tag, samples, chans, info in charts:
        keep = []
        for c in chans:
            note = impossible_axis(c)
            if note:
                info.setdefault("notes", []).append(note)
                continue
            keep.append(c)
        if keep:
            out.append((tag, samples, keep, info))
    return out


def _inner_plot_box(img, dark_sum=450):
    """The innermost box ruled on all four sides, at least 40% of the image
    wide and 25% tall -> (x0, y0, x1, y1), or None.

    For a page flattened into pictures, header and table and all: the plot's
    own frame is a thin mid-grey rule there, (96,96,96) down the sides and
    (146,146,146) along the top, and the darkest long rules on the page are
    the brown borders of the panel around it. _frame_bbox and find_charts
    both take those. Every box on the page is a candidate here, and the plot
    is the one inside all the others."""
    H, W = img.shape[:2]
    dark = np.asarray(img).sum(axis=2) < dark_sum
    rules = []
    for x in range(W):
        for a, b in _runs(dark[:, x], int(H * 0.25)):
            rules.append((x, a, b))
    groups = []
    for x, a, b in rules:
        for g in groups:
            if abs(g["a"] - a) <= 6 and abs(g["b"] - b) <= 6:
                g["xs"].append(x)
                break
        else:
            groups.append({"a": a, "b": b, "xs": [x]})
    # The top rule is checked a shade lighter: where it falls across a pixel
    # boundary it is anti-aliased over two rows at no darker than (154,154,
    # 154), and 00935 p47 (stage 6) lost its plot box, and with it the stage,
    # to a sum of 462.
    rule = np.asarray(img).sum(axis=2) < dark_sum + 60

    def smallest(groups):
        best = None
        for g in groups:
            x0, x1 = min(g["xs"]), max(g["xs"])
            if x1 - x0 < W * 0.4:
                continue
            a, b = g["a"], g["b"]
            ruled = lambda y: rule[max(0, y - 2):y + 3, x0:x1 + 1].any(axis=0).mean() >= 0.8
            if not (ruled(a) and ruled(b)):
                continue
            area = (x1 - x0) * (b - a)
            if best is None or area < best[0]:
                best = (area, (x0, a, x1, b))
        return best[1] if best else None

    box = smallest(groups)
    if box is not None and box[2] - box[0] < W * 0.85:
        return box
    # Only the panel, or nothing: the plot's sides may not start level. 00935
    # p63 (Interval 14.1, #810) prints a note box in the plot's top right
    # corner that hides the top of its right-hand rule, which runs from 526
    # where the left one runs from 469, so the two never paired. Sides that
    # END level are paired here, from the higher top, inside the panel; the
    # top and floor must still be ruled.
    by_floor = []
    for x, a, b in rules:
        for g in by_floor:
            if abs(g["b"] - b) <= 6:
                g["xs"].append(x)
                g["a"] = min(g["a"], a)
                break
        else:
            by_floor.append({"a": a, "b": b, "xs": [x]})
    inner = smallest([g for g in by_floor
                      if box is None or (g["a"] > box[1] + 20 and g["b"] < box[3] - 20)])
    return inner or box


def _extract_flattened(page, img, sample_sec=1.0):
    """A 2024 surface chart page printed as pictures only -> (meta, out), or
    None.

    00935 (#810) files its "Surface Chart" pages as four image strips with no
    text layer at all: tiled, so they reach the tiled reader, whose frame
    finder takes the panel border and finds no time axis below it — 71
    pages, "no extractable charts". The plot inside is the 2024 chart in
    every other respect, so it is read as one (see _inner_plot_box), and its
    stage and interval from an OCR of the page."""
    box = _inner_plot_box(img)
    if box is None:
        return None
    try:
        samples, chans, info = _extract_new_chart(img, sample_sec, box=box)
    except ValueError:
        return None
    text = ""
    try:
        import ocr_labels
        if ocr_labels.available():
            lines = ocr_labels._lines(page)
            lines.sort(key=lambda lt: (round(lt[0].y0, 1), lt[0].x0))
            text = "\n".join(t for _r, t in lines)
    except Exception:
        text = ""
    # The title and interval sit in the band over the plot, and an OCR of
    # that band alone reads them where the whole page's does not: 00935 p45,
    # p49, p51 and p53 lost "Interval 5" .. "Interval 9" and their depths
    # in the page's OCR, and every one reads cleanly here.
    try:
        band = img[max(0, box[1] - 330):box[1], box[0]:box[2]]
        text = " ".join(w[0] for w in ar.ocr_words(band, psm=6, whitelist="")) + "\n" + text
    except Exception:
        pass
    meta = {"stage": None, "interval": "", "kind": "main", "uwi": "",
            "date": "", "clock": False}
    m = re.search(r"Interval\s+(\d+)(?:\.(\d+))?(?![\d,])", text)
    if m:
        meta["stage"] = (int(m.group(1)) if m.group(2) is None
                         else f"{int(m.group(1))}.{m.group(2)}")
    m = re.search(r"([\d,]+\.\d+)\s*m\s*-\s*([\d,]+\.\d+)\s*m", text)
    if m:
        meta["interval"] = f"{m.group(1)}-{m.group(2)} m"
    tag = "c" if re.search(r"Chemical\s+Chart", text) and not re.search(
        r"Surface\s+Chart", text) else "t"
    _name_chemical(tag, chans)
    if _place_on_clock(img, info):
        meta["clock"] = True
    info.setdefault("notes", []).append(
        "a page printed as pictures only: its plot read inside the panel "
        "border, and its stage from an OCR of the page")
    return meta, _drop_impossible_axes(_fix_decimal_slip([(tag, samples, chans, info)]))


def extract_page(page, sample_sec=1.0):
    """-> (meta, [(chart_tag, samples, channels, info), ...])."""
    if not _detect_tiled(page) and _detect_new(page):
        meta, out = _extract_new(page, sample_sec)
        return meta, _drop_impossible_axes(_fix_decimal_slip(out))
    img = composite(page)
    # A LANDSCAPE page of pictures with no text layer is the 2024 chart
    # flattened (00935, #810), not a tiled 2017 book, which is portrait: on
    # one, the tiled reader takes the panel border for the frame and can
    # still read SOMETHING inside it, so it is not asked first.
    flat_first = img.shape[1] > img.shape[0] and not page.get_text().strip()
    if flat_first:
        flat = _extract_flattened(page, img, sample_sec)
        if flat is not None:
            return flat
    # the stacked tiles span the whole page, so one scale converts back
    pr = page.rect
    sx = img.shape[1] / pr.width if pr.width else 0
    sy = img.shape[0] / pr.height if pr.height else 0
    out = []
    seen_titles = []
    boxes = find_charts(img)
    for i, box in enumerate(boxes):
        # The chart says what it is. Position does not: 00184/00185 put a
        # second TREATMENT chart where the chemical one usually sits.
        try:
            title = ar.read_chart_title(img, box)
        except Exception:
            title = ""
        seen_titles.append(title)
        is_chem = "chemical" in title
        tag = "c" if is_chem else ("t" if "treatment" in title else
                                   ("t" if i == 0 else "c"))
        # Two chart STYLES share this tiled layout. The older one (00183)
        # prints each value axis' tick labels in that series' own colour, so a
        # number can be matched to a curve by colour — that is what ar.extract
        # does. The Shell 2017 wells (00269, 00271-4) print the SAME layout
        # with BLACK tick labels and a rotated title per axis, and there the
        # colour match is meaningless: every number on the page lands on
        # whichever coloured ink is nearest, which is the rotated title, so a
        # chart's three axes (Pressure 0..75, Rate 0..15, Conc 0..1000) all
        # arrive as one 'red' pile and RANSAC fits a line through the mixture.
        # That is where axes like [8.3, 9.4] and [-60, 90] came from. When the
        # axis titles are readable they say which column is which outright, so
        # take that reading in preference; require_titles keeps 00183 on the
        # colour-keyed path, where its titles do not exist.
        info = None
        try:
            samples, chans, info = _extract_new_chart(
                img, sample_sec, box=box, require_titles=True)
        except Exception:
            info = None
        titled = info is not None
        if not titled:
            try:
                # a label's colour is counted beside the label, not in the
                # plot it borders (00208 p24: see ar.ocr_tick_strip)
                samples, chans, info = ar.extract(img, sample_sec=sample_sec,
                                                  plot=box, glyphs=True,
                                                  edge_blank=True,
                                                  ticks_in_strip=True)
            except ValueError:
                continue
        info["geom"] = _page_geom(info, sx, sy)
        # These books print "Time (min)" and an info table where the newer
        # ones print the calendar span, so this finds nothing on 00183/4/5 —
        # but it costs one small OCR and it is what would read the span on a
        # tiled book that does print one. See _place_on_clock; a chart whose
        # axis is elapsed minutes cannot pass its agreement test.
        _place_on_clock(img, info)
        if titled:
            # names come from the axis titles plus NEW_SURFACE, which is the
            # colour table for exactly this chart style — the legend/position
            # reconciliation below is for the colour-keyed style only
            # NEW_SURFACE names the TREATMENT chart's colours; on the chemical
            # twin the rate axis is the clean rate and the concentrations are
            # additives, not proppant. See _name_chemical.
            tag, note = _bar_tag(tag, title, chans)
            if note:
                info.setdefault("notes", []).append(note)
            _name_chemical(tag, chans)
            out.append((tag, samples, chans, info))
            continue
        # An offset chart: its curves are neighbouring wells' casing
        # pressures, named only by its own legend (see _offset_legend). Its
        # title is the other charts' with "Offset" for "Treatment"; the OCR
        # does not always reach it (00248 p24 read the interval and legend
        # instead), so a title that names no analysis at all is asked too.
        offset = {}
        if _offset_title(title):
            offset = _offset_legend(img, box)
        if offset:
            kept = []
            for c in chans:
                fam = c["key"].replace("series-", "").rstrip("2")
                if fam in offset:
                    c["label"], c["unit"] = offset[fam]
                    m = re.fullmatch(r"([A-Z]) Well Casing Pressure", c["label"])
                    if m:
                        hx = ar.HUE_HEX.get(fam, "#000000")
                        c["offset"] = {"group": "casing",
                                       "rgb": [int(hx[i:i + 2], 16) for i in (1, 3, 5)],
                                       "votes": [m.group(1)]}
                    kept.append(c)
            # a colour the legend does not name is not a curve of this chart
            # (orange here is the brown of the title); a black well has no
            # colour to trace and is not read
            if kept:
                out.append((tag, samples, kept, info))
            continue
        # The legend states the colour -> series pairing; SERIES_NAMES only
        # guesses it from (chart position, colour). Measured on real wells the
        # guess is sometimes flatly wrong: 00184/00185 put a SECOND TREATMENT
        # chart where the chemical one usually sits, so its Surface Pressure
        # (cyan there, red on the first chart) was being exported as
        # "Combined Clean Rate" and its Slurry Rate as "SSI-3 Conc".
        legend = {}
        try:
            legend = ar.read_legend(img, box)
        except Exception:
            legend = {}
        # A chemical chart in this report family reprints the TREATMENT
        # chart's legend wholesale — "Surface Pressure (MPa)" over a 0..10 axis
        # whose curve peaks at 6 while the real surface pressure peaks at 58.
        # Trusting it exported a slurry rate of 1683 m3/min. One treatment-only
        # name is enough to condemn the whole block: it is the wrong legend,
        # not a wrong entry, and its remaining names (a "Slurry Rate" sitting
        # on a 0..2000 axis) are no more trustworthy. A genuine chemical legend
        # carries none of these names, so it survives intact.
        if is_chem and any(v[0] in ar.TREATMENT_ONLY for v in legend.values()):
            legend = {}
        # A legend name that contradicts the table proves the table's
        # (tag, colour) assumption does not hold for THIS chart, so its other
        # guesses are not trustworthy either — leave those channels unnamed
        # rather than stamping a confident wrong name onto a column.
        def _same(a, b):
            # compare through the alias table: the legend prints "Combined
            # Slurry Rate" where the table says "Slurry Rate", and those are
            # one channel, not a contradiction
            if a.lower() == b.lower():
                return True
            # ...and 00208's chemical legend reads "CLEAN RATE" on stages
            # 1-18 and "COMBINED CLEAN RATE" from 19 on, the same cyan pen.
            # Taken for a contradiction, it left the other three curves of
            # those charts "Series (red)", "(green)", "(magenta)".
            strip = lambda s: re.sub(r"^combined\s+", "", s.strip().lower())
            if strip(a) == strip(b):
                return True
            ca, cb = aliases.canon(a), aliases.canon(b)
            return bool(ca) and ca == cb
        fams = {c["key"].replace("series-", "").rstrip("2") for c in chans}
        contradicted = any(
            fam in fams and (tag, fam) in SERIES_NAMES
            and not _same(SERIES_NAMES[(tag, fam)][0], nm)
            for fam, (nm, _u) in legend.items())
        # The 2017 dual-fuel book 00185 prints a FLEET chart ("DGB
        # Analysis": surface pressure in red, pump units running, fleet fuel
        # rate, load and diesel substitution) and an offset chart whose well
        # legend the offset reader does not parse. No legend name matches, so
        # the colour tables named the fleet's substitution % — and a well's
        # casing pressure — Prop Conc, and the fleet's curves after chemical
        # additives, filed under the stage beside its real ones. Only the
        # red, as both legends say, keeps a treatment name.
        # A chart titled "DGB Analysis" has its legend band read whatever its
        # legend matched: 00185 p39's matched one fleet curve as "Btm Prop
        # Conc". The title alone does not say which it is — the same book
        # reprints chemical charts under that bar (p33, p73) — the band does.
        other = (_other_legend(img, box)
                 if re.search(r"\bdgb\b", title)
                 or (not legend and not is_chem and "treatment analysis" not in title)
                 else "")
        if other == "chemical":
            # 00185 p33 and p45 print the stage's chemical chart under the
            # "Offset Analysis" bar, in the treatment chart's place; its
            # legend names additives in L/m3 and the clean rate. Read as the
            # chemical chart it is, by the chemical colour table.
            tag = "c"
            for c in chans:
                fam = c["key"].replace("series-", "").rstrip("2")
                name, unit = SERIES_NAMES.get(("c", fam), (c["label"], c["unit"]))
                c["label"], c["unit"] = name, unit
            _name_chemical(tag, chans)
            info.setdefault("notes", []).append(
                "a chemical chart in the treatment chart's place: its legend "
                "names additives, and its curves are named by the chemical table")
            out.append((tag, samples, chans, info))
            continue
        if other in ("fleet", "wells"):
            # In the chemical chart's place, not even the red: a treatment
            # channel there makes the fleet chart the stage's "treatment"
            # sibling, and _drop_chemical_only then set the real chemical
            # chart aside (00185: 19 of them).
            for c in chans:
                if tag == "t" and c["key"].replace("series-", "").rstrip("2") == "red":
                    c["label"], c["unit"] = "Surface Pressure", "MPa"
            info.setdefault("notes", []).append(
                ("a fleet chart (pump units, fuel rate, substitution)" if other == "fleet"
                 else "an offset chart whose legend did not read")
                + ": its curves other than the surface pressure are not "
                  "treatment channels and keep their colour names")
            out.append((tag, samples, chans, info))
            continue
        for c in chans:
            fam = c["key"].replace("series-", "").rstrip("2")
            if fam in legend and legend[fam][0]:
                c["label"] = legend[fam][0]
                c["unit"] = _legend_unit_for(legend[fam][0], legend[fam][1]) or c["unit"]
                continue
            if contradicted:
                continue                      # keep the neutral "Series (x)"
            name, unit = SERIES_NAMES.get((tag, fam), (c["label"], c["unit"]))
            c["label"] = name
            c["unit"] = unit
        out.append((tag, samples, chans, info))

    if not out and not flat_first and not page.get_text().strip():
        flat = _extract_flattened(page, img, sample_sec)
        if flat is not None:
            return flat
    meta = page_meta(img)
    if meta.get("stage") is None and boxes:
        _stage_titled_meta(img, boxes[0], meta)
    if not out and _side_by_side(img) >= 2:
        meta.setdefault("skipped", []).append(
            "charts printed side by side, two or three to a row at a third of "
            "the page's width (a stage pumped in several attempts) — their axis "
            "and time labels are three or four pixels a character and do not "
            "read, so the page was not read")
    elif (not out and not boxes and (meta.get("stage") is not None or meta.get("interval"))
            and _blank_body(img)):
        # 00270 p30-p31: Treatment 7's pages print the title, the interval
        # and the info table round chart areas left blank. Nothing to read,
        # but the stage is then missing from the file, so say where.
        meta.setdefault("skipped", []).append(
            "a stage's chart page with its chart areas printed blank — "
            "nothing is drawn on it to read")
    # page_meta decides main-vs-casing by OCR'ing the header BAND, which on
    # these reports reads "STEP Energy Services Interval Summary ..." and
    # contains neither "Prop Conc" nor "Surface Pressure" — so every page fell
    # through to "casing" and the pipeline, which only emits "main", produced
    # nothing for the whole file. The chart's own title is the reliable signal
    # (v0.7.10 reads it for the treatment/chemical split already), so let it
    # correct the verdict when it recognises the analysis type.
    joined = " ".join(seen_titles)
    # Only a treatment chart promotes the page. An "offset analysis" is a
    # neighbouring well's chart and would invent stages that are not this
    # well's; a page carrying both still promotes on the treatment one.
    if "treatment analysis" in joined:
        meta["kind"] = "main"
    elif "casing" in joined:
        meta["kind"] = "casing"
    return meta, _drop_impossible_axes(_fix_decimal_slip(out))
