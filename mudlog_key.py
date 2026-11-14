"""The answer key for reading mudlogs from their PDF printouts.

A WellSight log and the PDF LogViewer printed from it hold the same log
twice: the file as data, the printout as drawing. The file says what the
printout shows, so every log with its printout is an answer sheet for a
reader that has only the PDF. build() writes the answer down from the file
(and finds where it lies on the printout); score() marks a reader's output
against it.

The key, schema "frac2csv/mudlog-key/1". A PDF reader writes the same fields
(those marked "key" it cannot know and leaves out):

  log        {file, sha1, app, version}                                  key
  printout   {file, sha1, pages, log_pages, left_out, depth_on_page,     key
              pt_per_m, strip_width_pt, check, ok}
             log_pages: [{page, from, to, depth: {coord, a, b},
                          across: {coord, origin, sign}}]: on that page
             depth = a * c + b, c its x or y; a point's x on the stitched
             strip = sign * (its other coordinate - origin)
  depth      {unit "m", axis "MD" | "TVD", top, bottom}
  header     {field: text}: fields as log_vocab.txt [header] names them
  tracks     [{title, keys, x0, x1, snapped}]: across the stitched strip
             (wellsight_print.stitch: depth down, top at y = 0), in points
  curves     [{name, kind, units, unit, track, top, step, values, scale,
              wraps}]: the reading at top + i * step, None where there is
             none; kind and unit are log_vocab's keys; scale the printed
             scale's sections [[from depth, left, right]] and wraps where
             the printout wraps the curve (wellsight_scales: a reader must
             unwrap those). LogViewer draws a reading half a step shallower
             than its depth; score() allows for that.
  rocks      [{top, base, rock, code}]: rock is a wellsight_symbols term
  percent    {rocks, top, step, values} or None: the % lithology column
  symbols    [{depth, group, term, code}]
  intervals  [{top, base, group, term, code}]: cores, tests, slide / rotate
  text       [{depth, column, text}]: the notes written on the log

score(key, candidate) marks each part 0..1 and says why; a part the key has
nothing for is None. What counts as right:

  header     the field's text, case, spaces and punctuation aside
  curves     each key curve against the reader's curve of the same kind:
             the share of its readings the reader has within 1 % of the
             printed scale's width (about 1.5 pt across the track; 2 % of
             the curve's own range where the scale is not known), at the
             depth shift that gets most right; a reading past twice its
             printed scale is left out (the printout does not show it)
  rocks      the share of the logged depth given the right rock
  symbols    found within 0.5 m with the right term (F1)
  intervals  the share of each interval's length given the right term
  text       the words of each note found within its depth window
  tracks     both edges within 2 pt

Standard library, plus PyMuPDF to build.
"""
import collections
import difflib
import gzip
import hashlib
import json
import math
import os
import re

import log_vocab as V
import wellsight_app as wa          # sets up the vendored decoder
import wellsight_layout as wl
import wellsight_scales as wscale
import wellsight_symbols as wsym

SCHEMA = "frac2csv/mudlog-key/1"
ws, cv = wa.ws, wa.cv


class Skip(Exception):
    """a log that cannot be an answer sheet: (status, reason)"""


def _r(v, nd=4):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), nd)


# ---------------------------------------------------------------- build

def _curves(raw, log):
    """the key's curves for a decoded log: readings, kind, unit, printed
    scale and wraps"""
    curves = []
    try:
        scales = wscale.scales(raw, log.get("curves") or [])
    except Exception:  # noqa: BLE001 - a key without scales still marks the readings
        scales = {}
    for i, c in enumerate(log.get("curves") or []):
        if not c.get("nonnull"):
            continue
        vc = V.curve(c.get("name") or "")
        kind = vc["key"] or V.curve(c.get("source_mnemonic") or "")["key"]
        secs = scales.get(i)
        curves.append({"name": c.get("name") or c.get("source_mnemonic") or "", "kind": kind,
                       "units": c.get("units") or "", "unit": V.unit(c.get("units"))["key"],
                       "track": c.get("track") or "", "top": _r(c["first_depth"], 3),
                       "step": _r(c["step"], 4), "values": [_r(v) for v in c["values"]],
                       "scale": [[d, l, r] for d, l, r in secs] if secs else None,
                       "wraps": wscale.wraps(c, secs) if secs and c.get("first_depth") is not None else []})
    return curves


def refresh_curves(key, log_path):
    """a key's curves written again from its log (a key written before the
    printed scales were read gets them); the printout is not stitched again"""
    with open(log_path, "rb") as f:
        raw = f.read()
    key["curves"] = _curves(raw, ws.read_log(raw))
    return key


def build(log_path, pdf_path, rel_log=None, rel_pdf=None):
    """-> key. Raises Skip when the log cannot be read or has no curves and
    no rocks to check a reader against."""
    import wellsight_print as wp
    with open(log_path, "rb") as f:
        raw = f.read()
    name = os.path.basename(log_path)
    try:
        log = ws.read_log(raw)
    except ws.NotReadable as e:
        raise Skip("not_readable", str(e))
    if log.get("top") is None or log.get("bottom") is None:
        raise Skip("no_depth", "the log's depth range was not found")
    top, bottom = float(log["top"]), float(log["bottom"])
    axis, _basis = ws.decide_axis(log.get("axis_votes") or (0, 0), name)

    curves = _curves(raw, log)

    lith = log.get("lithology") or {}
    _extra, ivs = cv.lith_curves(log, lith)
    rocks = wsym.rocks_from([{"top": iv["top_m"], "base": iv["base_m"], "code": iv["code"],
                              "rock": iv.get("name")} for iv in ivs])
    percent = None
    pc = lith.get("percent")
    if pc:
        lsyms = lith.get("_lith_symbols") or {}
        percent = {"rocks": [wsym.rock_term(lsyms.get(r, (str(r), ""))[0])[0] for r in pc["rocks"]],
                   "top": top, "step": pc["step_m"], "values": pc["values"]}
    symbols = [{"depth": _r(s["depth"], 3), "group": s["group"], "term": s["term"], "code": s["raw"]}
               for s in wsym.symbols_from(log.get("accessories") or [])]
    intervals = [{"top": _r(i["top"], 3), "base": _r(i["base"], 3), "group": i["group"], "term": i["term"],
                  "code": i["raw"]} for i in wsym.columns_from(lith.get("symbol_columns") or [])]
    text = [{"depth": _r(a["depth"], 3), "column": a.get("column") or "", "text": a.get("text") or ""}
            for a in log.get("annotations") or [] if (a.get("text") or "").strip()]

    key = {"schema": SCHEMA,
           "log": {"file": rel_log or name, "sha1": hashlib.sha1(raw).hexdigest(),
                   "app": log.get("app"), "version": log.get("version")},
           "printout": None,
           "depth": {"unit": "m", "axis": axis, "top": top, "bottom": bottom},
           "header": {k: v for k, v in (log.get("header") or {}).items() if v},
           "header_source": log.get("header_source"),
           "tracks": [], "curves": curves,
           "rocks": [{"top": r["top"], "base": r["base"], "rock": r["rock"], "code": r["raw"]} for r in rocks],
           "percent": percent, "symbols": symbols, "intervals": intervals, "text": text}

    with open(pdf_path, "rb") as f:
        pdf = f.read()
    po = {"file": rel_pdf or os.path.basename(pdf_path), "sha1": hashlib.sha1(pdf).hexdigest(), "ok": False}
    key["printout"] = po
    try:
        _strip, info = wp.stitch(pdf, top, bottom)
    except wp.NoDepthScale as e:
        po["error"] = str(e)
        return key
    po.update({"pages": info["pages"], "left_out": info["left_out"],
               "depth_on_page": info["depth_axis_on_page"], "pt_per_m": info["pt_per_m"],
               "strip_width_pt": info["width_pt"], "gaps": info["gaps"],
               "worst_seam_m": info["worst_seam_m"], "check": info["check"],
               "log_pages": [{k: p[k] for k in ("page", "from", "to", "depth", "across", "inferred")}
                             for p in info["placed"]]})
    try:
        key["tracks"] = [{k: t[k] for k in ("title", "keys", "x0", "x1", "snapped", "clipped")}
                         for t in wl.place(wl.read_tracks(raw), info.get("lines_pt") or [],
                                           info.get("curves_pt"), info["width_pt"],
                                           wl.curve_track_title(log.get("curves")))]
    except Exception as e:  # noqa: BLE001 - a layout the reader cannot place is noted, not fatal
        po["tracks_error"] = "%s: %s" % (type(e).__name__, e)
    ck = info["check"] or {}
    po["ok"] = bool(ck.get("labels")) and (ck.get("within_0.1m") or 0) >= 0.9 and not info["gaps"]
    return key


def save(key, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".part"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(key, f, separators=(",", ":"))
    os.replace(tmp, path)


def load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- score

def _norm_text(s):
    """letters, digits and points only: "600.5 m" and "600.5m" are the same"""
    return re.sub(r"[^a-z0-9.]+", "", str(s or "").lower())


def score_header(key, cand):
    kh = {k: v for k, v in (key.get("header") or {}).items() if str(v).strip()}
    if not kh:
        return None
    ch = cand.get("header") or {}
    fields, total = {}, 0.0
    for k, v in kh.items():
        # a unit after a number is the same reading: "564.4" and "564.4 m"
        a, b = (re.sub(r"(?<=\d)(m|ft|hrs)$", "", _norm_text(x)) for x in (v, ch.get(k)))
        if a == b:
            s, why = 1.0, "same"
        elif b and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
            s, why = 0.5, "close"
        else:
            s, why = 0.0, "missing" if not b else "different"
        fields[k] = why
        total += s
    return {"score": total / len(kh), "fields": fields}


def _grid_value(c, d):
    """a curve's reading at depth d, straight between its two neighbours;
    None outside it or across a gap"""
    if c["step"] in (None, 0) or c.get("top") is None:
        return None
    x = (d - c["top"]) / c["step"]
    i = int(math.floor(x))
    vals = c["values"]
    if i < 0 or i >= len(vals):
        return None
    f = x - i
    v0 = vals[i]
    if f < 1e-9:
        return v0
    if i + 1 >= len(vals):
        return None
    v1 = vals[i + 1]
    if v0 is None or v1 is None:
        return None
    return v0 + (v1 - v0) * f


def _resample(c, top, step, n):
    """a curve's readings at top + i * step, i < n (None where it has none)"""
    return [_grid_value(c, top + i * step) for i in range(n)]


def _pct(sorted_vals, q):
    return sorted_vals[min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))]


def _readable(k, d, v):
    """can a printout show this reading? Not one past twice its printed
    scale: LogViewer wraps once and then holds the line at the edge."""
    if not k.get("scale"):
        return True
    left, right = wscale.scale_at([tuple(s) for s in k["scale"]], d)
    p = wscale.printed(v, left, right)
    return p is None or abs(p[1]) < 2


CURVE_TOL = 0.01        # a reading is right within 1 % of its printed scale's width
CURVE_TOL_RANGE = 0.02  # ... or, with no printed scale, 2 % of the curve's 5-95 % range


def _compare_curve(k, c):
    """the share of the key curve's readings the reader has right (within
    CURVE_TOL of the printed scale's width at that depth: about 1.5 pt on a
    printout, what a drawn line can be read to), at the depth shift that
    gets most right"""
    pts = [(k["top"] + i * k["step"], v) for i, v in enumerate(k["values"])
           if v is not None and _readable(k, k["top"] + i * k["step"], v)]
    if not pts:
        return None
    secs = [tuple(s) for s in k.get("scale") or []]
    if secs:
        tols = []
        for d, _v in pts:
            left, right = wscale.scale_at(secs, d)
            tols.append(CURVE_TOL * abs(right - left) or 1e-9)
    else:
        vs = sorted(v for _, v in pts)
        rng = _pct(vs, 0.95) - _pct(vs, 0.05) or (vs[-1] - vs[0]) or 1.0
        tols = [CURVE_TOL_RANGE * rng] * len(pts)
    best = None
    for s in (-1.0, -0.5, 0.0, 0.5, 1.0):
        shift = s * k["step"]
        got = right = 0
        err = 0.0
        for (d, v), t in zip(pts, tols):
            b = _grid_value(c, d + shift)
            if b is None:
                continue
            got += 1
            e = abs(v - b) / t
            err += e
            right += e <= 1.0
        r = (right / len(pts), got / len(pts), err / got if got else None, shift)
        if best is None or r[0] > best[0]:
            best = r
    sc, cov, err, shift = best
    return {"coverage": round(cov, 4), "error": None if err is None else round(err * (CURVE_TOL if secs else CURVE_TOL_RANGE), 5),
            "shift_m": shift, "score": round(sc, 4)}


def score_curves(key, cand):
    kc = [c for c in key.get("curves") or [] if sum(v is not None for v in c["values"]) >= 10]
    if not kc:
        return None
    pool = list(cand.get("curves") or [])
    used, rows = set(), []
    for k in kc:
        same = [i for i, c in enumerate(pool) if i not in used and
                ((k["kind"] and c.get("kind") == k["kind"]) or
                 (not k["kind"] and _norm_text(c.get("name")) == _norm_text(k["name"])))]
        best = None
        for i in same:
            r = _compare_curve(k, pool[i])
            if r and (best is None or r["score"] > best[1]["score"]):
                best = (i, r)
        if best is None:
            rows.append({"name": k["name"], "kind": k["kind"], "score": 0.0, "why": "not found"})
            continue
        used.add(best[0])
        rows.append({"name": k["name"], "kind": k["kind"], **best[1]})
    extra = [pool[i].get("name") for i in range(len(pool)) if i not in used]
    return {"score": sum(r["score"] for r in rows) / len(rows), "curves": rows, "extra": extra}


def _rock_of(r):
    t = r.get("rock") or r.get("code") or ""
    return t if ("rock", t) in wsym._NAMES else wsym.rock_term(t)[0]


def _at(depth_ivs, d):
    for top, base, v in depth_ivs:
        if top <= d < base:
            return v
    return None


def score_rocks(key, cand, step=0.1):
    kr = key.get("rocks") or []
    if not kr:
        return None
    k_ivs = [(r["top"], r["base"], _rock_of(r)) for r in kr]
    c_ivs = sorted((r["top"], r["base"], _rock_of(r)) for r in cand.get("rocks") or [])
    n = right = 0
    for top, base, rock in k_ivs:
        d = top + step / 2
        while d < base:
            n += 1
            right += _at(c_ivs, d) == rock
            d += step
    return {"score": right / n if n else None, "samples": n}


def score_symbols(key, cand, tol=0.5):
    ks = key.get("symbols") or []
    if not ks:
        return None
    import bisect
    pools = collections.defaultdict(list)          # (group, term) -> depths, nearest taken first
    n_cand = 0
    for s in cand.get("symbols") or []:
        term = s.get("term") or wsym.normalise(s.get("group"), s.get("code"))[0]
        pools[(s.get("group"), term)].append(s["depth"])
        n_cand += 1
    for v in pools.values():
        v.sort()
    hit = 0
    by_group = collections.Counter()
    found_group = collections.Counter()
    for s in sorted(ks, key=lambda s: s["depth"]):
        by_group[s["group"]] += 1
        pool = pools.get((s["group"], s["term"]))
        if not pool:
            continue
        i = bisect.bisect_left(pool, s["depth"])
        near = [j for j in (i - 1, i) if 0 <= j < len(pool) and abs(pool[j] - s["depth"]) <= tol]
        if near:
            pool.pop(min(near, key=lambda j: abs(pool[j] - s["depth"])))
            hit += 1
            found_group[s["group"]] += 1
    rec = hit / len(ks)
    prec = hit / n_cand if n_cand else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"score": f1, "recall": round(rec, 4), "precision": round(prec, 4),
            "by_group": {g: round(found_group[g] / n, 4) for g, n in by_group.items()}}


def score_intervals(key, cand, step=0.1):
    ki = key.get("intervals") or []
    if not ki:
        return None
    ci = collections.defaultdict(list)
    for i in cand.get("intervals") or []:
        ci[i.get("group")].append((i["top"], i["base"], i.get("term")))
    n = right = 0
    for i in ki:
        d = i["top"] + step / 2
        while d < i["base"]:
            n += 1
            right += _at(ci[i["group"]], d) == i["term"]
            d += step
    return {"score": right / n if n else None, "samples": n}


_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _words(s):
    return _WORD.findall(str(s or "").lower())


def score_text(key, cand, line_m=0.6, chars_per_line=40):
    kt = [t for t in key.get("text") or [] if _words(t["text"])]
    if not kt:
        return None
    ct = sorted((t["depth"], _words(t["text"])) for t in cand.get("text") or [])
    depths = [d for d, _ in ct]
    import bisect
    want = got = 0
    for t in kt:
        lines = sum(max(1, math.ceil(len(x) / chars_per_line)) for x in t["text"].split("\n"))
        lo, hi = t["depth"] - 1.0, t["depth"] + 1.0 + lines * line_m
        near = collections.Counter()
        for j in range(bisect.bisect_left(depths, lo), bisect.bisect_right(depths, hi)):
            near.update(ct[j][1])
        w = collections.Counter(_words(t["text"]))
        want += sum(w.values())
        got += sum(min(n, near[x]) for x, n in w.items())
    allk = collections.Counter(x for t in kt for x in _words(t["text"]))
    allc = collections.Counter(x for _, ws_ in ct for x in ws_)
    prec = sum(min(n, allk[x]) for x, n in allc.items()) / sum(allc.values()) if allc else 0.0
    return {"score": got / want, "words": want, "precision": round(prec, 4)}


def score_tracks(key, cand, tol=2.0):
    kt = [t for t in key.get("tracks") or [] if t.get("snapped")]
    if not kt:
        return None
    ct = cand.get("tracks") or []
    right, rows = 0, []
    for t in kt:
        best = None
        for c in ct:
            if set(c.get("keys") or []) & set(t["keys"]) or _norm_text(c.get("title")) == _norm_text(t["title"]):
                e = max(abs(c["x0"] - t["x0"]), abs(c["x1"] - t["x1"]))
                if best is None or e < best:
                    best = e
        ok = best is not None and best <= tol
        right += ok
        rows.append({"title": t["title"], "edge_error_pt": best, "ok": ok})
    return {"score": right / len(kt), "tracks": rows}


PARTS = (("header", score_header), ("curves", score_curves), ("rocks", score_rocks),
         ("symbols", score_symbols), ("intervals", score_intervals), ("text", score_text),
         ("tracks", score_tracks))


def score(key, cand, parts=None):
    """{part: {score, ...} or None, "overall": mean of the parts scored}.
    parts limits the marking to some parts (a reader that does not try the
    rest is not marked down for them)."""
    out = {}
    for name, f in PARTS:
        if parts and name not in parts:
            continue
        out[name] = f(key, cand)
    marks = [v["score"] for v in out.values() if v and v.get("score") is not None]
    out["overall"] = sum(marks) / len(marks) if marks else None
    return out
