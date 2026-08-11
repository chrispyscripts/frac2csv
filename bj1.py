"""BJ / Baker Hughes chart template (BJ-1 in Carmine's codes).

One vector chart page per stage: title "UWI - Well X - Stage NN", time
axis labeled "Mon-DD HH:MM" (slanted black spans), stacked y-axes whose
numeric tick columns sit left/right of the plot with rotated axis-name
spans beside them (a shared axis names two series in one span). Legend
names are black text with a colored dash stroke to the left, so the
color↔series map comes from the dash nearest each name (Canyon-style).
"""
import re
from collections import defaultdict

import fitz
import numpy as np

from frac_core import PageMeta, _resample

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
TIME_RE = re.compile(r"([A-Z][a-z]{2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")


def detect(page):
    t = page.get_text()
    return ("Stage" in t and TIME_RE.search(t) is not None
            and re.search(r"\d{3}/\d{2}-\d{2}-\d{3}-\d{2}W\d", t) is not None)


def _spans(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    x0, y0, x1, y1 = span["bbox"]
                    out.append({"t": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                                "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return out


def _fit(pairs):
    v = np.array([p[0] for p in pairs], float)
    c = np.array([p[1] for p in pairs], float)
    A = np.vstack([np.ones_like(c), c]).T
    (a, b), *_ = np.linalg.lstsq(A, v, rcond=None)
    return float(a), float(b)


def _doc_year_map(doc):
    """{(month, day): year} harvested from full 'YYYY-MM-DD' dates anywhere
    in the document — the frac charts label only 'Mon-DD', so the year comes
    from the per-stage data tables. Cached on the document."""
    cached = getattr(doc, "_bj1_year_map", None)
    if cached is not None:
        return cached
    m = {}
    for p in range(len(doc)):
        for mo in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", doc[p].get_text()):
            m[(int(mo.group(2)), int(mo.group(3)))] = int(mo.group(1))
    try:
        doc._bj1_year_map = m
    except Exception:
        pass
    return m


def filename_year(name):
    """Year from a COMP filename ('..._COMP_2024JAN22_...') — survives the
    Lab's client-side page chunking, where the chart page and the dated
    tables can land in different chunks."""
    if not name:
        return None
    m = re.search(r"COMP[_-]?(20\d{2})", name) or re.search(r"\b(20\d{2})\b", name)
    return int(m.group(1)) if m else None


def _resolve_year(doc, mon, day):
    """Best year for a chart's start (month, day): an exact date-table match
    first; then the filename COMP-date hint (more reliable than a chunk that
    may hold only drilling-era dates under the Lab's page splitting); then
    the most common year in the doc; else 2000."""
    ymap = _doc_year_map(doc)
    if (mon, day) in ymap:
        return ymap[(mon, day)]
    hint = getattr(doc, "_bj1_year_hint", None)
    if hint:
        return hint
    if ymap:
        years = list(ymap.values())
        return max(set(years), key=years.count)
    return 2000


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    text = page.get_text()

    meta = PageMeta()
    m = re.search(r"(\d{3})/(\d{2})-(\d{2})-(\d{3})-(\d{2})W(\d)"
                  r".*?Stage\s*(\d+)", text, re.S)
    if m:
        meta.uwi = "{}{}{}{}{}W{}00".format(*m.groups()[:6])
        meta.stage = str(int(m.group(7)))
    title = next((s["t"] for s in spans if " - Stage" in s["t"]), "")
    meta.title = title[:60]

    # A stage can be charted MORE THAN ONCE. BJ names the aborted run in the
    # title — "- Stage 06 Plug Slip", "- Stage 17 HRF", "- Stage 41 Winterize"
    # — and numbers a re-pump "- Stage 10.1"; the treatment that actually
    # counts keeps the bare "- Stage 06". Reading the number alone filed both
    # under one stage, and every consumer merges same-stage charts by sample
    # index (pipeline_export.build_well, the Lab's stageItems). A 10-minute
    # plug slip and the 96-minute frac that followed it therefore fused into
    # one block: rate and pressure came from the slip, the concentrations from
    # the frac, over a row count belonging to neither — the plot filled a tenth
    # of a 96-minute grid and the header read "10 min · 5,758 samples".
    # Keep the printed suffix in the stage key so each treatment stays its own
    # chart, exactly as Liberty does for "Attempt 1/2" and STEP for "1.2".
    # Conservative by construction: the suffix must start with a letter and
    # hold only plain word/number text, and the number must be the one already
    # read above, or nothing changes. The space before the word is optional —
    # the operators also type "Stage 36.2HRF" with no gap.
    ms = re.search(r"-\s*Stage\s*(\d+(?:\.\d+)?)"
                   r"(?:\s*([A-Za-z][A-Za-z0-9. ]{0,19}))?\s*$", title)
    if ms:
        head, _dot, sub = ms.group(1).partition(".")
        stage = str(int(head)) + (f".{sub}" if sub else "")
        qual = " ".join((ms.group(2) or "").split())
        if qual:
            stage += " " + qual
        if meta.stage == str(int(head)) and stage != meta.stage:
            meta.stage = stage

    # time axis: slanted "Mon-DD HH:MM" labels; right bbox edge sits on
    # the gridline they annotate
    tpts = []
    daytags = []
    tlabels = []
    for s in spans:
        m = TIME_RE.fullmatch(s["t"])
        if m:
            mon, day, hh, mm = m.groups()
            if mon not in MONTHS:
                continue
            secs = ((MONTHS[mon] * 31 + int(day)) * 86400
                    + int(hh) * 3600 + int(mm) * 60)
            tpts.append((secs, s["x1"], s["cy"]))
            daytags.append((secs, MONTHS[mon], int(day)))
            # re-printed, not the raw span text: TIME_RE tolerates "Apr-6"
            # and a run of spaces, and two pages of ONE chart must not look
            # different because of typesetting
            tlabels.append((secs, f"{mon}-{int(day):02d} "
                                  f"{int(hh):02d}:{mm}"))
    if len(tpts) < 3:
        raise ValueError("bj1: time labels not found")
    # year rollover inside a stage: "Dec-31 ... Jan-01" labels wrap the
    # month*31+day clock backwards — push the new-year cluster up a
    # synthetic year (372 days) so time keeps increasing
    lo = min(p[0] for p in tpts)
    if max(p[0] for p in tpts) - lo > 186 * 86400:
        YEAR = 372 * 86400
        tpts = [(s + YEAR, x, cy) if s - lo < 186 * 86400 else (s, x, cy)
                for s, x, cy in tpts]
        daytags = [(s + YEAR, mo, d) if s - lo < 186 * 86400 else (s, mo, d)
                   for s, mo, d in daytags]
        tlabels = [(s + YEAR, lab) if s - lo < 186 * 86400 else (s, lab)
                   for s, lab in tlabels]
    # year is absent from the chart — resolve it from the document's tables
    _, start_mon, start_day = min(daytags)
    year = _resolve_year(page.parent, start_mon, start_day)
    meta.date = f"{year:04d}-{start_mon:02d}-{start_day:02d}"

    # A stage can be charted twice with the SAME printed title — a zoomed
    # detail view beside the full treatment, or two genuinely separate
    # treatments — so the suffix rule above has nothing to read and both
    # charts land under one stage key. The only thing on the page that tells
    # them apart is this axis: every page of ONE chart (the main plot and the
    # single-series auxiliaries that follow it) prints exactly the same
    # "Mon-DD HH:MM" label set, and two charts of the same stage never do.
    # Publish the set so the document-level pass in pipeline can separate
    # them; a stage charted once is unaffected.
    meta.axis_window = "|".join(lab for _s, lab in sorted(set(tlabels)))
    tfit = _fit([(v, x) for v, x, _ in tpts])
    if tfit[1] <= 0:
        raise ValueError("bj1: bad time fit")
    time_y = min(cy for _, _, cy in tpts)

    # y-axis tick columns: numeric spans above the time labels, clustered
    # by right-edge x
    nums = [s for s in spans if re.fullmatch(r"-?[\d,]+(\.\d+)?", s["t"])
            and s["cy"] < time_y - 5]
    cols = defaultdict(list)
    for s in nums:
        placed = False
        for key in list(cols):
            if abs(key - s["x1"]) < 8:
                cols[key].append(s)
                placed = True
                break
        if not placed:
            cols[round(s["x1"])].append(s)
    fits = {}          # col_x -> (a, b, y_lo, y_hi)
    for key, ss in cols.items():
        if len(ss) < 3:
            continue
        a, b = _fit([(float(s["t"].replace(",", "")), s["cy"]) for s in ss])
        if abs(b) > 1e-9:
            ys = [s["cy"] for s in ss]
            fits[key] = (a, b, min(ys) - 10, max(ys) + 10)
    if not fits:
        raise ValueError("bj1: no axis tick columns")

    # Tick labels are NOT consistently aligned: on some pages the '0' of an
    # axis sits ~11pt left of its '2000' (right edges 726 vs 743), so the
    # 8pt right-edge clustering above orphans it into a 1-member column that
    # gets dropped. The column then loses its bottom tick, its band starts
    # part-way up the axis, and every sample below that is clipped away —
    # which surfaced as concentration channels sitting on a flat raised
    # baseline (~373 kg/m³) instead of zero through the pad.
    # Re-attach an orphan only when it lands on an existing column's own
    # fitted line, so a genuinely unrelated number can't be absorbed.
    orphans = [s for _k, ss in cols.items() if len(ss) < 3 for s in ss]
    for s in orphans:
        try:
            v = float(s["t"].replace(",", ""))
        except ValueError:
            continue
        for key in list(fits):
            a, b, y_lo, y_hi = fits[key]
            if abs(key - s["x1"]) > 40:
                continue
            axis_span = abs(b) * max(1.0, y_hi - y_lo)
            if abs(a + b * s["cy"] - v) <= max(1e-6, 0.02 * axis_span):
                cols[key].append(s)
                pts = [(float(z["t"].replace(",", "")), z["cy"]) for z in cols[key]]
                a2, b2 = _fit(pts)
                ys = [z["cy"] for z in cols[key]]
                fits[key] = (a2, b2, min(ys) - 10, max(ys) + 10)
                break

    # rotated axis-name spans (taller than wide) -> nearest tick column
    axis_names = {}
    for s in spans:
        if (s["y1"] - s["y0"]) > (s["x1"] - s["x0"]) * 1.5 and \
                re.search(r"[A-Za-z]{3}", s["t"]):
            key = min(fits, key=lambda k: abs(k - s["cx"]))
            axis_names[s["t"]] = key

    # legend: black names with a short colored dash stroke to the left
    drawings = page.get_drawings()
    dashes = []
    for d in drawings:
        c = d.get("color")
        if c is None or d["type"] not in ("s", "fs"):
            continue
        c = tuple(round(x, 2) for x in c)
        if c == (0.0, 0.0, 0.0) or len(d["items"]) > 4:
            continue
        r = d["rect"]
        if r.width < 40 and r.height < 4:
            dashes.append((c, r))
    name_color = {}
    for s in spans:
        if not re.search(r"\([^)]+\)", s["t"]) or (s["y1"] - s["y0"]) > 20:
            continue
        best, bestd = None, 25
        for c, r in dashes:
            dy = abs((r.y0 + r.y1) / 2 - s["cy"])
            dx = s["x0"] - r.x1
            if dy < 6 and 0 < dx < bestd:
                best, bestd = c, dx
        if best:
            name_color.setdefault(s["t"], best)

    # match each legend name to the axis whose name span mentions it
    def name_axis(name):
        base = re.sub(r"\s+", " ", name)
        for ax_text, key in axis_names.items():
            if base in re.sub(r"\s+", " ", ax_text):
                return key
        return None

    # a black series (e.g. Comb FR Ratio) has a black legend dash, so it never
    # matched a colored sample above. Assign it the black stroke color when
    # exactly one un-coloured legend series maps to an axis (more than one black
    # curve would be indistinguishable). This has to run BEFORE the empty-legend
    # guard below: the auxiliary single-series pages BJ emits alongside each
    # stage plot their only curve in black, so bailing out first threw them all
    # away as "no legend colors".
    legend_names = {s["t"] for s in spans
                    if re.search(r"\([^)]+\)", s["t"]) and (s["y1"] - s["y0"]) <= 20}
    black_cands = [n for n in legend_names
                   if n not in name_color and name_axis(n) is not None]
    if len(black_cands) == 1:
        name_color[black_cands[0]] = (0.0, 0.0, 0.0)
    if not name_color:
        raise ValueError("bj1: no legend colors")

    # Clip curves to the plot FRAME (the full-height vertical gridlines), not
    # the time-label span. BJ prints its first/last time labels inset from the
    # frame edges, so each stage's opening ramp (and tail) sits between the
    # frame and the outermost labels — a label-based window clips it. The
    # per-series y-band and the >=5-item stroke length filter below already
    # exclude off-plot strokes, so widening to the frame only recovers real
    # curve points (verified: never drops points, only adds contiguous ramp).
    vgrid = [(d["rect"].x0 + d["rect"].x1) / 2 for d in drawings
             if d.get("color") is not None and d["type"] in ("s", "fs")
             and abs(d["rect"].x1 - d["rect"].x0) < 0.6
             and (d["rect"].y1 - d["rect"].y0) > 100]
    if vgrid:
        x_lo, x_hi = min(vgrid) - 2, max(vgrid) + 2
    else:
        x_lo = min(x for _, x, _ in tpts) - 15
        x_hi = max(x for _, x, _ in tpts) + 15
    series, units = {}, {}
    axes = {}          # label -> (axis_min, axis_max) from the printed ticks
    axis_fit = {}      # label -> (a, b) so the axis can be read AT the frame
    for name, color in name_color.items():
        key = name_axis(name)
        if key is None:
            continue
        a, b, y_lo, y_hi = fits[key]
        pts = []
        for d in drawings:
            c = d.get("color")
            if c is None or d["type"] not in ("s", "fs"):
                continue
            if tuple(round(x, 2) for x in c) != color or len(d["items"]) < 5:
                continue
            for item in d["items"]:
                if item[0] == "l":
                    p1, p2 = item[1], item[2]
                    if color == (0.0, 0.0, 0.0):
                        # black series shares ink with axes/grid: drop long
                        # axis-aligned segments (frame + gridlines)
                        if (abs(p1.x - p2.x) < 0.01 or abs(p1.y - p2.y) < 0.01) and \
                           max(abs(p1.x - p2.x), abs(p1.y - p2.y)) > 5:
                            continue
                    pts.append((p1.x, p1.y))
                    pts.append((p2.x, p2.y))
                elif item[0] == "c":
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
        t = tfit[0] + tfit[1] * arr[:, 0]
        v = a + b * arr[:, 1]
        order = np.argsort(t, kind="stable")
        mn = re.match(r"(.+?)\s*\(([^)]+)\)", name)
        label = mn.group(1).strip() if mn else name
        series[label] = (t[order], v[order])
        units[label] = mn.group(2).strip() if mn else ""
        # the chart's OWN printed axis for this curve, so the Lab plots
        # against the report's range instead of guessing one from the data
        tvals = [float(z["t"].replace(",", "")) for z in cols.get(key, [])]
        if tvals:
            axes[label] = (float(min(tvals)), float(max(tvals)))
            axis_fit[label] = (float(a), float(b))
    if not series:
        raise ValueError("bj1: no curves matched")

    t_lo = min(t.min() for t, _ in series.values())
    t_hi = max(t.max() for t, _ in series.values())
    n = int(t_hi - t_lo)
    if not (60 < n < 100000):
        raise ValueError(f"bj1: implausible duration {n}s")
    meta.duration_min = n / 60.0

    # geometry for the Lab's synced "Compare Original" view. Time runs along
    # x here (no page rotation), and the stacked value axes share one frame,
    # so the horizontal gridlines give its vertical extent.
    hgrid = []
    for d in drawings:
        if d.get("color") is None or d["type"] not in ("s", "fs"):
            continue
        r = d["rect"]
        if abs(r.y1 - r.y0) < 0.6 and (r.x1 - r.x0) > 100:
            hgrid.append((r.y0 + r.y1) / 2)
    # Ghost stretches the page so v0..v1 fills our plot rect, and the Lab
    # draws each curve against its printed tick range — so v0/v1 must be the
    # page coords where the axis READS those ticks. Gridline extremes are not
    # that (there is no gridline at the axis zero), which shifted the whole
    # backdrop. Invert each series' own fit and take the median.
    edges_lo, edges_hi = [], []
    for _n, (fa, fb) in axis_fit.items():
        if abs(fb) < 1e-12:
            continue
        lo_v, hi_v = axes[_n]
        edges_lo.append((lo_v - fa) / fb)
        edges_hi.append((hi_v - fa) / fb)
    if edges_lo and edges_hi:
        edges_lo.sort(); edges_hi.sort()
        p_lo = edges_lo[len(edges_lo) // 2]
        p_hi = edges_hi[len(edges_hi) // 2]
        v0, v1 = min(p_lo, p_hi), max(p_lo, p_hi)
    elif hgrid:
        v0, v1 = min(hgrid), max(hgrid)
    else:
        v0 = min(f[2] for f in fits.values())
        v1 = max(f[3] for f in fits.values())
    meta.geom = {"axis": "x", "ta": float(tfit[0] - t_lo),
                 "tb": float(tfit[1]), "v0": float(v0), "v1": float(v1)}

    day_sec = t_lo % 86400
    meta.start_time = (f"{int(day_sec // 3600):02d}:"
                       f"{int(day_sec % 3600 // 60):02d}:"
                       f"{int(day_sec % 60):02d}")
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {name: _resample(t - t_lo, v, samples)
            for name, (t, v) in series.items()}
    # printed axis range per curve, so the Lab's y axis matches the report;
    # axes_frame is the same axis read AT the geom frame edges — ghost
    # stretches the page between those, so any gap is visible misalignment
    meta.axes = axes
    meta.axes_frame = {n: (af[0] + af[1] * v0, af[0] + af[1] * v1)
                       for n, af in axis_fit.items()}
    return meta, samples, data, units
