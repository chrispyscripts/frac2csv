# Stratum handoff — 2026-09-17: the BC survey grid on the map view

One job: **put the DLS and NTS survey grids on Stratum's map view, drawn and
labelled.** The data is prepared and tiled; none of it is wired into the map
yet. That wiring is the work.

Stratum is `frac-pdf-extract/frac2csv/web`, deployed to Vercel as
`frac2csv-web` (account `chrisjayharder-2305`, use `npx vercel`). Repo
`chrispyscripts/frac2csv`, branch `main`. The map view is
`web/public/map.html` — MapLibre GL 4.7.1 off unpkg, an Esri dark-grey raster
basemap, and GeoJSON sources fetched from `public/data/`. Today it carries one
set: `data/pads/index.json` → the Gundy cluster, 8 pads / 76 wells, centred
56.794 / −122.115.

## 1. What Chris decided

Asked how much of the grid to carry and which families, he chose:

- **Whole NE BC, as vector tiles** — not clipped to where Stratum has data. The
  grid has to work for any cluster added later without regenerating.
- **Both NTS and DLS.**

Those two answers are why the pipeline below exists in the shape it does.

## 2. The source, and the one fact that shapes everything

`~/Downloads/_BC-NE-DLS-NTS-Nad83-ESPG-4269.zip` — 500 MB unpacked, 54 files,
nine shapefile layers. **EPSG:4269 (NAD83 geographic), so the coordinates are
already lon/lat degrees — nothing reprojects.** NAD83 sits within a couple of
metres of WGS84, far under a grid line's width. Chris picked that projection
deliberately; do not undo it.

| layer | polygons | shp | LABELTEXT reads |
|---|---:|---:|---|
| `NTSPRI` | 2 | 0.1 MB | `93` |
| `NTSLTR` | 24 | 0.2 MB | `93-I` |
| `NTSSIX` | 343 | 0.8 MB | `93-I-1` |
| `NTSBLK` | 4,044 | 2.9 MB | `A` |
| `NTSUNIT` | 403,458 | 55 MB | `1` |
| `NTSQTR` | **1,613,832** | **220 MB** | `A` |
| `DLSTWP` | 201 | 0.2 MB | `76-12W6` |
| `DLSSEC` | 6,386 | 1.3 MB | `1` |
| `DLSLSD` | 101,656 | 14 MB | `1` |

**DLS does not reach the current data.** It covers the Peace River Block only —
lon −121.99…−119.71, lat 55.55…56.68. Gundy is at −122.115, just west of the
edge. So on today's map DLS will draw nothing; it is there for the AER/Alberta
side and for BC wells inside the block. NTS covers all of NE BC and is what
Gundy is located in. Do not read an empty DLS layer over Gundy as a bug.

**The fine levels' labels are relative, not qualified.** A quarter unit's
`LABELTEXT` is just `A`. The full BC location (`A-038-L/094-H-05`) has to be
composed from the levels containing it — see §5.

## 3. The pipeline (done — this is background, not work)

There is **no GDAL, no ogr2ogr, no geopandas/fiona/shapely** on this Mac, and
none is needed. `web/scripts/grids/shp2ndjson.py` is a stdlib+numpy shapefile
and dbf reader that streams each layer to newline-delimited GeoJSON — streams,
because `NTSQTR` is 1.6 M polygons / 355 MB of JSON and nothing may hold it all.
`web/scripts/grids/convert_all.sh` drives all nine.

Two things it does that matter downstream:

- Coordinates rounded to 6 decimals (~0.1 m), finer than any survey corner needs.
- **Every feature carries `cx`/`cy`, its own area-weighted centroid.** This is
  for labelling. A cell straddling a tile boundary arrives at the client in two
  pieces; a label placed on a piece's centre lands off the cell and lands twice.
  `cx`/`cy` is identical on both pieces, so the client can place exactly one
  label in the right spot. Do not label from rendered geometry.

`tippecanoe` v2.79.0 is installed (`brew install tippecanoe`). **One archive per
level**, each tiled only over the zooms where it is legible — a survey grid must
be *complete* where it is drawn, so there are no `--drop-densest-as-needed` style
flags anywhere; the zoom bands are what keep tile density sane instead.

```
tippecanoe -o <level>.pmtiles -l <level> -n <level> -Z<min> -z<max> \
  --no-tile-size-limit --no-feature-limit --detect-shared-borders \
  --simplification=2 --force <level>.geojsonl
```

| level | -Z | -z | built size |
|---|---:|---:|---:|
| `nts_pri` | 4 | 8 | 0.01 MB |
| `nts_ltr` | 5 | 9 | 0.02 MB |
| `nts_six` | 6 | 10 | 0.15 MB |
| `nts_blk` | 8 | 12 | 1.69 MB |
| `dls_twp` | 6 | 10 | 0.03 MB |
| `dls_sec` | 9 | 13 | 1.03 MB |
| `dls_lsd` | 11 | 15 | 13.14 MB |
| `nts_unit` | 10 | 14 | 37.55 MB |
| `nts_qtr` | 12 | 15 | **was still building at handoff — check** |

**Built tiles are in `web/public/data/grids/`.** Eight of nine were there at
handoff; confirm `nts_qtr.pmtiles` landed and is non-trivial in size before
wiring it. If it did not, rerun the tippecanoe line above against
`nts_qtr.geojsonl`.

**The `.geojsonl` intermediates are NOT in the repo** — they total ~530 MB and
lived in a session scratchpad under `/private/tmp/claude-501/…` that gets swept.
To regenerate: unzip the download again and run
`bash web/scripts/grids/convert_all.sh` (edit the `SP` path at the top first).
Budget ~20 minutes, most of it `nts_qtr`.

## 4. What is actually left: the map integration

None of this exists yet. All of it is in `web/public/map.html`.

1. **Load the pmtiles protocol.** The page takes MapLibre off unpkg already;
   match that. `https://unpkg.com/pmtiles@3/dist/pmtiles.js`, then
   `maplibregl.addProtocol("pmtiles", new pmtiles.Protocol().tile)`.
2. **Nine vector sources**, `pmtiles://data/grids/<level>.pmtiles`, each with the
   source-layer name matching the level id. Vercel serves static files with HTTP
   range support, which is the whole reason pmtiles works here with no server.
3. **Line layers with display bands that hand off cleanly**, coarse levels heavier
   and brighter, fine levels thinner and dimmer, so the nesting reads like a plat.
   Note MapLibre will happily overzoom past an archive's `-z`; that is intended,
   the grid should stay visible when you zoom past 15.
4. **Labels — read §5 first, this is the trap.**
5. **A layer toggle**, NTS / DLS / off. The `.legend` box top-right is the
   natural home; `cluster-underground.js` already positions its own button
   relative to that element's rect, so if you resize or restructure the legend,
   check that button still lands correctly.
6. **A hover/click readout** composing the fully-qualified location.

## 5. The labelling trap — read before writing any symbol layer

**The base style carries no glyphs, so a MapLibre `symbol` layer cannot draw
text on this map at all.** This is already known in the codebase — `map.html`
renders the eight pad names as HTML markers with a comment saying exactly this.
A `symbol` layer with `text-field` will silently render nothing.

Two ways out:

- **HTML markers** (consistent with what is there). Recompute on `moveend` from
  `map.queryRenderedFeatures({layers:[…]})`, place each at its feature's
  `cx`/`cy`, dedupe by `cx,cy`, and gate hard on zoom *and* on-screen cell size —
  label only cells bigger than ~40 px, capped at a couple of hundred markers.
  At z15+ that is a few dozen on screen, which is fine; without the gate, a
  quarter-unit layer will try to place thousands and the map will die.
  No new dependency, no download.
- **Add a `glyphs` URL to the style** and use real symbol layers, which gets you
  MapLibre's collision detection for free. Means self-hosting a font's PBF range
  files under `public/` (a third-party glyph endpoint is not something to depend
  on in production). That is a download, so ask Chris first.

I would start with markers because it matches the existing code and can ship
today, and treat glyphs as the upgrade if label density gets unpleasant.

**Composing the full location:** each level only knows its own relative label.
`queryRenderedFeatures` at a point returns features from *every* visible layer,
so the client can read `nts_qtr` + `nts_unit` + `nts_blk` + `nts_ltr` + `nts_pri`
under the cursor and assemble `A-038-L/094-H-05` with no offline join and no
extra data. Put the qualified string in the hover readout; leave the polygons
labelled with their own short `LABELTEXT`, which is how a surveyor reads a plat.

## 6. Before you commit

`web/public/` has **uncommitted changes from the session before this one** that
are not mine and not part of this job:

```
cluster-underground.css   cluster-underground.js
data/engineering-import.json   data/underground.json
pad.html   well.html
```

They are the underground-explorer work — depth intervals, the pad-page iframe,
the "treatment-stage matching is unverified" caveat — and they appear to be
live on Vercel already but were never committed. **Do not sweep them into a
grid commit.** Either commit them separately with their own message after
checking with Chris, or leave them be.

Also weigh the deploy size: the tiles are ~53 MB plus whatever `nts_qtr` comes
to. The repo already commits large data under `web/public/data/` (`ab-wells.json`
is 27 MB), so this is in keeping — but it is worth a look at Vercel's limits
before the first `npx vercel deploy --prod` with the grid in.

## 7. Verify like this

`.claude/launch.json` may not have an entry for Stratum; it is a static site, so
serving `web/public` is enough. Check, in this order, because each one fails
differently:

1. The pmtiles archives answer range requests at all (network panel, 206s).
2. One coarse level draws — `nts_pri` at z5 — before you touch anything fine.
3. `nts_qtr` draws at z14 and the tiles are not enormous.
4. Labels appear, in the right place, and **do not double up** — pan a cell
   across a tile seam and watch it. That is what `cx`/`cy` is guarding against.
5. DLS is empty over Gundy and non-empty over the Peace River Block (pan east
   past −121.99). Both are correct.

## 8. Gotchas

- The grids are in degrees. Nothing reprojects. Resist adding proj4.
- No dropping flags in tippecanoe: a gap in a survey grid is a lie.
- `NTSQTR` is 1.6 M polygons. Never load it as GeoJSON, in any form, anywhere.
- `symbol` layers draw nothing on this style (§5).
- The DLS extent is a real boundary, not missing data (§2).
- Volume names in paths contain spaces; anything parsing them should stop at `/`,
  not at whitespace.
