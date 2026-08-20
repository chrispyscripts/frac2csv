"""Where a channel has no data, why, and when it is safe to fill.

A traced curve comes back with gaps, and they are not one thing. Three times
this project has tried to fill them and backed the attempt out, because the
common case is not a failure to read:

  - 00183's "missing slurry" is the chart lifting its pen while the pumps are
    off. The gap columns hold zero cyan pixels. Nothing was lost.
  - Trican's WH Prop Conc: of 8,148 blank columns over 23 pages, 84% sit
    before the curve's first reading or after its last — the pad and the
    flush. Of the 66 mid-chart runs, exactly ONE had the curve at zero on
    both sides; filling the rest would have invented a concentration.
  - STEP #112: a guard that required the donor curve to match at both edges
    of the gap could never fire on real occlusion, and loosening it made it
    fire everywhere.

So the first job here is not filling. It is SAYING SO: "an honest gap and a
parser failure look identical in the Lab — that is the real defect". Every
function below reports before it repairs, and anything filled is reported as
filled.

The rule this implements: a gap is worth calling MISSING when the curve is
mid-flight on both sides of it — strictly off the axis floor and off full
scale. A curve resting at zero has its pen up legitimately; a curve pinned at
full scale is off-chart, not absent. Only a curve that was somewhere in
between and came back somewhere in between actually lost something.
"""

# How close to an axis end still counts as "at" it. A curve drawn AT zero
# reads a little above it — the pen has width and the frame line is painted
# over the bottom row, which is the whole of the Trican conc story — so an
# exact test would call a resting curve mid-flight and fill its pen-up gaps.
FLOOR = 0.02
CEIL = 0.98

LEAD = "lead"                 # before the first reading: the pen has not started
TRAIL = "trail"               # after the last: the flush
AT_FLOOR = "at-floor"         # resting at zero on both sides — pen legitimately up
AT_CEIL = "at-ceiling"        # pinned at full scale
MISSING = "missing"           # mid-flight both sides: something was lost
UNKNOWN = "unclassified"      # no axis to measure "off the floor" against


def _frac(value, axis):
    """value -> its position in the axis, 0..1, or None if unknowable."""
    if value is None or axis is None:
        return None
    lo, hi = min(axis), max(axis)
    if hi - lo <= 0:
        return None
    return (value - lo) / (hi - lo)


def find_gaps(values, axis=None, floor=FLOOR, ceil=CEIL):
    """-> [{'start','end','before','after','kind','n'}] for every run of None.

    `start`/`end` are inclusive indices into `values`. `before`/`after` are the
    readings bracketing the run, or None at the ends of the series. `axis` is
    (lo, hi) for this channel; without it a gap can still be found and located
    but never classified as MISSING, because "off the floor" has no meaning
    without a floor.
    """
    out = []
    n = len(values)
    i = 0
    first = next((k for k, v in enumerate(values) if v is not None), None)
    last = next((k for k in range(n - 1, -1, -1) if values[k] is not None), None)
    while i < n:
        if values[i] is not None:
            i += 1
            continue
        j = i
        while j + 1 < n and values[j + 1] is None:
            j += 1
        before = values[i - 1] if i > 0 else None
        after = values[j + 1] if j + 1 < n else None
        if first is None or i < first:
            kind = LEAD
        elif last is not None and j > last:
            kind = TRAIL
        else:
            fb, fa = _frac(before, axis), _frac(after, axis)
            if fb is None or fa is None:
                # Without an axis there is no floor to be off, so this gap is
                # neither shown to be a loss nor shown to be a rest. Saying
                # either would be a guess, and a guess here becomes a filled
                # value; interpolate() never touches this kind.
                kind = UNKNOWN
            elif fb <= floor and fa <= floor:
                kind = AT_FLOOR
            elif fb >= ceil and fa >= ceil:
                kind = AT_CEIL
            else:
                kind = MISSING
        out.append({"start": i, "end": j, "n": j - i + 1,
                    "before": before, "after": after, "kind": kind})
        i = j + 1
    return out


def interpolate(values, gaps, kinds=(MISSING,)):
    """Linear fill across gaps of the named kinds. -> (filled, indices).

    `indices` is every position this invented, so the caller can mark them.
    Nothing here is silent: a value that was not read is not the same as a
    value that was, and the export has to be able to tell them apart.
    """
    out = list(values)
    filled = []
    for g in gaps:
        if g["kind"] not in kinds:
            continue
        a, b = g["before"], g["after"]
        if a is None or b is None:
            continue                       # nothing to interpolate between
        span = g["n"] + 1
        for k in range(g["n"]):
            out[g["start"] + k] = a + (b - a) * (k + 1) / span
            filled.append(g["start"] + k)
    return out, filled


def summarise(gaps, sample_sec=1.0, kinds=(MISSING,)):
    """-> (count, minutes) over the named kinds."""
    hits = [g for g in gaps if g["kind"] in kinds]
    return len(hits), sum(g["n"] for g in hits) * sample_sec / 60.0


def note(channel, gaps, sample_sec=1.0):
    """The per-channel line the 00183 report should have carried, or ''.

    Says what is missing AND what is merely not drawn, because the client's
    question is always "is this a hole in your reader or a hole in the job".
    """
    n_missing, min_missing = summarise(gaps, sample_sec, (MISSING,))
    n_rest, min_rest = summarise(gaps, sample_sec, (AT_FLOOR, AT_CEIL))
    n_unk, min_unk = summarise(gaps, sample_sec, (UNKNOWN,))
    bits = []
    if n_missing:
        bits.append(f"{n_missing} gap(s) totalling {min_missing:.1f} min where "
                    f"the curve is mid-range on both sides — data is missing")
    if n_rest:
        bits.append(f"{n_rest} gap(s) totalling {min_rest:.1f} min where the "
                    f"chart draws no curve because the channel is at rest")
    if n_unk:
        bits.append(f"{n_unk} gap(s) totalling {min_unk:.1f} min that cannot "
                    f"be told apart, because this channel's axis was not read")
    return f"{channel}: {'; '.join(bits)}" if bits else ""
