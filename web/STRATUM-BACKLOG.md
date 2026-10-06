# FracView feature list

FracView was called Stratum until 2026-10-05; code, storage keys and file
names still say stratum (renaming them would sign everyone out and drop saved
settings), only what people see changed.

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
- **Wine-rack view** (2026-10-03; rebuilt 2026-10-05). From the button on each
  pad's toes in the 3D view. No 3D behind it any more: the canvas, the 3D panel
  and its camera/quake controls step aside and the rack takes the width. Left
  (above, on narrow screens): the pad from overhead, turned so its laterals run
  left to right, with a straight line across them to drag along -- or the
  slider, ▶ to play it heel to toe, ← → (shift for 250 m). Right: the section
  across the pad at that line -- each well where it crosses, by offset across
  the pad and TVD, labelled with the stage it is in there, coloured by pad or by
  gamma at the line, with the spacing between neighbours along the top. Wells
  drop in through their landing curve (dashed) as the line reaches them and drop
  out past their toes; the frame stays fixed for the pad so wells move within
  it. Since 2026-10-05 (later) it opens in a window of its own
  (`winerack.html?pads=a,b`, named `stratum-rack`), from the map's pad popup or
  the 3D view's buttons, and the page that asked stays as it was; each pad after
  it is stacked underneath (↑ to reorder, × to close). The well's 2D section
  stays in the main window's dock: opening a rack shows its middle well there,
  a well clicked in the rack switches it, and the rack's line moves a cursor
  along that well, picking out the stage at the line with its chart as if
  hovered (BroadcastChannel `stratum-rack`, wellsection-host.js). Lines, colour
  and the picked well come back with the window and with sessions.
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
- **Engineering-grade seismicity** (2026-10-03). build_seismic.py merges the
  BC Seismic Research Consortium's relocated catalogues (May 2022-Apr 2024,
  ~250-600 m location error) over Earthquakes Canada, and matches each event to
  the frac stage pumping nearby (Lab chart clocks / BCER frac start times, local
  UTC-7). A control (dates shifted +-30/60 days) says ~68% of matches are
  beyond chance; matches are labelled "coincides with", not cause, because
  zipper fracs keep some stage pumping at all times. build_gmmr.py parses the
  ground-motion monitoring reports (Spectraseis, Nanometrics) filed per well:
  triggers, peak %g vs the 0.8 %g BCER threshold, felt reports, and the stages
  pumping when each trigger fired. Shown in the pad panel (3D) and as markers on
  the well's stage chart. Older relocated catalogues are PDF-only; GMMR
  miniSEED waveforms are not drawn yet.
- **Only wells with charts, for now** (2026-10-04). The map, the 3D view and the
  wine rack show only the wells whose Lab treatment curves are in (1,040 of
  2,917; 154 of 495 pads). The legend's "only wells with treatment charts" box
  is on by default and remembered per browser; untick it for every well.
- **View well: the whole well in 2D** (2026-10-04). A highlighted "View well" in
  a well's map popup and in the 3D view's well panel opens `wellsection.html`:
  a vertical section from the pad's surface location to TD along the line to
  the toe, with the build, heel, lateral, every filed stage as a tick at its
  measured depth (teal = treatment curves in, slate = filed only), gamma along
  the lateral and as a track under it, KB / sea level / ASL axis. Whole well
  (fitted, depth stretch labelled) or Lateral (depth stretched so undulation and
  toe-up/down show). Hover reads MD, TVD, ASL, gamma and the stage's pump data;
  click a stage for its charts. It docks under the map (drag the grip to size
  it; it comes back after Back) or in the 3D view's bottom panel in place of the
  pad data (× returns it). Pop out ↗ moves it into its own window that follows
  the selected well and the stage on the charts page (BroadcastChannel
  `stratum-section`, addressed to the main page by id and acknowledged); ↙ Dock
  puts it back under the map, and the charts page has "Section ↗" too.
  Picking a well (map lateral, sidebar list, 3D click or the 3D well menu) now
  opens this view straight away (2026-10-05); locking a pad still shows its pad
  data until a well is picked, and View well reopens it after ×.
  Clicking a stage (or Charts →) opens its charts in a window of their own
  (2026-10-05), so the map or 3D view stays put: one window, reused, picking
  the stage without a reload when it already shows the well. Popped out beside
  a well's charts page, the stage is picked on that page instead.
  Hovering a stage (or stepping with ← →) shows its stage chart as a
  thumbnail above it: the Lab's curves in the stage chart's names and colours,
  each on its own rounded scale, curves hidden on the charts page hidden here,
  with peaks, date/duration, what was pumped and the depth readout. In a short
  dock it sits beside the stage instead; filed-only stages show their summary.
- **Session files** (2026-10-04). "Sessions" (map sidebar, charts page) saves
  the whole workspace under a name: every open Stratum window (map, 3D view,
  charts, popped-out section, compare, pad pages), where each sits on screen,
  what each shows (3D camera/pad/well/stage/wine rack/section, map camera, open
  pads, earthquakes, survey grids, docked section, compare channels/axis/scale,
  chart tab), and the settings (charted-only filter, hidden curves, section
  prefs and dock height, compare wells). Kept in this browser and downloadable
  as `<name>.stratum-session.json`; "Open a session file…" loads one back.
  Opening Stratum fresh offers the saved sessions first ("Pick up where you
  left off"). Opening one turns this window into the saved main window and a
  bar reopens the others where they were; a browser allows one window per click
  unless pop-ups are allowed for the site. `web/public/session.js` (loaded in
  every page's head) holds it: windows answer a save over BroadcastChannel
  `stratum-session`, reopened windows get their state by a one-time
  localStorage hand-off, and files are filtered to Stratum pages and
  `stratum.*` keys. No accounts yet: when sign-in arrives, the same session
  JSON can be stored per user.

- **Gamma colour schemes** (2026-10-05). Amber, Viridis, Sand → shale (the log
  convention) and Cool → warm (diverging on the lateral median: outliers jump).
  One setting (`gamma-palettes.js`, localStorage `stratum.gammaPalette`) for the
  3D view (swatches in its gamma legend), the wine rack (menu in its key) and
  the well section (menu beside Stages | Gamma); every step clears 2.3:1 on the
  dark ground. A change in one window recolours the others.
- **Quake filter** (2026-10-05). Dates, magnitude min/max, hide undetermined
  depths, only those coinciding with a stage, only relocated (BCSRC). One
  setting (`quake-filter.js`, localStorage `stratum.quakeFilter`) for the map
  ("Filter quakes…" under the earthquakes box), the 3D view ("Filter" beside
  Quakes; its summary says what is filtered) and a well's charts (stages marked
  and markers drawn by it; a stage notes quakes the filter hides). The pad's
  accelerometer triggers are not filtered. Saved with sessions.
- **Ellipsoid positions** (2026-10-05). Survey offsets become latitude and
  longitude on NAD83's ellipsoid (`web/scripts/geodesy.py`; region map paths,
  earthquake matching, gamma neighbours) instead of a flat 111,320 m per degree:
  the test pad's toes now sit within ~2 m of a mapping package's bottom-hole
  positions (were 6-9 m). Sources: surface from the BCER wells table, path and
  toe from its directional survey (deepest drilling event).
- **Light theme, the default** (2026-10-05). `theme.js` sets
  `<html data-theme>` before paint from `stratum.theme` (light unless dark is
  chosen); a sun/moon switch sits by Sessions on every page and the choice
  follows across windows and sessions. Light basemap (Esri Light Gray), pad
  colours re-picked for white (validated for colour-blind separation), gamma
  schemes with light-ground stops (high gamma darkest), the Lab pages in their
  own light colours (sync_lab_views.py patches are now theme-aware). Dark is as
  before.
- **Arrow keys in 3D** (2026-10-05). As on the map: arrows move, Shift + arrows
  turn and tilt, + / − zoom; held keys keep going smoothly.
- **Pressure and rate along the well** (2026-10-05). The 2D well section draws
  each stage's treating pressure over its slurry rate in a strip above the
  well, spanning the stage's own stretch of hole, one scale for every stage;
  hover a stage there for its full chart, click for its charts. "Curves"
  toggles it.
- **Stage charts in their own windows** (2026-10-06). A stage clicked on a
  well's 2D view (on the well, its tick, or its curves above) opens its chart
  in a window (`stages.html?s=WA:stage,…`); with a stage window already open, a
  small dialog asks: stack it under the charts there, or open a new window.
  Each card is the charts page's stage chart (`wellview.html?solo=1`: zoom,
  pan, hide curves), with ‹ › to step that card's stage, Charts ↗ for the
  well's full charts, ↑ and ×. Windows say what they hold over
  `stratum-stages`; they come back with sessions. "Charts →" on the section
  still opens the well's full charts.
- **No pad page** (2026-10-06). `pad.html` on its own redirects to
  `map.html?pad=ID`, which centres the map on the pad with its popup open; the
  popup's "Pad data" link is gone, and the charts page's Back closes a window
  FracView opened (or goes to the map at the pad) instead of landing there.
  The 3D view's bottom panel still uses it embedded (`?embedded=1`).
- **Easier picking on the map and in 3D** (2026-10-06). The well under the
  pointer is outlined in ink and drawn thicker (map: a wide invisible stroke
  catches the pointer; 3D: hover targets all along each path); hovering a well
  or pad in the sidebar list picks it out on the map. Pad circles are about
  half again bigger (map and 3D). Pointing at the toe end of a pad on the map
  offers "Wine rack ↗" just past the toes, as the 3D view does; a pad drilled
  both ways offers it at each end.
- **Saved sessions belong to the account** (2026-10-06). `/api/sessions`
  (lib/saved-sessions.js) keeps each account's sessions in the private Blob
  store, `sessions/<account id>/<id>.json` plus an `index.json`, the account id
  taken only from the signed cookie (the same sha256-of-email the account is
  filed under), so one account can neither list, open nor delete another's.
  Same name replaces; 60 per account, oldest dropped. The Sessions panel lists,
  opens, saves and deletes through it; a browser's old local list is carried
  over to whoever opens the panel signed in there, once, then cleared. Files
  (download / open a file) work as before. Settings (theme, gamma colours,
  quake filter) are still per browser.
- **Private, invite-only** (2026-10-04). Every page, data file and the extractor
  need a signed-in account (`web/middleware.js`, Vercel Routing Middleware, before
  anything is served); only `login.html` and `/api/auth` are open. Accounts are
  created with an invite code an admin makes on `admin.html` (Invites & accounts:
  note, role, uses, expiry, copy code / invite link, withdraw; accounts list with
  reset code and remove). Reset codes set a new password (no email needed).
  Accounts and codes live as JSON in the private Vercel Blob store
  `stratum-accounts` (dev: `stratum-accounts-dev`); passwords are scrypt; the
  session is a signed `__Host-stratum` cookie (SESSION_SECRET), 14 days, and the
  middleware re-checks the account hourly so a removed account is out within the
  hour. The first admin comes from STRATUM_BOOTSTRAP_CODE (one use, and only
  while no admin exists, so earlier invitees signing up first can't block it). Later: per-user saved sessions on the server, rate limiting
  on sign-in (Vercel Firewall), email for resets.

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
