# Frac2CSV — session handoff

Written 2026-08-12. Repo: `frac-pdf-extract/frac2csv` (the git repo is that
directory, **not** the parent). Shipped: **v0.9.4**, live on the download page
and built as a Windows EXE.

## Read this first

Two rules earned the hard way, and both caught real defects tonight:

1. **Verify against the report's own printed numbers**, never against the
   parser's output. Every wrong diagnosis this session survived until someone
   compared to the printed table.
2. **A confident diagnosis is usually partly wrong.** Of the briefs written
   this session, roughly half named the wrong cause. Agents that measured
   first found things nobody predicted — 25% of a document's rows silently
   missing, intervals past 99 dropped while the parse *looked* complete.

## In flight right now

**Schlumberger template** (task #64) — an agent is surveying
`/Volumes/CNC2X1TB/BCER-Frac/Spud-2019-2023/__SCHLUM/` (199 PDFs, 2018-2021).
Briefed to report the layout survey BEFORE building. Owns `slb.py` +
`lab/api/slb.py` only; reports the `pipeline.py` hook rather than applying it.
If it has already reported, its findings are the starting point.

## Two drives, and they drop

- `/Volumes/For-Chris-CnC-1TB/BCER-Frac/` — original corpus, 1451 folders,
  `<index>-<uwi>_<wa>/` each holding a PDF.
- `/Volumes/CNC2X1TB/BCER-Frac/Spud-2019-2023/` — Carmine's newer set,
  **pre-sorted by provider** into `__CALFRAC` (120), `__HAL` (56),
  `__SCHLUM` (199), `__STEP` (51), `__TRICAN` (192), plus 618 loose PDFs and
  his own notes file mapping files to providers.

Both have disconnected mid-run and killed agents. **Always copy the PDFs you
need to scratchpad first.** `00374` on the old drive is truncated to 49 KB and
will throw — it needs re-copying from source.

## Three deploy targets — "shipped" means all three

1. `frac2csv-download` → https://frac2csv-download.vercel.app (download page
   + `/data.html` coverage page)
2. `carmines-lab` → https://carmines-lab.vercel.app (the hosted Lab)
3. The Windows EXE, built by GitHub Actions on a `v*` tag

**`version.py` must be bumped to match the tag** — its own docstring says so,
and skipping it shipped v0.9.2 reporting itself as 0.9.1. The version string
is embedded in every Flag Error report, so a stale one sends diagnosis after
the wrong build.

## The hosted Lab is NOT the desktop engine

`lab/api/version.py` says **0.6.8**. `lab/api/` is missing `step1`, `hal1`,
`trican_charts`, `auto_raster`, `sanjel`, `calfrac_progress`, `step_vec`, and
its `pipeline.py` predates them. So on carmines-lab.vercel.app: **STEP,
Halliburton Hal-1, Trican charts and Sanjel produce nothing**, CalFrac
multi-zone charts do not split, and there is no OCR at all (the raster import
sits in a `try:` and fails silently to `_RASTER_OK = False`).

The UI there is current; the engine is not. **Fine for showing the interface,
unreliable for judging data.** Now that Carmine has the URL this is the most
likely way to mislead someone. Closing this drift is the largest piece of
unaddressed debt in the project.

## Where the client's reports come from

Flag Error posts to GitHub issues: `gh issue list --repo chrispyscripts/frac2csv`.
Each body carries provider / file / chart / stage / pdfPage / version plus a
per-channel table of unit, axis and peak — **that channel table is the best
diagnostic in the project.** A peak outside its own axis means something not
on the curve is being read as data; that single observation cracked both the
Halliburton IFS and Hal-1 clusters.

## Landed this session (all committed)

- **hal1**: concentration axis was fitted to 21.34-1490.30 instead of 0-1500
  because OCR read the page's time labels; axis furniture printed inside the
  plot frame was read as data on 92 of 97 pages. WH Prop Conc mean absolute
  error vs printed **92.1% → 6.9%**. Also proved display and CSV export are
  bit-identical — the "export bias" report was the axis fit.
- **frac_core**: `_resample` averaged the two vertices of a step into a
  mid-level point, corrupting both ends of every flat run. Mean ink error
  **1.008 → 0.004**. This was also why CalFrac stages would not separate:
  files failing **59% → 15%**.
- **halliburton_ifs**: legend key lines admitted as curve points (829.85 on an
  800 axis); event-marker numbers taken for a tick column. Charts with a
  channel over its own axis, corpus-wide: **40 → 0**.
- **step1**: two more layouts detected (they failed on wording — no `LSD:`
  table and U+00A0 spaces); near-vertical spikes were reported at their
  midpoint.
- **Lab UI**: stacked per-channel window (`stacked.html`) linked by
  postMessage, readout-size slider, larger axis labels, dates on the time
  axis, IMAGE tag on raster-traced stages, Full page, scroll-to-zoom
  everywhere, stable control row, collision-free curve colours.

## Open, highest value first

- **#70** — four `pipeline.py` changes reported and NOT applied (held back so
  concurrent agents could not clobber the file). Includes the CalFrac clock
  fix: **932 stages export 00:00:00 and the printed grid supplies a real start
  for 931 of them.** The client called this a common issue. All four were
  verified in simulation. Apply these.
- **#67** — `sanjel.py` stamps charts with the **wrong well's UWI**, live and
  shipping. The table side is already fixed; tables and curves now disagree.
- **#66, #65** — paired chart/table fixes that must land together or a join
  breaks.
- **#69** — STEP uneven axis spacing (client-reported, cancelled mid-run when
  a drive was swapped; no code changed).
- **#72** — STEP rate read off an `L/min` axis instead of `m3/min`, ~2.5x out.
- **#61, #54-#59, #63** — five table parsers **built and verified but never
  wired into `pipeline.py`** (STEP, Hal-1, Canyon, IFS, Sanjel), plus three
  unverified drafts (`trican_b`, `calfrac_legacy`, `bj_wellops`).
- **#73** — the Alberta `AB_WCF` file is not on any drive. Ask Carmine for it.

## Untouched by request

Carmine's new drive also holds a `NOTES-Copy-Spud2018-with-Charts-AERO-0001-D.txt`
mapping files to providers, with what look like his own review comments in it
(19 instances of `??`). Worth reading before extracting from that set — it may
already say what he expects to see.
