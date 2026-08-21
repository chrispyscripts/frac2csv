# Frac2CSV — session handoff

Rewritten 2026-08-13, updated 2026-08-21. Repo: `frac-pdf-extract/frac2csv`
(the git repo is that directory, **not** the parent). Shipped: **v1.5.0**,
tagged and building as a Windows EXE, notes live on the download page.
`ifs-ocr-wip` is merged and no longer the place unproven work lives — cut a
new branch for that.

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

Nothing is running. `providers.tsv` and `curvelen.tsv` each carry all 184
rows with no errors; what they say is under "The pure-vector class" below,
and curvelen's answer is not the one it was built to give.

**Unfinished measurement, deliberately abandoned:** a 24-file sweep
(`scratchpad/sweep_fv.py`) meant to count how many wells recover a real
FracView clock under `fvLayout` got through 3 files in ~40 minutes and was
killed to free CPU for the release check. It is informational, not a gate —
the layout rule is covered by 26 unit tests and was checked against the real
00495 (66 stages, 1 jump named at 2023-11-02 04:51). Re-run it when the
machine is idle if the number is wanted.

Eight local app instances were running at the end of this session — past the
3-4 the tooling is comfortable with, and one was pinned at 96% CPU for over
an hour. Cycle them before testing anything.

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

## Landed after v1.4.0 — ALL SHIPPED in v1.5.0

Four fixes from 2026-08-20, plus the Liberty/IFS outlined-page work and the
daily-report clocks. All of it is in the v1.5.0 tag and the EXE it builds.

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

- **00060 has two stage clocks that cannot both be right, and it is not
  known whether the sheet or the reader is wrong.** CalFrac
  `__CALFRAC/00060-100030506723W500_0486730_COMP.pdf`, 23 stages, all dated
  and clocked. Read back:

        8            2018-07-14 09:57:40
        9            2018-07-16 23:10:36     <- after 10..20 have all run
        10           2018-07-16 03:57:49
        ...
        20           2018-07-16 14:44:45
        21 Surface   2018-07-16 15:48:06
        21 BH        2018-07-16 15:48:06     <- identical to 21 Surface
        21           2018-07-15 21:22:00     <- before both

  Stage 9 belongs between 8 and 10 and sits nineteen hours past 10; the third
  "21" sits eighteen hours before the other two. FracView now draws both out
  of order and names the moment, so they are visible — but visible is not
  diagnosed. Check the CalFrac sheet's own printed times before assuming the
  reader misread: if the filing prints them that way, the Fix time button is
  the whole answer and there is no bug. This is the first real well the
  jump markers found, so it is also the check that they work.

- **`gaps.py` is written, tested and WIRED INTO NOTHING.** Carmine asked for
  missing-data detection and interpolation: flag a sample whose value is
  missing while the axis position is between the floor and the ceiling, and
  fill the link. The module does that — `LEAD`/`TRAIL`/`AT_FLOOR`/`AT_CEIL`/
  `MISSING`/`UNKNOWN`, `FLOOR = 0.02`, `CEIL = 0.98`, `interpolate()` returns
  the filled values AND the indices it filled — with 19 tests. No caller
  anywhere. Deciding WHERE it goes is the open question: the export, the Lab's
  own graph, or a per-stage note. Nothing has been decided.
  - Read the tests before the module. The first version scanned for `None`
    while the pipeline carries `NaN`, so it could not have worked on a single
    real file, and all 14 tests passed because they were written in `None`
    too. `is_missing()` now handles both.

- **DATE/TIME COVERAGE IS MEASURED. `validation-tools/datetime_sweep.py`,
  60 files sampled across BOTH drives, run through the SHIPPED code.** It
  aggregates by the `source` each chart reports and counts dated and clocked
  SEPARATELY, because they fail for different reasons.

        template                              charts  date%  time%
        Halliburton IFS chart                    191   100%   100%
        SLB Zone Summary chart (raster)           62   100%   100%
        Halliburton treatment plot (raster)       49   100%   100%
        Liberty chart                             42   100%   100%
        Canyon chart                              25   100%   100%
        Sanjel chart                              22   100%   100%
        STEP surface chart (raster)              777    98%   100%
        CalFrac chart                            738    94%    71%
        STEP chemical chart (raster)             600    94%   100%
        Trican treatment chart (raster)          254    85%    85%
        SLB PRC chart                            115    43%   100%

  **Six of eleven types are already at 100/100.** The goal is three gaps, and
  they are FILE-level, not scattered:
    - **CalFrac clocks.** 00020 and 00027 are 81 charts each, fully dated and
      with ZERO start times; 00018 the same. 174 charts in three files.
    - **SLB PRC dates.** 00588 (0 of 15) and 00445 (0 of 47) are total misses.
    - **Older CalFrac (2014-15)**: 00007, 00033, 00022 have neither.
  Four sampled files produced no charts at all — one each from STEP, Trican,
  ARC and Nuvista.

- **AND THE CAUSE IS ONE THING, WITH ONE ANSWER.** 00020 has no Treatment
  Summary grid ANYWHERE — 493 pages, zero — and its charts plot "Time (min)"
  from 0, so there is no wall clock on them either. That is the same shape as
  00121: the reader depends on a vendor summary sheet and the sheet is not in
  the document.
  - **The operator's DAILY OPERATIONS REPORT is the general source.** 00020's
    "Daily Completion Operations" pages carry the time log with the stage in
    it, exactly as 00121's Peloton pages do:

        08:00 | 11:30 | 3.50 | 11.50 FRAC | PP | ... | Frac Stage # 1 (...)

    with the page's own Report Date. Stage -> (date, start time), from the
    OPERATOR's document, so it does not care which vendor pumped the job.
    That is why it answers the SLB gap and the CalFrac gap at once.
  - `validation-tools/fraclog.py` is a working prototype of that reader,
    already validated on 00121 against the charts' own clocks (32 of 36).
  - **The verification is NOT symmetric, and this is the trap.** 00121's
    charts print a clock, so the log can be CHECKED against them — that is
    how the lost-PM bug surfaced. 00020's charts are elapsed minutes, so the
    log would be the only authority and a wrong stage->time mapping would be
    invisible. Where there is nothing to check against, the value must be
    labelled as coming from the daily report rather than the chart.
  - **Do NOT read "stage N" from free text.** A comment ending "ready to Frac
    Stage #" is followed by the next cell, a clock, and a loose regex reads
    "16:30" as stage 16. Read it only from inside a FRAC row.


- **#588 — an OCR'd clock kept its PM (`1068870`), and the method that found
  it is reusable.** Every AFTERNOON chart in a pure-vector SLB filing was
  read twelve hours early: OCR returns "4:43" and "PM" as separate words and
  `_clock_minutes` parses one string. 00121 p134 is genuinely AM, so the
  file's first chart looked right and nothing said otherwise.
  - **It was found by an ORACLE, not by reading code.** 00121 carries no
    Stimulation Service Report, no Zone Summary and no Frac Stage Details —
    only 129 Peloton "Regulatory_Daily Completion and Workover" sheets. Those
    print a Report Date and a Time Log whose FRAC rows carry a start time and
    the stage number, so they date and time each stage INDEPENDENTLY of the
    chart. 22 of 36 logged stages disagreed by 709-719 minutes; nothing but a
    lost PM sits that tightly around 720. After the fix: agreement 14 -> 32.
  - `validation-tools/fraclog.py` is that harness. Point it at any filing with
    Peloton daily reports and it scores the charts against the log.
  - **Do NOT read "stage N" from the free text of a daily report.** A comment
    ending "ready to Frac Stage #" is followed by the next cell, a clock, and
    a loose regex reads "16:30" as stage 16. Read it only from inside a FRAC
    row.
  - Four stages still disagree. Not explained, and NOT assumed to share the
    cause.

- **Dates for the pure-vector class: the survey is DONE and it kills the
  obvious plan.** A pure-vector chart prints a clock and no calendar, so the
  day has to come from somewhere else. `validation-tools/datesrc.py` asked all
  184 files which of the four sheets the readers know is present IN THE TEXT
  LAYER; `validation-tools/datesrc-partial.tsv` is the full result.

        105  no-text      (no known sheet)
         68  labels-only  (no known sheet)
          7  labels-only  daily reports      <- the 00121 route
          4  labels-only  STEP Daily Stage Summary

  **173 of 184 carry NONE of them**, and of those only 38 print a date-shaped
  string anywhere in the document at all. So chasing summary sheets is a dead
  end for this class: eleven files, and seven of those are already reachable.
  - **The date has to come off the CHART.** That is not speculation — 00148's
    IFS charts print "2022-02-12" directly under the time axis, `_axis_date`
    already reads exactly that, and the OCR work on `ifs-ocr-wip` returns the
    right date for p136 today. Whatever reads a pure-vector chart gets its
    date for free; nothing else has to be built for it.
  - So the ordering is: make the chart readable, and the date follows. Do NOT
    start by building a date pipeline.

- **00148 / IFS-on-outlines is on branch `ifs-ocr-wip` and MUST NOT be
  merged as it stands.** 116 chart pages, no readable character, no
  Halliburton reader with an OCR fallback. Five gates now clear — detect,
  rotation (the page is /Rotate 90 and `page_rotated` had no text lines to
  measure), time axis, legend rebuilt from OCR words grouped by colour and
  row, and the tick columns. Stage, date and Tr Press (77.6 against a printed
  0..100) all come out right.
  - **It mis-maps the other axes and exports plausible wrong numbers.** The
    letter->column mapping clamps surplus letters onto the last column, so
    Slurry Rate read 62.83 against a printed 0..20 and BH Prop Conc 22.7
    against 0..1000 — each exactly its true value as a percentage of full
    scale on the PRESSURE axis. Removing the clamp drops the concentration
    and the rate is STILL 62.83.
  - The fix is to tie each letter to the column it actually labels — the
    letters print AT their columns (black 'A' at cx -700, 'B' at cx -133 on
    p136) and that position is the association, not left-to-right order —
    and then to check every peak against its own axis before returning, the
    way `step1.impossible_axis` already does.
  - The legend colour recovery is the reusable piece: an outlined glyph is a
    FILLED PATH carrying the colour the text had, so a word's colour is the
    dominant fill inside its box. Measured exact on p136 for all five series.


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

## From Carmine's reports, 2026-08-21

**#601 / #606 — every Liberty timestamp was a second short.** He diagnosed it
himself: "we are off by 1 second on the x axis thus we trigger a date
change... the actual chart display shows 2023/01/17 00:00". t_lo is a fit
through label centroids and lands a hair below the second it means; the
formatter truncated. Harmless until a chart starts at MIDNIGHT, where
00:00:00 became 23:59:59 on the day before, meta.date followed it back, and a
perfect clock tripped the backwards-clock warning on the stage beside it —
which is why the flag appeared on the wrong stage. Rounded, both halves off
one instant, in `_stamp()`. Measured over 273 pages: 0 channel values moved,
150 times +1s, nothing else. 108 of those were a TEXT-LAYER file, so every
Liberty CSV ever exported carries this.

**#612 — Halliburton IFS v6 was unread because the marker's V is capital.**
Builds to v4.6.3 stamp "(IFS v4.6.3)"; v6 stamps "(IFS V6.0.0)". Both the
module's detect and — the one that mattered — the pipeline's own gate tested
a lowercase literal. Fixing the module alone does nothing; the pipeline never
calls it. All five files he named, from zero:

    00084  388pp   45 series    00085  388pp   45 series
    00086  442pp   61 series    00087  472pp   60 series
    00088  284pp   29 series

    240 series, 239 dated, 240 clocked.

A corpus scan says the capital-V class is EXACTLY those five files (1,326 IFS
pages). It is closed, not a sample.

**How I got #612 wrong first, so nobody repeats it.** I picked "the chart
pages" by drawing count, ran extract_page on them directly, watched every one
fail with "time axis labels not found", and concluded v6 was a layout variant
needing its own reader — and committed a note saying so. Those were not the
chart pages. The titled pages I had dismissed as tables ARE the charts, and
the pipeline's gate selects them correctly. **Do not test a template by
choosing pages yourself when a gate already chooses them.** The note carrying
the wrong theory has been removed.

**Triaged, not acted on.** #602 is retracted by his own #604. #611 confirms
the date-check flag is working. #585 and #588 are v1.4.0-era and predate
several fixes — re-test before treating either as live.

## The "no text at all" class — 191 files, and it is mostly Halliburton

Carmine: every file on the textless list is unreadable. Measured, the list is
191 files and 49,250 pages, and it is not one problem:

    136 files  37,083 pages   a Halliburton marker
     22 files   3,772 pages   Liberty (dealt with below)
      6 files                 STEP
      1 file                  SLB
     25 files                 no vendor name found at all

**Why they were unreadable: no detector fired on any of them.** hal1.detect
read the raw text layer for "TREATMENT PLOT" and these pages have no text
layer — while OCR shows exactly that string printed on the page. The chart was
never the problem: it is a raster image and extract_image already OCRs its own
axes. Only detect and page_meta read text, and both strings are on the image.

Two changes, in `547630e`:

1. The same _page_text OCR fallback lib1/slb/IFS already use. The big-image
   test runs FIRST — it is nearly free, OCR is not, and detect is called on
   every page of every document.
2. **These plots are rendered SIDEWAYS.** Found by rendering the page, not by
   reasoning about it: "Pump Time" runs down the page, so the tick ladders,
   the time calibration and the series masks are all reading the wrong axis.
   The orientation is not guessed — normal is tried first, and only a page
   that fails to find a time axis is turned clockwise and read again, so a
   page that reads today never reaches the new path.

Result on the first 12 (the smallest, 84-181 pages):

    9 files now extract    122 series, all "Halliburton treatment plot (raster)"
    3 files still return nothing — and that is the RIGHT answer for them

Those three (00150, 00151, 00356) are operator daily-report documents that
merely NAME Halliburton, in a "Company: Halliburton" row of a Stimulation
Summary. Rendered, their most-coloured page is a Peloton daily-completion
table — coloured cells, no curve. The pipeline's own note already says so.
Do not chase them. And do not use longest-path to decide this: that threshold
is recorded further down as retracted, and it was checked here by rendering.

Regression, on two filings hal1 reads TODAY, found by CONTENT — picking them
by 5-digit index tested files hal1 never read at all, because the two drives
number different wells the same:

    00478 + 00479, 57 chart pages, 228 channels
    0 moved, 0 pages gained or lost, 0 metadata changed

### Open on this class

- **Speed, and it will read as a hang.** lib1.detect costs 3.0s on a textless
  page, because it OCRs every page looking for the word "Liberty" before any
  other reader gets a turn. 84 pages is ~4 minutes before the first chart
  appears and this class runs to 800 pages. The hal1 change does not add to
  it — its image test rejects a non-chart page in 0.000s — but it does not
  remove it. Whether a cheap guard is safe for lib1 is NOT known; the
  measurement that would answer it timed out.
- **Every stage also prints a CHEMISTRY PLOT page** of additive
  concentrations (OPTIKLEEN-WF, FIGHTR EC-1, MC B-8510...). hal1 reads these
  on no filing at all, textless or not, because detect requires "TREATMENT
  PLOT". Pre-existing gap, not caused by this class.
- **One page of 00392 still fails and may be right to.** Its labels run 28
  07:09, 28 16:53, 28 17:26, 28 17:59, 29 22:33 — a stage broken by long
  shut-ins, so the axis is linear in PUMP time while the labels are wall
  clock. A straight-line fit would invent timestamps. Not confirmed by
  measuring the label positions, so do that before changing anything.
- The other 33 textless files (STEP, SLB, and the 25 with no vendor found)
  have not been looked at.

## Liberty, read page by page — what a one-page sample was hiding

Every Liberty number on record before this was measured on ONE page per file,
the busiest chart in each. Reading all 3,774 pages of the 22 outlined files
found seven defects, and only two of them ever announced themselves. The rest
are silent: the CSV simply has less in it, or the numbers are quietly high.

**The corpus is bigger than this file said.** 425 Liberty filings, not 19:
403 carry the printed marker and 22 have no text layer at all. The outlined
set includes five nobody had listed — 00998, 01000, 01001, 01002, 01003 — and
a first pass missed 00913 and 00914 because "textless" was defined as all but
one sampled page blank; half the sampled pages is the right cut. A Liberty
MARKER is not a Liberty CHART: 129 of the 403 also name another vendor, so
the file list has to come from detect firing, not from the name.

**Result over all 22 outlined files, measured before and after:**

                          before     after
    chart pages             1,261     1,258      -3, daily reports no longer
                                                 mistaken for charts
    extracted               1,227     1,254     +27
    FAILED                     34         4     -30
    dated                   1,202     1,229     +27
    clocked                 1,227     1,254     +27
    channels                4,568     4,803    +235

    extraction rate          97.3%     99.7%

The 4 that still fail: 3 "legend or tick rows not found", 1 "day is out of
range for month". The whole implausible-duration class is gone.

And the corpus as a whole, from the detect pass: **395 of 403 marker files
hold Liberty charts, 23,243 chart pages.** The 22 outlined files above are
3,774 of those pages; the rest have a text layer and were already read.

Baseline over the 22 outlined files, before the fixes below:

    3,774 pages   1,261 chart pages   1,227 extracted (97.3%)
    34 failures: 26 implausible duration, 4 no legend/ticks,
                 3 no time labels, 1 day out of range
    dated 98.0%   clocked 100%   staged 96.8%
    values outside their printed axis: 0

That last line is the v1.5.0 axis work holding up across 1,227 pages.

### The seven

1. **A channel going missing.** A colour needs four tick labels to earn an
   axis, and OCR reads 00915 p108's rate ladder as [12, 16, 20] — three
   labels, evenly stepped and evenly spaced. No fit, and Slurry Rate is
   dropped from the page with nothing to say it was there. 22 of that file's
   24 treatment charts lose it. Three labels even in value AND even in
   position are now accepted; three bad reads do not land on both grids.
2. **A channel overwriting another.** Both greens come back "Prop Conc" when
   OCR drops the "Btm", and the dict kept one. It kept the LAST, so the
   bottom-hole curve was landing under the surface name. The first is kept
   now and the clash is numbered — "Prop Conc #2" — rather than guessed at.
3. **A misread day killing the page.** The old repair wanted three readable
   dates and a majority; OCR leaves two. A chart is contiguous, so the day
   advances exactly where the clock wraps. Do NOT infer direction by counting
   rollovers — that is written up under _walk and it broke p106 when I did it
   anyway. The shortest consistent reading wins instead.
4. **A stage dated a day late.** start_time came off the window start, the
   date off whichever label the fit anchored on. Both come from the same
   instant now.
5. **Legend words read down the page instead of along it.** OCR turns chart
   ink into "|" 300 points below the legend row and in the same colour; that
   outlier makes the vertical spread larger, and on a row every word shares a
   coordinate so the sort ties and the name arrives in span order. "475 CONC"
   became "CONC 475" on 28 pages.
6. **_snap_name compared title case against a list that is not all title
   case**, so "GORV Pressure" could not be reached by any variant of itself.
   Both sides lowered. Measured: every additive code still matches nothing
   even at 0.70, and BH/WH stays refused.
7. **A curve losing its bottom.** The worst, and the quietest. 00913 p133
   prints 0 on all five ladders and OCR reads none of them. The AXIS is
   extended to zero for that case; the INK bound was not, so it stopped a
   whole step higher and both proppant concentrations read a floor of ~193
   kg/m3 through the third of the stage the sheet draws flat at zero.

### Settled, do not re-investigate

- **The ink-heavy pages the detector passes over are wellbore schematics**,
  not missed charts — "Well Summary (schematic) - By Job", checked on six
  files, 10-12 pages each. This is the same trap the earlier session fell
  into with a saturation count; the count is a candidate signal only.
- **GORV Pressure really does run flat near the top of its axis.** I assumed
  it was clipped, rendered the page, and measured the line at 76.4 on a 0-80
  axis against our 76. The extractor was right and the eyeball was wrong.
- **daily reports are not charts.** The operator's sheet names the service
  company and the stage it fracced, which is everything detect asks for, so
  00915 p50 came through as a broken Liberty chart. daily_ops knows the
  shape; it missed the title because "Daily Completion and WS" is its "Daily
  Completion & WS" marker with the ampersand spelled out.

### Still open on this template

- **A two-label ladder.** 00913 p133's blue ladder OCRs as [12, 16] — below
  even the three-label rule — so Slurry Rate is dropped from that page. Two
  points do determine a line; what they do not carry is any evidence that
  they are a ladder. Needs a different kind of check, not a lower count.
- **GORV's maximum reports the axis top exactly** (80.0) while the curve runs
  flat at 76. Some magenta ink reaches the top tick and red on the same page
  does not do this — the difference is not understood yet.
- **The light-green concentration keeps a floor of 38** on 00915 p110 rather
  than 0, and misses its final drop to zero. Better than the 200 it was.
- Names still arriving mangled past the snapper: "BH Con" (73 pages),
  "—— BN Con" (23), "B701 NC" (15), "LTM PUMP B701 CONC" (13). The additive
  codes cannot go in _CANON_NAMES without risking exactly the mislabel the
  cutoff exists to prevent.

### Harnesses, in scratchpad — rebuild rather than reinvent

`lib_inv.py` (which files are Liberty), `lib_id.py` (OCR-identify the
textless ones), `lib_detect.py` (chart pages per file), `lib_pages.py` +
`lib_sweep.py` (per-page analysis, one JSON per file, restartable),
`lib_report.py` (the numbers above), `ab.py` + `ab_diff.py` (before/after
digests; the spec always includes a TEXT-LAYER file, because every change
here is gated on OCR pages and that file proves the gate holds).

## Liberty on outlined pages — SHIPPED in v1.5.0

19 of the client's 37 failing files are Liberty filings with no text layer.
All 19 extract, each on its busiest chart page, every one with a date, a
clock and values inside their printed axes:

    00913 s13 04-29  00914 s19 04-29  00915 s8  04-28  00916 s38 05-05
    00917 s18 05-08  00918 s41 05-06  00919 s2  04-23  00920 s43 05-06
    01004     12-11  01007 s24 05-09  01072 s6  01-28  01073 s2  01-26
    01074     01-27  01075 s4  01-29  01076 s10 01-29  01077 s5  01-27
    01078     01-27  01079 s3  01-26  01080 s1  01-25

00919 p111 was checked channel by channel against its render and all five
agree. Files that DO carry a text layer come back bit-identical: 252 channels,
0 moved.

**The bug was the axis fit, not the tracing.** Every wrong value sat exactly
on a fitted bound — 25.0, 300.0, 1500.0 — which is the signature of clipping
into a mis-fitted range. Four fixes, in the order they landed:

- `734609f` a ladder whose zero OCR never found was lifting flat curves off
  the floor. Where the tick step divides the lowest tick, the axis starts at
  0 whether or not the 0 was read.
- `0a8c8cb` ink above the top tick is not data.
- `8fc864a` `x_lo` was the global top tick across EVERY colour, so ink above a
  given series' own maximum still reached its fit. Each series is now bounded
  by its own ladder.
- `1580565` a misread DAY is repaired like a misread year: a label within one
  day of the majority is kept, anything further out is a misread.
- `3ab6456` `_time_axis` accepted two clock labels on an OCR'd page and
  `_horizontal` still demanded three, so four landscape charts went down the
  ROTATED path and died with "implausible duration 487965257s".

### Four theories that are NOT the cause — do not spend the hour again

Each was tried and disproved by measurement:

  1. legend glyphs traced as curve ink — clipped them out, no change
  2. tick-label glyphs traced as curve ink — clipped them out, no change;
     `keep` already excludes both, they never reach the fit
  3. the real curve filtered out by the value bounds — it is not
  4. a unit-keyed borrow via `unit_fit` — no: `fits[blue]` exists, so
     `fits.get(color) or unit_fit.get(unit)` never falls through

And the naming trap that cost two of those attempts: in the collector
`arr[:,0]` is the VALUE coord and `arr[:,1]` is TIME, so `x_lo/x_hi` bound
VALUES and `y_lo/y_hi` bound TIME — the opposite of what the names suggest.
Both clip attempts were no-ops because they had this backwards.

### Still open on this template (cosmetic, not value errors)

- Four channel names survive OCR mangled past the snapper: "H Prop Conc"
  (ambiguous BH/WH — refused deliberately rather than guessed), "BH Con",
  "Prop Bint Con Sn", "—— BN Con".
- 01004, 01074 and 01078 report no stage number.
- 01004 has one channel that comes back all-NaN.
