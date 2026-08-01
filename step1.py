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


def _detect_new(page):
    t = page.get_text()
    if "LSD:" not in t or ("Surface Chart" not in t and "Interval" not in t):
        return False
    big = [im for im in page.get_images(full=True)
           if im[2] >= 500 and im[3] >= 300]
    return len(big) >= 1


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
NEW_SURFACE = {"red": ("Surface Pressure", "MPa", "pressure"),
               "blue": ("Slurry Rate", "m3/min", "rate"),
               "cyan": ("Slurry Rate", "m3/min", "rate"),
               "green": ("Prop Conc", "kg/m3", "conc"),
               "orange": ("Btm Prop Conc", "kg/m3", "conc")}


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
        from PIL import Image as _Im
        strip = rows[:, max(0, xa):xb]
        if strip.size == 0:
            return []
        pil = _Im.fromarray(strip.astype(np.uint8))
        pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
        words = ar.ocr_words(np.array(pil).astype(int), psm=6,
                             whitelist="0123456789.-")
        out = []
        import re as _re
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
            cols.append(("conc" if top >= 50 else "rate", seg))
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
    if len(ltitles) >= 2:
        edges = [t[1] for t in ltitles] + [x0]
        lsegs = [(q, strip_ticks(tx + 4, edges[i + 1] - 4))
                 for i, (q, tx) in enumerate(ltitles)]
        lsegs = [(q, s) for q, s in lsegs if s]
    else:
        lsegs = [(ltitles[0][0] if ltitles else "pressure",
                  strip_ticks(0, x0))]

    fits = {}

    def _use(qty, seg, only_if_free=False):
        # fit each axis on its own ticks: an offset chart prints two right-hand
        # PRESSURE axes, and one fit over both columns' numbers is meaningless
        if only_if_free and qty in fits:
            return
        cal = ar.fit_ticks_guarded(seg) if seg else None
        if cal and (fits.get(qty) is None or cal[2] > fits[qty][2]):
            fits[qty] = cal

    for qty, seg in cols:
        _use(qty, seg)
    for qty, seg in lsegs[:-1]:
        # an outer left axis is an auxiliary channel ("TP Rate" in L/min, not
        # the slurry rate in m3/min) — it only fills a quantity nothing else has
        _use(qty, seg, only_if_free=True)
    # The axis nearest the plot on the left is the chart's principal one and
    # wins its quantity outright. An offset chart carries THREE pressure axes
    # (0..80 main, 0..40 offset wells, 0..4 abandoned wells) and taking
    # whichever fitted best put Surface Pressure on the offset scale.
    lqty, lseg = lsegs[-1]
    lcal = ar.fit_ticks_guarded(lseg) if lseg else None
    if lcal is None and len(lsegs) > 1:
        # a stacked left column is only ~50px wide and tesseract sometimes
        # reads nothing from it; the whole strip still fits, so use that
        lcal = ar.fit_ticks_guarded(strip_ticks(0, x0))
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
        py = ar.curve_positions(sub) + y0
        # same round-bound snap as the tiled path (see auto_raster.snap_axis):
        # applied before values are read so it reaches the exported numbers
        _vt, _vb, _sn = ar.snap_axis(a + b * y0, a + b * y1)
        if _sn and abs(y1 - y0) > 1:
            b = (_vb - _vt) / float(y1 - y0)
            a = _vt - b * y0
        vals = a + b * py
        t_cols = (ta + tb * (np.arange(n_cols) + x0)) - t_start
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
    import re
    doc = page.parent
    text = page.get_text()
    meta = {"stage": None, "interval": "", "kind": "main"}
    # These pages number the stage as "Treatment N"; only some spell it
    # "Interval N". Looking for Interval alone left every page of a file with
    # stage None, so they all grouped under one nameless stage and the Lab
    # showed a single "Stage ?". This is the page's real text layer, not OCR.
    m = (re.search(r"Interval\s+(\d+)", text)
         or re.search(r"Treatment\s+(\d+)", text))
    if m:
        meta["stage"] = int(m.group(1))
    m = re.search(r"([\d,]+\.\d+)\s*m\s*-\s*([\d,]+\.\d+)\s*m", text)
    if m:
        meta["interval"] = f"{m.group(1)}-{m.group(2)} m"
    ims = [im for im in page.get_images(full=True)
           if im[2] >= 500 and im[3] >= 300]
    ims.sort(key=lambda im: page.get_image_rects(im[0])[0].y0)
    out = []
    done = set()
    for i, im in enumerate(ims):
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
        try:
            r = page.get_image_rects(im[0])[0]
            if r.width > 1 and r.height > 1:
                info["geom"] = _page_geom(info, pix.width / r.width,
                                          pix.height / r.height, r.x0, r.y0)
        except Exception:
            pass
        out.append((tag, samples, chans, info))
    return meta, out


def _is_pressure(c):
    if (c.get("unit") or "").lower() in ("mpa", "kpa", "psi"):
        return True
    return "pressure" in (c.get("label") or "").lower()


def _drop_impossible_pressure(charts):
    """Refuse to export a pressure channel read off an axis that cannot be a
    pressure axis. See auto_raster.plausible_pressure_axis — a wrong number
    here is invisible downstream, a missing channel is not."""
    out = []
    for tag, samples, chans, info in charts:
        keep = []
        for c in chans:
            fr = c.get("axis_frame")
            if fr and _is_pressure(c) and not ar.plausible_pressure_axis(*fr):
                info.setdefault("notes", []).append(
                    f"{c.get('label')}: axis ({fr[0]:.2f}, {fr[1]:.2f}) is "
                    "not a possible pressure scale — channel dropped")
                continue
            keep.append(c)
        if keep:
            out.append((tag, samples, keep, info))
    return out


def extract_page(page, sample_sec=1.0):
    """-> (meta, [(chart_tag, samples, channels, info), ...])."""
    if not _detect_tiled(page) and _detect_new(page):
        meta, out = _extract_new(page, sample_sec)
        return meta, _drop_impossible_pressure(out)
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
                                                  plot=box)
            except ValueError:
                continue
        info["geom"] = _page_geom(info, sx, sy)
        if titled:
            # names come from the axis titles plus NEW_SURFACE, which is the
            # colour table for exactly this chart style — the legend/position
            # reconciliation below is for the colour-keyed style only
            for c in chans:
                # NEW_SURFACE names the TREATMENT chart's colours. On the
                # chemical twin the rate axis is the clean rate, and exporting
                # it as "Slurry Rate" would put two different channels of that
                # name on one stage.
                if tag == "c" and c["label"] == "Slurry Rate":
                    c["label"] = "Combined Clean Rate"
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
    return meta, _drop_impossible_pressure(out)
