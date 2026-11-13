"""The geologist's written descriptions in a WellSight log, read.

Most logs carry a text column ("Geol. Descrs.", on 8,679 of the drive's 8,954
logs: 607,379 notes) where the wellsite geologist describes each cuttings
sample in the shorthand of the trade:

  1400-1405 LS (90%): wh to bf, micxl, tt intxl por up to 6%, no show;
  SH (10%): m to dk gy, sbfis to blky, rr pyr.

  2080 - 2090 DOL(95%): off wh - crm tan, p - fr intxl por, ptchy - even tan
  - med brn o stng (50-55%) assoc wi yel flor & a modly stmg, strong yelgn
  flort cut; ANHY(5%): fros - trnsl tan, micxl, dns.

The same column, and the engineering columns beside it, also hold formation
tops ("Upper Bakken Shale: 1538.8 m TVD, -922.1 m MSL"), events ("ICP:
1519m MD", "TD reached @ 2360.0m MD"), mud reports and the well's header.

read() sorts each note into one of those, and a sample description into
what it says: the depth range; each rock with its share; colour, grain size,
sorting and rounding, carbonate texture, accessories (in the same terms as
the symbols, wellsight_symbols.py); porosity (types, a quality grade, the
per cent quoted); and the show (stain, fluorescence, cut, odour, free oil,
graded 1 trace .. 4 strong like the show symbols, or an explicit "no show").
analyse() adds them up over the log and sets them beside the symbols.

Standard library only.
"""
import re

import log_vocab as V
import wellsight_symbols as W

# ---------------------------------------------------------------- vocabulary

# rock words a description segment starts with -> wellsight_symbols rock term
# (log_vocab.txt [rock word])
_ROCKS = {e.key: "|".join(e.spellings) for e in V.entries("rock word")}
_ROCK_OF = {}
for _t, _ws in _ROCKS.items():
    for _w in _ws.split("|"):
        _ROCK_OF[_w] = _t
_ROCK_ALT = "|".join(sorted(_ROCK_OF, key=len, reverse=True))
# a rock heading a segment: at the start, or after ; | : . , and up to two
# modifier words ("PEL OOL LS", "ABOVE P1 POROSITY DOLOSTONE"), then a share
# "(90%)", "90%", "(100)" and/or a colon
# ... or a share first: "100% SLTST:"
_HEAD = re.compile(
    r"(?:^|(?<=[;|:.]))\s*(?:(\d{1,3})\s*%\s*)?(?:\(?\b[A-Za-z0-9]{1,9}\b\)?\s+){0,3}?\b(" + _ROCK_ALT + r")\b"
    r"\s*(?:\(\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*\)|(\d{1,3}(?:\.\d+)?)\s*%)?\s*(?=[:;,.(\s]|$)", re.I)

_RANGE = re.compile(
    r"^\W{0,3}(\d{2,5}(?:\.\d+)?)\s*(?:m(?:\s*MD)?\b)?\s*(?:-|–|—|to)\s*(\d{2,5}(?:\.\d+)?)"
    r"\s*(?:m(?:\s*MD)?\b)?\s*[:.]?\s*", re.I)
_ONE = re.compile(r"^\W{0,3}(\d{3,5}(?:\.\d+)?)\s*(?:m(?:\s*MD)?\b)?\s*[:\-–]\s*", re.I)

# a formation top: a name, then depths with MD / TVD / SS
_DEPTHS = re.compile(r"(-?\+?\s*\d{2,5}(?:\.\d+)?)\s*m?\s*(MD|TVD|SSL|SS|MSL|Subsea|KB)\b", re.I)
_EVENT = re.compile(r"\b(ICP|I\.C\.P|INT(?:ERMEDIATE)?\s+CASING|TD\b|T\.D\.|TOTAL\s+DEPTH|CASING|CSG|KOP|KICK[- ]?OFF|"
                    r"LANDED|LANDING|SIDETRACK|TRIP(?:PED)?|BIT\s*(?:NO|#|\d)|START(?:ED)?\s+SAMPLES|SAMPLES|"
                    r"GAMMA\s+TOOL|MUD\s+UP|SURFACE\s+CASING|DRILL(?:ED|ING)?\s+OUT|RIG\s+RELEASE|SPUD|"
                    r"WIPER|REAM|LOST\s+CIRC|CONNECTION\s+GAS|TRIP\s+GAS|FLOW\s*CHECK)\b", re.I)
_MUD = re.compile(r"\b(DEN|DENS|VIS|WL|PH|MW|MUD\s+WT|FL|GELS|CHLORIDES)\b\s*[:=]?\s*\d", re.I)
_HEADER = re.compile(r"\b(UWI|LICEN[CS]E|ELEV(?:ATION)?S?|K\.?B\.?\s*(?:ELEV\w*\s*)?[:=]|G\.?L\.?\s*[:=]|GROUND|GRND|"
                     r"SURFACE\s+LOCATION|VERTICAL\s+SECTION|COORDINATES|LSD|SEC\.|TWP|RGE|"
                     r"\d{1,2}[A-D]\d{1,2}-\d{1,2}(?:-\d{1,3}){0,3})\b", re.I)

# porosity in words -> wellsight_symbols porosity term
_POR_TYPES = [
    ("intergranular", r"int(?:er|r)?\s*-?\s*gr(?:an|n|ain)?(?:ular)?|\big\b|intrgran"),
    ("intercrystalline", r"int(?:er|r)?\s*-?\s*x(?:l|ln|tl|tln|yln)\b|intercrystal\w*|\bix\b|int\s*xl|\binx(?:t)?ln\b"),
    ("vuggy", r"\b(?:mic(?:ro)?\s*-?\s*)?vug(?:gy|s)?\b"),
    ("pinpoint", r"\bpin\s*-?\s*p(?:oin)?t\b|\bpp\b"),
    ("moldic", r"\bmou?ld(?:ic)?\b"),
    ("fracture", r"\bfrac(?:t|ture|tured|s)?\b"),
    ("interfragmental", r"\bint(?:er)?\s*-?\s*frag\w*"),
    ("interparticle", r"\bint(?:er)?\s*-?\s*(?:pel|part)\w*"),
    ("fenestral", r"\bfenes\w*"),
    ("earthy", r"\be?a?rthy\b|\bchalky\b|\bchky\b|\bchlky\b"),
]
_POR_TYPES = [(t, re.compile(p, re.I)) for t, p in _POR_TYPES]
# porosity grades: 0 none, 0.5 tight, 1 very poor, 2 poor, 3 fair, 4 good, 5 very good
_GRADE_WORDS = [
    (5, r"\bv\s*g(?:d|ood)?\b|\bvery\s+good\b|\bexc(?:el+ent)?\b"),
    (4, r"\bg(?:d|ood)?\b"),
    (3, r"\bfr\b|\bfair\b|\bf\b(?=\s*(?:-|to)?\s*(?:g|gd|good)\b)"),
    (1, r"\bv\s*p(?:r|oor)?\b|\bvery\s+poor\b"),
    (2, r"\bp(?:r|oor)?\b"),
    (0.5, r"\btt\b|\btight\b|\bti\b"),
]
_GRADE_WORDS = [(g, re.compile(p, re.I)) for g, p in _GRADE_WORDS]
GRADE_NAMES = {0: "No visible porosity", 0.5: "Tight", 1: "Very poor", 2: "Poor", 3: "Fair", 4: "Good",
               5: "Very good"}

_POR = re.compile(r"\bpor(?:o|osity|e|s)?\b|\bporos\w*|\bphi\b", re.I)
_STAIN = re.compile(r"\bo(?:il)?\.?\s*st(?:n|ng|ain|ained|aining)\b|\bstn(?:g|d)?\b|\bstain(?:ed|ing)?\b|\bo\s*stng\b", re.I)
_FLOR = re.compile(r"\bfl(?:uo|ou|o)?r(?:o|escence|esence|escent)?\b|\bflr\b|\bfluor\w*", re.I)
_FLORT_CUT = re.compile(r"\bflo?u?rt?\w*\s+cut\b", re.I)
_CUT = re.compile(r"\bcut\b", re.I)
_ODOUR = re.compile(r"\bod(?:or|our)?\b|\bodr\b|\bhydc\s+od\w*|\bhc\s+od\w*|\bpetro(?:liferous)?\b", re.I)
_FREE = re.compile(r"\b(?:free|live)\s+o(?:il)?\b|\bo(?:il)?\s+(?:flush|in\s+(?:wash|smpl|sample|mud)|on\s+(?:pits|shakers))|"
                   r"\bbleed(?:ing)?\s+o", re.I)
_NO_SHOW = re.compile(r"\bno?\s+(?:vis(?:ible)?\s+)?shows?\b|\bns\b|\bn/s\b|\bnsfoc\b|\bno\s+(?:o\s+)?(?:stn|stain|flor|fluor\w*|cut)\b|"
                      r"\bno\s+hydc\b|\bno\s+show\w*", re.I)
_DEAD = re.compile(r"\bdead\s+o(?:il)?\b|\bdd\s+o\b|\bres(?:id)?\s+o(?:il)?\b|\bpyro?\s*bit\w*|\bbitumen\b|\bbit\b", re.I)

_SHOW_DIST = [("even", r"\bev(?:en)?\b|\bsolid\b|\bsat(?:urated)?\b|\bpervasive\b"),
              ("patchy", r"\bp(?:a)?tchy\b|\bpchy\b|\bptchy\b"),
              ("spotty", r"\bsp(?:ot+(?:ed|y)?|ty|tty)?\b|\bscat(?:tered)?\b|\bpinpoint\b"),
              ("trace", r"\btr(?:ace)?\b|\brr\b|\bfaint\b|\bfnt\b")]
_SHOW_DIST = [(t, re.compile(p, re.I)) for t, p in _SHOW_DIST]
_BRIGHT = re.compile(r"\bbri(?:ght|t)?\b|\bbrt\b|\bstr(?:o?ng|g)\b|\bint(?:ense)?\b", re.I)
_DULL = re.compile(r"\bdull\b|\bfnt\b|\bfaint\b|\bpale\b|\bwk\b|\bweak\b|\bmin(?:eral)?\b", re.I)
_CUT_STRONG = re.compile(r"\binst\w*|\bimmed\w*|\bfast\b|\brpd\b|\brapid\w*|\bstr(?:o?ng|g)\b|\bstr(?:ea)?mi?n?g\b|\bstmg\b|"
                         r"\bbl(?:oo)?mi?n?g\b|\bflash\b", re.I)
_CUT_WEAK = re.compile(r"\bslo?w\b|\bwk\b|\bweak\b|\bcrush\b|\bring\b|\bv\s*slow\b|\bdif(?:f|fuse)?\b", re.I)
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:-\s*(\d{1,3}(?:\.\d+)?)\s*)?%")

# described things that are also symbols: (group, term) by pattern
_ACCESSORIES = [
    ("mineral", "pyrite", r"\bpyr\w*"), ("mineral", "glauconite", r"\bglau\w*"),
    ("mineral", "carbonaceous", r"\bcarb(?:onaceous|\s+mat\w*|\s+frag\w*|\s+flecks)?\b"),
    ("mineral", "mica", r"\bm?mica\w*|\bmicmica\b"), ("mineral", "calcareous", r"\bcalc(?:s|areous|ite)?\b"),
    ("mineral", "dolomitic", r"\bdol(?:c|ic|omitic)\b"), ("mineral", "argillaceous", r"\barg(?:illaceous|c)?\b"),
    ("mineral", "silty", r"\bslty\b|\bsilty\b"), ("mineral", "sandy", r"\bsdy\b|\bsandy\b"),
    ("mineral", "anhydritic", r"\banhy(?:c|dritic)\b|\banhydritic\b"), ("mineral", "siliceous", r"\bsil(?:c|ic|iceous)\b"),
    ("mineral", "kaolinite", r"\bkao\w*"), ("mineral", "sideritic", r"\bsid(?:eritic|erite)?\b"),
    ("mineral", "chert", r"\bcht\b|\bchert\b|\bchty\b"), ("mineral", "bentonitic", r"\bbent\w*"),
    ("mineral", "feldspar", r"\bfeld\w*|\bfsp\b"), ("mineral", "heavy_minerals", r"\bhvy\s+min\w*|\bheavy\s+min\w*"),
    ("fossil", "fossils", r"\bfos+(?:il)?s?\b|\bfos+\s+(?:frags?|deb\w*)"), ("fossil", "oolites", r"\bool\w*"),
    ("fossil", "pellets", r"\bpel(?:s|let\w*|oid\w*)?\b"), ("fossil", "crinoids", r"\bcrin\w*"),
    ("fossil", "brachiopods", r"\bbrach\w*"), ("fossil", "bioclasts", r"\bbio\s*-?\s*(?:cl\w*|frag\w*)"),
    ("fossil", "algae", r"\balg(?:al|ae)\b"), ("fossil", "corals", r"\bcoral\w*"),
    ("fossil", "fish_remains", r"\bfish\b"), ("fossil", "plant_remains", r"\bplant\b"),
    ("texture", "mudstone", r"\bmu?dst(?:n|one)?\b"), ("texture", "wackestone", r"\bw(?:a)?c?k(?:e)?st(?:n|one)?\b"),
    ("texture", "packstone", r"\bpa?c?kst(?:n|one)?\b|\bps\b"), ("texture", "grainstone", r"\bgr(?:ai)?n?st(?:n|one)?\b|\bgs\b"),
    ("texture", "boundstone", r"\bbo?u?ndst\w*"),
    ("texture", "cryptocrystalline", r"\bcr(?:y|i)?p?t?o?\s*-?\s*x(?:l|ln|tln)\w*|\bcyxln\b|\bcrpxl\w*|\bcrypto\w*"),
    ("texture", "microcrystalline", r"\bmi?c(?:ro)?\s*-?\s*x(?:l|ln|yln|tln)\w*|\bmicrocrys\w*"),
    ("texture", "finely_crystalline", r"\bf\s*-?\s*x(?:l|ln)\b|\bfine(?:ly)?\s+crys\w*"),
    ("texture", "sucrosic", r"\b(?:mic)?suc(?:rosic)?\b"), ("texture", "chalky", r"\bch(?:a)?l?ky\b"),
    ("texture", "micritic", r"\bmic(?:t|rite|ritic)\b"),
    ("sorting", "well", r"\b(?:v\s*)?w(?:ell|l)?\s*-?\s*s(?:o)?r(?:t|td|ted)\b"),
    ("sorting", "moderately_well", r"\bmod(?:ly|erately)?\s*w(?:ell)?\s*s(?:o)?r(?:t|td|ted)\b"),
    ("sorting", "moderate", r"\bmod(?:ly|erately)?\s*s(?:o)?r(?:t|td|ted)\b"),
    ("sorting", "poor", r"\bp(?:oor(?:ly)?|r)?\s*s(?:o)?r(?:t|td|ted)\b"),
    ("rounding", "subangular", r"\bs(?:u)?b\s*-?\s*ang(?:ular)?\b|\bsa\b"),
    ("rounding", "subrounded", r"\bs(?:u)?b\s*-?\s*r(?:nd|d|ou?nded)\b|\bsr\b|\bsbrd\b"),
    ("rounding", "angular", r"(?<!sb\s)(?<!sub\s)(?<!sb)(?<!sub)\bang(?:ular)?\b"),
    ("rounding", "rounded", r"(?<!sb\s)(?<!sub\s)(?<!sb)(?<!sub)\b(?:w(?:ell)?\s+)?(?:rnd|rounded|rd)\b"),
]
_ACCESSORIES = [(g, t, re.compile(p, re.I)) for g, t, p in _ACCESSORIES]
# "gr" here is grain: gr, grs, grn, grnd, grained, grains -- not gray, grey, green
_GR = r"(?:gr(?:s|n|nd|nds|ns|ained|ains|ain)?|g)\b"
_GRAIN = [("very fine", r"\b(?:[lu]\s*)?v(?:ery)?\s*f(?:ine)?\s*" + _GR + r"|\bvfg?\b|\b[lu]\s*vf\b"),
          ("fine", r"(?<!v\s)(?<!v)\b(?:[lu]\s*)?f(?:ine)?\s*" + _GR + r"|\bfg\b"),
          ("medium", r"\bm(?:ed|edium)?\s*" + _GR + r"|\bmg\b"),
          ("coarse", r"\bc(?:rs|oarse)?\s*" + _GR + r"|\bcg\b")]
_GRAIN = [(t, re.compile(p, re.I)) for t, p in _GRAIN]
_COLOUR = re.compile(r"\b(?:(?:v\s*)?(?:lt|light|m|med|medium|dk|dark|pale|off|bri|brt)\s*-?\s*)?"
                     r"(wh|white|crm|cream|bf|buff|tan|gy|gry|grey|gray|brn|brown|blk|black|grn|gn|green|red|orng|"
                     r"orange|pnk|pink|yel|yellow|olive|clr|clear|trnsl|frost(?:ed)?|fros|mottled|mot)\b", re.I)
_AMOUNT = re.compile(r"\b(tr|trace|rr|rare|occ|occasional|mnr|minor|com|comly|common|abnt|abd|abundant|pred|predly|"
                     r"predominantly|ip|ipt)\b", re.I)

# ---------------------------------------------------------------- one note


def _num(s):
    try:
        return float(str(s).replace(" ", "").replace("+", ""))
    except ValueError:
        return None


def classify(text, column="", depth=None, top=None, bottom=None):
    """What kind of note this is: sample / top / event / mud / header / note."""
    t = " ".join(str(text or "").split())
    if not t:
        return "note"
    rng = _RANGE.match(t)
    descr_col = bool(re.search(r"descr|geolog", column or "", re.I))
    if rng and _sane_range(rng, top, bottom) and (_HEAD.search(t[rng.end():rng.end() + 60]) or
                                                  _cue_count(t) >= 2):
        return "sample"
    if _HEADER.search(t) and not (rng and _sane_range(rng, top, bottom)):
        return "header"
    if _MUD.search(t) and len(_MUD.findall(t)) >= 2:
        return "mud"
    if any(k.upper() in ("MD", "TVD", "SS", "SSL", "MSL", "SUBSEA") for _v, k in _DEPTHS.findall(t)) \
            and not _EVENT.search(t[:40]):
        name = _top_name(t)
        if name:
            return "top"
    if _EVENT.search(t):
        return "event"
    if descr_col and (_HEAD.search(t[:40]) and _cue_count(t) >= 2):
        return "sample"
    return "note"


def _cue_count(t):
    return sum(1 for rx in (_POR, _STAIN, _FLOR, _CUT, _NO_SHOW, _COLOUR) if rx.search(t))


def _sane_range(m, top, bottom):
    a, b = float(m.group(1)), float(m.group(2))
    if b < a:
        return False
    if b - a > 300:
        return False
    if top is not None and bottom is not None and not (top - 200 <= a <= bottom + 200):
        return False
    return True


def _top_name(t):
    """the formation's name in "Upper Bakken Shale: 1538.8 m TVD ..." or
    "Second White Specks | @ 577.70 m TVD" """
    m = re.match(r"\s*([A-Za-z][A-Za-z0-9 '\"/&().,|-]{1,70}?)\s*(?:@|:|-?\s*\d)", t)
    if not m:
        return None
    name = " ".join(m.group(1).replace("|", " ").split()).strip(" :@-,.")
    if not re.search(r"[A-Za-z]{3}", name) or _HEADER.search(name):
        return None
    # a description or a note that happens to quote a depth is not a top
    if _STAIN.search(name) or _FLOR.search(name) or _CUT.search(name) or _POR.search(name) or \
            re.search(r"\b(extrapolat\w*|project\w*|bit|survey|sample|sampl|samples|gas|mud|drill\w*|"
                      r"circulat\w*|minor|fair|good|poor|trace|asks?|drop\w*|target\w*|new|steer\w*|meter|metre|"
                      r"we|us|our|will|pull\w*|up|down|keep|kept|stay\w*|land\w*)\b", name, re.I) or \
            len(name.split()) > 6 or "(" in name and ")" not in name:
        return None
    return name


def read_top(text):
    t = " ".join(str(text or "").split())
    out = {"name": _top_name(t) or t[:60]}
    for v, kind in _DEPTHS.findall(t):
        k = kind.upper()
        k = "SS" if k in ("SS", "SSL", "MSL", "SUBSEA") else k
        if k not in out:
            out[k.lower()] = _num(v)
    return out


def read_sample(text, depth=None):
    """One cuttings-sample description -> its depth range, rocks and what is
    said of them."""
    raw = " ".join(str(text or "").split())
    out = {"top": None, "base": None, "text": raw}
    m = _RANGE.match(raw)
    body = raw
    if m:
        out["top"], out["base"] = float(m.group(1)), float(m.group(2))
        body = raw[m.end():]
    else:
        m1 = _ONE.match(raw)
        if m1:
            out["top"] = float(m1.group(1))
            body = raw[m1.end():]
        elif depth is not None:
            out["top"] = depth
    # split into rock segments. A rock heads a segment at the start, after a
    # ";" or "|", or anywhere else only with its share or a colon after it:
    # "SANDSTONE 35%: Salt and peppered" is sandstone, not salt.
    heads = []
    for h in _HEAD.finditer(body):
        before = body[:h.start()].rstrip()
        after = body[h.end():h.end() + 3].lstrip()
        if not before or before[-1] in ";|" or h.group(1) or h.group(3) or h.group(4) or after.startswith(":"):
            heads.append(h)
    segs = []
    if not heads:
        segs.append((None, None, body))
    else:
        if heads[0].start() > 0 and body[:heads[0].start()].strip(" ;|.,"):
            segs.append((None, None, body[:heads[0].start()]))
        for i, h in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            pct = h.group(3) or h.group(4) or h.group(1)
            segs.append((_ROCK_OF[h.group(2).upper()], _num(pct) if pct else None, body[h.end():end]))
    # a rock named twice (a summary line, then its own paragraph) is one rock
    rocks = {}
    order = []
    general = []
    for rock, pct, seg in segs:
        if rock is None:
            general.append(seg)
            continue
        if rock not in rocks:
            rocks[rock] = {"rock": rock, "pct": pct, "text": seg}
            order.append(rock)
        else:
            if rocks[rock]["pct"] is None:
                rocks[rock]["pct"] = pct
            rocks[rock]["text"] += " , " + seg
    comps = [rocks[r] for r in order]
    known = sum(c["pct"] for c in comps if c["pct"] is not None)
    unk = [c for c in comps if c["pct"] is None]
    for c in unk:
        c["pct"] = round(max(0.0, 100.0 - known) / len(unk), 1) if known < 100 else 0.0
    # a rock left with no share (the others already add up to 100) is a
    # mention, not part of the sample
    comps = [c for c in comps if c["pct"] > 0] or comps
    for c in comps:
        c.update(_attributes(c["text"]))
        c["name"] = W._NAMES.get(("rock", c["rock"]), (c["rock"],))[0]
        c["colour"] = _colours(c["text"])
        del c["text"]
    out["rocks"] = comps
    # porosity and shows may be said of the sample as a whole
    whole = _attributes(body)
    out["porosity"] = _best_porosity([c["porosity"] for c in comps] + [whole["porosity"]])
    out["show"] = _show(body)
    out["accessories"] = sorted({(g, t) for c in comps for g, t in c["accessories"]} |
                                {(g, t) for g, t in whole["accessories"]})
    out["reservoir"] = _reservoir(body)
    return out


def _clauses(t):
    return [c.strip() for c in re.split(r"[,;]|\s\|\s", t) if c.strip()]


_POR_CUE = re.compile(r"%|\btt\b|\btight\b|\bpor", re.I)


def _por_clauses(cls):
    """each clause that names porosity, with the clauses just before it that
    only grade it or name its kind ("9-12% intgran, pp, & micvug por")"""
    out, used = [], set()
    for i, cl in enumerate(cls):
        if not _POR.search(cl):
            continue
        j = i
        while j - 1 >= 0 and j - 1 not in used and len(cls[j - 1]) <= 40 and not _POR.search(cls[j - 1]) and \
                not (_STAIN.search(cls[j - 1]) or _FLOR.search(cls[j - 1]) or _CUT.search(cls[j - 1])) and \
                (any(rx.search(cls[j - 1]) for _t, rx in _POR_TYPES) or _PCT.search(cls[j - 1]) and
                 len(cls[j - 1].split()) <= 4):
            j -= 1
        used.update(range(j, i + 1))
        out.append(", ".join(cls[j:i + 1]))
    return out, used


def _attributes(t):
    acc = set()
    por = {"types": [], "grade": None, "pct": None}
    grains = []
    cls = _clauses(t)
    pcl, used = _por_clauses(cls)
    for cl in pcl:
        p = _porosity(cl)
        por["types"] = sorted(set(por["types"]) | set(p["types"]))
        if p["grade"] is not None and (por["grade"] is None or p["grade"] > por["grade"]):
            por["grade"] = p["grade"]
        if p["pct"] is not None and (por["pct"] is None or p["pct"] > por["pct"]):
            por["pct"] = p["pct"]
    for i, cl in enumerate(cls):
        if i in used:
            continue
        if _POR.search(cl):
            p = _porosity(cl)
            por["types"] = sorted(set(por["types"]) | set(p["types"]))
            if p["grade"] is not None and (por["grade"] is None or p["grade"] > por["grade"]):
                por["grade"] = p["grade"]
            if p["pct"] is not None and (por["pct"] is None or p["pct"] > por["pct"]):
                por["pct"] = p["pct"]
            continue
        if _STAIN.search(cl) or _FLOR.search(cl) or _CUT.search(cl):
            continue                 # a show clause: its colours and words are the show's
        for g, term, rx in _ACCESSORIES:
            if rx.search(cl):
                acc.add((g, term))
        for gname, rx in _GRAIN:
            if rx.search(cl) and gname not in grains:
                grains.append(gname)
    # one sorting and one rounding: the best stated
    for g in ("sorting", "rounding"):
        terms = [x for x in acc if x[0] == g]
        if len(terms) > 1:
            keep = max(terms, key=lambda x: W._NAMES[x][1] or 0)
            acc -= set(terms)
            acc.add(keep)
    return {"accessories": sorted(acc), "porosity": por, "grain": grains}


def _porosity(cl):
    out = {"types": [], "grade": None, "pct": None}
    if re.search(r"\bno\s+(?:vis(?:ible)?\s+)?por", cl, re.I):
        out["grade"] = 0
        return out
    head = re.split(_POR, cl)[0] if _POR.search(cl) else cl
    for t, rx in _POR_TYPES:
        if rx.search(cl):
            out["types"].append(t)
    grades = [g for g, rx in _GRADE_WORDS if rx.search(head)]
    if grades:
        out["grade"] = max(grades)
    pcts = [_num(b or a) for a, b in _PCT.findall(cl)]
    pcts = [p for p in pcts if p is not None and p <= 40]
    if pcts:
        out["pct"] = max(pcts)
        if out["grade"] is None:
            p = out["pct"]
            out["grade"] = 1 if p < 3 else 2 if p < 6 else 3 if p < 10 else 4 if p < 15 else 5
    return out


def _best_porosity(ps):
    out = {"types": [], "grade": None, "pct": None}
    for p in ps:
        out["types"] = sorted(set(out["types"]) | set(p["types"]))
        if p["grade"] is not None and (out["grade"] is None or p["grade"] > out["grade"]):
            out["grade"] = p["grade"]
        if p["pct"] is not None and (out["pct"] is None or p["pct"] > out["pct"]):
            out["pct"] = p["pct"]
    out["grade_name"] = GRADE_NAMES.get(out["grade"]) if out["grade"] is not None else None
    return out


def _show(t):
    """stain, fluorescence, cut, odour, free oil -> a grade 1 trace .. 4
    strong (like the show symbols), or 0 for an explicit no show"""
    s = {"stain": None, "fluorescence": None, "cut": None, "odour": False, "free_oil": False, "dead": False,
         "none": False, "level": None}
    levels = []
    weak = False
    for cl in _clauses(t):
        pct = [_num(b or a) for a, b in _PCT.findall(cl)]
        pct = max([p for p in pct if p is not None and p <= 100], default=None)
        dist = next((d for d, rx in _SHOW_DIST if rx.search(cl)), None)
        if _NO_SHOW.search(cl):
            # "no vis shows or cut": what the clause names, it denies
            s["none"] = True
            continue
        if _DEAD.search(cl) and (_STAIN.search(cl) or re.search(r"\bdead|\bres(?:id)?\s+o|bitumen|pyro?bit", cl, re.I)):
            s["dead"] = True
            levels.append(1)
        if _STAIN.search(cl) and not re.search(r"\bno\s+(?:o\s+)?st", cl, re.I):
            lv = 3 if dist == "even" else 1 if dist == "trace" else 2
            if pct is not None and pct >= 50:
                lv += 1
            s["stain"] = {"distribution": dist, "pct": pct}
            levels.append(lv)
        cut_here = bool(_CUT.search(cl)) and not re.search(r"\bno\s+(?:\w+\s+)?cut", cl, re.I)
        flor_here = bool(_FLOR.search(cl)) and not re.search(r"\bno\s+fl", cl, re.I) and not \
            (_FLORT_CUT.search(cl) and len(_FLOR.findall(cl)) == 1)
        if flor_here:
            lv = 3 if _BRIGHT.search(cl) else 1 if _DULL.search(cl) else 2
            weak = weak or (lv == 1)
            if pct is not None and pct >= 50:
                lv += 1
            s["fluorescence"] = {"bright": bool(_BRIGHT.search(cl)), "pct": pct}
            levels.append(lv)
        if cut_here:
            lv = 3 if _CUT_STRONG.search(cl) else 2 if _CUT_WEAK.search(cl) else 2
            weak = weak or bool(_CUT_WEAK.search(cl) and not _CUT_STRONG.search(cl))
            s["cut"] = {"strong": bool(_CUT_STRONG.search(cl))}
            levels.append(lv)
        if _ODOUR.search(cl) and not re.search(r"\bno\s+(?:\w+\s+)?od", cl, re.I):
            s["odour"] = True
            levels.append(1)
        if _FREE.search(cl):
            s["free_oil"] = True
            levels.append(4)
    if levels:
        lv = max(levels)
        # stain, fluorescence and cut together are a show of note, unless the
        # words say they were weak
        if sum(1 for k in ("stain", "fluorescence", "cut") if s[k]) >= 3 and not weak:
            lv = max(lv, 3)
        s["level"] = min(4, lv)
    elif s["none"]:
        s["level"] = 0
    s["name"] = {0: "No show", 1: "Trace", 2: "Weak", 3: "Moderate", 4: "Strong"}.get(s["level"])
    return s


def _reservoir(t):
    m = re.search(r"\b(v\s*g(?:d|ood)?|very\s+good|g(?:d|ood)?|fr|fair|p(?:r|oor)?|v\s*p(?:oor)?|exc\w*)"
                  r"(?:\s*(?:-|to)\s*(?:v\s*g\w*|g\w*|fr|fair))?\s*res(?:ervoir)?\b", t, re.I)
    if not m:
        return None
    w = m.group(0)
    for g, rx in _GRADE_WORDS:
        if rx.search(w.split("res")[0]) and g >= 1:
            return GRADE_NAMES.get(max(g for g, r in _GRADE_WORDS if r.search(w.split("res")[0])))
    return None


def _colours(t):
    first = " , ".join(c for c in _clauses(t)[:3] if not (_STAIN.search(c) or _FLOR.search(c) or _CUT.search(c)))
    out = []
    for m in _COLOUR.finditer(first):
        w = " ".join(m.group(0).lower().split())
        if w not in out:
            out.append(w)
    return out[:4]


# ---------------------------------------------------------------- one log

def read(annotations, top=None, bottom=None):
    """the log's notes -> {"samples": [...], "tops": [...], "events": [...],
    "mud": n, "other": n}. A sample with no base of its own runs to the next
    sample's top."""
    samples, tops, events = [], [], []
    mud = other = 0
    for a in annotations or []:
        text = a.get("text") or ""
        depth = a.get("depth", a.get("depth_m"))
        kind = classify(text, a.get("column", ""), depth, top, bottom)
        if kind == "sample":
            s = read_sample(text, depth)
            s["column"] = a.get("column")
            samples.append(s)
        elif kind == "top":
            t = read_top(text)
            t["depth"] = depth
            t["text"] = " ".join(text.split())[:200]
            t["column"] = a.get("column")
            tops.append(t)
        elif kind == "event":
            m = _EVENT.search(text)
            events.append({"depth": depth, "what": m.group(1).upper() if m else "",
                           "text": " ".join(text.split())[:200], "column": a.get("column")})
        elif kind == "mud":
            mud += 1
        else:
            other += 1
    samples = [s for s in samples if s["top"] is not None]
    samples.sort(key=lambda s: s["top"])
    for i, s in enumerate(samples):
        if s["base"] is None:
            nxt = samples[i + 1]["top"] if i + 1 < len(samples) else None
            s["base"] = nxt if nxt is not None and nxt > s["top"] and nxt - s["top"] <= 50 else s["top"] + 5.0
    tops.sort(key=lambda t: t.get("md") or t.get("depth") or 0)
    events.sort(key=lambda e: e["depth"] or 0)
    return {"samples": samples, "tops": tops, "events": events, "mud": mud, "other": other}


def analyse(described, rock_intervals=None, symbols=None, show_zones=None):
    """What the descriptions add up to, and how they sit beside the symbols."""
    S = described["samples"]
    out = {"samples": len(S), "tops": len(described["tops"]), "events": len(described["events"])}
    out["described_m"] = round(sum(s["base"] - s["top"] for s in S), 2)
    # rocks, by thickness and share
    mix = {}
    for s in S:
        th = s["base"] - s["top"]
        for c in s["rocks"]:
            mix[c["rock"]] = mix.get(c["rock"], 0) + th * (c["pct"] or 0) / 100.0
    tot = sum(mix.values())
    out["rocks"] = [{"rock": r, "name": W._NAMES.get(("rock", r), (r,))[0], "color": W.rock_color(r),
                     "m": round(m, 2), "pct": round(100 * m / tot, 1) if tot else None}
                    for r, m in sorted(mix.items(), key=lambda kv: -kv[1])]
    # porosity, by grade
    grades = {}
    types = {}
    for s in S:
        g = s["porosity"]["grade"]
        if g is not None:
            grades[g] = grades.get(g, 0) + s["base"] - s["top"]
        for t in s["porosity"]["types"]:
            types[t] = types.get(t, 0) + 1
    out["porosity"] = [{"grade": g, "name": GRADE_NAMES[g], "m": round(m, 2)} for g, m in sorted(grades.items())]
    out["porosity_types"] = [{"term": t, "name": W._NAMES.get(("porosity", t), (t,))[0], "samples": n}
                             for t, n in sorted(types.items(), key=lambda kv: -kv[1])]
    # shows, grouped where described samples with a show run on
    zones = []
    for s in S:
        lv = s["show"]["level"]
        if lv is None or lv < 2:
            continue
        if zones and s["top"] - zones[-1]["base"] <= 1.0:
            z = zones[-1]
            z["base"] = max(z["base"], s["base"])
            z["level"] = max(z["level"], lv)
            z["samples"] += 1
        else:
            zones.append({"top": s["top"], "base": s["base"], "level": lv, "samples": 1, "said": []})
            z = zones[-1]
        bits = []
        sh = s["show"]
        if sh["stain"]:
            bits.append("stain" + (" " + sh["stain"]["distribution"] if sh["stain"]["distribution"] else ""))
        if sh["fluorescence"]:
            bits.append("bright fluorescence" if sh["fluorescence"]["bright"] else "fluorescence")
        if sh["cut"]:
            bits.append("strong cut" if sh["cut"]["strong"] else "cut")
        if sh["free_oil"]:
            bits.append("free oil")
        for b in bits:
            if b not in z["said"]:
                z["said"].append(b)
        g = s["porosity"]["grade"]
        if g is not None and g > z.get("porosity", -1):
            z["porosity"] = g
    for z in zones:
        z["m"] = round(z["base"] - z["top"], 2)
        z["strength"] = {2: "Weak", 3: "Moderate", 4: "Strong"}[z["level"]]
        z["porosity"] = GRADE_NAMES.get(z.get("porosity")) if z.get("porosity", -1) >= 0 else None
    out["show_zones"] = zones
    # beside the symbols: does the text say the same?
    if show_zones:
        agree = 0
        for sz in show_zones:
            if any(z["top"] < sz["base"] and z["base"] > sz["top"] for z in zones):
                agree += 1
            sz_text = [s for s in S if s["top"] < sz["base"] and s["base"] > sz["top"]]
            best = max((s["show"]["level"] for s in sz_text if s["show"]["level"] is not None), default=None)
            sz["described"] = {0: "No show", 1: "Trace", 2: "Weak", 3: "Moderate", 4: "Strong"}.get(best)
        out["symbol_zones_described"] = agree
    if rock_intervals:
        same = n = 0
        for s in S:
            if not s["rocks"]:
                continue
            main = max(s["rocks"], key=lambda c: c["pct"] or 0)["rock"]
            cover = {}
            for iv in rock_intervals:
                o = min(s["base"], iv["base"]) - max(s["top"], iv["top"])
                if o > 0:
                    cover[iv["rock"]] = cover.get(iv["rock"], 0) + o
            if cover:
                n += 1
                same += max(cover, key=cover.get) == main
        out["rock_column_agrees"] = {"samples": n, "same_main_rock": same,
                                     "pct": round(100 * same / n, 1) if n else None}
    return out


# ---------------------------------------------------------------- tables

def rows_samples(described):
    yield ["top_m", "base_m", "rocks", "porosity_grade", "porosity_types", "porosity_pct", "show", "stain",
           "fluorescence", "cut", "free_oil", "reservoir", "accessories", "text"]
    for s in described["samples"]:
        sh = s["show"]
        yield [s["top"], s["base"], "; ".join(f'{c["name"]} {c["pct"]:g}%' for c in s["rocks"]),
               s["porosity"]["grade_name"] or "", " ".join(s["porosity"]["types"]),
               "" if s["porosity"]["pct"] is None else s["porosity"]["pct"], sh["name"] or "",
               (sh["stain"] or {}).get("distribution") or ("yes" if sh["stain"] else ""),
               ("bright" if sh["fluorescence"]["bright"] else "yes") if sh["fluorescence"] else "",
               ("strong" if sh["cut"]["strong"] else "yes") if sh["cut"] else "",
               "yes" if sh["free_oil"] else "", s["reservoir"] or "",
               " ".join(f"{g}:{t}" for g, t in s["accessories"]), s["text"]]


def rows_tops(described):
    yield ["name", "md_m", "tvd_m", "ss_m", "note_depth_m", "text"]
    for t in described["tops"]:
        yield [t["name"], t.get("md", ""), t.get("tvd", ""), t.get("ss", ""), t.get("depth", ""), t["text"]]
