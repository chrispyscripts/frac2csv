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
    widths = set()
    for im in ims:
        rects = page.get_image_rects(im[0])
        if not rects:
            return False
        widths.add(round(rects[0].width))
    return len(widths) == 1 and widths.pop() > page.rect.width * 0.9


def _page_text(page):
    """Page text with the separators these filings actually use.

    STEP's own generator sets every space in its captions as a NO-BREAK SPACE
    (U+00A0) and every hyphen as a non-breaking hyphen (U+2011), so a literal
    "Surface Treatment Plot" never matches the text layer. Normalise once,
    here, rather than in each caller."""
    return (page.get_text().replace(" ", " ").replace("‑", "-")
            .replace("‐", "-"))


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
        rects = page.get_image_rects(im[0])
        if rects:
            out.append((rects[0].y0, im))
    out.sort(key=lambda p: p[0])
    return [im for _y, im in out]


def composite(page):
    """Stack the page's image tiles top-to-bottom at native resolution."""
    doc = page.parent
    ims = sorted(page.get_images(full=True),
                 key=lambda im: page.get_image_rects(im[0])[0].y0)
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


def _runs(col, minlen):
    out, start = [], None
    for y, v in enumerate(col):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= minlen:
                out.append((start, y))
            start = None
    if start is not None and len(col) - start >= minlen:
        out.append((start, len(col)))
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
    out.sort(key=lambda b: b[1])
    return out


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
    if "Prop Conc" not in text and "Casing" in text.replace("Cacinn", "Casing"):
        meta["kind"] = "casing"
    elif "Prop Conc" not in text:
        # garbled OCR on the casing twin is common; main pages OCR cleanly
        meta["kind"] = "casing" if "Surface Pressure" not in text else "main"
    return meta


def _frame_bbox(img):
    """Plot box = bounding box of long strict-dark line runs (frame and
    gridlines are black in the new format)."""
    H, W = img.shape[:2]
    dark = img.sum(axis=2) < 400
    col_ok = np.where(dark.sum(axis=0) > H * 0.6)[0]
    row_ok = np.where(dark.sum(axis=1) > W * 0.6)[0]
    if not len(col_ok) or not len(row_ok):
        return None
    return int(col_ok[0]), int(row_ok[0]), int(col_ok[-1]), int(row_ok[-1])


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

NEW_SURFACE = {"red": ("Surface Pressure", "MPa", "pressure"),
               "blue": ("Slurry Rate", "m3/min", "rate"),
               "cyan": ("Slurry Rate", "m3/min", "rate"),
               "green": ("Prop Conc", "kg/m3", "conc"),
               "orange": ("Btm Prop Conc", "kg/m3", "conc")}


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

    def strip_ticks(xa, xb):
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
        from PIL import Image as _Im
        strip = rows[:, max(0, xa):xb]
        if strip.size == 0:
            return []
        pil = _Im.fromarray(strip.astype(np.uint8))
        pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
        arr = np.array(pil).astype(int)
        out = []
        import re as _re
        for psm in (6, 11):
            try:
                words = ar.ocr_words(arr, psm=psm, whitelist="0123456789.-")
            except Exception:
                continue
            for text, cx, cy in words:
                t = text.replace(",", "").strip("-.")
                if _re.fullmatch(r"\d+(\.\d+)?", t):
                    out.append((float(t), int(cx / 3) + max(0, xa),
                                int(cy / 3) + ry0))
        return [(v, y, True) for v, x, y in
                ((v, x, y) for v, x, y in out) if y0 - 25 <= y <= y1 + 25]

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
    cols = []                       # [(quantity, ticks)], one entry per axis
    if rtitles:
        lo = x1 + 3
        for qty, tx in rtitles:
            if tx - 4 > lo:
                cols.append((qty, strip_ticks(lo, tx - 4)))
            lo = tx + 4
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
            top = max(abs(cal[0] + cal[1] * y0), abs(cal[0] + cal[1] * y1))
            if top >= RATE_AXIS_MAX:
                return
        if cal and (fits.get(qty) is None or cal[2] > fits[qty][2]):
            fits[qty] = cal

    for qty, seg in cols:
        _use(qty, seg)
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
        if whole is None:
            lcal = None
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
            lcal = min(cands, key=_rank) if cands else whole
    if lcal:
        fits[lqty] = lcal

    masks = ar.hue_masks(img)
    samples = np.arange(int(n / sample_sec)) * sample_sec
    channels = []
    seen = set()
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
        a, b, ntick = cal
        sub = mask[y0:y1, x0:x1]
        cov = float(sub.any(axis=0).mean())
        if cov < 0.1:
            continue
        n_cols = sub.shape[1]
        # glyphs=True: these reports print the FracPro logo inside the frame,
        # in the series' own inks. See auto_raster.drop_glyph_islands.
        py = ar.curve_positions(sub, glyphs=True)
        cx, py = _keep_excursions(sub, py)
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
        channels.append({"key": f"series-{fam}", "label": name, "unit": unit,
                         "color": ar.HUE_HEX.get(base, "#555577"),
                         "values": v, "ticks": ntick, "coverage": cov,
                         # axis read at the frame edges — see auto_raster
                         "axis_frame": (float(a + b * y0), float(a + b * y1))})
        seen.add(name)
    if not channels:
        raise ValueError("step1: no channel calibrated")
    info = {"plot": box, "t0_seconds": float(t_start),
            "duration_s": int(n), "notes": []}
    return samples, channels, info


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


def _keep_excursions(sub, py, min_px=6, factor=3.0, split=0.25):
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


def _extract_new(page, sample_sec=1.0):
    doc = page.parent
    text = page.get_text()
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
    m = re.search(r"Interval\s+(\d+)(?:\.(\d+))?", text)
    if m:
        meta["stage"] = (int(m.group(1)) if m.group(2) is None
                         else f"{int(m.group(1))}.{m.group(2)}")
    else:
        m = re.search(r"Treatment\s+(\d+)", text)
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
        tag = "t" if not out else "c"
        try:
            samples, chans, info = _extract_new_chart(img, sample_sec)
        except ValueError:
            continue
        _name_chemical(tag, chans)
        try:
            r = page.get_image_rects(im[0])[0]
            if r.width > 1 and r.height > 1:
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
        if not ar.plausible_pressure_axis(*fr):
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


def extract_page(page, sample_sec=1.0):
    """-> (meta, [(chart_tag, samples, channels, info), ...])."""
    if not _detect_tiled(page) and _detect_new(page):
        meta, out = _extract_new(page, sample_sec)
        return meta, _drop_impossible_axes(_fix_decimal_slip(out))
    img = composite(page)
    # the stacked tiles span the whole page, so one scale converts back
    pr = page.rect
    sx = img.shape[1] / pr.width if pr.width else 0
    sy = img.shape[0] / pr.height if pr.height else 0
    out = []
    seen_titles = []
    for i, box in enumerate(find_charts(img)):
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
                samples, chans, info = ar.extract(img, sample_sec=sample_sec,
                                                  plot=box, glyphs=True)
            except ValueError:
                continue
        info["geom"] = _page_geom(info, sx, sy)
        if titled:
            # names come from the axis titles plus NEW_SURFACE, which is the
            # colour table for exactly this chart style — the legend/position
            # reconciliation below is for the colour-keyed style only
            # NEW_SURFACE names the TREATMENT chart's colours; on the chemical
            # twin the rate axis is the clean rate and the concentrations are
            # additives, not proppant. See _name_chemical.
            _name_chemical(tag, chans)
            out.append((tag, samples, chans, info))
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
            ca, cb = aliases.canon(a), aliases.canon(b)
            return bool(ca) and ca == cb
        fams = {c["key"].replace("series-", "").rstrip("2") for c in chans}
        contradicted = any(
            fam in fams and (tag, fam) in SERIES_NAMES
            and not _same(SERIES_NAMES[(tag, fam)][0], nm)
            for fam, (nm, _u) in legend.items())
        for c in chans:
            fam = c["key"].replace("series-", "").rstrip("2")
            if fam in legend and legend[fam][0]:
                c["label"] = legend[fam][0]
                c["unit"] = legend[fam][1] or c["unit"]
                continue
            if contradicted:
                continue                      # keep the neutral "Series (x)"
            name, unit = SERIES_NAMES.get((tag, fam), (c["label"], c["unit"]))
            c["label"] = name
            c["unit"] = unit
        out.append((tag, samples, chans, info))

    meta = page_meta(img)
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
