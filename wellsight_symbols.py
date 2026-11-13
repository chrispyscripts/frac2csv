"""What a WellSight log's symbols say: rock types, accessories, other symbols.

A StripLog / HorizontalLog stores more than curves. Its printout's legend
pages list three families, and the file holds all three:

  ROCK TYPES       the lithology column: one rock per depth sample, or a
                   % lithology column of ten cells (10 % each)
  ACCESSORIES      symbols placed at a depth: Mineral, Fossil, Stringer,
                   Texture
  OTHER SYMBOLS    Porosity Type, Sorting, Rounding, Oil Shows, placed at a
                   depth too; and columns of intervals (core, DST, slide),
                   events, reservoir quality

The decoder (wellsight_convert) reads them as each file stores them, and
every file carries its own symbol library: the same thing is "INTER" in one
log, "INTERGRANULAR" or "intergran./xl" in the next, and its category is
"Porosity" or "Porosity Type". On the 8,954 logs of the WellSight drive there
are 31 accessory categories and hundreds of spellings. So this module:

  normalise    each raw (category, code) -> a group and a term of that group,
               with a rank where the group is a scale (show strength,
               sorting, rounding, reservoir quality). A code it does not
               know keeps its own name, so nothing is dropped.
  analyse      one log: rock thickness and share, curve response by rock,
               symbol counts and density, show zones (oil-show symbols
               grouped by depth, with the rock, porosity and gas across
               them), and the interval columns.

Standard library only.
"""
import math
import re
import statistics

import log_vocab as V

# ---------------------------------------------------------------- groups

# group -> (label, data set). The data sets are the printout legend's three
# families; the Lab lists one entry per data set.
GROUPS = {
    "rock": ("Rock type", "rocks"),
    "mineral": ("Mineral", "accessories"),
    "fossil": ("Fossil", "accessories"),
    "stringer": ("Stringer", "accessories"),
    "texture": ("Texture", "accessories"),
    "porosity": ("Porosity type", "other"),
    "sorting": ("Sorting", "other"),
    "rounding": ("Rounding", "other"),
    "show": ("Oil show", "other"),
    "interval": ("Intervals", "other"),
    "quality": ("Reservoir quality", "other"),
    "event": ("Events", "other"),
    "directional": ("Slide / rotate", "other"),
    "perm": ("Rock class", "other"),
    "photo": ("Photos", "other"),
    "misc": ("Other", "other"),
}
# groups whose symbols are names in their own right (a rock-class label, a
# photo's caption): kept as they are, not counted as unknown
PASSTHROUGH = {"perm", "photo", "misc"}
# a symbol filed under one group that belongs to another: (group, code) -> group
_REFILE = {(g, V.norm(c)): e.key for e in V.entries("refile")
           for g, c in (s.split(":", 1) for s in e.spellings)}
DATASETS = {
    "rocks": "Rock Types",
    "accessories": "Accessories",
    "other": "Other Symbols",
}


def _key(s):
    """upper case, letters and digits only: "intergran./xl" -> "INTERGRANXL" """
    return re.sub(r"[^A-Z0-9]+", "", str(s or "").upper())


# a category as files name it -> group (log_vocab.txt [category])
_CATEGORY = {V.norm(s): e.key for e in V.entries("category") for s in e.spellings}


def group_of(category):
    return _CATEGORY.get(_key(category), "misc")


# ---------------------------------------------------------------- terms

# group -> [(term, name, rank or None, [raw codes as _key gives them])],
# from log_vocab.txt, one section per group. Rank is the place on the
# group's scale where it has one: show strength 0 dead .. 4 strong, sorting
# 1 poor .. 3 well, rounding 1 angular .. 4 rounded, reservoir quality
# 0 none .. 5 excellent.
_TERMS = {g: [(e.key, e.name, V.rank(e.extra), list(e.spellings)) for e in V.entries(g)]
          for g in V.SYMBOL_GROUPS}

# show symbols: what each says beyond its strength
SHOW_KIND = {"even": "stain", "spotted": "stain", "stain": "stain", "dead": "stain", "bitumen": "stain",
             "fluorescence": "fluorescence", "cut": "cut"}
SHOW_LEVELS = {0: "Dead", 1: "Questionable", 2: "Weak", 3: "Moderate", 4: "Strong"}
SCALES = {"show": SHOW_LEVELS,
          "sorting": {1: "Poor", 2: "Moderate", 2.5: "Moderately well", 3: "Well"},
          "rounding": {1: "Angular", 2: "Subangular", 2.5: "Subangular-subrounded", 3: "Subrounded",
                       4: "Rounded"},
          "quality": {0: "None", 1: "Very poor", 2: "Poor", 2.5: "Marginal", 3: "Fair", 4: "Good",
                      5: "Excellent"}}

_LOOKUP = {}
_NAMES = {}
for _g, _terms in _TERMS.items():
    for _t, _n, _r, _raws in _terms:
        _NAMES[(_g, _t)] = (_n, _r)
        for _raw in _raws:
            _LOOKUP.setdefault((_g, _raw), _t)
# the rock types also name stringers and minerals ("DOL"), but a term is
# looked up in its own group first

# the rock modifiers some logs fold into a rock's code ("SS ARG", "SLTST SDY")
_ROCK_MODS = {c: e.key for e in V.entries("rock modifier") for c in e.spellings}
_ROCK_COLORS = {
    "sandstone": "#f2d14b", "siltstone": "#c9a46b", "shale": "#8a9a7b", "claystone": "#a8b39b",
    "limestone": "#6fa8dc", "dolomite": "#b48ad8", "anhydrite": "#f4b6c2", "gypsum": "#f0c8d8",
    "salt": "#d9e3ec", "coal": "#1b1b1b", "chert": "#b5651d", "conglomerate": "#e39b5b",
    "breccia": "#d98c5f", "marlstone": "#9fb7a0", "bentonite": "#d9c27a", "till": "#c7c0a8",
    "igneous": "#c0504d", "metamorphic": "#7f6a93", "cement": "#9aa1a9", "blank": "#eef0f2",
}


def _unknown(raw):
    k = _key(raw)
    return "raw:" + k if k else "raw:?"


def normalise(group, raw):
    """(term, name, rank) for one raw code in its group. Unknown codes keep
    their own name, under a term starting "raw:"."""
    k = _key(raw)
    if group in PASSTHROUGH:
        if k in ("BLANK", "NONE", ""):
            return "none", "Nothing", None
        return "is:" + k, str(raw).strip(), None
    t = _LOOKUP.get((group, k))
    if t is None and group == "rock":
        t, _mods = rock_term(raw)
        if t.startswith("raw:"):
            return t, str(raw).strip() or "?", None
    if t is None:
        # "Moderate/Moderate", "Slow/Weak", "SUB ROUNDED" ... : the words one by one
        words = [_key(w) for w in re.split(r"[^A-Za-z0-9]+", str(raw or "")) if w]
        for w in reversed(words):
            t = _LOOKUP.get((group, w))
            if t:
                break
    if t is None:
        return _unknown(raw), str(raw).strip() or "?", None
    n, r = _NAMES[(group, t)]
    return t, n, r


def rock_term(raw):
    """(term, modifiers) for a rock code: "SS" -> sandstone; "SS ARG" ->
    sandstone, argillaceous; "SANDSTONE_SILTSTONE" -> sandstone, silty;
    "Bakken" -> raw:BAKKEN (a log's own name, kept)."""
    k = _key(raw)
    t = _LOOKUP.get(("rock", k))
    if t:
        return t, []
    words = [_key(w) for w in re.split(r"[^A-Za-z0-9]+", str(raw or "")) if w]
    for i, w in enumerate(words):
        t = _LOOKUP.get(("rock", w))
        if t:
            mods = []
            for m in words[:i] + words[i + 1:]:
                if m in _ROCK_MODS:
                    mods.append(_ROCK_MODS[m])
                elif _LOOKUP.get(("rock", m)):
                    mods.append(_NAMES[("rock", _LOOKUP[("rock", m)])][0].lower())
            return t, mods
    # "PAY ZONE SAND", "DOL2", "SLTSTGY": a known rock code at the start
    for code in sorted({r for (g, r) in _LOOKUP if g == "rock"}, key=len, reverse=True):
        if len(code) >= 2 and k.startswith(code) and len(code) >= 0.5 * len(k):
            return _LOOKUP[("rock", code)], []
    if "SAND" in k:
        return "sandstone", []
    return _unknown(raw), []


def rock_color(term):
    if term in _ROCK_COLORS:
        return _ROCK_COLORS[term]
    h = 0
    for ch in term:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return "hsl(%d 40%% 62%%)" % (h % 360)


# ---------------------------------------------------------------- one log

def symbols_from(accessories):
    """The decoder's accessories -> normalised symbols, depth-sorted:
    {depth, group, term, name, rank, raw, category}."""
    out = []
    for a in accessories or []:
        g = group_of(a.get("category"))
        g = _REFILE.get((g, _key(a.get("code"))), g)
        t, n, r = normalise(g, a.get("code"))
        if t == "none":
            continue
        out.append({"depth": a["depth_m"], "group": g, "term": t, "name": n, "rank": r,
                    "raw": a.get("code"), "category": a.get("category")})
    out.sort(key=lambda s: (s["depth"], s["group"]))
    return out


def rocks_from(intervals):
    """lithology intervals {top, base, code} -> normalised, neighbours of the
    same rock merged."""
    out = []
    for iv in intervals or []:
        t, mods = rock_term(iv.get("code"))
        name = _NAMES[("rock", t)][0] if ("rock", t) in _NAMES else (iv.get("rock") or iv.get("code"))
        rec = {"top": iv["top"], "base": iv["base"], "rock": t, "name": name, "mods": mods,
               "raw": iv.get("code"), "color": rock_color(t)}
        if out and out[-1]["rock"] == t and out[-1]["mods"] == mods and abs(out[-1]["base"] - rec["top"]) < 1e-6:
            out[-1]["base"] = rec["base"]
        else:
            out.append(rec)
    return out


def columns_from(symbol_columns):
    """the decoder's other symbol columns (intervals, reservoir quality,
    slide/rotate) -> normalised intervals, "nothing" runs left out:
    {top, base, group, term, name, rank, raw, column}"""
    out = []
    for c in symbol_columns or []:
        g = group_of(c.get("category"))
        if g in ("rock", "misc"):
            # a "Slide / Rotate" bar drawn with lithology fill, or an odd one
            title = _key(c.get("column"))
            g = "directional" if ("SLIDE" in title or "ROTATE" in title) else \
                "quality" if "QUALITY" in title else "interval" if "INTERVAL" in title else g
        for iv in c.get("intervals") or []:
            for raw in iv.get("symbols") or []:
                k = _key(raw)
                gg = "directional" if "SLIDE" in k or "ROTATE" in k else _REFILE.get((g, k), g)
                if gg == "directional" and k not in ("SLIDE", "SLIDES", "SLIDEHZ", "ORIENTSLIDE", "ROTATE",
                                                       "NONE", "BLANK"):
                    # a slide bar drawn with a lithology fill: the fill means "sliding"
                    raw = "SLIDE"
                t, n, r = normalise(gg, raw)
                if t == "none":
                    continue
                out.append({"top": iv["top_m"], "base": iv["base_m"], "group": gg, "term": t, "name": n,
                            "rank": r, "raw": raw, "column": c.get("column")})
    out.sort(key=lambda r: (r["top"], r["group"]))
    return out


def _spacing(depths):
    """the log's usual distance between neighbouring symbol depths: how far
    apart the cuttings were described (5 m on a vertical log, 1-2 m on many
    laterals)"""
    ds = sorted(set(round(d, 3) for d in depths))
    gaps = [b - a for a, b in zip(ds, ds[1:]) if b - a > 0.01]
    if not gaps:
        return 1.0
    return min(10.0, max(0.5, statistics.median(gaps)))


def _clusters(depths, spacing):
    """runs of depths no more than 1.5 spacings apart -> [(first, last)]"""
    out = []
    for d in sorted(depths):
        if out and d - out[-1][1] <= 1.5 * spacing + 1e-6:
            out[-1][1] = d
        else:
            out.append([d, d])
    return [(a, b) for a, b in out]


class Curves:
    """the log's curves on their regular grid, looked up by depth"""

    def __init__(self, curves, depth0, step):
        self.curves = curves or []
        self.d0, self.step = depth0, step

    def values(self, c, top, base):
        """the samples from top down to, not including, base: an interval's
        base is the next one's top"""
        if self.d0 is None or not self.step:
            return []
        i0 = max(0, int(math.ceil((top - self.d0) / self.step - 1e-9)))
        i1 = min(len(c["values"]) - 1, int(math.ceil((base - self.d0) / self.step - 1e-9)) - 1)
        return [v for v in c["values"][i0:i1 + 1] if v is not None]

    def find(self, pattern):
        rx = re.compile(pattern, re.I)
        for c in self.curves:
            if rx.search(c.get("mnemonic") or "") or rx.search(c.get("name") or ""):
                return c
        return None


def _stats(vals):
    if not vals:
        return None
    v = sorted(vals)
    q = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]   # noqa: E731
    return {"n": len(v), "mean": round(sum(v) / len(v), 4), "p10": q(0.1), "p50": q(0.5), "p90": q(0.9)}


def analyse(top, bottom, rock_intervals, symbols, column_intervals, curves=None, depth0=None, step=None,
            percent=None):
    """One log's rock types, accessories and other symbols.

    rock_intervals:   rocks_from(...)      symbols: symbols_from(...)
    column_intervals: columns_from(...)    curves: the payload's curves on
    the grid starting at depth0 every step.
    percent: {"rocks": [codes], "step": m, "values": [[pct per rock] per sample]}
    from a % lithology column, or None."""
    C = Curves(curves, depth0, step)
    span = (bottom - top) if (top is not None and bottom is not None and bottom > top) else None
    out = {"top": top, "bottom": bottom}

    # ---- rock types: thickness, share, how the curves read in each
    described = sum(iv["base"] - iv["top"] for iv in rock_intervals if iv["rock"] != "blank")
    by = {}
    for iv in rock_intervals:
        r = by.setdefault(iv["rock"], {"rock": iv["rock"], "name": iv["name"], "color": iv["color"],
                                        "m": 0.0, "intervals": 0, "first": iv["top"], "last": iv["base"]})
        r["m"] += iv["base"] - iv["top"]
        r["intervals"] += 1
        r["first"], r["last"] = min(r["first"], iv["top"]), max(r["last"], iv["base"])
    rocks = sorted(by.values(), key=lambda r: -r["m"])
    for r in rocks:
        r["m"] = round(r["m"], 2)
        r["pct"] = round(100 * r["m"] / described, 1) if described and r["rock"] != "blank" else None
        r["curves"] = {}
        for c in C.curves:
            vals = []
            for iv in rock_intervals:
                if iv["rock"] == r["rock"]:
                    vals += C.values(c, iv["top"], iv["base"])
            st = _stats(vals)
            if st:
                r["curves"][c["mnemonic"]] = st
    out["rocks"] = rocks
    out["described_m"] = round(described, 2)
    out["coverage_pct"] = round(100 * described / span, 1) if span else None
    if percent and percent.get("values"):
        comp = {}
        n = 0
        for row in percent["values"]:
            if row is None:
                continue
            n += 1
            for code, p in zip(percent["rocks"], row):
                t, _m = rock_term(code)
                comp[t] = comp.get(t, 0) + (p or 0)
        out["percent_mix"] = sorted(({"rock": t, "name": _NAMES.get(("rock", t), (t,))[0],
                                      "color": rock_color(t), "pct": round(v / n, 1)}
                                     for t, v in comp.items() if n and v), key=lambda x: -x["pct"])

    # ---- symbols: counts by group and term, and how densely they were placed
    groups = {}
    for s in symbols:
        g = groups.setdefault(s["group"], {"group": s["group"], "label": GROUPS[s["group"]][0],
                                            "dataset": GROUPS[s["group"]][1], "n": 0, "terms": {}})
        g["n"] += 1
        t = g["terms"].setdefault(s["term"], {"term": s["term"], "name": s["name"], "rank": s["rank"],
                                               "n": 0, "first": s["depth"], "last": s["depth"],
                                               "raw": set()})
        t["n"] += 1
        t["first"], t["last"] = min(t["first"], s["depth"]), max(t["last"], s["depth"])
        t["raw"].add(str(s["raw"]))
    for g in groups.values():
        g["per_100m"] = round(100 * g["n"] / span, 1) if span else None
        g["terms"] = sorted(({**t, "raw": sorted(t["raw"])} for t in g["terms"].values()),
                            key=lambda t: (-t["n"], t["name"]))
        g["unknown"] = sum(t["n"] for t in g["terms"] if t["term"].startswith("raw:"))
    out["groups"] = groups
    out["symbols"] = len(symbols)
    out["unknown_symbols"] = sum(g["unknown"] for g in groups.values())

    # ---- show zones: the oil-show symbols, grouped where they run on.
    # Shows are placed once per described sample, and on a lateral the
    # samples are hand-placed (every 4-6 m on 07I231) with the other
    # symbols in between, so the shows' own spacing says when a run of
    # them is broken: a gap of more than one and a half of their usual
    # gaps starts a new zone.
    shows = [s for s in symbols if s["group"] == "show" and s["term"] not in ("none",)]
    spacing = _spacing([s["depth"] for s in (shows if len(shows) >= 3 else symbols)]) if symbols else 1.0
    out["sample_spacing_m"] = round(spacing, 2)
    gas = C.find(r"gas|\bTG\b|C1")
    rop = C.find(r"\bROP\b|rate of pen|penetration")
    gamma = C.find(r"gamma|\bGR\b|\bAPI\b")
    gas_bg = None
    if gas:
        allg = [v for v in gas["values"] if v is not None]
        gas_bg = statistics.median(allg) if allg else None
    zones = []
    for a, b in _clusters([s["depth"] for s in shows], spacing):
        base = b + spacing
        mine = [s for s in shows if a - 1e-6 <= s["depth"] <= b + 1e-6]
        level = max((s["rank"] for s in mine if s["rank"] is not None), default=None)
        kinds = sorted({SHOW_KIND[s["term"]] for s in mine if s["term"] in SHOW_KIND})
        terms = sorted({s["name"] for s in mine})
        z = {"top": round(a, 2), "base": round(base, 2), "m": round(base - a, 2), "symbols": len(mine),
             "level": level, "strength": SHOW_LEVELS.get(level, "—") if level is not None else "—",
             "kinds": kinds, "terms": terms}
        # what else was described across the zone
        near = [s for s in symbols if a - 1e-6 <= s["depth"] <= base + 1e-6]
        z["porosity"] = sorted({s["name"] for s in near if s["group"] == "porosity"})
        srt = [s["rank"] for s in near if s["group"] == "sorting" and s["rank"] is not None]
        rnd = [s["rank"] for s in near if s["group"] == "rounding" and s["rank"] is not None]
        z["sorting"] = SCALES["sorting"].get(_nearest(SCALES["sorting"], statistics.mean(srt))) if srt else None
        z["rounding"] = SCALES["rounding"].get(_nearest(SCALES["rounding"], statistics.mean(rnd))) if rnd else None
        z["texture"] = sorted({s["name"] for s in near if s["group"] == "texture"})
        cover = {}
        for iv in rock_intervals:
            o = min(base, iv["base"]) - max(a, iv["top"])
            if o > 0 and iv["rock"] != "blank":
                cover[iv["name"]] = cover.get(iv["name"], 0) + o
        z["rocks"] = [k for k, _v in sorted(cover.items(), key=lambda kv: -kv[1])]
        q = [c for c in column_intervals if c["group"] == "quality" and c["base"] > a and c["top"] < base]
        z["quality"] = max((c["name"] for c in q), key=lambda n: _rank_of("quality", n), default=None)
        for label, c in (("gas", gas), ("rop", rop), ("gamma", gamma)):
            vals = C.values(c, a, base) if c else []
            z[label] = {"curve": c["mnemonic"], "mean": round(sum(vals) / len(vals), 4),
                        "max": max(vals)} if vals else None
        if z["gas"] and gas_bg:
            z["gas"]["x_background"] = round(z["gas"]["mean"] / gas_bg, 2) if gas_bg > 0 else None
        z["score"] = _zone_score(z)
        zones.append(z)
    out["show_zones"] = zones
    out["gas_background"] = round(gas_bg, 4) if gas_bg is not None else None

    # ---- interval columns: cores, tests, slides, reservoir quality
    ivs = {}
    for c in column_intervals:
        k = (c["group"], c["term"])
        r = ivs.setdefault(k, {"group": c["group"], "term": c["term"], "name": c["name"], "rank": c["rank"],
                               "n": 0, "m": 0.0, "first": c["top"], "last": c["base"]})
        r["n"] += 1
        r["m"] += c["base"] - c["top"]
        r["first"], r["last"] = min(r["first"], c["top"]), max(r["last"], c["base"])
    out["intervals"] = sorted(({**r, "m": round(r["m"], 2)} for r in ivs.values()),
                              key=lambda r: (r["group"], -r["m"]))
    return out


def _nearest(scale, v):
    return min(scale, key=lambda k: abs(k - v))


def _rank_of(group, name):
    for (g, _t), (n, r) in _NAMES.items():
        if g == group and n == name:
            return r if r is not None else -1
    return -1


def _zone_score(z):
    """a rough order for the zones: show strength first, then the gas over
    background, the porosity described and the thickness"""
    s = 10.0 * (z["level"] or 0)
    if z.get("gas") and z["gas"].get("x_background"):
        s += min(10.0, 2.0 * z["gas"]["x_background"])
    s += 2.0 * min(3, len(z.get("porosity") or []))
    s += min(5.0, z["m"] / 2.0)
    return round(s, 1)


# ---------------------------------------------------------------- tables

def rows_rocks(rock_intervals):
    yield ["top_m", "base_m", "rock", "name", "modifiers", "code_in_file"]
    for iv in rock_intervals:
        yield [iv["top"], iv["base"], iv["rock"], iv["name"], " ".join(iv["mods"]), iv["raw"]]


def rows_symbols(symbols):
    yield ["depth_m", "group", "term", "name", "rank", "code_in_file", "category_in_file"]
    for s in symbols:
        yield [s["depth"], s["group"], s["term"], s["name"], "" if s["rank"] is None else s["rank"],
               s["raw"], s["category"]]


def rows_columns(column_intervals):
    yield ["top_m", "base_m", "group", "term", "name", "rank", "code_in_file", "column_in_file"]
    for c in column_intervals:
        yield [c["top"], c["base"], c["group"], c["term"], c["name"], "" if c["rank"] is None else c["rank"],
               c["raw"], c["column"]]


def rows_zones(analysis):
    yield ["top_m", "base_m", "thickness_m", "strength", "stain_fluorescence_cut", "show_symbols", "rocks",
           "porosity", "texture", "sorting", "rounding", "reservoir_quality", "gas_mean", "gas_x_background",
           "rop_mean", "gamma_mean", "score"]
    for z in analysis["show_zones"]:
        yield [z["top"], z["base"], z["m"], z["strength"], " ".join(z["kinds"]), z["symbols"],
               "; ".join(z["rocks"]), "; ".join(z["porosity"]), "; ".join(z["texture"]), z["sorting"] or "",
               z["rounding"] or "", z["quality"] or "",
               z["gas"]["mean"] if z["gas"] else "", (z["gas"] or {}).get("x_background") or "",
               z["rop"]["mean"] if z["rop"] else "", z["gamma"]["mean"] if z["gamma"] else "", z["score"]]


def csv_text(rows):
    import csv
    import io
    f = io.StringIO()
    w = csv.writer(f, lineterminator="\n")
    for r in rows:
        w.writerow(r)
    return f.getvalue()
