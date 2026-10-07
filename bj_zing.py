"""BJ charts drawn by ZingChart (Ovintiv's 2026 filings, #796 / #797).

BJ's 2026 Sunrise and Tower Lake books stopped printing the BJ-1 chart bj1
reads ("100-12-27-079-16W6 - Well D - Stage 01" over slanted "Mar-24 21:34"
labels and a legend) and print a ZingChart render instead:

    OVV HZ SUNRISE I3-19-78-16 | 29 | Stage 29 | API/UWI: 103/07-34-078-17-W6/00 | Ovintiv 03-19 Pad

with the clock printed as a date over a time, "24 Mar 26" / "21:34:44",
centred on its gridline, and no legend at all: each value axis prints its
ticks and its rotated title in its series' own colour, and a series with no
tick column of its own ("Density at Perfs", yellow) sets its title beside the
axis it shares. Everything but the curves is text, and the curves are vector
paths, so nothing here is traced: the stroke's vertices go through the two
fits and come out as values.

Same return as bj1.extract_page, so the pipeline treats the two alike.
"""
import datetime
import re

import numpy as np

from frac_core import PageMeta, _resample

_DATE = re.compile(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{2})")
_CLOCK = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")
_STAGE = re.compile(r"\|\s*Stage\s+(\d+(?:\.\d+)?)\s*([A-Za-z][\w .#-]*?)?\s*(?:\||$)")
_UWI = re.compile(r"API/UWI:\s*(\d{3})/(\d{2})-(\d{2})-(\d{2,3})-(\d{2})-?W(\d)(?:/(\d{2}))?")
_NUM = re.compile(r"-?[\d,]+(?:\.\d+)?")
LABEL_TOL_S = 120.0
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
     "Nov", "Dec"), 1)}


def detect(page):
    t = page.get_text()
    return ("ZingChart" in t and _STAGE.search(t) is not None
            and _DATE.search(t) is not None and _CLOCK.search(t) is not None)


def _spans(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                c = s["color"]
                out.append({"t": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                            "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                            "rgb": ((c >> 16 & 255) / 255.0, (c >> 8 & 255) / 255.0,
                                    (c & 255) / 255.0),
                            "c": c, "rot": abs(l["dir"][1]) > 0.9})
    return out


def _fit(pairs):
    """[(value, coord)] -> (a, b) with value = a + b * coord."""
    v = np.array([p[0] for p in pairs], float)
    x = np.array([p[1] for p in pairs], float)
    b, a = np.polyfit(x, v, 1)
    return float(a), float(b)


def _near(c1, c2, tol=0.04):
    return max(abs(a - b) for a, b in zip(c1, c2)) <= tol


def extract_page(page, sample_sec=1.0):
    """-> (meta, samples, {name: values}, {name: unit})"""
    spans = _spans(page)
    meta = PageMeta()
    title = next((s["t"] for s in spans if "| Stage" in s["t"] or "|Stage" in s["t"]), "")
    m = _STAGE.search(title)
    if m is None:
        raise ValueError("bj-zing: no stage in the title")
    meta.stage = m.group(1) + (f" {m.group(2).strip()}" if m.group(2) and m.group(2).strip() else "")
    u = _UWI.search(title)
    if u:
        meta.uwi = (f"{u.group(1)}/{u.group(2)}-{u.group(3)}-{int(u.group(4)):03d}-"
                    f"{u.group(5)}W{u.group(6)}/{u.group(7) or '00'}")
    meta.title = title[:60]

    # the clock: each "HH:MM:SS" with the "DD Mon YY" printed just above it
    dates = [s for s in spans if not s["rot"] and _DATE.fullmatch(s["t"])]
    tpts, labels = [], []
    for s in spans:
        mc = _CLOCK.fullmatch(s["t"])
        if not mc or s["rot"]:
            continue
        above = [d for d in dates if 0 < s["cy"] - d["cy"] < 16 and abs(d["cx"] - s["cx"]) < 12]
        if not above:
            continue
        d = min(above, key=lambda d: s["cy"] - d["cy"])
        md = _DATE.fullmatch(d["t"])
        mon = _MONTHS.get(md.group(2))
        if mon is None:
            continue
        try:
            day = datetime.date(2000 + int(md.group(3)), mon, int(md.group(1)))
        except ValueError:
            continue
        secs = ((day - datetime.date(2000, 1, 1)).days * 86400
                + int(mc.group(1)) * 3600 + int(mc.group(2)) * 60 + int(mc.group(3)))
        tpts.append((secs, s["cx"]))
        labels.append(f"{d['t']} {s['t']}")
    if len(tpts) < 2:
        raise ValueError("bj-zing: time labels not found")
    # One bad label tilts a two-point line by weeks: 00060 p221 prints
    # "7 Mar 26" under one of five clocks the rest date "27 Mar 26", and the
    # fit came out 643,836 s long. Labels on evenly spaced gridlines agree on
    # one line to the second, so with three or more the worst is dropped
    # while it sits more than LABEL_TOL_S off the line through the others.
    while len(tpts) >= 3:
        a, b = _fit(tpts)
        res = [abs(v - (a + b * x)) for v, x in tpts]
        worst = int(np.argmax(res))
        if res[worst] <= LABEL_TOL_S:
            break
        del tpts[worst], labels[worst]
    tfit = _fit(tpts)
    if tfit[1] <= 0:
        raise ValueError("bj-zing: bad time fit")
    meta.axis_window = "|".join(sorted(set(labels)))
    time_y = min(s["y0"] for s in spans if _CLOCK.fullmatch(s["t"]))

    # value axes: the tick numbers, one column per colour
    cols = {}
    for s in spans:
        if s["rot"] or not _NUM.fullmatch(s["t"]) or s["cy"] >= time_y - 4:
            continue
        cols.setdefault(s["c"], []).append(s)
    fits = {}
    for c, ss in cols.items():
        if len(ss) < 3:
            continue
        a, b = _fit([(float(z["t"].replace(",", "")), z["cy"]) for z in ss])
        if abs(b) < 1e-12:
            continue
        vals = [float(z["t"].replace(",", "")) for z in ss]
        fits[c] = {"a": a, "b": b, "cx": float(np.mean([z["cx"] for z in ss])),
                   "rgb": ss[0]["rgb"], "lo": min(vals), "hi": max(vals)}
    if not fits:
        raise ValueError("bj-zing: no axis tick columns")

    # series: each rotated, coloured title names one, on its own colour's
    # axis or — with no column of its own — the column it is printed beside
    names = []
    for s in spans:
        if not s["rot"] or not re.search(r"[A-Za-z]{3}", s["t"]):
            continue
        key = s["c"] if s["c"] in fits else min(fits, key=lambda k: abs(fits[k]["cx"] - s["cx"]))
        names.append((s["t"], s["rgb"], key))
    if not names:
        raise ValueError("bj-zing: no axis titles")

    drawings = page.get_drawings()
    frame = None
    for d in drawings:
        r = d["rect"]
        if d.get("color") is not None and r.width > 200 and r.height > 200:
            if frame is None or r.width * r.height > frame.width * frame.height:
                frame = r
    series, units, axes, axis_fit = {}, {}, {}, {}
    for name, rgb, key in names:
        ax = fits[key]
        pts = []
        for d in drawings:
            c = d.get("color")
            if c is None or len(d["items"]) < 5 or not _near(c, rgb):
                continue
            for it in d["items"]:
                if it[0] == "l":
                    pts.append((it[1].x, it[1].y))
                    pts.append((it[2].x, it[2].y))
                elif it[0] == "c":
                    pts.append((it[1].x, it[1].y))
                    pts.append((it[4].x, it[4].y))
        if len(pts) < 20:
            continue
        arr = np.array(pts)
        if frame is not None:
            keep = ((arr[:, 0] >= frame.x0 - 1) & (arr[:, 0] <= frame.x1 + 1)
                    & (arr[:, 1] >= frame.y0 - 1) & (arr[:, 1] <= frame.y1 + 1))
            arr = arr[keep]
        if len(arr) < 20:
            continue
        t = tfit[0] + tfit[1] * arr[:, 0]
        v = ax["a"] + ax["b"] * arr[:, 1]
        order = np.argsort(t, kind="stable")
        mn = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", name)
        label = mn.group(1).strip() if mn else name
        series[label] = (t[order], v[order])
        units[label] = mn.group(2).strip() if mn else ""
        axes[label] = (ax["lo"], ax["hi"])
        axis_fit[label] = (ax["a"], ax["b"])
    if not series:
        raise ValueError("bj-zing: no curves matched")

    t_lo = min(t.min() for t, _ in series.values())
    t_hi = max(t.max() for t, _ in series.values())
    n = int(t_hi - t_lo)
    if not (60 < n < 200000):
        raise ValueError(f"bj-zing: implausible duration {n}s")
    meta.duration_min = n / 60.0
    day0 = datetime.date(2000, 1, 1) + datetime.timedelta(days=int(t_lo // 86400))
    sod = t_lo % 86400
    meta.date = day0.isoformat()
    meta.start_time = f"{int(sod // 3600):02d}:{int(sod % 3600 // 60):02d}:{int(sod % 60):02d}"

    if frame is not None:
        v0, v1 = float(frame.y0), float(frame.y1)
    else:
        v0 = min(z["cy"] for ss in cols.values() for z in ss)
        v1 = max(z["cy"] for ss in cols.values() for z in ss)
    meta.geom = {"axis": "x", "ta": float(tfit[0] - t_lo), "tb": float(tfit[1]),
                 "v0": v0, "v1": v1}
    meta.axes = axes
    meta.axes_frame = {k: (af[0] + af[1] * v0, af[0] + af[1] * v1)
                       for k, af in axis_fit.items()}
    samples = np.arange(int(n / sample_sec)) * sample_sec
    data = {k: _resample(t - t_lo, v, samples) for k, (t, v) in series.items()}
    return meta, samples, data, units
