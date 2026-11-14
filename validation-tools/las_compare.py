"""Compare two LAS files of one log: what the printout PDF reads as
(mudlog_pdf, "<name>.from-printout.las") against what the log file holds
(Save LAS, "<name>.las"), curve by curve, and say why they differ.

    from las_compare import read_las, compare
    report = compare(read_las(source_text), read_las(pdf_text), scales)

Curves are paired by name (then by what log_vocab says they are). Each
source reading is looked up in the PDF's LAS at the same depth (its nearest
row), and every difference is measured as a share of the curve's printed
scale width: how far apart the two would be drawn on the printout. The
depth shift that best lines the two up is found (LogViewer draws a curve
about half a recorded step shallower than its depth). On a logarithmic
scale (from above nothing over a thousandfold, a resistivity's over a
hundredfold) the readings' logarithms are compared, as they are drawn.

A reading the two disagree on by more than AGREE of the width is put down
to the first of these that fits:

  past_twice   the source reading is past twice its printed scale: the
               printout pins it to the track's edge and cannot show it
  wrap         the PDF reading is one scale width off (a wrap read the
               wrong way)
  missing      the PDF has no reading there
  steep        the source curve moves more than STEEP of the width within
               EDGE_M of the depth: a steep line read a little high or low
  other        none of these

Standard library only (log_vocab for curve names).
"""
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

AGREE = 0.02        # a reading within 2 % of the scale width agrees
GOOD = 0.01         # within 1 %: as close as a drawn line can be read
STEEP = 0.10        # the curve moves 10 % of the width ...
EDGE_M = 0.25       # ... within this many metres: a steep stretch
LAGS = [round(0.05 * k, 2) for k in range(-10, 11)]    # depth shifts tried, m

CAUSES = ("past_twice", "wrap", "missing", "steep", "other")


def read_las(text):
    """a LAS 2.0 file's text -> {well: {MNEM: value}, curves: [(mnem, unit,
    description)], depth: [..], data: {mnem: [..]}, step, null}"""
    sec, well, curves, rows = None, {}, [], []
    null = -999.25
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("~"):
            sec = s[1:2].upper()
            continue
        if sec == "A":
            rows.append(s.split())
            continue
        m = re.match(r"([^.\s]+)\s*\.(\S*)\s+(.*?)\s*:\s*(.*)$", s)
        if not m:
            continue
        mn, unit, val, desc = m.groups()
        if sec == "W":
            well[mn.upper()] = val.strip()
            if mn.upper() == "NULL":
                try:
                    null = float(val)
                except ValueError:
                    pass
        elif sec == "C":
            curves.append((mn, unit, desc.strip()))
    depth, data = [], {c[0]: [] for c in curves[1:]}
    for r in rows:
        if len(r) < len(curves):
            continue
        depth.append(float(r[0]))
        for (mn, _u, _d), v in zip(curves[1:], r[1:]):
            x = float(v)
            data[mn].append(None if abs(x - null) < 1e-6 or not math.isfinite(x) else x)
    step = None
    try:
        step = float(well.get("STEP", "").split()[0])
    except (ValueError, IndexError):
        pass
    if not step and len(depth) > 1:
        step = depth[1] - depth[0]
    return {"well": well, "curves": curves[1:], "depth": depth, "data": data, "step": step, "null": null}


def _name(desc, mnem):
    """a curve's own name from its LAS description ("Gamma (track ...)")"""
    d = re.split(r"\s*\(", desc or "", 1)[0].strip()
    return d or mnem


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _kind(name):
    try:
        import log_vocab as V
        return V.curve(name)["key"]
    except Exception:  # noqa: BLE001 - names alone still pair most curves
        return None


def pair_curves(src, pdf):
    """[(source mnem, pdf mnem or None)], [pdf mnems left over]"""
    s_names = [(mn, _name(d, mn)) for mn, _u, d in src["curves"]]
    p_names = [(mn, _name(d, mn)) for mn, _u, d in pdf["curves"]]
    left = dict(p_names)
    hits = {}
    for mn, nm in s_names:                      # the same name first, for every curve
        hit = next((p for p, pn in left.items() if _norm(pn) == _norm(nm)), None)
        if hit is not None:
            hits[mn] = left.pop(hit) and hit
    for mn, nm in s_names:                      # then the one curve left of the same kind
        if mn in hits:
            continue
        k = _kind(nm)
        same = [p for p, pn in left.items() if k and _kind(pn) == k]
        if len(same) == 1:
            hits[mn] = same[0]
            left.pop(same[0])
    return [(mn, hits.get(mn)) for mn, _nm in s_names], list(left)


def _at(las, mn, d):
    """the PDF LAS's reading at depth d (its nearest row), None off it"""
    dep, st = las["depth"], las["step"]
    if not dep or not st:
        return None
    i = int(round((d - dep[0]) / st))
    if 0 <= i < len(dep) and abs(dep[i] - d) <= st / 2 + 1e-6:
        return las["data"][mn][i]
    return None


def _scale_at(scales, d):
    if not scales:
        return None
    cur = scales[0]
    for s in scales:
        if s[0] is None or s[0] <= d + 1e-9:       # a section with no depth holds from the top
            cur = s
    return cur[1], cur[2]


def _log_kind(src, mn):
    """a resistivity curve (its log_vocab kind, or its name)"""
    nm = _name(dict((m, d) for m, _u, d in src["curves"]).get(mn, ""), mn)
    return "resistivity" in str(_kind(nm) or "") or "resist" in nm.lower()


def _is_log(lo, hi, resist):
    """a scale LogViewer draws logarithmic: from above nothing over a
    thousandfold (a resistivity's over a hundredfold)"""
    return lo > 0 and hi / lo >= (100 if resist else 1000)


def compare_curve(src, mn, pdf, pmn, scales):
    """one curve: {n, coverage, lag_m, mae, p95, max, bias, within_1, within_2, causes{}}
    (errors as shares of the printed scale width)"""
    dep, vals = src["depth"], src["data"][mn]
    pts = [(d, v) for d, v in zip(dep, vals) if v is not None]
    if not pts:
        return None
    if not scales:                               # no printed scale known: the curve's own 5-95 % range
        vs = sorted(v for _d, v in pts)
        lo, hi = vs[int(0.05 * (len(vs) - 1))], vs[int(0.95 * (len(vs) - 1))]
        scales = [(dep[0], lo, hi if hi > lo else lo + 1)]

    logs = _log_kind(src, mn)

    def errors(lag):
        out = []
        for d, v in pts:
            left, right = _scale_at(scales, d)
            lo, hi = min(left, right), max(left, right)
            p = _at(pdf, pmn, d + lag) if pmn else None
            if _is_log(lo, hi, logs):
                # a logarithmic scale: places along it are the readings'
                # logarithms, so the miss is measured between those
                at = lambda x: math.log10(max(x, lo * 1e-3) / lo)
                w = math.log10(hi / lo)
                vv, pp, lo_, hi_ = at(v), None if p is None else at(p), 0.0, w
            else:
                w = (hi - lo) or 1.0
                vv, pp, lo_, hi_ = v, p, lo, hi
            out.append((d, vv, pp, None if pp is None else (pp - vv) / w, w, lo_, hi_))
        return out

    best = None
    for lag in LAGS if pmn else [0.0]:
        e = errors(lag)
        es = sorted(abs(x[3]) for x in e if x[3] is not None)
        med = es[len(es) // 2] if es else math.inf
        if best is None or med < best[0] - 1e-9 or (abs(med - best[0]) < 1e-9 and abs(lag) < abs(best[1])):
            best = (med, lag, e)
    _med, lag, e = best
    got = [x for x in e if x[3] is not None]
    es = sorted(abs(x[3]) for x in got)
    causes = dict.fromkeys(CAUSES, 0)
    for i, (d, v, p, err, w, lo, hi) in enumerate(e):
        if err is not None and abs(err) <= AGREE:
            continue
        if v > hi + (hi - lo) or v < lo - (hi - lo):
            causes["past_twice"] += 1
        elif err is not None and abs(abs(err) - 1.0) < 0.05:
            causes["wrap"] += 1
        elif p is None:
            causes["missing"] += 1
        else:
            near = [x[1] for x in e[max(0, i - 50):i + 51] if abs(x[0] - d) <= EDGE_M]
            if near and (max(near) - min(near)) / w > STEEP:
                causes["steep"] += 1
            else:
                causes["other"] += 1
    n = len(e)
    return {"n": n, "coverage": len(got) / n, "lag_m": lag,
            "mae": sum(es) / len(es) if es else None,
            "median": es[len(es) // 2] if es else None,
            "p95": es[int(0.95 * (len(es) - 1))] if es else None,
            "max": es[-1] if es else None,
            "bias": sum(x[3] for x in got) / len(got) if got else None,
            "within_1": sum(1 for x in es if x <= GOOD) / n,
            "within_2": sum(1 for x in es if x <= AGREE) / n,
            "causes": causes}


HEADER = (("WELL", "well name"), ("LIC", "licence"), ("UWI", "UWI"), ("LOC", "location"), ("COMP", "operator"))


def compare(src, pdf, scales_by_name=None):
    """{curves: [{source, pdf, name, ...compare_curve}], extra: [pdf curves
    not in the source], header: {field: same|different|missing}, depth:
    {source: (strt, stop, step), pdf: (...)}}"""
    pairs, extra = pair_curves(src, pdf)
    out = []
    for mn, pmn in pairs:
        nm = _name(dict((m, d) for m, _u, d in src["curves"])[mn], mn)
        sc = (scales_by_name or {}).get(_norm(nm))
        r = compare_curve(src, mn, pdf, pmn, sc)
        if r is None:
            continue
        r.update(source=mn, pdf=pmn, name=nm, kind=_kind(nm))
        out.append(r)
    head = {}
    for k, label in HEADER:
        a, b = _norm(src["well"].get(k)), _norm(pdf["well"].get(k))
        head[label] = "same" if a == b else ("missing" if not b else ("blank in source" if not a else "different"))
    rng = lambda L: (L["depth"][0], L["depth"][-1], L["step"]) if L["depth"] else None
    return {"curves": out, "extra": [_name(d, m) for m, _u, d in pdf["curves"] if m in extra],
            "header": head, "depth": {"source": rng(src), "pdf": rng(pdf)}}
