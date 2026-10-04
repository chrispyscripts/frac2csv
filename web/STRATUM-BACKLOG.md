# Stratum feature list

Features Chris has asked for, in the order asked. Newest status at the top of
each entry.

## Done

- **Gamma-coloured wells** (2026-10-03). Underground view, Colour: Pad | Gamma.
  `web/scripts/build_gamma.py` → `data/gamma.json` from the eLibrary LAS files;
  46 of 76 Gundy wells have a gamma log, the other 30 draw dashed.
- **Well page = the Lab's charts** (2026-10-03). `wellview.html?wa=&stage=` is
  now Stage chart (curves hide on click, isolate on double-click) | Stacked |
  FracView. Stacked and FracView are the Lab's own pages, generated into
  `public/lab/` by `web/scripts/sync_lab_views.py` (re-run it to pick up Lab
  changes): FracView gets host() so it can talk to a parent frame, and both get
  Stratum's dark theme and the stage chart's curve colours. The old 3D single-well
  dashboard and its stage-reconciliation panel are gone from this page.
- **Wine-rack view** (2026-10-03). A "Wine rack" button rides on each pad's
  cluster of toes in the underground view; it turns the camera to look down the
  laterals and opens a 2D section of that pad: each well end placed by offset
  across the pad and toe TVD, its lateral traced behind it, coloured by pad or
  by lateral median gamma, hover for spacing to the nearest end, click to open
  the well's charts. Back from the well page lands in the rack again.

- **100 km region around Gundy** (2026-10-03). `web/scripts/build_region.py`
  builds every surveyed, fractured BC well within 100 km (2,917 wells, 495
  pads) from the BCER bulk files: pads by surface location, per-pad files for
  3D, the map's pad set, and a well file per well with its filed stage
  summaries. The map lists the pads in view and opens 3D / wine rack from a
  pad's popup; Change View opens 3D on the pads in view (nearest 30). Wells
  without Lab curves show their filed stages as a table.
  The 2TB drive's Lab CSVs added 113 more region wells' curves (199 in all).
  Pending: gamma beyond Gundy (eLibrary LAS fetch).

- **Demo areas** (2026-10-03). Town North (PETRONAS), Nig Creek (CNRL +
  Tourmaline), Altares (Canbriam), 10 pads each, plus Gundy; one click each
  from the map's sidebar. Lab TXT lists for their PDFs in
  `frac-pdf-extract/demo-lists/`. Overnight: `~/stratum-lab/run-clusters.sh`
  reads them headless (lab_batch.py, Lab v1.11.33), imports, rebuilds and
  publishes via `~/stratum-lab/after-clusters.sh`, then reads the rest of the
  region's drive PDFs to `/Volumes/CnC-2TB-ssd/Stratum-Lab`.
- **Earthquakes** (2026-10-03). Earthquakes Canada catalog (build_seismic.py),
  Quakes toggle in 3D and on the map, matched to nearby frac jobs.
- **Gamma for every demo well** (2026-10-03). LAS for the 216 demo wells that
  filed one (eLibrary), every vendor mnemonic; the 97 with none get an offset
  estimate (neighbours at the same subsea depth), drawn dashed and scored.
  Follow-ups: 10 wells have a printed log PDF only -- a validated PDF reader
  (draft in ~/stratum-lab/gamma_from_pdf_experimental.py) would make them
  measured; vendor normalisation would sharpen estimates.
- **Found: GMMR = ground-motion monitoring reports** (miniSEED waveforms +
  PDF) filed per well during fracs -- the per-pad seismic record. Not yet used.

## Asked for, not started

- **All BC wells.** Estimate given 2026-10-03: paths, stage summaries and
  perforation intervals for all ~5,800 fractured BC wells from the IRIS bulk
  files already on disk (2–3 days, needs a pad/area picker in 3D); gamma via an
  eLibrary LAS fetch (~11 GB, ~1 day); treatment curves need ~11,000 completion
  PDFs through the Lab (~600–950 CPU-hours, 1–2 weeks with QA, partial
  coverage by vendor).

## Suggested, not asked for

- **Induced seismicity near each pad.** Public: BCER seismicity map (ML ≥ 1.5)
  and Geoscience BC's annual event CSV. Would draw as events by time and depth
  in the underground view.
- **Full-resolution curves.** The well page draws the ~350-point series in
  `data/wells/<WA>.json`; the Lab's 1-second exports for all 76 Gundy wells are
  in `exports/bc-gundy-cluster/lab-seconds/` (1.2 GB as CSV) if spikes matter.
- **logs_from_las.py misses GAM / MWD_GAMMA / MG1C**, so `well.html`'s GR track
  lacks 8 wells that `build_gamma.py` reads.
