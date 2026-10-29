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
    spike.aligned      the same second spikes on 3+ channels: a page seam,
                       a rule or a text column read through every mask (#629)
    peak.off-axis      a value above the printed axis: something not on
                       the curve was read                 (the IFS/Hal-1 tell)
    peak.pinned        ≥30 s sitting at full scale: off-chart, not data
    pair.disagree      WH and BH Prop Conc peaks disagree: BH is delayed
                       WH, and honest charts agree within a percent (#634)
    pair.coverage      one of the pair carries far less of the stage than
                       the other: it lost its trace where its twin kept it (#638)
    stage.missing      numbers absent from the 1..N ladder         (#625), and
                       stages the report's own stage table pumps that no
                       chart carries, past the last chart included
    stage.not-pumped   a ladder gap the stage table leaves blank too: not
                       pumped, or filed with no data — info, not a miss
    stage.single       one template's charts all carry ONE stage: the number
                       was read once, not per page (00232, 00233, 00240)
    stage.unknown      a stage-length chart with no stage number — "Stage ?"
                       in the Lab (00278's 60 charts)
    stage.doubled      one label produced twice
    stage.failed       a chart page the reader gave up on, by reason
    clock.absent       no date, or the 00:00:00 default — a warning when the
                       page is known to print a clock the reader did not take
    clock.in-table     the report's own stage table prints a start for this
                       stage and the chart has none — a join never made (#639)
    clock.none         no stage of a template has a clock: the layout's time
                       axis is unread, or the charts plot elapsed minutes (#639)
    stage.unlabelled   charts with no stage label (overview plots) — info
    clock.backwards    starts before the stage before it
    clock.overlap      starts before the stage before it finished (#589),
                       with the likeliest cause where the numbers show one:
                       a date a day off, or a chart away from the start the
                       report's stage table prints for it

Usage:

    python3 audit.py report.pdf                    # extract, then audit
    python3 audit.py report.pdf --save payload.json --json findings.json
    python3 audit.py payload.json --matrix         # re-audit a saved payload

and a folder or a whole corpus, any provider, in one report:

    python3 validation-tools/audit/sweep.py <out-dir> <pdf-or-folder>...

or from code, audit_stages(stages, notes, tables) on the serialize() output.
"""
import hashlib
import json
import re
import sys
from collections import Counter
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
SPIKE_PLUNGE_FRAC = 0.5    # no axis: a downward spike losing this much of the peak still warns
SPIKE_EDGE_S = 300.0       # pressure spikes this close to a stage's ends are transients, at INFO
ALIGN_WIN_S = 2            # spikes within this many seconds count as the same moment
ALIGN_MIN_CH = 3           # channels that must share the moment
PIN_TOL = 0.005            # of axis span: "at full scale"
PIN_MIN_S = 30.0
PAIR_TOL = 0.15            # WH vs BH Prop Conc peak disagreement
PAIR_COV_TOL = 0.25        # WH vs BH Prop Conc coverage disagreement, in points
PRESENT_FRAC = 0.5         # a channel on this share of a template's stages is expected
OVERLAP_FRAC = 0.35        # the Lab's OVERLAP_FRAC: of the starting stage's own duration
OVERLAP_FLOOR_S = 900.0    # the Lab's OVERLAP_FLOOR_MS: never under fifteen minutes

PAIRS = [("WH Prop Conc", "BH Prop Conc")]
# findings that speak for a whole channel on a stage; its gaps sit under them
CHANNEL_LEVEL = {"channel.sparse", "gap.hold", "pair.coverage", "pair.disagree",
                 "channel.empty"}

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
    # Once the channel itself has warned — sparse, or the hold shape — the
    # gaps are its evidence, not forty more warnings. A channel with a few
    # isolated gaps and no channel-level finding keeps them as warnings.
    # One warning per channel per stage. A channel with no channel-level
    # finding but real holes gets ONE gap.missing warning naming its longest;
    # every individual gap is listed beneath it as information, with its
    # span, so a fill can find it. 01433 was carrying 255 of these.
    channel_warned = any(f["kind"] in ("channel.sparse", "gap.hold") for f in out)
    if big and not channel_warned:
        tops = sorted(big, key=lambda g: -g["n"])[:3]
        where = ", ".join(f"{_mmss(g['n'] * sample_sec)} at {_mmss(g['start'] * sample_sec)} "
                          f"({g['before']:.3g}→{g['after']:.3g})" for g in tops)
        out.append(_f("gap.missing", WARN, st, ch,
                      f"{len(big)} mid-flight gap(s) ≥ {MIN_GAP_S:.0f} s, "
                      f"{_mmss(sum(g['n'] for g in big) * sample_sec)} in all — longest {where}"
                      + (f"; plus {small} under {MIN_GAP_S:.0f} s" if small else ""),
                      "mid-range both sides: candidates for a marked interpolation",
                      count=len(big), seconds=round(sum(g["n"] for g in big) * sample_sec, 1)))
    for g in sorted(big, key=lambda g: -g["n"])[:GAP_LIST_MAX]:
        secs = g["n"] * sample_sec
        out.append(_f("gap.missing", INFO, st, ch,
                      f"{_mmss(secs)} blank from {_mmss(g['start'] * sample_sec)} to "
                      f"{_mmss((g['end'] + 1) * sample_sec)}, curve at {g['before']:.4g} "
                      f"before and {g['after']:.4g} after",
                      "one gap, with its span",
                      span=[g["start"], g["end"] + 1], seconds=round(secs, 1)))
    if len(big) > GAP_LIST_MAX or (small and not big):
        rest = len(big) - min(len(big), GAP_LIST_MAX)
        out.append(_f("gap.missing", INFO, st, ch,
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
    if axis:
        sev = WARN if (len(runs) >= SPIKE_WARN_N or abs(biggest) >= SPIKE_WARN_FRAC * span) else INFO
        scale = f"{abs(biggest) / span * 100:.0f}% of the axis"
    else:
        # Without a printed axis "% of span" is a fraction of the channel's
        # own range, and a flat channel's range is its noise: Canyon's
        # Monitor gave 122 "excursions" of 0.05 MPa. What still counts with
        # no axis is a PLUNGE — the curve losing half of its own peak and
        # coming straight back — which is #629 exactly.
        peak = float(np.nanmax(np.abs(v))) or 1.0
        plunge = any(m < 0 and abs(m) >= SPIKE_PLUNGE_FRAC * peak for m in mags)
        sev = WARN if plunge else INFO
        scale = f"{abs(biggest) / peak * 100:.0f}% of the channel's peak, no axis known"
    tops = sorted(zip(mags, runs), key=lambda t: -abs(t[0]))[:3]
    where = ", ".join(f"{_mmss(fin[r[0]] * sample_sec)} ({m:+.3g})" for m, r in tops)
    action = "a label, tick or gridline caught by the mask — check the ink at those seconds"
    # A PRESSURE spike inside the first or last minutes of a stage is what a
    # ball seating or the pumps shutting down looks like, and the page draws
    # it: on 00026, 39 of the 44 BH Pressure excursions flagged here were
    # strokes of the brown curve itself, 20-100 px tall, nearly all at the
    # stage's edges. Said as what it is, at INFO, so the sweep's warnings
    # are left for the mask's mistakes.
    total = float(fin[-1] * sample_sec) if fin.size else 0.0
    edge = all(fin[r[0]] * sample_sec < SPIKE_EDGE_S
               or fin[r[-1]] * sample_sec > total - SPIKE_EDGE_S for r in runs)
    if edge and _is_pressure(ch) and sev == WARN:
        sev = INFO
        action = ("pressure transients at the stage's edges — a ball seating or "
                  "the pumps shutting down, which the page draws; not a mask error")
    out = [_f("spike", sev, st, ch,
              f"{len(runs)} excursion(s) of ≤{SPIKE_MAX_RUN} samples beyond {thr:.3g} "
              f"from the local median; {down} downward; largest {biggest:+.3g} "
              f"({scale})"
              + ("; reaches the axis floor" if floor else "") + f" — at {where}",
              action,
              count=len(runs), largest=biggest,
              at=[round(float(fin[r[0]] * sample_sec), 1) for r in runs])]
    return out


def _is_pressure(ch):
    k = (str(ch.get("key") or "") + " " + str(ch.get("label") or "")
         + " " + str(ch.get("unit") or "")).lower()
    return "press" in k or "mpa" in k or "kpa" in k


def aligned_spikes(st, spike_findings, sample_sec):
    """Spikes that land at the same second on several channels.

    Per channel a spike is a label or a gridline caught by one colour mask.
    The same second on three channels is something every mask read — a
    vertical rule, a page seam (Canyon charts span two pages), a column of
    text — and that is one defect, not three (#629).
    """
    at = {}
    for f in spike_findings:
        for t in f.get("at", ()):
            at.setdefault(int(t // ALIGN_WIN_S), set()).add(f["channel"])
    hits = [(b * ALIGN_WIN_S, chans) for b, chans in sorted(at.items()) if len(chans) >= ALIGN_MIN_CH]
    if not hits:
        return []
    where = "; ".join(f"{_mmss(t)} ({', '.join(sorted(c))})" for t, c in hits[:4])
    return [_f("spike.aligned", WARN, st, None,
               f"{len(hits)} moment(s) where {ALIGN_MIN_CH}+ channels spike together — {where}"
               + (" …" if len(hits) > 4 else ""),
               "a vertical feature read through every mask — a page seam, a rule or a "
               "text column; one defect, not one per channel",
               moments=[t for t, _ in hits])]


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

def per_stage(group):
    """How many charts one template prints for a stage: the usual count over
    its numbered stages. STEP's treatment and offset-well plots are both "STEP
    surface chart" and both carry the stage's number (00241, 00243: two a
    stage), and so are CalFrac's Surface and Bottom Hole sheets."""
    n = Counter(_stage_label(st).strip() for st in group)
    n.pop("", None)
    return Counter(n.values()).most_common(1)[0][0] if n else 1


def kinds(group):
    """One template's charts split into the kinds it prints a stage: the n-th
    chart of each stage, by page, against the n-th of the others. A stage
    that printed more or fewer joins each chart to the kind it shares most
    channels with, so a chart that lost most of its pens still lands with
    its own kind and is reported there."""
    n = per_stage(group)
    if n < 2:
        return [group]
    by = {}
    for st in group:
        by.setdefault(_stage_label(st).strip(), []).append(st)
    out, odd = [[] for _ in range(n)], []
    for label, sts in by.items():
        if label and len(sts) == n:
            for i, st in enumerate(sorted(sts, key=lambda s: s.get("page") or 0)):
                out[i].append(st)
        else:
            odd += sts
    keys = [Counter(c["key"] for st in kd for c in st.get("channels", [])) for kd in out]
    for st in odd:
        have = {c["key"] for c in st.get("channels", [])}
        i = max(range(n), key=lambda i: sum(keys[i][k] for k in have) / max(1, len(out[i])))
        out[i].append(st)
    return out


def presence(stages):
    """A channel every other stage of this template carries, absent here."""
    by_src = {}
    for st in stages:
        by_src.setdefault(st.get("source", "?"), []).append(st)
    out = []
    for src, whole in by_src.items():
        for group in kinds(whole):
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


_TABLE_STAGE_COL = re.compile(r"^\s*(stage|interval|zone)\s*(#|no\.?|number|name)?\s*$", re.I)
# what a pumped stage's row prints; not "volume": STEP's Hole Volume and
# CalFrac's Volume to Frac Port are the well's geometry, filled in either way
_PUMPED_COL = re.compile(r"date|start|end\s*time|duration|pump|slurry|clean|proppant|"
                         r"rate|pressure|isip", re.I)


def table_ladder(tables):
    """The report's own per-stage table: (title, {stage: pumped}) or None.

    pumped is True when the row prints anything a pumped stage has — a
    time, a rate, a volume — False when it prints its number and depths
    only (00185 leaves stages 1, 13, 14 … blank in its Daily Stage Summary:
    nothing was pumped there, or nothing was filed), and None when the table
    has no such column to tell by. The table with the most stages wins."""
    best = None
    for t in tables or []:
        cols = [str(c) for c in t.get("columns") or []]
        si = next((i for i, c in enumerate(cols) if _TABLE_STAGE_COL.match(c)), None)
        if si is None:
            continue
        pumped = [i for i, c in enumerate(cols) if i != si and _PUMPED_COL.search(c)]
        rows = {}
        for row in t.get("rows") or []:
            if len(row) <= si:
                continue
            k = stage_num(row[si])
            if k >= 10 ** 9:
                continue
            if not pumped:
                rows.setdefault(k, None)
                continue
            filled = any(j < len(row) and row[j] is not None and str(row[j]).strip()
                         for j in pumped)
            rows[k] = bool(rows.get(k)) or filled
        if rows and (best is None or len(rows) > len(best[1])):
            best = (t.get("title") or "the stage table", rows)
    return best


def _minutes(st):
    return float(_meta(st, "duration_min") or 0.0) or \
        (st.get("n") or 0) * float(st.get("sample_sec") or 1.0) / 60.0


def ladder(stages, notes, tables=None):
    labels = [_stage_label(st) for st in stages]
    nums = sorted({stage_num(l) for l in labels if stage_num(l) < 10 ** 9})
    out = []
    tab = table_ladder(tables)
    title, rows = tab if tab else ("", {})
    hi = max(nums) if nums else 0
    if nums or any(rows.values()):
        gaps_ = [k for k in range(1, hi + 1) if k not in set(nums)]
        # a gap the report's own table leaves blank is the report's, not the
        # reader's: there is no chart to find
        blank = [k for k in gaps_ if rows.get(k) is False]
        # ...and a stage the table pumps past the last chart is as missing as
        # one inside the ladder — 00271's table runs to 38, its charts stop at 5
        missing = [k for k in gaps_ if k not in blank] + \
            sorted(k for k, p in rows.items() if p and k > hi)
        top = max([hi] + [k for k, p in rows.items() if p])
        if missing:
            listed = [k for k in missing if rows.get(k)]
            out.append(_f("stage.missing", WARN, None, None,
                          f"{len(missing)} of {top} absent from the ladder: "
                          + ", ".join(map(str, missing[:20]))
                          + (" …" if len(missing) > 20 else "")
                          + (f" — {title!r} prints data for {len(listed)} of them"
                             if listed else ""),
                          "a page the reader skipped or failed — see stage.failed — or the "
                          "report prints no chart for it (00271 charts 1-5 of 38)",
                          stages=missing))
        if blank:
            out.append(_f("stage.not-pumped", INFO, None, None,
                          f"{', '.join(map(str, blank[:20]))} absent from the charts and blank in "
                          f"{title!r} too",
                          "not pumped, or filed with no data — nothing for the reader to find",
                          stages=blank))
    # One template whose charts all carry one stage: the number was read once
    # and not per page. 00232, 00233 and 00240 (Canyon) print "Interval: 1" on
    # the first page and the bare number after, and filed 16, 15 and 17
    # stages as stage 1. A one-stage job draws one or two charts per template;
    # three or more under one number is the tell.
    per_src = {}
    for st, l in zip(stages, labels):
        per_src.setdefault(st.get("source", ""), []).append(l.strip())
    for src, ls in per_src.items():
        named = {l for l in ls if l}
        if len(ls) >= 3 and len(named) == 1 and ls.count(next(iter(named))) >= 3:
            out.append(_f("stage.single", WARN, None, None,
                          f"all {len(ls)} {src} charts carry stage {next(iter(named))!r}",
                          "the stage number was read once, not per page — look at "
                          "where each page prints its own"))
    # STEP prints a surface chart AND a chemical chart for every stage; two
    # series with one label from two templates is the layout, not a double.
    seen = {}
    for st, l in zip(stages, labels):
        seen.setdefault((st.get("source", ""), l), []).append(st.get("page"))
    # "Stage ?" in the Lab. An overview of the whole job carries no number by
    # design and runs far longer than any one stage; a chart of a stage's
    # length with no number is a number the reader did not take (00278: 60).
    durs = sorted(_minutes(st) for st, l in zip(stages, labels) if l.strip())
    typical = durs[len(durs) // 2] if durs else 0.0
    unknown, overview = [], 0
    for st, l in zip(stages, labels):
        if l.strip():
            continue
        if typical and _minutes(st) > 3 * typical:
            overview += 1
        else:
            unknown.append(st.get("page"))
    if unknown:
        out.append(_f("stage.unknown", WARN, None, None,
                      f"{len(unknown)} chart(s) with no stage number (\"Stage ?\"), pages "
                      + ", ".join(f"p{pg}" for pg in unknown[:15])
                      + (" …" if len(unknown) > 15 else ""),
                      "the page prints a stage the reader did not take — or a fix file names it",
                      pages=unknown))
    if overview:
        out.append(_f("stage.unlabelled", INFO, None, None,
                      f"{overview} chart(s) with no stage label, over 3× a stage's length — "
                      "overview or whole-treatment plots",
                      "not on the ladder; check the CSV names them sensibly"))
    # ...and a template that prints two charts for every stage (STEP's
    # treatment and offset plots) doubles only past its own two
    usual = {}
    for st in stages:
        usual.setdefault(st.get("source", ""), []).append(st)
    usual = {src: per_stage(g) for src, g in usual.items()}
    for (src, l), pages in seen.items():
        if len(pages) > usual.get(src, 1) and l.strip():
            out.append(_f("stage.doubled", WARN, None, None,
                          f"stage {l!r} produced {len(pages)} times by {src}, pages {pages}",
                          "two sheets of one run merged, or one run read twice"))
    failed = []
    for n in notes or []:
        m = _FAILED.match(str(n))
        if m:
            failed.append((int(m.group(1)), m.group(2), m.group(3)))
    # A failed page sitting between the pages of stages k-1 and k+1 IS stage
    # k. 01433: stages 1, 3, 35 and 45 are p155, p157, p188, p198 — the four
    # "implausible duration" pages — and stage 16 has no page at all, which
    # is a different question.
    by_page = sorted((int(st.get("page") or 0), stage_num(l)) for st, l in zip(stages, labels)
                     if st.get("page") and stage_num(l) < 10 ** 9)
    linked = {}
    for page, what, why in failed:
        before = [k for pg, k in by_page if pg < page]
        after = [k for pg, k in by_page if pg > page]
        if before and after and after[0] - before[-1] == 2:
            linked[before[-1] + 1] = page
    for page, what, why in failed:
        k = next((k for k, pg in linked.items() if pg == page), None)
        out.append(_f("stage.failed", WARN, None, None,
                      f"p{page}: {what} — {why}"
                      + (f" — this is stage {k}, by position" if k else ""),
                      "a chart page produced nothing; the ladder gap above is probably this",
                      page=page, stage_linked=k))
    for f in out:
        if f["kind"] == "stage.missing":
            named = [k for k in f["stages"] if k in linked]
            bare = [k for k in f["stages"] if k not in linked]
            f["evidence"] += (f" — {', '.join(str(k) for k in named)} "
                              f"{'is' if len(named) == 1 else 'are'} the failed page(s) "
                              f"{', '.join('p' + str(linked[k]) for k in named)}" if named else "")
            f["evidence"] += (f"; {', '.join(map(str, bare))} "
                              f"{'has' if len(bare) == 1 else 'have'} no page at all" if bare and named else "")
            f["linked"] = linked
    return out, {"stages": len(stages), "numbered": len(nums),
                 "max": max(nums) if nums else 0, "failed": len(failed)}


_DATE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _start(st):
    """The stage's clock as a datetime, or None for the pipeline's default.

    The default is no date AND 00:00:00. A dated stage starting at 00:00:00
    is midnight: 00015's stage 4 (a 12-hour "12:00" resolved to the next
    day's midnight) was being read as unclocked and re-flagged."""
    d, t = str(_meta(st, "date") or ""), str(_meta(st, "start_time") or "")
    m = _DATE.search(d)
    if not m or not t:
        return None
    try:
        hh, mm, ss = (int(x) for x in (t.split(":") + ["0", "0"])[:3])
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hh, mm, ss)
    except ValueError:
        return None


_STAGE_COL = re.compile(r"^(stage|interval|zone)\b", re.I)
_START_COL = re.compile(r"^start(?!.*date)|start.?time", re.I)
_CLOCK = re.compile(r"^\s*([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?\s*([AaPp][Mm])?\s*$")


def table_clocks(tables):
    """{stage number: 'HH:MM'} from any table that prints a start per stage.

    00015 (#639): the pipeline reads a Trican summary table with a start
    for all 11 stages and every chart still exports 00:00:00. The table is
    the report's own printed number, so a chart without a clock while its
    row has one is a join that was never made. Note what the join needs:
    these sheets print a 12-hour clock with no AM/PM (12:44, 01:48, 02:48)
    over a two-day job — the #588 lost-PM trap — so the number is reported
    here, not applied.
    """
    out = {}
    for t in tables or []:
        cols = [str(c) for c in t.get("columns") or []]
        si = next((i for i, c in enumerate(cols) if _STAGE_COL.match(c)), None)
        ti = next((i for i, c in enumerate(cols) if _START_COL.match(c)), None)
        if si is None or ti is None:
            continue
        for row in t.get("rows") or []:
            if len(row) <= max(si, ti):
                continue
            k = stage_num(row[si])
            v = str(row[ti]).strip()
            if k < 10 ** 9 and _CLOCK.match(v) and k not in out:
                out[k] = v
    return out


def _off_table(t, row):
    """Minutes between a chart's start and its stage's printed start, by the
    12-hour reading that fits — these tables can print no AM/PM (#588)."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})", str(row or ""))
    if not m:
        return None
    d = (t.hour * 60 + t.minute) - (int(m.group(1)) % 24 * 60 + int(m.group(2)))
    return min(min(x % 1440, 1440 - x % 1440) for x in (d, d - 720))


def _overlap_cause(over, st, t, pst, pt, table):
    """The likeliest cause of an overlap, from the numbers alone, or ""."""
    k = round(over / 1440)
    if k >= 1 and abs(over - 1440 * k) < 240:
        return f"a date {k} day{'s' if k > 1 else ''} off"
    rc, rp = table.get(stage_num(_stage_label(st))), table.get(stage_num(_stage_label(pst)))
    dc, dp = _off_table(t, rc), _off_table(pt, rp)
    if dc is None or dp is None:
        return ""
    if dc > 10 >= dp:
        return f"this chart's clock: the stage table prints {rc}, {dc} min away"
    if dp > 10 >= dc:
        return (f"stage {_stage_label(pst)}'s chart: the stage table prints {rp}, "
                f"{dp} min from where it starts")
    if dc <= 10 and dp <= 10:
        return ("the report's own times: both charts start where the stage table "
                "prints them, and the earlier one runs past")
    return ""


def clocks(stages, tables=None):
    out = []
    by_src = {}
    for st in stages:
        by_src.setdefault(st.get("source", ""), []).append(st)
    printed = table_clocks(tables)
    for group in by_src.values():
        out += _clocks_one_source(group, printed)
    return out


def _clocks_one_source(stages, table=None):
    """One template's stages in ladder order. STEP's surface and chemical
    charts of one stage share a clock by design, so a stage is never
    compared with another chart of the same number."""
    table = table or {}
    out = []
    order = sorted(stages, key=lambda st: (stage_num(_stage_label(st)), st.get("page") or 0))
    prev = None
    absent, in_table = [], []
    # Several charts of one template at exactly 00:00:00 are the default, not
    # midnight: 00278's 60 STEP charts print no clock and carry their day and
    # 00:00:00, and "overlapped" each other 54 times where the Lab, which
    # reads 00:00:00 as no clock, flags none. One chart at midnight is a
    # midnight (00015's stage 4, above).
    zero = [st for st in stages if str(_meta(st, "start_time") or "") == "00:00:00"
            and not _meta(st, "clock_chart")]
    default = {id(st) for st in zero} if len(zero) > 1 else set()
    for st in order:
        t = None if id(st) in default else _start(st)
        if t is None:
            absent.append(st)
            printed = st.get("clock_printed")
            row = table.get(stage_num(_stage_label(st)))
            if row:
                in_table.append(st)
                out.append(_f("clock.in-table", WARN, st, None,
                              f"the report's stage table prints start {row} for this stage; "
                              f"the chart carries {_meta(st, 'start_time')!r}",
                              "a join never made — the table's clock, with its day and "
                              "AM/PM resolved, belongs on the chart"))
            else:
                out.append(_f("clock.absent", WARN if printed else INFO, st, None,
                              f"date {_meta(st, 'date')!r}, start {_meta(st, 'start_time')!r}"
                              + (f" — the page prints a clock axis, {printed}" if printed else ""),
                              "the reader did not take the clock this page prints" if printed else
                              "no clock on this chart; the CSV will date it from the default"))
            continue
        if prev and stage_num(prev[2]) != stage_num(_stage_label(st)):
            pt, pdur, plabel, pst = prev
            if t < pt:
                out.append(_f("clock.backwards", WARN, st, None,
                              f"starts {t:%Y-%m-%d %H:%M:%S}, before stage {plabel} "
                              f"({pt:%Y-%m-%d %H:%M:%S})",
                              "a misread date or a lost PM — the Fix time button, or the reader"))
            # The Lab's own rule (index.html OVERLAP_FRAC / OVERLAP_FLOOR_MS):
            # a chart window a few minutes wider than its stage is not an
            # overlap — 00015's windows run 4-10 min past the table's
            # durations on every stage — a stage starting more than 35% of
            # its own length, and at least fifteen minutes, inside the one
            # before it is.
            elif t < pt + timedelta(minutes=pdur) - timedelta(
                    seconds=max(OVERLAP_FLOOR_S,
                                OVERLAP_FRAC * 60.0 * float(_meta(st, "duration_min") or 0.0))):
                over = (pt + timedelta(minutes=pdur) - t).total_seconds() / 60.0
                cause = _overlap_cause(over, st, t, pst, pt, table)
                out.append(_f("clock.overlap", WARN, st, None,
                              f"starts {t:%H:%M:%S}, {over:.0f} min before stage {plabel} finished"
                              + (f" — likely {cause}" if cause else ""),
                              "one of the two clocks is wrong, or the stages genuinely overlap",
                              cause=cause or ""))
            # Shorter than that is still drawn twice by FracView (#645: every
            # 00041 chart ran 4-10 min into the next). The pipeline now hands
            # a tail over to the next chart where the two agree, so what is
            # left at this size is a pair that disagrees, or a clock a few
            # minutes off — worth a line, not an alarm.
            elif t < pt + timedelta(minutes=pdur) - timedelta(seconds=60):
                out.append(_f("clock.overlap", INFO, st, None,
                              f"starts {t:%H:%M:%S}, {(pt + timedelta(minutes=pdur) - t).seconds / 60:.1f} "
                              f"min before stage {plabel} finished",
                              "a short overlap the hand-over pass left: the two charts "
                              "disagree over those minutes, or one clock is minutes off"))
        prev = (t, float(_meta(st, "duration_min") or 0.0), _stage_label(st), st)
    # Every stage of a template without a clock is one finding about the
    # template, not N about the charts: either its charts plot elapsed
    # minutes (00020 — the daily report is the source, see HANDOFF) or the
    # reader misses this layout's time axis (00015, #639).
    if len(stages) >= 3 and len(absent) == len(stages):
        printed = sum(1 for st in absent if st.get("clock_printed"))
        checked = any("clock_printed" in st for st in absent)
        src = stages[0].get("source", "")
        if in_table:
            where = (f"; the report's stage table prints a start for {len(in_table)} of them "
                     f"({', '.join(table[stage_num(_stage_label(st))] for st in in_table[:4])}"
                     + (" …" if len(in_table) > 4 else "") + ")")
            action = ("join the table's clock to the charts — mind the 12-hour times without "
                      "AM/PM and the job's day count (#588)")
        elif printed:
            where = f"; {printed} of them print a clock axis on the page"
            action = "the reader misses this layout's time axis — read the page"
        elif checked:
            where = ("; the pages' text layer prints no clock axis (a raster chart carries "
                     "its axis in the image, which only OCR can read)")
            action = "elapsed-minute charts, or a clock axis drawn as pixels — look at the page"
        else:
            where = "; whether the pages print one is not known without the PDF"
            action = "elapsed-minute charts: the operator's daily report is the source (HANDOFF)"
        out.append(_f("clock.none", WARN, None, None,
                      f"0 of {len(stages)} {src} stages carry a date or a start time" + where,
                      action, source=src, printed=printed, in_table=len(in_table)))
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


def audit_stages(stages, notes=None, tables=None):
    findings, coverage = [], {}
    for st in stages:
        sec = float(st.get("sample_sec") or 1.0)
        spk = []
        for ch in st.get("channels", []):
            f, cov = gap_findings(st, ch, sec)
            findings += f
            coverage[f"{_stage_label(st)}|{ch['key']}"] = cov
            findings += flat_rule(st, ch)
            spk += spikes(st, ch, sec)
            findings += peak_checks(st, ch, sec)
        findings += spk
        findings += aligned_spikes(st, spk, sec)
        findings += pair_disagree(st)
    findings += presence(stages)
    # One warning per problem. A channel that has already warned at its own
    # level — sparse, the hold shape, the pair — has its gaps as evidence,
    # not as more warnings. gap_findings handles the first two; the pair
    # findings are only known now.
    warned = {(f["stage"], f["channel"]) for f in findings
              if f["severity"] == WARN and f["kind"] in CHANNEL_LEVEL}
    for f in findings:
        if f["kind"] == "gap.missing" and f["severity"] == WARN and (f["stage"], f["channel"]) in warned:
            f["severity"] = INFO
    lad, ladder_info = ladder(stages, notes, tables)
    findings += lad
    findings += clocks(stages, tables)
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
    stages, tables, notes, summary = localapp.serialize(results, notes)
    clock_hints(stages, doc)
    doc.close()
    return {"file": os.path.basename(path), "npages": npages,
            "seconds": round(time.time() - t0, 1), "stages": stages,
            # rows kept: the stage tables are the report's own printed
            # numbers, and a clock or a peak printed there and absent from
            # the chart is a finding only the rows can make
            "tables": tables,
            "notes": notes}


def clock_hints(stages, doc):
    """What the page prints that the reader may not have taken. Only the
    clock for now: 00015 (#639) prints "Clock Time (hour:min)" 18:30-19:32
    over every chart and exported 00:00:00 for all of them. The payload
    alone cannot tell that blank from an elapsed-minute chart; the page can."""
    texts = {}
    for st in stages:
        pg = st.get("page")
        if pg and pg not in texts and 1 <= pg <= len(doc):
            texts[pg] = doc[pg - 1].get_text()
        st["clock_printed"] = _clock_hint(texts.get(pg, ""))


_HHMM = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")


def _clock_hint(text):
    """'18:30–19:32' if the page prints a wall-clock axis, else ''."""
    ticks = _HHMM.findall(text) and [m.group(0) for m in _HHMM.finditer(text)]
    if re.search(r"clock\s*time", text, re.I) or (ticks and len(ticks) >= 3):
        return f"{ticks[0]}–{ticks[-1]}" if ticks else "a clock axis"
    return ""


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
    res = audit_stages(payload["stages"], payload.get("notes"), payload.get("tables"))
    print(report(payload, res, show_matrix="--matrix" in argv))
    if "--json" in argv:
        out = argv[argv.index("--json") + 1]
        json.dump({"file": payload.get("file"), **res}, open(out, "w"), indent=1)
        print(f"\nfindings → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
