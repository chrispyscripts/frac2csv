# Frac2CSV

Desktop tool that converts frac-stage chart PDFs (MView-style vector charts)
into 1-second CSV time series — one CSV per stage page.

## Download (Windows)

Grab `Frac2CSV.exe` from the [latest release](../../releases/latest).
No install needed — double-click to run. Windows SmartScreen may warn on
first launch (unsigned binary): click **More info → Run anyway**.

## Use

1. **Add PDFs…** — pick frac chart PDFs and/or images (PNG/JPG/TIFF).
   Multi-page PDFs are fine; each page is treated as one stage.
2. **Extract All** — a CSV is written next to each input file
   (`<name>-stage-<n>.csv`), and the last page is drawn in the preview pane.

The app detects what it's fed and says so in the log:

- **Vector chart PDF** (native MView output) — curves are read straight from
  the PDF's line geometry. Near-lossless: validated at ≤0.5% full-scale RMSE.
  UWI, stage, date, duration and all axis scales are auto-detected from the
  page text.
- **Raster input** (flattened/scanned PDF page, or a PNG/JPG image) — curves
  are pixel-traced by color. Lower fidelity by nature. If the page has no
  readable labels, the *raster fallback* fields in the toolbar supply the
  duration, axis scales, UWI/stage/date.

### Raster caveat — read this before trusting scanned inputs

A raster chart is just pixels on a shared canvas, so information is
genuinely missing wherever curves cross or ride on top of each other — the
top-drawn series hides the ones beneath. Frac2CSV does not hide this: for
every raster extraction the log lists, per channel, the exact timeframes
that are **interpolated estimates** (curve unreadable/occluded) or **less
reliable** (two curves overlapping within a line-width). Steep transitions
also smear by a few seconds due to line thickness. Typical accuracy is
1–3% of full scale on clean renders, worse where overlaps are sustained —
use vector PDFs whenever they exist.

Try it: `examples/example-flattened-chart.png` is a flattened render of the
validation chart — extract it and compare the caveats against the same
stage extracted from a vector PDF.

## Output format

```
UWI, STAGE, DATETIME, ELAPSED, TIMESTAMP, LABEL,
Tr Press (MPa), Slurry Rate (m3/Min), WH Prop Conc (Kg/m3), BH Prop Conc (Kg/m3)
```

Sampled at 1 s by default (80-minute stage → 4,800 rows; interval is
adjustable in the toolbar). Samples after the recorded data ends are left
blank, not extrapolated. `TIMESTAMP` is the local-time epoch of `DATETIME`.

## How it works

These chart PDFs are vector graphics: every curve is stored as thousands of
colored line segments. Frac2CSV reads that geometry directly (no OCR, no
pixel tracing), calibrates it against the plot frame and axis tick labels,
and resamples each channel onto an exact 1-second grid.

Validated against a known-good CSV export: worst-channel RMSE ≈ 0.5% of full
scale, per-channel correlation ≥ 0.9996.

## Run from source

```
pip install pymupdf numpy
python frac2csv_gui.py
```

Works on Windows, macOS and Linux (Python 3.10+).
