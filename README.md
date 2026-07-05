# Frac2CSV

Desktop tool that converts frac-stage chart PDFs (MView-style vector charts)
into 1-second CSV time series — one CSV per stage page.

## Download (Windows)

Grab `Frac2CSV.exe` from the [latest release](../../releases/latest).
No install needed — double-click to run. Windows SmartScreen may warn on
first launch (unsigned binary): click **More info → Run anyway**.

## Use

1. **Add PDFs…** — pick one or more frac chart PDFs (multi-page is fine;
   each page is treated as one stage).
2. **Extract All** — a CSV is written next to each PDF
   (`<name>-stage-<n>.csv`), and the last page is drawn in the preview pane.

Everything is auto-detected from each page: UWI (from the chart title),
stage/zone number, date, stage duration, and the axis scales for pressure,
rate and concentration. Detection issues show up as warnings in the log.

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
