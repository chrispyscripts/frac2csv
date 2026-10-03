"""Canyon Technical Services chart template (Canyon-1 in Carmine's codes).

One page per interval: three stacked panels — Pressure (MPa), Rate (m³/min),
Concentration (kg/m³) — sharing an HH:MM time axis. Legends are black text
names preceded by colored line samples, so color↔series mapping comes from
the stroke nearest each name. Header block: Ticket#, Customer, LSD (DLS
UWI), Date, Interval "#N - depth".
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta, _resample

PANEL_UNITS = {"Pressure": "MPa", "Rate": "m³/min", "Concentration": "kg/m³"}


class NotAStageChart(ValueError):
    """This page is a chart, and deliberately not exported as a stage.

    Distinct from a parse failure so the caller can say "skipped" instead of
    "failed". An honest skip and a broken parser look identical in the Lab,
    and that confusion is what 197 "No extractable data" reports were made of.
    """


def detect(page):
    t = page.get_text()
    has_ticket = "Ticket#:" in t or "Ticket #:" in t
    return has_ticket and ("Pressure (MPa)" in t or "Rate (m³/min)" in t)


def _spans(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    x0, y0, x1, y1 = span["bbox"]
                    out.append({"t": t, "x0": x0, "x1": x1,
                                "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def _fit(pairs):
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    A = np.vstack([np.ones_like(c), c]).T
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(a), float(b)


def _black_is_curve(p1, p2):
    """Black shares its ink with the axes, the grid and the tick marks.

    A long axis-aligned segment is a frame or a gridline and was always
    dropped. The TICK MARKS were not: each is a 2.4-pt vertical on the
    panel's time axis, one per time label, and it slipped under the 5-pt
    floor — so every black series (BHP, Combined WH, Proppant Blender on
    00229) took a point ON THE BASELINE at every label and exported a
    plunge to zero there, the same second in all three panels (#629). The
    rendered chart shows nothing of the kind.

    A curve sampled in time is never exactly vertical — of 12,000 coloured
    segments on that page, none was — so any vertical black segment is the
    axis's, whatever its length. Exactly horizontal ones can be a hold at a
    constant value, so those keep the length test.
    """
    dx, dy = abs(p1.x - p2.x), abs(p1.y - p2.y)
    if dx < 0.01:
        return False
    if dy < 0.01 and dx > 5:
        return False
    return True


def _black_rules(drawings):
    """-> (rules, verticals). rules: [(x0, x1, y)] for every long horizontal
    black rule on the page, the plot frames' borders among them. verticals:
    [(x, y0, y1)] for every long vertical one."""
    rules, verticals = [], []
    for d in drawings:
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs") \
                or tuple(round(x, 2) for x in c) != (0.0, 0.0, 0.0):
            continue
        for item in d["items"]:
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) < 0.01 and abs(p1.x - p2.x) > 100:
                rules.append((min(p1.x, p2.x), max(p1.x, p2.x), p1.y))
            elif abs(p1.x - p2.x) < 0.01 and abs(p1.y - p2.y) > 100:
                verticals.append((p1.x, min(p1.y, p2.y), max(p1.y, p2.y)))
    return rules, verticals


def _frame_x(rules, y_lo, y_hi):
    """(left, right) of the panel's plot frame, or None when it draws no
    black border to measure."""
    xs = [(a, b) for a, b, y in rules if y_lo <= y <= y_hi]
    if not xs:
        return None
    return min(a for a, _b in xs), max(b for _a, b in xs)


def _outside(frame, p1, p2):
    """Black ink wholly outside the plot frame is the axis's, not a curve's.

    The value axis's tick marks are short black horizontals just left of the
    frame — 43.2-46.8 against a frame edge at 48.2 on 00203 — and a black
    series took one point at every labelled value there: 00203's Bottom Hole
    read 0-81 MPa where the chart draws 36-69, and each stage started 90
    seconds before its own frame. Same shape as the time axis's ticks
    (#629), on the other axis."""
    if frame is None:
        return False
    lo, hi = frame
    return max(p1.x, p2.x) < lo - 0.5 or min(p1.x, p2.x) > hi + 0.5


def _frame_cap(d, rules, verticals):
    """A speck of black that carries a frame rule past its end is the frame's
    cap, not a curve.

    00203 closes each frame with two of them, 0.24pt long, drawn as paths of
    their own: one runs on from the top rule's right end (583.92 -> 584.16),
    one sits just below the left rule's foot (312.24 -> 312.48). A black
    series took a point at each, the top of its axis and below the bottom of
    it, and Bottom Hole's range read 0-81 MPa where the chart draws 36-69.

    Judged by where it sits relative to the rule, never by size alone: the
    2016 sheets (00170, 00179) draw every segment of a black curve as a path
    of its own, most of them under a point long, and a curve resting at zero
    starts exactly ON the frame's corner. Those lie inside the frame, so
    they stay; only ink running beyond the end of the frame's own rule goes."""
    r = d["rect"]
    if len(d["items"]) > 4 or (r.width + r.height) >= 1.0:
        return False
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    for x0, x1, y in rules:
        if abs(cy - y) < 0.6 and ((r.x1 > x1 + 0.1 and r.x0 <= x1 + 0.6)
                                  or (r.x0 < x0 - 0.1 and r.x1 >= x0 - 0.6)):
            return True
    for x, y0, y1 in verticals:
        if abs(cx - x) < 0.6 and ((r.y1 > y1 + 0.1 and r.y0 <= y1 + 1.0)
                                  or (r.y0 < y0 - 0.1 and r.y1 >= y0 - 1.0)):
            return True
    return False


_HHMM = re.compile(r"\b\d{1,2}:\d{2}\b")


def _paired_times(page):
    """[{t, cx, cy}] for each HH:MM inside a span that holds more than one.

    Each label is placed at the centre of its OWN characters, read from the
    page's glyph boxes, never by dividing the span's width: the gap between
    two labels is a space, which is narrower than a digit."""
    out = []
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return out
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.get("chars", [])
                text = "".join(c.get("c", "") for c in chars)
                hits = list(_HHMM.finditer(text))
                if len(hits) < 2:
                    continue
                for m in hits:
                    boxes = [chars[i]["bbox"] for i in range(m.start(), m.end())]
                    x0 = min(b[0] for b in boxes)
                    x1 = max(b[2] for b in boxes)
                    y0 = min(b[1] for b in boxes)
                    y1 = max(b[3] for b in boxes)
                    out.append({"t": m.group(0), "x0": x0, "x1": x1,
                                "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def _stroke_sample(d):
    """a stroked legend sample's colour (a short line before the name)"""
    c = d.get("color")
    if c is None or d["type"] not in ("s", "fs"):
        return None
    return tuple(round(x, 2) for x in c)


def _filled_sample(d):
    """a filled legend sample's colour: a swatch box, never a background.

    Swatch-sized only (00203's are 16.8 x 10.6pt), and never white, which is
    what a page's background and legend boxes are filled with."""
    c = d.get("fill")
    if c is None or d["type"] != "f":
        return None
    r = d["rect"]
    if r.width > 30 or r.height > 15:
        return None
    c = tuple(round(x, 2) for x in c)
    return None if c == (1.0, 1.0, 1.0) else c


def _legend_sample(drawings, s, colour_of):
    """colour of the nearest sample ending within 30pt left of name span s,
    on its line, or None"""
    best, bestd = None, 30
    for d in drawings:
        c = colour_of(d)
        if c is None:
            continue
        r = d["rect"]
        ry = (r.y0 + r.y1) / 2
        if abs(ry - s["cy"]) < 4 and 0 < s["x0"] - r.x1 < bestd:
            best, bestd = c, s["x0"] - r.x1
    return best


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    text = page.get_text()

    meta = PageMeta()
    m = re.search(r"(1[0-9A-F]\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)", text)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups())
    else:
        m = re.search(r"\b([a-dA-D])-?([A-Z]?\d{2,3})-([A-L])\s*/\s*0?(\d{2,3})-([A-P])-0?(\d{1,2})\b", text)
        if m:
            q, unit, blk, sheet, letter, num = m.groups()
            unit_num = unit if unit[:1].isalpha() else f"{int(unit):03d}"
            meta.uwi = (f"200{q.upper()}{unit_num}{blk.upper()}"
                        f"{int(sheet):03d}{letter.upper()}{int(num):02d}00")
    # Labels and values are separated in the text stream, so the interval has
    # to be found by its own shape rather than by what it sits next to —
    # reading the span after the "Interval:" LABEL hands back the ticket
    # number. The 2014 layout prints "#1 - 3709.32m"; the 2017 ones print a
    # bare "#1" (00204) or drop the "Interval:" label altogether and print the
    # number alone (00203, Painted Pony). Requiring the depth left every chart
    # page of both 2017 families with NO stage at all, so nothing could be
    # joined to a table by interval. Checked across all 92 chart pages of
    # 00009, 00203 and 00204: each has exactly ONE "#N" on it and the sequence
    # runs in order, so the bare form is safe to fall back to. A ticket number
    # is never at risk — those print as "Ticket#: 40-015318", digits separated
    # from the "#" by the colon.
    # A page whose Interval field names a RANGE of stages is Canyon's per-day
    # OVERVIEW plot, not a stage: 00011 prints "#1 - 6", "#7-14", "#15 - 21"
    # and "#22 - 25" on pages 161-167, after its 25 per-stage charts. Those
    # four carried no depth, so the bare "#N" fallback below read each as the
    # FIRST stage of its range and handed back stages 1, 7, 15 and 22 a second
    # time — 420, 528, 414 and 241 minutes long against a 68-minute median.
    # Same key as the real stage, so the Lab merged them and drew stage 1 on a
    # 7-hour axis with the actual stage squeezed into the left fifth of it.
    #
    # Dropped rather than relabelled, for the reason the client already gave
    # about SLB's whole-job plot: all of the data necessary is in the
    # individual charts, at full resolution, and this is the same data zoomed
    # out. The depth form must still win — "#1 - 3689.04m" is a stage, and the
    # lookaheads are what keep 3689 from reading as the end of a range.
    rng = re.search(r"#\s*(\d+)\s*-\s*(\d+)(?![\d.,])(?!\s*m\b)", text)
    if rng and int(rng.group(2)) > int(rng.group(1)):
        raise NotAStageChart(
            f"charts stages "
            f"{rng.group(1)}-{rng.group(2)} on one axis — each of those "
            f"stages has its own chart in this report")
    m = (re.search(r"#(\d+)\s*-\s*[\d,.]+\s*m\b", text)
         or re.search(r"#\s*(\d+)\b", text))
    if m:
        meta.stage = m.group(1)
        # A stage pumped in two runs prints two charts: 00229's "#7 - Shut
        # down early" on p37 and "#7 - continued" on p39. Both said "7",
        # the Lab merged a 35-minute chart with a 46-minute one, and the
        # audit called it a doubled stage. CalFrac's second run of a zone
        # is "13 (2)" (#617); the same name here keeps the two apart.
        if re.search(r"#\s*" + m.group(1) + r"\b[^\n]{0,40}?\bcontinued\b", text, re.I):
            meta.stage = f"{m.group(1)} (2)"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        meta.date = m.group(0)
    meta.title = f"Canyon interval {meta.stage or '?'}"

    # panels: title spans mark panel tops
    panels = []
    for s in spans:
        pm = re.match(r"(Pressure|Rate|Concentration)\s*\(", s["t"])
        if pm:
            panels.append({"name": pm.group(1), "title_y": s["cy"], "x": s["cx"]})
    if not panels:
        raise ValueError("canyon: no panel titles")
    panels.sort(key=lambda p: p["title_y"])
    page_h = page.rect.height
    for i, p in enumerate(panels):
        p["y_end"] = panels[i + 1]["title_y"] if i + 1 < len(panels) else page_h

    # per-panel: y-axis ticks (black numerals, left column), time row, legend
    drawings = page.get_drawings()
    rules, verticals = _black_rules(drawings)
    paired = None
    all_series = {}
    units = {}
    t_fit_global = None
    for p in panels:
        band = [s for s in spans if p["title_y"] < s["cy"] < p["y_end"]]
        nums = [s for s in band if re.fullmatch(r"[\d,]+(\.\d+)?", s["t"])]
        if not nums:
            continue
        left_x = min(s["cx"] for s in nums)
        ticks = [s for s in band if re.fullmatch(r"[\d,]+(\.\d+)?", s["t"])
                 and s["cx"] < left_x + 25]
        if len(ticks) < 3:
            continue
        vfit = _fit([(float(s["t"].replace(",", "")), s["cy"]) for s in ticks])
        y_lo = min(s["cy"] for s in ticks) - 8
        y_hi = max(s["cy"] for s in ticks) + 8
        frame = _frame_x(rules, y_lo, y_hi)

        tl = [s for s in band if re.fullmatch(r"\d{1,2}:\d{2}", s["t"])]
        if len(tl) < 3:
            # 00301 p39 prints its labels in pairs, "13:15 13:30" as ONE
            # span, so only the two lone ends were found and its 4h20m stage
            # had no clock at all. Asked only when the lone labels are too
            # few to fit, so no page that already fitted is touched.
            if paired is None:
                paired = _paired_times(page)
            tl = tl + [s for s in paired
                       if p["title_y"] < s["cy"] < p["y_end"]]
        if len(tl) >= 3:
            vals = []
            for s in sorted(tl, key=lambda s: s["cx"]):
                h, mnt = s["t"].split(":")
                vals.append((int(h) * 3600 + int(mnt) * 60, s["cx"]))
            for i in range(1, len(vals)):
                if vals[i][0] < vals[i - 1][0] - 20000:
                    vals[i] = (vals[i][0] + 86400, vals[i][1])
            tf = _fit(vals)
            if tf[1] > 0:
                t_fit_global = tf
                x_lo = min(v[1] for v in vals) - 15
                x_hi = max(v[1] for v in vals) + 15
                p["x_range"] = (x_lo, x_hi)
        if t_fit_global is None:
            continue

        # legend: black names on/near the title row; a coloured sample left
        # of each. Taken from the whole page, not the panel's band: the band
        # starts BELOW the title, and the 2017 Painted Pony sheets (#771,
        # 00203/00213/00301...) print their legend 2.2pt ABOVE it, so every
        # name was outside the band and no curve on 97 filings was ever named.
        legend_row = [s for s in spans if abs(s["cy"] - p["title_y"]) < 8
                      and s["cx"] > p["x"] + 40
                      and re.search(r"[A-Za-z]", s["t"])]
        name_color = {}
        for s in legend_row:
            best = _legend_sample(drawings, s, _stroke_sample)
            # Those same sheets draw each sample as a small FILLED box
            # rather than a line. Asked only when no stroked sample is found,
            # so a page that already read keeps exactly the colours it had.
            if best is None:
                best = _legend_sample(drawings, s, _filled_sample)
            if best:
                name_color.setdefault(s["t"], best)

        # curves: strokes within the panel plot box, keyed by legend color
        x_lo, x_hi = p.get("x_range", (0, page.rect.width))
        color_names = defaultdict(list)
        for name, color in name_color.items():
            color_names[color].append(name)
        for color, names in color_names.items():
            pts = []
            for d in drawings:
                c = d.get("color")
                if c is None or d["type"] not in ("s", "fs"):
                    continue
                if tuple(round(x, 2) for x in c) != color:
                    continue
                black = color == (0.0, 0.0, 0.0)
                if black and _frame_cap(d, rules, verticals):
                    continue
                for item in d["items"]:
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        if black and (not _black_is_curve(p1, p2)
                                      or _outside(frame, p1, p2)):
                            continue
                        pts.append((p1.x, p1.y))
                        pts.append((p2.x, p2.y))
                    elif item[0] == "c":
                        if black and _outside(frame, item[1], item[4]):
                            continue
                        pts.append((item[1].x, item[1].y))
                        pts.append((item[4].x, item[4].y))
            if len(pts) < 40:
                continue
            arr = np.array(pts)
            keep = ((arr[:, 0] >= x_lo) & (arr[:, 0] <= x_hi) &
                    (arr[:, 1] >= y_lo) & (arr[:, 1] <= y_hi))
            arr = arr[keep]
            if len(arr) < 40:
                continue
            ta, tb = t_fit_global
            t = ta + tb * arr[:, 0]
            v = vfit[0] + vfit[1] * arr[:, 1]
            order = np.argsort(t, kind="stable")
            name = names[0] if len(names) == 1 else " / ".join(sorted(names))
            all_series[name] = (t[order], v[order])
            units[name] = PANEL_UNITS.get(p["name"], "")

    if not all_series or t_fit_global is None:
        raise ValueError("canyon: no calibrated series")
    t_lo = min(t.min() for t, _ in all_series.values())
    t_hi = max(t.max() for t, _ in all_series.values())
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"canyon: implausible duration {n}s")
    meta.duration_min = n / 60.0

    # geometry for the Lab's synced "Compare Original" view. Time runs along
    # x; the three stacked panels share it, so the value extent spans the
    # whole plotted region (top panel's frame down to the bottom panel's) —
    # the horizontal gridlines across all panels give that span.
    hgrid = []
    for d in drawings:
        if d.get("color") is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        if abs(r.y1 - r.y0) < 0.6 and (r.x1 - r.x0) > 100:
            hgrid.append((r.y0 + r.y1) / 2)
    if hgrid:
        ta, tb = t_fit_global
        meta.geom = {"axis": "x", "ta": float(ta - t_lo), "tb": float(tb),
                     "v0": float(min(hgrid)), "v1": float(max(hgrid))}
    if meta.date:
        h = int(t_lo // 3600) % 24
        meta.start_time = f"{h:02d}:{int(t_lo % 3600 // 60):02d}:{int(t_lo % 60):02d}"
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {}
    for name, (t, v) in all_series.items():
        data[name] = _resample(t - t_lo, v, samples)
    return meta, samples, data, units
