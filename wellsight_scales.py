"""Each curve's printed scale, and where its readings run past it.

A WellSight curve is drawn across its track from a left value to a right
value (0 to 150 API, 0 to 1000 units). LogViewer does not stop a reading
that runs past the right value: it draws the line to the track's edge and
carries on from the other edge, in a thin solid line of the curve's colour
(a "wrap"). Gas at 1,037 units on a 0 to 1000 scale is printed at 37, near
the left edge; at 2,037 it would wrap twice. A reading below the left value
wraps the other way. It wraps once only: a reading past twice the scale
stays at the edge of the wrap (on 300 of the drive's printouts, 99% of
readings past the scale once are drawn where one wrap puts them, and only
5 to 12% of those past it twice or more). So a printout's line can sit far
from the value it stands for, a reading more than twice the scale cannot
be read off it at all, and the file's reading is the true one.

A scale can change down the log: the geologist sets a new one where the
gas comes in (0 to 500 units, then 0 to 4000 from 1,410 m), and LogViewer
prints a new curve header there. The scales are kept after the curves they
are for, as sections, each from a depth on:

    sections (int32)
    per section: depth (f64) | n (int32) | left[0..n-1] (f64) | n (int32) | right[0..n-1] (f64)

with a slot for each of the track's curve records, in the order they are
stored. This holds on the drive's printouts: see
validation-tools/wellsight_scale_check.py and tests/test_wellsight_scales.py.

    scales(raw, curves)          {curve index: [(from depth, left, right), ...]}
    scale_at(sections, depth)    the (left, right) in force at a depth
    printed(v, left, right)      where a reading lands: (position 0..1, wraps)
    wraps(curve, sections)       the depth runs where the printout wraps it
    drawn(v, left, right)        the main and the wrap line's positions for a reading
    read_drawn(series, ...)      a curve's readings back from its lines, down the log

Standard library only.
"""
import math
import os
import struct
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wellsight_convert")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import wellsight as ws        # noqa: E402


_NEAR = 640          # how far past a curve record's readings (or its mark) a table can start


def _plausible(left, right):
    return all(math.isfinite(v) and abs(v) < 1e8 for v in left + right) and \
        all(abs(r - l) > 1e-6 * max(1.0, abs(l), abs(r)) for l, r in zip(left, right)
            if l != r) and left != right


def _table_at(body, p):
    """(n, [left], [right], end) for a table at p, or None"""
    if p < 0 or p + 4 > len(body):
        return None
    n = struct.unpack_from("<i", body, p)[0]
    if not 1 <= n <= 64:
        return None
    q = p + 4 + 8 * n
    if q + 4 + 8 * n > len(body) or struct.unpack_from("<i", body, q)[0] != n:
        return None
    left = list(struct.unpack_from("<%dd" % n, body, p + 4))
    right = list(struct.unpack_from("<%dd" % n, body, q + 4))
    if not _plausible(left, right):
        return None
    return n, left, right, q + 4 + 8 * n


def _sections(body, p):
    """the scale sections around the table found at p: [(depth, [left],
    [right])] and the end of the block, or None when the table is not
    preceded by its section count and depth"""
    if p < 12:
        return None
    k = struct.unpack_from("<i", body, p - 12)[0]
    if not 1 <= k <= 200:
        return None
    out, at = [], p - 8
    for _ in range(k):
        if at + 8 > len(body):
            return None
        d = struct.unpack_from("<d", body, at)[0]
        tab = _table_at(body, at + 8)
        if tab is None or not math.isfinite(d) or abs(d) > 1e6:
            return None
        n, left, right, end = tab
        if out and n != len(out[0][1]):
            return None
        out.append((d, left, right))
        at = end
    return out, at


def _tables(body, curves, marks):
    """the scale blocks in the file: [(position, end, [(depth, [left],
    [right])])]. A block follows the record of the last curve it is for, so
    only the bytes just past each curve's readings, or past a record's mark
    when it has no readings, are looked at."""
    starts = sorted({c["offset"] + 12 + 8 * c["samples"] for c in curves} | set(marks))
    out, done_to = [], 0
    n_body = len(body)
    for s in starts:
        for p in range(max(s, done_to), min(n_body - 8, s + _NEAR)):
            n = body[p]
            if not (1 <= n <= 64 and body[p + 1:p + 4] == b"\x00\x00\x00"):
                continue
            tab = _table_at(body, p)
            if tab is None:
                continue
            sec = _sections(body, p)
            if sec:
                out.append((p, sec[1], sec[0]))
                done_to = sec[1]
            else:                      # a table on its own: one section, from the top
                out.append((p, tab[3], [(None, tab[1], tab[2])]))
                done_to = tab[3]
            break
    return out


def scales(raw, curves):
    """{index into curves: [(from depth, left, right), ...]} for the curves
    whose scales are found, sections in depth order (the first from the top
    of the log: its depth None when the file does not say); curves as
    wellsight.read_log gives them (each with the offset of its record).

    A block follows the curve records it is for, with a slot for each of
    them in order: the records between it and the block before it. The
    decoder leaves out a record with no readings, so a curve's slot is its
    place among those records (each starts with the display mark before its
    units), not among the decoded curves. A block can hold more slots than
    there are records before it; the slots past the last record belong to
    no curve read here."""
    body, _ = ws.inflate(raw, [])
    marks, m = [], body.find(ws._DISPLAY_MARK)
    while m >= 0:
        marks.append(m)
        m = body.find(ws._DISPLAY_MARK, m + 1)
    blocks = _tables(body, curves, marks)
    out = {}
    if not blocks:
        return out
    mark_of = {i: body.rfind(ws._DISPLAY_MARK, max(0, c["offset"] - 260), c["offset"]) for i, c in enumerate(curves)}
    prev_end = 0
    for pos, end, secs in blocks:
        mine = [mk for mk in marks if prev_end <= mk < pos]
        prev_end = end
        if not mine or len(mine) > len(secs[0][1]):
            continue
        secs = sorted(secs, key=lambda s: -math.inf if s[0] is None else s[0])
        for i, mk in mark_of.items():
            if mk in mine:
                j = mine.index(mk)
                out[i] = [(d, left[j], right[j]) for d, left, right in secs]
    return out


def scale_at(sections, depth):
    """the (left, right) in force at a depth"""
    cur = sections[0]
    for s in sections:
        if s[0] is None or depth >= s[0] - 1e-6:
            cur = s
        else:
            break
    return cur[1], cur[2]


def printed(v, left, right):
    """(where v lands across the track, 0 at the left value and 1 at the
    right; how many times it wrapped, + past the right value, - past the
    left). None for no reading or a scale of no width."""
    if v is None or right == left or not math.isfinite(v):
        return None
    f = (v - left) / (right - left)
    k = math.floor(f)
    if f == k and k > 0:          # exactly on the right edge: drawn there, not wrapped
        k -= 1
    return f - k, k


def wraps(curve, sections):
    """the depth runs where the printout wraps the curve:
    [{top, base, wraps, peak, left, right}]; wraps is +1 above the scale's
    high value (printed wrapped once), +2 past it by more than the scale's
    width (printed at the edge: the printout cannot show it), -1 and -2 the
    same below its low value, whichever side of the track each is printed
    on. curve as wellsight.read_log gives it (values from first_depth by
    step), sections as scales() gives them."""
    out, cur = [], None
    step, d0 = curve["step"], curve["first_depth"]
    if d0 is None:
        return out
    for i, v in enumerate(curve["values"]):
        d = d0 + i * step
        left, right = scale_at(sections, d)
        k = 0
        if v is not None and math.isfinite(v) and left != right:
            lo, hi = min(left, right), max(left, right)
            if v > hi:
                k = 1 if v <= hi + (hi - lo) else 2
            elif v < lo:
                k = -1 if v >= lo - (hi - lo) else -2
        if k and cur and cur["wraps"] == k and (cur["left"], cur["right"]) == (left, right):
            cur["base"] = d + step
            cur["peak"] = max(cur["peak"], v) if k > 0 else min(cur["peak"], v)
        elif k:
            cur = {"top": d, "base": d + step, "wraps": k, "peak": v, "left": left, "right": right}
            out.append(cur)
        else:
            cur = None
    for w in out:
        w["top"], w["base"] = round(w["top"], 3), round(w["base"], 3)
    return out


EDGE = 0.005         # a line this close to a track edge (as a share of its width) is pinned to it


def drawn(v, left, right):
    """the two lines LogViewer draws for a reading, as positions across the
    track (0 at the left value, 1 at the right): the main line, the reading
    held between the scale's ends, and the wrap line, the reading less one
    scale width held the same way. In the scale, the wrap line lies along
    the low end; past it, the main line lies along the high end and the
    wrap line carries on inside; past twice the scale, both lie along the
    high end. The scale's high end is the larger of left and right."""
    lo, hi = min(left, right), max(left, right)
    span = hi - lo

    def pos(u):
        return (min(max(u, lo), hi) - left) / (right - left)
    return pos(v), pos(v - span)


def read_drawn(series, left, right):
    """a curve's readings back from its lines on a printout, down the log:
    series[i] = the positions where its lines cross depth i (0 at the left
    value's edge, 1 at the right value's), [] where nothing is drawn (a gap
    in a dashed line). -> [(value, exact) or None].

    At each depth the reading is the line inside the track (a line along
    the low end is the wrap line waiting: the reading is in the scale). Down
    the log, a line that runs off the high end and comes back in from the
    low end has wrapped: from there the reading is one scale width more,
    until it runs back out the low end. It wraps once only, so a line along
    the high end with nothing inside is a reading of at least the high end,
    and one along the low end with nothing inside is at most the low end."""
    lo, hi = min(left, right), max(left, right)
    span = hi - lo
    tol = EDGE * span
    out, k, last = [], 0, None
    for ps in series:
        vals = sorted(left + p * (right - left) for p in ps or () if -EDGE <= p <= 1 + EDGE)
        mid = [u for u in vals if lo + tol < u < hi - tol]
        at_hi = any(u >= hi - tol for u in vals)
        at_lo = any(u <= lo + tol for u in vals)
        if mid:
            u = mid[0] if last is None else min(mid, key=lambda m: abs(m - last))
            if last is not None and abs(u - last) > span / 2:
                k = 1 if u < last else 0       # in from the low end: wrapped; back out of it: not
            elif last is None and at_hi and not at_lo:
                k = 1
            out.append((u + k * span, True))
            last = u
        elif at_hi:
            # the main line and the wrap line both along the high end: past
            # twice the scale; one line there: past the scale at least
            n_hi = sum(1 for u in vals if u >= hi - tol)
            out.append((hi + span if n_hi >= 2 else hi + k * span, False))
            last = hi
        elif at_lo and k == 0:
            out.append((lo, False) if not vals or all(u <= lo + tol for u in vals) and last is not None
                       and last <= lo + span / 4 else None)
        else:
            out.append(None)
    return out


# ---------------------------------------------------------------- tables

def rows_scales(curves):
    """the printed scales as rows: the payload's curves (wellsight_app)"""
    rows = [["curve", "unit", "from_m", "left", "right"]]
    for c in curves:
        for d, left, right in c.get("scale") or []:
            rows.append([c["name"], c["unit"], "" if d is None else d, left, right])
    return rows


def rows_wraps(curves):
    """where the printout wraps a curve, as rows"""
    rows = [["curve", "unit", "top_m", "base_m", "printed_scale", "printout", "peak_reading"]]
    for c in curves:
        for w in c.get("wraps") or []:
            how = ("wrapped once: the line comes back in from the other edge" if abs(w["wraps"]) == 1
                   else "past twice the scale: drawn at the edge, the reading cannot be read off it")
            rows.append([c["name"], c["unit"], w["top"], w["base"], "%g to %g" % (w["left"], w["right"]),
                         how, w["peak"]])
    return rows
