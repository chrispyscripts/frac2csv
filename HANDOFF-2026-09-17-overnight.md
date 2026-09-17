# Handoff — 2026-09-17 overnight

> **Update 2026-09-17 01:20 MDT, from the Mac — §4 items 1–5 are done.**
> Tests: `f450260` failed two `test_trican_under` cases because `_deduce_under`
> now returns the deduced column sets, not counts — the tests were updated
> (`8d1a74f`), 601 pass. All commits were already on `origin/main`. The v1.10.0
> release carries `release-notes/v1.10.0.md` and the EXE. The pad page's
> "Stages (BCER)" column read `w.depth_intervals`, which `pad_json.py` did not
> write to the pad entries; it now writes `depth_intervals` and `summaries`
> per well, and the site is redeployed. The two Claude-launched portals were
> restarted on the new code with pinned ports: **http://127.0.0.1:8801/ and
> :8802/** (50903/50904 stopped; 50821/60066 from Sep 13–14 left alone). The
> results cache was emptied: its 76 Gundy entries were pre-`f450260` reads.
> Open: §5, the gap goal — start with the 40-file sample scoreboard.

Continues `HANDOFF-2026-09-16-evening.md`. Repo `frac-pdf-extract/frac2csv`,
`main`, remote `chrispyscripts/frac2csv`. Long-lived notes stay in `HANDOFF.md`.

**This session ran in Cowork — a cloud container with a two-folder bridge to the
Mac.** No macOS processes, no `/Volumes`, no git/gh/vercel credentials, no
`fitz`, no `pytest`. That is why everything below that needs the machine is
still open. Run the rest from Claude Code on the Mac.

## 1. Three commits, none pushed

- `2e9bfb8` **Stratum: every Gundy well with its treatment curves.** 68 files,
  all under `web/public/data/`. `stages_from_csv.py` then `pad_json.py` over the
  76 lab-seconds exports: "76 wells with Lab exports, 0 without"; `gundy.json`
  has 8 pads / 76 wells. Spot-checked 28744: 43 stages, press/rate/wh_conc/
  bh_conc at 342 points each, 190 trajectory stations, `bcer_stages` and
  `depth_intervals` preserved.
- `629d416` **Lab: `F2C_PORT` pins the portal's port.** `main()` bound to port 0,
  so every launch took a random ephemeral port. `F2C_PORT=8801 F2C_NO_BROWSER=1
  python3 localapp.py`. Unset or 0 keeps the old behaviour. `localapp.py` is in
  `_NOT_A_READER`, so this alone retires nothing.
- `f450260` **Conc curves: deduce the hidden one per chart, and flag it.** See §3.

The export run from the evening finished on its own: **76/76 seconds CSVs at
20:57**, 0 failures. Whatever was killed, it was not that.

## 2. The Trican "files not found" — it was `_ROOT_CACHE`

Not the drive letters, not the lists. `find_drive_roots()` caches which volumes
hold a top folder (`BCER-Frac`, `AER-Frac-Montney-ARC`) **the first time it is
asked, for the life of the process**. A portal started while the 1 TB drive was
unmounted has that frozen and keeps reporting those files missing however many
drives you plug in afterwards.

**Fix: restart the portals.** Verified against the live Lab with both drives
mounted — 28 files probed across all eight `trican1` batches, including the
names most likely to break (spaces, `INITIAL COMPLETION`, `.CSV.PDF`, the `XX-`
duplicate, `M04-17 REV`, the two identical AER basenames): **28/28 resolved in
under 0.1 s**, 24 off `For-Chris-CnC-1TB`, 4 off `CnC-2TB-ssd`.

The lists never needed editing. `find_drive_roots` strips the drive letter and
`index_pdfs` matches on basename anywhere under the root, so `K:` / `L:` and the
`_TRICAN-Type` folder are all irrelevant. Both drives carry a `_TRICAN-Type`.

## 3. `f450260` in detail — what changed and what it costs

**The bug.** `_UNDER_PAIRS` hard-coded `("wh_conc", "dh_conc")` from legend
order, so WH was recovered from under DH and never the reverse. On a report that
paints the wellhead trace last it is the DOWNHOLE curve that vanishes and
exports flat — the "BH prop conc hidden under the other data set" report.

**`_conc_under(traced)`** now reads the direction off each chart's own pixels:
for each of the pair, count the columns inside its OWN drawn span where it has
no ink and the other does. Needs a clear margin — twice as many and ≥20 columns
— before it overrides the legend. The conc pair is out of `_UNDER_PAIRS`
entirely, so the two can no longer fill from each other's filled traces.

**Deduced samples now travel labelled.** `_deduce_under` returns the column sets;
`extract_image` resamples them onto the value grid as a per-sample `deduced`
bool; `_series()` and all four pipeline flatten sites carry it; `localapp`
ships it as `deducedRuns` (spans, not a 300k array); the Lab chart draws those
stretches in **pulsing black** over the curve, with a pale under-stroke so they
read on the dark blueprint. One clock, loop only turns while a span is on
screen, gated to ~16 fps.

**`gaps.py` is finally on the Lab's read path.** It has classified gaps since it
was written — lead / trail / at-floor / at-ceiling / missing / unknown — but only
`audit.py` ever called it. Channels now carry `gapKinds` and `gapNote`, with the
axis taken from the frame reading or the printed ticks. No axis ⇒ everything
stays `UNKNOWN`, which is the honest answer.

**Costs and holes:**
- Editing `trican_charts.py` and `pipeline.py` changed `code_stamp()`, so **the
  entire results cache is retired** — 441 wells re-read. The re-key script in
  §3.2 of the evening handoff is moot.
- **Layout B never calls `_deduce_under` at all.** Two `extract_image` paths,
  only the first deduces. That path has had this bug untreated in both
  directions from the start. Not fixed; wants a layout-B page to look at.
- **The tests were never run.** Syntax-checked with `ast.parse` only; this
  container has no `pytest` and no `fitz`. Run `python3 -m pytest tests -q`
  before trusting `f450260`.

## 4. Open, in order — all of it needs the Mac

1. `python3 -m pytest tests -q` against `f450260`.
2. `git push origin main` (three commits).
3. `gh run view 35173203549 --json status,conclusion` then
   `gh release edit v1.10.0 --notes-file release-notes/v1.10.0.md`.
4. Stratum deploy: `cd web && npx vercel deploy --prod --yes`. Check
   `pad.html?set=gundy` first — the header says "3219 stages at BCER depths"
   while the per-well `Stages (BCER)` column reads `–` for every row visible
   across pads 1-3. Either the column is keyed off something `pad_json.py` does
   not write, or the total counts from a different source.
5. Restart the portals so `_ROOT_CACHE` re-reads both drives (§2).
6. The goal, below.

## 5. The goal Chris set

**Every gap in `step1` and `trican1` is accounted for** — 777 files, 407 STEP +
370 Trican, from `batch-lists/by-type/`. Not "no blank samples": `gaps.py`
measured that 84% of the 8,148 blank columns in Trican's WH Prop Conc are lead
and trail, the pad and the flush, and of 66 mid-chart runs exactly one had the
curve at zero on both sides. Filling those would invent concentration.

Goal condition — **zero `MISSING`, zero `UNKNOWN`**:

- `MISSING` (mid-flight both sides) → `gaps.interpolate(vals, gaps,
  kinds=(MISSING,))` and flag. Evidence brackets it.
- `UNKNOWN` (axis unread) → fix the axis read so it classifies at all.
- covered → deduce from under and flag. Done for layout A, open for layout B.
- lead / trail / at-floor → left as gaps. Not data.

First move is the scoreboard, not the fix: run `audit.py`'s classification over
both corpora, count `MISSING`/`UNKNOWN` per file per channel, rank by cause.
That says whether this is five defects or five hundred. At the export run's
3-5 min/file this is 40-65 h single-threaded, 8-13 h at five workers, and the
cache is empty, so budget for a real job. A 40-file sample across both corpora
and every template gives the defect shape in under an hour.

## 6. Also landed tonight (outside the repo)

`For_Chris-testing.zip` (122 MB, 66 files, all verified byte-for-byte) unpacked
into two homes under `frac-pdf-extract/`:

- **`bcer-iris-2026-09-10/`** — province-wide BCER IRIS pull, history to
  2026-SEP-10, and the first copy of these tables kept in the project
  (`validate_step.py` and `build_well_map_data.py` still point at `/tmp`):
  `dir_survey.csv` (2,025,777 stations, 171 MB), `hydraulic_fracture.csv`
  (176,822), `perf.csv` (104,095), `perf_net_interval.csv` (558,966), the column
  dictionaries, and `wells_and_attribute_data-New-BC.csv` (49,345 wells).
  `_regulator-ops-files/` holds six Oracle/WebLogic logs the regulator shipped
  by mistake — no well data, safe to delete.
- **`exports/bc-gundy-west/`** — Petronas Gundy Creek West, WA 40067-40076,
  Montney A, fracced 2024-APR-24, the pad west of the Tourmaline cluster.
  `lab-seconds/` (10 files, 365 stages, 2.39 M rows), `LAS/` (33 logs — two per
  well except 40070, which has 15), `docs/` (40070's geology report and two
  stitched striplogs), the well header grid, and a `.pha`. Not in Stratum yet;
  the IRIS pull covers these wells (2,559 survey stations, 366 frac rows, 332
  perf, 3,054 interval), so a cluster TSV and a trajectories cut would make them
  loadable the way Gundy was.

**`wells_and_attribute_data-New-BC.csv` carries production** — `cum_oil/gas/
water`, `recent_*`, current to 2026-07-01, 21,749 wells with cumulative gas —
plus surface AND bottom-hole lat/lon for all 49,345. Nothing else in the project
has production. **Trap: sixteen columns are empty in every single row**,
including `operator`, `active_event`, `fluid`, `status`, `type` and `pb_depth`.
Use `licensee` for the company and `trajectory` for horizontal-vs-vertical.

## 7. Gotchas

- A portal caches its drive roots at first use (§2). Restart after mounting.
- Editing any reader retires every cached result. `localapp.py`, `version.py`
  and the Stratum builders do not.
- Well 40070's seconds CSV: labels do not track stage numbers — stage 13 is
  `12A HRF`, 14 is `12B`, so everything after runs one behind and the last stage
  is 34 labelled 32. `12A HRF` pumped no proppant at all (max WH and BH conc
  0.0) — a diverter or acid stage, not a frac stage.
- ISIP read one second after rate drops below 0.5 m3/min climbs 27 → 38 MPa
  across that well's lateral. Real stress trend, and the thing Petro.ai sells as
  a product. Stages 2 and 5 come back at 74 and 79 — rate did not fall cleanly,
  worth a look.
- Claude-in-Chrome was still not connected. The built-in browser pane in the
  desktop app DOES reach `127.0.0.1`, which is how the Lab's `/api/manifest` was
  driven for §2.
