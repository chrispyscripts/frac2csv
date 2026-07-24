# Calfrac "Summary Tables" — variable catalogue

Field inventory for the planned **Summary Tables** screen. Mined from every
Calfrac-branded page found on Carmine's drive (214 files, 1,219 summary
pages), reading the label column by x-position and pairing each label with
the unit printed in its `U of M` column.

No parser has been written yet — this is the scoping pass.

## Two layouts

| | Layout A — modern | Layout B — legacy |
|---|---|---|
| Page title | `Treatment Summary` | `Multiple Zone Frac Treatment Summary` |
| Vintage | 2024+ | ~2013–2016 |
| Pages found | 804 | 415 |
| Units | explicit `U of M` column | baked into the label text |
| Zones per page | 5–8 columns, continues on next page | up to 10 columns, one page |
| Sections | left-column group headings | ALL-CAPS band headings |

Both are **zone-major**: one column per stage, one row per variable — the
transpose of the per-second CSV. A row's `U of M` cell makes Layout A far
cheaper to parse; Layout B needs a label→unit table.

Layout A splits across two pages (`Zone`/`Treatment Summary` repeat, page 2
usually holds only `Comments`), so a well's zones must be stitched across
page breaks.

---

## Header block — one set of values per job

Present in both layouts, above the zone grid.

**Identity** — `UWI`, `LSD`, `Well License`, `Customer`, `Job Date`,
`Job Type`, `Program Number`, `Service Order #`, `Calfrac Service Line`,
`Formation`, `Calfrac Rep`, `Calfrac Supervisor`, `Customer Representative`

**Well construction** — `Casing`, `Tubing`, `Liner`, `Annulus`, each with
`OD (mm)`, `Weight (kg/m)`, `Grade`, `Capacity (m³/m)`, `Max Pres. (MPa)`,
`Depth (m)`, `Volume (m³)`

**Well state** — `BHT (°C)`, `PBTD (m)`, `Packers (m)`, `TVD (m)`, `MD (m)`,
`Treatment Mode`, `Well Config`

**Programme limits** — `Maximum Treating Press (MPa)`, `Pressure Test (MPa)`,
`Frac Gradient (kPa/m)`, `Frac Gradient Mini Frac (kPa/m)`,
`Annular Relief Set (MPa)`, `Annulus Pressure (MPa)`, `Flush Density (kg/m³)`

**Shut-in pressures** — `Mini Frac/Acid ISIP Press (MPa)`,
`Final Treatment ISIP Press (MPa)`, `1 Minute Shut In Press`,
`5 / 10 / 15 Minute SIP (MPa)`

**Job totals** — `Total Tonnage Pumped`, `REMARKS`, `WELL INFORMATION`

---

## Per-zone variables

One value per stage. Coverage = share of summary pages carrying the row.

### Identity & geometry
| Field | Unit | Layout | Cover |
|---|---|---|---|
| `Zone #` | — | A+B | 100% |
| `Description` | text (`Frac`) | A | 96% |
| `Service Order #` | — | A | 96% |
| `Job Date` | date | A | 96% |
| `Formation` / `Formation Treated` | text | A+B | 96% |
| `Interval Top` | m | A | 100% |
| `Interval Bottom` | m | A | 86% |
| `Top Perf` | m | B | 93% |
| `Bottom Perf` | m | B | 15% |
| `TVD` | m | A | 92% |
| `Volume to Frac Port` | m³ | B | 96% |
| `Blender #` | — | A | 95% |
| `Zone Comments` | text | A | 3% |

`Zone Comments` is how a stage is marked `Skipped` — the only per-zone
status flag in the table, and the thing to check before treating a zone
column as a real stage.

### Time
`Start Time` (hh:mm) · `Stop Time` (hh:mm) · `Duration` (hh:mm, **minutes in
practice**) · `Zone Date` (M/DD/YYYY, rare)

> `Duration` is labelled `hh:mm` but holds integer minutes (77, 65, 54…).
> Worth confirming with Carmine before it is treated as a clock value.

### Ball drop / sleeve
`Slurry Vol. Ball Launch` · `Slow Down Vol.` · `Slurry Vol. to Slow Down` ·
`Slurry Vol. Ball Seat` — all m³ · `Ball size` (in, legacy) ·
`Sleeve Shift` (MPa)

### Fluid volumes — m³
`Displacement Vol.` · `Pad` · `Proppant` · `Sweep` · `Spacer` · `Flush` ·
`Acid` · `Clean Total` · `Slurry Total` · `Over / Under Flush` ·
`Wireline Pumpdown` · `Pumpdown Total` · `Fluid In Formation` ·
`Fluid Grand Total` · `TP Pump` · `Hole Fill` · `Displace Ball / Acid` ·
`Water Vol. (Mixed With Acid)` · `CUSTOMER SUPPLIED ACID` ·
`Produced Water` · `Fluid System` / `Fluid Type` (text) · `Salinity` (%)

### Proppant mass — T
`Programmed` · `Pumped Proppant Total` · `In Formation Proppant Total` ·
`Screen Out` (Yes/No)

Per-mesh rows, name varies by supply: mesh ∈ {`50/140`, `40/70`, `30/50`,
`20/40`} × source ∈ {`Local`, `Northern White`, `Domestic`, `Import`,
`Prime Plus`, `SB Prime`}. A parser should match the mesh pattern rather
than enumerate names.

### Proppant concentration — kg/m³
`Maximum Conc. @ Formation` · `Max Conc. <mesh> <source>` (per mesh) ·
`Conc @ perfs` · `Max Conc @ perfs` · `Final Conc @ perfs`

### Chemicals — L (some kg or m³)
Product names, not roles — the role is the text after the comma. Seen:
`CalBreak™ 5700/5501/5825` · `CalVisc™ HB 6850/6650/6851`, `CalVisc™ 6702`
(kg), `CalVisc™ 6621` · `K-BAC 1020` · `AQUCAR 742` · `PropCure™ XB/XC` ·
`DynaScale™ 3515` · `DynaRate™ 6410`, `DynaRate 6440/6524` ·
`CalStim™ WLS 1501/751` (m³), `CalStim™ 3464` · `CalSurf™ 9590` ·
`Coilube 3150` · `CalGel™ 4001` · `DynaLink™ 5026` · `CalTreat™ 7107` ·
`15% HCl` / `7.5% HCl Acid` (m³) · `CO-SOLVE CO-WC100` (m³)

Legacy `DWP-###` / `DAP-###` codes: `DWP-913` clay control · `DWP-621/641`
friction reducer · `DWP-944/962` biocide · `DWP-949/959/967` surfactant ·
`DAP-902` scale inhibitor.

Legacy chemical block is its own sub-table with columns
`Name | Pumped (L) | Losses (L) | # of Pumps Used | Total (L) | Average (L/m³)`
— five values per chemical, not one.

### Pressures — MPa
`Breakdown` · `Minimum` · `Maximum` · `Average` · `ISIP` · `Sleeve Shift`
(legacy names: `Minimum/Maximum/Average Pressure`)
Plus `Specific Gravity on Flush` (—) and `Frac Gradient` (kPa/m).

Some jobs repeat the block **after** the flush — `Post ISIP` (MPa),
`Post Frac Gradient` (kPa/m), `Post Specific Gravity on Flush` (545 pages).
These are separate columns, not replacements: a zone can carry both.
Per-zone shut-in rows `SIP 1 min` / `SIP 5 min` (MPa) also appear on a few
jobs, duplicating what is normally a header-level value.

### Rate — m³/min
`Slurry Rate Minimum` · `Slurry Rate Maximum` · `Slurry Rate Average`
(legacy: `Minimum / Maximum / Average Fluid Rate`)

### Power & fuel
`Fluid Power` (kW) · `Energy` (kW×hr) · `Dyed Diesel` / `Clear Diesel` /
`Pump Down Diesel` / `Pumpdown Dyed Diesel` / `Misc Fuel` / `Fuel Total` (L) ·
`CNG (e3m3)` · `CNG Total` (SCF) · `LNG Total`

Fleet counts, on newer dual-fuel jobs — `Total # of Pumps` ·
`# of Bi-Fuel Pumps` · `# of Bi-Fuel Pumps (Burning CNG)` · `Diesel Pumps` ·
`Tier 2 DF Pumps` · `Tier 4 DF Pumps` · `Tier 2 DF Pumps (Burning CNG)` ·
`DF Pumps Total` · `DF Pumps (Burning CNG) Total` · `Pumps Total`.
Naming is unsettled across vintages; match on `Pump` and keep the raw label.

### Nitrogen — legacy only
`N2 Treatment` (scm) · `N2 Losses` (scm) · `N2 Rate` (scm/min)

### Legacy totals column
Layout B carries a `TOTAL` / `AVERAGE` column to the right of the last zone —
a job roll-up, not a stage. Must be excluded from per-stage output (or
exported separately), or it will read as a phantom extra stage.

---

## Cross-checks against the chart data

These summary values are independently derivable from the per-second series
already extracted, so they double as a validation harness for the chart
pipeline:

| Summary field | Chart equivalent |
|---|---|
| `Maximum` / `Minimum` / `Average` (MPa) | max/min/mean of `Tr Press` |
| `Slurry Rate Max/Min/Average` | same on `Slurry Rate` |
| `Maximum Conc. @ Formation` | max of `BH Prop Conc` |
| `Start Time` / `Stop Time` / `Duration` | stage window in the export |
| `Slurry Total` | ∫ `Slurry Rate` dt |

A first pass could report agreement per stage — a cheap, high-signal QA
screen and a direct answer to whether the chart extraction is right.

---

## Open questions for Carmine

1. Which of these does he actually want exported? The full set is ~100
   columns per zone; his per-second CSV spec is deliberately four.
2. One row per zone (wide), or long form `zone | field | value | unit`?
   Wide breaks whenever a chemical or proppant mesh differs between jobs.
3. Should the legacy `TOTAL`/`AVERAGE` column be kept as a job summary row?
4. Are the legacy `DWP-###` codes worth mapping to roles, or is the raw
   product name enough?
5. Confirm `Duration` is minutes despite the `hh:mm` unit label.

## Coverage

Complete scan: all 4,573 PDFs on the drive, 849 of which carry Calfrac
branding across 19,942 pages. Every distinct page family was checked, and
the two layouts above are the only tabular ones:

| Page family | Pages | |
|---|---|---|
| `Treatment Summary` | 5,176 | Layout A |
| `Multiple Zone Frac Treatment Summary` | 1,240 | Layout B |
| `GENERAL INFORMATION` | 2,262 | Layout B continuation sections |
| `Well Name :` | 3,096 | operator completion report — narrative |
| `Temp:` | 2,305 | operator daily field report |
| `Time Log` | 2,121 | Peloton, already parsed |
| `DATE` | 279 | operator daily summary — narrative |

≈6,400 genuine Calfrac summary pages. 133 distinct label/unit pairs in
Layout A, 215 recurring labels in Layout B.

### Narrative fallback

The `Well Name :` family is prose, but it carries real per-stage numbers:

> "Calfrac conducted a 55T Slickwater Frac on the Montney sleeve interval
> 2783.3mKB. Pumped a 47.8m³ pad. Placed 5T of 50/140, 45T 30/50 Reg…
> Average rate of 10 m³/min, Average pressure of 55.3 MPa. Pmax 58.7 MPa."

Regex-able for older wells that predate the tabular summaries, but phrasing
varies by supervisor. Fallback only — not part of a first build.

### Label spelling drift

`Well License` also appears as `WellLicense` (no space), `7.5% HCl Acid` as
`7.5% HCI Acid` (capital i for l), `CalVisc™` as `Calvisc™`. Match labels
case-insensitively with whitespace collapsed.
