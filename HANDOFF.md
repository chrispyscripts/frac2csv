# Frac2CSV — session handoff

Rewritten 2026-08-13, updated 2026-08-20. Repo: `frac-pdf-extract/frac2csv`
(the git repo is that directory, **not** the parent). Shipped: **v1.4.0**,
tagged and building as a Windows EXE, notes live on the download page.

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
result.** The first before/after run of the 2026-08-13 session reported "no
change on every channel" because the harness unpacked four return values as
three and silently recorded 103 errors. The number that looks like a null
result is often a bug in how you measured.

It happened twice more on 2026-08-20, both times producing a confident and
wrong answer:

- A probe measuring a fix REIMPLEMENTED the old code inline, so it could not
  see the change it was written to measure. Measure through the real call
  path, never through a copy of it.
- A before/after harness ran `git stash push` on an already-clean tree, so
  its "before" was the current code and the diff was empty. An IDENTICAL
  result is only meaningful if you have proved the two sides actually differ —
  check that the branch under test is even reached.

And one about agents: a subagent reported "89 files errored" as fact. The
rows said otherwise, because it had already retried them. **Read the data the
agent read** before repeating what it concluded.

## In flight right now

Nothing is running. Both jobs the last handoff listed have finished:
`providers.tsv` and `curvelen.tsv` each carry all 184 rows with no errors.
What they say is under "The pure-vector class" below, and curvelen's answer
is not the one it was built to give.

Three local app instances are still running and ALL of them predate the
2026-08-20 parser work. Cycle them before testing anything.

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

## Landed 2026-08-20, after v1.4.0 — NOT in any build yet

Four fixes, all pushed, none tagged. The client runs the EXE and the EXE is
still v1.4.0, so NONE of this has reached him.

- **A legend OCR'd a word at a time is read as whole labels (#582/#569,
  `bb30490`). 00121 went from 64 chart pages detected and ZERO extracted to
  64 of 64**, intervals 1-60. Everything else on the page already worked
  after fb6b1a3; only the legend failed, because OCR hands back a WORD at a
  time and "Treating Pressure" arrived as "Pressure", so `_classify` owned
  nothing and every colour on the chart went unclaimed. Two things make the
  join non-obvious and both are measured on p134: the legend is a single ROW
  (all five keys share cy 529.1, so "everything to the right" gives every key
  the same string — the bound is the NEXT key), and tesseract merges the
  swatch STROKE into the first word of its own label, which is what "—GORV",
  "—Prop" and "—BH" are, so the label starts LEFT of where the swatch ends.
  Overlap on the near side, centre on the far side.
  - Runs ONLY for pages whose labels came from OCR. 00011 is bit-identical:
    54 detected, 46 extracted, 230 peaks, none moved.
  - Supersedes the attempt backed out in fb6b1a3, which joined words globally
    in `_spans` and broke the time axis by joining the tick numbers too.
  - Verified against the RENDER, not the parser: legend reads Treating
    Pressure / Slurry Rate x 10 / GORV / Prop Con / BH Prop Con, peaks 77.90,
    9.47, 87.59, 236.61, 233.82 against printed axes 0..100 and 0..500, clock
    3:06 AM. The x10 multiplier is only knowable BECAUSE the legend reads.

- **A chart that fails no longer hands its identity to the other one (#585,
  `a9f05f2`).** `_extract_new` named each plot by ORDINAL POSITION. 00344's
  surface plot raises "time axis unreadable" on all 32 pages, so the chemical
  plot arrived first, inherited the treatment tag, and its Combined Clean Rate
  went out as **"Slurry Rate" on the chemical chart's own 0..16 axis** — a
  legal rate scale, so `impossible_axis` passed it. An upstream failure became
  downstream WRONG DATA. The tag now comes from the caption the page prints
  above each plot. 4 charts -> 27, zero carrying a surface name. Four other
  STEP files bit-identical over 737 channels.
  - **Still open and now isolated: 00344's surface plot — the one with
    pressure, rate and both concentrations — is unreadable on all 32 pages.**
    That is the data Carmine actually wants and it is untouched.

- **One stage drawn as two plots is one stage (#589, `d8916e7`).** The
  backwards-clock warning fired on all 51 stages of 00540 and Carmine asked
  whether it was real. It was not. `serialize()` sends the Lab one entry per
  CHART; only `build_well` groups by stage. A STEP page draws Surface and
  Chemical of the SAME stage, so the well arrived as 102 entries in 51 pairs
  starting SECONDS apart, and each pair was compared against itself. The well
  runs perfectly: ~8 h a stage over three days, nothing overlapping.
  - A warning that cries wolf on every stage of a good well is how the next
    real one gets ignored. 13 tests now, was 10.

- **An interval charted as a bitmap says so instead of vanishing (#557,
  `0a27a33`).** See below — unchanged from this morning.

## Open, top of the list

- **#588 — 00121 gives no tables and no dates/times.** The charts now read;
  the text around them does not. This file is the labels-only pure-vector
  class, so its tables and its Zone Summary date are outlines exactly as the
  legend was. The SLB path already has the OCR machinery (`_spans`,
  `detect_prc`, `page_stage`, and now `_legend`); the tables and the date
  need the same treatment. This is the natural next step and it is on a file
  that already half-works.
- **00148 and the Halliburton half of the pure-vector class.** 280 pages,
  **746 characters in the whole document, and not ONE detector fires** — not
  slb, step1, lib1, bj1, canyon, hal1, and no IFS marker. It is labels-only
  (29 chart pages, 0 chars on them) and `providers.tsv` calls it Hal.
  **00121 works and 00148 cannot, for one reason: SLB is the only reader with
  an OCR fallback.** Halliburton has none, so there is no chain to extend —
  it has to be built. Bigger job than 00121 was.


- **An interval charted as a bitmap says so instead of vanishing (#557,
  `0a27a33`).** Carmine reported 00611 losing stage 27 and could only find it
  by spotting a gap in the sequential numbering. The chart IS in the PDF:
  p261 draws Interval 27 as three 2702x736 images and ONE vector path, where
  the chart page beside it draws 192 paths and 32,936 items. `halliburton_ifs`
  is a vector reader, so it found no clock labels, failed the gate and
  `continue`d — no note, no error, interval gone.
  - The skip is right; the SILENCE was the defect, and it had already cost
    data twice before (the branch's own comment records 24 of 36 IFS files,
    and six of 00001's ten intervals, lost the same way).
  - The previous session's attempt went into the IFS *exception* handler,
    which sits inside the branch the page never enters. It could not fire and
    was correctly reverted rather than shipped. The working place is the gate.
  - **Sized, over 56 __HAL files: 11 pages in 8 files, one to four intervals
    each.** Silent on the other 48, zero errors, 2,456 charts extracted. Two
    independent passes (real `extract_document`, and a per-page image census
    using a different rule) agree on 11-in-8.
  - The threshold is placed on 10,068 IFS pages, not on one file: largest
    image on a page that charts fine 102,750px, on a table of contents
    27,000, smallest on a bitmap chart page 245,403. Empty gap, so it sits at
    the midpoint. Getting there took catching two of my own overclaims — the
    "two orders of magnitude" gap was true only of 00611, and the first census
    pooled each page's logo into the chart population and produced a
    meaningless 0.1x ratio. Per-page maxima is what the code actually tests.
  - **No exported value can change**: the new branch is reached only when the
    old one already skipped the page, and it appends a note and nothing else.

- **Still open, and now sized: the raster IFS reader.** An IFS-layout chart
  rendered as a bitmap has no template. `hal1`'s raster path is a different
  layout and answers "time axis unreadable" on the same page. It is worth
  building: 11 charts across 8 of 56 HAL files, and TESTING.md puts the full
  Halliburton tier at ~510 files. 00242 alone loses four intervals
  (1, 5, 20, 24). The three verified examples are 00611 p261, 00124 p246 and
  00123 p276 — each one path plus large images, neighbours drawing 150-210.

- **00611 charts interval 3 and interval 17 TWICE, and both are legitimate.**
  The charts say so themselves: "Interval 3 – Main Treatment (No Ball Seat)"
  (p135) against "Interval 3 – Main Treatment" (p138), and "Interval 17 –
  Main Treatment (Part A)" (p208) against "(Part B)" (p211). Not the #550/#553
  doubling defect. But both collapse onto one stage number in the CSV, so the
  export carries two stage-3 blocks and two stage-17 blocks with nothing to
  tell them apart — the parenthetical is right there in the title and is not
  being used. That is the shape `_split_bj_windows`/`_window_tags` already
  solves for BJ. Not investigated further, and NOT a #557 symptom.

## Landed 2026-08-19/20 (v1.3.0, v1.4.0)

Fully described in the git log and on the download page; what follows is only
what a future session needs to KNOW rather than what shipped.

- **FracView could not open at all, on any well, for most of a day.** A button
  removed from the markup left its handler bound at top level, the TypeError
  killed every statement below it — including the one that announces the window
  to the Lab — and the symptom was "Waiting for the Lab…" forever. Bindings now
  go through `bind()`, which warns and carries on. If a companion window ever
  goes silent again, read its console before anything else.
- **SLB PRC charts never reported an axis.** `meta.axes` was set in exactly one
  place in `slb.py`, the raster Zone-sheet path, so every vector chart fell to
  the Lab's rounded-peak fallback and read "(guessed)". Four reports, one cause.
  **No exported value changed** — 306 channels measured identical — because the
  values always came off the real tick fit. Only the axis reported and drawn
  against was invented.
- **Two date sources added.** HAL-2 vector charts read their ISO axis label
  (00328: 41 undated stages -> 41 dated); SLB PRC charts read the Stimulation
  Service Report when no Zone Summary sheet exists (00011: 52 of 52 intervals).
  Both were verified against dates the reports print elsewhere for themselves.
- **A stage whose clock runs backwards is now detected on open**, with a manual
  correction that reaches the CSV. The rule is "starts before the previous one
  ENDED", so a long wait between stages is never mistaken for a fault.
- **Trican layout B**: the rate trace was losing 41% of itself to a gridline
  guard, and both concentrations were dropped for want of an axis that turned
  out to be shared. See the two entries under "do not re-litigate".

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

- **The pure-vector class is bundled and measured.** 184 of 2,917 filings on
  `/Volumes/CnC-2TB-ssd` draw their chart labels as outlines: 127 in
  AER-Frac-Montney-ARC, 57 in BCER-Frac, 0 in Nuvista and Paramount. Lists of
  20 and an INDEX are in `batch-lists/vector-no-text/`. The test is
  `pipeline.vector_no_text()`, and it must be asked of the pages that DRAW
  CURVES, not of the document — 00121 carries 288,439 characters over 577
  pages and not one is on a chart. Median chart-page characters: **0** on the
  hits, **347** on everything else. There is no threshold to tune.
  - **It is two jobs, not one.** Split by whether the DOCUMENT carries any
    text: **79 are labels-only** (text everywhere but the charts — 00121 has
    288,439 characters over 577 pages) and **105 have no readable character
    anywhere at all** (00147 is 256 pages of nothing). The 79 are the
    tractable half and where the SLB OCR work applies; on the 105 even the
    vendor cannot be read from the text layer, so detection, tables and dates
    all have to come off the render, and nothing in the tree does that today.
    Lists for both are in `batch-lists/vector-no-text/`.
  - **`curvelen.py` has finished (184/184, no errors) and its answer is NOT
    a threshold.** It was built to split the 184 by longest stroked path, so
    the files with charts to read could be told from the ones where "no
    extractable data" is simply true. The values do not fall into two groups.
    They collapse onto a handful of EXACT repeated numbers — 82 on 76 files,
    464 on 34, 999 on 15, 1,046 on 8. **133 of 184 sit on four values.** An
    identical maximum across dozens of files is a shared template, not a
    measurement of content, and a `>=1000` rule would have thrown the 999 and
    1,046 clusters onto the wrong side of the line. Do not tune this number.
  - **The lead worth chasing is VARIETY, not magnitude** — how many distinct
    per-page maxima a document has. Sampled on one file per cluster (FIVE
    files, so this is a lead and not a result):

        00121  577 pages  longest 6,443  distinct maxima 130  <- known charts
        00147  256 pages  longest   999  distinct maxima  53
        00274  253 pages  longest    82  distinct maxima  11
        00913  198 pages  longest   464  distinct maxima   7  <- furniture
        01756  118 pages  longest 1,046  distinct maxima   5

    The furniture files draw 5-11 different things across 118-253 pages. The
    known-charts file draws 130. **By variety, the 999 cluster (15 files)
    sits with 00121, not with the furniture** — which is the opposite of what
    its round-looking number suggests, and 999 looks like a ceiling rather
    than a measurement, so check that before trusting it. Verify by RENDERING
    a page from the 999 and 1,046 clusters before acting on any of this: the
    whole point of the split is deciding which files deserve OCR work, and
    getting it wrong sends the effort at documents with no charts in them.
  - Nuvista's zero is NOT a clean negative. Only 7 of its 233 files register a
    chart page at all: its charts are RASTER, a different class this detector
    structurally cannot see. Read its zero as "not this class".
- **SLB reads three of the gates on a pure-vector page; it stops at the
  fourth.** `_spans`, `detect_prc` and `page_stage` all fall back to
  `ocr_labels` when — and only when — a page carries no text of its own. On
  00121 that took pages 131-260 from 0 detected to 19 detected and named.
  It now fails at `_time_axis`: three clock labels are wanted among the OCR
  spans and are not being found, though the render plainly holds them ("5:07
  AM" reads at the top of the page text). Behind that gate are the value axes
  and the legend, and THOSE are where accuracy starts to matter — a wrong
  answer there becomes a number in a CSV rather than a page that is skipped.
  Feasibility is not in doubt: labels read at confidence 92-97, both tick
  columns included.
- **Liberty's frame fit drifts, and the drift is measured.** Over all 85
  charts / 522 channels of 00494, frame-vs-printed error runs median 2.27%,
  p90 4.40%, worst 13.02%, with 49% of channels over 3%. The on-screen tick
  labels snap to the printed number but only within 2.5%, which is why some
  stages look right and others do not. That tolerance was deliberately NOT
  widened — it is the only thing between a drifting fit and a chart showing
  round numbers it did not earn. The tell that it is a fit error rather than a
  frame that legitimately extends past its ticks: stage 60's conc reads
  -227.94..1640.05 against a printed 0..1750 — low end outward, high end
  INWARD.

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
    label converted to vector outlines. **No text-based detector can ever fire
    on these.** But they are TWO groups, not one, and only the first is an
    extraction problem:
    - **19 files with real charts — the big remaining prize.** 39-69 chart
      pages each, ~950 pages in total, curves drawn as clean vector polylines
      (01116 p222 is a BJ chart drawn that way). The curves are readable; it
      is the axis, legend and time labels that need OCR. Start here.
    - **8 files (01151-01158) that contain NO treatment charts at all, and
      "No extractable data" is the CORRECT answer for them.** Ovintiv WellOps
      daily-report packages: 122-214 pages of tables, and exactly ONE
      ink-heavy page each, which is a wellbore SCHEMATIC, not a chart
      (verified by rendering 01151 p142, 01155 p112 and 01158 p138 — same OVV
      Tower Lake pad, same layout). Every other page in all eight scores <=180
      saturated vector items against 4,700-6,900 on the schematic. **Do not
      point OCR at these** — there is nothing to read. What they need is the
      per-file note the 00183 entry below already argues for: say the file
      holds no treatment charts, so an honest empty result stops looking like
      a parser failure and stops generating reports.
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
  read a black series off a coloured axis of the same unit. Census over all 12
  Liberty vector files, 901 pages: **403 pages carried a wrong value and every
  one is a black series — no coloured channel moved anywhere**, so the rest of
  the corpus is unaffected.
    - Hydr Pressure, 182 pages, ~4.5x too high (black axis 10..110, inverted).
    - PFR-ZC FR CONC, too low by the page's own printed range: x2 on 147
      pages (0..1.0), x3 on 73 (0..1.5), x4 on 1 (0..2.0), against a borrowed
      0..0.5 colour axis.
    - **The factor is NOT constant, so an old export cannot be corrected by
      multiplying.** Re-export.
    - The three distinct ratios landing exactly on black_max/0.5 with no
      fitting is the strongest evidence the fix reads the printed axis rather
      than inventing a scale.
    - Affects 00374, which Carmine reports as WORKING in #110. Shapes right,
      scale wrong.

- **Trican WH Prop Conc, 41% blank.** Improved but not resolved, and the
  remainder has **two** causes, not one. Of 39,194 columns still carrying no WH
  ink: 50.6% have DH sitting on the shared zero row, so the two curves coincide
  and the partition hands the pixel to whichever colour was painted last; 46.7%
  have nothing drawn at zero at all, so WH is genuinely absent and why is not
  established; 2.7% hold no conc ink anywhere. Neither of the first two is
  recoverable from colour alone. **Do not assume the zero-row story explains all
  of it** — that is the mistake the last two attempts on this channel made.
  (Deleted by accident in ba6c5b0, which was correcting the 2025 diagnosis and
  took this neighbouring item with it. Restored verbatim — the percentages are
  measured and re-deriving them means re-running the corpus.)

- **A 299-page Liberty file takes 322.7s end to end with no progress signal.**
  Not a defect, but a five-minute silent wait is how "it did nothing" reports
  get written — and 197 of those arrived in three days.
- **Cosmetic:** 01103 labels stage 1 as "01" and stages 2-9 bare, so a CSV
  sorted by stage puts 01 after 9. It is the chart's own printed text, so not
  a data defect.
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

## Measured and settled — do not re-litigate

- **Trican layout B's gridline colour cannot be found by colour.** This
  template tints each axis's rules to MATCH that axis's own curve, so the
  obvious fix — pick the rule colour by what dominates across all the rule
  rows — fails: the rate blue still wins 10/12, 10/13 and 9/11 on three pages
  of 00583. Structure separates them and colour never will. A rule is ~360
  runs of ONE pixel; the curve on the row beside it is 8 runs of median 22.
- **Trican WH Prop Conc's gaps are not fillable from DH.** Over all 23 chart
  pages of 00583: 109 blank runs, 8,148 columns, and 6,882 of those columns —
  84% — are before its first reading or after its last. That is the pad and
  the flush, and `ct.resample` is right to hand back nothing. Of the 66
  mid-chart runs, exactly ONE has WH at zero on both sides. Filling from the
  neighbouring curve would invent a concentration for the other 65. This is
  the third time this class has been attempted; the handoff warned about it
  and was right again.

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

## Liberty on outlined pages — where it stands (branch `ifs-ocr-wip`)

19 of the client's 37 failing files are Liberty filings with no text layer.
The reader now clears every gate and returns stage, date, clock and named
channels on 7 of 8 sampled pages. **The values are not yet trustworthy.**

Measured against the render of 00919 p111:

    Treating Pressure  37.875   chart peaks ~38 on 0..75    correct
    Slurry Rate        25.0     chart peaks ~14 on 0..25    WRONG
    Prop Conc         300.0     chart is FLAT AT ZERO       WRONG

**The two wrong ones read EXACTLY a tick value** — 25.0 is the top of the blue
ladder, 300.0 the bottom of the green. And the ladders come back short:

    blue  [10, 15, 20, 25]          missing 0 and 5
    green [300 ... 1500]            missing 0
    red   [15, 30, 45, 60, 75]      missing 0
    magenta [0, 15, ... 75]         complete

Two leads, in order:

1. **The tick labels may be being traced as curve ink.** On an outlined page
   every label is a FILLED VECTOR PATH in its series' colour — the same kind
   of object the curve collector takes. On a text-layer page they are text and
   the tracer never sees them, which is why this has never bitten before. If
   so the fix is to exclude fills that sit outside the plot frame, or that are
   glyph-sized, before tracing.
2. **A ladder missing its zero** still fits (four points determine the line),
   so this is probably not the cause on its own — but check it second.

Do NOT merge the branch until a rendered page agrees channel by channel.
Wrong concentrations in a CSV are worse than the nothing they replace.

### Liberty: what the curve collector actually sees (measured, 00919 p111)

Two hypotheses tried and BOTH DISPROVED by measurement — recorded so they are
not tried a third time:

    type=s items=200 rect=(98,419)-(296,469)   the real curve, inside the plot
    type=f items=37  rect=(201,122)-(208,129)  LEGEND glyphs, above the plot
    type=f items=22  rect=(77,402)-(83,410)    TICK LABEL glyphs, left of it

On an outlined page those glyphs are filled vector paths in the series colour,
and the collector takes filled paths deliberately (2025 filings draw curves
that way). So they LOOK like the cause. Clipping them out — on the value axis
for the legend, on the time axis for the tick labels, both verified to be the
right axes — changed NOTHING. The numbers are identical with and without.

So the glyphs are not what produces the wrong values. What remains:

    Prop Conc      300.0  = the MINIMUM of its fitted axis
    Slurry Rate     25.0  = the MAXIMUM of its fitted axis
    Btm Prop Conc 1500.0  = the MAXIMUM
    GORV Pressure   75.0  = the MAXIMUM
    Treating Press  37.87 = correct, and the only one NOT on a bound

Every wrong channel sits exactly on a fitted bound, which is the signature of
CLAMPING into a mis-fitted range rather than of tracing the wrong ink. And the
ladders come back missing their zero: blue [10,15,20,25], green [300..1500],
red [15..75]. Look there next — at where a traced value is clipped to
(v_lo_ax, v_hi_ax), and at whether a ladder missing its bottom tick makes that
range wrong.
