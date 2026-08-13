# Frac2CSV — session handoff

Rewritten 2026-08-13. Repo: `frac-pdf-extract/frac2csv` (the git repo is that
directory, **not** the parent). Shipped: **v0.9.10**, tagged and building as a
Windows EXE, notes live on the download page.

## Read this first

Two rules earned the hard way, and both caught real defects again tonight:

1. **Verify against the report's own printed numbers**, or against BCER's
   filing — never against the parser's output.
2. **A confident diagnosis is usually partly wrong.** The Trican conc fix
   below is the clean example: the previous session found a genuine 32% gap in
   the colour rules, fixed it, and the channel barely moved. The real cause was
   somewhere else entirely. Measure the thing you are about to blame, and
   measure it again after the fix.

A corollary worth its own line: **check your harness before you trust its
result.** The first before/after run this session reported "no change on every
channel" because the harness unpacked four return values as three and silently
recorded 103 errors. The number that looks like a null result is often a bug in
how you measured.

## In flight right now

Nothing is running. The CalFrac corpus pass that was live at the last handoff
finished; its result is in the v0.9.10 numbers below.

## Two drives, and they drop

- `/Volumes/For-Chris-CnC-1TB/BCER-Frac/` — original corpus, 1451 folders,
  `<index>-<uwi>_<wa>/` each holding a PDF. **Not mounted as of this writing.**
- `/Volumes/CNC2X1TB/BCER-Frac/Spud-2019-2023/` — Carmine's newer set,
  **pre-sorted by provider** into `__CALFRAC` (120), `__HAL` (56),
  `__SCHLUM` (199), `__STEP` (51), `__TRICAN` (192), plus 618 loose PDFs.

Both have disconnected mid-run and killed agents. **Always copy the PDFs you
need to scratchpad first.** `00374` on the old drive is truncated to 49 KB and
will throw — it needs re-copying from source. Note the two drives use different
index schemes, so a file number in a client report may not exist on the drive
you have mounted.

## Preserved off-drive, outside the repo

- `frac-pdf-extract/carmine-notes/` — Carmine's own hand-written corpus notes
  (five per-provider files plus screenshots): the SCHLUM date-sourcing cascade,
  casing-test exclusions, the `x10`/`x5` slurry multipliers, and 20 open `??`
  questions. **This is the client's spec.** Read it before extracting from his
  set — it may already say what he expects to see. Deliberately outside the git
  repo, because `frac2csv` is public and this is client data.
- `frac-pdf-extract/validation-tools/` — `validate_step.py` (scores extraction
  against BCER's filing), `capcheck.py`, `smooth.py`, `regress.py`,
  `steprepro.py`, `gapaudit.py`, `logoprobe.py`, `glyphproto.py`. These encode
  the measurement methods behind the fixes; recreating them means re-deriving
  the approach.

## Deploy targets — "shipped" means the EXE

The client uses the EXE and nothing else. A release is the `version.py` bump,
the `v*` tag that builds it, and the download page that serves it.
**`version.py` must match the tag** — its own docstring says so, and skipping
it shipped v0.9.2 reporting itself as 0.9.1. The version string is embedded in
every Flag Error report, so a stale one sends diagnosis after the wrong build.

Local testing is `python3 localapp.py` in `frac2csv/`.

### The hosted Lab is retired (2026-08-12)

Client: "Let's stop using the vercel app altogether and stick to running only
the local version to stay consistent with the EXE."

**Do not deploy `carmines-lab` again.** `lab/api/version.py` says **0.9.5** and
its module set is well behind the root, so it would serve stale results.
`lab/public/index.html` and `stacked.html` are STILL the live UI — the local app
serves them; retiring the deployment does not retire those files. The download
page (`frac2csv-download`) is unaffected and still ships.

## Where the client's reports come from

Flag Error posts to GitHub issues: `gh issue list --repo chrispyscripts/frac2csv`.
Each body carries provider / file / chart / stage / pdfPage / version plus a
per-channel table of unit, axis and peak — **that channel table is the best
diagnostic in the project.** A peak outside its own axis means something not on
the curve is being read as data; that observation cracked both the Halliburton
IFS and Hal-1 clusters.

**Issues are a running log, not a to-do state.** Nothing is closed except the
early test issues, and several open ones (#100, #102, #110) are Carmine saying
something *works*. Read the body before treating a number as a defect.

## Landed in v0.9.10

- **Trican conc at zero (#105, #109).** `extract_image` cropped the plot as
  `[y0+1:y1]`, and a conc curve resting at zero is drawn ON the bottom frame
  line: the pen is 2px, the black frame is painted over `y1`, and the only
  surviving green sat in the one row the crop excluded. Every blank column was
  a column where the chart drew zero — the pad at the start of a stage and the
  flush at the end, which is why the blanks came in two contiguous runs. Now
  reads one row past the frame and clamps it back on. Corpus-wide over 103
  layout-A chart pages, 22,262 of 23,311 blank columns (95.5%) had ink there.
  **DH Prop Conc 29.1% → 1.7% blank; WH Prop Conc 51.2% → 41.2%.** Pressure and
  rate are bit-identical (0 peaks moved) — measured, not assumed: those three
  series have zero masked pixels on every row from `y1` to `y1+4`.
- **Trican green partition (#105, #109).** The two conc curves were split by two
  independent threshold rules with a gap between them; 32% of green ink matched
  neither. Now a partition. A real fix, but it was not the main cause.
- **CalFrac job dates (#98).** A well prints its Multiple-Zone summary as a RUN
  of sheets carrying different days; reading the nearest sheet before a chart
  handed the first chart the LAST sheet's day. Now picks the sheet whose zone
  columns actually hold the chart's first zone. Paired over 242 keyed files
  against BCER: **stages dated exactly right 58.2% → 71.7%**, off-by-one
  1,598 → 1,131, other 676 → 432, and stages matched went *up* (5,437 → 5,514),
  so nothing was dropped to get there.
- **CalFrac stage separation (#101).** Pages that over-segment now split using
  the printed zone start times to choose among boundaries the pumping data
  proposed.
- **Stacked window sync.** The link is a loop now — seq + ack, with the child
  asking on load, on focus, and on a slow tick. Recovers a reloaded Lab (937 ms)
  and a dropped push (103 ms).
- **Full page ghost (#78-adjacent).** The panel and the graph's backdrop were
  sharing one buffer, so Full page blanked the ghost. Two buffers now.
- **SLB Zone Summary geometry (#95).** The call site filed every SLB chart with
  no geometry, so Compare Original fitted the whole sheet, tables and all.

## Open, highest value first

- **Trican WH Prop Conc, 41% blank.** Improved but not resolved, and the
  remainder has **two** causes, not one. Of 39,194 columns still carrying no WH
  ink: 50.6% have DH sitting on the shared zero row, so the two curves coincide
  and the partition hands the pixel to whichever colour was painted last; 46.7%
  have nothing drawn at zero at all, so WH is genuinely absent and why is not
  established; 2.7% hold no conc ink anywhere. Neither of the first two is
  recoverable from colour alone. **Do not assume the zero-row story explains all
  of it** — that is the mistake the last two attempts on this channel made.
- **Four client reports filed after the last session went quiet and never
  looked at**: #110 (Liberty, positive — "got our term summary data"),
  #111 (STEP raster, "do not try to get mainline 3 same colors as conc"),
  #112 (STEP raster 00349, "missing data"), #113 (BJ list-load export reports
  success and writes the CSVs nowhere — Carmine explicitly says this is low
  priority, and drag-and-drop works).
- **#104** — extracted data not being assigned to "our terms". Alias-table work;
  `alias_table.txt` is 104 lines and has a Trican section as of v0.9.9.
- **#69** — STEP uneven axis spacing (cancelled mid-run when a drive was
  swapped; no code changed).
- **#72** — STEP rate read off an `L/min` axis instead of `m3/min`, ~2.5x out.
- **Three unverified table-parser drafts, still uncommitted and untracked**:
  `trican_b.py` and `bj_wellops.py` sit in the working tree unstaged. They are
  not in any build. Decide whether to finish or delete them.
- **#73** — the Alberta `AB_WCF` file is not on any drive. Ask Carmine for it.

## Two things measured and settled — do not re-litigate

- **Trican gridlines are not a defect.** Carmine suggested removing the
  horizontal grid lines. They are pure neutral grey `(211,211,211)`, zero
  saturation, so no colour family in our tracer can match them. That step is
  what his own PNGViewer digitizer needs, not ours.
- **00183's "missing slurry" is NOT a bug.** The gap columns contain zero cyan
  pixels; the chart lifts its pen while the pumps are off. An honest gap and a
  parser failure look identical in the Lab — *that* is the real defect, and a
  per-channel note ("4 gaps totalling 12.8 min where the chart draws no curve")
  would have prevented the client report. The same shape explains the Trican
  conc blanks above, which is why it was worth checking whether the ink existed
  before concluding the pen was up.
