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
| **Trican layout A** | **nothing** | **nothing** | **gap — clock is on the page, unread** |

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

## Trican layout A — the clearest open gap

**0 of 39 stages on 00005 and 0 of 28 on 00317 carry any date or start time.**
Measured this session, not inferred.

The cause is specific and fixable: `trican_charts.time_axis` reads the strip
*below* the frame (`y1+1 .. y1+46`), which is the **"Elapsed Time (min)"** row.
The module's own header docstring records that these charts print time along x
**twice** — "clock time (HH:MM) above the frame, elapsed minutes below it". The
wall clock is on the page and is never read.

That is the same shape as the STEP fix in `f6898de` ("ask the chart for its
clock instead of the page's wording"), and layout A has a per-stage answer key
sitting next to it: `trican2.py` reads the STAGE INFORMATION table on the
following page. Both halves are already in the tree.

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

1. **Trican layout A's clock** is the biggest single gap and the mechanism is
   already identified above — with `trican2`'s STAGE INFORMATION table as the
   answer key.
2. **STEP's undated stages** (5 of 46 on 00308) — they have a clock, so only
   the day is missing.
3. **Verify SLB against the client's cascade** rather than against our output;
   his notes are in `frac-pdf-extract/carmine-notes/`.
4. Hal-1 / IFS / BJ have no day source at all. Check whether their reports
   print one before building anything.
