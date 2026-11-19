"""Curves of a geosteering printout: a horizontal well's log drawn along its
MD, a cross-section beside it, and the curves in a band of their own.

mudlog_pdf reads a printout's curves from WellSight's captions (a scale's
left end, the name, its right end, in the curve's colour). Geosteering
printouts caption them other ways, three of them seen:

  ends     each caption one line in its colour, its scale's end before its
           name ("10 ROP (min/m)", "150 Gamma (API)"), at one edge of the
           band; the other end a number in that colour level with it along
           the log at the band's other edge. The captions and their numbers
           are stacked a line apart: the band is the same for them all, from
           the long line at the captions' edge to the one at the numbers'.
  split    the same with the near end a number of its own beside the name
           ("10", "ROP (min/m)", ..., "0"); the lines can be drawn in other
           colours than their captions (a darker red, a black ROP under a
           blue caption): a caption with no line of its colour takes the
           colour of a line in the band no caption has, the nearest.
  row      the caption in black, the scale under or over it a row of
           numbers in the curve's colour at their places across the band
           (0 50 100 150): the curve is the line of the numbers' colour,
           its scale the straight line through them. Printed on the log's
           first page only: later pages go on with the scales before them.

Each curve is a line with a corner at every reading; a reading past the
scale is drawn at the band's edge (read there: it says only that it is past).
Depth comes from each page's own MD labels (wellsight_print.page_lines), so a
log on many pages or one long one reads the same.
-> curves in mudlog_pdf.read_curves' form.
"""
import math
import re

STEP = 0.1              # m, as mudlog_pdf's curves
CAPTION = re.compile(r"^\s*(-?\d[\d,]*(?:\.\d+)?)\s+([A-Za-z][^()]*?\([^)]*\))\s*$")     # "150 Gamma (API)"
NAMED = re.compile(r"^\s*([A-Za-z][^()]*?\([^)]*\))\s*$")                               # "Gamma Ray (gapi)"
NUMBER = re.compile(r"^\s*-?\d[\d,]*(?:\.\d+)?\s*$")
GAP_M = 2.0             # corners further apart than this along the log are not joined
COLOUR_TOL = 0.03       # a line's colour as its caption's, channel by channel
OFF_BAND = 0.25         # a corner further than this share of the band past it is no reading
MIN_SHARE = 0.10        # a curve read along less of the log than this is a stray line
# the curves these printouts draw again from the low end past the high one
# (shaded under): gas. A gamma that drops from the top to the bottom of its
# band is a reading (out of the casing, "gamma attenuated inside casing").
WRAPS = {"total_gas", "methane", "ethane", "propane", "butane", "pentane", "c:total_gas"}


def _num(t):
    return float(t.strip().replace(",", ""))


def _rgb(c):
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0


def _same_colour(a, b):
    return all(abs(x - y) <= COLOUR_TOL for x, y in zip(a, b))


def _spans(pg):
    out = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                t = s["text"].strip()
                if t:
                    out.append((tuple(s["bbox"]), t, s["color"]))
    return out


class _Frame:
    """a page's depth along one coordinate (axis 1: x, 2: y), the curves'
    readings along the other"""

    def __init__(self, axis, a, b):
        self.axis, self.a, self.b = axis, a, b

    def along(self, x, y):
        return x if self.axis == 1 else y

    def across(self, x, y):
        return y if self.axis == 1 else x

    def depth(self, x, y):
        return self.a * self.along(x, y) + self.b

    def box(self, bb):
        """(along lo, along hi, across lo, across hi) of a box"""
        x0, y0, x1, y1 = bb
        if self.axis == 1:
            return x0, x1, y0, y1
        return y0, y1, x0, x1


def _frame(pg, top=None, bottom=None):
    """the page's depths, from its MD labels; None on a page with none (or,
    given the log's range, with none in it)"""
    import wellsight_print as wp
    ax = wp.page_axis(pg, 1, 99999, whole=True)
    if not ax or len(ax[3]) < 5:
        return None
    if top is not None and not any(top - 20 <= d <= bottom + 20 for _c, d in ax[3]):
        return None
    return _Frame(ax[0], ax[1], ax[2])


def _long_lines(pg, f, min_len=200.0):
    """the across places of the lines drawn a long way along the log (a
    band's edges and its grid)"""
    out = []
    for d in pg.get_drawings():
        for it in d["items"]:
            if it[0] != "l":
                continue
            p, q = it[1], it[2]
            if abs(f.across(p.x, p.y) - f.across(q.x, q.y)) < 0.3 and abs(f.along(p.x, p.y) - f.along(q.x, q.y)) > min_len:
                out.append(f.across(p.x, p.y))
    return sorted(set(round(v, 2) for v in out))


def _snap(v, lines, tol=3.0):
    near = min(lines, key=lambda l: abs(l - v)) if lines else None
    return near if near is not None and abs(near - v) <= tol else v


def _level(a, b, slack=2.0):
    """two along-extents side by side (overlapping, or within slack)"""
    return min(a[1], b[1]) - max(a[0], b[0]) >= -slack


def _curve(nm, colour, lo, hi, lo_at, hi_at):
    """a curve's scale: value lo at across lo_at, hi at hi_at"""
    p = (hi - lo) / (hi_at - lo_at)
    return {"name": nm[0], "unit": nm[1], "kind": nm[2], "colour": colour, "lo": lo, "hi": hi,
            "p": p, "q": lo - p * lo_at, "band": (min(lo_at, hi_at), max(lo_at, hi_at))}


def _ends(spans, f, lines):
    """the "ends" and "split" captions: [curve], each block of captions
    (stacked a line apart, so sharing one band) with its own band, or []"""
    import pdf_legend as PL
    nums = []
    for bb, t, col in spans:
        if NUMBER.match(t):
            b = f.box(bb)
            v = _num(t)
            if abs(f.depth(*((b[0] + b[1]) / 2, 0) if f.axis == 1 else (0, (b[0] + b[1]) / 2)) - v) < 2.0:
                continue                          # an MD label at its own depth, not a scale's end
            nums.append((b, v, col))
    caps = []
    for bb, t, col in spans:
        m = CAPTION.match(t)
        nm = PL._caption_name(m.group(2) if m else t)
        if not nm or not nm[2] or (not m and not NAMED.match(t)):
            continue
        a0, a1, c0, c1 = f.box(bb)
        # its scale's ends: the number before its name (in it, or its own
        # just before it), and the nearest number of its colour level with
        # it on the far side (not one further on: another column's)
        mine = [((b[2], b[3]), v) for b, v, ncol in nums if ncol == col and _level((a0, a1), b[:2])]
        before = [e for e in mine if e[0][1] <= c0 + 1]
        after = [e for e in mine if e[0][0] >= c1 - 1]
        if m:
            here = ((c0, c1), _num(m.group(1)))
            far = [e for e in after if e[0][0] - c1 >= 20] or [e for e in before if c0 - e[0][1] >= 20]
            if not far:
                continue
            other = min(far, key=lambda e: max(e[0][0] - c1, c0 - e[0][1]))
            lo_end, hi_end = (here, other) if other[0][0] > c1 else (other, here)
        else:
            if not before or not after:
                continue
            lo_end = max(before, key=lambda e: e[0][1])
            hi_end = min(after, key=lambda e: e[0][0])
        if hi_end[0][1] - lo_end[0][0] < 20 or lo_end[1] == hi_end[1]:
            continue
        caps.append({"nm": nm, "col": col, "lo": lo_end, "hi": hi_end, "along": (a0 + a1) / 2})
    if not caps:
        return []
    # blocks: captions side by side along the log; each block one band (from
    # its outermost number on one side to the other side's)
    caps.sort(key=lambda c: c["along"])
    blocks, out = [], []
    for c in caps:
        if blocks and c["along"] - blocks[-1][-1]["along"] < 40:
            blocks[-1].append(c)
        else:
            blocks.append([c])
    for blk in blocks:
        at0 = _snap(min(c["lo"][0][0] for c in blk), lines)
        at1 = _snap(max(c["hi"][0][1] for c in blk), lines)
        if at1 - at0 < 20:
            continue
        for c in blk:
            cv = _curve(c["nm"], c["col"], c["lo"][1], c["hi"][1], at0, at1)
            cv["at"] = c["along"]
            out.append(cv)
    return out


def _rows(spans, f, lines):
    """the "row" captions: [curve], each with its own scale, or []"""
    import pdf_legend as PL
    names = []
    for bb, t, col in spans:
        if NAMED.match(t):
            nm = PL._caption_name(t)
            if nm and nm[2]:
                names.append((f.box(bb), nm))
    if not names:
        return []
    rows = _number_rows(spans, f, lines)
    if not rows:
        return []
    return _pair(names, rows)


def _number_rows(spans, f, lines):
    """rows of numbers: numbers of one colour level with each other along
    the log, spread across (two or more places) on a straight scale"""
    groups = {}
    for bb, t, col in spans:
        if NUMBER.match(t):
            b = f.box(bb)
            groups.setdefault((col, round((b[0] + b[1]) / 2 / 4)), []).append((b, _num(t)))
    # (a row is numbers near each other across: another scale level with it
    # elsewhere on the page, a cross-section's, is a row of its own)
    runs = []
    for (col, _k), g in groups.items():
        g.sort(key=lambda x: x[0][2])
        cur, trend = [g[0]], 0
        for x in g[1:]:
            step = (x[1] > cur[-1][1]) - (x[1] < cur[-1][1])
            # a wide gap, or the numbers turning back (5 10 15 20 then 15 10
            # 5 0): another scale
            if x[0][2] - cur[-1][0][3] > 60 or (trend and step and step != trend):
                runs.append((col, cur))
                cur, trend = [], 0
            elif step:
                trend = step
            cur.append(x)
        runs.append((col, cur))
    rows = []
    for col, g in runs:
        if len(g) < 2 or g[-1][0][2] - g[0][0][3] < 40 or len({v for _b, v in g}) < 2:
            continue
        # where each number stands for its value: the end ones by their
        # outer edges (printed inside the band's edges), the others centred
        at = [g[0][0][2]] + [(b[2] + b[3]) / 2 for b, _v in g[1:-1]] + [g[-1][0][3]]
        vs = [v for _b, v in g]
        n = len(at)
        ma, mv = sum(at) / n, sum(vs) / n
        sxx = sum((a - ma) ** 2 for a in at)
        if not sxx:
            continue
        p = sum((a - ma) * (v - mv) for a, v in zip(at, vs)) / sxx
        q = mv - p * ma
        if not p or max(abs(p * a + q - v) for a, v in zip(at, vs)) > 0.05 * (max(vs) - min(vs)):
            continue                                     # not a straight scale
        along = (min(b[0] for b, _v in g), max(b[1] for b, _v in g))
        rows.append({"col": col, "along": along, "p": p, "q": q, "across": (g[0][0][2], g[-1][0][3]),
                     "band": (_snap(at[0], lines), _snap(at[-1], lines)), "lo": min(vs), "hi": max(vs)})
    return rows


def _pair(names, rows):
    """a row goes with the caption next to it along the log, all on the same
    side (row then caption, or caption then row)"""
    names.sort(key=lambda x: x[0][0])
    rows.sort(key=lambda r: r["along"][0])
    best = (0, 0.0, [])
    for before in (True, False):
        got, gaps = [], 0.0
        for b, nm in names:
            over = [r for r in rows if min(r["across"][1], b[3]) > max(r["across"][0], b[2])]   # across the caption
            # (a row and its caption are printed a line apart, overlapping a little)
            gap = (lambda r: b[0] - r["along"][1]) if before else (lambda r: r["along"][0] - b[1])
            cands = [r for r in over if -4.0 <= gap(r) < 15]
            if cands:
                r = min(cands, key=lambda r: abs(gap(r)))
                gaps += abs(gap(r))
                got.append({"name": nm[0], "unit": nm[1], "kind": nm[2], "colour": r["col"], "lo": r["lo"],
                            "hi": r["hi"], "p": r["p"], "q": r["q"], "band": tuple(sorted(r["band"])),
                            "at": (b[0] + b[1]) / 2})
        if (len(got), -gaps) > (best[0], -best[1]):
            best = (len(got), gaps, got)
    return best[2]


def _captions(pg, f):
    """the curves a page captions: [curve], or []"""
    # (not text cut off by the page's edge: "150 Gamma" there reads "50 Gamma")
    w, h = (pg.rect.height, pg.rect.width) if pg.rotation in (90, 270) else (pg.rect.width, pg.rect.height)
    length = w if f.axis == 1 else h
    spans = [sp for sp in _spans(pg) if f.box(sp[0])[0] >= -0.5 and f.box(sp[0])[1] <= length + 0.5]
    lines = _long_lines(pg, f)
    ends, rows = _ends(spans, f, lines), _rows(spans, f, lines)
    return ends if len({_key(c) for c in ends}) >= len({_key(c) for c in rows}) else rows


def _paths(pg, f, band):
    """the lines inside the band (and a little past it), path by path:
    {colour: [[(x, y), ...], ...]}"""
    lo, hi = min(band) - 2.0, max(band) + 2.0
    out = {}
    for d in pg.get_drawings():
        c = d.get("color")
        if not c:
            continue
        runs, run, last = [], [], None
        for it in d["items"]:
            if it[0] != "l":
                continue
            p, q = it[1], it[2]
            if last is None or abs(p.x - last.x) > 0.01 or abs(p.y - last.y) > 0.01:
                if len(run) > 1:
                    runs.append(run)
                run = [(p.x, p.y)]
            run.append((q.x, q.y))
            last = q
        if len(run) > 1:
            runs.append(run)
        runs = [r for r in runs if _in_band(r, f, lo, hi)]
        if runs:
            out.setdefault(tuple(round(v, 3) for v in c), []).extend(runs)
    return out


def _in_band(run, f, lo, hi):
    """a curve's line: in the band, most of it (it runs past the band where
    a reading is past the scale), and along the log (not a grid line across
    the band)"""
    acr = [f.across(*pt) for pt in run]
    if sum(1 for a in acr if lo <= a <= hi) < 0.5 * len(acr):
        return False
    return abs(f.along(*run[0]) - f.along(*run[-1])) > 1.0


def _unwrap(vals, scale_at, past=None):
    """readings past a scale's high end drawn again from its low end (the
    line leaves the band at the top and comes in from the bottom one scale
    width lower, shaded under): put back one width up while wrapped. A
    wrap: a reading past the high end, then one in the low half. Its end:
    a reading past the low end, then one in the high half. scale_at(j) ->
    (lo, hi) at reading j; past: {j: (past the high end, past the low end)}
    for readings where a line of the curve's ran past the band (a line
    that rises steeply leaves the band between two readings)."""
    past = past or {}
    out, k, prev = list(vals), 0, None
    last, gap = None, 0                     # the last reading put back, readings since it
    for j, v in enumerate(vals):
        if v is None:
            prev = None
            gap += 1
            continue
        lo, hi = scale_at(j)
        span = hi - lo
        if prev is None and k and span:
            # after a gap: the line may have come back in meanwhile. The
            # wraps that carry on from the reading before it; none after a
            # long gap (nothing to go by)
            if last is None or gap > 50:
                k = 0
            else:
                k = min(range(k + 1), key=lambda w: abs(v + w * span - last))
        if prev is not None and span:
            ph = past.get(j, (False, False))
            pp = past.get(j - 1, (False, False))
            past_hi = (prev - hi) / span > 0.005 or ph[0] or pp[0]
            past_lo = (lo - prev) / span > 0.005 or ph[1] or pp[1]
            was, now = (prev - lo) / span, (v - lo) / span
            # a wrap is a jump from the band's top to its bottom (or back),
            # the line past the edge it left by
            if past_hi and was >= 0.5 and now <= 0.35 and was - now >= 0.4:      # out at the top, in at the bottom
                k += 1
            elif past_lo and k and was <= 0.5 and now >= 0.65 and now - was >= 0.4:   # out at the bottom, in at the top
                k -= 1
        out[j] = v + k * span
        prev, last, gap = v, out[j], 0
    return out


def _lines_for(curves, paths):
    """each curve's lines: those of its colour; a curve with none takes the
    colour, of those no curve has, nearest its own (a caption printed darker
    than its line, or a black line under a coloured caption)"""
    got, free = {}, dict(paths)
    for c in curves:
        want = _rgb(c["colour"])
        for col in list(free):
            if _same_colour(col, want):
                got[_key(c)] = free.pop(col)
                break
    # what a line of a colour no caption has looks like: long (most of the band)
    long_runs = {col: rs for col, rs in free.items() if sum(len(r) for r in rs) >= 50}
    for c in curves:
        if _key(c) in got or not long_runs:
            continue
        want = _rgb(c["colour"])
        col = min(long_runs, key=lambda k: sum((a - b) ** 2 for a, b in zip(k, want)))
        got[_key(c)] = long_runs.pop(col)
    return got


def _key(c):
    """a curve: its kind and its name (a log can print three gammas: Gamma,
    Gamma Up, Gamma Down)"""
    return c["kind"], c["name"].lower()


def _one_each(caps):
    """one caption of each kind (the colour of its line)"""
    seen = {}
    for c in caps:
        seen.setdefault(_key(c), c)
    return list(seen.values())


def _scale_at(copies, d):
    """the copy of a curve's caption whose scale holds at depth d: the last
    one printed at or above it (the first, above them all)"""
    got = copies[0]
    for c in copies:
        if c["depth"] <= d + 1e-6:
            got = c
    return got


def _follow(cands, n):
    """one reading at each depth. Where two lines of the curve's colour give
    one (the curve, and shapes drawn in its colour: the humps of gas at a
    connection, short strokes), the curve's is the long line's: of the lines
    nearly as long as the longest there, the one nearest the reading before"""
    vals, last = [None] * n, None
    for j in range(n):
        cs = cands.get(j)
        if not cs:
            last = None
            continue
        longest = max(ln for _v, ln in cs)
        cs = [v for v, ln in cs if ln >= 0.5 * longest]
        v = cs[0] if len(cs) == 1 or last is None else min(cs, key=lambda c: abs(c - last))
        vals[j] = last = v
    return vals


def read_curves(doc, top, bottom, step=STEP):
    """-> [{name, kind, units, unit, top, step, values, scale, colour,
    track_pt, past_scale, recorded_step, shifted_m, log_scale_from, lines}]"""
    import log_vocab as V
    n = int(math.floor((bottom - top) / step + 1e-6)) + 1
    curves = {}                 # kind -> {curve, values, past}
    last = []                   # the scales a page goes on with when it prints none
    # a page's depths are the log's (not a cross-section's TVD scale: a
    # header page's numbers can make a line of their own)
    frames = [_frame(pg, top, bottom) for pg in doc]
    axes = [f.axis for f in frames if f]
    axis = max(set(axes), key=axes.count) if axes else None
    for pg, f in zip(doc, frames):
        if f is None:
            # a page of the log's header can print the scales (a page with
            # no depths of its own): its captions go on to the pages after
            if axis is not None:
                caps = _captions(pg, _Frame(axis, 1.0, 0.0))
                if caps:
                    last = [dict(c, depth=-1e9) for c in caps]
            continue
        caps = _captions(pg, f)
        if caps:
            for c in caps:
                c["depth"] = f.depth(*((c["at"], 0) if f.axis == 1 else (0, c["at"])))
        else:
            caps = [dict(c, depth=-1e9) for c in last]        # the scales before, from the page's start
        if not caps:
            continue
        last = caps
        band = (min(c["band"][0] for c in caps), max(c["band"][1] for c in caps))
        lines = _lines_for(_one_each(caps), _paths(pg, f, band))
        for key in {_key(c) for c in caps}:
            runs = lines.get(key)
            if not runs:
                continue
            copies = sorted((c for c in caps if _key(c) == key), key=lambda c: c["depth"])
            cur = curves.setdefault(key, {"curve": copies[0], "cands": {}, "past": set(), "scales": []})
            for c in copies:
                if not cur["scales"] or (cur["scales"][-1][1], cur["scales"][-1][2]) != (c["lo"], c["hi"]):
                    cur["scales"].append([round(max(c["depth"], top), 3), c["lo"], c["hi"]])
            for run in runs:
                got = {}                                 # this line's reading at each depth
                prev = None
                for x, y in run:
                    d = f.depth(x, y)
                    a = f.across(x, y)
                    c = _scale_at(copies, d)
                    b0, b1 = c["band"]
                    if a < b0 - OFF_BAND * (b1 - b0) or a > b1 + OFF_BAND * (b1 - b0):
                        prev = None                     # a pen's move far off the band: no reading
                        continue
                    v = c["p"] * a + c["q"]
                    i = int(round((d - top) / step))
                    if prev is not None:
                        pd, pv, pi = prev
                        # the readings between two corners on the line
                        if abs(d - pd) <= GAP_M and abs(i - pi) > 1:
                            for j in range(min(i, pi) + 1, max(i, pi)):
                                if 0 <= j < n:
                                    got[j] = pv + (v - pv) * (top + j * step - pd) / (d - pd)
                    if 0 <= i < n:
                        got[i] = v                       # (a later corner at a depth: the line went on from it)
                        if a <= b0 + 0.3 or a >= b1 - 0.3:
                            cur["past"].add(i)
                    prev = (d, v, i)
                length = abs(f.depth(*run[0]) - f.depth(*run[-1]))    # m of the log this line runs
                for j, v in got.items():
                    cur["cands"].setdefault(j, []).append((v, length))
    out = []
    for k, cur in curves.items():
        vals = _follow(cur["cands"], n)
        sc = sorted(cur["scales"])

        def scale_at(j, sc=sc):
            d = top + j * step
            got = sc[0]
            for x in sc:
                if x[0] <= d + 1e-6:
                    got = x
            lo, hi = got[1], got[2]
            return (min(lo, hi), max(lo, hi))
        past = {}
        for j, cs in cur["cands"].items():
            lo, hi = scale_at(j)
            tol = 0.005 * (hi - lo)
            past[j] = (any(v > hi + tol for v, _ln in cs), any(v < lo - tol for v, _ln in cs))
        if cur["curve"]["kind"] in WRAPS:
            vals = _unwrap(vals, scale_at, past)
            # (no gas below nothing: a shape drawn under the band at a
            # connection, not a reading)
            vals = [None if v is not None and v < scale_at(j)[0] - 0.01 * (scale_at(j)[1] - scale_at(j)[0])
                    else v for j, v in enumerate(vals)]
        # nothing these logs record reads below nothing: on a scale from
        # nothing up, a reading under it is a stroke under the band
        vals = [None if v is not None and scale_at(j)[0] >= 0 and v < -0.01 * (scale_at(j)[1] - scale_at(j)[0])
                else v for j, v in enumerate(vals)]
        # a curve read along a sliver of the log is a stray line of its colour
        if sum(1 for v in vals if v is not None) < max(10, MIN_SHARE * n):
            continue
        c = cur["curve"]
        out.append({"name": c["name"], "kind": c["kind"], "units": c["unit"],
                    "unit": V.unit(c["unit"])["key"] if c["unit"] else None,
                    "top": round(top, 3), "step": step,
                    "values": [None if v is None else round(v, 4) for v in vals],
                    "scale": sorted(cur["scales"]), "colour": "#%06x" % c["colour"],
                    "track_pt": [round(c["band"][0], 1), round(c["band"][1], 1)], "past_scale": len(cur["past"]),
                    "recorded_step": step, "shifted_m": 0.0, "log_scale_from": None, "lines": 1,
                    "from": "geosteering"})
    return out
