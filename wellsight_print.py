"""A WellSight LogViewer printout -> one long strip, depth running down.

LogViewer prints a log over Letter pages: header and legend pages first, then
the log, running on from page to page ("Page Breaks" off, the default), with
the depth labels printed every few metres. A horizontal log prints sideways,
depth across the page. To stack the printout against the LAS export, depth
has to run down one continuous page at one scale, starting at the log top.

stitch() does that from the printout itself:
  - every page that carries depth labels is mapped coordinate -> depth by a
    straight-line fit through its labels (the log's own top and bottom keep
    out the cross-section's TVD scale and the header's numbers);
  - pages run on: one page's bottom edge is the next page's top edge to
    0.01 m on every printout tried, so a page with too few labels of its own
    -- the legend page the log starts on, the last page the log ends on --
    takes its depths from the page beside it;
  - each page's slice of the log is cut out and placed at its depth on one
    page, turned so depth runs down. Header and legend pages are left out.

The strip is vector: show_pdf_page carries the drawing over, so curves stay
lines and text stays text. The scale is the printout's own (11.81 pt per
metre at 1:240).

The strip keeps every track LogViewer printed, and curve_track() finds the
one the LAS curves are drawn in, so a view can show that compartment alone:
the reference for the curves, without the descriptions, lithology and
cross-section beside it.

Needs PyMuPDF.
"""
import bisect
import collections
import math
import re

import fitz

NUM = re.compile(r"\d{2,5}(\.0)?")
PAGE_MAX = 14400.0      # PDF viewers' page-size limit (200 in), in points


class NoDepthScale(Exception):
    pass


def _labels(pg, lo, hi):
    out = []
    for w in pg.get_text("words"):
        if NUM.fullmatch(w[4]):
            v = float(w[4])
            if lo <= v <= hi:
                out.append((v, (w[0] + w[2]) / 2, (w[1] + w[3]) / 2))
    return out


def _fit(pts):
    n = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts); sxy = sum(p[0] * p[1] for p in pts)
    den = n * sxx - sx * sx
    if not den:
        return None
    a = (n * sxy - sx * sy) / den
    b = (sy - a * sx) / n
    return a, b


TOL_M = 0.25        # a label within this of the line is on it


def _robust(pts):
    """The line most of the labels sit on, and those labels. Each round
    fifty-metre label (1100, 1150, ...) on some logs prints 9 pt off its
    gridline -- 0.75 m at 1:240 -- so one least-squares fit through all of
    them misses everything by a little. Every pair of labels proposes a line;
    the one most labels agree with wins, refitted through those."""
    best = None
    m = len(pts)
    for i in range(m):
        for j in range(i + 1, m):
            (x1, d1), (x2, d2) = pts[i], pts[j]
            if x1 == x2 or d1 == d2:
                continue
            a = (d2 - d1) / (x2 - x1)
            b = d1 - a * x1
            on = [p for p in pts if abs(a * p[0] + b - p[1]) < TOL_M]
            if best is None or len(on) > len(best):
                best = on
    if not best or len(best) < 3 or len({p[1] for p in best}) < 3:
        return None
    f = _fit(best)
    if not f or f[0] == 0:
        return None
    a, b = f
    on = [p for p in pts if abs(a * p[0] + b - p[1]) < TOL_M]
    if len(on) < 3:
        return None
    return a, b, on


def page_lines(pg, lo, hi):
    """Every straight row or column of depth-range numbers on the page:
    [(axis, key, a, b, on)], depth = a * coord + b, coord = x (axis 1) or
    y (axis 2), key = the row's y or the column's x, on = [(coord, depth)]."""
    labels = _labels(pg, lo, hi)
    out = []
    if len(labels) < 3:
        return out
    for axis in (1, 2):
        lines = collections.Counter(round(l[3 - axis]) for l in labels)
        for other, _n in lines.most_common(6):
            pts = [(l[axis], l[0]) for l in labels if abs(l[3 - axis] - other) < 2]
            if len(pts) < 3:
                continue
            r = _robust(pts)
            if r:
                out.append((axis, other, r[0], r[1], r[2]))
    return out


def page_axis(pg, lo, hi):
    """The page's depth line on its own: of its rows and columns of numbers,
    the one whose labels cover the most depth (the cross-section's TVD scale
    on a horizontal log can fall inside the log's MD range and hold as many
    labels, but covers twenty metres where the depth track covers the page).
    -> (axis, a, b, on) or None. stitch() chooses across all the pages."""
    best = None
    for axis, key, a, b, on in page_lines(pg, lo, hi):
        span = max(p[1] for p in on) - min(p[1] for p in on)
        k = (round(span, 1), len(on))
        if best is None or k > best[0]:
            best = (k, axis, a, b, on)
    return None if best is None else best[1:]


def _edges(pg, axis):
    r = pg.rect
    return (r.x0, r.x1) if axis == 1 else (r.y0, r.y1)


def _median(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def stitch(pdf, top, bottom):
    """pdf: bytes or a path. -> (strip_pdf_bytes, info). Raises NoDepthScale
    when no page carries the log's depth labels."""
    doc = fitz.open(stream=pdf, filetype="pdf") if isinstance(pdf, (bytes, bytearray)) \
        else fitz.open(pdf)
    top, bottom = float(top), float(bottom)
    cands = {}                         # page -> its rows/columns of numbers
    for pno, pg in enumerate(doc):
        ls = page_lines(pg, top - 1, bottom + 1)
        if ls:
            cands[pno] = ls
    if not cands:
        raise NoDepthScale("no page of the printout carries this log's depth labels "
                           f"({top:g}-{bottom:g} m); is it the printout of this file?")
    # Which way depth runs on the page, and at what scale: each page's
    # widest-spanning line votes. LogViewer prints at one scale throughout.
    votes = {}
    for pno, ls in cands.items():
        axis_, _k, a_, _b, on = max(ls, key=lambda l: (max(p[1] for p in l[4]) - min(p[1] for p in l[4]), len(l[4])))
        votes[pno] = (axis_, a_)
    axis = collections.Counter(v[0] for v in votes.values()).most_common(1)[0][0]
    a = _median([v[1] for v in votes.values() if v[0] == axis])
    ppm = 1.0 / abs(a)

    # The depth track. A log can print more than one column of depths (a
    # second depth track by the gamma, a TVD column on a build log), and they
    # are not all placed alike: on 00 8248 one column sits on the gridlines
    # and the other 9 pt off them, unevenly. Pages that switch between them
    # leave 0.75 m steps. So one column is chosen for the whole printout: the
    # one whose labels sit most exactly on a line of the common scale, over
    # all the pages.
    TIGHT = 0.08

    def gridlines(pg):
        """coordinates of the lines drawn across the depth axis"""
        out = []
        for d in pg.get_drawings():
            for it in d["items"]:
                if it[0] != "l":
                    continue
                p0, q0 = it[1], it[2]
                if axis == 2 and abs(p0.y - q0.y) < 0.05 and abs(p0.x - q0.x) > 30:
                    out.append(p0.y)
                if axis == 1 and abs(p0.x - q0.x) < 0.05 and abs(p0.y - q0.y) > 30:
                    out.append(p0.x)
        return sorted(out)

    def off_grid(lines, c):
        if not lines:
            return None
        i = bisect.bisect_left(lines, c)
        return min(abs(lines[j] - c) for j in (i - 1, i) if 0 <= j < len(lines))

    # key -> [tight labels, pages, distances from the gridlines]
    score = collections.defaultdict(lambda: [0, 0, []])
    for pno, ls in cands.items():
        lines = None
        for axis_, key, _a, _b, on in ls:
            if axis_ != axis or abs(_a - a) > 0.02 * abs(a):
                continue
            if lines is None:
                lines = gridlines(doc[pno])
            b = _median([d - a * c for c, d in on])
            tight = [c for c, d in on if abs(a * c + b - d) < TIGHT]
            k = round(key / 3.0)                         # same column, page to page
            score[k][0] += len(tight)
            score[k][1] += 1
            score[k][2] += [g for g in (off_grid(lines, c) for c in tight) if g is not None]
    if not score:
        raise NoDepthScale("the printout's depth labels do not agree on one scale")
    # The depth track prints its labels on its gridlines; a second column of
    # depths can be just as straight and sit a constant 9 pt off them. Of the
    # columns with a fair share of the labels, the one on the lines wins.
    most = max(v[0] for v in score.values())
    fair = [k for k, v in score.items() if v[0] >= 0.5 * most]

    def grid_miss(k):
        g = score[k][2]
        return _median(g) if g else 99.0
    col = min(fair, key=lambda k: (round(grid_miss(k), 1), -score[k][0]))
    maps, found = {}, {}
    for pno, ls in cands.items():
        mine = [l for l in ls if l[0] == axis and round(l[1] / 3.0) == col]
        if not mine:
            continue
        on = mine[0][4]
        b = _median([d - a * c for c, d in on])
        on2 = [(c, d) for c, d in on if abs(a * c + b - d) < TIGHT] or on
        b = _median([d - a * c for c, d in on2])
        if len(on2) >= 2:
            maps[pno] = (a, b)
            found[pno] = (axis, a, b, on2)
    if not maps:
        raise NoDepthScale("the printout's depth labels do not agree on one scale")

    def start_end(p):
        """depths where page p's log begins and ends (its two edges, in
        print order)."""
        aa, bb = maps[p]
        e0, e1 = _edges(doc[p], axis)
        d0, d1 = aa * e0 + bb, aa * e1 + bb
        return (d0, d1) if d0 <= d1 else (d1, d0)

    def map_after(q, d_start):
        """page q starts where the page before it ended."""
        f0, f1 = _edges(doc[q], axis)
        maps[q] = (a, d_start - a * (f0 if a > 0 else f1))

    def map_before(q, d_end):
        """page q ends where the page after it begins."""
        f0, f1 = _edges(doc[q], axis)
        maps[q] = (a, d_end - a * (f1 if a > 0 else f0))

    inferred = []
    # Pages run on from one to the next, so a page with too few labels of its
    # own -- the legend page the log starts on, a page whose labels are
    # pictures, the last page -- takes its depths from the page before it
    # (or, ahead of the first labelled page, the page after it).
    first = min(maps)
    p = first
    while p - 1 >= 0 and p - 1 not in maps and start_end(p)[0] > top + 0.01:
        map_before(p - 1, start_end(p)[0])
        inferred.append(p - 1)
        p -= 1
    for q in range(first + 1, len(doc)):
        if q in maps:
            continue
        if q - 1 in maps and start_end(q - 1)[1] < bottom - 0.01:
            map_after(q, start_end(q - 1)[1])
            inferred.append(q)

    # across the depth axis: the log's width, from what the depth pages draw
    # (a straight line's box has no area, so boxes are clipped by hand)
    lo_c, hi_c = None, None
    for p in found:
        pg = doc[p]
        P = pg.rect
        boxes = [d["rect"] for d in pg.get_drawings()] + \
            [fitz.Rect(w[:4]) for w in pg.get_text("words")]
        for r in boxes:
            x0, y0 = max(r.x0, P.x0), max(r.y0, P.y0)
            x1, y1 = min(r.x1, P.x1), min(r.y1, P.y1)
            if x0 > x1 or y0 > y1:
                continue
            c0, c1 = (y0, y1) if axis == 1 else (x0, x1)
            lo_c = c0 if lo_c is None else min(lo_c, c0)
            hi_c = c1 if hi_c is None else max(hi_c, c1)
    if lo_c is None or hi_c - lo_c < 10:
        e0, e1 = (P.y0, P.y1) if axis == 1 else (P.x0, P.x1)
        lo_c, hi_c = e0, e1
    width = hi_c - lo_c
    height = (bottom - top) * ppm

    out = fitz.open()
    op = out.new_page(width=width, height=height)
    done_to = top
    placed, gaps, seams = [], [], []
    for p in sorted(maps):
        aa, bb = maps[p]
        d0e, d1e = start_end(p)
        if placed:
            seams.append(round(d0e - done_to, 3))     # + gap, - overlap
        d0, d1 = max(d0e, done_to, top), min(d1e, bottom)
        if d1 - d0 < 0.005:
            continue
        if d0 - done_to > 0.1:
            gaps.append((round(done_to, 2), round(d0, 2)))
        k0, k1 = sorted(((d0 - bb) / aa, (d1 - bb) / aa))
        tgt = fitz.Rect(0, (d0 - top) * ppm, width, (d1 - top) * ppm)
        if axis == 2:
            clip = fitz.Rect(lo_c, k0, hi_c, k1)
            rot = 0 if aa > 0 else 180
        else:
            clip = fitz.Rect(k0, lo_c, k1, hi_c)
            rot = -90 if aa > 0 else 90
        op.show_pdf_page(tgt, doc, p, clip=clip, rotate=rot, keep_proportion=False)
        placed.append({"page": p + 1, "from": round(d0, 3), "to": round(d1, 3),
                       "labels": len(found[p][3]) if p in found else 0,
                       "inferred": p in inferred})
        done_to = d1
    if bottom - done_to > 0.1:
        gaps.append((round(done_to, 2), round(bottom, 2)))
    out.set_metadata({"title": "stitched printout", "creator": "Frac2CSV",
                      "subject": f"depth {top:g}-{bottom:g} m at {ppm:.4f} pt/m, top at y=0"})
    data = out.tobytes(garbage=3, deflate=True)
    worst_seam = max([abs(x) for x in seams], default=0.0)
    info = {"top": top, "bottom": bottom, "pt_per_m": round(ppm, 4),
            "width_pt": round(width, 1), "height_pt": round(height, 1),
            "depth_axis_on_page": "across" if axis == 1 else "down",
            "pages": len(doc), "log_pages": len(placed),
            "left_out": [i + 1 for i in range(len(doc)) if i not in maps],
            "inferred": [i + 1 for i in sorted(inferred)],
            "placed": placed, "gaps": gaps, "worst_seam_m": round(worst_seam, 3),
            "over_page_limit": height > PAGE_MAX}
    info["check"] = check(data, top, bottom, ppm)
    spg = fitz.open(stream=data, filetype="pdf")[0]
    ct = curve_track(spg)
    info["curves_pt"] = [round(ct[0], 1), round(ct[1], 1)] if ct else None
    info["lines_pt"] = track_lines(spg)
    return data, info


def _strokes(pg):
    """The long dark lines down a stitched strip (x, merged within 1 pt), and
    its coloured and dark slanting strokes as (x, length)."""
    H = pg.rect.height
    runs = collections.defaultdict(float)        # x of a dark line down the log -> length
    curve, slant = [], []                        # (x, length): coloured, dark slanting strokes
    for d in pg.get_drawings():
        col = d.get("color")
        if not col:
            continue                             # a fill
        coloured = max(col) - min(col) > 0.3
        dark = max(col) < 0.35
        for it in d["items"]:
            if it[0] == "l":
                p, q = it[1], it[2]
                dx, dy = abs(p.x - q.x), abs(p.y - q.y)
                if dark and dx < 0.3 and dy > 2:
                    runs[round(p.x * 2) / 2] += dy
                elif coloured:
                    curve.append(((p.x + q.x) / 2, min(20.0, math.hypot(dx, dy))))
                elif dark and dx >= 0.3 and dy >= 0.3:
                    slant.append(((p.x + q.x) / 2, min(20.0, math.hypot(dx, dy))))
            elif it[0] == "re" and dark:
                r = it[1]
                runs[round(r.x0 * 2) / 2] += r.height
                runs[round(r.x1 * 2) / 2] += r.height
    xs = []
    for x in sorted(x for x, n in runs.items() if n >= 0.3 * H):
        if not xs or x - xs[-1] > 1.0:
            xs.append(x)
    return xs, curve, slant


def track_lines(pg):
    """x of the long dark lines a stitched strip draws its tracks between."""
    return _strokes(pg)[0]


def curve_track(pg):
    """(x0, x1), in points across a stitched strip (depth running down),
    of the track the curves are drawn in; None if there is none.

    LogViewer prints each track between long dark lines that run the length
    of the log, and grids it in grey. The curves (ROP, gas, gamma) are drawn
    in colour, as many short strokes; borders, gridlines and text are black
    or grey. So the curve track is the space between two neighbouring long
    dark lines that holds the most coloured stroke. On a horizontal log the
    well-bore cross-section has some colour too (its outlines), at most 0.6
    of what the data-curves track has on 400 printouts of the drive.

    A TVD gamma log draws its one curve in black. With no coloured curve
    along the log, the track with the most slanting dark stroke is taken
    instead: gridlines and borders run straight along or across, a curve
    wanders."""
    H = pg.rect.height
    xs, curve, slant = _strokes(pg)
    def best_by(strokes):
        best = None
        for a, b in zip(xs, xs[1:]):
            if b - a < 20:
                continue
            w = sum(n for x, n in strokes if a <= x <= b)
            if best is None or w > best[2]:
                best = (a, b, w)
        return best
    # a curve along the log has at least a tenth of the log's length in
    # strokes; less is a mark or two, not a curve
    for strokes in (curve, slant):
        best = best_by(strokes)
        if best and best[2] >= 0.1 * H:
            return best[0], best[1]
    return None


def check(strip, top, bottom, ppm):
    """Every depth label on the strip should sit at (depth - top) * ppm.
    Counts the labels in the depth column and how far each lands from its
    depth: the median, the 95th percentile and the worst, in metres."""
    doc = fitz.open(stream=strip, filetype="pdf")
    pg = doc[0]
    labels = _labels(pg, top - 1, bottom + 1)
    if not labels:
        return {"labels": 0, "median_m": None, "p95_m": None, "worst_m": None}
    # the depth column: of the strip's columns of numbers, the one that sits
    # on the strip's own scale (a second depth column can sit off it)
    # A label printed across a page edge keeps only its digits on one side
    # ("1350" -> "350"); it is in the right place, just not readable, so
    # anything more than 20 m from its depth is counted apart.
    cols = collections.defaultdict(list)
    for v, x, y in labels:
        cols[round(x / 3.0)].append(abs(top + y / ppm - v))
    allm = max(cols.values(), key=lambda m: (sum(1 for e in m if e < 0.1), len(m)))
    cut = sum(1 for e in allm if e > 20)
    miss = sorted(e for e in allm if e <= 20)
    if not miss:
        return {"labels": 0, "median_m": None, "p95_m": None, "worst_m": None}
    return {"labels": len(miss), "median_m": round(_median(miss), 3),
            "p95_m": round(miss[min(len(miss) - 1, int(0.95 * len(miss)))], 3),
            "worst_m": round(miss[-1], 3),
            "off_by_over_1m": sum(1 for m in miss if m > 1.0),
            "within_0.1m": round(sum(1 for m in miss if m <= 0.1) / len(miss), 3),
            "cut_at_page_edge": cut}


def render(strip, d0, d1, top, ppm, px_per_m, width_px=None, across=None):
    """A PNG of the strip from depth d0 to d1 at px_per_m pixels per metre.
    width_px stretches it across to that many pixels (the stacked window
    does, when the whole log is fitted to the screen and the strip at its own
    proportions would be a sliver); otherwise it keeps its proportions.
    across=(x0, x1) shows that part of the strip only (the curve track).
    strip: the PDF bytes, a Document, or the DisplayList of its page (the
    fast way to draw one page many times)."""
    if isinstance(strip, fitz.DisplayList):
        src = strip
    else:
        doc = strip if isinstance(strip, fitz.Document) else fitz.open(stream=strip, filetype="pdf")
        src = doc[0]
    R = src.rect
    x0, x1 = (max(R.x0, across[0]), min(R.x1, across[1])) if across else (R.x0, R.x1)
    y0 = max(0.0, (d0 - top) * ppm)
    y1 = min(R.height, (d1 - top) * ppm)
    if y1 <= y0 or x1 <= x0:
        return None
    zy = px_per_m / ppm
    zx = (float(width_px) / (x1 - x0)) if width_px else zy
    pix = src.get_pixmap(matrix=fitz.Matrix(zx, zy), clip=fitz.Rect(x0, y0, x1, y1), alpha=False)
    return pix.tobytes("png")


def cut(strip, x0, x1):
    """The strip with only the part from x0 to x1 across: one compartment of
    the printout as its own PDF, still vector."""
    src = fitz.open(stream=strip, filetype="pdf")
    R = src[0].rect
    out = fitz.open()
    pg = out.new_page(width=x1 - x0, height=R.height)
    pg.show_pdf_page(pg.rect, src, 0, clip=fitz.Rect(x0, R.y0, x1, R.y1))
    out.set_metadata(src.metadata)
    return out.tobytes(garbage=3, deflate=True)
