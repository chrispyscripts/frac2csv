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

`slb.py` and `lab/api/slb.py` now exist and are UNCOMMITTED — that agent's
work, deliberately left alone by the session that landed 9811e8e/55462e6.
Its report is in the previous session's transcript, not in the task list.

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

## DECISION: the hosted Lab is retired (2026-08-12)

Client: "Let's stop using the vercel app altogether and stick to running only
the local version to stay consistent with the EXE."

**Do not deploy `carmines-lab` again.** The two runtimes that matter are the
Windows EXE and the local Mac app (`python3 localapp.py` in `frac2csv/`), and
both have tesseract, so both do raster/OCR. That kills the whole class of
"works in one place, not the other" confusion — a hosted engine seven releases
behind was the largest untreated risk in this project.

Consequences worth keeping in mind:
- No more `lab/api` sync burden. `lab/api/*.py` exists only to serve that
  deployment; it can stop being maintained, though leaving it in step costs
  little and keeps the option open.
- No more `raster_available()` fallbacks written for a platform with no
  tesseract. Build for raster and trace the real charts.
- `lab/public/index.html` and `stacked.html` are STILL the live UI — the local
  app serves them. Retiring the deployment does not retire those files.
- The download page (`frac2csv-download`) is unaffected and still ships.

The URL still resolves and Carmine may have it bookmarked. It now serves an
engine that will drift further from the EXE with every release, so if he uses
it he will file reports against data the desktop app would not produce.
**Decide whether to replace that page with a pointer to the download, rather
than leaving a stale tool live.**

## The hosted Lab is NOT the desktop engine (historical — now retired)

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

## Landed since this file was written (9811e8e, 55462e6)

Not yet deployed — no version bump, no tag, and `lab/api` is NOT synced, so
none of this is on carmines-lab.vercel.app yet.

- **#70 CLOCKS/DATES/SKEW.** Applied and measured over all 120 CalFrac files:
  stages exporting `00:00:00` **1,681 → 30** (165 left deliberately blank
  where the grid names no zone), 1,583 rows re-dated across 77 files, 3,303
  re-clocked across 117. Cross-page skew **27.1 s mean → 0** by construction.
  Verified against the printed grid page, not the parser. One regression the
  corpus run caught before commit: requiring a twin's cuts cost 00070 19 of
  its 24 stages, so a twin whose captioned page could not be split still
  splits on its own data.
- **#70 GHOST.** Proportional ink coverage instead of a 0/255 snap — the
  threshold was erasing 10.3% of the page's inked pixels (measured in the
  browser on 00304). The canvas-sizing half is NOT done; see the new task.
- **#67 SANJEL UWI.** Charts now leave `uwi` empty and report `banner_uwi`,
  so the filename UWI wins. 00013 and 00019 were exporting another well's
  UWI on every chart.
- **#66 IFS LETTERED INTERVALS.** Bigger than reported: the pipeline's own
  IFS gate matched bare digits and skips silently, so 00001's intervals 4A,
  4B, 5A, 5B, 6A, 6B produced **nothing at all** — 8 charts became 20, over
  10 intervals, validated against the report's printed Max Treating Pressure.
- **#65 CANYON.** All 32 chart pages of 00204 had NO interval number (2017
  layouts print a bare "#1"); 17 of 00009's 25 charts were dated to the job's
  first day. Both fixed, dates now taken from the printed TREATMENT INTERVAL
  SUMMARY, choosing between re-attempt rows by the chart's own clock.

## Open, highest value first

- **Deploy what landed.** `version.py` bump + `v*` tag + the `lab/api` sync
  below, or Carmine is running an EXE and a hosted Lab that predate all of it.
- **`lab/api` sync.** `lab/api/pipeline.py` and `lab/api/halliburton_ifs.py`
  are now stale against the root, and there is no `lab/api/sanjel.py` at all,
  so the hosted Lab has none of the fixes above. `lab/api/canyon_tables.py`
  and `lab/api/ifs_tables.py` were kept in step by hand. Part of the larger
  engine-drift problem, but do at least this much before any Lab deploy.
- **Lab canvases.** `#graph`/`#origgraph` carry `width="1120"` with CSS
  `width:100%`; measured at a 1600px window that is a 770px CSS box on a
  dpr-2 display, so the backing store is stretched over 1540 device pixels.
  The report's claim that the hit-testing "needs no change" is wrong if a
  compensating `setTransform` is added — pick one coordinate system and
  convert all ~20 uses of `cv.width` as a logical width, plus GP margins and
  every font size. `renderSynced` is the delicate one.
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
