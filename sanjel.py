"""Sanjel Corporation treatment plots (Carmine's SanJel-1) — VECTOR pages.

Nothing recognised these, so every Sanjel filing came back "no extractable
data": 374 treatment charts across 14 reports, all of them drawn rather than
scanned, were simply never read.

The layout is a single full-page plot with time along the bottom and FOUR
value axes stacked at the two sides — two on the left, two on the right.
Colour is what ties everything together, exactly as in step_vec:

    legend text   "Main Pressure (MPa)"          -> the name and the unit
    tick labels   0.00 / 14.00 / ... / 70.00     -> that curve's own scale
    stroke paths                                 -> the curve itself

so one colour is enough to give a curve its name, its unit and its scale.

Two things here are not step_vec's problem, and both are solved the same way —
by snapping every label to the chart's own gridlines instead of trusting where
the label happens to sit:

  * The two ladders on a side share gridlines but are printed 10 pt apart so
    the numerals do not collide. Fitting a ladder on its own label positions
    therefore puts one of the two curves a full label-height off its axis —
    about 3% of full scale, silently, on every page.
  * The first and last time label are pulled inward so they do not overflow
    the page. Fitting on them stretches the time axis by ~5%, which is the
    same defect v0.8.1 fixed for STEP.

The grid is drawn as thin teal lines with the black plot frame as its outer
pair, 11 by 11, so there is always a ruler to snap to.

Two vintages, one geometry:

    2015   time labels are a wall-clock pair, "2015/07/26" over "11:31"
    2016   time labels are a running job clock, "00:12:21"

Both parse to seconds and are rebased to the stage start, so the difference
never leaves this file.

Pages titled "Chemical Interval N Plot", "Interval #N Chemical Plot",
"Chemical Zone N Plot", "Hydration Zone N Plot" or "Pressure Test Plot" use
the identical drawing engine but plot additive concentrations, not treatment
channels — detect() rejects them, the same call the MView template makes.
"""
import re

import numpy as np

import curve_trace as ct

BLACK = 0
WHITE = 0xFFFFFF

_NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_UNIT = re.compile(r"\(([^)]*)\)\s*$")
_CLOCK = re.compile(r"^(\d{1,3}):([0-5]\d)(?::([0-5]\d))?$")
_DATE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
# "Interval #4 Plot", "Interval#12 Plot", "Interval #7A Plot", and the
# chemical/hydration twins that must NOT be treated as treatment charts.
_PLOT = re.compile(
    r"(?:(?P<pre>Chemical|Hydration)\s+)?"
    r"(?P<what>Interval|Zone)\s*#?\s*(?P<n>\d+[A-Za-z]?)\s+"
    r"(?P<mid>Chemical\s+)?Plot", re.I)
# "100/05-15-080-18 W6M/00" as printed in the page header
_LSD = re.compile(r"\b(1\d\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})\s*W(\d)")
_MONTHS = ("january february march april may june july august september "
           "october november december").split()


# --------------------------------------------------------------- detection

def _title_span(page):
    """The white banner across the top of every Sanjel plot page."""
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                if s.get("color") == WHITE and s.get("size", 0) >= 11:
                    t = s["text"].strip()
                    if t:
                        return t
    return ""


def page_role(page):
    """None, or what this Sanjel chart page plots.

    Chemical, hydration and pressure-test plots carry the same header, the
    same grid and the same colour scheme as the treatment charts; only the
    banner separates them, and exporting one as treatment channels would put
    litres-per-cubic-metre of biocide in the proppant column. They are named
    here rather than merely rejected so the caller can say what it skipped.
    """
    try:
        text = page.get_text()
    except Exception:
        return None
    if "sanjel.com" not in text.lower() or "Plot" not in text:
        return None
    title = _title_span(page)
    if not re.search(r"\bPlot\b", title):
        return None
    m = _PLOT.search(title)
    if m and not m.group("pre") and not m.group("mid") \
            and m.group("what").lower() == "interval":
        return "treatment"
    low = title.lower()
    for word in ("chemical", "hydration", "pressure test"):
        if word in low:
            return word
    return "other"


def detect(page):
    """A Sanjel TREATMENT plot page — not a chemical or hydration one."""
    return page_role(page) == "treatment"


# ------------------------------------------------------------------ pieces

def _spans(page):
    """-> [{c, t, cx, cy, y0}] for every non-blank span."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                t = s["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                out.append({"c": s.get("color", 0), "t": t,
                            "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                            "y0": y0, "size": s.get("size", 0)})
    return out


def _num(t):
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def _rgb_int(c):
    """Drawing colour (float triple) -> the int a text span carries."""
    r, g, b = (int(round(max(0.0, min(1.0, x)) * 255)) for x in c)
    return (r << 16) | (g << 8) | b


def _cluster(vals, tol=1.0):
    out = []
    for v in sorted(vals):
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def _gridlines(drawings):
    """-> (xs, ys): the chart's vertical and horizontal rules.

    The frame is the outermost pair on each list, so the plot rectangle comes
    out of the same measurement and cannot disagree with it.
    """
    hx, vy = [], []
    for d in drawings:
        if d.get("color") is None:
            continue
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                dx, dy = abs(p1.x - p2.x), abs(p1.y - p2.y)
                if dy < 0.2 and dx > 200:
                    hx.append(round((p1.y + p2.y) / 2, 2))
                elif dx < 0.2 and dy > 200:
                    vy.append(round((p1.x + p2.x) / 2, 2))
            elif it[0] in ("re", "qu"):
                # Most pages stroke the plot frame as four lines, but some
                # emit it as a single rectangle. Missing it costs the two
                # outermost rules on each axis, and the grid then stops short
                # of the chart it is supposed to measure.
                r = it[1].rect if it[0] == "qu" else it[1]
                if r.width > 200 and r.height > 200:
                    hx += [round(r.y0, 2), round(r.y1, 2)]
                    vy += [round(r.x0, 2), round(r.x1, 2)]
    return _cluster(vy), _cluster(hx)


def _snap(v, grid, tol):
    """The gridline this label belongs to, or None if it is nowhere near one."""
    if not grid:
        return None
    best = min(grid, key=lambda g: abs(g - v))
    return best if abs(best - v) <= tol else None


def _ladder(coords, grid):
    """Label positions -> the gridlines they actually mark, or None.

    Every ladder on a Sanjel page is printed against the same rules and
    spans the whole plot, so N labels land on every k-th gridline. Assigning
    them that way — rather than each to its nearest rule — is what survives
    the stacking: with seven axes on a page (offset-well pressures on top of
    the four treatment channels) the outermost ladder is printed a full
    16 pt below its rules, more than half a gridline, and nearest-rule put
    Main Pressure one whole gridline out and dropped its zero, reading a
    56.7 MPa stage as 64.2.
    """
    n = len(coords)
    if n < 3 or len(grid) < 2:
        return None
    step = (len(grid) - 1) / (n - 1)
    if abs(step - round(step)) > 1e-9 or round(step) < 1:
        return None
    k = int(round(step))
    out = [grid[i * k] for i in range(n)]
    # Sanity: the labels must be evenly spread the same way the rules are.
    a, b = coords[0], coords[-1]
    ga, gb = out[0], out[-1]
    if abs(b - a) < 1e-6 or abs(gb - ga) < 1e-6:
        return None
    if not 0.97 <= (gb - ga) / (b - a) <= 1.03:
        return None
    return out


def _fit(pairs):
    """[(value, coord)] -> (a, b) with value = a + b*coord, or None."""
    if len(pairs) < 2:
        return None
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    if c.max() - c.min() < 1e-6:
        return None
    b, a = np.polyfit(c, v, 1)
    return float(a), float(b)


def _secs(t):
    m = _CLOCK.match(t)
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


def _page_date(spans, text):
    """The date this interval was pumped, as YYYY-MM-DD."""
    # The 2015 layout prints it under the time axis, once per tick — that is
    # the interval's own date. The header "Date:" field is the job's, and on
    # a multi-day job it names a different day from the chart below it.
    for s in spans:
        m = _DATE.match(s["t"])
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if m and m.group(1).lower() in _MONTHS:
        mo = _MONTHS.index(m.group(1).lower()) + 1
        return f"{int(m.group(3))}-{mo:02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{2})/(\d{2})/(\d{2})\b", text)
    if m:                                   # mm/dd/yy in the header block
        return f"20{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return ""


def _time_axis(spans, text, xs, ys, frame):
    """-> ("x"|"y", [[seconds, coord], ...]) read off the printed time labels.

    Three vintages print the same axis three ways, and all three end up as
    seconds here:

        2015    a wall clock under each tick, "2015/07/26" over "11:31"
        2016a   a running job clock, "00:12:21"
        2016b   decimal minutes under a "Time (min)" caption, 0.0 / 21.0 / ...

    The direction is decided by trying both and keeping whichever produces a
    straight line — the four pages filed rotated plot the identical chart with
    time running up the page, and page.rotation does not describe the
    coordinates the text and drawings come back in.
    """
    x0, x1, y0, y1 = frame
    clock = [s for s in spans if s["c"] == BLACK and _CLOCK.match(s["t"])]
    if len(clock) >= 3:
        cands = [(float(_secs(s["t"])), s) for s in clock]
        wrap = True
    elif re.search(r"Time\s*\(\s*min", text, re.I):
        # Plain numerals: the remarks are black numerals too, so only the ones
        # printed OUTSIDE the plot and lined up with the grid are the axis.
        cands = [(_num(s["t"]) * 60.0, s) for s in spans
                 if s["c"] == BLACK and _NUM.match(s["t"])
                 and _num(s["t"]) is not None]
        wrap = False
    else:
        return None, None

    best = None
    for axis in ("x", "y"):
        tkey, pkey = ("cx", "cy") if axis == "x" else ("cy", "cx")
        tgrid = xs if axis == "x" else ys
        tol = 0.49 * float(np.median(np.diff(tgrid)))
        lo, hi = (y0, y1) if axis == "x" else (x0, x1)      # across the plot
        tlo, thi = (x0, x1) if axis == "x" else (y0, y1)    # along it
        # The axis is ONE row of labels just outside the plot. Every numeral
        # on the page is a candidate otherwise, and the header's ticket number
        # (407117) sat close enough to a gridline to join the fit and stretch
        # the stage to four days — the same way a licence number once did in
        # the STEP template.
        rows = {}
        for secs, s in cands:
            p = s[pkey]
            if lo - 1 <= p <= hi + 1:
                continue                    # inside the plot: a remark
            rows.setdefault(round(p, 0), []).append((secs, s))
        usable = [(min(abs(round(p) - lo), abs(round(p) - hi)), p, items)
                  for p, items in rows.items()
                  if len(items) >= 3 and
                  max(i[1][tkey] for i in items) -
                  min(i[1][tkey] for i in items) > 0.3 * (thi - tlo)]
        if not usable:
            continue
        usable.sort()
        row = sorted(usable[0][2], key=lambda c: c[1][tkey])
        coords = [c[1][tkey] for c in row]
        marked = _ladder(coords, tgrid)
        if marked is not None:
            # The first and last label are pulled inward so they do not
            # overflow the page — v0.8.1 fixed the same thing for STEP.
            # Reading their printed position stretches the axis by ~5%.
            out = [[float(secs), float(g)] for (secs, _s), g in zip(row, marked)]
        else:
            out, seen = [], set()
            for secs, s in row:
                g = _snap(s[tkey], tgrid, tol)
                if g is None or g in seen:
                    continue
                seen.add(g)
                out.append([float(secs), float(g)])
        if len(out) < 3:
            continue
        if wrap:
            # A stage that runs through midnight, or a job clock past 24h.
            # On the rotated pages time increases UP the page, so the labels
            # come out newest-first when read in coordinate order; unwrapping
            # them in that order turned a 70-minute stage into five days.
            up = sum(1 for i in range(1, len(out))
                     if out[i][0] > out[i - 1][0])
            seq = out if up * 2 >= len(out) - 1 else out[::-1]
            for i in range(1, len(seq)):
                while seq[i][0] < seq[i - 1][0]:
                    seq[i][0] += 86400.0
        fit = _fit(out)
        if fit is None:
            continue
        pred = [fit[0] + fit[1] * c for _v, c in out]
        rms = float(np.sqrt(np.mean([(p - v) ** 2
                                     for p, (v, _c) in zip(pred, out)])))
        score = rms / max(1.0, abs(out[-1][0] - out[0][0]))
        if best is None or score < best[0]:
            best = (score, axis, out)
    if best is None or best[0] > 0.02:
        return None, None
    return best[1], best[2]


# --------------------------------------------------------------- extraction

def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit}).

    Same shape as step_vec/lib1 so pipeline can treat this like any other
    vector template.
    """
    class Meta:
        pass

    spans = _spans(page)
    text = page.get_text()
    drawings = page.get_drawings()
    xs, ys = _gridlines(drawings)
    if len(xs) < 3 or len(ys) < 3:
        # An interval that was skipped still gets its page — header, footer
        # and "Did not frac zone 5" in the remarks, and no chart at all.
        raise ValueError("sanjel: page carries no chart (interval not pumped)")
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]

    meta = Meta()
    meta.warnings = []
    title = _title_span(page)
    m = _PLOT.search(title)
    meta.stage = m.group("n") if m else None
    meta.title = f"Interval {meta.stage or '?'}"
    meta.date = _page_date(spans, text)
    m = _LSD.search(title) or _LSD.search(text)
    meta.uwi = "".join(m.groups()[:5]) + "W" + m.group(6) + "00" if m else ""

    # --- the time axis, and which way it runs --------------------------
    axis, pairs = _time_axis(spans, text, xs, ys, (x0, x1, y0, y1))
    if axis is None:
        raise ValueError("sanjel: no time axis labels")
    tkey, vkey = ("cx", "cy") if axis == "x" else ("cy", "cx")
    tgrid, vgrid = (xs, ys) if axis == "x" else (ys, xs)
    vtol = 0.49 * float(np.median(np.diff(vgrid)))
    tfit = _fit(pairs)
    if tfit is None or tfit[1] == 0.0:
        raise ValueError("sanjel: time axis is degenerate")
    ta, tb = tfit

    # --- one tick ladder and one legend entry per colour ---------------
    # Every ladder is printed against the same rules, offset from them by a
    # label height per axis so the numerals clear each other. The rules are
    # the truth; where the numeral sits is typography.
    raw, named = {}, {}
    for s in spans:
        c = s["c"]
        if c in (BLACK, WHITE):
            continue
        if _NUM.match(s["t"]):
            v = _num(s["t"])
            if v is not None:
                raw.setdefault(c, []).append((s[vkey], v))
        elif "(" in s["t"] and re.search(r"[A-Za-z]", s["t"]):
            if len(s["t"]) > len(named.get(c, "")):
                named[c] = s["t"]

    ticks = {}
    for c, items in raw.items():
        items.sort()
        marked = _ladder([p for p, _v in items], vgrid)
        if marked is not None:
            ticks[c] = {g: v for g, (_p, v) in zip(marked, items)}
            continue
        d = {}
        for p, v in items:
            g = _snap(p, vgrid, vtol)
            if g is not None:
                d[g] = v
        if d:
            ticks[c] = d

    # --- the curves ----------------------------------------------------
    # Take a segment only when its MIDPOINT is inside the plot. Each value
    # axis draws its tick marks in its own colour, 3 pt long and straddling
    # the frame edge, so one endpoint of every one of them lands exactly on
    # the frame — full scale. Four such ticks put Btm Prop Conc at 2000 kg/m³
    # on a page whose real maximum was 266. Testing the midpoint drops them
    # and the legend's colour samples without also dropping a curve that runs
    # along the frame because it saturated.
    def _inside(ax, ay, bx, by):
        return (x0 - 0.05 <= (ax + bx) / 2 <= x1 + 0.05 and
                y0 - 0.05 <= (ay + by) / 2 <= y1 + 0.05)

    strokes = {}
    for d in drawings:
        c = d.get("color")
        if c is None:
            continue
        key = _rgb_int(c)
        if key not in named:
            continue                    # grid, frame, callouts, unnamed ink
        pts = strokes.setdefault(key, [])
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1], it[2]
            elif it[0] == "c":
                p1, p2 = it[1], it[4]
            else:
                continue
            if _inside(p1.x, p1.y, p2.x, p2.y):
                pts.append((p1.x, p1.y))
                pts.append((p2.x, p2.y))

    data, units, axes, axes_frame = {}, {}, {}, {}
    t_lo = t_hi = None
    for c, label in named.items():
        ladder = ticks.get(c)
        if not ladder or len(ladder) < 3:
            # An offset-well pressure trace ("G Well (MPa)") is drawn in the
            # legend but given no axis of its own — there is no scale to read
            # it against, so it is not exported.
            meta.warnings.append(
                f"{_UNIT.sub('', label).strip()} has no value axis, dropped")
            continue
        vfit = _fit([(v, g) for g, v in ladder.items()])
        pts = strokes.get(c)
        if vfit is None or not pts:
            continue
        arr = np.array(pts)
        # The plot clips its own curves, so the frame is the whole of the
        # window; anything outside it is the legend's colour sample or a tick
        # mark, and in step_vec those samples pushed peaks past full scale.
        keep = ((arr[:, 0] >= x0 - 0.5) & (arr[:, 0] <= x1 + 0.5) &
                (arr[:, 1] >= y0 - 0.5) & (arr[:, 1] <= y1 + 0.5))
        arr = arr[keep]
        if len(arr) < 40:
            continue
        tc = arr[:, 0] if axis == "x" else arr[:, 1]
        vc = arr[:, 1] if axis == "x" else arr[:, 0]
        t_abs = ta + tb * tc
        vals = vfit[0] + vfit[1] * vc
        order = np.argsort(t_abs, kind="stable")
        t_abs, vals = t_abs[order], vals[order]
        name = _UNIT.sub("", label).strip()
        unit = (_UNIT.search(label).group(1) if _UNIT.search(label) else "")
        lo, hi = float(t_abs.min()), float(t_abs.max())
        t_lo = lo if t_lo is None else min(t_lo, lo)
        t_hi = hi if t_hi is None else max(t_hi, hi)
        data[name] = (t_abs, vals)
        units[name] = unit.replace("³", "3")
        tv = sorted(ladder.values())
        axes[name] = (tv[0], tv[-1])
        v_far, v_near = (y0, y1) if axis == "x" else (x0, x1)
        axes_frame[name] = (float(vfit[0] + vfit[1] * v_far),
                            float(vfit[0] + vfit[1] * v_near))

    if not data:
        raise ValueError("sanjel: no series curve matched a legend entry")

    span_s = max(1.0, t_hi - t_lo)
    n = int(span_s / sample_sec)
    if not (60 < n < 200000):
        raise ValueError(f"sanjel: implausible duration {n}s")
    samples = np.arange(n) * sample_sec
    out = {}
    for name, (t_abs, vals) in data.items():
        rel = t_abs - t_lo
        keep = np.isfinite(rel) & np.isfinite(vals)
        if keep.sum() < 2:
            continue
        # Never np.interp straight: it clamps both tails to the end value and
        # bridges any hole, so a channel that stops dead mid-stage would be
        # exported as a long diagonal that is not on the page.
        out[name] = ct.resample(samples, rel[keep], vals[keep])

    meta.duration_min = span_s / 60.0
    t0 = int(round(t_lo)) % 86400
    meta.start_time = f"{t0 // 3600:02d}:{t0 % 3600 // 60:02d}:{t0 % 60:02d}"
    meta.axes = axes
    meta.axes_frame = axes_frame
    # Ghost mode places the source page with (t - ta) / tb and the samples
    # above start at zero, so the absolute origin has to come out of ta or
    # the page slides away by however far into the job this stage sat.
    v0, v1 = (y0, y1) if axis == "x" else (x0, x1)
    meta.geom = {"axis": axis, "ta": float(ta - t_lo), "tb": float(tb),
                 "v0": float(v0), "v1": float(v1)}
    return meta, samples, out, units
