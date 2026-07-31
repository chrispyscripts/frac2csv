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

    out = []
    for g in groups:
        x0, x1 = min(g["xs"]), max(g["xs"])
        if x1 - x0 < W * 0.3:
            continue                      # too narrow to be a plot
        out.append((x0, g["y0"], x1, g["y1"]))
    out.sort(key=lambda b: b[1])
    return out


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


NEW_SURFACE = {"red": ("Surface Pressure", "MPa", "left"),
               "blue": ("Slurry Rate", "m3/min", "right1"),
               "cyan": ("Slurry Rate", "m3/min", "right1"),
               "green": ("Prop Conc", "kg/m3", "right2"),
               "orange": ("Btm Prop Conc", "kg/m3", "right2")}


def _extract_new_chart(img, sample_sec=1.0):
    """New-format chart image: black tick labels on fixed axes —
    left=Pressure(red), right1=Rate(blue), right2=Concentration."""
    img = np.asarray(img).astype(int)
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

    def strip_ticks(xa, xb):
        from PIL import Image as _Im
        strip = img[:, max(0, xa):xb]
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
                out.append((float(t), int(cx / 3) + max(0, xa), int(cy / 3)))
        return [(v, y, True) for v, x, y in
                ((v, x, y) for v, x, y in out) if y0 - 25 <= y <= y1 + 25]

    W = img.shape[1]
    left = strip_ticks(0, x0)
    right = []
    from collections import defaultdict as _dd
    # right side: split labels into columns by x gap
    from PIL import Image as _Im
    strip = img[:, x1 + 3:W]
    cols = _dd(list)
    if strip.size:
        pil = _Im.fromarray(strip.astype(np.uint8))
        pil = pil.resize((pil.width * 3, pil.height * 3), _Im.LANCZOS)
        words = ar.ocr_words(np.array(pil).astype(int), psm=6,
                             whitelist="0123456789.-")
        import re as _re
        pts = []
        for text, cx, cy in words:
            t = text.replace(",", "").strip("-.")
            if _re.fullmatch(r"\d+(\.\d+)?", t):
                px, py = int(cx / 3) + x1 + 3, int(cy / 3)
                if y0 - 25 <= py <= y1 + 25:
                    pts.append((float(t), px, py))
        if pts:
            xs = sorted(p[1] for p in pts)
            gaps = [(b - a, a, b) for a, b in zip(xs, xs[1:]) if b - a > 40]
            split = (gaps[0][1] + gaps[0][2]) / 2 if gaps else max(xs) + 1
            for v, px, py in pts:
                cols["right1" if px <= split else "right2"].append(
                    (v, py, True))
    fits = {"left": ar.fit_ticks_guarded(left)}
    for k in ("right1", "right2"):
        fits[k] = ar.fit_ticks_guarded(cols.get(k, []))

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
        cal = fits.get(axis)
        if cal is None:
            continue
        a, b, ntick = cal
        sub = mask[y0:y1, x0:x1]
        cov = float(sub.any(axis=0).mean())
        if cov < 0.1:
            continue
        n_cols = sub.shape[1]
        py = np.full(n_cols, np.nan)
        for cx in range(n_cols):
            ys_ = np.where(sub[:, cx])[0]
            if len(ys_):
                py[cx] = np.median(ys_) + y0
        # same round-bound snap as the tiled path (see auto_raster.snap_axis):
        # applied before values are read so it reaches the exported numbers
        _vt, _vb, _sn = ar.snap_axis(a + b * y0, a + b * y1)
        if _sn and abs(y1 - y0) > 1:
            b = (_vb - _vt) / float(y1 - y0)
            a = _vt - b * y0
        vals = a + b * py
        t_cols = (ta + tb * (np.arange(n_cols) + x0)) - t_start
        ok = ~np.isnan(vals)
        if ok.sum() < 50:
            continue
        v = np.interp(samples, t_cols[ok], vals[ok])
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


def extract_page(page, sample_sec=1.0):
    """-> (meta, [(chart_tag, samples, channels, info), ...])."""
    if not _detect_tiled(page) and _detect_new(page):
        return _extract_new(page, sample_sec)
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
        try:
            samples, chans, info = ar.extract(img, sample_sec=sample_sec,
                                              plot=box)
        except ValueError:
            continue
        info["geom"] = _page_geom(info, sx, sy)
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
    return meta, out
