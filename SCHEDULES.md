# Where each provider prints its pump schedule

Written 2026-08-13, for the "schedule data as a separate CSV" work.

A **schedule** is the stage-by-stage pumping breakdown — one row (or column)
per pump step: pad, the proppant ramp, sweeps, flush — carrying rate, clean
and slurry volume, proppant concentration and fluid. It is NOT the per-stage
summary that the summary parsers already read, which is one row per frac
stage.

**Two layouts, and the difference decides the parser.** Halliburton and STEP
print schedules TRANSPOSED — pump stages run across the page as columns, with
the quantity names down the left. SLB prints them the ordinary way round, one
row per stage. A row-wise reader run over a transposed sheet produces
plausible nonsense, so establish the orientation before writing anything.

## Status

| provider | where | layout | parsed today? |
|---|---|---|---|
| Halliburton (IFS) | `PUMPING SCHEDULE` + `TREATMENT DESIGN` pages | **transposed** | no |
| SLB / SCHLUM | FLUID + PROPPANT blocks on each Zone/Interval Summary sheet | row-wise | **yes** (this session) |
| STEP | `Treatment Report - Daily Stage Summary` | **transposed** | partly — read for clocks |
| Trican layout A | `STAGE INFORMATION` page, its volume/fluid/proppant sections | row-wise, flattened | partly |
| CalFrac | not located yet | — | no |
| **Liberty** | `Job Design` pages | row-wise | no |
| **BJ** | not located (WellOps report is metadata) | — | no |
| **Canyon** | none found in 3 files | — | no |
| **Sanjel** | none found in 3 files | — | no |

## Halliburton (IFS) — the clearest schedule in the corpus

Explicitly titled. In a 4-file sample: 65 `PUMPING SCHEDULE` pages plus 150 and
102 `TREATMENT DESIGN` pages.

Transposed: measured on 00011 p28, the pump stages sit at x = 128, 157, 185,
202, 230, 246, 262, 279, 295, 312, 340, 368, with a total column at 397. The
left-hand labels are the quantities:

- `Prop. Mass (kg)` — 0, 0, 1000, 1000, 4000, 6000, 8000, 10000, 12000, 7980,
  0, 0 → total 49980
- `Proppant Conc. (kg/m3)` — 0, 0, 50, 50, 100, 150, 200, 250, 300, 350, 0, 0
- `Clean Vol. (m3)` — 2.0, 40.0, 20.0, 20.0, 40.0 … → total 314.8
- `Rate - Liq+Prop (m3/min)`, `Fluid Desc.`, `Proppant`

That is a complete pump schedule and nothing reads it today. Highest value of
the group.

## SLB / SCHLUM — done this session

The FLUID block on every Zone and Interval Summary sheet IS the as-pumped
schedule: `PAD / SLURRY / SPACER / FLUSH / SWEEP` on a Zone sheet, and
`PUMPDOWN: PRODUCED / FRESH / ACID / SW / METHANOL` and
`FRAC: SPACER / ACID / PAD / SAND 70-140 / SAND 40-140 / FLUSH / WINTERIZE`
on an Interval one, each with fluid type, clean total and slurry total. The
PROPPANT block beside it gives designed vs placed tonnage per proppant type.

Now emitted by `slb_tables.py` — 4,514 fluid rows and 1,805 proppant rows over
513 sheets, no sheet missing either block.

## STEP — already half-read

`Treatment Report - Daily Stage Summary`, transposed: the columns are literally
`Stage 01`, `Stage 02`, … and the pages carry 450+ numbers each.

`step_summary.parse_stage_summary` already parses this sheet — that is where
the stage clock comes from (see DATES.md) — and returns a `columns` structure.
**Check what it already exposes before writing anything new**: the schedule
rows may only need surfacing, not parsing.

## Trican layout A — flattened, may be enough

The `STAGE INFORMATION` page prints `DH SLURRY VOLUME` (Pad / Prop / Flush),
`FLUID`, `CHEMICAL` and `PROPPANT` sections. `trican2.parse_page` already
reads these but FLATTENS them to one row per stage — `pad_vol_m3`,
`prop_vol_m3`, `water_m3`, `proppant_t`, `proppant_types`. If the CSV wants a
row per pump step rather than per stage, the section detail has to be kept
instead of summed.

Note for the year rule: the POST-FRAC SUMMARY cover prints
`Start Date : February 16, 2019` and `Finish Date : February 18, 2019` — a
full date WITH a year, which is a better source than `trican2._year_for`'s
span heuristic. Worth switching to, and cheap.

## Liberty — the richest schedule found, and row-wise

Titled `Job Design`; 11 pages across a 3-file sample. Unlike Halliburton and
STEP this one is the ordinary way round, one row per pump step, and it carries
a per-step timestamp, which none of the others do.

Columns measured on 00375 p32: `STAGE #`, `CMTV Reset Vol.`, `Reset Count`,
`Step Date Time` (e.g. `10-10-2024 12:47:00`), `Pressure`, `Rate`,
`STAGE TYPE`, `FLUID TYPE`, `PROPPANT TYPE`, `PPA (kgPA)`,
`DESIGN RATE (m3pm)`, `DESIGN VOLUME (m3)`, `CLEAN VOLUME (m3)`,
`SLURRY VOLUME (m3)`, `PROPPANT (kg) STAGE COUNTER`, and an
`ADDITIVE CONCENTRATIONS` group. Non-pumping steps are labelled in place —
step 4 of that page reads `Shut Down`.

Because it timestamps every step, this is the one schedule that can be lined
up against a chart's own clock, which makes it the natural place to validate
whatever schedule CSV shape gets chosen.

## BJ, Canyon, Sanjel — not found yet, and what was actually checked

- **BJ**: 67 pages of `DC & Workover - WellOps Regulatory Report` match on
  shape, but the one inspected (00418 p19) is well and wellbore METADATA —
  legal location, elevations, casing, kick-offs — not a pump schedule. The
  report has many sections and a schedule may sit deeper in it. Note there is
  an unverified, still-untracked `bj_wellops.py` draft in the working tree
  that presumably reads this report; read it before scanning further.
- **Canyon** and **Sanjel**: nothing schedule-shaped in three files each.
  Three files is thin, and both were sampled from the first drive rather than
  a provider folder, so treat this as "not found" rather than "not present".

## Finding these files at all

Neither drive sorts these four into folders — `__CALFRAC/__HAL/__SCHLUM/
__STEP/__TRICAN` on the newer drive is the whole of it. They live on the first
drive, `/Volumes/For-Chris-CnC-1TB/BCER-Frac`, in 1,451 unsorted
`<index>-<uwi>_<wa>/` folders. Classifying them by each module's OWN detector
over a sample of pages gives:

  Liberty 189, Canyon 89, BJ 71, Canyon+Sanjel 15, unclassified 1,080, error 7

Do NOT classify these by searching for the vendor's name: `bj1.detect` keys on
a Stage title plus a time and a UWI, and `canyon.detect` on `Ticket#:` plus an
axis label, so neither needs the company name to appear and a name scan finds
almost none of them. The 15 Canyon+Sanjel co-detections are Sanjel — a known
overlap that `pipeline.py:1048` already guards by testing Sanjel first.

The classification is cached at `prov_detect.tsv` in the session scratchpad,
and the scanner (`findprov2.py`) is resumable, which matters because the drive
drops.

## Still to do

1. **Halliburton** — write the transposed reader. Explicitly titled, clearly
   laid out, nothing reads it.
2. **CalFrac** — not located. The candidates in 00017 are pages 6-8, which
   carry 28-35 numbers under a `Well Name : / Licence #` header; that may be
   the Multiple-Zone summary `calfrac_progress` already reads rather than a
   schedule. Needs one careful look.
3. **BJ, Liberty, Canyon, Sanjel** — not scanned at all.
4. Decide the CSV shape. A transposed sheet and a row-wise sheet have to land
   in the SAME csv layout, so pick it once — most naturally one row per pump
   step with `stage`, `step`, `fluid`, `clean_m3`, `slurry_m3`, `rate`,
   `prop_conc`, `prop_type`, `prop_mass` — and have each provider's reader
   normalise into it.
