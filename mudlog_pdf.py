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
                    if abs(da - db) < 1e-4 or not (P.on(da, 0.01) or P.on(db, 0.01)):
                        continue
                    aa, ab = P.across(p.x, p.y), P.across(q.x, q.y)
                    out.append((da, aa, db, ab) if da < db else (db, ab, da, aa))

    def of(self, colour):
        want = L.rgb(colour)
        for key, groups in self.by.items():
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
    out, last = [], None

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
            elif any(abs(m - u) < agree for m in vm):
                either += [u, up, down]
            elif not vm and last is not None:
                sure += [c for c in (up, down) if abs(c - last) < span / 4]
        r = None
        if sure:
            r = (near(sure), True)
        elif either:
            r = (near(either) if last is not None else min(either, key=lambda c: abs(c - (lo + hi) / 2)), True)
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


def read_one_line(series, left, right):
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
    end, the one below it). Between, the line in the track is the reading, one
    scale width on while wrapped; a jump of over half the track with no
    pair drawn is taken as a wrap too (wellsight_scales.read_drawn's rule)."""
    lo, hi = min(left, right), max(left, right)
    e = wscale.EDGE
    out, k, last = [], 0, None                   # k: scale widths the line in the track is off the reading

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

    for i, ps in enumerate(series):
        pts = sorted(ps or ())
        pairs = [(a, b) for j, a in enumerate(pts) for b in pts[j + 1:] if abs(b - a - 1) < 0.03]
        if pairs and any(b > 1 + e for a, b in pairs) and k != 1:
            a, b = pairs[-1]
            if not carries_on(i, a):
                pairs = [(a, b) for a, b in pairs if b <= 1 + e]
        r = None
        if pairs:
            a, b = pairs[-1] if any(b > 1 + e for a, b in pairs) else pairs[0]
            if b > 1 + e:
                r, k = b, 1
            elif a < -e:
                # below the low end only where the line already is (mudlog
                # readings rarely go under a scale that starts at nothing)
                r, k = (a, -1) if k == -1 else (b, 0)
            else:
                r, k = nearest([(b, 0), (a, 0)])
            out.append((val(r), True))
            last = r
            continue
        inside = [p for p in pts if -e <= p <= 1 + e]
        if not inside:
            past = [p for p in pts if p < -e or p > 1 + e]
            if past and last is not None:
                r = min(past, key=lambda p: abs(p - last))
                if abs(r - last) < 0.5:
                    k = 1 if r > 1 else -1
                    out.append((val(r), True))
                    last = r
                    continue
            out.append(None)
            continue
        mid = [p for p in inside if e < p < 1 - e]
        if mid:
            p = min(mid, key=lambda m: abs(m + k - last)) if last is not None else mid[0]
            if last is not None and abs(p + k - last) > 0.5:
                if p + k < last:
                    k = min(1, k + 1)            # in from the low end: wrapped (or back from below it)
                else:
                    k = max(0, k - 1)            # back out of the low end (below the scale only where drawn so)
            out.append((val(p + k), True))
            last = p + k
        elif any(p >= 1 - e for p in inside):
            out.append((val(1 + k), k != 0) if k else (hi if right > left else lo, False))
            last = 1 + k
        else:
            out.append((val(k), k != 0) if k else (lo if right > left else hi, False))
            last = 0.0 + k
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


def read_curves(doc, pages, lines_pt, top, bottom, step=STEP, strokes=None):
    """-> [{name, kind, units, unit, top, step, values, scale, colour,
    track_pt, past_scale}]"""
    caps = []
    for P in pages:
        for c in L.captions(doc[P.page - 1], P.page - 1, P.across):
            x0, y0, x1, y1 = c.bbox
            # a caption is printed just below where its scale starts
            d = min(P.depth(x0, y0), P.depth(x1, y1)) - CAPTION_M
            if P.on(d, 0.5):
                caps.append((d, c))
    # one curve per name and colour; its scale from each caption down the log
    curves = collections.OrderedDict()
    for d, c in sorted(caps, key=lambda t: t[0]):
        curves.setdefault((c.name, c.unit, c.colour), []).append((d, c))
    strokes = strokes or Strokes(doc, pages)
    n = int(round((bottom - top) / step)) + 1
    out = []
    for (_name, _unit, colour), seen in curves.items():
        first = seen[0][1]
        edges = collections.Counter()
        for _d, c in seen:
            e = _track_edges(lines_pt, c.left_at, c.right_at)
            if e:
                edges[e] += 1
        if not edges:
            continue
        x0, x1 = edges.most_common(1)[0][0]
        secs = []
        for d, c in seen:
            if not secs or (c.left, c.right) != secs[-1][1:]:
                secs.append((top if not secs else d, c.left, c.right))
        groups = {w: _relative(sg, x0, x1) for w, sg in strokes.of(colour).items()}
        groups = {w: sg for w, sg in groups.items() if sg}
        if not groups:
            continue
        wmain = max(groups, key=lambda w: (_inside(groups[w]), w))
        if _inside(groups[wmain]) < 0.05 * (bottom - top):
            continue
        main = _in_track(_series(groups[wmain], top, n, step))
        # the line where it runs out of the track, past the scale: the
        # strokes with one end inside it (other marks of the colour beyond
        # the track, another column's lines, are not the curve)
        e = wscale.EDGE
        crossing = [sg for sg in groups[wmain] if (-e <= sg[1] <= 1 + e) != (-e <= sg[3] <= 1 + e)]
        whole = [ms + [p for p in ps if p < -e or p > 1 + e]
                 for ms, ps in zip(main, _series(crossing, top, n, step))]
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
        values, unsure = [None] * n, 0
        for j, (d_from, left, right) in enumerate(secs):
            d_to = secs[j + 1][0] if j + 1 < len(secs) else bottom + step
            i0 = max(0, int(round((d_from - top) / step)))
            i1 = min(n, int(round((d_to - top) / step)))
            if two_lines:
                got = read_line(main[i0:i1], wrap[i0:i1], left, right)
            else:
                got = read_one_line(whole[i0:i1], left, right)
            for k, r in enumerate(got):
                if r is None:
                    continue
                if r[1]:
                    values[i0 + k] = round(r[0], 4)
                else:
                    unsure += 1
        values = _fill(values, top, step)
        if sum(v is not None for v in values) < 10:
            continue
        vc = V.curve(first.name)
        out.append({"name": first.name, "kind": first.kind or vc["key"], "units": first.unit,
                    "unit": V.unit(first.unit)["key"] if first.unit else None,
                    "top": round(top, 3), "step": step, "values": values,
                    "scale": [[round(d, 3), l, r] for d, l, r in secs], "colour": "#%06x" % colour,
                    "track_pt": [round(x0, 1), round(x1, 1)], "past_scale": unsure})
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
        out["curves"] = read_curves(doc, pages, info.get("lines_pt") or [], top, bottom)
        if not out["curves"]:
            out["notes"].append("no curve captions found")
    return out
