# Where each provider's dates and times come from

Written 2026-08-13. This map existed only inside a session transcript before
now, and was lost with it once. Keep it here.

Two separate questions per template, and they have different answers:

- **the clock** — what time of day a stage started, and the elapsed axis the
  samples are laid on;
- **the day** — which calendar date that stage belongs to.

A chart usually knows one and not the other, which is why almost every
template needs a second source and a rule for who outranks whom.

## Status at a glance

| provider | day comes from | clock comes from | state |
|---|---|---|---|
| CalFrac | Multiple-Zone sheet `Job Date:` | printed zone start times | **measured**, 71.7% exact vs BCER |
| STEP | Daily Stage Summary Date column | chart's own clock, else the sheet | **measured**, 51/51 and 41/46 |
| Canyon | `Treatment Date:` header + interval summary | chart clock | from code |
| SLB | Zone N Summary sheet timestamps | same sheet, AM/PM | from code; check vs client spec |
| Sanjel | date printed under the time axis | time axis | from code |
| Liberty | `_parse_date` | time axis | from code |
| Halliburton (Hal-1, IFS) | nothing in the module | time axis only | **gap** |
| BJ | nothing in the module | time axis only | **gap** |
| **Trican layout A** | STAGE INFORMATION page | STAGE INFORMATION page | **measured**, 98.0% of 6,795 stages |

"Measured" means re-run this session and counted. "From code" means read out
of the module and not re-verified — treat as a claim, not a result.

## CalFrac — the most worked-through, and the model for the rest

`calfrac_progress.py` plus the block at `pipeline.py:251`.

1. **`sheet_job_date`** reads `Job Date:` from the GENERAL INFORMATION block of
   the Multiple-Zone summary sheet — single day or range, `Mar 8, 2015` or
   `8/23/2017 - 08/25/2017`.
2. A well reprints that sheet **per block of zones, with that block's own day**
   (00017: Mar 08 over zones 1-11, Mar 09 over 12-18). `job_date_for` picks the
   sheet in the run whose zone columns actually hold the chart's first zone,
   falling back to the run's earliest dated sheet.
3. The MView **footer** date is when the chart was *exported*, not when the zone
   ran, and is outranked by the sheet. 00194's three chart pages sign off 8/24,
   8/25 and 8/25 for zones its own summary dates 8/23-8/25.
4. **`_calfrac_days`** enforces that zones pumped in order have increasing
   instants, moving the fewest printed pages that makes the clock run forwards.

Measured this session, paired over the 242 keyed files with a BCER key:
stages dated exactly right **58.2% → 71.7%**, off-by-one 1,598 → 1,131, other
676 → 432, and stages matched went *up* (5,437 → 5,514).

## STEP — the filed number, and a guard worth keeping

`step_summary.stage_clock` plus `pipeline.py:612`.

The Daily Stage Summary is the only place these books print when a stage ran.
Every generation carries `Start Time (hh:mm)`; 2017-on also carries a Date
column. 2016 books (00180) print the time alone and their charts carry their
own date.

**It is the filed number, not our reading of one** — for 00664 it matches
BCER's FRAC START TIME on all 36 stages to the minute. But it is *not* the
instant the chart's plot window opens: over 140 stages that carry both, the
window opens within 15 min of it on 88% and within 30 min on 98%. So it is for
charts that print no clock of their own, and nowhere else.

Precedence: a chart that read its own clock keeps it, and the sheet may correct
only its **date** — and only when the two agree about the time of day. The
guard exists because 00664 p130 is titled Interval 22 while plotting a window
its footer dates three hours from the 13:55 the sheet files for 22; taking the
sheet's day there moved a correctly dated chart onto the wrong day.

Measured this session: 00349 — 51 stages, 51 dated, 51 clocked, 9 re-dated from
the summary. 00308 — 46 stages, **41 dated**, 46 clocked, so five stages come
out with a clock and no day.

## Trican layout A — was the clearest gap, now read from the table

It exported **0 of 39 stages on 00005 and 0 of 28 on 00317** with any date or
time, because `trican_charts.time_axis` reads only the "Elapsed Time (min)"
strip below the frame.

`trican2.stage_clock` now supplies both from the STAGE INFORMATION page that
follows each chart — its As-Pumped "Start Time" cell, e.g. `Feb 10, 10:09 AM`,
present on 39/39, 34/34 and 27/27 rows. Wired in at `pipeline._trican_clock`,
which fills only what is empty and corrects nothing.

**The join is proved by the data.** These charts are cut from one job-long
elapsed clock, so the gap between two charts' origins equals the gap between
the same two rows' Start Times — exactly, from the second stage on. 00317's 27
stages agree within a constant 306 min, 00156's 34 within 135 min, and that
constant is stage 1 alone, whose chart window opens partway through a long
first stage. Caveat: 00005's elapsed axis RESTARTS mid-job (stages 17 and 22
both report origin 0), so this is a check, not the join.

**The year is the hard part.** No STAGE INFORMATION page prints one. The
report's own dates — licence, submission, expiry — are not the job but bracket
it, so `_year_for` takes the year landing nearest the middle of that span. A
"use the filing year" rule gets 00156 wrong: filed 2019DEC06, printed dates
2019-10-19 to 2020-01-30, job Nov **2019**.

Result: 34/39, 34/35, 27/28 dated, the rest being whole-job "continuous" pages
with no stage number. Across all 100 rows the clock runs forwards with **zero
backwards steps**, over 5d19h, 22h26m and 17h41m.

**Corpus-validated** over all 192 `__TRICAN` files — 182 carry STAGE
INFORMATION pages, holding 6,795 stages, of which **6,657 (98.0%) are dated**,
with zero crashes.

- The 4 undated files print no date anywhere in their first pages, so
  `_year_for` returns nothing and the charts keep no year rather than a
  guessed one. That is the designed behaviour, and it is the whole of the 2%.
- **The year rule holds: zero backwards steps of year scale.** All 75
  backwards steps across 45 files are under a day (0.01-0.97 d), and most land
  exactly on `00:00:00` — stages whose Start Time cell reads midnight, which is
  a cell-content question, not a dating one. A mis-picked year would show as a
  ~365-day jump and none occurs, including on the report whose own printed
  dates span 432 days.
- Two files put their first stage outside the report's printed span, and both
  look right on inspection: 00470 and 00520 print a single date, 2021-03-15,
  for jobs pumped the previous December, which the filenames
  (`COMP_2021JAN27`, `COMP_2021FEB03`) agree with.

An earlier draft of this file said layout A was "NOT in `__TRICAN` on the newer
drive". That was wrong. It came from classifying a directory that was empty
because the drive had dropped mid-copy — three zeros that read like a result
and actually meant no data. 00005, 00156 and 00317 are all in `__TRICAN`.

## Canyon, SLB, Sanjel, Liberty — read from code, not re-measured

- **Canyon** (`canyon_tables._treatment_date`) takes `Treatment Date:` off the
  label's own printed line rather than by scanning page text, because the
  comments columns are full of other dates and the `/Rotate 90` sheets give no
  useful stream order. `55462e6` added dating from the printed TREATMENT
  INTERVAL SUMMARY, choosing between re-attempt rows by the chart's own clock.
- **SLB** (`slb._zone_sheet_times`) takes the four timestamps off a Zone N
  Summary sheet **positionally** — first cell right of the label on the label's
  own row — because the text stream is in drawing order and the values arrive
  nowhere near their labels. Worth checking against the client's own spec: his
  notes say SCHLUM-1 takes "Date start from Stimulation Service report", and
  SCHLUM-2 prints DATE and times (AM/PM) on the Zone 1 Summary.
- **Sanjel** (`_page_date`) uses the date printed under the time axis, once per
  tick, because that is the interval's own day — the header `Date:` field is
  the job's and names a different day on a multi-day job.
- **Liberty** (`lib1._parse_date`) and **Peloton** carry date handling; Hal-1,
  Halliburton IFS and BJ have no date function in their modules at all and read
  only a time axis.

## The safety net under all of them

`pipeline.py:488` re-dates stages so a well's clock runs forwards, moving the
fewest stages that achieves it, and reports how many it moved. It only fires
where a stage has both a day and a real clock (not `00:00:00`). It is a
backstop for a mis-sourced day, not a substitute for finding the right source.

## If you pick this up next

1. **Validate the Trican clock on the layout-A corpus.** It is written and
   working on three files; the 2015-2016 vintage lives on the first drive, not
   `__TRICAN`. Check `_year_for` against a report whose own printed dates span
   more than a year, which is the case most likely to pick the wrong one.
2. **STEP's undated stages** (5 of 46 on 00308) — they have a clock, so only
   the day is missing.
3. **Verify SLB against the client's cascade** rather than against our output;
   his notes are in `frac-pdf-extract/carmine-notes/`.
4. Hal-1 / IFS / BJ have no day source at all. Check whether their reports
   print one before building anything.
