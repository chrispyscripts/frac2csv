"""Frac2CSV raster core: pixel-trace frac chart curves from images.

Fallback path for flattened/scanned charts (PNG, JPG, or PDF pages whose
curves are raster images rather than vector strokes). Works in display
orientation: time along x, values along y, all axes zero-based spanning the
plot frame.

Raster extraction is inherently lower fidelity than vector extraction:
where curves overlap, the top-drawn series hides the ones beneath it, and
line thickness smears steep transitions. Occluded/unreadable spans are
bridged by interpolation and reported per channel so the caveat travels
with the output.
"""
from dataclasses import dataclass, field

import numpy as np

# display RGB -> (csv column, axis kind); matches MView series colors
RASTER_SERIES = {
    (0, 0, 255):   ("Tr Press", "pressure"),
    (255, 0, 0):   ("Slurry Rate", "rate"),
    (0, 128, 0):   ("WH Prop Conc", "conc"),
    (128, 0, 128): ("BH Prop Conc", "conc"),
}
COLOR_TOL2 = 80 ** 2  # squared RGB distance tolerance (antialias/scan shift)


def _fmt_span(a, b):
    return (f"{int(a // 60):02d}:{int(a % 60):02d}"
            f"-{int(b // 60):02d}:{int(b % 60):02d}")


@dataclass
class ChannelQuality:
    coverage_pct: float = 100.0
    gaps: list = field(default_factory=list)      # (start_sec, end_sec) missing, interpolated
    overlaps: list = field(default_factory=list)  # (start_sec, end_sec, other_name)

    def caveats(self):
        out = []
        if self.gaps:
            total = sum(b - a for a, b in self.gaps)
            a, b = max(self.gaps, key=lambda g: g[1] - g[0])
            out.append(f"{len(self.gaps)} unreadable span(s) totaling {total:.0f}s "
                       f"(longest {_fmt_span(a, b)}) - interpolated estimates")
        if self.overlaps:
            total = sum(b - a for a, b, _ in self.overlaps)
            a, b, other = max(self.overlaps, key=lambda g: g[1] - g[0])
            others = ", ".join(sorted({o for _, _, o in self.overlaps}))
            out.append(f"overlaps {others} for {total:.0f}s total "
                       f"(longest {_fmt_span(a, b)}) - values there are less reliable")
        return out


def find_frame_px(img):
    """Plot frame = extent of long dark runs. img: HxWx3 uint8 array."""
    dark = img.sum(axis=2) < 180
    H, W = dark.shape
    rows = np.where(dark.sum(axis=1) > 0.55 * W)[0]
    cols = np.where(dark.sum(axis=0) > 0.55 * H)[0]
    if not len(rows) or not len(cols):
        raise ValueError("plot frame not found in image (needs a solid chart border)")
    return cols.min(), rows.min(), cols.max(), rows.max()  # x0, y0, x1, y1


def trace(img, duration_min, fullscale, sample_sec=1.0, min_gap_sec=2.0,
          min_overlap_sec=10.0):
    """Pixel-trace all series. Returns ({col: values}, {col: ChannelQuality}).

    img: HxWx3 uint8; fullscale: {"pressure": v, "rate": v, "conc": v}.
    """
    x0, y0, x1, y1 = find_frame_px(img)
    inner = img[y0 + 2:y1 - 1, x0 + 2:x1 - 1].astype(int)
    n_cols = inner.shape[1]
    sec_per_px = duration_min * 60.0 / (x1 - x0)

    n = int(round(duration_min * 60 / sample_sec))
    samples = np.arange(n) * sample_sec

    data, quality = {}, {}
    traced_py = {}   # per-series pixel-y per column, for overlap detection
    widths = {}
    for rgb, (name, kind) in RASTER_SERIES.items():
        fs = fullscale.get(kind, 0)
        if fs <= 0:
            continue
        dist2 = ((inner - np.array(rgb)) ** 2).sum(axis=2)
        mask = dist2 < COLOR_TOL2
        col_has = mask.any(axis=0)
        if not col_has.any():
            continue
        # per-column value: median y of matching pixels (robust at steep steps)
        vals = np.full(n_cols, np.nan)
        py = np.full(n_cols, np.nan)
        px_counts = []
        for cx in np.where(col_has)[0]:
            ys = np.where(mask[:, cx])[0]
            py[cx] = np.median(ys)
            px_counts.append(len(ys))
            y_mid = py[cx] + y0 + 2
            vals[cx] = (y1 - y_mid) / (y1 - y0) * fs
        traced_py[name] = py
        widths[name] = float(np.median(px_counts))

        t_px = (np.arange(n_cols) + 2) * (duration_min * 60.0) / (x1 - x0)
        have = ~np.isnan(vals)
        first, last = np.argmax(have), n_cols - 1 - np.argmax(have[::-1])

        # gap report (occlusion / unreadable spans inside the data range)
        q = ChannelQuality()
        in_range = have[first:last + 1]
        q.coverage_pct = 100.0 * in_range.mean()
        run_start = None
        for i in range(first, last + 2):
            missing = i <= last and not have[i]
            if missing and run_start is None:
                run_start = i
            elif not missing and run_start is not None:
                a, b = t_px[run_start], t_px[i - 1] + sec_per_px
                if b - a >= min_gap_sec:
                    q.gaps.append((a, b))
                run_start = None

        v = np.interp(samples, t_px[have], vals[have])
        v[samples < t_px[first]] = vals[have][0]          # backfill leading flatline
        v[samples > t_px[last] + sec_per_px] = np.nan     # blank after data ends
        data[name] = v
        quality[name] = q

    # overlap detection: spans where two traced curves share pixel rows
    t_all = (np.arange(n_cols) + 2) * (duration_min * 60.0) / (x1 - x0)
    names = list(traced_py)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            near = (np.abs(traced_py[a] - traced_py[b]) <
                    0.75 * (widths[a] + widths[b]) + 1.0)
            near &= ~np.isnan(traced_py[a]) & ~np.isnan(traced_py[b])
            run_start = None
            for k in range(n_cols + 1):
                hit = k < n_cols and near[k]
                if hit and run_start is None:
                    run_start = k
                elif not hit and run_start is not None:
                    s, e = t_all[run_start], t_all[k - 1] + sec_per_px
                    if e - s >= min_overlap_sec:
                        quality[a].overlaps.append((s, e, b))
                        quality[b].overlaps.append((s, e, a))
                    run_start = None

    if not data:
        raise ValueError("no series curves found in image (expected MView colors)")
    return samples, data, quality


def pixmap_to_array(pix):
    """fitz.Pixmap -> HxWx3 uint8 numpy array."""
    import fitz
    if pix.alpha or pix.colorspace.n != 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    return arr.copy()
