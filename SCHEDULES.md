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
| BJ, Liberty, Canyon, Sanjel | not scanned | — | no |

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
