"""Liberty summary-table extraction (the "Summary Data" screen for Liberty).

Liberty COMP PDFs carry a text "STIMULATION SUMMARY" page — one block per
stage with the treatment roll-up (interval depths, proppant, volume, ISIP,
average/max treating pressure, injection rate) plus job totals. Text, not a
positional grid, so it parses with regex.

  - find_summary_pages(doc): the document's summary/table pages grouped for
    viewing (Stimulation Summary, Proppant Summary, TimeTracker log, Cement
    Report) with page numbers, so the Lab can render them with pdf.js.
  - parse_stimulation(doc): the per-stage Stimulation Summary parsed into a
    structured {columns, rows} grid — one row per stage.
  - parse_stage_sheets(doc): the stage-keyed Tableau sheets — WELLBORE
    SUMMARY, the PRESSURE SUMMARY grid, FLUID SUMMARY (volumes by stage) and
    the PROPPANT SUMMARY grid — each as {columns, rows, totals, pages}, one
    row per stage. The per-stage dropdown of #767 is built from these.
"""
import re

# see lib1: filings before the rename print "Liberty Oilfield Services LLC"
_LIBERTY = re.compile(r"Liberty\s+(?:Energy|Oilfield)", re.I)

# Order matters: _page_kind returns the FIRST pattern that matches.
#
# The last four are the 2025-era filings, which print none of the first four.
# Measured over 18 Liberty files: the old vintage leads its sheets with
# "LIBERTY", "Stage No" and "STIMULATION SUMMARY"; the 2025 vintage leads with
# "Time Log" (271 pages across 6 files), "24 Hour Summary:" and "Completion
# Field Report" and carries no STIMULATION SUMMARY page at all. Knowing only
# the old names meant the Summary view came up empty on every new filing —
# Carmine got it on 10 of 299 files.
#
# WELL COMPLETION SUMMARY is on the OLD vintage and was missed too: it sits
# beside STIMULATION SUMMARY in all 12 old files sampled and matched nothing.
# The stage-keyed sheets (2026-10-02, #767). A Liberty filing prints half a
# dozen Tableau sheets that each lead with "Stage No" — ball hits, the
# proppant bar chart, the chemical comparison, the proppant grid, fluid
# volumes by stage, the wellbore summary — and `^Stage No` used to hand every
# one of them to "proppant", so the Summary view put one name on six
# different pages and nothing could be parsed until they were told apart.
# Each now has its own kind, told by the column or title it alone prints;
# the three layouts that share the PRESSURE SUMMARY title (the per-stage
# grid, a "Measure Names" pivot, a presets chart) are split the same way, and
# the catch-all is the LAST rule, where it labels only what nothing else
# claimed. Measured on 49367 (2025 vintage): each of its ten sheet pages
# lands on its own kind.
SUMMARY_KINDS = [
    ("stimulation", r"STIMULATION SUMMARY"),
    ("wellcompletion", r"WELL COMPLETION SUMMARY"),
    # a stage-keyed grid of its own (FSD rates, frictions, F_ISIP, F_BHISIP,
    # F_FG) that the F_BHISIP column below used to file under the pressure
    # grid -- 00269 p88, printed straight after PRESSURE SUMMARY
    ("stepdown", r"FINAL STEP ?DOWN SUMMARY"),
    # "Measure Names" is the legend title of EVERY Tableau chart that plots
    # more than one measure -- job completion %, pumpdown, pump time per
    # stage, even the chemical comparison (00470 p150-169) -- so the pivot is
    # the one that names a pressure measure too
    ("pressure_measures",
     r"(?s)\A(?=.*^Measure Names\s*$)(?=.*(?:PRESSURE SUMMARY|"
     r"^(?:Ave|Max) (?:BHPSI|MPa|PSI)\s*$|^F_B?H?ISIP\s*$|^BD_Psi\s*$))"),
    ("ballhit", r"BALL HIT INFO|^Ball Hit Vol\b"),
    ("pressure_presets", r"Pressure Summary Presets|Initial & Final Stepdowns"),
    # the per-stage grid, by title or by the columns only it prints
    ("pressure", r"PRESSURE SUMMARY|^Max Working MPa\s*$|^F_BHISIP\s*$"),
    ("fluid_totals", r"FLUID VOLUMES SUMMARY|^Aggregates\s*$"),
    ("wellbore", r"WELL\s?BORE SUMMARY|^PERF TopShot\s*$"),
    # the grid prints a Prop Screw column; its bar-chart twin prints axis
    # ticks (0K, 100K ...) instead, and _page_kind splits that one off
    ("proppant", r"PROPPANT SUMMARY|^Prop Screw\b"),
    # the chart twin without its title: stage-keyed, a Prop column, and an
    # axis counted in thousands. The lookaheads are pinned to \A: unpinned,
    # re.search retried them at every offset, quadratic in the page text --
    # 6 s on one 27 KB page of 00674 (682 pages), minutes per filing.
    ("proppant_chart", r"(?s)\A(?=.*^Stage No\s*$)(?=.*^-?\d+K\s*$)"
                       r"(?=.*^Prop(?:pant)? (?:Actual|Design|Name)\b)"),
    ("chemical", r"CHEMICAL (?:COMPARISON|CONCENTRATION)|^Chemical Name\s*$"),
    # the stacked-bar chart of the same volumes (00470 p165): stage-keyed
    # with a fluid legend, so the rule below took it for the grid
    ("fluid_chart", r"TREATMENT FLUID VOLUMES? BY STAGE"),
    # by stage, named for the fluids it prints: the 2025 sheet is titled
    # FLUID SUMMARY; the older one is known only by its columns
    ("fluid", r"(?s)^FLUID SUMMARY\s*$|\A(?=.*^Stage No\s*$)"
              r"(?=.*^(?:Treated Water|Fresh Water|HVFR\b|HCR Acid|HCl))"),
    ("timetracker", r"^LIBERTY\s*$|TimeTracker"),
    ("cement", r"^Cement Report"),
    ("timelog", r"^Time Log\s*$"),
    ("dailysummary", r"^\s*\d+\s*(?:Hour|Hr)\s+Summary\s*:"),
    ("fieldreport", r"^Completion Field Report"),
    # what no rule above claimed: named for what it is, not guessed at
    ("stagetable", r"^Stage No\b"),
]
KIND_TITLES = {
    "stimulation": "Stimulation Summary",
    "wellcompletion": "Well Completion Summary",
    "proppant": "Proppant Summary",
    "proppant_chart": "Proppant Summary (chart)",
    "pressure": "Pressure Summary",
    "pressure_measures": "Pressure Summary (measures)",
    "pressure_presets": "Pressure Summary (presets)",
    "ballhit": "Ball Hit Info",
    "wellbore": "Wellbore Summary",
    "fluid": "Fluid Volumes by Stage",
    "fluid_chart": "Fluid Volumes by Stage (chart)",
    "fluid_totals": "Fluid Volumes (well totals)",
    "stepdown": "Final Step Down Summary",
    "chemical": "Chemical Comparison",
    "stagetable": "Stage table",
    "timetracker": "TimeTracker Log",
    "cement": "Cement Report",
    "timelog": "Time Log",
    "dailysummary": "24 Hour Summary",
    "fieldreport": "Completion Field Report",
}
_PROP_TICK = re.compile(r"^-?\d+K\s*$", re.M)
_PROP_SCREW = re.compile(r"^Prop Screw\b", re.M)


def detect_document(doc):
    """True when this is a Liberty filing, whether or not its charts read.

    find_summary_pages used to be reachable only when a Liberty CHART had
    already been extracted, so a filing whose plots we could not read showed
    no summary sheets either — even though the sheets are plain text and were
    sitting right there. Same shape as the Calfrac gate in pipeline.py, and
    the same reasoning: a filing prints its tables whether or not we can read
    its plots.
    """
    for p in range(min(doc.page_count, 400)):
        try:
            if _LIBERTY.search(doc[p].get_text() or ""):
                return True
        except Exception:
            continue
    return False

# order matters: label -> (column name, unit). Interval Base before Top would
# still work (regex is anchored on the label), but keep report order.
FIELDS = [
    (r"Interval Top", "Interval Top", "m"),
    (r"Interval Base", "Interval Base", "m"),
    (r"Prop", "Proppant", "tonne"),
    (r"Total Vol", "Total Volume", "m³"),
    (r"ISIP", "ISIP", "kPa"),
    (r"Average pressure", "Avg Pressure", "kPa"),
    (r"Inj Rate Avg", "Avg Inj Rate", "m³/min"),
    (r"Max\.?\s*treatment pressure", "Max Treatment Pressure", "kPa"),
]


def _page_kind(text):
    for kind, pat in SUMMARY_KINDS:
        if re.search(pat, text, re.M):
            # two PROPPANT SUMMARY pages: the grid, and a bar chart drawn
            # from it. Carmine's "text page not the image page" is the grid,
            # and only the chart prints an axis of thousands
            if kind == "proppant" and not _PROP_SCREW.search(text) \
                    and len(_PROP_TICK.findall(text)) >= 3:
                return "proppant_chart"
            return kind
    return None


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — consecutive same-kind pages grouped."""
    groups = []
    for p in range(doc.page_count):
        kind = _page_kind(doc[p].get_text())
        if kind is None:
            continue
        page1 = p + 1
        if groups and groups[-1]["kind"] == kind and \
                page1 - groups[-1]["pages"][-1] <= 2:
            groups[-1]["pages"].append(page1)
        else:
            groups.append({"kind": kind, "title": KIND_TITLES.get(kind, kind),
                           "pages": [page1]})
    return groups


def is_stimulation_page(page):
    return "STIMULATION SUMMARY" in page.get_text()


_NUM = r"([-\d,]+(?:\.\d+)?)"


def _val(block, label):
    """the number following 'label:' in a stage block, or None."""
    m = re.search(label + r"\s*:?\s*" + _NUM, block)
    if not m:
        return None
    return m.group(1).replace(",", "")


def parse_stimulation(doc):
    """-> {columns, rows, totals} for the per-stage Stimulation Summary,
    or None. One row per stage."""
    text = ""
    for p in range(doc.page_count):
        t = doc[p].get_text()
        if "STIMULATION SUMMARY" in t or (text and "Stage:" in t):
            text += "\n" + t
            # keep appending while the stimulation blocks continue
            if "Stage:" not in t and text:
                break
    if "Stage:" not in text:
        return None

    # split into per-stage blocks on "Stage: N"
    parts = re.split(r"Stage:\s*(\d+)", text)
    # parts = [pre, stageNo, block, stageNo, block, ...]
    rows = []
    for i in range(1, len(parts) - 1, 2):
        stage = parts[i].strip()
        block = parts[i + 1]
        row = [stage]
        for _pat, _name, _unit in FIELDS:
            row.append(_val(block, _pat))
        if any(c is not None for c in row[1:]):
            rows.append(row)
    if not rows:
        return None
    columns = ["Stage"] + [f"{n} ({u})" for _p, n, u in FIELDS]

    totals = {}
    mf = re.search(r"Total Fluid All Fracs\s*:?\s*" + _NUM, text)
    mp = re.search(r"Total Proppant All Fracs\s*:?\s*" + _NUM, text)
    md = re.search(r"Pumped Down\s*:?\s*([A-Za-z ]+)", text)
    if mf:
        totals["Total Fluid All Fracs (m³)"] = mf.group(1).replace(",", "")
    if mp:
        totals["Total Proppant All Fracs (tonne)"] = mp.group(1).replace(",", "")
    if md:
        totals["Pumped Down"] = md.group(1).strip()
    return {"columns": columns, "rows": rows, "totals": totals}


# ------------------------------------------------------- stage-keyed grids
#
# The wellbore, pressure, fluid and proppant sheets are Tableau exports: one
# text span per cell, a title, a header (one to three lines), then one row per
# stage keyed by its number down the left margin.
#
# The columns come from the HEADER, not from the body. Tableau draws every
# header cell as a filled rectangle, and the vertical edges of those
# rectangles are the column boundaries; a body value belongs to the column
# whose band holds its centre. That matters because the body is aligned
# either way: 49367 (2025) centres its numbers, but most of the corpus
# right-aligns them (00269, 00198, 00738 ...), where a centre-x cluster puts
# "-1,995" and "0" of one column in two columns and drops every header name
# (they sit at the column's centre, 25 pt left of the numbers). A header cell
# whose rectangle spans several columns is a group label ("30/70 White" over
# Prop Actual / Prop Screw / Prop Design / Proppant Actual-Design) and is
# prefixed to the names under it; the caption over everything ("Proppant
# Name") is dropped. Without rectangles (a page that draws none) the bands are
# the midpoints between the header names' centres.
#
# A column the sheet titled but never filled (PERF TotalNumShots on 49367,
# PERF ClusterLength / PerfDiam on 00269) is reported in `empty_columns`, not
# shipped blank. The Min / Max / Average footer under the pressure grid is
# printed by a SEPARATE sheet with its own column pitch, so it is matched by
# order rather than by x and kept apart in `totals`.
_INT = re.compile(r"^\d{1,4}$")
_NUMC = re.compile(r"^-?[\d,]*\.?\d+%?$")
_UNIT_CELL = re.compile(r"^\(?(?:m3|m³|m3pm|m3/min|bbls?|bpm|MPa|kPa|psi|PSI|"
                        r"kgs?|lbs?|tonnes?|t|m|ft|min|%|L|[Gg]al)\)?$")
# a flush-volume header prints its unit four ways -- "(m3)" (49367), "m3"
# (00738), "bbl" (00269), "Gal" (00697) -- and the column name carries it
# the one way: "Top Shot Flush Vol (m3)"
_TRAIL_UNIT = re.compile(r"\s+\(?(m3|m³|bbls?|[Gg]al)\)?$")
_FOOTER = re.compile(r"^(?:Min|Max|Average|Avg|Total|Grand Total|Sum)\b", re.I)
_TITLE = re.compile(r"\bSUMMARY\b")
_KEY_HEAD = re.compile(r"^Stage(?:\s+No\.?)?\s*$", re.I)


def _cells(page):
    """[(x0, y0, x1, y1, text)], one per text span — a sheet's cells arrive
    whole, "Sum of PERF PlugDepth" as one span, not four words."""
    try:
        d = page.get_text("dict")
    except Exception:
        return []
    out = []
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                t = (sp.get("text") or "").strip()
                if t:
                    x0, y0, x1, y1 = sp["bbox"]
                    out.append((x0, y0, x1, y1, t))
    return out


def _rows(cells, tol=2.5):
    """[(cy, [cell, ...])] — cells grouped into visual rows by centre-y, each
    row left to right."""
    rows = []
    for c in sorted(cells, key=lambda c: ((c[1] + c[3]) / 2, c[0])):
        cy = (c[1] + c[3]) / 2
        if rows and abs(rows[-1][0] - cy) <= tol:
            rows[-1][1].append(c)
        else:
            rows.append((cy, [c]))
    return [(cy, sorted(cs, key=lambda c: c[0])) for cy, cs in rows]


def _cluster(xs, tol):
    groups = []
    for x in sorted(xs):
        if groups and x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups]


def _is_stage_row(cells):
    """a body row: an integer at the left margin with a cell after it"""
    return (len(cells) >= 2 and cells[0][0] < 90
            and _INT.match(cells[0][4]) is not None)


def _header_boxes(page, top, bottom, key_x):
    """the filled rectangles Tableau draws behind the header cells, between
    the title and the first stage row, less the key column's own cell"""
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    out = []
    for d in drawings:
        if d.get("fill") is None:
            continue
        x0, y0, x1, y1 = tuple(d["rect"])
        if x1 - x0 < 4 or y1 - y0 < 4 or y0 < top - 1 or y1 > bottom + 1:
            continue
        if x0 - 1 <= key_x <= x1 + 1:
            continue
        out.append((x0, y0, x1, y1))
    return out


def _bands(boxes):
    """column bands [(x0, x1)] from the header rectangles' vertical edges --
    every stretch between two edges that some rectangle covers"""
    edges = []
    for x in sorted(v for b in boxes for v in (b[0], b[2])):
        if not edges or x - edges[-1] > 1.5:
            edges.append(x)
    return [(a, b) for a, b in zip(edges, edges[1:])
            if b - a >= 8 and any(bx[0] - 1 <= (a + b) / 2 <= bx[2] + 1
                                  for bx in boxes)]


def _band_of(bands, cx, slack=12.0):
    for i, (a, b) in enumerate(bands):
        if a - 0.5 <= cx <= b + 0.5:
            return i
    if not bands:
        return None
    i = min(range(len(bands)), key=lambda i: min(abs(bands[i][0] - cx),
                                                 abs(bands[i][1] - cx)))
    a, b = bands[i]
    return i if min(abs(a - cx), abs(b - cx)) <= slack else None


def _stage_grid(page):
    """One sheet page -> {columns, rows, totals, empty_columns, all_columns}
    or None.

    columns[0] is "Stage"; a row is [stage, cell, ...] with None where the
    sheet printed nothing in that column. all_columns is every column the
    header names, filled or not, in page order."""
    rows = _rows(_cells(page))
    body = [(cy, cs) for cy, cs in rows if _is_stage_row(cs)]
    if not body:
        return None
    first_y, last_y = body[0][0], body[-1][0]
    # the header is everything between the title and the first stage row;
    # with no title on the page, sixty points is more than a three-line
    # header ever takes
    title_y = max([cy for cy, cs in rows if cy < first_y
                   and any(_TITLE.search(c[4]) for c in cs)]
                  or [first_y - 60])
    key = body[0][1][0]
    key_x, key_x1 = (key[0] + key[2]) / 2, key[2]
    head = [c for cy, cs in rows if title_y < cy < first_y for c in cs
            if not _KEY_HEAD.match(c[4])
            and not (c[0] - 1 <= key_x <= c[2] + 1)]   # the key's own name
    boxes = _header_boxes(page, title_y, first_y, key_x)
    bands = _bands(boxes)
    if not bands:
        # no rectangles: one band per header name, split at the midpoints
        xs = _cluster([(c[0] + c[2]) / 2 for c in head], 8.0)
        if not xs:                      # no header either: the body's own x
            vals = [c for _cy, cs in body for c in cs[1:]]
            xs = _cluster([(c[0] + c[2]) / 2 for c in vals], 12.0)
        cuts = [key_x1] + [(a + b) / 2 for a, b in zip(xs, xs[1:])] + [1e9]
        bands = list(zip(cuts, cuts[1:]))
    if not bands:
        return None

    # header text -> its band(s): a rectangle over one band names (or gives
    # the unit of) that column; one over several is a group label
    parts = [[] for _ in bands]
    units = [None] * len(bands)
    groups = []                                   # (y, first, last, text)
    for c in sorted(head, key=lambda c: (c[1], c[0])):
        cx, cy, t = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2, c[4]
        hosts = [b for b in boxes if b[0] - 1 <= cx <= b[2] + 1
                 and b[1] - 1 <= cy <= b[3] + 1]
        span = []
        if hosts:
            b = min(hosts, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            span = [i for i, (a, z) in enumerate(bands)
                    if b[0] - 1 <= (a + z) / 2 <= b[2] + 1]
        if not span:
            i = _band_of(bands, cx)
            span = [] if i is None else [i]
        if len(span) > 1:
            groups.append((cy, span[0], span[-1], t))
        elif span and _UNIT_CELL.match(t):
            units[span[0]] = t.strip("()")
        elif span:
            parts[span[0]].append(t)
    names = []
    for i in range(len(bands)):
        nm = " ".join(parts[i])
        if units[i] and units[i] not in nm:
            nm = "%s (%s)" % (nm, units[i]) if nm else units[i]
        nm = _TRAIL_UNIT.sub(lambda m: " (%s)" % m.group(1), nm)
        over = sorted((g for g in groups if g[1] <= i <= g[2]),
                      key=lambda g: g[0])
        if len(over) > 1:     # a caption over the whole sheet says nothing
            over = [g for g in over[:-1]
                    if (g[1], g[2]) != (0, len(bands) - 1)] + over[-1:]
        names.append(": ".join([g[3] for g in over] + ([nm] if nm else [])))

    cells = [[None] * len(bands) for _ in body]
    for r, (_cy, cs) in enumerate(body):
        for c in cs[1:]:
            i = _band_of(bands, (c[0] + c[2]) / 2)
            if i is None:
                continue
            v = c[4].replace(",", "") if _NUMC.match(c[4]) else c[4]
            cells[r][i] = v if cells[r][i] is None else cells[r][i] + " " + v
    filled = [i for i in range(len(bands))
              if any(row[i] is not None for row in cells)]
    if not filled:
        return None
    # a band with neither name nor value (the gutter between two sheets) is
    # no column; a filled one without a name is called by its place
    keep = [i for i in range(len(bands)) if names[i] or i in filled]
    seen = {}
    for i in keep:
        nm = names[i] or ("col%d" % (i + 1))
        seen[nm] = seen.get(nm, 0) + 1
        names[i] = nm if seen[nm] == 1 else "%s (%d)" % (nm, seen[nm])
    out = [[cs[0][4]] + [cells[r][i] for i in filled]
           for r, (_cy, cs) in enumerate(body)]

    totals = {}
    for cy, cs in rows:
        if cy <= last_y or not _FOOTER.match(cs[0][4]):
            continue
        fv = [c[4].replace(",", "") for c in cs[1:]]
        if len(fv) == len(filled):
            totals[cs[0][4].rstrip(":")] = fv
    return {"columns": ["Stage"] + [names[i] for i in filled], "rows": out,
            "totals": totals,
            "empty_columns": [names[i] for i in keep if i not in filled],
            "all_columns": [names[i] for i in keep]}


# the sheets that are a grid keyed on the stage, and the title each is
# published under. The chart twins and the pivots are pages to look at, not
# tables to parse.
STAGE_SHEETS = ("wellbore", "pressure", "fluid", "proppant")


def _stage_no(s):
    try:
        return (0, int(s))
    except ValueError:
        return (1, s)


def _parse_kind(doc, kind, groups=None):
    """one table from every page of `kind`, stitched on the stage number.

    A sheet that runs onto a second page continues with the next stages and
    stitches by column name, so a column empty on one page and filled on the
    other is one column. A page whose stages were already read is a reprint
    -- 00470 (AER Duvernay, 2022) prints the whole sheet set twice, and the
    wellbore, pressure, fluid and proppant tables came back with every stage
    twice -- and is listed in `repeated_pages` instead. Rows are in stage
    order whichever way the sheet sorted them (00738 prints 74 down to 1)."""
    if groups is None:
        groups = find_summary_pages(doc)
    names, filled, by_stage = [], set(), {}
    totals, pages, repeats = {}, [], []
    for g in groups:
        if g["kind"] != kind:
            continue
        for p in g["pages"]:
            tab = _stage_grid(doc[p - 1])
            if not tab:
                continue
            if any(r[0] in by_stage for r in tab["rows"]):
                repeats.append(p)
                continue
            cols = tab["columns"][1:]
            for nm in tab["all_columns"]:
                if nm not in names:
                    names.append(nm)
            filled.update(cols)
            for r in tab["rows"]:
                by_stage[r[0]] = dict(zip(cols, r[1:]))
            for lab, vals in tab["totals"].items():
                totals.setdefault(lab, {}).update(zip(cols, vals))
            pages.append(p)
    if not by_stage:
        return None
    columns = [nm for nm in names if nm in filled]
    rows = [[s] + [by_stage[s].get(nm) for nm in columns]
            for s in sorted(by_stage, key=_stage_no)]
    return {"columns": ["Stage"] + columns, "rows": rows,
            "totals": {lab: [t.get(nm) for nm in columns]
                       for lab, t in totals.items()},
            "empty_columns": [nm for nm in names if nm not in filled],
            "pages": pages, "repeated_pages": repeats}


def parse_stage_sheets(doc):
    """-> {kind: table} for every stage-keyed sheet the filing prints and
    this module can read; the page sweep is done once for all of them."""
    groups = find_summary_pages(doc)
    out = {}
    for kind in STAGE_SHEETS:
        tab = _parse_kind(doc, kind, groups)
        if tab:
            out[kind] = tab
    return out


def parse_wellbore(doc):
    return _parse_kind(doc, "wellbore")


def parse_pressure(doc):
    return _parse_kind(doc, "pressure")


def parse_fluid(doc):
    return _parse_kind(doc, "fluid")


def parse_proppant(doc):
    return _parse_kind(doc, "proppant")
