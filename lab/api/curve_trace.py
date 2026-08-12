"""Read one plotted curve out of a colour mask, column by column.

Every raster template — STEP, BJ-1, Hal-1 — reduces a masked chart image to a
series the same way: for each pixel column, decide where the curve sits. That
step used to be

    py[cx] = np.median(rows_where_mask_is_set)

which is only right when the mask holds the curve and nothing else. Three
separate defects traced back to it:

  * narrow notches plunging toward zero — a gridline, tick label or frame
    caught by the mask in one column drags the median off the stroke for the
    width of that feature (00183, 00244);
  * flat invented data — the caller's np.interp had no left/right, so numpy
    clamped to the edge value and the export carried a straight line across
    parts of the chart with no ink at all;
  * an earlier attempted fix that tracked "the run nearest the previous
    column" collapsed whole traces, because it seeded on column 0 — usually
    the frame — and continuity then held it there for the rest of the chart.

The approach here avoids all three. A column is split into contiguous runs of
set pixels; a curve is a short run, a gridline is a tall one. Columns holding
exactly one plausible run are unambiguous, and they alone define a reference
track. Only then are the ambiguous columns resolved, each against that
reference. Nothing is chosen sequentially, so there is no seed to get wrong and
no drift; and columns with no ink stay blank instead of being filled in.
"""
import numpy as np

# A stroke is a few pixels thick. Anything covering this much of the plot
# height in a single column is structure — a gridline, an axis, a frame edge —
# not a reading.
TALL_FRAC = 0.12
# Below this many unambiguous columns there is no reliable reference to
# resolve the rest against, and guessing would be worse than the old
# behaviour, so the caller is told to fall back.
MIN_ANCHORS = 12


def _runs(rows):
    """Contiguous pixel runs in one column -> [(centre, length)]."""
    if not len(rows):
        return []
    breaks = np.where(np.diff(rows) > 1)[0]
    return [(float(r.mean()), len(r)) for r in np.split(rows, breaks + 1)]


def column_track(sub):
    """Mask of the plot area -> per-column curve row, NaN where there is none.

    `sub` is the boolean mask cropped to the plot rect, rows top-down. The
    returned array is in the same row coordinates, one entry per column.
    """
    n_cols = sub.shape[1]
    tall = max(3.0, TALL_FRAC * sub.shape[0])
    per_col = [_runs(np.where(sub[:, cx])[0]) for cx in range(n_cols)]

    # Short runs are candidate strokes. A column with exactly one of them says
    # where the curve is without needing any context, and those are what the
    # reference is built from — never a column that only holds structure.
    short = [[r for r in runs if r[1] <= tall] for runs in per_col]
    anchor = np.full(n_cols, np.nan)
    for cx, cands in enumerate(short):
        if len(cands) == 1:
            anchor[cx] = cands[0][0]

    known = np.where(np.isfinite(anchor))[0]
    if len(known) < MIN_ANCHORS:
        return None                     # caller falls back

    # Reference across the whole width, from the unambiguous columns only.
    ref = np.interp(np.arange(n_cols), known, anchor[known])

    out = np.full(n_cols, np.nan)
    for cx in range(n_cols):
        # Deliberately NO fallback to the tall runs. Where a gridline crosses
        # the curve the two merge into one full-height run, and its centre is
        # nowhere near the reading — that centre IS the notch. Leaving the
        # column blank is honest, and since such columns are one or two wide
        # the resample below bridges them; the same is true of a genuine
        # near-vertical move, which bridges to the vertical it actually was.
        cands = short[cx]
        if not cands:
            continue                    # no usable ink here — stays blank
        if len(cands) == 1:
            out[cx] = cands[0][0]
        else:
            # Several strokes in one column: the curve is the one nearest
            # where the unambiguous neighbours say it should be. A tie on
            # distance goes to the longer run.
            out[cx] = min(cands, key=lambda r: (abs(r[0] - ref[cx]), -r[1]))[0]
    return out


def resample(samples, t_cols, vals, gap_factor=6.0, min_gap_s=20.0):
    """Curve columns -> the sample grid, WITHOUT inventing anything.

    np.interp on its own extends the first and last value forever and draws a
    straight line across any hole. Both are fabrications: the chart simply has
    no ink there, and a report must say so rather than show a plausible flat
    line. Outside the measured span, and across any gap much wider than the
    normal column spacing, the result is NaN — which the exporter writes as an
    empty cell.
    """
    ok = np.isfinite(vals)
    if ok.sum() < 2:
        return np.full(len(samples), np.nan)
    t, v = np.asarray(t_cols)[ok], np.asarray(vals)[ok]
    order = np.argsort(t, kind="stable")
    t, v = t[order], v[order]
    out = np.interp(samples, t, v, left=np.nan, right=np.nan)
    if len(t) > 2:
        step = float(np.median(np.diff(t)))
        limit = max(min_gap_s, gap_factor * step)
        for i in np.where(np.diff(t) > limit)[0]:
            out[(samples > t[i]) & (samples < t[i + 1])] = np.nan
    return out
