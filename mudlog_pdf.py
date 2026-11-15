"""A mudlog read from its PDF printout alone, with the printout's own legend.

    import mudlog_pdf
    reading = mudlog_pdf.read("log.pdf")

The reading has the mudlog answer key's fields (mudlog_key.py), so it can
be marked against the key of a log whose file we have:

  depth    the depth labels down the log give the range and map every log
           page to depth (wellsight_print.stitch); pages run on from one to
           the next
  header   the pages before the log, and the first log page above the log:
           rows of "Label: value", named by log_vocab ("Company:" under
           OPERATOR is the operator)
  text     every line of text on the log pages, at the depth of its top
  rocks    each picture on the log that is one of the legend's rock
           patterns, at its depths; where several are drawn at one depth
           (a percentage column beside the rock column, a cross-section)
           the rock drawn widest wins
  symbols  each picture that is one of the legend's symbols, at the depth
           of its top edge (a symbol hangs from its depth)
  intervals the pictures of the legend's intervals, slide / rotate and
           reservoir quality, as the runs they draw down their column
  tracks   the log's columns: between the long lines down the log, titled
           by the header row over them
  curves   each curve caption (a name, in the curve's colour, between the
           scale's two ends; again lower down where the scale changes)
           names the lines of its colour in the track between the long lines
           either side of it. Their position across the track is the
           reading. LogViewer draws each curve twice: a main line held inside
           the track and a thin line one scale width off it that the PDF
           keeps whole past the track's edge, so a reading past its scale is
           read exactly (read_line). With one line only, a line that runs off
           one end and comes back in from the other has wrapped
           (wellsight_scales.read_drawn)

Nothing here knows one program's patterns, symbols or colours: those come
from the legend and the captions. A picture the printout's legend leaves
out can be looked up in a library of other printouts' legends
(validation-tools/pdf_legend_library.py). The printouts read so far are
WellSight LogViewer's; the legend and caption reading is the part meant to
carry over to others.

Needs PyMuPDF.
"""
import collections
import math
import re

import log_vocab as V
import pdf_legend as L
import wellsight_scales as wscale

READER = "frac2csv mudlog_pdf 1"
STEP = 0.1              # m: curves are read at this spacing
GAP_PT = 12.0           # header words further apart than this on a row are separate fields
CAPTION_M = 0.1         # m: a scale starts this far above its caption's top
FILL_M = 1.5            # a gap in a curve's line (a dashed line) up to this long is filled straight


# ---------------------------------------------------------------- depth

def _depth_range(doc):
    """(top, bottom, metres per point) as the printout's depth labels give
    them, widened by one label step each way (the log runs on past its first
    and last label), or None"""
    import wellsight_print as wp
    lines = []
    for pg in doc:
        ax = wp.page_axis(pg, 1, 99999)
        if ax and len(ax[3]) >= 5:
            lines.append((abs(ax[1]), [d for _c, d in ax[3]]))
    if not lines:
        return None
    # the log's pages share one scale; a header page's numbers do not
    scale = sorted(s for s, _ in lines)[len(lines) // 2]
    ds = sorted({d for s, on in lines if abs(s - scale) <= 0.02 * scale for d in on})
    if not ds:
        return None
    gaps = sorted(b - a for a, b in zip(ds, ds[1:]) if b > a)
    step = gaps[len(gaps) // 2] if gaps else 0.0
    # a page whose best row of numbers is some other (three stray numbers
    # can span more depth than its labels): its depth labels are a row of
    # the log's scale whose numbers step by the log's label step
    if step > 0:
        more = set()
        for pg in doc:
            for _axis, _key, a, _b, on in wp.page_lines(pg, 1, 99999):
                vs = sorted(d for _c, d in on)
                if len(vs) >= 4 and abs(abs(a) - scale) <= 0.02 * scale \
                        and all(abs(v / step - round(v / step)) < 0.01 for v in vs):
                    more.update(vs)
        ds = sorted(set(ds) | more)
    return ds[0] - step, ds[-1] + step, scale


def depth_range(doc):
    """the log's range as its printout's depth labels give it: (top,
    bottom) or None"""
    r = _depth_range(doc)
    return r[:2] if r else None


def _labelled_range(doc, pages, rng):
    """the range again, from every depth label that sits at its own depth
    on the pages as stitched: the first and last pages of a log carry too
    few labels to be counted on their own"""
    import wellsight_print as wp
    lo, hi = rng
    found = []
    for P in pages:
        for v, x, y in wp._labels(doc[P.page - 1], lo - 1000, hi + 1000):
            if abs(P.depth(x, y) - v) < 0.3:
                found.append(v)
    found = sorted(set(found))
    if len(found) < 2:
        return rng
    gaps = sorted(b - a for a, b in zip(found, found[1:]))
    step = gaps[len(gaps) // 2]
    return min(lo, found[0] - step), max(hi, found[-1] + step)


class Page:
    """one log page's map to the stitched log: depth down, across"""

    def __init__(self, pl):
        self.page = pl["page"]
        self.lo, self.hi = pl["from"], pl["to"]
        dm, ac = pl["depth"], pl["across"]
        self.a, self.b, self.dc = dm["a"], dm["b"], dm["coord"]
        self.origin, self.sign = ac["origin"], ac["sign"]

    def depth(self, x, y):
        return self.a * (x if self.dc == "x" else y) + self.b

    def across(self, x, y):
        return self.sign * ((y if self.dc == "x" else x) - self.origin)

    def on(self, d, pad=0.0):
        return self.lo - pad <= d <= self.hi + pad

    def extent(self, rect):
        """the depths at the page's two edges"""
        e0, e1 = (rect.x0, rect.x1) if self.dc == "x" else (rect.y0, rect.y1)
        return tuple(sorted((self.a * e0 + self.b, self.a * e1 + self.b)))


# ---------------------------------------------------------------- header and text

def rows_of(pg, keep=None, whole=False):
    """the page's words in rows, top to bottom, each row left to right;
    keep(word) chooses the words, if given. whole: also the letters a box
    clips (a value longer than its box is read to its end)"""
    found = _words(pg) if whole else pg.get_text("words")
    words = sorted((w for w in found if keep is None or keep(w)),
                   key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows = []
    for w in words:
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - yc) < 3:
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    return [sorted(r[1], key=lambda w: w[0]) for r in rows]


def _words(pg):
    """the page's words as get_text("words") gives them, but also with the
    letters a box clips, and cut where the letters of a word stand apart
    (two fields printed with no space between them: "2692.00mTotal")"""
    import fitz
    out = []
    flags = fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_MEDIABOX_CLIP
    for bi, b in enumerate(pg.get_text("rawdict", flags=flags)["blocks"]):
        for li, ln in enumerate(b.get("lines", [])):
            k = 0
            for sp in ln["spans"]:
                word, prev = [], None
                for ch in sp["chars"] + [None]:
                    gap = 0.0
                    if ch is not None and prev is not None:
                        r = ch["bbox"]
                        gap = max(r[0] - prev[2], prev[0] - r[2], r[1] - prev[3], prev[1] - r[3])
                    if ch is None or ch["c"].isspace() or (word and gap > 0.25 * sp["size"]):
                        if word:
                            x0 = min(c["bbox"][0] for c in word)
                            y0 = min(c["bbox"][1] for c in word)
                            x1 = max(c["bbox"][2] for c in word)
                            y1 = max(c["bbox"][3] for c in word)
                            out.append((x0, y0, x1, y1, "".join(c["c"] for c in word), bi, li, k))
                            k += 1
                        word = []
                    if ch is not None and not ch["c"].isspace():
                        word.append(ch)
                        prev = ch["bbox"]
    return out


def _chunk_words(row):
    """a row's words in runs, split where they stand apart"""
    out, cur = [], [row[0]]
    for w in row[1:]:
        if w[0] - cur[-1][2] > GAP_PT:
            out.append(cur)
            cur = [w]
        else:
            cur.append(w)
    out.append(cur)
    return out


def chunks(row):
    """a row's words split where they stand apart"""
    return [" ".join(w[4] for w in c) for c in _chunk_words(row)]


def _labelled(words, box):
    """a run of words -> [(label or None, value words)]: a label ends with
    ":", and is the longest run of words before it that log_vocab knows
    (else the one word). A colon log_vocab does not know after other words,
    or a label straight after the label, is part of the value ("Acme
    Energy Ltd.: Attn ...", "Location: Surface: 01-02-3-4W5")"""
    out, label, start, field = [], None, 0, None
    # "WELL LICENCE No. 99X003": a label ending in "No." or "#" with no
    # colon, its value straight after it, at the start of the run (also
    # "NO.99X001" in one word, and "NO," with a comma)
    split = []
    for w in words:
        m = re.match(r"(?i)^(no[.,]|#)(\w.*)$", w[4])
        split += [w[:4] + (m.group(1),) + w[5:], w[:4] + (m.group(2),) + w[5:]] if m else [w]
    if split and not any(":" in w[4] for w in split):
        for n in range(min(6, len(split) - 1), 0, -1):
            t = " ".join(w[4] for w in split[:n])
            if re.search(r"(?i)(\bno[.,]?|#)$", t) and V.header(t, box)["key"]:
                return [(t, split[n:])]
    for j, w in enumerate(words):
        if not w[4].endswith(":") or len(w[4]) < 2:
            continue
        n, known = 1, False
        for k in range(min(6, j + 1), 0, -1):
            t = " ".join(x[4] for x in words[j - k + 1:j + 1])
            h = V.header(t, box)["key"]
            if h is None and field == "logged_interval_top":
                h = V.header(t, "LOGGED INTERVAL")["key"]      # "Logged Interval: 865 m To: 2607 m"
            if h:
                n, known, field = k, True, h
                break
        lo = max(start, j - n + 1)
        if label is not None and (not known or lo == start):
            continue
        if label is None and not known and lo > start:
            continue                # "Acme Energy Ltd.: Attn": a colon inside a value
        if lo > start or label is not None:
            out.append((label, words[start:lo]))
        label, start = " ".join(x[4] for x in words[lo:j + 1]), j + 1
    out.append((label, words[start:]))
    return [(l, v) for l, v in out if l is not None or v]


def pieces(text, box):
    """a row's text -> [(label or None, value)] (see _labelled)"""
    words = [(i, 0, i + 1, 1, t) for i, t in enumerate(text.split())]
    return [(l, " ".join(w[4] for w in v)) for l, v in _labelled(words, box)]


def _wrapped(run, nxt, box):
    """a label printed over two lines: this run of words starts it ("Bottom
    Hole 294.90 m NORTH ...") and a run on the next line ends it
    ("Coordinates: OR 692.6 m ..."), the two parts of the label ending
    at one place across, the values right of it. -> (index of the run in nxt, label, the first line's value words) or
    None"""
    for k, other in enumerate(nxt):
        found = _labelled(other, box)
        if not found or found[0][0] is None:
            continue
        end = other[len(found[0][0].split()) - 1][2]     # the label's right end: the first line's label ends by it
        lead = [w for w in run if w[2] <= end + 6]
        rest = [w for w in run if w[2] > end + 6]
        if (not lead or any(w[0] <= end for w in rest) or other[0][0] > lead[-1][2]
                or any(w[4].endswith(":") for w in lead)):
            continue
        label = " ".join(w[4] for w in lead) + " " + found[0][0]
        if V.header(label, box)["key"]:
            return k, label, rest
    return None


def read_header(pages):
    """pages: [page or (page, keep)], keep choosing the page's words that
    are header (the part of the first log page above the log).

    A field is read where its label first is: a label met again later (the
    licence on two pages) adds nothing. A value may stand apart from its
    label, go on onto the next lines that start where it did, and a label
    may be printed over two lines."""
    out, done = {}, set()
    text = lambda ws: " ".join(w[4] for w in ws)

    def put(field, unit, value, sep):
        if field is None or not value:
            return
        out[field] = out[field] + sep + value if out.get(field) else value
        if unit and re.search(r"\d$", out[field]):
            out[field] += " " + unit

    for pg in pages:
        pg, keep = pg if isinstance(pg, tuple) else (pg, None)
        box, prev, prev_y = None, {}, None
        rows = rows_of(pg, keep, whole=True)
        early = {}                                   # (row, run) -> (label, value words) begun on the row above
        for i, row in enumerate(rows):
            runs = _chunk_words(row)
            whole = text(row).strip()
            y = (row[0][1] + row[0][3]) / 2
            if prev_y is not None and y - prev_y > 2.2 * max(w[3] - w[1] for w in row):
                prev = {}                            # a gap: the lines above are done
            prev_y = y
            if len(runs) == 1 and ":" not in whole and V.key("header box", whole):
                box, prev = whole, {}
                continue
            cur, dangling, last = {}, None, None     # dangling: (field, unit) of a label still waiting for its value
            for ci, run in enumerate(runs):
                hit = next((f for vx, f in prev.items() if abs(vx - run[0][0]) <= 4), None)
                if hit and (i, ci) not in early and last is None:   # no label before it on its line
                    put(hit, None, text(run), "\n")         # the next line of a value (whatever it holds)
                    cur[run[0][0]] = hit
                    continue
                found = _labelled(run, box)
                if (len(found) == 1 and found[0][0] is None and ci + 1 < len(runs)
                        and V.header(text(run), box)["key"]):
                    found = [(text(run), [])]                # a label with no colon, its value apart: "RIG No.   11"
                elif dangling and found[0][0] is not None and not V.header(found[0][0], box)["key"]:
                    found = [(None, run)]                    # "Location:   Surface: 01-02-3-4W5": all the value
                begun = early.get((i, ci))
                if begun and found[0][0] is not None:
                    found = [(begun[0], found[0][1])] + found[1:]
                elif found[0][0] is None and i + 1 < len(rows):
                    w = _wrapped(run, _chunk_words(rows[i + 1]), box)
                    if w:
                        early[(i + 1, w[0])] = (w[1], w[2])
                        continue
                for j, (label, vw) in enumerate(found):
                    if label is None:
                        if dangling:
                            put(dangling[0], dangling[1], text(vw), "\n")
                            cur[vw[0][0]] = dangling[0]
                            dangling = None
                        continue
                    h = V.header(label, box)
                    if h["key"] is None and last == "logged_interval_top":
                        h = V.header(label, "LOGGED INTERVAL")         # "Logged Interval: 865 m   To: 2607 m"
                    field, dangling, last = h["key"], None, h["key"]
                    if field is None or (field in done and out.get(field)):
                        continue
                    done.add(field)
                    value = text(vw)
                    if begun and j == 0:
                        value = "\n".join(v for v in (text(begun[1]), value) if v)
                    put(field, h["unit"], value, " ")
                    if vw:
                        cur[vw[0][0]] = field
                    else:
                        dangling = (field, h["unit"])
            prev = cur
    return out


def read_text(doc, pages):
    text = []
    for P in pages:
        pg = doc[P.page - 1]
        for b in pg.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                s = "".join(sp["text"] for sp in ln["spans"]).strip()
                if not s:
                    continue
                x0, y0, x1, y1 = ln["bbox"]
                d = min(P.depth(x0, y0), P.depth(x1, y1))
                if P.on(d, 0.5):
                    a0, a1 = sorted((P.across(x0, y0), P.across(x1, y1)))
                    text.append({"depth": round(d, 3), "text": s, "across": [round(a0, 1), round(a1, 1)],
                                 "height": round(abs(P.depth(x1, y1) - P.depth(x0, y0)), 3)})
    return text


# ---------------------------------------------------------------- pictures

def legend_of(doc, pages):
    """the legend: pictures with labels on the pages that are not the log,
    or on a log page outside the part of it that is the log"""
    by_page = {P.page: P for P in pages}
    look = []
    for i in range(len(doc)):
        P = by_page.get(i + 1)
        if P is not None:
            e0, e1 = P.extent(doc[i].rect)
            if P.lo <= e0 + 0.5 and P.hi >= e1 - 0.5:
                continue                     # all log: no legend here
        look.append(i)
    out = []
    for s in L.legend(doc, look):
        P = by_page.get(s.page)
        if P is not None:
            x0, y0, x1, y1 = s.bbox
            if P.on(P.depth((x0 + x1) / 2, (y0 + y1) / 2), 0.0):
                continue
        out.append(s)
    return out


RUNS = ("interval", "directional", "quality")    # groups drawn as runs down a column, not marks


def read_pictures(doc, pages, lib):
    """-> (tiles [(d0, d1, width, term, group)]: rock patterns and the runs
    of the interval, slide / rotate and reservoir-quality columns; symbols
    [{depth, group, term}]; pictures not in the legend)"""
    tiles, symbols, unknown = [], [], 0
    for P in pages:
        pg = doc[P.page - 1]
        for im in pg.get_image_info(hashes=True, xrefs=True):
            x0, y0, x1, y1 = im["bbox"]
            d0, d1 = sorted((P.depth(x0, y0), P.depth(x1, y1)))
            a0, a1 = sorted((P.across(x0, y0), P.across(x1, y1)))
            mid = (d0 + d1) / 2
            if not P.on(mid, 0.0):
                continue
            s = lib.find(im.get("digest"), im.get("xref"), (im["width"], im["height"]))
            if s is None:
                unknown += 1
                continue
            if s.group == "rock" or s.group in RUNS:
                d0, d1 = max(d0, P.lo), min(d1, P.hi)
                if d1 > d0:
                    tiles.append((d0, d1, a1 - a0, s.term, s.group))
            else:
                # a symbol hangs from its depth: LogViewer draws it from
                # there down (a stringer's bar runs a metre or more below)
                symbols.append({"depth": round(max(d0, P.lo), 3), "group": s.group, "term": s.term,
                                "across": round((a0 + a1) / 2, 1)})
    symbols.sort(key=lambda s: (s["depth"], s["group"]))
    return tiles, symbols, unknown


def rocks_from_tiles(tiles, step=0.05):
    """the rock drawn widest at each depth, as intervals {top, base, rock}"""
    tiles = [t for t in tiles if t[4] == "rock"]
    if not tiles:
        return []
    top = min(t[0] for t in tiles)
    n = int(math.ceil((max(t[1] for t in tiles) - top) / step)) + 1
    bins = [None] * n
    for d0, d1, w, term, _g in tiles:
        i0, i1 = int((d0 - top) / step + 0.5), int((d1 - top) / step + 0.5)
        for i in range(max(0, i0), min(n, i1)):
            b = bins[i]
            if b is None:
                b = bins[i] = collections.Counter()
            b[term] += w
    out = []
    for i, b in enumerate(bins):
        if not b:
            continue
        rock = b.most_common(1)[0][0]
        d0, d1 = round(top + i * step, 3), round(top + (i + 1) * step, 3)
        if out and out[-1]["rock"] == rock and abs(out[-1]["base"] - d0) < 1e-6:
            out[-1]["base"] = d1
        else:
            out.append({"top": d0, "base": d1, "rock": rock})
    return out


def intervals_from_tiles(tiles, join_m=0.05):
    """the interval, slide / rotate and quality runs: {top, base, group,
    term}, touching pictures of one term joined"""
    out = []
    for d0, d1, _w, term, g in sorted((t for t in tiles if t[4] in RUNS), key=lambda t: (t[4], t[3], t[0])):
        if out and out[-1]["group"] == g and out[-1]["term"] == term and d0 <= out[-1]["base"] + join_m:
            out[-1]["base"] = round(max(out[-1]["base"], d1), 3)
        else:
            out.append({"top": round(d0, 3), "base": round(d1, 3), "group": g, "term": term})
    out.sort(key=lambda r: (r["top"], r["group"]))
    return out


# ---------------------------------------------------------------- curves

def _grid_lines(doc, pages):
    """the light lines straight down the log (a curve track's grid), across
    in points, from the first two log pages"""
    out = collections.Counter()
    for P in sorted(pages, key=lambda q: q.page)[:2]:
        for d in doc[P.page - 1].get_drawings():
            c = d.get("color")
            if not c or min(c[:3]) <= 0.35 or max(c[:3]) - min(c[:3]) > 0.1:
                continue                           # a grey line only
            for it in d["items"]:
                if it[0] != "l":
                    continue
                p, q = it[1], it[2]
                a0, a1 = P.across(p.x, p.y), P.across(q.x, q.y)
                if abs(a0 - a1) < 0.3 and abs(P.depth(p.x, p.y) - P.depth(q.x, q.y)) > 1.0:
                    out[round(a0 * 2) / 2] += 1
    return sorted(out)


def _grid_edges(grid, lines_pt, x0, x1):
    """a curve track's edges from its grid: evenly spaced grey lines across
    the track, its edges one spacing outside the outer ones (a slide bar's
    strip beside the track can be inside it, its line no edge of the
    scale). (x0, x1) as they were where the grid does not say"""
    def even(inner):
        if len(inner) < 4:
            return None
        gaps = [b - a for a, b in zip(inner, inner[1:])]
        sp = sorted(gaps)[len(gaps) // 2]
        return None if sp < 2 or any(abs(g - sp) > 0.2 * sp for g in gaps) else sp

    # the grid a little past the edges (they can be a line out), else the
    # grid inside them only (the next track's grid close by)
    inner = [g for g in grid if x0 - 12 < g < x1 + 12]
    sp = even(inner)
    if sp is None:
        inner = [g for g in grid if x0 < g < x1]
        sp = even(inner)
    if sp is None:
        return x0, x1

    def snap(x):
        near = min(lines_pt, key=lambda l: abs(l - x))
        return near if abs(near - x) <= 1.5 else None

    a, b = snap(inner[0] - sp), snap(inner[-1] + sp)
    # an edge with no line of its own (the page's edge, the track cut off
    # by it) is where the grid puts it
    if a is None and x0 not in lines_pt:
        a = inner[0] - sp
    if b is None and x1 not in lines_pt:
        b = inner[-1] + sp
    return (a if a is not None else x0), (b if b is not None else x1)


def _widen(segs, lines_pt, x0, x1):
    """a curve's track widened past a line of the log while the curve's own
    line runs on across it: it crosses the line again and again, and much of
    it lies beyond (at a real edge the line only pokes past it where a
    reading runs off the scale). segs: the curve's strokes, across in
    points. -> (x0, x1)"""
    def length(sg):
        return max(abs(sg[2] - sg[0]), 0.01)

    def inside(lo, hi):
        return sum(length(sg) for sg in segs if lo - 0.5 <= min(sg[1], sg[3]) and max(sg[1], sg[3]) <= hi + 0.5)

    lines = sorted(lines_pt)
    most = 1.5 * (x1 - x0)                     # a band is not much wider than its caption block's column
    for side in (0, 1):
        while True:
            edge = x0 if side == 0 else x1
            if edge not in lines:
                break
            i = lines.index(edge)
            j = i - 1 if side == 0 else i + 1
            if not 0 <= j < len(lines):
                break
            nxt = lines[j]
            if (x1 - nxt if side == 0 else nxt - x0) > most:
                break
            lo, hi = (nxt, edge) if side == 0 else (edge, nxt)
            beyond = inside(lo, hi)
            cross = sum(1 for sg in segs if min(sg[1], sg[3]) < edge - 0.5 and max(sg[1], sg[3]) > edge + 0.5)
            # the curve is in one place at a depth: past the line where it is
            # not in the track. Another column's drawing of the colour sits
            # there at the same depths as the curve
            here, there = set(), set()
            for sg in segs:
                a = (sg[1] + sg[3]) / 2
                bins = range(int(sg[0] // 0.25), int(sg[2] // 0.25) + 1)
                if x0 + 0.5 < a < x1 - 0.5:
                    here.update(bins)
                elif lo + 0.5 < a < hi - 0.5:
                    there.update(bins)
            alone = len(there - here) >= 3 * len(there & here) and len(there - here) >= 0.05 * len(here)
            if cross >= 10 and beyond >= 0.05 * inside(x0, x1) and alone:
                if side == 0:
                    x0 = nxt
                else:
                    x1 = nxt
            else:
                break
    return x0, x1


def _nice(v):
    """v as a scale's end would print it (1, 2, 2.5 or 5 of a power of ten),
    or None when it is no such number"""
    if v <= 0:
        return None
    e = math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        n = m * 10 ** e
        if abs(v - n) <= 0.06 * n:
            return round(n, 6)
    return None


def _ends_from_decades(c, x0, x1):
    """a caption's scale ends. A log scale can print its decades where they
    lie on the scale (1 10 100 under its name, the ends 0.2 and 200 at the
    track's edges unprinted): numbers well inside the track a whole number
    of decades apart give the ends at the edges, where those come out as a
    scale's numbers. -> (left, right)"""
    lv, rv = c.left, c.right
    if not (lv > 0 and rv > 0) or abs(math.log10(rv / lv)) < 0.99:
        return lv, rv
    dec = math.log10(rv / lv)
    if abs(dec - round(dec)) > 0.01 or x1 <= x0:
        return lv, rv
    w = x1 - x0
    inside = min(c.left_at, c.right_at) > x0 + 0.08 * w or max(c.left_at, c.right_at) < x1 - 0.08 * w
    if not inside or not (x0 - 1 <= min(c.left_at, c.right_at) and max(c.left_at, c.right_at) <= x1 + 1):
        return lv, rv
    per = (c.right_at - c.left_at) / dec              # points per decade, signed
    if abs(per) < 5:
        return lv, rv
    l_ = _nice(10 ** (math.log10(lv) + (x0 - c.left_at) / per))
    r_ = _nice(10 ** (math.log10(lv) + (x1 - c.left_at) / per))
    return (l_, r_) if l_ and r_ and (l_, r_) != (lv, rv) else (lv, rv)


def _past_decade_lines(c, lines_pt, x0, x1):
    """a log scale's track whose edges were taken from its decade lines
    (its numbers 1 and 1000 on two of them, the track running on to 0.2 and
    2000 past them): out to the next line each side within a decade, where
    that is no line of the decades. -> (x0, x1)"""
    lv, rv = c.left, c.right
    if not (lv > 0 and rv > 0) or abs(math.log10(rv / lv)) < 0.99:
        return x0, x1
    dec = math.log10(rv / lv)
    if abs(dec - round(dec)) > 0.01:
        return x0, x1
    per = abs(c.right_at - c.left_at) / dec
    if per < 5 or abs(min(c.left_at, c.right_at) - x0) > 1.5 or abs(max(c.left_at, c.right_at) - x1) > 1.5:
        return x0, x1
    inner = [l for l in lines_pt if x0 - 1 <= l <= x1 + 1]
    if not all(abs((l - x0) / per - round((l - x0) / per)) < 0.05 for l in inner):
        return x0, x1                            # (the lines between are not every decade's)
    lo = [l for l in lines_pt if x0 - per + 1 < l < x0 - 1]
    hi = [l for l in lines_pt if x1 + 1 < l < x1 + per - 1]
    return (max(lo) if lo else x0), (min(hi) if hi else x1)


def _track_edges(lines_pt, a_left, a_right):
    """the long lines either side of a caption's two numbers"""
    lo = [x for x in lines_pt if x <= a_left + 1.0]
    hi = [x for x in lines_pt if x >= a_right - 1.0]
    if not lo or not hi:
        return None
    return max(lo), min(hi)


class Strokes:
    """every coloured or dark stroke on the log pages, on the stitched log:
    by colour, then by line width, [(d0, a0, d1, a1)] with d depth and a
    across, d0 <= d1. A stroke straight across at one depth is left out: it
    says nothing between depths."""

    def __init__(self, doc, pages):
        self.by = collections.defaultdict(lambda: collections.defaultdict(list))
        self.flats = collections.defaultdict(lambda: collections.defaultdict(list))
        for P in pages:
            for dr in doc[P.page - 1].get_drawings():
                c = dr.get("color")
                if c is None:
                    continue
                key = tuple(round(v, 2) for v in c[:3])
                w = round(dr.get("width") or 0.0, 2)
                out = self.by[key][w]
                for it in dr["items"]:
                    if it[0] == "l":
                        p, q = it[1], it[2]
                    elif it[0] == "c":
                        p, q = it[1], it[4]
                    else:
                        continue
                    da, db = P.depth(p.x, p.y), P.depth(q.x, q.y)
                    if not (P.on(da, 0.01) or P.on(db, 0.01)):
                        continue
                    aa, ab = P.across(p.x, p.y), P.across(q.x, q.y)
                    if abs(da - db) < 1e-4:
                        # straight across at one depth: kept apart (a step's
                        # flat, which says a reading moved and did not wrap)
                        self.flats[key][w].append((da, min(aa, ab), da, max(aa, ab)))
                        continue
                    out.append((da, aa, db, ab) if da < db else (db, ab, da, aa))

    def of(self, colour, flats=False):
        want = L.rgb(colour)
        for key, groups in (self.flats if flats else self.by).items():
            if max(abs(a - b) for a, b in zip(key, want)) <= 0.02:
                return groups
        return {}


def _relative(segs, x0, x1):
    """strokes with across as a share of the track, 0 at x0 and 1 at x1;
    the track's borders (straight down it, long, at an edge) left out"""
    w = x1 - x0
    out = []
    for da, aa, db, ab in segs:
        pa, pb = (aa - x0) / w, (ab - x0) / w
        if abs(pa - pb) < 1e-4 and db - da > 3.0 and (abs(pa) < 0.01 or abs(pa - 1) < 0.01):
            continue
        out.append((da, pa, db, pb))
    return out


def _inside(segs):
    """how far the strokes run inside the track, in metres down it"""
    return sum(db - da for da, pa, db, pb in segs if -0.005 <= pa <= 1.005 and -0.005 <= pb <= 1.005)


def _series(segs, top, n, step):
    """for each depth top + i * step, the positions where the strokes cross it"""
    series = [[] for _ in range(n)]
    for da, pa, db, pb in segs:
        i0 = max(0, int(math.ceil((da - top) / step - 1e-9)))
        i1 = min(n - 1, int(math.floor((db - top) / step + 1e-9)))
        for i in range(i0, i1 + 1):
            d = top + i * step
            series[i].append(pa + (pb - pa) * (d - da) / (db - da))
    return series


def _fill(values, top, step, most_m=FILL_M):
    """short gaps (a dashed line's) filled straight between their ends"""
    out = list(values)
    n = len(out)
    i = 0
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        if 0 < i and j < n and (j - i) * step <= most_m:
            a, b = out[i - 1], out[j]
            for k in range(i, j):
                out[k] = a + (b - a) * (k - i + 1) / (j - i + 1)
        i = j
    return out


def read_line(main, wrap, left, right):
    """a curve's readings from its lines, down the log. LogViewer draws a
    reading twice: the main line, held inside the track (it lies along the
    scale's end, or folds back in from the other end, past it), and a thin
    line one scale width off it, which the PDF keeps whole where the page
    cuts it off: one width lower where readings run past the scale's high
    end, one width higher where they run below its low end. main[i],
    wrap[i]: where each crosses depth i, as a share of the track.
    -> [(value, exact) or None]

    A thin line is the reading, one scale width on, where the main line
    bears it out: the same reading inside the scale, or the main line along
    the end the reading is past. Where the two lie together (the main line
    folded back in, or the reading itself) the one that carries on from the
    reading above is taken. Elsewhere the main line inside the track is the
    reading; one along an end of the scale says only that the reading is
    past it (not exact)."""
    lo, hi = min(left, right), max(left, right)
    span = hi - lo
    tol = wscale.EDGE * span
    agree = 0.01 * span
    together = 0.025 * span                        # (two lines drawn in different widths cross a
    out, last = [], None                           #  depth a little apart)

    def val(p):
        return left + p * (right - left)

    def near(cands):
        return min(cands, key=lambda u: abs(u - last)) if last is not None else cands[0]

    for ms, ws in zip(main, wrap):
        vm = [val(p) for p in ms]
        mid = [u for u in vm if lo + tol < u < hi - tol]
        at_hi = any(u >= hi - tol for u in vm)
        at_lo = any(u <= lo + tol for u in vm)
        sure, either = [], []
        for u in (val(p) for p in ws):
            up, down = u + span, u - span          # the reading, were the thin line below it / above it
            if any(abs(m - up) < agree or abs(m - down) < agree for m in mid):
                sure += [c for c in (up, down) if any(abs(m - c) < agree for m in mid)]
            elif at_hi and up >= hi - tol:
                sure.append(up)
            elif at_lo and down <= lo + tol:
                sure.append(down)
            elif any(abs(m - u) < together for m in vm):
                # together: the main line folded back in on the thin one,
                # one width off the reading (past the high end, or past the
                # low end where the reading already is)
                either.append(down if last is not None and last < lo else up)
            elif not vm and last is not None:
                sure += [c for c in (up, down) if abs(c - last) < span / 4]
        r = None
        if sure:
            r = (near(sure), True)
        elif either:
            r = (near(either), True)
        elif mid:
            r = (near(mid), True)
        elif at_hi:
            r = (hi, False)
        elif at_lo:
            r = (lo, False)
        out.append(r)
        if r is not None:
            last = r[0]
    return out


def _moves(segs, top, n, step):
    """for each depth i, the stretches across the track the line covers
    between depth i - 1 and i: [(lo, hi)] (a step drawn flat across the
    track between two readings shows here, missed by the crossings)"""
    out = [[] for _ in range(n)]
    for da, pa, db, pb in segs:
        if db < da:
            da, pa, db, pb = db, pb, da, pa
        i0 = max(1, int(math.floor((da - top) / step + 1e-9)) + 1)
        i1 = min(n - 1, int(math.ceil((db - top) / step - 1e-9)))
        for i in range(i0, i1 + 1):
            a, b = top + (i - 1) * step, top + i * step
            u, v = max(da, a), min(db, b)
            if v < u - 1e-9:
                continue
            if db - da < 1e-9:
                xs = (pa, pb)
            else:
                xs = tuple(pa + (pb - pa) * (d - da) / (db - da) for d in (u, v))
            out[i].append((min(xs), max(xs)))
    return out


NULL = -999.25
JUNK = -99.99          # a mudlog's own "no reading", drawn as one too


def _junk_dives(line, top, step, left, right):
    """the readings where junk under a scale from nothing (-368 on gas
    0 - 1000) is drawn: the line dives well under the track and back up
    within 0.5 m, its bottom cut off the page. A wrapped line dips the
    same way where the reading falls under the scale's top for a moment:
    read_one_line takes these as junk only where the reading was in the
    scale. -> {index}"""
    out = set()
    if left != 0 or right == left:
        return out
    down = sorted(db for da, pa, db, pb in line if pb < -0.15 and pa > pb + 0.15)
    up = sorted(da for da, pa, db, pb in line if pa < -0.15 and pb > pa + 0.15)
    for d1 in down:
        d2 = next((u for u in up if 0 < u - d1 <= 0.5), None)
        if d2 is not None:
            out.update(range(int(round((d1 - top) / step)) - 3, int(round((d2 - top) / step)) + 4))
    return out


def _null_dips(line, top, step, left, right):
    """the readings where LogViewer drew the log's null (-999.25, no
    reading) as if it were one: on a wide scale its place is just past the
    low edge, and the line turns there (and its copy one width on). ->
    {index}"""
    if right == left:
        return set()
    out = set()
    for junk in (NULL,):
        pn = (junk - left) / (right - left)
        if -wscale.EDGE <= pn <= 1 + wscale.EDGE or abs(pn) > 3:
            continue
        # (a place on an edge is no sign: a reading of nothing is drawn there)
        at = [q for q in (pn - 1, pn, pn + 1) if -1.5 < q < 2.5 and min(abs(q), abs(q - 1)) > 0.02]
        outside, inside = [], []
        for da, pa, db, pb in line:
            if db - da > 0.5 and abs(pa - pb) < 1e-4 and any(abs(pa - q) < 0.002 for q in at):
                # drawn flat along it (or its copy) for a stretch: no reading
                # there all along (a steady reading does not sit on it)
                out.update(range(int(round((da - top) / step)), int(round((db - top) / step)) + 1))
                continue
            for d, p in ((da, pa), (db, pb)):
                if any(abs(p - q) < 0.004 for q in at):
                    (inside if 0 <= p <= 1 else outside).append(int(round((d - top) / step)))
        # past the track nothing else is drawn there: the line on its way
        # down to it and back up is no reading either. Its copy inside the
        # track counts only beside that (the line's own corner can meet it)
        for j in outside:
            out.update(range(j - 3, j + 4))
        out.update(j for j in inside if any(abs(j - o) <= 5 for o in outside))
    return out


def _junk_flats(line, top, step, left, right):
    """the readings where a mudlog's own "no reading" (-99.99) is drawn
    flat for a stretch: on a wide scale from nothing just past the low
    edge, its copy one width on inside the track (a steady reading does not
    sit exactly there) -> {index}"""
    if right == left or left != 0:
        return set()
    pn = (JUNK - left) / (right - left)
    if -wscale.EDGE <= pn or pn < -0.5:
        return set()
    # (a dashed line draws it in dashes: those close together are one stretch)
    flat = sorted((da, db) for da, pa, db, pb in line
                  if abs(pa - pb) < 1e-4 and min(abs(pa - pn), abs(pa - pn - 1)) < 0.002)
    spans = []
    for da, db in flat:
        if spans and da - spans[-1][1] < 0.8:
            spans[-1][1] = max(spans[-1][1], db)
            spans[-1][2] += 1
        else:
            spans.append([da, db, 1])
    out = set()
    for da, db, n in spans:
        if db - da > 0.5 and (n >= 3 or db - da > 1.0):
            out.update(range(int(round((da - top) / step)), int(round((db - top) / step)) + 1))
    return out


def read_one_line(series, left, right, moves=None, under=False, nulls=(), dives=(), k0=0, junk=()):
    """a curve's readings where LogViewer drew it with one line only, down
    the log: series[i], where its line crosses depth i as a share of the
    track, unclipped (the PDF keeps the line past the track's edge, cut off
    on the page). -> [(value, exact) or None]

    Past the scale's high end the line stops at the first reading past it
    and goes on one scale width lower, in from the low end, until the
    readings come back. Where both are drawn at a depth (the two lie one
    track width apart) the one past the end is the reading and says the
    line has wrapped; the one in the track with one below the low end is
    the reading in the scale (or, where the line is already below the low
    end, the one below it). The wrapped line running out of the low end,
    or the line running out of the high end and carrying on lower, says the
    same with no pair drawn. Between, the line in the track is the reading,
    one scale width on while wrapped. With nothing drawn to say so, a jump
    from the top quarter of the track to the bottom quarter is a wrap, and a
    jump of the wrapped line back up ends it, unless the line is drawn
    across the track between the two readings (moves[i], from _moves: a
    step drawn flat): then the reading really moved. A wrong wrap would
    misread everything until the next jump, a missed one only the readings
    past the scale, so a jump is taken for a wrap only where it plainly is
    one. On a linear scale (under: one that starts above nothing; or one
    from nothing, which only junk readings run under), a pair by the low
    edge is below the scale where the line just was there. At nulls (the
    log's null drawn as a reading, _null_dips) there is no reading, and the
    line starts afresh after it."""
    lo, hi = min(left, right), max(left, right)
    e = wscale.EDGE
    out, k, last = [], k0, None                  # k: scale widths the line in the track is off the reading
    leapt = -10 ** 9                             # where the line last leapt up over half the track

    def val(p):
        return left + p * (right - left)

    def nearest(cands):
        return min(cands, key=lambda c: abs(c[0] - last)) if last is not None else cands[0]

    def carries_on(i, p):
        """the line in the track goes on from p below depth i (a scribble
        across the track draws one-off pairs)"""
        for ps in series[i + 1:i + 4]:
            inside = [q for q in ps or () if -e <= q <= 1 + e]
            if inside:
                return any(abs(q - p) < 0.25 for q in inside)
        return False

    def crossed(i, a, b):
        """the line is drawn across the track between places a and b since
        the last reading, down to depth i: through the middle between them
        (a dashed line's dashes too), or in one stroke from one to the other"""
        lo, hi = min(a, b) + 0.08, max(a, b) - 0.08
        j0 = i if last_i is None else max(last_i + 1, i - 5)
        if any(lo < q < hi for ps in series[j0:i + 1] for q in ps or ()):
            return True
        return bool(moves) and any(lo < a0 < hi or lo < a1 < hi or (a0 <= lo and a1 >= hi)
                                   for ms in moves[j0:i + 1] for a0, a1 in ms)

    def low_a_while():
        """the line has run along the bottom of the track for its last
        readings (junk under a scale from nothing comes after such a run; a
        wrapped line coming down fast through the track runs out too)"""
        got = [(r[0] - left) / (right - left) for r in out[-15:] if r is not None][-5:]
        return len(got) >= 2 and all(-0.2 <= q <= 0.3 for q in got)       # (junk just under counts)

    def back_in_at_top(i, at):
        """since the last reading (at, in the track) the line went on down
        and was next drawn by the top of the track (a dashed line's dashes
        after a gap): a wrapped line run out of the low end and the reading
        in again from the top"""
        if last_i is None or not moves:
            return False
        for j in range(last_i + 1, i):
            seen_ = [q for a0, a1 in moves[j] for q in (a0, a1)] + list(series[j] or ())
            if any(q > 1 + e for q in seen_):
                return False                     # the line itself past the top: still wrapped
            if any(q >= 0.85 for q in seen_):
                return True                      # by the top, with only the line going down before
            if any(q > max(at, 0.2) + 0.03 for q in seen_):
                return False
        return False

    def high_a_while():
        """the line has been up by the top of the track for its last two
        readings (a line that only leapt there is no wrap when it drops)"""
        got = [(r[0] - left) / (right - left) for r in out[-15:] if r is not None][-2:]
        return len(got) == 2 and all(0.85 <= q <= 1.2 for q in got)

    def went_under(i):
        """the line ran out of the low edge just above depth i"""
        if any(q <= e for ps in series[max(0, i - 2):i] for q in ps or ()):
            return True
        return bool(moves) and any(a0 <= e for ms in moves[max(0, i - 1):i + 1] for a0, _a1 in ms)

    def comes_back(i):
        """the line in the track is back near the top within 3 m below
        depth i: a short wrap ends when the reading falls back under the
        scale's end; a real drop to the background stays down"""
        for ps in series[i + 1:i + 31]:
            if any(0.6 <= q <= 1 + e for q in ps or ()):
                return True
        return False

    last_i, seen, under_since, before_gap, dive_junk = None, [], None, None, False
    for i, ps in enumerate(series):
        if out and out[-1] is not None:
            last_i = i - 1
        if k == -1:
            under_since = i - 1 if under_since is None else under_since
            top_ps = [q for ps_ in series[max(under_since, i - 10):i] for q in ps_ or () if q >= 0.5]   # (the last 1 m)
            drawn = sum(1 for ps_ in series[under_since:i] if any(q >= 0.5 for q in ps_ or ()))
            if not under and i - under_since > 10 and top_ps and max(top_ps) - min(top_ps) > 0.03 \
                    and drawn >= 0.7 * (i - under_since):    # (a line drawn all along, not junk's bits)
                k, under_since = 0, None         # junk under a scale from nothing sits flat: a line
                if last is not None:             # in from the top that moves for 1 m is the reading
                    last += 1
        else:
            under_since = None
        if last is not None and i - last_i > 30 and not (
                any(q > 1 + e for q in seen) or (any(q >= 1 - e for q in seen) and not any(q <= e for q in seen))):
            before_gap = last if k == 0 else None
            last, k = None, 0                    # nothing read for 30 readings: the line starts afresh
            #                                      (unless it went off past the top: it comes back wrapped)
        if ps:
            seen = list(ps)
        if i in dives and i - 1 not in dives:
            dive_junk = k == 0                   # a dive from the reading in the scale is junk; from a
        #                                          wrapped one it is the reading under the top for a moment
        if i in nulls or (i in dives and dive_junk):
            out.append(None)
            last, k = None, 0
            continue
        if i in junk:
            pj = (JUNK - left) / (right - left)
            out.append((JUNK, True))             # the log's own "no reading", as it holds it
            last, k = pj, -1
            continue
        pts = sorted(ps or ())
        # on a scale from nothing, a reading of nothing (or a little under)
        # is drawn on both edges at once, nothing else drawn: it reads 0
        # where the reading before was low (by the top it is the top)
        if left == 0 and k == 0 and (last is None or last <= 0.2) and not any(0.02 < q < 0.98 for q in pts) and any(
                abs(b - a - 1) < 0.03 and abs(a) <= 0.012 and abs(b - 1) <= 0.012
                for j, a in enumerate(pts) for b in pts[j + 1:]):
            out.append((float(left), True))
            last = 0.0
            continue
        # two lines one on each edge (a frame, or a line pinned at both
        # ends) say nothing about where the reading is
        pairs = [(a, b) for j, a in enumerate(pts) for b in pts[j + 1:]
                 if abs(b - a - 1) < 0.03 and not (abs(a) <= e and abs(b - 1) <= e)]
        if pairs and any(b > 1 + e for a, b in pairs) and k != 1:
            a, b = pairs[-1]
            # a wrap starts where the line just was, up at the top, and goes
            # on from the low end (a scribble, or a line from a gap in the
            # data, draws one-off pairs)
            if not carries_on(i, a) or last is None or abs(b - last) > 0.35:
                pairs = [(a, b) for a, b in pairs if b <= 1 + e]
        r = None
        if pairs:
            a, b = pairs[-1] if any(b > 1 + e for a, b in pairs) else pairs[0]
            if b > 1 + e:
                r, k = b, 1
            elif a < -e:
                # below the low end only where the line already is (mudlog
                # readings rarely go under a scale that starts at nothing)
                if k == -1 or ((under or (left == 0 and low_a_while())) and last is not None
                               and abs(a - last) < 0.25 and abs(a - last) < abs(b - last)):
                    r, k = a, -1
                else:
                    r, k = b, 0
            else:
                r, k = nearest([(b, 0), (a, 0)])
            out.append((val(r), True))
            last = r
            continue
        inside = [p for p in pts if -e <= p <= 1 + e]
        out_lo = [p for p in pts if p < -e]
        out_hi = [p for p in pts if p > 1 + e]
        if k == 1 and inside and (out_lo or (moves and any(
                a1 - a0 > 0.02 and a0 < -e and a1 > -0.05 for a0, a1 in moves[i]))):   # (one that reaches the low edge)
            k = 0                                # the wrapped line runs out of the low end: back in the scale
        elif k == 0 and out_hi and last is not None and not any(abs(q - last) < 0.08 for q in inside):
            # (not where the line goes on inside the track from the reading
            # above: what runs out of the top there is another line)
            r = min(out_hi, key=lambda p: abs(p - last))
            if abs(r - last) < 0.5 and carries_on(i, r - 1):
                k = 1                            # out of the high end, on one width lower
                out.append((val(r), True))
                last = r
                continue
        if not inside:
            # the line just past an edge: read where it is drawn, but a line
            # grazing the edge says nothing about a wrap
            past = [p for p in pts if p < -e or p > 1 + e]
            if past and last is not None:
                r = min(past, key=lambda p: abs(p - last - (1 if k == 1 and p < 0 else 0)))
                if r > 1 and k == 1 and abs(r + 1 - last) < abs(r - last):
                    v = r + 1                    # the wrapped line itself past the top: past twice
                elif r > 1:
                    v = r                        # the line past the top is the reading itself
                    if k == 1:
                        k = 0                    # ... and it is back: the wrapped line has ended
                else:
                    v = r + max(k, 0)            # the wrapped line just below the low edge
                if abs(v - last) < 0.5:
                    out.append((val(v), True))
                    last = v
                    continue
            out.append(None)
            continue
        mid = [p for p in inside if e < p < 1 - e]
        if mid:
            p = min(mid, key=lambda m: abs(m + k - last)) if last is not None else mid[0]
            prev = last - k if last is not None else None       # where the line was in the track
            if last is not None and abs(p + k - last) > 0.5 and moves and any(
                    -e <= a0 and a1 <= 1 + e and a0 <= min(p, prev) + 0.05 and a1 >= max(p, prev) - 0.05
                    for a0, a1 in moves[i]):
                pass                                 # drawn across the track: the reading moved
            elif k == 0 and under and last_i is not None and 1 < i - last_i <= 50 and p >= 0.8 \
                    and (last if last is not None else before_gap) is not None \
                    and (prev if last is not None else before_gap) <= 0.5 \
                    and abs(p - 1 - (last if last is not None else before_gap)) \
                    < abs(p - (last if last is not None else before_gap)):
                k = -1                           # back after a gap by the top, the reading before low: run
                #                                  under the scale (only its copy in from the top drawn)
            elif last is not None and k == 0 and prev <= 0.25 and p >= 0.9 and went_under(i) and not crossed(i, prev, p) \
                    and (under or low_a_while()):
                k = -1                           # gone just under the low edge, drawn in at the top
                #                                  (a real leap up draws its line across the track)
            elif last is not None and k == 0 and prev >= 0.9 and p <= 0.1 and i - leapt > 20 and not crossed(i, p, prev) \
                    and high_a_while():
                k = 1                            # off the top edge, in at the low one, nothing drawn
                #                                  across between: wrapped (a real drop is drawn across)
            elif last is not None and k == 0 and prev >= 0.75 and p <= 0.25 and i - leapt > 20 and comes_back(i) \
                    and not crossed(i, p, prev):
                k = 1                            # off the top, in from the low end: wrapped (a line that
                #                                  leapt up just before is a spike coming back down)
            elif last is not None and k == 1 and prev <= 0.3 and back_in_at_top(i, prev):
                k = 0                            # the wrapped line out of the low end, in again from the top
            elif last is not None and k == 1 and p - prev > 0.3:
                k = 0                            # the wrapped line jumps back up: the reading is back in the scale
            elif last is not None and k == -1 and (prev - p > 0.3 or p < 0.5):
                k = 0                            # (and a reading half a width under the scale is no
                #                                  dip: the line was wrapped, now in the scale)
            if last is not None and k == 0 and p - (last - k) > 0.5:
                leapt = i
            out.append((val(p + k), True))
            last = p + k
        elif left == 0 and k == 0 and any(p >= 1 - e for p in inside) and any(-0.015 <= q < -e for q in pts):
            out.append((float(left), True))      # nothing, drawn just under the low edge and along the top
            last = 0.0
        elif any(p >= 1 - e for p in inside) and not any(p <= e for p in inside):
            if k == 0 and last is not None and last <= 0.25 and went_under(i) and not crossed(i, last, 1.0) \
                    and (under or low_a_while()):
                k = -1                           # gone just under the low edge, drawn in at the top
                #                                  (a real leap up draws its line across the track)
            if k == 1 and last is not None and abs(1 - last) < abs(2 - last):
                k = 0                            # wrapped just past the top, the line itself back along it
            out.append((val(1 + k), k != 0) if k else (hi if right > left else lo, False))
            last = 1 + k
        elif not any(p >= 1 - e for p in inside):
            out.append((val(k), k != 0) if k else (lo if right > left else hi, False))
            last = 0.0 + k
        else:
            out.append(None)                     # on both edges at once: nothing to go on
    return out


def _recorded_step(segs):
    """the step a curve was recorded at, from its drawn line: most of its
    strokes run from one reading to the next, so their length down the log
    is the step. Corners where the line is cut off at the track's edge split
    some strokes shorter, and a dashed line's dashes are shorter still (left
    out), so of 1, 0.5, 0.2 and 0.1 m the step is the largest that one
    stroke in seven matches (within a tenth of it: a sideways page's depth
    scale can be a little off); None when none does"""
    long_ = [(da, db) for da, _pa, db, _pb in segs if abs(db - da) >= 0.08]
    lens = [abs(db - da) for da, db in long_]
    if len(lens) < 20:
        return None
    for S in (1.0, 0.5, 0.2, 0.1):
        if sum(1 for L in lens if abs(L - S) <= max(0.012, 0.1 * S)) >= 0.15 * len(lens):
            return S if _in_step(long_, S) else None
    return None


def _in_step(strokes, S, window=10.0):
    """whether the line's corners fall a whole number of steps apart down
    the log: readings S apart put every corner at one place in the step.
    A line LogViewer drew simplified (its corners where it bends, not at the
    readings) has strokes of many lengths, some near S by chance, its
    corners anywhere. Judged over each `window` metres (a page's depth
    scale can be a little off, so the place can drift down the log)"""
    by = collections.defaultdict(list)
    for da, db in strokes:
        for d in (da, db):
            by[int(d // window)].append((d / S) % 1.0)
    got = tot = 0
    for ph in by.values():
        if len(ph) < 6:
            continue
        best = max(sum(1 for q in ph if min(abs(q - c), 1 - abs(q - c)) <= 0.1) for c in ph)
        got += best
        tot += len(ph)
    return tot == 0 or got >= 0.5 * tot


def _shift(values, k, blend=True):
    """readings moved k grid steps deeper (k need not be whole: between two
    readings the value is taken straight between them, or with blend False
    (a curve drawn in steps) the nearer one, the deeper at half way)"""
    out = []
    for i in range(len(values)):
        x = i - k
        j = int(math.floor(x))
        f = x - j
        a = values[j] if 0 <= j < len(values) else None
        b = values[j + 1] if 0 <= j + 1 < len(values) else None
        if f < 1e-9:
            out.append(a)
        elif not blend or a is None or b is None:
            out.append(a if f < 0.5 else b)
        else:
            out.append(round(a + (b - a) * f, 4))
    return out


def _hold(values, top, step, every):
    """readings on the grid from top by step, each taken at its nearest
    depth that is a whole number of `every` metres (ties go deeper)"""
    n = len(values)
    out = []
    for i in range(n):
        d = top + i * step
        j = int(round((math.floor(d / every + 0.5 + 1e-9) * every - top) / step))
        out.append(values[j] if 0 <= j < n else None)
    return out


def _offset(main, other):
    """how another line of the curve's colour runs beside its main line,
    where the main line crosses a depth once inside the track: 0 the same
    line again, 1 the thin line one scale width off it (either way); None
    if it keeps no steady distance (another curve, or other marks)"""
    qs = collections.Counter()
    n = 0
    for ms, os_ in zip(main, other):
        if len(ms) != 1 or not os_ or not (0.01 < ms[0] < 0.99):
            continue
        n += 1
        ks = {abs(round(o - ms[0])) for o in os_ if abs(o - ms[0] - round(o - ms[0])) < 0.02}
        qs.update(ks)
    if n < 5 or not qs:
        return None
    k, m = qs.most_common(1)[0]
    return k if m >= 0.6 * n and k in (0, 1) else None


def _in_track(series):
    """the crossings inside the track only: the main line is held inside it"""
    e = wscale.EDGE
    return [[p for p in ps if -e <= p <= 1 + e] for ps in series]


def read_curves(doc, pages, lines_pt, top, bottom, step=STEP, strokes=None, dropped=None):
    """-> [{name, kind, units, unit, top, step, values, scale, colour,
    track_pt, past_scale}]. dropped, a list, gets (name, why) for each
    captioned curve whose line could not be read"""
    dropped = dropped if dropped is not None else []
    caps = []
    for P in pages:
        for c in L.captions(doc[P.page - 1], P.page - 1, P.across):
            x0, y0, x1, y1 = c.bbox
            # a caption is printed just below where its scale starts
            d = min(P.depth(x0, y0), P.depth(x1, y1)) - CAPTION_M
            # a note's word that took a depth label for a number (RPM 0
            # .. 1240 at 1241 m) is no caption: scales end on round numbers
            if any(abs(v - d) < 5 and v % 50 for v in (c.left, c.right)):
                continue
            # nor one that took a reading from the text (79.1): a scale's
            # ends of ten and more are whole numbers
            if any(abs(v) >= 10 and abs(v - round(v)) > 1e-6 for v in (c.left, c.right)):
                continue
            if P.on(d, 0.5):
                caps.append((d, c, P))
    # a number two captions both took (one curve's end, the other with no
    # number of its own on that side) belongs to the one in its track: no
    # line of the log between that one's name and the number
    def across_name(c, P):
        x0, y0, x1, y1 = c.bbox
        return sorted((P.across(x0, y0), P.across(x1, y1)))
    used = collections.defaultdict(list)
    for d, c, P in caps:
        used[(P.page, c.colour, round(c.left_at, 1), c.left)].append(c)
        used[(P.page, c.colour, round(c.right_at, 1), c.right)].append(c)
    shared = {id(c) for cs in used.values() if len({x.name for x in cs}) > 1 for c in cs}

    def apart(c, P):
        n0, n1 = across_name(c, P)
        return any(c.left_at + 1 < l < n0 - 1 or n1 + 1 < l < c.right_at - 1 for l in lines_pt)
    caps = [(d, c) for d, c, P in caps if not (id(c) in shared and apart(c, P))]
    # one curve per colour and name in a column: a curve captioned again
    # lower down, in full or cut short ("Gamma Ray", "Gam"), is the same
    # curve, named by its fullest caption; its scale from each caption down
    # the log
    curves = collections.OrderedDict()

    def same(a, b):          # one name the other cut short ("Gam", "mma Ray" in "Gamma Ray")
        a, b = re.sub(r"[^a-z0-9]", "", a.lower()), re.sub(r"[^a-z0-9]", "", b.lower())
        return bool(a and b) and (a in b or b in a)

    # a track at the side of the log can run to the page's edge, with no
    # line of its own there
    sides = [P.across(x, y) for P in pages for r in [doc[P.page - 1].rect] for x, y in ((r.x0, r.y0), (r.x1, r.y1))]
    edged = sorted(set(lines_pt) | ({min(sides), max(sides)} if sides else set()))
    # every scale each curve's own name is captioned with, down the whole
    # log (a name cut short is matched on all of them, not only those above)
    scales_of = collections.defaultdict(set)
    for d, c in caps:
        e = _track_edges(lines_pt, c.left_at, c.right_at) or _track_edges(edged, c.left_at, c.right_at)
        if e:
            scales_of[(c.colour, e, c.name)].add((c.left, c.right))
    for d, c in sorted(caps, key=lambda t: t[0]):
        e = _track_edges(lines_pt, c.left_at, c.right_at) or _track_edges(edged, c.left_at, c.right_at)
        if not e:
            continue
        # the same name (its scale may change down the log), or a name cut
        # short with a scale the curve is captioned with: two scales at
        # once are two curves
        key = next((k for k in curves if k[0] == c.colour and k[1] == e and (
            k[2] == c.name or (same(k[2], c.name) and (c.left, c.right) in scales_of[k]))), None)
        if key is None:
            key = (c.colour, e, c.name)
        curves.setdefault(key, []).append((d, c))
    # a caption that took another column's number (a depth label) lands in
    # a column of its own: of the curves of one colour and name, one with
    # a handful of captions beside one with many is that
    most = collections.Counter()
    for (colour, e, name), seen in curves.items():
        most[(colour, name)] = max(most[(colour, name)], len(seen))
    curves = collections.OrderedDict((k, v) for k, v in curves.items()
                                     if len(v) >= 3 or len(v) * 3 >= most[(k[0], k[2])])
    # a caption cut short by its column ("mma Ray") whose whole name is
    # another curve of its colour is that curve again, read in the wrong place
    def clipped(a, b):       # a starts inside one of b's words: "mma Ray" in "Gamma Ray"
        i = b.lower().find(a.lower())
        return a.lower() != b.lower() and i > 0 and b[i - 1].isalnum()

    curves = collections.OrderedDict(
        (k, v) for k, v in curves.items()
        if not any(o[0] == k[0] and clipped(k[2], o[2]) and len(curves[o]) >= len(v) for o in curves))
    strokes = strokes or Strokes(doc, pages)
    n = int(round((bottom - top) / step)) + 1
    # the curves captioned in one block share a track: where one curve's
    # line shows the track runs on past a line (_widen), so do the others'
    band = {}
    for (colour, e, _name) in curves:
        ws = strokes.of(colour)
        if not ws:
            continue
        wm = max(ws, key=lambda w: (_inside(_relative(ws[w], *e)), w))
        w0, w1 = _widen(ws[wm], lines_pt, *e)
        b0, b1 = band.get(e, e)
        band[e] = (min(b0, w0), max(b1, w1))
    # a block inside a wider one that shares an edge with it is the same
    # band (its numbers stacked at another height fell between other lines)
    # where the wider block captions a real curve (a known name and a unit,
    # not a note like "WOB")
    real = {e for (colour, e, _name), seen in curves.items()
            if len(seen) >= 2 and any(c.kind and c.unit for _d, c in seen)}
    for e1 in list(band):
        for e2 in real:
            if (e2 != e1 and e2[0] <= e1[0] and e2[1] >= e1[1] and (e2[0] == e1[0] or e2[1] == e1[1])
                    and e2[1] - e2[0] <= 1.5 * (e1[1] - e1[0])):
                a, b = band[e1], band.get(e2, e2)
                band[e1] = (min(a[0], b[0]), max(a[1], b[1]))
    grid = _grid_lines(doc, pages)
    out = []
    for (colour, (x0, x1), _name), seen in curves.items():
        x0, x1 = band.get((x0, x1), (x0, x1))
        g0, g1 = _grid_edges(grid, lines_pt, x0, x1)
        # a track run off the page (no line at its edge) with no grid to
        # say where it ends, on a logarithmic scale (no even grid either):
        # where the line is on it cannot be told
        off_page = (x0 not in lines_pt and g0 == x0) or (x1 not in lines_pt and g1 == x1)
        x0, x1 = g0, g1
        # a scale one caption alone gives, between two that agree, is a
        # misread number, not a change of scale
        seen = [t for i, t in enumerate(seen)
                if not (0 < i < len(seen) - 1
                        and (seen[i - 1][1].left, seen[i - 1][1].right) == (seen[i + 1][1].left, seen[i + 1][1].right)
                        != (t[1].left, t[1].right))]
        names = collections.Counter((c.name, c.unit, c.kind) for _d, c in seen)
        best = max(names, key=lambda k: (k[2] is not None, names[k], len(k[0]) + len(k[1] or "")))
        first = next(c for _d, c in seen if (c.name, c.unit, c.kind) == best)
        x0, x1 = _past_decade_lines(first, lines_pt, x0, x1)
        secs = []
        for d, c in seen:
            l_, r_ = _ends_from_decades(c, x0, x1)
            if not secs or (l_, r_) != secs[-1][1:]:
                secs.append((top if not secs else d, l_, r_))
        groups = {w: _relative(sg, x0, x1) for w, sg in strokes.of(colour).items()}
        groups = {w: sg for w, sg in groups.items() if sg}
        if not groups:
            dropped.append((first.name, "no line of its colour in its track"))
            continue
        wmain = max(groups, key=lambda w: (_inside(groups[w]), w))
        if _inside(groups[wmain]) < 0.05 * (bottom - top):
            dropped.append((first.name, "its line runs %.0f m of the log's %.0f m" % (_inside(groups[wmain]), bottom - top)))
            continue
        main = _in_track(_series(groups[wmain], top, n, step))
        # the line where it runs out of the track, past the scale: the
        # strokes with one end inside it (other marks of the colour beyond
        # the track, another column's lines, are not the curve)
        e = wscale.EDGE
        # for a curve drawn with one line: the line without straight runs
        # along the track's edges (a box's sides; a pinned line says nothing
        # the reader can write), and where it runs out of the track
        line = [sg for sg in groups[wmain] if not (abs(sg[1] - sg[3]) < 1e-4 and abs(sg[2] - sg[0]) > 0.3
                                                  and (abs(sg[1]) < 0.003 or abs(sg[1] - 1) < 0.003))
                and not (abs(sg[1] - sg[3]) < 1e-4 and abs(sg[2] - sg[0]) > 3.0)]   # one straight stroke over
        #                                                    3 m is a legend's sample line, not readings
        crossing = [sg for sg in line if (-e <= sg[1] <= 1 + e) != (-e <= sg[3] <= 1 + e)]
        whole = [ms + [p for p in ps if p < -e or p > 1 + e]
                 for ms, ps in zip(_in_track(_series(line, top, n, step)), _series(crossing, top, n, step))]
        flat = [sg for sg in _relative(strokes.of(colour, flats=True).get(wmain, []), x0, x1)
                if -0.5 < sg[1] < 1.5 and -0.5 < sg[3] < 1.5]
        moves = _moves(line + flat, top, n, step)
        wrap = [[] for _ in range(n)]
        for w, sg in groups.items():
            if w == wmain:
                continue
            ser = _series(sg, top, n, step)
            k = _offset(main, ser)
            if k == 0:
                for i, ps in enumerate(_in_track(ser)):
                    main[i] += ps
                    whole[i] += ps
            elif k == 1:
                for i, ps in enumerate(ser):
                    wrap[i] += ps
        two_lines = any(wrap)
        values, unsure, pinned = [None] * n, 0, {}
        for j, (d_from, left, right) in enumerate(secs):
            d_to = secs[j + 1][0] if j + 1 < len(secs) else bottom + step
            i0 = max(0, int(round((d_from - top) / step)))
            i1 = min(n, int(round((d_to - top) / step)))
            if two_lines:
                got = read_line(main[i0:i1], wrap[i0:i1], left, right)
            else:
                # a linear scale that starts above nothing (gamma 50 - 150)
                # can be run under: the line wraps in from the top there
                under = left != 0 and not (left > 0 and right > 0 and max(left, right) / min(left, right) >= 100)
                args = dict(under=under,
                            nulls={i - i0 for i in _null_dips(line, top, step, left, right) if i0 <= i < i1},
                            dives={i - i0 for i in _junk_dives(line, top, step, left, right) if i0 <= i < i1},
                            junk={i - i0 for i in _junk_flats(line, top, step, left, right) if i0 <= i < i1})
                got = read_one_line(whole[i0:i1], left, right, moves[i0:i1], **args)
                # a curve is in its scale most of the way (it is printed on it):
                # one read past it for most of the log started a width off (a
                # reading under the scale at the top, drawn in from the top)
                lo_, hi_ = min(left, right), max(left, right)
                tol = 0.02 * (hi_ - lo_)

                def past(g):
                    rs = [r[0] for r in g if r is not None and r[1]]
                    return sum(1 for v in rs if v < lo_ - tol or v > hi_ + tol) / len(rs) if rs else 0.0
                if past(got) > 0.5:
                    for k0 in ((-1, 1) if under else (1,)):
                        alt = read_one_line(whole[i0:i1], left, right, moves[i0:i1], k0=k0, **args)
                        if past(alt) < 0.5 * past(got):
                            got = alt
            for k, r in enumerate(got):
                if r is None:
                    continue
                if r[1]:
                    values[i0 + k] = round(r[0], 4)
                else:
                    pinned[i0 + k] = round(r[0], 4)
                    unsure += 1
        # a line along the edge where the scale is nothing (gas 0 - 500): a
        # reading of nothing, not one past the scale (it cannot go below)
        for j, (d_from, left, right) in enumerate(secs):
            zero = 0.0 if left == 0 else 1.0 if right == 0 else None
            if zero is None:
                continue
            d_to = secs[j + 1][0] if j + 1 < len(secs) else bottom + step
            for i in range(max(0, int(round((d_from - top) / step))), min(n, int(round((d_to - top) / step)))):
                # (with, on the other edge, the line one width on: a reading
                # of nothing is drawn on both)
                if values[i] is None and main[i] and any(abs(p - zero) < 0.01 for p in main[i]) \
                        and all(abs(p - zero) < 0.01 or abs(abs(p - zero) - 1) < 0.01 for p in main[i]):
                    values[i] = 0.0
        # a line along the scale's end otherwise is the reading there or past
        # it: the end is written (a detector pegged at its top reads its top),
        # and counted as past the scale
        for i, v in pinned.items():
            if values[i] is None:
                values[i] = v
        # a scale from above nothing over a thousandfold (a resistivity's over a
        # hundredfold: 0.2 - 2000, 1 - 100) is drawn logarithmic: the line's
        # place is the reading's logarithm between the ends; a gas scale
        # 10 - 1000 is not
        logs = []
        resist = "resistivity" in (first.kind or V.curve(first.name)["key"] or "")
        if off_page and any(l_ > 0 and r_ > 0 and max(l_, r_) / min(l_, r_) >= (100 if resist else 1000)
                            for _d, l_, r_ in secs):
            dropped.append((first.name, "its logarithmic scale runs off the page"))
            continue
        for j, (d_from, left, right) in enumerate(secs):
            if left > 0 and right > 0 and max(left, right) / min(left, right) >= (100 if resist else 1000):
                d_to = secs[j + 1][0] if j + 1 < len(secs) else bottom + step
                i0 = max(0, int(round((d_from - top) / step)))
                i1 = min(n, int(round((d_to - top) / step)))
                for i in range(i0, i1):
                    if values[i] is not None:
                        pos = (values[i] - left) / (right - left)
                        values[i] = round(left * (right / left) ** pos, 4)
                logs.append(round(d_from, 3))
        values = _fill(values, top, step)
        if sum(v is not None for v in values) < 10:
            dropped.append((first.name, "fewer than 10 readings"))
            continue
        # LogViewer draws a reading half its recorded step shallower than
        # its depth; the step is the spacing of the line's corners down the
        # log. The readings are put back where the log has them.
        # (from the strokes in this track only: a curve of the same colour
        # in another track is no part of this one's line)
        own = [sg for sg in groups[wmain] if -0.02 <= sg[1] <= 1.02 and -0.02 <= sg[3] <= 1.02]
        rec = _recorded_step(own)
        half = rec / 2 if rec else 0.0
        if half >= step / 4:
            long_ = [sg for sg in own if abs(sg[2] - sg[0]) >= 0.08]
            steps = long_ and sum(abs(sg[1] - sg[3]) < 1e-4 for sg in long_) > 0.5 * len(long_)
            values = _shift(values, half / step, blend=not steps)     # a step drawn flat is not blended
            # each reading held from half way to the reading before to half
            # way to the next, as the log's own LAS holds it (the line drawn
            # between readings is LogViewer's, not a reading)
            values = _hold(values, top, step, rec)
        vc = V.curve(first.name)
        out.append({"name": first.name, "kind": first.kind or vc["key"], "units": first.unit,
                    "unit": V.unit(first.unit)["key"] if first.unit else None,
                    "top": round(top, 3), "step": step, "values": values,
                    "scale": [[round(d, 3), l, r] for d, l, r in secs], "colour": "#%06x" % colour,
                    "track_pt": [round(x0, 1), round(x1, 1)], "past_scale": unsure,
                    "recorded_step": rec, "shifted_m": round(half, 3) if half >= step / 4 else 0.0,
                    "log_scale_from": logs, "lines": 2 if two_lines else 1})
    return out


# ---------------------------------------------------------------- columns

def track_keys(title):
    """the data a column of the log holds, from its title (as
    wellsight_layout names a track's)"""
    t = (title or "").strip()
    low = t.lower()
    keys = set()
    k = V.key("column", t)
    if k:
        keys.add(k)
    if V.curve_track(t):
        keys.add("curves")
    if V.depth_column(t) or low == "depth" or V.curve(t)["key"] in ("md", "tvd"):
        keys |= {"depth", "interval"}
    if "slide" in low or "rotate" in low:
        keys.add("directional")
    if "%" in low and "lith" in low:
        keys.add("pct")
    elif "lith" in low or "cross section" in low:
        keys.add("rock")              # a horizontal log draws the rocks along its cross-section
    if "descr" in low or "geolog" in low:
        keys.add("descriptions")
    return sorted(keys)


def _header_row(pg, P, lines_pt, band_m):
    """(top, bottom): the depths of the header row over the log's columns
    on its first page, None if there is none. The long lines between the
    columns run up from the log through the boxed header row: its top is
    where they start (a top two lines agree on, so one long frame line does
    not take the row up the page), its bottom the first line drawn across
    the columns below that (None if there is none: the row runs to the
    log's first depth label)."""
    runs = collections.defaultdict(list)          # line across -> [(upper, lower)] depths
    across = []                                    # (depth, a0, a1) of lines drawn across the log
    near = lambda a: min(lines_pt, key=lambda x: abs(x - a))
    for d in pg.get_drawings():
        col = d.get("color")
        if not col or max(col) > 0.35:
            continue                               # a fill, or not a dark line
        for it in d["items"]:
            if it[0] == "l":
                segs = [(it[1], it[2])]
            elif it[0] == "re":
                r = it[1]
                segs = [(r.tl, r.bl), (r.tr, r.br), (r.tl, r.tr), (r.bl, r.br)]
            else:
                continue
            for p, q in segs:
                a0, a1 = P.across(p.x, p.y), P.across(q.x, q.y)
                d0, d1 = P.depth(p.x, p.y), P.depth(q.x, q.y)
                if abs(d0 - d1) < 0.02 and abs(a0 - a1) > 1.0:
                    across.append(((d0 + d1) / 2, min(a0, a1), max(a0, a1)))
                if abs(a0 - a1) > 0.3 or abs(d0 - d1) < 0.05:
                    continue
                x = near(a0)
                if abs(x - a0) <= 1.0:
                    runs[x].append((min(d0, d1), max(d0, d1)))
    tops = []
    for x, segs in runs.items():
        segs.sort()
        cur = None
        for u, lo in segs + [(math.inf, math.inf)]:   # join the line's pieces, then take the one at the log's top
            if cur and u <= cur[1] + 0.3:
                cur[1] = max(cur[1], lo)
                continue
            if cur and P.lo - band_m < cur[0] < P.lo - 0.2 and cur[1] >= P.lo - 0.3:
                tops.append(cur[0])
            cur = [u, lo]
    tops.sort()
    top = next((t for t in tops if len(tops) == 1 or sum(abs(u - t) <= 0.5 for u in tops) >= 2), None)
    if top is None:
        return None
    width = lines_pt[-1] - lines_pt[0]
    spans = collections.defaultdict(list)          # a line across, its pieces joined
    for dep, a0, a1 in across:
        if dep > top + 0.3:
            spans[round(dep * 20)].append((a0, a1))
    bottom = None
    for k in sorted(spans):
        cover, end = 0.0, -math.inf
        for a0, a1 in sorted(spans[k]):
            a0 = max(a0, end)
            if a1 > a0:
                cover += a1 - a0
                end = a1
        if cover >= 0.8 * width:
            bottom = k / 20
            break
    return top, bottom


def _header_pieces(pg, P, lo, hi):
    """the words between depths lo and hi on a page, also cut where the
    letters of a word part (two titles printed with no space between them
    read as one word): [(order, across, text, size)]. Letters a column
    clips are kept: the title is read whole even where the printout shows
    only its middle."""
    import fitz
    flags = fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_MEDIABOX_CLIP
    out = []
    for bi, b in enumerate(pg.get_text("rawdict", flags=flags)["blocks"]):
        for li, ln in enumerate(b.get("lines", [])):
            for si, sp in enumerate(ln["spans"]):
                size = sp["size"]
                piece, prev, k = [], None, 0
                for ch in sp["chars"] + [None]:
                    if ch is not None:
                        r = ch["bbox"]
                        gap = 0.0 if prev is None else max(r[0] - prev[2], prev[0] - r[2], r[1] - prev[3], prev[1] - r[3])
                    if ch is None or ch["c"].isspace() or (piece and gap > 0.25 * size):
                        text = "".join(c["c"] for c in piece).strip()
                        if text:
                            xs = [(c["bbox"][0] + c["bbox"][2]) / 2 for c in piece]
                            ys = [(c["bbox"][1] + c["bbox"][3]) / 2 for c in piece]
                            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
                            if lo < P.depth(cx, cy) < hi:
                                out.append(((bi, li, si, k), P.across(cx, cy), " ".join(text.split()), size))
                        piece, k = [], k + 1
                    if ch is not None and not ch["c"].isspace():
                        piece.append(ch)
                        prev = ch["bbox"]
    return out


def read_tracks(doc, pages, lines_pt, legend, band_m=15.0, min_pt=5.0, row=False):
    """the log's columns across the stitched log, between its long lines,
    each titled by the header row printed over it on the first log page:
    [{title, keys, x0, x1}]. The header row runs up from the top of the log
    as far as the lines between the columns do (else band_m, and not into
    the legend). Over each column the largest text is its title; a column
    whose header holds curve captions ("Gamma (API)") holds curves. row:
    the header row's (top, bottom) depths, if worked out already."""
    if not pages or len(lines_pt) < 2:
        return []
    P = min(pages, key=lambda q: q.page)
    pg = doc[P.page - 1]
    lo = P.lo - band_m
    for sw in legend:                                    # the header row starts below the legend
        if sw.page == P.page:
            x0, y0, x1, y1 = sw.bbox
            d = max(P.depth(x0, y0), P.depth(x1, y1))
            if d < P.lo:
                lo = max(lo, d + 1.0)
    hi = P.lo + 0.2
    if row is False:                                    # not worked out by the caller
        row = _header_row(pg, P, lines_pt, band_m)
    if row:
        lo = max(lo, row[0] - 0.05)
        hi = row[1] if row[1] else hi
    pieces = [w for w in _header_pieces(pg, P, lo, hi) if not NUMERIC.match(w[2])]
    out = []
    for x0, x1 in zip(lines_pt, lines_pt[1:]):
        if x1 - x0 < min_pt:
            continue
        mine = [w for w in pieces if x0 < w[1] < x1]
        title = ""
        keys = set()
        if mine:
            big = max(w[3] for w in mine)
            # in the PDF's own order: a title printed up the page reads in
            # that order, not top to bottom
            title = " ".join(w[2] for w in sorted(mine) if w[3] >= big - 0.25)
            lines = collections.defaultdict(list)
            for w in sorted(mine):
                lines[w[0][:2]].append(w[2])
            for words in lines.values():
                text = " ".join(words)
                m = L._UNIT.match(text)
                if m and m.group(2) and V.curve(text)["key"] not in (None, "md", "tvd"):
                    keys.add("curves")          # a curve's caption in the column's header
        keys |= set(track_keys(title))
        out.append({"title": title, "keys": sorted(keys), "x0": round(x0, 1), "x1": round(x1, 1)})
    return out


NUMERIC = re.compile(r"^[-+]?\d+(\.\d+)?$")


# ---------------------------------------------------------------- reading

PARTS = ("header", "text", "rocks", "symbols", "intervals", "curves", "tracks")


def read(pdf, parts=None, library=None):
    """pdf: a path or bytes. -> the reading, in the answer key's fields,
    plus "legend" (what the legend says) and "notes". library: a legend
    library (validation-tools/pdf_legend_library.py), its file or its
    contents, to name pictures this printout's legend leaves out."""
    import fitz
    import wellsight_print as wp
    doc = fitz.open(stream=pdf, filetype="pdf") if isinstance(pdf, (bytes, bytearray)) else fitz.open(pdf)
    parts = set(parts or PARTS)
    dr = _depth_range(doc)
    if not dr:
        return {"reader": READER, "error": "no depth labels found"}
    src = pdf if isinstance(pdf, (bytes, bytearray)) else doc.tobytes()
    # stitched a page wider each way, so the first and last pages of the log
    # (too few labels of their own) are mapped; then cut to the labels'
    # range, counting the labels on those pages too
    page_m = max(doc[0].rect.width, doc[0].rect.height) * dr[2]
    _strip, info = wp.stitch(src, dr[0] - page_m, dr[1] + page_m)
    every = [Page(pl) for pl in info["placed"]]
    rng = _labelled_range(doc, every, dr[:2])
    pages = []
    for P in every:
        P.lo, P.hi = max(P.lo, rng[0]), min(P.hi, rng[1])
        if P.hi - P.lo > 0.005:
            pages.append(P)
    if not pages:
        return {"reader": READER, "error": "no log pages within the depth labels"}
    top, bottom = rng
    # the log starts below the header row over its columns (the labels'
    # range is widened a label's step, which can reach up into the row)
    P0 = min(pages, key=lambda q: q.page)
    row = _header_row(doc[P0.page - 1], P0, info.get("lines_pt") or [], 15.0) \
        if len(info.get("lines_pt") or []) >= 2 else None
    if row and row[1] and P0.lo < row[1] < P0.hi:
        P0.lo = row[1]
        top = round(math.ceil(row[1] / STEP - 1e-6) * STEP, 3)     # readings on round depths
    out = {"reader": READER, "depth": {"unit": "m", "top": round(top, 3), "bottom": round(bottom, 3)},
           "printout": {"pages": info["pages"], "pt_per_m": info["pt_per_m"],
                        "depth_on_page": info["depth_axis_on_page"],
                        "log_pages": [P.page for P in pages]}, "notes": []}
    first_log = min(P.page for P in pages) - 1
    if "header" in parts:
        P = min(pages, key=lambda q: q.page)
        lim = row[0] if row else P.lo - 0.5                # above the header row over the columns
        above = (doc[P.page - 1], lambda w, P=P: P.depth((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) < lim)
        out["header"] = read_header([doc[i] for i in range(first_log)] + [above])
    if "text" in parts:
        out["text"] = read_text(doc, pages)
    sw = legend_of(doc, pages) if parts & {"rocks", "symbols", "intervals", "tracks"} else []
    if "tracks" in parts:
        out["tracks"] = read_tracks(doc, pages, info.get("lines_pt") or [], sw, row=row)
    if parts & {"rocks", "symbols", "intervals"}:
        if isinstance(library, str):
            import json
            with open(library, encoding="utf-8") as f:
                library = json.load(f)
        lib = L.Library(sw, doc, shelf=library)
        out["legend"] = [s.as_dict() for s in lib.swatches]
        tiles, symbols, unknown = read_pictures(doc, pages, lib)
        if "rocks" in parts:
            out["rocks"] = rocks_from_tiles(tiles)
        if "intervals" in parts:
            out["intervals"] = intervals_from_tiles(tiles)
        if "symbols" in parts:
            out["symbols"] = symbols
        if not sw:
            out["notes"].append("no legend found" + (": the pictures on the log cannot be named"
                                                     if not lib.shelf else ""))
        if lib.from_shelf:
            out["notes"].append("%d pictures named from other printouts' legends" % lib.from_shelf)
        if unknown:
            out["notes"].append("%d pictures on the log are not in the legend" % unknown)
    if "curves" in parts:
        dropped = []
        out["curves"] = read_curves(doc, pages, info.get("lines_pt") or [], top, bottom, dropped=dropped)
        if not out["curves"]:
            out["notes"].append("no curve captions found")
        for name, why in dropped:
            out["notes"].append("%s is captioned but not read: %s" % (name, why))
    return out
