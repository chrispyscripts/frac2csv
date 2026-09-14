"""Well audit: the things a person flags, found from the data alone.

Runs over exactly what the desktop app hands the Lab — the `stages` list
from localapp.serialize — so the Lab, the export and a corpus sweep all read
ONE computation. Nothing here repairs anything: the project has backed out
three gap-filling attempts, and every one of them went wrong by filling a
hole it had not first classified. This module classifies, with evidence,
and stops.

A finding is a dict:

    kind      what was found (gap.missing, flat.rule, stage.missing, ...)
    severity  "warn" — a person would flag this; "info" — worth knowing,
              not a defect (the pen was up, the chart is not drawn yet)
    stage     the chart's stage label, "" for file-level findings
    channel   the canonical channel, "" for stage- or file-level findings
    page      the PDF page the chart came from
    evidence  the numbers, in one sentence
    action    what to do about it, in one sentence

Kinds, and the client report each answers:

    channel.absent     a channel every other stage of this template carries
                       is not on this one at all            (#638)
    channel.empty      the channel is present and holds nothing
    channel.sparse     a quarter or more of the stage is missing MID-FLIGHT —
                       not the pad, not the flush, not the pen at rest
    gap.missing        one blank run with the curve mid-range on both sides
    gap.hold           most of a channel's gaps begin and end at ONE level:
                       the curve held flat and the reader dropped it (#638)
    flat.rule          a run pinned to one value across the chart: a rule
                       read as data (698.29 on 01350 p226)      (#634)
    spike              excursions that leave and return within seconds:
                       a glyph or gridline read as curve    (#629, #634)
    peak.off-axis      a value above the printed axis: something not on
                       the curve was read                 (the IFS/Hal-1 tell)
    peak.pinned        ≥30 s sitting at full scale: off-chart, not data
    pair.disagree      WH and BH Prop Conc peaks disagree: BH is delayed
                       WH, and honest charts agree within a percent (#634)
    pair.coverage      one of the pair carries far less of the stage than
                       the other: it lost its trace where its twin kept it (#638)
    stage.missing      numbers absent from the 1..N ladder         (#625)
    stage.doubled      one label produced twice
    stage.failed       a chart page the reader gave up on, by reason
    clock.absent       no date, or the 00:00:00 default
    clock.backwards    starts before the stage before it
    clock.overlap      starts before the stage before it finished (#589)

Usage:

    python3 audit.py report.pdf                    # extract, then audit
    python3 audit.py report.pdf --save payload.json --json findings.json
    python3 audit.py payload.json --matrix         # re-audit a saved payload

or from code, audit_stages(stages, notes) on the serialize() output.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta

import numpy as np

import gaps
from pipeline_export import stage_num

WARN, INFO = "warn", "info"

# ---- thresholds, in one place so a sweep can say which one it moved -------
MIN_GAP_S = 5.0            # a MISSING run shorter than this is counted, not listed
GAP_LIST_MAX = 5           # longest gaps listed per channel; the rest roll up
HOLD_TOL = 0.03            # of axis span: the two edges of a gap "agree"
HOLD_MIN_N = 3             # gaps before the hold shape is called
HOLD_FRAC = 0.7            # share of a channel's gaps that must be holds
SPARSE_FRAC = 0.25         # mid-flight missing above this is a sparse channel
EMPTY_FRAC = 0.02          # filled below this is an empty channel
FLAT_MIN_FRAC = 0.06       # stacked.html's FLAT_MIN_FRAC — keep them equal
FLAT_MIN_N = 12
FLAT_WARN_FRAC = 0.25      # a hold this long is a rule, not a proppant step
SPIKE_WIN = 21             # rolling-median window, samples
SPIKE_MAX_RUN = 8          # wider than this is a feature, not a spike
SPIKE_FRAC = 0.04          # of axis span: the smallest excursion that counts
SPIKE_WARN_N = 3
SPIKE_WARN_FRAC = 0.15     # one excursion this big is a warn on its own
PIN_TOL = 0.005            # of axis span: "at full scale"
PIN_MIN_S = 30.0
PAIR_TOL = 0.15            # WH vs BH Prop Conc peak disagreement
PAIR_COV_TOL = 0.25        # WH vs BH Prop Conc coverage disagreement, in points
PRESENT_FRAC = 0.5         # a channel on this share of a template's stages is expected
OVERLAP_MIN_S = 120.0      # a stage starting this far inside the previous one

PAIRS = [("WH Prop Conc", "BH Prop Conc")]

_FAILED = re.compile(r"^p(\d+): (.+?) failed — (.+)$")


# ---- helpers ---------------------------------------------------------------

def _axis(ch):
    """(lo, hi) the channel was read against, or None if nothing knows it.

    `axisMax` is the printed tick range where a template reports one; the
    raster templates report the axis read at the plot-frame edges instead
    (`frameTop`/`frameBot`), and Trican reports only that. Without the
    fallback every Trican gap is "unclassified" and every spike is scaled
    against the data's own range instead of the 0..80 axis it was drawn on.
    """
    hi = ch.get("axisMax")
    lo = ch.get("axisMin") or 0.0
    if hi is None and ch.get("frameTop") is not None and ch.get("frameBot") is not None:
        lo, hi = ch["frameBot"], ch["frameTop"]
    if hi is None:
        return None
    lo, hi = float(lo), float(hi)
    return None if hi == lo else (min(lo, hi), max(lo, hi))


def _arr(ch):
    return np.array([np.nan if v is None else v for v in ch["values"]], dtype=float)


def _span(axis, a):
    if axis:
        return axis[1] - axis[0]
    fin = a[np.isfinite(a)]
    return float(fin.max() - fin.min()) if fin.size else 0.0


def _stage_label(st):
    m = st.get("meta") or {}
    return str(m.get("stage") if isinstance(m, dict) else getattr(m, "stage", "") or "")


def _meta(st, key):
    m = st.get("meta") or {}
    return m.get(key) if isinstance(m, dict) else getattr(m, key, None)


def _f(kind, sev, st, ch, evidence, action, **extra):
    d = {"kind": kind, "severity": sev, "stage": _stage_label(st) if st else "",
         "channel": ch.get("key", "") if ch else "",
         "page": st.get("page") if st else None,
         "evidence": evidence, "action": action}
    d.update(extra)
    return d


def _mmss(s):
    s = int(round(s))
    return f"{s // 60:02d}:{s % 60:02d}"


# ---- per-channel detectors -------------------------------------------------

def gap_findings(st, ch, sample_sec):
    """Every blank run, classified the way gaps.py classifies it.

    Per channel this emits at most: channel.empty | channel.sparse, one
    gap.hold, one roll-up of the mid-flight gaps with the longest few listed,
    and the pad/flush note. A channel with 40 gaps does not get 40 lines;
    what it gets is the shape they make, which is what diagnoses them.
    """
    vals = ch["values"]
    n = len(vals)
    if not n:
        return [], {}
    axis = _axis(ch)
    runs = gaps.find_gaps(vals, axis)
    by = {}
    for g in runs:
        by[g["kind"]] = by.get(g["kind"], 0) + g["n"]
    filled = 1.0 - sum(by.values()) / float(n)
    out = []
    if filled < EMPTY_FRAC:
        out.append(_f("channel.empty", WARN, st, ch,
                      f"{filled * 100:.1f}% of {n} samples carry a value",
                      "the curve was not traced — check whether this page draws it at all"))
        return out, {"filled": filled, **by}

    miss = by.get(gaps.MISSING, 0) + by.get(gaps.UNKNOWN, 0)
    # The pad and the flush are not drawn on some templates, so the honest
    # denominator is the span between the first reading and the last — what
    # the chart actually plotted — not the whole stage. 01350 stage 1: WH
    # Prop Conc is 24% of the STAGE missing mid-flight, which reads as a
    # rounding error, and 49% of its DRAWN span, which is the defect.
    drawn = n - by.get(gaps.LEAD, 0) - by.get(gaps.TRAIL, 0)
    first = by.get(gaps.LEAD, 0) / n * 100
    last = (n - by.get(gaps.TRAIL, 0)) / n * 100
    if drawn > 0 and miss / drawn >= SPARSE_FRAC:
        kinds = ("mid-flight" if axis else
                 "mid-chart, unclassified because this channel's axis was not read")
        out.append(_f("channel.sparse", WARN, st, ch,
                      f"{miss / drawn * 100:.0f}% of the drawn span ({_mmss(miss * sample_sec)}) "
                      f"is missing {kinds}; the curve runs from {first:.0f}% to {last:.0f}% "
                      f"of the chart and carries {filled * 100:.0f}% of the stage",
                      "a trace was lost, or painted over — open the page",
                      missing_frac=round(miss / drawn, 3), filled=round(filled, 3)))

    big = [g for g in runs if g["kind"] == gaps.MISSING and g["n"] * sample_sec >= MIN_GAP_S]
    small = sum(1 for g in runs if g["kind"] == gaps.MISSING) - len(big)
    span = _span(axis, _arr(ch)) or 1.0
    # A gap the curve enters and leaves at the same level was a HOLD: the
    # curve ran flat through it. On 01350, 364 of WH Prop Conc's 384 gaps are
    # this shape, at the proppant schedule's own levels — the reader drops the
    # flat segments of a curve drawn in its gridlines' colour.
    flat = [g for g in big if abs(g["after"] - g["before"]) < HOLD_TOL * span]
    if len(big) >= HOLD_MIN_N and len(flat) / len(big) >= HOLD_FRAC:
        step = span / 16.0
        levels = {}
        for g in flat:
            lv = step * round((g["after"] + g["before"]) / 2 / step)
            levels[lv] = levels.get(lv, 0) + 1
        top = ", ".join(f"{lv:g} ×{c}" for lv, c in
                        sorted(levels.items(), key=lambda kv: -kv[1])[:5])
        out.append(_f("gap.hold", WARN, st, ch,
                      f"{len(flat)} of {len(big)} gaps begin and end at the same level "
                      f"(Δ < {HOLD_TOL * 100:.0f}% of the axis), {_mmss(sum(g['n'] for g in flat) * sample_sec)} "
                      f"in all — the curve held flat through them, at {top}",
                      "flat segments are being dropped — a rule read where the curve holds a level; "
                      "each hold is witnessed at both edges and could be filled at that level, marked",
                      flat=len(flat), total=len(big)))
    for g in sorted(big, key=lambda g: -g["n"])[:GAP_LIST_MAX]:
        secs = g["n"] * sample_sec
        out.append(_f("gap.missing", WARN, st, ch,
                      f"{_mmss(secs)} blank from {_mmss(g['start'] * sample_sec)} to "
                      f"{_mmss((g['end'] + 1) * sample_sec)}, curve at {g['before']:.4g} "
                      f"before and {g['after']:.4g} after",
                      "mid-range both sides: a candidate for a marked interpolation",
                      span=[g["start"], g["end"] + 1], seconds=round(secs, 1)))
    if len(big) > GAP_LIST_MAX or (small and not big):
        rest = len(big) - min(len(big), GAP_LIST_MAX)
        out.append(_f("gap.missing", INFO if not big else WARN, st, ch,
                      f"{len(big)} mid-flight gap(s) ≥ {MIN_GAP_S:.0f} s in all, "
                      f"{_mmss(sum(g['n'] for g in big) * sample_sec)}"
                      + (f"; {rest} not listed above" if rest > 0 else "")
                      + (f"; plus {small} under {MIN_GAP_S:.0f} s" if small else ""),
                      "the roll-up; the longest are listed individually"))
    if (by.get(gaps.LEAD, 0) + by.get(gaps.TRAIL, 0)) / n >= 0.5:
        out.append(_f("channel.partial", INFO, st, ch,
                      f"drawn from {first:.0f}% to {last:.0f}% of the chart; nothing outside that",
                      "the chart does not draw this channel there — not a loss"))
    return out, {"filled": filled, **by}


def flat_rule(st, ch):
    """A run pinned to ONE value across the chart — stacked.html's flatRuns."""
    a = _arr(ch)
    n = a.size
    if not n:
        return []
    axis = _axis(ch)
    span = _span(axis, a) or 1.0
    tol = span * 1e-4
    need = max(FLAT_MIN_N, int(round(n * FLAT_MIN_FRAC)))
    # A curve resting at the floor for the pad and the flush is flat too, and
    # it is the pen at rest, not a rule — the same line gaps.py draws. Pinned
    # at the ceiling is peak_checks' job. Only a mid-range run is a rule.
    lo = axis[0] if axis else float(np.nanmin(a))
    out, i = [], 0
    while i < n:
        v = a[i]
        if not np.isfinite(v):
            i += 1
            continue
        j = i + 1
        while j < n and np.isfinite(a[j]) and abs(a[j] - v) <= tol:
            j += 1
        frac = (v - lo) / span
        if j - i >= need and gaps.FLOOR < frac < gaps.CEIL:
            # Concentration is pumped in steps — 100, 200, 225 kg/m3 held for
            # minutes each is the schedule, not a rule. The Lab shades from
            # 6% so the eye can judge; the auditor only WARNS when the run is
            # long enough that no schedule holds it (698.29 was 44%).
            sev = WARN if (j - i) / n >= FLAT_WARN_FRAC else INFO
            out.append(_f("flat.rule", sev, st, ch,
                          f"{j - i} samples ({(j - i) / n * 100:.0f}% of the stage) sit at "
                          f"exactly {v:.4g} from sample {i} to {j}",
                          "a rule or frame line read as the curve — blank it, do not export it",
                          span=[i, j], value=float(v)))
        i = j if j > i else i + 1
    return out


def spikes(st, ch, sample_sec):
    """Excursions that leave the curve and come back within seconds."""
    a = _arr(ch)
    fin = np.flatnonzero(np.isfinite(a))
    if fin.size < SPIKE_WIN * 2:
        return []
    v = a[fin]
    w = SPIKE_WIN
    pad = np.pad(v, (w // 2, w // 2), mode="edge")
    med = np.median(np.lib.stride_tricks.sliding_window_view(pad, w), axis=1)
    resid = v - med
    axis = _axis(ch)
    span = _span(axis, a) or 1.0
    mad = np.median(np.abs(resid - np.median(resid))) * 1.4826
    thr = max(SPIKE_FRAC * span, 6.0 * mad)
    hot = np.abs(resid) > thr
    if not hot.any():
        return []
    idx = np.flatnonzero(hot)
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    runs = [r for r in runs if len(r) <= SPIKE_MAX_RUN]
    if not runs:
        return []
    mags = [float(resid[r][np.argmax(np.abs(resid[r]))]) for r in runs]
    biggest = max(mags, key=abs)
    down = sum(1 for m in mags if m < 0)
    floor = axis and any(v[r].min() <= axis[0] + PIN_TOL * span for r in runs)
    sev = WARN if (len(runs) >= SPIKE_WARN_N or abs(biggest) >= SPIKE_WARN_FRAC * span) else INFO
    tops = sorted(zip(mags, runs), key=lambda t: -abs(t[0]))[:3]
    where = ", ".join(f"{_mmss(fin[r[0]] * sample_sec)} ({m:+.3g})" for m, r in tops)
    out = [_f("spike", sev, st, ch,
              f"{len(runs)} excursion(s) of ≤{SPIKE_MAX_RUN} samples beyond {thr:.3g} "
              f"from the local median; {down} downward; largest {biggest:+.3g} "
              f"({abs(biggest) / span * 100:.0f}% of span)"
              + ("; reaches the axis floor" if floor else "") + f" — at {where}",
              "a label, tick or gridline caught by the mask — check the ink at those seconds",
              count=len(runs), largest=biggest)]
    return out


def peak_checks(st, ch, sample_sec):
    axis = _axis(ch)
    if not axis:
        return []
    a = _arr(ch)
    if not np.isfinite(a).any():
        return []
    lo, hi = axis
    span = hi - lo
    out = []
    pk = float(np.nanmax(a))
    if pk > hi + PIN_TOL * span:
        out.append(_f("peak.off-axis", WARN, st, ch,
                      f"peak {pk:.4g} is above the printed axis top {hi:.4g}",
                      "something that is not the curve was read as data — the IFS/Hal-1 tell"))
    mn = float(np.nanmin(a))
    if mn < lo - PIN_TOL * span:
        out.append(_f("peak.off-axis", WARN, st, ch,
                      f"minimum {mn:.4g} is below the printed axis floor {lo:.4g}",
                      "something below the frame was read as data"))
    at = np.isfinite(a) & (a >= hi - PIN_TOL * span)
    if at.any():
        idx = np.flatnonzero(at)
        longest = max(len(r) for r in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1))
        if longest * sample_sec >= PIN_MIN_S:
            out.append(_f("peak.pinned", WARN, st, ch,
                          f"{_mmss(longest * sample_sec)} sitting within {PIN_TOL * 100:.1f}% "
                          f"of full scale ({hi:.4g})",
                          "the curve is off-chart there, or the frame line was traced"))
    return out


# ---- per-stage detectors ---------------------------------------------------

def pair_disagree(st):
    chans = {c["key"]: c for c in st.get("channels", [])}
    out = []
    for a, b in PAIRS:
        if a not in chans or b not in chans:
            continue
        pa, pb = _arr(chans[a]), _arr(chans[b])
        if not (np.isfinite(pa).any() and np.isfinite(pb).any()):
            continue
        fa, fb = float(np.isfinite(pa).mean()), float(np.isfinite(pb).mean())
        if abs(fa - fb) > PAIR_COV_TOL:
            low, high = (a, b) if fa < fb else (b, a)
            out.append(_f("pair.coverage", WARN, st, chans[low],
                          f"{a} carries {fa * 100:.0f}% of the stage, {b} {fb * 100:.0f}% — "
                          f"{low} has lost {abs(fa - fb) * 100:.0f} points against its pair",
                          "BH is delayed WH, drawn over the same span; the sparse one lost "
                          "its trace where the other kept it — the ink says where"))
        ka, kb = float(np.nanmax(pa)), float(np.nanmax(pb))
        top = max(ka, kb)
        if top <= 0:
            continue
        d = abs(ka - kb) / top
        if d > PAIR_TOL:
            out.append(_f("pair.disagree", WARN, st, chans[a] if ka > kb else chans[b],
                          f"{a} peaks at {ka:.4g}, {b} at {kb:.4g} — {d * 100:.0f}% apart",
                          "BH is delayed WH; the higher one has read something that is not "
                          "the curve — usually a rule or a label"))
    return out


# ---- file-level detectors --------------------------------------------------

def presence(stages):
    """A channel every other stage of this template carries, absent here."""
    by_src = {}
    for st in stages:
        by_src.setdefault(st.get("source", "?"), []).append(st)
    out = []
    for src, group in by_src.items():
        if len(group) < 3:
            continue
        count = {}
        for st in group:
            for c in st.get("channels", []):
                count[c["key"]] = count.get(c["key"], 0) + 1
        expected = {k for k, n in count.items() if n / len(group) >= PRESENT_FRAC}
        for st in group:
            have = {c["key"] for c in st.get("channels", [])}
            for k in sorted(expected - have):
                out.append(_f("channel.absent", WARN, st, {"key": k},
                              f"{k} is on {count[k]} of {len(group)} {src} stages and not this one",
                              "the reader dropped the channel on this page — its note says why"))
    return out


def ladder(stages, notes):
    labels = [_stage_label(st) for st in stages]
    nums = sorted({stage_num(l) for l in labels if stage_num(l) < 10 ** 9})
    out = []
    if nums:
        lo, hi = 1, max(nums)
        missing = [k for k in range(lo, hi + 1) if k not in set(nums)]
        if missing:
            out.append(_f("stage.missing", WARN, None, None,
                          f"{len(missing)} of {hi} absent from the ladder: "
                          + ", ".join(map(str, missing[:20]))
                          + (" …" if len(missing) > 20 else ""),
                          "a page the reader skipped or failed — see stage.failed",
                          stages=missing))
    seen = {}
    for st, l in zip(stages, labels):
        seen.setdefault(l, []).append(st.get("page"))
    for l, pages in seen.items():
        if len(pages) > 1:
            out.append(_f("stage.doubled", WARN, None, None,
                          f"stage {l!r} produced {len(pages)} times, pages {pages}",
                          "two sheets of one run merged, or one run read twice"))
    failed = []
    for n in notes or []:
        m = _FAILED.match(str(n))
        if m:
            failed.append((int(m.group(1)), m.group(2), m.group(3)))
    for page, what, why in failed:
        out.append(_f("stage.failed", WARN, None, None,
                      f"p{page}: {what} — {why}", "a chart page produced nothing; "
                      "the ladder gap above is probably this", page=page))
    return out, {"stages": len(stages), "numbered": len(nums),
                 "max": max(nums) if nums else 0, "failed": len(failed)}


_DATE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _start(st):
    d, t = str(_meta(st, "date") or ""), str(_meta(st, "start_time") or "")
    m = _DATE.search(d)
    if not m or not t or t == "00:00:00":
        return None
    try:
        hh, mm, ss = (int(x) for x in (t.split(":") + ["0", "0"])[:3])
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hh, mm, ss)
    except ValueError:
        return None


def clocks(stages):
    out = []
    order = sorted(stages, key=lambda st: (stage_num(_stage_label(st)), st.get("page") or 0))
    prev = None
    for st in order:
        t = _start(st)
        if t is None:
            out.append(_f("clock.absent", INFO, st, None,
                          f"date {_meta(st, 'date')!r}, start {_meta(st, 'start_time')!r}",
                          "no clock on this chart; the CSV will date it from the default"))
            continue
        if prev:
            pt, pdur, plabel = prev
            if t < pt:
                out.append(_f("clock.backwards", WARN, st, None,
                              f"starts {t:%Y-%m-%d %H:%M:%S}, before stage {plabel} "
                              f"({pt:%Y-%m-%d %H:%M:%S})",
                              "a misread date or a lost PM — the Fix time button, or the reader"))
            elif t < pt + timedelta(minutes=pdur) - timedelta(seconds=OVERLAP_MIN_S):
                out.append(_f("clock.overlap", WARN, st, None,
                              f"starts {t:%H:%M:%S}, {(pt + timedelta(minutes=pdur) - t).seconds // 60} "
                              f"min before stage {plabel} finished",
                              "one of the two clocks is wrong, or the stages genuinely overlap"))
        prev = (t, float(_meta(st, "duration_min") or 0.0), _stage_label(st))
    return out


# ---- the audit -------------------------------------------------------------

def digest(stages):
    """Per stage|channel: a hash of the values, the peak and the fill — the
    before/after currency. Two runs whose digests match did not change."""
    out = {}
    for st in stages:
        for ch in st.get("channels", []):
            a = _arr(ch)
            h = hashlib.sha1(np.round(np.nan_to_num(a, nan=-9e9), 3).tobytes()).hexdigest()[:12]
            out[f"{_stage_label(st)}|{ch['key']}"] = {
                "sha": h, "peak": float(np.nanmax(a)) if np.isfinite(a).any() else None,
                "filled": round(float(np.isfinite(a).mean()), 4) if a.size else 0.0}
    return out


def audit_stages(stages, notes=None):
    findings, coverage = [], {}
    for st in stages:
        sec = float(st.get("sample_sec") or 1.0)
        for ch in st.get("channels", []):
            f, cov = gap_findings(st, ch, sec)
            findings += f
            coverage[f"{_stage_label(st)}|{ch['key']}"] = cov
            findings += flat_rule(st, ch)
            findings += spikes(st, ch, sec)
            findings += peak_checks(st, ch, sec)
        findings += pair_disagree(st)
    findings += presence(stages)
    lad, ladder_info = ladder(stages, notes)
    findings += lad
    findings += clocks(stages)
    by_kind = {}
    for f in findings:
        k = f["kind"] + ("" if f["severity"] == WARN else " (info)")
        by_kind[k] = by_kind.get(k, 0) + 1
    return {"findings": findings, "by_kind": by_kind, "ladder": ladder_info,
            "coverage": coverage, "digest": digest(stages)}


# ---- report ----------------------------------------------------------------

def matrix(stages, coverage):
    """stage × channel: filled% and mid-flight-missing%, one glance."""
    keys = []
    for st in stages:
        for ch in st.get("channels", []):
            if ch["key"] not in keys:
                keys.append(ch["key"])
    lines = ["  stage  page  " + "  ".join(f"{k[:14]:>14}" for k in keys)]
    for st in stages:
        cells = []
        have = {c["key"] for c in st.get("channels", [])}
        for k in keys:
            if k not in have:
                cells.append(f"{'— absent —':>14}")
                continue
            cov = coverage.get(f"{_stage_label(st)}|{k}", {})
            n = len(next(c for c in st["channels"] if c["key"] == k)["values"]) or 1
            miss = (cov.get(gaps.MISSING, 0) + cov.get(gaps.UNKNOWN, 0)) / n * 100
            cells.append(f"{cov.get('filled', 0) * 100:5.0f}% / m{miss:3.0f}%")
        lines.append(f"  {_stage_label(st):>5}  {str(st.get('page') or ''):>4}  " + "  ".join(cells))
    return "\n".join(lines)


def report(payload, res, show_matrix=False):
    stages = payload["stages"]
    srcs = {}
    for st in stages:
        srcs[st.get("source", "?")] = srcs.get(st.get("source", "?"), 0) + 1
    L = [f"{payload.get('file', '?')} — {payload.get('npages', '?')} pages, "
         f"{len(stages)} series ({', '.join(f'{k} ×{v}' for k, v in srcs.items())}), "
         f"{len(payload.get('notes') or [])} notes"]
    lad = res["ladder"]
    L.append(f"ladder: {lad['numbered']} numbered stages of max {lad['max']}, "
             f"{lad['failed']} chart page(s) failed")
    warn = [f for f in res["findings"] if f["severity"] == WARN]
    L.append(f"\n{len(warn)} warn finding(s), {len(res['findings']) - len(warn)} info")
    for k, n in sorted(res["by_kind"].items(), key=lambda kv: (kv[0].endswith("(info)"), -kv[1])):
        L.append(f"  {n:4d}  {k}")
    L.append("")
    for f in warn:
        where = f"stage {f['stage']}" if f["stage"] else "file"
        if f.get("page"):
            where += f" p{f['page']}"
        ch = f" · {f['channel']}" if f["channel"] else ""
        L.append(f"WARN {f['kind']:<16} {where}{ch}\n      {f['evidence']}\n      → {f['action']}")
    if show_matrix:
        L.append("\ncoverage — filled% / m = missing mid-flight%  (absent = channel not on the stage)")
        L.append(matrix(stages, res["coverage"]))
    return "\n".join(L)


def load_pdf(path, on_page=None):
    """The desktop app's own call chain — pipeline.extract_document then
    localapp.serialize — never a copy of it. -> the payload audit reads."""
    import os
    import time
    import fitz
    import localapp
    import pipeline
    t0 = time.time()
    doc = fitz.open(path)
    npages = len(doc)
    results, notes = pipeline.extract_document(
        doc, filename=os.path.basename(path), on_page=on_page)
    doc.close()
    stages, tables, notes, summary = localapp.serialize(results, notes)
    return {"file": os.path.basename(path), "npages": npages,
            "seconds": round(time.time() - t0, 1), "stages": stages,
            "tables": [{k: v for k, v in t.items() if k != "rows"}
                       | {"nrows": len(t["rows"])} for t in tables],
            "notes": notes}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0].lower().endswith(".pdf"):
        def prog(d, t):
            if d % 25 == 0 or d == t:
                print(f"  page {d}/{t}", file=sys.stderr, flush=True)
        payload = load_pdf(argv[0], on_page=prog)
        if "--save" in argv:
            out = argv[argv.index("--save") + 1]
            json.dump(payload, open(out, "w"),
                      default=lambda o: getattr(o, "__dict__", str(o)))
            print(f"payload → {out}", file=sys.stderr)
    else:
        payload = json.load(open(argv[0]))
    res = audit_stages(payload["stages"], payload.get("notes"))
    print(report(payload, res, show_matrix="--matrix" in argv))
    if "--json" in argv:
        out = argv[argv.index("--json") + 1]
        json.dump({"file": payload.get("file"), **res}, open(out, "w"), indent=1)
        print(f"\nfindings → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
