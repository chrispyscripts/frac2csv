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

- **THE 2025 FILINGS: THREE DIFFERENT PROBLEMS, not one.** An earlier version
  of this file said "33 have NO detector firing at all... one document class
  explains most of the backlog". That was wrong, and it was wrong in the way
  that matters: it would have sent the next session hunting for one new
  template. Measured properly over all 42 reported 2025 filings present on a
  drive (thanks to the parallel Liberty session, which had the files open):
  - **4 files (01103-01106): lib1 DID fire**, on 72-86 pages each, then failed
    with "no curves matched" — their curves are FILLED ribbons, not strokes.
    **Fixed in v1.0.0.**
  - **2 files (01397/01398): "STG 1" not "Stage 1"**, so detect never fired.
    **Fixed in v1.0.0.** Those six together went from 0 to 568/568 chart pages
    and 1,939,562 samples.
  - **27 files: NO TEXT LAYER AT ALL** — 2-3 text pages out of 150-330, every
    label converted to vector outlines (01116 p222 is a BJ chart drawn that
    way). **No text-based detector can ever fire on these.** They need OCR of
    the axis and legend text. THIS is the big remaining group and it is a
    different problem from the other two.
  - 7 files (00944, 01137-01142): partial text layer, ~62 of 400 pages, STEP
    marker present.
  - 2 files (01078/01079): Trican/STEP/Canyon/Hal markers, not Liberty.
  Only 56 of the 208 open "No extractable data" reports are on either mounted
  drive; the other 152 are all 2021/2022 filings on the drive Carmine has yet
  to send (~1000 more files coming).
  - Do NOT cross-reference reports to files by the 5-digit index. The two
    drives use DIFFERENT index schemes and the same number means different
    wells — matching that way produced a confident, entirely wrong Liberty/BJ
    classification. Match on the full filename.
- **Tell Carmine to re-export affected Liberty wells.** Builds before v1.0.0
  exported Hydr Pressure at ~4.5x true and PFR-ZC FR CONC at half, on files
  including 00374 — the one he reports as WORKING in #110. Shapes right, scale
  wrong.
- **#112 — STEP 00349 p138, Btm Prop Conc 37.9% blank. Diagnosed, NOT fixed,
  and one attempt has already been backed out.** Reproduced exactly (the
  report's peaks 76.08 / 660.99 / 685.76 / 10.49 / 4.80 all match). What is
  measured:
    - It is **not** the Trican under-the-frame defect. Of the blank columns,
      36.5% have no orange ink anywhere and only 1.2% are dropped by the
      tracer, and the rows at and below the frame hold 0, 3 and 0 pixels.
    - The gaps are 5 runs: four of 4-6 columns sitting on the proppant ramp's
      step risers, one of 54 columns mid-chart, one of 55 running to the
      chart's end.
    - In the 54-column band, green (Prop Conc) occupies orange's own row band
      — 463 px across rows 440..470 — while orange enters at row 456 and
      leaves at 451.5. Green sits at ~451 through most of the band and then
      plunges to 643, and **orange reappears exactly where green leaves.**
      That is the signature of green being painted over orange.
    - But it does not explain the short gaps: at 39..44 and 85..88 green is
      11-16 rows off orange's level at the gap edges. At least two mechanisms
      are in play, which is the same trap as the Trican WH remainder.
  **The trap for the next attempt**, learned by walking into it: a guard that
  requires the donor curve to match the hidden one at BOTH edges of the gap
  can never fire on real occlusion, because the donor *leaving* is what makes
  the hidden curve reappear. Loosening it to a median-vs-midpoint test makes
  it fire 5/5 on this chart — and that test is too weak to be trusted, which
  is why the change was reverted rather than shipped. Filling a hidden curve
  from its neighbour invents data if the reasoning is wrong; this one needs a
  rule validated across the 51 STEP files, not one chart.
- **#111 — no code change wanted.** "do not try ti get mainline 3 same colors
  as cocn" is Carmine telling us NOT to chase Mainline 3 on STEP 00308,
  because it shares an ink with the conc traces. Leave it alone; do not let a
  future colour-splitting pass "fix" it into the concentration channel.
- **#110 — nothing to do.** Liberty 00374, and he is reporting that it works.
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
