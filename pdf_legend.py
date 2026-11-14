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
import math
import re

import log_vocab as V
import wellsight_symbols as wsym

SWATCH_MAX_W = 80.0      # pt: a legend picture is a small one; a frame or logo is not
SWATCH_MAX_H = 24.0
LABEL_GAP = 60.0         # pt from a picture's right edge to its label at most
ROW_TOL = 4.5            # pt: a label's middle within the picture's height, give or take this
COLUMN_TOL = 20.0        # pt: entries this close across are one column of a box
NUMBER = re.compile(r"[-+]?\d+(\.\d+)?$")


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


def _lines(pg):
    """the page's text lines: (bbox, text, colour as 0xRRGGBB, size)"""
    out = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = " ".join(s["text"].strip() for s in spans)
            out.append((tuple(ln["bbox"]), text, spans[0]["color"], spans[0]["size"]))
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


_UNIT = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def _caption_name(text):
    """(name, unit text, curve kind) for a caption's name, or None"""
    t = text.strip()
    m = _UNIT.match(t)
    name, unit = (m.group(1), m.group(2)) if m else (t, "")
    if not name or NUMBER.match(name):
        return None
    vc = V.curve(t)
    if not vc["key"]:
        vc = V.curve(name)
    if not vc["key"] and not unit:
        return None
    return name.strip(), unit.strip(), vc["key"]


def captions(pg, pno, across):
    """the curve captions on a page. across(x, y) gives a page point's
    place across the log (the coordinate the scale runs along), so a
    caption on a sideways page reads the same as one the right way up.

    A caption is a curve's name in a colour with a number of the same
    colour either side of it across the log: the scale's left end on the
    left, its right end on the right. On a page that is the right way up
    the three sit on one row; on a sideways one the numbers are stacked by
    the names, so the nearest number on each side is taken."""
    lines = _lines(pg)
    nums = [(bb, float(t), c) for bb, t, c, _s in lines if NUMBER.match(t.strip())]
    out = []
    for bb, text, col, _sz in lines:
        nm = _caption_name(text)
        if not nm:
            continue
        a0, a1 = sorted((across(bb[0], bb[1]), across(bb[2], bb[3])))
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        left = right = None
        for nb, v, ncol in nums:
            if ncol != col:
                continue
            nx, ny = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
            d = math.hypot(nx - cx, ny - cy)
            if d > 260:
                continue
            na = across(nx, ny)
            if na < a0:
                if left is None or d < left[0]:
                    left = (d, v, na)
            elif na > a1:
                if right is None or d < right[0]:
                    right = (d, v, na)
        if left is None or right is None:
            continue
        c = Caption(pno + 1, bb, nm[0], nm[2], nm[1], col)
        c.left, c.left_at, c.right, c.right_at = left[1], left[2], right[1], right[2]
        out.append(c)
    return out


def rgb(colour):
    """0xRRGGBB -> (r, g, b) 0..1, as PyMuPDF gives a line's colour"""
    return ((colour >> 16) & 255) / 255.0, ((colour >> 8) & 255) / 255.0, (colour & 255) / 255.0
