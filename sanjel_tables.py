"""Sanjel table extraction (the "Summary Data" screen for Sanjel).

`sanjel.py` traces Sanjel's treatment PLOTS; this reads the engineering
TABLES that sit a few pages ahead of them. A Sanjel Treatment Report prints
three ruled, per-interval grids on consecutive pages:

  - "Completion Details" — perf/zone, fraced Y/N, formation, packer and
    sleeve depths, TVD, displacement, frac start/end, the end-of-job shut-in
    pressures, and a free-text Remarks column that carries the per-interval
    sleeve-shift pressure and ball-seat volume.
  - "Treatment Details" — breakdown/average/max surface pressure, ISIP, frac
    gradient, blender and downhole rates, the pumped volumes, and then a
    block of tonnage columns REPEATED once per proppant type.
  - "Zones" — additive/chemical volume pumped per interval, one column per
    product code.

Public surface, matching the other summary modules:

  - find_summary_pages(doc): the report's table pages grouped for viewing.
  - parse_completion_details(doc) / parse_treatment_details(doc) /
    parse_zones(doc): one table each as {columns, rows, totals, pages,
    empty_columns}. `empty_columns` names the columns the report ruled and
    titled but never filled anywhere in the document; they are withheld from
    `columns`, not shipped at 0%.

    The three grids do NOT share a grain. Treatment Details and Zones are one
    row per frac interval; Completion Details is one row per PERF, and on a
    well with several perf clusters per zone it is much longer — 00019 prints
    39 perfs against 13 intervals, with the Zone # column filled on only 15
    of the 39 rows. Do not join the three on row position.
  - parse_all(doc): whichever of the three parsed, as a list of table dicts
    ready to hand to the pipeline.

Geometry notes (why this is not a regex module):

  * Every one of these grids is a ruled table, and roughly half the corpus
    prints it on a /Rotate 90 page. Span coordinates come back in unrotated
    space, so everything is pushed through `page.rotation_matrix` first —
    after that both layouts are the same landscape grid and one parser reads
    both.
  * Column and row boundaries are taken from the ruling lines, not from text
    clustering. That matters because several columns are printed EMPTY (an
    unnamed spacer column, the N2 columns on a nitrogen-free job), and a
    clustering parser silently shifts every value one column left when it
    meets one.
  * A ruling line that stops short of a header row IS the merged-cell
    marker. That is how the repeating proppant block is read: the number of
    proppant types varies per file (2 here, 3 there), so the group header
    ("Proppant" / "Domestic (40/70)") is resolved from the ruling geometry
    and its sub-columns are NAMED PER PROPPANT rather than hard-coded — a
    file with N proppants yields N x (however many rows that file prints in
    the block, 4 or 5) columns automatically.
  * Narrow header cells are typeset as vertical text, and the m³ superscript
    lands in its own smaller span. Header text is therefore re-flowed in the
    line's own reading direction and the superscript folded back in.

VERIFICATION STATE
------------------
Verified against the reports' own printed numbers on 00013, 00014, 00019 and
00100 (2015-16 vintage, the only vintage that carries these grids):

  - interval counts match what the reports print — 00013: 18 intervals in all
    three grids; 00014: 22; 00019: 39 perfs in Completion against 13
    intervals in Treatment and Zones; 00100: 29.
  - field values spot-checked cell-by-cell on named intervals against the
    printed page, and cross-checked arithmetically against the reports' own
    Avg / Total-or-Max footer rows (e.g. 00013 Break Press: the 14 numeric
    cells average 45.96 against a printed Avg of 46.0).
  - the repeating proppant block is generated from the ruling geometry, not
    hard-coded: 00013 prints 2 proppants x 4 sub-columns, 00100 prints 3
    proppants x 5 (Avg DH Conc appears only on the later layout). Both read.
  - printed interval suffixes survive: 00014 prints 3a, 3b, 7a, 7b and all
    four arrive as distinct rows.
  - after the fixes below, no column ships 0% filled on any of the four.

Every column under 99% on those four files was traced back to the page and is
genuine source sparsity — an unfraced zone (00013 interval 5, "Did not frac
zone 5 as per program"), a shut-in pressure Sanjel only recorded on a handful
of zones, an additive used on 6 of 29 intervals.

Corpus census over all 56 `sanjel`-marked filings, run once serially: 14
carry these grids (00013, 00014, 00019, 00020, 00021, 00097-00105), 42 do
not, for 42 tables and 1,079 interval rows. Of 695 columns shipped, none is
0% filled and 37 dead columns were withheld; 127 are under 99% and every one
sampled traced back to genuine source sparsity.

The 42 that carry nothing are not misses. Outside the 2015-16 vintage the
`sanjel` marker is a substring hit on "Sanjel Cementers Ltd." / "Sanjel
Energy Services Inc." in a Peloton vendor list (00646 p99, 01108 p13) — a
cementing contractor, not a Sanjel Treatment Report. Size this module on the
census, not on the marker count.

One caution for consumers: the grids disagree with each other about labels.
00014 prints interval "7a" on Treatment and Zones but "7" on Completion, and
00019's Completion is per-perf while the other two are per-interval. Both are
read as printed; neither is a parser artefact.

Deliberately NOT parsed: the "Field Quality Control Report" pages
(RHEOLOGY DATA OF FLUID SYSTEM, PROPPANT CHECK/SIEVE ANALYSIS, PHYSICAL
PROPERTIES OF BASE FLUID). Their grain is a fluid tank / a sieve size / a
composite sample, not a frac interval, and the only link back to the
intervals is a page-level "Zones: 1 To 21" range. The sieve Pass/Fail cells
also read FAIL for proppant columns that were simply left blank, so
publishing them as data would manufacture QC failures. Those pages are
listed by find_summary_pages so they stay visible, but nothing is parsed
off them.
"""
import re

import fitz

SUMMARY_KINDS = [
    ("completion", "Completion Details"),
    ("treatment", "Treatment Details"),
    ("zones", "Zones"),
    ("quality", "Field Quality Control Report"),
]
KIND_TITLES = {
    "completion": "Completion Details",
    "treatment": "Treatment Details",
    "zones": "Zones — additives pumped",
    "quality": "Field Quality Control Report",
}

TABLE_TITLES = {
    "completion": "Completion Details",
    "treatment": "Treatment Details",
    "zones": "Zones — additives pumped",
}

# page-level title text. The Zones grid is titled by its contents ("Chemical
# Amount Pumped (L) for ..." / "Chemicals, ...") and only names itself in the
# header cell, so it is matched on that cell.
_TITLE_RE = {
    "completion": re.compile(r"^\s*Completion Details\s*$", re.M),
    "treatment": re.compile(r"^\s*Treatment Details\s*$", re.M),
    "zones": re.compile(r"^\s*Zones\s*$", re.M),
}
_QUALITY_RE = re.compile(r"Field Quality Control Report|"
                         r"RHEOLOGY DATA OF FLUID SYSTEM")

# The name of the grid's key column, which is what actually identifies the
# table. Matching on the page title alone is not enough: other vendors' well
# profiles print a bare "Zones" line over a ruled grid of their own, and the
# Sanjel job-header page prints the words "Completion Details".
_KEYCOL = {
    "completion": re.compile(r"^(?:Perf|Zone)\s*#", re.I),
    "treatment": re.compile(r"^Interval\s*#", re.I),
    "zones": re.compile(r"^Zones\b", re.I),
}

# "Sanjel Treatment Report, Shell Canada Limited 104/05-17-080-18 W6M/00
#  License #:27522" — also the banner on the Zones page, minus the report name
# `client` is length-bounded on purpose. Unbounded, this pattern is
# superlinear in the length of the string it is searched over, and the string
# is a whole page of text with its newlines collapsed — 0.26s on a 5k-char
# page, minutes over a 300-page filing. See _banner_page's literal gate.
_BANNER = re.compile(r"(?P<client>[^,]{0,80}),?\s*"
                     r"(?P<uwi>\d{3}/\S+(?:\s+W\d\S*)?)"
                     r"\s+License\s*#:?\s*(?P<lic>\d+)")
# The same LSD pattern sanjel.py reads off the plot pages, rebuilt the same
# way ('104/05-17-080-18 W6M/00' -> '104051708018W600'). Keeping the two in
# step is the whole point: the tables have to join to the traced curves, and
# the banner's 'W6M/00' would otherwise canonicalise to a different string.
_LSD = re.compile(r"\b(1\d\d)/(\d{2})-(\d{2})-(\d{3})-(\d{2})\s*W(\d)")

_ZONE_UNIT = re.compile(r"Amount Pumped\s*\(([^)]{1,6})\)")
# An interval key is usually a plain number, but a zone that had to be split
# and re-attempted prints as '3a' / '3b' / '7b'. Without the letter suffix
# those rows were classified as footer labels and silently left out of the
# grid — three of the 22 rows in 00014.
_INT = re.compile(r"^\d{1,3}\s*[A-Za-z]?$")
_UNIT = re.compile(
    r"^(?:m|m³|mMD|mKB|MPa|kPa|kPa/m|kg|kg/m|kg/m³|m/min|m³/min|sm³/min|"
    r"sm/min|scm|scm/min|Tonne|tonne|T|t|L|kW|%|°C|SG|min|"
    r"\(hh:mm\)|\(mm/dd/yy\)|hh:mm|mm/dd/yy)$")


# ------------------------------------------------------------------ geometry

def _spans(page):
    """-> [{t, size, x0, x1, y0, y1, xc, yc, rd}] in DISPLAY coordinates.

    `rd` is the line's reading direction, also rotated into display space, so
    a cell's fragments can be re-flowed in the order they were typeset."""
    m = page.rotation_matrix
    a, b, c, d = m.a, m.b, m.c, m.d
    out = []
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            dx, dy = ln.get("dir", (1.0, 0.0))
            rd = (dx * a + dy * c, dx * b + dy * d)
            for s in ln["spans"]:
                t = s["text"].strip()
                if not t:
                    continue
                r = fitz.Rect(s["bbox"]) * m
                out.append({"t": t, "size": s.get("size", 0.0),
                            "x0": r.x0, "x1": r.x1, "y0": r.y0, "y1": r.y1,
                            "xc": (r.x0 + r.x1) / 2, "yc": (r.y0 + r.y1) / 2,
                            "rd": rd})
    return out


def _rules(page):
    """-> (vertical, horizontal) ruling segments in display coordinates:
    v = [(x, y0, y1)], h = [(y, x0, x1)]. Hairline rects count as their
    edges — Sanjel draws some borders as filled rectangles."""
    m = page.rotation_matrix
    v, h = [], []
    for g in page.get_drawings():
        for it in g["items"]:
            if it[0] == "l":
                p, q = it[1] * m, it[2] * m
                segs = [(p.x, p.y, q.x, q.y)]
            elif it[0] == "re":
                r = it[1] * m
                segs = [(r.x0, r.y0, r.x0, r.y1), (r.x1, r.y0, r.x1, r.y1),
                        (r.x0, r.y0, r.x1, r.y0), (r.x0, r.y1, r.x1, r.y1)]
            else:
                continue
            for x0, y0, x1, y1 in segs:
                if abs(x1 - x0) <= 1.0 and abs(y1 - y0) > 1.5:
                    v.append(((x0 + x1) / 2, min(y0, y1), max(y0, y1)))
                elif abs(y1 - y0) <= 1.0 and abs(x1 - x0) > 1.5:
                    h.append(((y0 + y1) / 2, min(x0, x1), max(x0, x1)))
    return v, h


def _cluster(vals, tol):
    """sorted values -> [[members], ...], greedy, chained on the gap."""
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def _covered(intervals):
    """union length of [(a, b), ...]."""
    tot, end = 0.0, None
    start = None
    for a, b in sorted(intervals):
        if end is None or a > end:
            if end is not None:
                tot += end - start
            start, end = a, b
        else:
            end = max(end, b)
    if end is not None:
        tot += end - start
    return tot


def _cuts(page):
    """-> (xcuts, ycuts, xcov, hdrcuts) for the page's ruled table, or None.

    xcuts/ycuts are the column/row boundaries. xcov[i] is the list of y ranges
    over which boundary i is actually ruled — the merged-cell key. hdrcuts is
    a looser row-boundary list, used only above the first data row."""
    v, h = _rules(page)
    if len(v) < 3 or len(h) < 3:
        return None

    # Row separators are drawn cell by cell, so a full-width rule only exists
    # as the union of its segments — cluster on y first, then measure.
    hgroups = {}
    for y, x0, x1 in h:
        hgroups.setdefault(round(y, 1), []).append((x0, x1))
    hrows = []
    for grp in _cluster(sorted(hgroups), 2.0):
        segs = [s for k in grp for s in hgroups[k]]
        hrows.append((sum(grp) / len(grp), _covered(segs),
                      min(a for a, _b in segs), max(b for _a, b in segs)))
    width = max(c for _y, c, _a, _b in hrows)
    ycuts = [y for y, c, _a, _b in hrows if c >= 0.55 * width]
    if len(ycuts) < 3:
        return None
    # the table's own left/right edge is the extent MOST of those rules share;
    # taking the min/max would swallow the page frame, which is also ruled
    # full width and would add a phantom first and last column
    tally = {}
    for _y, c, a, b in hrows:
        if c >= 0.55 * width:
            key = (round(a), round(b))
            tally[key] = tally.get(key, 0) + 1
    xlo, xhi = max(tally, key=lambda k: (tally[k], k[1] - k[0]))
    top, bot = ycuts[0], ycuts[-1]
    height = bot - top
    if height <= 0:
        return None

    groups = {}
    for x, y0, y1 in v:
        if xlo - 2 <= x <= xhi + 2:
            groups.setdefault(round(x, 1), []).append((y0, y1))
    cand = []
    for grp in _cluster(sorted(groups), 2.0):
        segs = [s for k in grp for s in groups[k]]
        cov = _covered(segs)
        if cov < max(4.0, 0.02 * height):
            continue                      # a tick or a box corner, not a rule
        cand.append((sum(grp) / len(grp), segs, cov))
    strong = [c for c in cand if c[2] >= 0.40 * height]
    # The Zones grid rules its column borders across the HEADER ROW ONLY —
    # the body is open. Trust the full-height rules where there are enough of
    # them, and fall back to the header-only rules where they leave a column
    # implausibly wide (or where there are barely any at all).
    if len(strong) >= 4:
        xs = [c[0] for c in strong]
        gaps = sorted(b - a for a, b in zip(xs, xs[1:]))
        med = gaps[len(gaps) // 2]
        wide = [(a, b) for a, b in zip(xs, xs[1:]) if b - a > 2.5 * med]
        keep = list(strong)
        for c in cand:
            if any(a < c[0] < b for a, b in wide):
                keep.append(c)
        cand = sorted(keep, key=lambda c: c[0])
    xcuts = [c[0] for c in cand]
    xcov = [c[1] for c in cand]
    if len(xcuts) < 3:
        return None
    # The rule that separates the header's label row from its unit row is
    # only drawn under the columns that HAVE a unit, so it can fall well
    # short of the 55% the data-row rules clear. Header bands therefore get
    # their own, looser, cut list — without it 'Top Packer' and 'mMD' land in
    # one cell and every unit is lost.
    hdr = [y for y, c, _a, _b in hrows if c >= 0.15 * width]
    return xcuts, ycuts, xcov, hdr


def _read_order(items):
    """the spans of one cell, in the order the report typeset them."""
    if len(items) < 2:
        return list(items)
    rds = {}
    for s in items:
        rds[(round(s["rd"][0]), round(s["rd"][1]))] = \
            rds.get((round(s["rd"][0]), round(s["rd"][1])), 0) + 1
    rdx, rdy = max(rds, key=rds.get)
    if rdx == 0 and rdy == 0:
        rdx, rdy = 1, 0
    px, py = -rdy, rdx                      # the line-advance axis

    def start(s):
        return min(x * rdx + y * rdy
                   for x in (s["x0"], s["x1"]) for y in (s["y0"], s["y1"]))

    def perp(s):
        return s["xc"] * px + s["yc"] * py

    lines = []
    for s in sorted(items, key=perp):
        if lines and perp(s) - lines[-1][0] <= 4.0:
            lines[-1][1].append(s)
        else:
            lines.append([perp(s), [s]])
        lines[-1][0] = perp(s)
    out = []
    for _p, grp in lines:
        out.extend(sorted(grp, key=start))
    return out


def _join(items):
    """cell spans -> one string, superscripts folded back in.

    A lone digit set in a smaller font is the m³ / N₂ superscript that landed
    in its own span; it glues on with no space. So does a fragment that opens
    with '/', which is how 'm' '3' '/min' arrives."""
    parts, prev = [], 0.0
    for s in _read_order(items):
        t = s["t"]
        glue = parts and (
            (re.fullmatch(r"\d{1,2}", t) and s["size"] < 0.92 * prev)
            or t.startswith("/") or parts[-1].endswith("/"))
        if glue:
            parts[-1] += t
        else:
            parts.append(t)
        prev = s["size"] or prev
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _clean_name(text):
    """header text only — data cells are handed back exactly as printed, so a
    remark reading '33m3' is not quietly rewritten to '33m³'."""
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"(?<=m)3(?!\d)", "³", t)            # m3, kg/m3, sm3/min
    t = re.sub(r"\s+([)\]])", r"\1", t)
    t = re.sub(r"([(\[])\s+", r"\1", t)
    return t.strip(" -")


# -------------------------------------------------------------------- tables

def _grid(page):
    """-> (columns, rows) for the page's ruled table.

    rows is [(label, [cell, ...]), ...] in page order; `label` is the first
    column's text so the caller can split interval rows from the Avg /
    Total-or-Max footer rows the report prints. None if no table."""
    cut = _cuts(page)
    if cut is None:
        return None
    xcuts, ycuts, xcov, hdrcuts = cut
    spans = _spans(page)
    ncol = len(xcuts) - 1

    def cell(x0, x1, y0, y1):
        """spans whose centre falls in the box. Band membership is decided on
        the centre alone and never with slop at both edges — an overlapping
        tolerance double-counts a header that sits on a rule and prints the
        group name twice."""
        return [s for s in spans
                if x0 <= s["xc"] < x1 and y0 <= s["yc"] < y1]

    # the table's outer edges get a little slack: a value can sit a hair
    # outside the border rule, and there is nothing beyond it to steal
    xb = list(xcuts)
    xb[0] -= 4
    xb[-1] += 4

    # ---- where the data starts: the first band whose first column is a
    # plain integer (Perf # / Interval # / zone number)
    first = None
    for i in range(len(ycuts) - 1):
        if _INT.fullmatch(_join(cell(xb[0], xb[1],
                                     ycuts[i], ycuts[i + 1]))):
            first = i
            break
    if first is None or first == 0:
        return None

    # ---- header: every band above the data, read per merged cell
    def ruled_at(j, y):
        """is boundary j actually drawn at height y?"""
        return any(a - 1.5 <= y <= b + 1.5 for a, b in xcov[j])

    hband = [y for y in hdrcuts if ycuts[0] - 0.5 <= y <= ycuts[first] + 0.5]
    if len(hband) < 2:
        hband = ycuts[:first + 1]

    names = [[] for _ in range(ncol)]
    for i in range(len(hband) - 1):
        ya, yb = hband[i], hband[i + 1]
        mid = (ya + yb) / 2
        # merged cells = runs of columns between boundaries drawn at this height
        runs, lo = [], 0
        for j in range(1, ncol):
            if ruled_at(j, mid):
                runs.append((lo, j))
                lo = j
        runs.append((lo, ncol))
        if len(runs) == 1:
            continue                       # a full-width band: the page title
        for a, b in runs:
            txt = _clean_name(_join(cell(xb[a], xb[b], ya, yb)))
            if not txt:
                continue
            for j in range(a, b):
                names[j].append(txt)

    # ---- the last header band is the unit row when it reads like units. The
    # Zones grid has no unit row at all — its bottom header band is the list
    # of product codes, and treating those as units would lose every name.
    tail = [n[-1] for n in names if n]
    hits = sum(1 for t in tail if _UNIT.fullmatch(t))
    unit_row = bool(tail) and hits >= max(2, len(tail) // 2)

    columns = []
    for parts in names:
        # 'Proppant' is the literal that sits above every proppant name; the
        # name below it is the part that identifies the block
        parts = [p for p in parts if p and p.lower() != "proppant"]
        unit = ""
        if unit_row and parts and _UNIT.fullmatch(parts[-1]):
            unit = parts.pop()
        # a band holding only a parenthetical ('Volumes' and '(Total)' rule
        # into two bands) belongs to the band before it, not beside it
        merged = []
        for p in parts:
            if merged and p.startswith("("):
                merged[-1] += " " + p
            else:
                merged.append(p)
        name = " — ".join(merged)
        if unit:
            if not unit.startswith("("):
                unit = f"({unit})"
            name = f"{name} {unit}".strip()
        columns.append(name)

    # ---- body
    rows = []
    for i in range(first, len(ycuts) - 1):
        ya, yb = ycuts[i], ycuts[i + 1]
        cells = [_join(cell(xb[j], xb[j + 1], ya, yb)) for j in range(ncol)]
        if any(cells):
            rows.append((cells[0], cells))
    if not rows:
        return None
    return columns, rows


def _drop_empty(columns, rows):
    """drop the unnamed spacer columns Sanjel rules but never fills."""
    keep = [j for j in range(len(columns))
            if columns[j] or any(r[j] for r in rows)]
    return ([columns[j] for j in keep],
            [[r[j] for j in keep] for r in rows])


# ------------------------------------------------------------------ document

def _table_for(page, kind):
    """the page's grid, but only if it really is `kind`'s table."""
    if not _TITLE_RE[kind].search(page.get_text()):
        return None
    g = _grid(page)
    if not g:
        return None
    if not _KEYCOL[kind].match(g[0][0].strip()):
        return None
    return g


def _banner_page(page):
    """(client, uwi) off one page's 'Sanjel Treatment Report, ... License #:'
    banner, or None if the page carries no banner."""
    text = " ".join(page.get_text().split())
    if "License" not in text:
        return None         # cheap literal gate; _BANNER is far from cheap
    m = _BANNER.search(text)
    if not m:
        return None
    client = re.split(r"\bfor\s+", m.group("client").strip(" ,"))[-1]
    lsd = _LSD.search(m.group("uwi")) or _LSD.search(text)
    uwi = ("".join(lsd.groups()[:5]) + "W" + lsd.group(6) + "00"
           if lsd else m.group("uwi").strip())
    return client.strip(), uwi


def _banner(doc, pages=()):
    """(client, uwi) off the 'Sanjel Treatment Report, ... License #:' banner.

    Read from the table pages themselves: a COMP filing bundles several wells,
    so the first 'License #' in the document is often somebody else's."""
    for p in list(pages) or range(1, doc.page_count + 1):
        if not 1 <= p <= doc.page_count:
            continue
        got = _banner_page(doc[p - 1])
        if got:
            return got
    return "", ""


def page_role(page):
    """'completion' | 'treatment' | 'zones' | 'quality' | None.

    Structural, not textual: the Sanjel job-header page also prints the words
    "Completion Details", and claiming it would emit a one-row junk table.

    Stateless, so it cannot see a continuation page that omits the page
    title. `find_summary_pages` does not use it for that reason — it is kept
    as a single-page convenience for callers that only want a label."""
    if _QUALITY_RE.search(page.get_text()):
        return "quality"
    for kind in _TITLE_RE:
        try:
            g = _table_for(page, kind)
        except Exception:
            g = None
        if g and len(g[1]) >= 2:
            return kind
    return None


# Named "UWI" on purpose: pipeline._normalise_tables prepends a document-level
# UWI column to every table that has not got one, and on a multi-well filing
# that document-level value is right for only one of the wells. Emitting the
# per-row UWI under this name makes the pipeline leave it alone.
WELL_COL = "UWI"
# carried on the row under a key no printed header can collide with, and
# renamed to WELL_COL only on the way out
_UWI_KEY = "\x00uwi"


def _same_shape(prev, cols):
    """does `cols` continue the grid `prev`, judged on header names alone?"""
    if not prev or not cols:
        return False
    common = len(set(prev) & set(cols))
    return common >= max(3, int(0.6 * min(len(prev), len(cols))))


def _grid_pages(doc, kind):
    """[(page1, cols, body)] — the pages carrying `kind`'s grid, in order.

    Shared by find_summary_pages and _parse_kind so that the pages the viewer
    offers are exactly the pages the rows were read from.

    A continuation page is accepted on its HEADER, not on the page title:
    requiring the title on every page loses the tail of any report that
    prints it once, and requiring two body rows loses a page carrying the
    job's last interval on its own. Both losses are silent, and both cost
    whole intervals."""
    out = []
    prev_cols, last_page = None, None
    for p in range(doc.page_count):
        page = doc[p]
        titled = bool(_TITLE_RE[kind].search(page.get_text()))
        cont = last_page is not None and (p + 1) - last_page <= 2
        if not titled and not cont:
            continue
        try:
            g = _grid(page)
        except Exception:
            continue
        if not g or not _KEYCOL[kind].match(g[0][0].strip()):
            continue
        cols, body = _drop_empty(g[0], [c for _l, c in g[1]])
        if not body:
            continue
        if not cont and len(body) < 2:
            continue            # one row on a fresh page is not a table
        if cont and not titled and not _same_shape(prev_cols, cols):
            continue
        prev_cols, last_page = cols, p + 1
        out.append((p + 1, cols, body))
    return out


def find_summary_pages(doc):
    """[{kind, title, pages:[1-based]}] — consecutive same-kind pages grouped."""
    role = {}
    for kind in _TITLE_RE:
        try:
            for page1, _cols, _body in _grid_pages(doc, kind):
                role.setdefault(page1, kind)
        except Exception:
            continue
    groups = []
    for p in range(doc.page_count):
        page1 = p + 1
        kind = role.get(page1)
        if kind is None:
            try:
                if _QUALITY_RE.search(doc[p].get_text()):
                    kind = "quality"
            except Exception:
                kind = None
        if kind is None:
            continue
        if groups and groups[-1]["kind"] == kind and \
                page1 - groups[-1]["pages"][-1] <= 2:
            groups[-1]["pages"].append(page1)
        else:
            groups.append({"kind": kind, "title": KIND_TITLES.get(kind, kind),
                           "pages": [page1]})
    return groups


def _parse_kind(doc, kind):
    """-> {columns, rows, totals, pages, empty_columns} for one of the three
    grids, or None.

    A long well splits its grid over consecutive pages; those are stitched on
    matching column names, and a continuation page that adds columns (a
    proppant only used late in the job) widens the table rather than being
    dropped.

    Two things here exist to stop intervals merging, which is the failure
    this family of parsers keeps hitting:

      * A COMP filing can bundle more than one well, and each well restarts
        its interval numbering at 1. When more than one banner UWI feeds the
        same grid a per-row `UWI` column is added so the two treatments stay
        distinguishable. On a single-well filing this is a no-op.
      * A footer label that repeats across pages is kept under a page-tagged
        key instead of overwriting the earlier one.

    Columns that are ruled and named but hold no value anywhere in the
    document are dropped before returning: a 0%-filled column is not data."""
    columns, rows, totals, pages = [], [], {}, []
    cur_uwi = ""
    for p1, cols, body in _grid_pages(doc, kind):
        page = doc[p1 - 1]
        if kind == "zones":
            # the Zones grid names its unit in the page title only:
            # "Chemical Amount Pumped (L) for <client> <uwi> License #:..."
            u = _ZONE_UNIT.search(page.get_text())
            if u:
                cols = [cols[0]] + [f"{c} ({u.group(1)})" if c else c
                                    for c in cols[1:]]
        got = _banner_page(page)
        if got and got[1]:
            cur_uwi = got[1]
        pages.append(p1)
        idx = {}
        for j, c in enumerate(cols):
            name = c or f"col{j + 1}"
            while name in idx:
                name += " "
            idx[name] = j
            if name not in columns:
                columns.append(name)
        for cells in body:
            label = cells[0]
            row = {n: cells[j] for n, j in idx.items()}
            row[_UWI_KEY] = cur_uwi
            if _INT.fullmatch(label):
                rows.append(row)
            elif label:
                key = label
                n = 1
                while key in totals:
                    n += 1
                    key = (f"{label} (p{p1})" if n == 2
                           else f"{label} (p{p1}.{n})")
                totals[key] = row
    if not rows:
        return None

    keycol = columns[0]
    multi = len({r[_UWI_KEY] for r in rows if r[_UWI_KEY]}) > 1
    wcol = WELL_COL
    if multi:
        while wcol in columns:
            wcol += " "
        columns.insert(0, wcol)
    for r in list(rows) + list(totals.values()):
        v = r.pop(_UWI_KEY, "")
        if multi:
            r[wcol] = v

    def live(c):
        # judged on the INTERVAL rows only. The footer is not evidence: on a
        # nitrogen-free, acid-free job (00013) Sanjel still prints the Avg and
        # Total rows of the N2 rate, N2 volume, Spear Head Acid and
        # "Slurry Conc. > 1500 kg/m³" columns as "0.0" over eighteen blank
        # cells. Keeping those on the strength of a zero total ships five
        # columns of nothing and reads as a measured zero.
        return (c == keycol or (multi and c == wcol)
                or any(r.get(c, "").strip() for r in rows))

    kept = [c for c in columns if live(c)]
    dropped = [c for c in columns if c not in kept]
    grid = [[r.get(c, "") for c in kept] for r in rows]
    return {"columns": kept, "rows": grid, "pages": pages,
            "empty_columns": dropped,
            "totals": {k: [v.get(c, "") for c in kept]
                       for k, v in totals.items()}}


def parse_completion_details(doc):
    return _parse_kind(doc, "completion")


def parse_treatment_details(doc):
    return _parse_kind(doc, "treatment")


def parse_zones(doc):
    return _parse_kind(doc, "zones")


def parse_all(doc):
    """[{title, columns, rows, totals, pages, well, uwi}] for whichever of the
    three per-interval grids this report carries, in report order."""
    out = []
    for kind in ("completion", "treatment", "zones"):
        try:
            tab = _parse_kind(doc, kind)
        except Exception:
            tab = None
        if not tab:
            continue
        tab["title"] = TABLE_TITLES[kind]
        tab["kind"] = kind
        out.append(tab)
    if not out:
        # _banner falls back to scanning the whole document when it is given
        # no pages, so on the ~95% of the corpus that is not Sanjel this call
        # used to read and regex-search every page for nothing.
        return out
    pages = [p for t in out for p in t["pages"]]
    well, uwi = _banner(doc, pages)
    for tab in out:
        tab["well"] = well
        # The banner's UWI is reported, not trusted. On every 2015-16 file
        # checked it names a different well than the filing it sits in —
        # 00013 prints 104/05-17-080-18 inside 103031708018W600, 00014 prints
        # 102/04-17-080-18 inside 102031708018W600, 00019 prints
        # 100/05-15-080-18 inside 107031708018W600 — while the banner's
        # License # matches the filing's WA number every time. BCER's own
        # metadata is the authority on which well a filing is for, so `uwi`
        # is left empty and pipeline._normalise_tables falls back to
        # filename_uwi. Emitting the printed value would override a correct
        # UWI with a wrong one on every Sanjel table.
        tab["banner_uwi"] = uwi
        tab["uwi"] = ""
    return out
