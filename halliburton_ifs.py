"""Halliburton IFS chart template (as filed by Shell, Vermilion, Ovintiv in BC).

Layout (landscape, unrotated): per-interval treatment charts titled
"x.y Interval N - Entire Treatment", footer "(IFS v x.y.z)". The legend
lists each series in its stroke color followed by a same-colored axis
letter (A/B/C); numeric tick columns for A sit left of the plot, B and C
to the right. Time axis is HH:MM labels along the bottom.

Everything needed is in the text layer, so calibration comes entirely from
tick-label positions — no frame detection required.
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta

STD_NAMES = [
    (("treating pressure",), "Tr Press"),
    (("slurry rate", "clean rate"), "Slurry Rate"),
    (("slurry proppant conc", "blender prop"), "WH Prop Conc"),
    (("bh proppant conc", "bottomhole prop"), "BH Prop Conc"),
]


def detect(page):
    text = page.get_text()
    return "(IFS v" in text


def is_entire_treatment(page):
    return re.search(r"Interval\s+\d+\s*[-–]\s*Entire Treatment",
                     page.get_text()) is not None


def page_rotated(page):
    """True when the chart is drawn 90° rotated (time axis vertical). Some
    IFS builds (v4.3.1) render portrait: every text span reads bottom-to-top
    (dir≈(0,-1)). Detected by the dominant span direction."""
    vert = horiz = 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1, 0))
            if abs(dy) > abs(dx):
                vert += len(line.get("spans", []))
            else:
                horiz += len(line.get("spans", []))
    return vert > horiz and vert >= 3


def _unrotate(x, y):
    """Map a 90°-rotated (dir=(0,-1)) point back to canonical orientation so
    the horizontal-chart logic applies unchanged: (x, y) -> (-y, x)."""
    return -y, x


def _spans(page, rotated=None):
    if rotated is None:
        rotated = page_rotated(page)
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if rotated:
                    cx, cy = _unrotate(cx, cy)
                out.append({"t": t, "cx": cx, "cy": cy,
                            "x0": x0, "x1": x1, "color": span.get("color", 0)})
    return out


def _fit(pairs):
    """least squares value = a + b*coord over [(value, coord)]"""
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    A = np.vstack([np.ones_like(c), c]).T
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(a), float(b)


def _axis_columns(spans):
    """Cluster numeric black tick labels into vertical columns."""
    nums = [s for s in spans if s["color"] == 0 and
            re.fullmatch(r"-?\d+(\.\d+)?", s["t"].replace(",", ""))]
    # cluster on label centers (alignment varies by axis side); tick digits
    # are short so centers stay within ~6 pt per column
    nums.sort(key=lambda s: s["cx"])
    clusters, cur = [], [nums[0]] if nums else []
    for s in nums[1:]:
        if s["cx"] - cur[-1]["cx"] > 6:
            clusters.append(cur); cur = [s]
        else:
            cur.append(s)
    if cur:
        clusters.append(cur)

    out = []
    for group in clusters:
        if len(group) < 4:
            continue
        # keep the longest chain that is evenly spaced in y AND arithmetic in
        # value (drops strays: section numbers, stray decimals, event-marker
        # labels that share the column's x range but break the tick scale)
        group.sort(key=lambda s: s["cy"])

        def val(s):
            return float(s["t"].replace(",", ""))

        best_chain = []
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                gap = group[j]["cy"] - group[i]["cy"]
                if gap < 8:
                    continue
                vstep = val(group[j]) - val(group[i])
                if vstep == 0:
                    continue
                chain = [group[i], group[j]]
                exp_y = group[j]["cy"] + gap
                exp_v = val(group[j]) + vstep
                for k in range(j + 1, len(group)):
                    if abs(group[k]["cy"] - exp_y) <= gap * 0.2 and \
                       abs(val(group[k]) - exp_v) <= abs(vstep) * 0.15 + 1e-9:
                        chain.append(group[k])
                        exp_y = group[k]["cy"] + gap
                        exp_v = val(group[k]) + vstep
                if len(chain) > len(best_chain):
                    best_chain = chain
        if len(best_chain) < 4:
            continue
        vals = [(val(s), s["cy"]) for s in best_chain]
        a, b = _fit(vals)
        if abs(b) < 1e-9:
            continue
        ys = [y for _, y in vals]
        out.append({"x": float(np.mean([s["cx"] for s in best_chain])),
                    "a": a, "b": b, "n": len(best_chain),
                    "y_lo": min(ys), "y_hi": max(ys)})
    # A value axis is labelled the full height of the plot. IFS also numbers
    # the EVENT MARKERS down the right-hand side, 1..N, and once an interval
    # runs past sixteen events four of those numbers ("17 18 19 20") sit in
    # their own column, evenly spaced, arithmetic — indistinguishable from a
    # tick ladder except that they cover a fifth of the frame. On 00001
    # interval 3 (41 events) that phantom column took axis B, which pushed
    # Slurry Rate onto a 17..20 scale and BOTH concentrations onto the rate
    # axis: WH Prop Conc came back as 16.59 kg/m3 on a 0..16 scale (#77).
    if out:
        tallest = max(c["y_hi"] - c["y_lo"] for c in out)
        out = [c for c in out if c["y_hi"] - c["y_lo"] >= 0.6 * tallest]
    out.sort(key=lambda c: c["x"])
    return out


def _time_axis(spans):
    """HH:MM(:SS) labels row -> seconds = a + b * x, plus start date if shown."""
    tspans = [s for s in spans if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    if len(tspans) < 3:
        return None, ""
    # keep the y-row with the most time labels (legend times would be rare)
    rows = defaultdict(list)
    for s in tspans:
        rows[round(s["cy"] / 6)].append(s)
    row = max(rows.values(), key=len)
    if len(row) < 3:
        return None, ""
    row.sort(key=lambda s: s["cx"])
    vals = []
    for s in row:
        parts = [int(p) for p in s["t"].split(":")]
        secs = parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)
        vals.append((secs, s["cx"]))
    # unwrap midnight
    for i in range(1, len(vals)):
        if vals[i][0] < vals[i - 1][0] - 20000:
            vals[i] = (vals[i][0] + 86400, vals[i][1])
    a, b = _fit(vals)
    if b <= 0:
        return None, ""
    # a date label like 3/3/2019 often sits under the first tick
    date = ""
    for s in spans:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s["t"])
        if m:
            date = f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            break
    return (a, b), date


def _legend(spans):
    """[(series_name, unit, color_int, axis_letter)] from legend rows."""
    out = []

    def add(s, letters):
        m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", s["t"])
        if not m or len(m.group(1).strip()) < 3:
            return
        name, unit = m.group(1).strip(), m.group(2).strip()
        # the axis letter of the same color on (nearly) the same line
        best, bestd = None, 1e9
        for l in letters:
            if l["color"] != s["color"]:
                continue
            d = abs(l["cy"] - s["cy"])
            if d < 4 and l["cx"] > s["cx"] and (l["cx"] - s["cx"]) < bestd:
                best, bestd = l["t"], l["cx"] - s["cx"]
        if best:
            out.append((name, unit, s["color"], best))

    named = [s for s in spans if s["color"] != 0 and
             re.search(r"\(([^)]+)\)\s*$", s["t"]) and len(s["t"]) > 8]
    letters = [s for s in spans if s["color"] != 0 and re.fullmatch(r"[A-F]", s["t"])]
    for s in named:
        add(s, letters)

    # one black series (e.g. N2 Standard Rate) has a black name + black axis
    # letter. Accept it only when exactly one such black-named series exists,
    # since black curves share ink and can't be separated by colour.
    black_named = [s for s in spans if s["color"] == 0 and "IFS" not in s["t"]
                   and re.fullmatch(r".{3,}?\s*\([A-Za-z][^)]{0,9}\)", s["t"])]
    if len(black_named) == 1:
        black_letters = [s for s in spans if s["color"] == 0 and re.fullmatch(r"[A-F]", s["t"])]
        add(black_named[0], black_letters)
    return out


def _color_close(stroke, legend_int):
    lr = ((legend_int >> 16) & 255) / 255
    lg = ((legend_int >> 8) & 255) / 255
    lb = (legend_int & 255) / 255
    return sum((a - b) ** 2 for a, b in zip(stroke, (lr, lg, lb))) < 0.02


def _pen_resample(t, v, spans, samples, sample_sec=1.0):
    """Stroked segments -> the sample grid, WITHOUT inventing anything.

    frac_core._resample is written for MView, where every series is drawn
    across the whole plot and the chart merely omits the leading flatline. It
    does two things that are wrong on an IFS page:

      * np.interp draws a straight line across ANY hole in the curve. An IFS
        concentration series is pen-down only while proppant is being pumped,
        so the hole is most of the interval and the export carried a straight
        ramp through it — Carmine's "straight line extending past the chart"
        (#75-#77) and "pen up down issues" (#65);
      * it holds the first value back to t=0. The grid starts when the FIRST
        series starts (pressure), so a concentration curve that begins 38
        minutes later was exported as a flat line at its opening value for
        those 38 minutes — 00001 stage 1 drew exactly that at 0.19 kg/m3.

    A segment IS the pen being down, so the union of the segments' time spans
    is where this series has data. Everything else is blank, which the
    exporter writes as an empty cell.
    """
    uniq, inv = np.unique(np.round(t, 6), return_inverse=True)
    vu = np.bincount(inv, weights=v) / np.bincount(inv)
    out = np.interp(samples, uniq, vu, left=np.nan, right=np.nan)
    if not len(spans):
        return out
    tol = max(float(sample_sec), 1.0)
    order = np.argsort(spans[:, 0], kind="stable")
    cov = np.zeros(len(samples), dtype=bool)
    lo, hi = spans[order[0]]
    for a, b in spans[order[1:]]:
        if a <= hi + tol:                     # same pen-down stretch
            hi = max(hi, b)
            continue
        cov |= (samples >= lo - tol) & (samples <= hi + tol)
        lo, hi = a, b
    cov |= (samples >= lo - tol) & (samples <= hi + tol)
    out[~cov] = np.nan
    return out


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {column: values}, channel_info) for an IFS chart page."""
    rotated = page_rotated(page)
    spans = _spans(page, rotated)
    text = page.get_text()
    tfit, date = _time_axis(spans)
    if tfit is None:
        raise ValueError("IFS: time axis labels not found")
    ta, tb = tfit
    legend = _legend(spans)
    if not legend:
        raise ValueError("IFS: legend not found")
    columns = _axis_columns(spans)
    if not columns:
        raise ValueError("IFS: no axis tick columns")
    # axis letters -> columns: A = leftmost; remaining right-side columns in
    # x order take B, C, D...  (IFS convention)
    letters_used = sorted({ax for *_, ax in legend})
    mapping = {}
    if "A" in letters_used:
        mapping["A"] = columns[0]
    rest = [ax for ax in letters_used if ax != "A"]
    right = columns[1:] if len(columns) > 1 else columns
    for i, ax in enumerate(rest):
        mapping[ax] = right[min(i, len(right) - 1)]

    # collect stroked SEGMENTS per legend color. Segments, not loose points:
    # a segment is one stretch of pen-down, and the union of their time spans
    # is the only honest statement of where this series has data at all. See
    # _pen_resample.
    pts_by_color = defaultdict(list)
    for d in page.get_drawings():
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        if r.width < 10 and r.height < 10:
            continue                       # event-marker glyphs, not curves
        for name, unit, cint, ax in legend:
            if _color_close(c, cint):
                lst = pts_by_color[cint]
                for item in d["items"]:
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        if cint == 0:
                            # black series shares ink with axes/grid: drop long
                            # axis-aligned segments (frame + gridlines)
                            if (abs(p1.x - p2.x) < 0.01 or abs(p1.y - p2.y) < 0.01) and \
                               max(abs(p1.x - p2.x), abs(p1.y - p2.y)) > 5:
                                continue
                        pp = [(p1.x, p1.y), (p2.x, p2.y)]
                    elif item[0] == "c":
                        pp = [(item[1].x, item[1].y), (item[4].x, item[4].y)]
                    else:
                        continue
                    if rotated:
                        pp = [_unrotate(x, y) for x, y in pp]
                    lst.append(pp)
                break

    # plot time-range: clip to the plot FRAME, not the time-label span. IFS
    # (like BJ/Liberty) insets its first/last time labels from the frame
    # edges, so each interval's opening ramp sits between the frame and the
    # first labeled gridline and a label-based window clips it. The frame is
    # the outermost full-height vertical gridlines (in the unrotated frame);
    # the per-column value band and legend-color match already exclude
    # off-plot strokes, so widening to the frame only recovers real points.
    t_row = [s for s in spans if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s["t"])]
    lab_lo = min(s["cx"] for s in t_row)
    lab_hi = max(s["cx"] for s in t_row)
    vgrid = []
    for d in page.get_drawings():
        if d.get("color") is None or d["type"] not in ("s", "fs"):
            continue
        for item in d["items"]:
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            ax, ay = (_unrotate(p1.x, p1.y) if rotated else (p1.x, p1.y))
            bx, by = (_unrotate(p2.x, p2.y) if rotated else (p2.x, p2.y))
            if abs(ax - bx) < 0.6 and abs(ay - by) > 100:
                vgrid.append((ax + bx) / 2)
    if vgrid:
        # never narrower than the old label-based window (stay a superset)
        x_lo = min(min(vgrid) - 2, lab_lo - 30)
        x_hi = max(max(vgrid) + 2, lab_hi + 30)
    else:
        x_lo, x_hi = lab_lo - 30, lab_hi + 30

    meta = PageMeta()
    m = re.search(r"UWI:\s*(1[0-9A-F]\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups())
    m = re.search(r"Interval\s+(\d+)", text)
    if m:
        meta.stage = m.group(1)
    meta.date = date
    t = re.search(r"Interval\s+\d+\s*[-\u2013]\s*[A-Za-z ]+", text)
    meta.title = (t.group(0).strip() if t
                  else " ".join(text.strip().splitlines()[0].split()))[:60]

    # The PLOT FRAME, in the same coordinates the points are read in. Every
    # tick column brackets the same frame vertically except where its labels
    # stop short of it, so the median pair is the frame and an individual
    # column's extent is not.
    used = []
    for c in mapping.values():
        if c not in used:
            used.append(c)
    lo_s = sorted(c["y_lo"] for c in used)
    hi_s = sorted(c["y_hi"] for c in used)
    v_top = float(lo_s[len(lo_s) // 2])
    v_bot = float(hi_s[len(hi_s) // 2])
    if v_bot < v_top:
        v_top, v_bot = v_bot, v_top

    t_min_all, t_max_all = None, None
    series = {}
    series_axis = {}                 # (name, unit) -> the tick column it reads
    info = {}
    for name, unit, cint, ax in legend:
        segs = pts_by_color.get(cint)
        col = mapping.get(ax)
        if not segs or col is None:
            continue
        # Clip to the FRAME, not to this column's own tick extent ±12pt. That
        # slack was wrong in both directions on every IFS file sampled:
        #  - too generous above. The legend key is drawn in the series' own
        #    colour a few points above the frame, so its swatch line entered
        #    the data as two points at a value ABOVE the axis maximum — which
        #    is how 00001 stage 1 reported WH Prop Conc 829.85 on a 0..800
        #    scale (#75), and why the Lab drew a straight line diving in from
        #    off the top of the chart: np.interp ran from that phantom point
        #    to the first real one.
        #  - too strict below. The concentration column labels 100..800, so
        #    y_hi is the 100 gridline and everything the curve does under
        #    ~44 kg/m3 fell outside the window: 622 and 704 real points cut
        #    from the two concentration series on that page alone, each cut
        #    leaving a hole np.interp then bridged with a straight line.
        arr = np.array(segs, dtype=float)          # (m, 2, 2)
        inside = ((arr[:, :, 0] >= x_lo) & (arr[:, :, 0] <= x_hi) &
                  (arr[:, :, 1] >= v_top - 2) & (arr[:, :, 1] <= v_bot + 2))
        arr = arr[inside.all(axis=1)]
        if arr.size < 60:
            continue
        t = ta + tb * arr[:, :, 0]
        v = col["a"] + col["b"] * arr[:, :, 1]
        span = np.stack([t.min(axis=1), t.max(axis=1)], axis=1)
        t, v = t.reshape(-1), v.reshape(-1)
        order = np.argsort(t, kind="stable")
        series[(name, unit)] = (t[order], v[order], span)
        series_axis[(name, unit)] = col
        lo, hi = t.min(), t.max()
        t_min_all = lo if t_min_all is None else min(t_min_all, lo)
        t_max_all = hi if t_max_all is None else max(t_max_all, hi)
    if not series:
        raise ValueError("IFS: no series curves matched the legend colors")

    n = int(t_max_all - t_min_all)
    if not (60 < n < 100000):
        raise ValueError(f"IFS: implausible duration {n}s")
    meta.duration_min = n / 60.0
    samples = np.arange(int(n / sample_sec)) * sample_sec

    def std_name(raw):
        low = raw.lower()
        for keys, std in STD_NAMES:
            if any(k in low for k in keys):
                return std
        return raw[:24]

    # --- chart geometry in PAGE coordinates, for the Lab's synced view ---
    # Everything above works in the CANONICAL frame, which _unrotate maps a
    # 90°-filed page into: canonical x is page x when the page is filed
    # upright and page -y when it is filed rotated, and canonical y is page y
    # / page x to match. That is exactly the axis "x"/"y" distinction the Lab
    # encodes, so the rotated case is a sign flip on tb and nothing else.
    #
    # Two things this has to get right, both silent when wrong:
    #  - `ta` is relative to the STAGE start. The samples below begin at
    #    t_min_all, so quoting the absolute clock fit here would slide the
    #    backdrop by however far into the job this interval sat.
    #  - v0/v1 and every channel's axes_frame are read at the SAME page
    #    coordinates. Quoting a curve against its own tick extent while the
    #    page is placed by a different pair leaves it a constant distance off
    #    its own ink (the concentration column labels 100..800, not 0..800,
    #    so its extent is not the frame's).
    meta.geom = {"axis": "y" if rotated else "x",
                 "ta": float(ta - t_min_all),
                 "tb": float(-tb if rotated else tb),
                 "v0": v_top, "v1": v_bot}

    data, chinfo, axes, axes_frame = {}, {}, {}, {}
    for (name, unit), (t, v, span) in series.items():
        col = std_name(name)
        if col in data:
            continue
        vals = _pen_resample(t - t_min_all, v, span - t_min_all, samples,
                             sample_sec)
        data[col] = vals
        chinfo[col] = {"label": name, "unit": unit}
        acol = series_axis.get((name, unit))
        if acol:
            p_lo = acol["a"] + acol["b"] * acol["y_hi"]
            p_hi = acol["a"] + acol["b"] * acol["y_lo"]
            axes[col] = (float(min(p_lo, p_hi)), float(max(p_lo, p_hi)))
            axes_frame[col] = (float(acol["a"] + acol["b"] * v_top),
                               float(acol["a"] + acol["b"] * v_bot))
    meta.axes = axes
    meta.axes_frame = axes_frame
    # start time of day for DATETIME column
    if meta.date:
        h = int(t_min_all // 3600) % 24
        mnt = int(t_min_all % 3600 // 60)
        s = int(t_min_all % 60)
        meta.start_time = f"{h:02d}:{mnt:02d}:{s:02d}"
    return meta, samples, data, chinfo


# The treatment phases that count as a stage's own chart. "Breakdown",
# "Ball Action", "Stage Summary" and "Chemical Additives" are the other
# sections of the same interval and are not the treatment.
TREATMENT_PHASES = ("Main Treatment", "Entire Treatment")

_SECTION = re.compile(r"^(\d{1,2})\.(\d{1,2})$")


def section_stage(page):
    """-> (interval, phase) for IFS v4.2.0 pages, else None.

    v4.3.1 and v4.6.3 title the chart "Interval 7 – Main Treatment". v4.2.0
    names neither: it prints the section number and the phase on their own
    lines ("7.3" then "Main Treatment"), leaving the interval implied by the
    section's major number. The pipeline gate looked for the newer wording, so
    every chart in these reports was skipped and the file came back with no
    extractable data (Carmine's report on 00003).

    The phase must follow the section line — a bare "N.M" is also how this
    template prints ordinary measurements ("56.86"), and taking the first one
    on the page would match those.
    """
    try:
        lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    except Exception:
        return None
    for i, line in enumerate(lines[:-1]):
        m = _SECTION.match(line)
        if m and lines[i + 1] in TREATMENT_PHASES:
            return int(m.group(1)), lines[i + 1]
    return None
