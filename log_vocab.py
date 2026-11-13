"""What the names on well logs mean: one vocabulary for every log reader.

The names live in log_vocab.txt beside this file, which says how to write
it. It is read once, at import; a mistake in it (a spelling given to two
things in one section, a line that cannot be read) stops the import with
the line number, so it is found at once rather than as a curve that
quietly goes missing.

    key(section, raw)       the key a spelling means in a section, or None
    entries(section)        the section's entries, in file order
    curve(raw)              what a curve name means, taken apart if need be
    unit(raw)               a unit spelling, its sample spacing and scale off
    convert(x, frm, to)     a value from one unit to another
    header(label, box)      a header page's label
    curve_track(title)      True if a track by this title holds curves
    depth_column(title)     "md", "tvd" or None

The WellSight readers (wellsight_symbols, wellsight_descriptions,
wellsight_layout) take their symbol, rock and column lists from here; the
PDF readers to come share them.

Standard library only.
"""
import collections
import csv
import os
import re
import sys

Entry = collections.namedtuple("Entry", "key name extra spellings line")

# the sections the file may have; the symbol groups are wellsight_symbols'
SYMBOL_GROUPS = ("rock", "mineral", "fossil", "stringer", "texture", "porosity", "sorting", "rounding",
                 "show", "interval", "quality", "event", "directional")
SECTIONS = ("category", "refile") + SYMBOL_GROUPS + (
    "rock modifier", "rock word", "column", "curve", "curve qualifier", "curve source", "unit", "convert",
    "curve track", "depth column", "header", "header box")
_RAW = {"refile", "convert"}          # spellings kept as written, not looked up


def _find_file():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "log_vocab.txt")]
    mei = getattr(sys, "_MEIPASS", None)    # PyInstaller onefile unpacks data here
    if mei:
        cands.append(os.path.join(mei, "log_vocab.txt"))
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


PATH = _find_file()


def norm(s):
    """upper case, letters and digits only: "Geol. Descrs." -> "GEOLDESCRS" """
    return re.sub(r"[^A-Z0-9]+", "", str(s or "").upper())


def norm_unit(s):
    """lower case, spaces out, the rest kept: "Ohm m" -> "ohmm", "per cent" -> "percent" """
    return re.sub(r"\s+", "", str(s or "").strip().lower())


def _normer(section):
    return norm_unit if section == "unit" else norm


class VocabError(ValueError):
    pass


def _split(text, path, n):
    try:
        return [s.strip() for s in next(csv.reader([text], skipinitialspace=True)) if s.strip()]
    except (csv.Error, StopIteration) as e:
        raise VocabError("%s:%d: cannot read the spellings (%s)" % (path, n, e))


def load(path=PATH):
    """-> {section: [Entry]}"""
    if not os.path.exists(path):
        raise VocabError("the log vocabulary is missing: %s" % path)
    out = collections.OrderedDict((s, []) for s in SECTIONS)
    section, last = None, None
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            text = line.strip()
            if not text or text.startswith("#"):
                if not text:
                    last = None
                continue
            if line[0] in " \t":                      # carries on the entry above
                if last is None:
                    raise VocabError("%s:%d: an indented line with no entry above it" % (path, n))
                last.spellings.extend(_split(text, path, n))
                continue
            m = re.fullmatch(r"\[\s*([a-z ]+?)\s*\]", text)
            if m:
                section = m.group(1)
                if section not in out:
                    raise VocabError("%s:%d: no such section [%s]" % (path, n, section))
                last = None
                continue
            if section is None:
                raise VocabError("%s:%d: an entry before any [section]" % (path, n))
            if "=" not in text:
                raise VocabError("%s:%d: no '=' in the line" % (path, n))
            left, right = text.split("=", 1)
            parts = [p.strip() for p in left.split("|")]
            if not parts[0] or len(parts) > 3:
                raise VocabError("%s:%d: write key | name | extra = spellings" % (path, n))
            key = parts[0]
            name = parts[1] if len(parts) > 1 and parts[1] else None
            extra = parts[2] if len(parts) > 2 and parts[2] else None
            last = Entry(key, name, extra, _split(right, path, n), n)
            out[section].append(last)
    return out


def _index(sections, path=PATH):
    """{section: {normalised spelling: key}}; a spelling given to two keys of
    one section is an error. A header spelling "BOX:Label" is filed under the
    box's key: "operator:COMPANY"."""
    idx = {}
    for section, entries in sections.items():
        if section in _RAW:
            continue
        nf = _normer(section)
        d = idx[section] = {}
        for e in entries:
            for sp in [e.key] + e.spellings if section in ("curve", "unit") else e.spellings:
                if section == "header" and ":" in sp:
                    box, label = sp.split(":", 1)
                    k = "box:%s:%s" % (norm(box), norm(label))
                else:
                    k = nf(sp)
                if not k:
                    continue
                if d.get(k, e.key) != e.key:
                    raise VocabError("%s:%d: [%s] %r already means %r" % (path, e.line, section, sp, d[k]))
                d[k] = e.key
    # box names in header spellings -> the box's key
    boxes = idx.get("header box", {})
    hd = idx.get("header", {})
    for k in [k for k in hd if k.startswith("box:")]:
        _, box, label = k.split(":", 2)
        hd["%s:%s" % (boxes.get(box, box.lower()), label)] = hd.pop(k)
    return idx


SECTIONS_DATA = load()
INDEX = _index(SECTIONS_DATA)
_BY_KEY = {s: {e.key: e for e in es} for s, es in SECTIONS_DATA.items()}


def entries(section):
    return list(SECTIONS_DATA[section])


def key(section, raw):
    return INDEX[section].get(_normer(section)(raw))


def entry(section, k):
    return _BY_KEY[section].get(k)


def name(section, k):
    e = _BY_KEY[section].get(k)
    return (e.name or e.key) if e else None


def rank(extra):
    """a symbol term's rank as written: "2" -> 2, "2.5" -> 2.5, None -> None"""
    if extra is None:
        return None
    return int(extra) if re.fullmatch(r"-?\d+", extra) else float(extra)


# ---------------------------------------------------------------- units

_SPACING = re.compile(r"\s*/\s*([0-9O]*\.?[0-9O]+)\s*(m|ft|meter|metre)\.?\s*$", re.I)
_SCALE = re.compile(r"\s*/\s*(10+)\s*$")


def unit(raw):
    """{raw, key, spacing, scale}: "AAPI/0.1m" -> API, spacing "0.1 m";
    "units/10000" -> units, scale "10000". key None if not known."""
    s = str(raw or "").strip().strip("()[]").strip()
    out = {"raw": raw, "key": key("unit", s) if s else None, "spacing": None, "scale": None}
    if out["key"] or not s:
        return out
    m = _SPACING.search(s)
    if m:
        out["spacing"] = "%s %s" % (m.group(1).replace("O", "0"), m.group(2).lower())
        s = s[:m.start()]
    m = _SCALE.search(s)
    if m:
        out["scale"] = m.group(1)
        s = s[:m.start()]
    out["key"] = key("unit", s) if s.strip() else None
    return out


def _formula(text):
    t = text.replace(" ", "")
    m = re.fullmatch(r"([0-9.]+)/x", t)
    if m:
        k = float(m.group(1))
        return (lambda x: k / x), (lambda y: k / y)
    m = re.fullmatch(r"x\*([0-9.]+)", t)
    if m:
        k = float(m.group(1))
        return (lambda x: x * k), (lambda y: y / k)
    m = re.fullmatch(r"x/([0-9.]+)", t)
    if m:
        k = float(m.group(1))
        return (lambda x: x / k), (lambda y: y * k)
    if t == "x":
        return (lambda x: x), (lambda y: y)
    raise VocabError("%s: [convert] cannot read the formula %r" % (PATH, text))


_CONVERT = {}
for _e in SECTIONS_DATA["convert"]:
    if len(_e.spellings) != 2:
        raise VocabError("%s:%d: [convert] write from = to, formula" % (PATH, _e.line))
    _fwd, _back = _formula(_e.spellings[1])
    _f, _t = key("unit", _e.key), key("unit", _e.spellings[0])
    if not _f or not _t:
        raise VocabError("%s:%d: [convert] unit not in [unit]" % (PATH, _e.line))
    _CONVERT[(_f, _t)] = _fwd
    _CONVERT.setdefault((_t, _f), _back)


def convert(value, frm, to):
    """value in unit frm -> unit to; None if no conversion is known. Units may
    be spelt any way [unit] knows."""
    a, b = unit(frm)["key"], unit(to)["key"]
    if a is None or b is None or value is None:
        return None
    if a == b:
        return value
    f = _CONVERT.get((a, b))
    if f is None:
        return None
    try:
        return f(value)
    except ZeroDivisionError:
        return None


# ---------------------------------------------------------------- curves

def _tokens(s):
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)          # PasonGamma -> Pason Gamma
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)     # MWDGamma -> MWD Gamma
    return [t.upper() for t in re.split(r"[^A-Za-z0-9]+", s) if t]


def _sequences(section):
    """[(tokens, key)] longest first, for taking words out of a name"""
    seqs = []
    for e in SECTIONS_DATA[section]:
        for sp in e.spellings:
            t = tuple(_tokens(sp))
            if t:
                seqs.append((t, e.key))
    seqs.sort(key=lambda x: -len(x[0]))
    return seqs


_QUALIFIERS = _sequences("curve qualifier")
_SOURCES = _sequences("curve source")


def _take(tokens, seqs):
    """tokens with every listed sequence taken out -> (rest, keys taken)"""
    rest, taken, i = [], [], 0
    while i < len(tokens):
        for seq, k in seqs:
            if tuple(tokens[i:i + len(seq)]) == seq:
                taken.append(k)
                i += len(seq)
                break
        else:
            rest.append(tokens[i])
            i += 1
    return rest, taken


# a well location: 1A1-1, 4B12-33_4B4-33, 01/13-11, 13-32-005-20W3, 3D8-7-3A15-6-2-15W2M
_LOCATION = re.compile(r"[0-9][0-9A-Da-d/_.\-]*[0-9](?:[Ww][1-6][Mm]?)?(?:/\d{2})?")
_LEG = re.compile(r"\b(leg|run|lateral|sidetrack)\s*#?\s*\(?\s*(\d+)\s*\)?", re.I)
_NTH_RUN = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+run\b", re.I)
_ST = re.compile(r"\bST\b\s*#?\s*(\d+)?")
_VALUE_UNITS = {"API", "cps", "units", "%", "ppm", "min/m", "m/h", "kg/m3", "kPa", "ohm.m", "mV", "us/m",
                "b/e", "rpm", "daN", "kdaN"}


def curve(raw):
    """What a curve name means:
    {raw, key, name, unit, unit_hint, qualifiers, source, location, notes, how}

    key is None when the name is not known. how is "exact" when the name is
    listed whole, "parts" when it was found once the location, leg or run,
    company, qualifier words, bracketed unit and trailing number were taken
    out, "bracket" when only a name in brackets was known ("Deep Ind.
    (RILD)"). unit is the curve's usual unit; unit_hint the one its name
    says. location is True when a well location was in the name: the curve
    may be another well's."""
    s = str(raw or "").strip()
    out = {"raw": raw, "key": None, "name": None, "unit": None, "unit_hint": None, "qualifiers": [],
           "source": None, "location": False, "notes": [], "how": None}

    def done(k, how):
        out["key"], out["how"] = k, how
        e = _BY_KEY["curve"].get(k)
        out["name"] = e.name if e else k
        out["unit"] = e.extra if e else None
        return out

    k = key("curve", s)
    if k:
        return done(k, "exact")
    # a well location
    words = []
    for w in s.split():
        bare = w.replace("(", "").replace(")", "")
        if _LOCATION.fullmatch(bare) and re.search(r"[-/]", bare):
            out["location"] = True
        else:
            words.append(w)
    s = " ".join(words)
    # leg, run and sidetrack numbers
    for rx, kind in ((_NTH_RUN, "run"), (_LEG, None)):
        for m in list(rx.finditer(s)):
            out["qualifiers"].append("%s:%s" % (kind or m.group(1).lower(), m.groups()[-1]))
        s = rx.sub(" ", s)
    for m in list(_ST.finditer(s)):
        out["qualifiers"].append("sidetrack" + (":" + m.group(1) if m.group(1) else ""))
    s = _ST.sub(" ", s)
    # what is in brackets: a unit, another name, qualifier words, a company or a note
    alt = None
    for m in list(re.finditer(r"\(([^()]*)\)", s)):
        c = m.group(1).strip()
        if not c:
            continue
        u = unit(c)
        ck = key("curve", c)
        rest, q = _take(_tokens(c), _QUALIFIERS)
        rest2, src = _take(_tokens(c), _SOURCES)
        if u["key"]:
            out["unit_hint"] = u["key"]
        elif ck:
            alt = ck
        elif q and not rest:
            out["qualifiers"] += q
        elif src and not rest2:
            out["source"] = src[0]
        else:
            out["notes"].append("(%s)" % c)
    s = re.sub(r"\([^()]*\)", " ", s)
    if "%" in s:
        out["unit_hint"] = out["unit_hint"] or "%"
        s = s.replace("%", " ")
    tokens = _tokens(s)
    tokens, src = _take(tokens, _SOURCES)
    if src:
        out["source"] = out["source"] or src[0]
    tokens, q = _take(tokens, _QUALIFIERS)
    out["qualifiers"] += [x for x in q if x != "noise"]
    if len(tokens) > 1:
        u = key("unit", tokens[-1])
        if u in _VALUE_UNITS:
            out["unit_hint"] = out["unit_hint"] or u
            tokens = tokens[:-1]
    if len(tokens) > 1 and tokens[-1].isdigit():
        out["qualifiers"].append("#" + tokens[-1])
        tokens = tokens[:-1]
    k = INDEX["curve"].get("".join(tokens)) if tokens else None
    if k:
        return done(k, "parts")
    if alt:
        return done(alt, "bracket")
    if tokens:
        out["notes"].append("left: " + " ".join(tokens))
    return out


# ---------------------------------------------------------------- tracks, columns, header

def _plain_title(title):
    """a title without what it says about one well: the well after " - "
    ("Gamma TVD Log - <well>"), a well location, a trailing number ("Data
    Curves 2")"""
    s = re.sub(r"\s+-\s+.*$", "", str(title or ""))
    s = " ".join(w for w in s.split() if not (_LOCATION.fullmatch(w) and re.search(r"[-/]", w)))
    return re.sub(r"\s+\d+$", "", s).strip()


def curve_track(title):
    return key("curve track", title) == "curves" or key("curve track", _plain_title(title)) == "curves"


def depth_column(title):
    return key("depth column", title)


# the part of a horizontal well a header field is for: "LATERAL SECTION TOTAL
# DEPTH", "DRILLING COMPLETED (TOE)". Header pages cut long labels at the box
# edge, so "BUILD/DIRECTIONAL" can arrive as "IRECTIONAL".
_SECTION_HEAD = re.compile(r"^(lateral|latearal|build\s*/\s*directional|build|ld\s*/\s*directional|directional|"
                           r"irectional|rectional|ctional|vertical|heel|toe)\s+section\s+", re.I)
_SECTION_TAIL = re.compile(r"\s*\((heel|toe)\)\s*$", re.I)


def _section_word(w):
    w = re.sub(r"\s+", "", w.lower())
    return "lateral" if w.startswith("lat") else "build" if "build" in w or w.endswith("ctional") else w


def header(label, box=None):
    """{key, unit, section}: a header page's label ("K.B. Elevation (m):")
    -> its field ("kb_elevation") and the unit it states ("m"). box is the
    title of the box the label is in, if known; a label that means
    different things in different boxes is looked up in the box's first.
    A label for one part of a horizontal well ("LATERAL SECTION TOTAL
    DEPTH", "DRILLING COMPLETED (TOE)") gives that part as section."""
    s = str(label or "").strip().rstrip(":").strip()
    u = None
    m = re.search(r"\(([^()]*)\)\s*$", s)
    if m and unit(m.group(1))["key"]:
        u = unit(m.group(1))["key"]
        s = s[:m.start()].strip()

    def find(text):
        if box:
            b = key("header box", box) or norm(box).lower()
            hit = INDEX["header"].get("%s:%s" % (b, norm(text)))
            if hit:
                return hit
        return key("header", text)

    k, section = find(s), None
    if k is None:
        rest = s
        m = _SECTION_TAIL.search(rest)
        if m:
            section, rest = m.group(1).lower(), rest[:m.start()]
        m = _SECTION_HEAD.match(rest)
        if m and m.group(1).lower() != "vertical":
            section, rest = _section_word(m.group(1)), rest[m.end():]
        if rest != s:
            k = find(rest)
            if k is None:
                section = None
    return {"key": k, "unit": u, "section": section}
