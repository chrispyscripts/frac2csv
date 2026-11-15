"""A mudlog printout's own legend: what each picture on the log means, and
each curve's name, colour and scale, read off the printout.

A printed mudlog says what its marks mean twice over: a legend (a small
picture of each rock pattern and symbol, its label beside it, under a
heading) and, along the curve track, a caption for each curve in the
curve's own colour, the scale's two ends either side of its name. Reading
those instead of a list of one program's patterns and colours is what lets
a reader carry over to printouts it has not seen.

  legend(doc) -> [Swatch]: every legend picture with its label, the heading
                 it sits under and what log_vocab makes of the two: a rock,
                 or a symbol (group, term)
  Library     a legend's pictures, looked up by the exact picture first and
              then by look (a printout that draws the same pattern again at
              another size)
  captions(page) -> [Caption]: the curve captions on a page: name, unit,
                 colour, the scale's two numbers and where they sit

A legend picture's label is the code the log file gives it ("Sltst",
"Pyr"), so log_vocab names it as it names the file's codes. A heading names
a group as files name their symbol categories ("MINERAL", "OIL SHOWS"); a
box title that is not a group ("ACCESSORIES") starts a box with none.

Needs PyMuPDF.
"""
import bisect
import collections
import math
import re

import log_vocab as V
import wellsight_symbols as wsym

SWATCH_MAX_W = 80.0      # pt: a legend picture is a small one; a frame or logo is not
SWATCH_MAX_H = 24.0
LABEL_GAP = 60.0         # pt from a picture's right edge to its label at most
ROW_TOL = 4.5            # pt: a label's middle within the picture's height, give or take this
COLUMN_TOL = 20.0        # pt: entries this close across are one column of a box
NUMBER = re.compile(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?$")    # (a log scale's top may be printed 1e4)


class Swatch:
    __slots__ = ("page", "bbox", "digest", "xref", "px", "label", "heading", "group", "term", "look")

    def __init__(self, page, bbox, digest, xref, px):
        self.page, self.bbox, self.digest, self.xref, self.px = page, bbox, digest, xref, px
        self.label = self.heading = self.group = self.term = None
        self.look = None

    def as_dict(self):
        return {"page": self.page, "bbox": [round(v, 2) for v in self.bbox], "label": self.label,
                "heading": self.heading, "group": self.group, "term": self.term}

    def __repr__(self):
        return "Swatch(%s %s:%s %r)" % (self.label, self.group, self.term, [round(v, 1) for v in self.bbox])


def _lines(pg, by_colour=False):
    """the page's text lines: (bbox, text, colour as 0xRRGGBB, size). With
    by_colour, a line is cut where its colour changes (one curve's number
    run into the next curve's caption: "0 SPP (kPa)")"""
    out = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            runs = [[spans[0]]]
            for s in spans[1:]:
                if by_colour and s["color"] != runs[-1][-1]["color"]:
                    runs.append([s])
                else:
                    runs[-1].append(s)
            for run in runs:
                text = " ".join(s["text"].strip() for s in run)
                bb = tuple(ln["bbox"]) if len(runs) == 1 else (
                    min(s["bbox"][0] for s in run), min(s["bbox"][1] for s in run),
                    max(s["bbox"][2] for s in run), max(s["bbox"][3] for s in run))
                out.append((bb, text, run[0]["color"], run[0]["size"]))
    return out


def _label_like(t):
    """a legend label is a code or a word or two, not a line of notes"""
    t = t.strip()
    return 0 < len(t) <= 24 and len(t.split()) <= 3 and not t[0].isdigit()


def _is_heading_text(t):
    letters = re.sub(r"[^A-Za-z]", "", t)
    return len(letters) >= 3 and letters.isupper() and len(t) <= 40


def term_of(group, label):
    """(group, term) for a legend label under a group: the label is the
    code the log file uses, so it is named as the file's codes are"""
    if group == "rock":
        return group, wsym.rock_term(label)[0]
    k = wsym._key(label)
    if "SLIDE" in k or "ROTATE" in k:
        group = "directional"
    g = wsym._REFILE.get((group, k), group)
    return g, wsym.normalise(g, label)[0]


def legend(doc, pages=None):
    """-> [Swatch] for every legend picture on the given pages (all, if
    None) that has a label beside it"""
    out = []
    for pno in (range(len(doc)) if pages is None else pages):
        out += _page_legend(doc[pno], pno)
    return out


def _page_legend(pg, pno):
    imgs = []
    for im in pg.get_image_info(hashes=True, xrefs=True):
        x0, y0, x1, y1 = im["bbox"]
        w, h = x1 - x0, y1 - y0
        if 1.5 < w <= SWATCH_MAX_W and 1.5 < h <= SWATCH_MAX_H:
            imgs.append(Swatch(pno + 1, (x0, y0, x1, y1), im.get("digest"), im.get("xref"),
                               (im["width"], im["height"])))
    if not imgs:
        return []
    lines = _lines(pg)
    # lines and pictures indexed by the middle of their height, so each
    # picture looks only along its own row (a log page holds thousands)
    by_ym = sorted(((bb[1] + bb[3]) / 2, i) for i, (bb, _t, _c, _s) in enumerate(lines))
    yms = [y for y, _i in by_ym]
    img_rows = sorted(((o.bbox[1] + o.bbox[3]) / 2, k) for k, o in enumerate(imgs))
    img_ys = [y for y, _k in img_rows]
    tallest = max(o.bbox[3] - o.bbox[1] for o in imgs)
    used = set()
    found = []
    for s in imgs:
        x0, y0, x1, y1 = s.bbox
        best = None
        for j in range(bisect.bisect_left(yms, y0 - ROW_TOL), bisect.bisect_right(yms, y1 + ROW_TOL)):
            i = by_ym[j][1]
            gap = lines[i][0][0] - x1
            if -1.0 <= gap <= LABEL_GAP and (best is None or gap < best[0]):
                best = (gap, i)
        if best is None or not _label_like(lines[best[1]][1]):
            continue
        # a picture between its neighbour and that one's label is not this one's
        bb = lines[best[1]][0]
        between = False
        for j in range(bisect.bisect_left(img_ys, y0 - tallest), bisect.bisect_right(img_ys, y1 + tallest)):
            o = imgs[img_rows[j][1]]
            if o is not s and o.bbox[0] > x1 - 0.5 and o.bbox[2] < bb[0] + 0.5 and \
                    o.bbox[1] < y1 and o.bbox[3] > y0:
                between = True
                break
        if between:
            continue
        s.label = lines[best[1]][1].strip()
        used.add(best[1])
        found.append(s)
    if not found:
        return []

    # headings and box titles: capitals on their own, no picture beside them
    heads = []
    for i, (bb, text, _c, _sz) in enumerate(lines):
        if i in used or not _is_heading_text(text):
            continue
        g = V.key("category", text)
        heads.append((bb, text.strip(), g))

    # boxes: a title spans the box, so each entry and heading belongs to the
    # nearest title above it; reading order inside a box runs down each
    # column, the columns left to right
    # a box's title stands alone on its row, over the box ("ROCK TYPES",
    # "ACCESSORIES"); a column's heading shares its row with other columns'
    # entries and starts its column ("FOSSIL")
    starts = [s.bbox[0] for s in found]
    titles = sorted([h for h in heads if _alone(h[0], found) and
                     (h[2] is None or _centred(h[0], found) or
                      min(abs(h[0][0] - x) for x in starts) > COLUMN_TOL)], key=lambda h: h[0][1])

    def box_of(y):
        k = -1
        for j, h in enumerate(titles):
            if h[0][1] <= y + 0.5:
                k = j
        return k

    cols = _columns([s.bbox[0] for s in found])

    def col_of(x):
        return min(range(len(cols)), key=lambda j: abs(cols[j] - x))

    seq = []
    for s in found:
        seq.append((box_of(s.bbox[1]), col_of(s.bbox[0]), s.bbox[1], 1, s))
    for h in heads:
        if h in titles:
            seq.append((box_of(h[0][1]), -1, h[0][1], 0, h))
        else:
            seq.append((box_of(h[0][1]), col_of(h[0][0]), h[0][1], 0, h))
    seq.sort(key=lambda r: r[:4])
    group, heading, box = None, None, None
    for b, _c, _y, kind, item in seq:
        if b != box:
            box, group, heading = b, None, None
        if kind == 0:
            heading, group = item[1], item[2]
            continue
        item.heading = heading
        if group:
            item.group, item.term = term_of(group, item.label)
    return found


def _alone(bb, found):
    """no legend picture beside a heading, on its row"""
    return not any(s.bbox[1] < bb[3] - 1 and s.bbox[3] > bb[1] + 1 for s in found)


def _centred(bb, found):
    """a heading over the middle of the legend"""
    xs = [s.bbox[0] for s in found] + [s.bbox[2] for s in found]
    mid = (min(xs) + max(xs)) / 2
    return abs((bb[0] + bb[2]) / 2 - mid) < 0.15 * (max(xs) - min(xs))


def _columns(xs):
    out = []
    for x in sorted(xs):
        if out and x - out[-1][-1] <= COLUMN_TOL:
            out[-1].append(x)
        else:
            out.append([x])
    return [sum(c) / len(c) for c in out]


# ---------------------------------------------------------------- looking up

LOOK_W, LOOK_H = 12, 12          # a picture's look: its colours on a grid this size
LOOK_MAX = 0.12                  # mean colour difference (0..1) for a look-alike
LOOK_ASPECT = 0.2                # ... of the same shape, width over height within 20 %
LOOK_PX_MAX = 512                # ... and no bigger than this (a frame or a photo is no symbol)


def look(doc, xref):
    """a picture's colours on a LOOK_W x LOOK_H grid, 0..1 per channel; None
    if it cannot be read"""
    import fitz
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.n - pix.alpha != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
    except Exception:  # noqa: BLE001 - a picture PyMuPDF cannot read has no look
        return None
    w, h, s = pix.width, pix.height, pix.samples
    out = []
    for gy in range(LOOK_H):
        ya, yb = gy * h // LOOK_H, max(gy * h // LOOK_H + 1, (gy + 1) * h // LOOK_H)
        for gx in range(LOOK_W):
            xa, xb = gx * w // LOOK_W, max(gx * w // LOOK_W + 1, (gx + 1) * w // LOOK_W)
            acc = [0, 0, 0]
            n = 0
            for y in range(ya, min(yb, h)):
                row = y * pix.stride
                for x in range(xa, min(xb, w)):
                    o = row + x * 3
                    acc[0] += s[o]; acc[1] += s[o + 1]; acc[2] += s[o + 2]
                    n += 1
            out.append(tuple(a / (255.0 * max(n, 1)) for a in acc))
    return out


def _distance(a, b):
    return sum(abs(p - q) for u, v in zip(a, b) for p, q in zip(u, v)) / (3 * len(a))


class Library:
    """a legend's pictures, to name the pictures on the log by. find()
    takes the exact picture first; with look_alike, a rock pattern stored
    again at another size is matched by its look: its colours on a small
    grid, within LOOK_MAX of the legend picture's. Symbols are matched
    exactly only: most are a letter in a box, too alike at that size."""

    def __init__(self, swatches, doc=None, look_alike=True, shelf=None):
        self.by_digest = {}
        self.swatches = [s for s in swatches if s.term]
        for s in self.swatches:
            self.by_digest.setdefault(s.digest, s)
        # pictures other printouts' legends name (validation-tools/
        # pdf_legend_library.py), for those this legend leaves out
        self.shelf = {}
        for hexdig, e in ((shelf or {}).get("by_digest") or {}).items():
            sw = Swatch(None, None, bytes.fromhex(hexdig), None, tuple(e.get("px") or (0, 0)))
            sw.group, sw.term, sw.label = e["group"], e["term"], e.get("label")
            self.shelf[sw.digest] = sw
        self.from_shelf = 0
        self.doc = doc
        self.look_alike = look_alike and doc is not None
        self._looks = {}
        if self.look_alike:
            for s in self.swatches:
                if s.group == "rock":
                    s.look = self._look(s.xref)

    def _look(self, xref):
        if xref not in self._looks:
            self._looks[xref] = look(self.doc, xref) if xref else None
        return self._looks[xref]

    def find(self, digest, xref=None, px=None):
        s = self.by_digest.get(digest)
        if s is None and digest in self.shelf:
            self.from_shelf += 1
            return self.shelf[digest]
        if s is not None or not self.look_alike or not xref or not px:
            return s
        if max(px) > LOOK_PX_MAX or min(px) < 2:
            return None
        lk = self._look(xref)
        if lk is None:
            return None
        best = None
        aspect = px[0] / float(px[1])
        for c in self.swatches:
            # patterns only: symbols are mostly a letter in a box, too
            # alike at this size to tell one from another by look
            if c.look is None or c.group != "rock":
                continue
            # the same picture at another size keeps its shape
            if abs(math.log(aspect / (c.px[0] / float(c.px[1])))) > LOOK_ASPECT:
                continue
            d = _distance(lk, c.look)
            if best is None or d < best[0]:
                best = (d, c)
        return best[1] if best and best[0] <= LOOK_MAX else None


# ---------------------------------------------------------------- curve captions

class Caption:
    __slots__ = ("page", "bbox", "name", "kind", "unit", "colour", "left", "right", "left_at", "right_at")

    def __init__(self, page, bbox, name, kind, unit, colour):
        self.page, self.bbox, self.name, self.kind, self.unit, self.colour = page, bbox, name, kind, unit, colour
        self.left = self.right = self.left_at = self.right_at = None

    def as_dict(self):
        return {"page": self.page, "name": self.name, "kind": self.kind, "unit": self.unit,
                "colour": "#%06x" % self.colour, "left": self.left, "right": self.right}

    def __repr__(self):
        return "Caption(%s [%s] %s..%s #%06x p%d)" % (self.name, self.unit, self.left, self.right, self.colour, self.page)


_UNIT = re.compile(r"^(.*?)\s*\(\(?([^()]*)\)?\)\s*$")       # "Gamma (API)", "Neutron ((%))"


# a note printed by a curve, not its caption: a reading or range in its
# name ("Den:1130", "MW 1070", "ROP 0-10", "1924.5 TVD", "BIT # 3"); a
# curve's own name holds at most a one-digit number ("C1", "Leg 2")
_NOTE = re.compile(r"\d{2,}|\d+\.\d+|\d\s*-\s*\d|:\s*\d|#")


def _caption_name(text):
    """(name, unit text, curve kind) for a caption's name, or None"""
    t = text.strip()
    m = _UNIT.match(t)
    name, unit = (m.group(1), m.group(2)) if m else (t, "")
    if _NOTE.search(name or "") and unit and re.fullmatch(r"[A-Za-z][A-Za-z .]*?\s+\d{2,3}", name.strip()) \
            and V.curve(re.sub(r"\s+\d+$", "", name.strip()))["key"]:
        pass                    # a known curve with a number in its name and a unit: "Gamma 180 (API)"
    elif not name or NUMBER.match(name) or _NOTE.search(name) or re.search(r"\d\s*-\s*\d", unit or ""):
        return None             # a note: a reading or range in the name, or a range for a unit
    vc = V.curve(t)
    if not vc["key"]:
        vc = V.curve(name)
    if not vc["key"] and not unit:
        return None
    if vc["key"] in ("md", "tvd") or name.strip().upper() in ("VD", "TV", "SS"):
        return None             # a depth scale's label (a cross-section's TVD), not a curve
    if not unit and name.strip().islower() and len(name.strip()) <= 6:
        return None             # a word of the descriptions ("med", "gas."): a caption is capitalised
    if name.rstrip().endswith((",", ";")) or len(name.split()) > 6 \
            or (name[:1].islower() and len(name.split()) >= 4):
        return None             # a line of the descriptions, or a depth's note ("m TVD, (-949.33 m SS)")
    if re.search(r"[A-Za-z]\s*-\s*\d+(\.\d+)?$", name.strip()):
        return None             # a reading by its name ("RPM-0", "RPM-35")
    if re.fullmatch(r"-?\d+(\.\d+)?\s*(m|ft)?\s*(SS|TVD|MD|KB)?", unit.strip(), re.I) and re.search(r"\d", unit):
        return None             # a depth for its unit: a formation top's ("JOLI FOU FM (-32.6m SS)")
    if re.fullmatch(r"\d{3,}(\.\d+)?\s*units?", unit.strip(), re.I):
        return None             # a reading for its unit: a note ("from trip gas (650 units)")
    return name.strip(), unit.strip(), vc["key"]


def _decades(left, right, mine, ca):
    """a log scale can print every decade between its ends (1 10 100 1000):
    the numbers nearest the name either side are then only the inner two.
    The series is followed out each way, a number at a time, while the next
    one along the same row is the next decade (the same ratio as the inner
    two) no further on than they are apart"""
    lv, rv = left[1], right[1]
    if lv <= 0 or rv <= 0 or abs(math.log10(rv / lv)) < 0.3:
        return left, right
    r = rv / lv
    gap = abs(right[2] - left[2])

    def out(end, way):
        _d, v, at = end
        row = next((o for a, o, x, *_ in mine if abs(a - at) < 0.5 and abs(x - v) < 1e-9), None)
        while row is not None:
            want = v / r if way < 0 else v * r
            nxt = [(abs(a - at), a, x) for a, o, x, *_ in mine
                   if (a - at) * way > 2.0 and abs(a - at) <= gap and abs(o - row) <= 3.0
                   and abs(x - want) <= 0.01 * want]
            if not nxt:
                break
            _g, at, v = min(nxt)
        return (abs(at - ca), v, at)

    return out(left, -1), out(right, 1)


def captions(pg, pno, across, one=None):
    """the curve captions on a page. across(x, y) gives a page point's
    place across the log (the coordinate the scale runs along), so a
    caption on a sideways page reads the same as one the right way up.

    A caption is a curve's name in a colour with a number of the same
    colour either side of it across the log: the scale's left end on the
    left, its right end on the right. On a page that is the right way up
    the three sit on one row; on a sideways one the numbers are stacked by
    the names, so the nearest number on each side is taken. one, a list,
    gets the resistivity captions with a single decade number only (both
    ends set to it, to be worked out from the track's grid)."""
    lines = _lines(pg, by_colour=True)
    nums = [(bb, float(t), c, sz) for bb, t, c, sz in lines if NUMBER.match(t.strip())]
    out, where = [], {}
    # the page's other coordinate (a stack of captions is a column of it)
    perp = (lambda x, y: x) if abs(across(1.0, 0.0) - across(0.0, 0.0)) < 1e-9 else (lambda x, y: y)
    for bb, text, col, size in lines:
        nm = _caption_name(text)
        if not nm:
            continue
        a0, a1 = sorted((across(bb[0], bb[1]), across(bb[2], bb[3])))
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        ca = across(cx, cy)
        left = right = at_end = None
        mine = []                                   # (along, off the row, value) of this colour's numbers near it
        for nb, v, ncol, nsz in nums:
            if ncol != col or abs(nsz - size) > 0.2 * size:
                continue                    # (a scale's numbers are in its caption's size)
            nx, ny = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
            d = math.hypot(nx - cx, ny - cy)
            if d > 260:
                continue
            na = across(nx, ny)
            off = math.sqrt(max(0.0, d * d - (na - ca) ** 2))
            if off > 50:
                continue                    # (another column's: a legend's names have no numbers)
            mine.append((na, off, v, perp(nx, ny)))
            if na < a0:
                if left is None or d < left[0]:
                    left = (d, v, na)
            elif na > a1:
                if right is None or d < right[0]:
                    right = (d, v, na)
            elif na > a1 - 5 and (at_end is None or d < at_end[0]):
                at_end = (d, v, na)             # (a decade number set under the name's end)
        if right is None and at_end is not None:
            if left is not None and one is not None and "resistivity" in (nm[2] or "") \
                    and at_end[1] in (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0):
                left = None                     # (the number on its left another track's end)
            if left is None:
                right = at_end
        if (left is None) != (right is None) and one is not None and "resistivity" in (nm[2] or "") \
                and (left or right)[1] in (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0):
            # a log scale printed with one decade only (its ends unprinted):
            # mudlog_pdf works the ends out from the track's log grid
            c = Caption(pno + 1, bb, nm[0], nm[2], nm[1], col)
            end = left or right
            c.left = c.right = end[1]
            c.left_at = c.right_at = end[2]
            one.append(c)
            continue
        if left is None or right is None:
            continue
        left, right = _decades(left, right, mine, ca)
        c = Caption(pno + 1, bb, nm[0], nm[2], nm[1], col)
        c.left, c.left_at, c.right, c.right_at = left[1], left[2], right[1], right[2]
        out.append(c)
        where[id(c)] = (a0, a1, mine)
    _by_rank(out, where)
    return out


def _by_rank(caps, where):
    """captions of one colour stacked by each other (a sideways page) that
    took the same number on a side: the stack's numbers run in the order
    of its names, the first name's outermost, so they are handed out in
    that order"""
    def column(c, at, v):                       # where across the page the number taken sits
        return next((round(pp) for a, _o, x, pp in where[id(c)][2] if abs(a - at) < 0.5 and abs(x - v) < 1e-9), None)

    by = collections.defaultdict(list)
    for c in caps:
        by[(c.colour, "L", round(c.left_at, 1), column(c, c.left_at, c.left))].append(c)
        by[(c.colour, "R", round(c.right_at, 1), column(c, c.right_at, c.right))].append(c)
    for (_col, side, at, col_), cs in by.items():
        if col_ is None or len(cs) < 2 or len({c.name for c in cs}) < 2:
            continue
        cs = sorted(cs, key=lambda c: where[id(c)][0])
        lo = min(where[id(c)][0] for c in cs)
        hi = max(where[id(c)][1] for c in cs)
        cand = sorted({(round(a, 2), v) for c in cs for a, o, v, pp in where[id(c)][2]
                       if abs(pp - col_) <= 3.0 and (a < lo if side == "L" else a > hi)},
                      key=lambda t: abs(t[0] - (lo if side == "L" else hi)))[:len(cs)]
        if len(cand) < len(cs):
            continue
        cand.sort()
        for c, (a, v) in zip(cs, cand):
            if side == "L":
                c.left, c.left_at = v, a
            else:
                c.right, c.right_at = v, a


def rgb(colour):
    """0xRRGGBB -> (r, g, b) 0..1, as PyMuPDF gives a line's colour"""
    return ((colour >> 16) & 255) / 255.0, ((colour >> 8) & 255) / 255.0, (colour & 255) / 255.0
