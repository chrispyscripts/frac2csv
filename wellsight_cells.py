"""A WellSight log's Porosity and Grain Size cells, as LAS curves.

Some tracks of a StripLog / HorizontalLog are not curves and not symbols
but a grid of cells: a row every 0.5 m (or 1, 0.25, 0.1 m) down the whole
log, a cell per printed sub-column, each cell filled or empty. Two kinds are
on the WellSight drive:

  Porosity     most often eight cells on a porosity scale, 0 to 24 %, 3 %
               each, labelled "24% 18% 12% 6%" (or every 3 %, or as ranges
               "21-24+ ... 0-3"). A row is filled as a bar from the 0 % end
               as far as the porosity it shows, so it holds one value: the
               porosity where its bar ends (9 % for three cells; checked on
               the printouts). Some logs label the cells as grades instead
               (Excellent ... Very Poor), with no porosity on them.
  Grain Size   five to seven cells, most often "1/16 mm, 1/8 mm, 1/4 mm,
  (Grain/      1/2 mm, 1 mm", one per printed row, each named by the bottom
  CrystalSize) of its grain-size class (the 1/16 mm cell is very fine sand:
               the log's descriptions say so, and labels that spell it out
               read "VERY FINE 1/16-1/8 mm"). A row can fill one cell or a
               run of them (very fine to medium), so each cell is a curve of
               its own.

How the file stores one (after the column's own title, the second time it is
written): 01, <u32 k cells>, <u32 0/1>, <u8 0/1>, <u32 L labels>, L
length-prefixed labels, <u32 colour>, <f64 step>, one byte, <u32 n rows>,
then n rows of <u32 k> and k bytes (1 = filled). Row i covers top + i*step
down to top + (i+1)*step, as the lithology column's samples do (grain-size
cells line up with the rock column at no offset, and a bar on the printout
starts at the row's depth).

Logs label the cells their own way ("Very Fine", "vf", "L-U vf" over two
cells each, "1/8mm", typos such as "course"; some in reverse order), so
every log is put on one standard set, the most common one on the drive:

  POR                   porosity, %, where the bar ends (0-24 %, 3 % cells)
  GS_1_16MM .. GS_1MM   the 1/16, 1/8, 1/4, 1/2 and 1 mm cells (very fine to
                        very coarse sand): 1 filled, 0 empty

A grain-size cell finer than very fine sand (micritic, microcrystalline,
silt) or coarser than the 1 mm class (2 mm) has no standard curve; its row
still counts as described. Where a row has no cell filled the curves are
null: nothing was marked there. A column whose cells cannot be put on the
standard set (porosity in grades, labels not known) is left out, and the LAS
says so.

Standard library only.
"""
import math
import re
import struct

KIND_POROSITY = "porosity"
KIND_GRAIN = "grain"

POROSITY_MNEM = "POR"

# the standard grain-size cells: (mnemonic, printed label, the class it is the bottom of)
GRAIN_CELLS = (("GS_1_16MM", "1/16 mm", "very fine sand, 1/16-1/8 mm"),
               ("GS_1_8MM", "1/8 mm", "fine sand, 1/8-1/4 mm"),
               ("GS_1_4MM", "1/4 mm", "medium sand, 1/4-1/2 mm"),
               ("GS_1_2MM", "1/2 mm", "coarse sand, 1/2-1 mm"),
               ("GS_1MM", "1 mm", "very coarse sand, 1-2 mm"))


def _key(label):
    """a label reduced to its letters, digits, slashes and >, lower case:
    "L-U vf" -> "luvf", "1/16 mm" -> "1/16mm", "Very Fine" -> "veryfine" """
    return re.sub(r"[^a-z0-9/>]+", "", (label or "").lower())


# label -> index into GRAIN_CELLS; None = a class outside the standard set
_GRAIN = {}
for _i, _names in enumerate((
        ("1/16mm", "1/16", "veryfine", "verfine", "vfine", "vf", "vfg", "luvf"),
        ("1/8mm", "1/8", "fine", "fn", "f", "luf"),
        ("1/4mm", "1/4", "medium", "med", "m", "lum"),
        ("1/2mm", "1/2", "coarse", "course", "crs", "c", "luc"),
        ("1mm", ">1mm", "verycoarse", "verycourse", "vcoarse", "vcourse", "vc", "luvc"))):
    for _n in _names:
        _GRAIN[_n] = _i
for _n in ("micritic", "mic", "micxl", "micxl/sltst", "micxl/siltstone", "microcrystalline", "silt", "slt", "sltst",
           "cslt", "coarsesilt", "crypt", "cryptocrystalline", "micr", "2mm", ">2mm", ">vc", "gran", "granule",
           "pebble", "pebbles", "pbl"):
    _GRAIN[_n] = None


def grain_cell(label):
    """a Grain Size cell's printed label -> index into GRAIN_CELLS; None for a
    class outside them (micritic, silt, 2 mm); KeyError for a label not known.
    A label that spells out its class reads by its words: "vf(1/16 mm)",
    "VERY FINE 1/16-1/8 mm", "v f sd", "vf snd"."""
    k = _key(label)
    if k in _GRAIN:
        return _GRAIN[k]
    words = re.match(r"[a-z /<>-]*?(?=\s*[<(0-9]|$)", (label or "").lower().strip())
    w = _key(words.group(0)) if words else ""
    w = re.sub(r"(?:snd|sd|sand|grn|gr)$", "", w) or w
    if w in _GRAIN:
        return _GRAIN[w]
    raise KeyError(label)


def _known_grain(label):
    try:
        grain_cell(label)
        return True
    except KeyError:
        return False


def porosity_scale(labels, k):
    """(zero end, % per cell) of a Porosity column from its labels: the
    largest porosity printed is the far end of the scale, spread evenly over
    the k cells ("24% 18% 12% 6%" on 8 cells: 3 % each); the zero end is the
    cell at the other end from the largest label (the last cell when the
    labels count down). None when the labels name no porosity (grades)."""
    nums = []
    for x in labels:
        v = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", x or "")]
        nums.append(max(v) if v else None)
    known = [v for v in nums if v is not None]
    if len(known) < 2 or max(known) <= 0:
        return None
    first = next(v for v in nums if v is not None)
    last = next(v for v in reversed(nums) if v is not None)
    zero = k - 1 if first > last else 0
    return zero, max(known) / k


def _kind(title):
    t = (title or "").strip().lower()
    if "grain" in t:
        return KIND_GRAIN
    if t.startswith("poros"):
        return KIND_POROSITY
    return None


def _str(b, p):
    if p + 4 > len(b):
        return None, p
    n = struct.unpack_from("<I", b, p)[0]
    if not 0 < n < 200 or p + 4 + n > len(b):
        return None, p
    return b[p + 4:p + 4 + n].decode("latin-1"), p + 4 + n


def _grid_at(b, p, title):
    """the grid whose title starts at p, or None when what follows is not one"""
    q = p + len(title)
    if q + 14 > len(b) or b[q] != 1:
        return None
    k, flag, flag2, nlab = struct.unpack_from("<IIBI", b, q + 1)
    if not 1 <= k <= 40 or flag > 1 or flag2 > 1 or not 1 <= nlab <= 41:
        return None
    r, labels = q + 14, []
    for _ in range(nlab):
        s, r = _str(b, r)
        if s is None:
            return None
        labels.append(s)
    if r + 17 > len(b):
        return None
    step = struct.unpack_from("<d", b, r + 4)[0]
    n = struct.unpack_from("<I", b, r + 13)[0]
    if not 0.01 <= step <= 20 or not 1 <= n <= 2_000_000 or r + 17 + n * (4 + k) > len(b):
        return None
    s0, rows, kb = r + 17, [], struct.pack("<I", k)
    for _ in range(n):
        if b[s0:s0 + 4] != kb:
            return None
        rows.append(tuple(1 if v else 0 for v in b[s0 + 4:s0 + 4 + k]))
        s0 += 4 + k
    return {"title": title.decode("latin-1"), "labels": labels, "step": round(step, 6), "rows": rows}


def grids(body, titles):
    """every Porosity / Grain Size grid in an inflated log body, looked for
    under each of the log's track and column titles:
    [{title, kind, labels, step, rows}] (rows: one tuple of 0/1 per cell)"""
    out, seen = [], set()
    for t in sorted({t for t in titles if _kind(t)}):
        tb = t.encode("latin-1", "ignore")
        p = body.find(tb)
        while p >= 0:
            if p >= 4 and struct.unpack_from("<I", body, p - 4)[0] == len(tb) and p not in seen:
                g = _grid_at(body, p, tb)
                if g:
                    seen.add(p)
                    g["kind"] = _kind(t)
                    out.append(g)
            p = body.find(tb, p + 1)
    return out


def _porosity_rows(g):
    k = len(g["rows"][0])
    sc = porosity_scale(g["labels"], k)
    if sc is None:
        return None, "its cells are grades, not a porosity scale"
    zero, width = sc
    vals = []
    for r in g["rows"]:
        on = [i for i, v in enumerate(r) if v]
        if not on:
            vals.append(None)
        else:
            far = min(on) if zero == k - 1 else max(on)
            vals.append(round(abs(zero - far) * width + width, 4))
    return vals, None


def _grain_rows(g):
    labels, rows = g["labels"], g["rows"]
    k = len(rows[0])
    if k % len(labels):
        return None, "%d labels for %d cells" % (len(labels), k)
    per = k // len(labels)           # "L-U vf" on 10 cells: two cells (lower, upper) a label
    try:
        cells = [grain_cell(labels[i // per]) for i in range(k)]
    except KeyError:
        return None, "grain-size labels not known: " + ", ".join(x for x in labels if not _known_grain(x))
    if all(c is None for c in cells):
        return None, "no grain-size cell in the standard set"
    vals = []
    for r in rows:
        if not any(r):
            vals.append(None)
            continue
        on = [0] * len(GRAIN_CELLS)
        for c, v in zip(cells, r):
            if v and c is not None:
                on[c] = 1
        vals.append(tuple(on))
    return vals, None


def _row_values(g):
    """one grid -> (per row: a porosity %, or a tuple of 0/1 per standard
    grain cell; None where the row has nothing filled, None, or (None, why
    it is left out); why is None for a column left blank"""
    if not g["rows"] or not any(any(r) for r in g["rows"]):
        return None, None
    return (_porosity_rows if g["kind"] == KIND_POROSITY else _grain_rows)(g)


def _span(g, top):
    """(first, last) depth of the grid's filled rows"""
    idx = [i for i, r in enumerate(g["rows"]) if any(r)]
    return top + idx[0] * g["step"], top + (idx[-1] + 1) * g["step"]


def las_curves(found, top, depths, step):
    """The cells as curves on the LAS depths (top + k*step): each depth takes
    the row it is in (a row 0.5 m long repeats on a 0.2 m step); on a step
    coarser than the rows it takes every row from it down to the next depth,
    joined (the most porosity, any cell filled), so no row is lost.
    Returns ([(mnemonic, unit, description, values)], notes), the notes
    saying which columns were left out and why."""
    curves, notes = [], []
    por, grain = [], []
    for g in found:
        vals, why = _row_values(g)
        if vals is None:
            if why:
                notes.append("%s column (%s) left out: %s." % (g["title"], ", ".join(g["labels"]), why))
            continue
        (por if g["kind"] == KIND_POROSITY else grain).append((g, vals))

    def rows_at(g, d):
        # the row the depth is in; on a step coarser than the rows, every row
        # that starts from the depth down to the next one
        s, x = g["step"], d - top
        if s >= step - 1e-9:
            a = int(math.floor(x / s + 1e-6))
            b = a + 1
        else:
            a = int(math.ceil(x / s - 1e-6))
            b = max(a + 1, int(math.ceil((x + step) / s - 1e-6)))
        return range(max(0, a), min(len(g["rows"]), b))

    if por:
        out = []
        for d in depths:
            best = None
            for g, vals in por:
                for i in rows_at(g, d):
                    if vals[i] is not None and (best is None or vals[i] > best):
                        best = vals[i]
            out.append(best)
        g0 = por[0][0]
        k = len(g0["rows"][0])
        zero, width = porosity_scale(g0["labels"], k)
        desc = ("Porosity from the %s column's cells: where the bar ends, %g %% a cell (%d cells, printed %s; "
                "a row every %g m); null where no cell is filled"
                % (g0["title"], width, k, " ".join(g0["labels"]), g0["step"]))
        curves.append((POROSITY_MNEM, "%", desc, out))
    if grain:
        cols = [[] for _ in GRAIN_CELLS]
        for d in depths:
            on, described = [0] * len(GRAIN_CELLS), False
            for g, vals in grain:
                for i in rows_at(g, d):
                    if vals[i] is not None:
                        described = True
                        on = [x | y for x, y in zip(on, vals[i])]
            for c in range(len(GRAIN_CELLS)):
                cols[c].append(on[c] if described else None)
        g0 = grain[0][0]
        printed = {}
        for g, _ in grain:
            for x in g["labels"]:
                c = grain_cell(x)
                if c is not None and x not in printed.setdefault(c, []):
                    printed[c].append(x)
        for c, (mn, label, cls) in enumerate(GRAIN_CELLS):
            desc = ("Grain size %s cell (%s) from the %s column (printed %s; a row every %g m): "
                    "1 filled, 0 empty; null where no cell is filled"
                    % (label, cls, g0["title"], " / ".join(printed.get(c) or ["not on this log"]), g0["step"]))
            curves.append((mn, "", desc, cols[c]))
    return curves, notes


def span(found, top):
    """(first, last) depth any usable grid has a filled row, or None"""
    spans = [_span(g, top) for g in found if _row_values(g)[0] is not None]
    if not spans:
        return None
    return min(s[0] for s in spans), max(s[1] for s in spans)
