"""Carmine's alias table: vendor curve names -> canonical columns.

Parses alias_table.txt verbatim (Carmine maintains that file — the format
is his own spec):

    alias = Tr Press,Slurry Rate,WH Prop Conc,BH Prop Conc
    units =      MPa,     m3/Min,       Kg/m3,       Kg/m3

    <Template-Code>
    curve.<Canonical> = <raw name>, <raw name>, ...

Lookups are case/space-insensitive and merged across templates (vendor
curve names don't collide across systems in practice).
"""
import os
import re
import sys

def _find_table():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "alias_table.txt")]
    # PyInstaller onefile extracts bundled data under sys._MEIPASS
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        cands.append(os.path.join(mei, "alias_table.txt"))
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


_DEFAULT_PATH = _find_table()   # the bundled table
_PATH = _DEFAULT_PATH

CANONICAL = []          # ordered canonical columns
CANONICAL_UNITS = {}    # canonical -> unit
_LOOKUP = {}            # normalized raw name -> canonical
# per-template extras Carmine keeps in his file (chart_headers_include,
# chart_stage_tokens, ...). Parsed and kept so his data round-trips even
# though the templates don't consult them yet.
DIRECTIVES = {}         # template code -> {key: [values]}


def _norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def _load():
    if not os.path.exists(_PATH):
        return
    template = None
    for line in open(_PATH, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("alias"):
            CANONICAL.extend(c.strip() for c in line.split("=", 1)[1].split(","))
        elif line.lower().startswith("units"):
            units = [u.strip() for u in line.split("=", 1)[1].split(",")]
            for c, u in zip(CANONICAL, units):
                CANONICAL_UNITS[c] = u
        elif line.lower().startswith("curve."):
            left, right = line.split("=", 1)
            canonical = left.split(".", 1)[1].strip()
            for raw in right.split(","):
                if raw.strip():
                    _LOOKUP[_norm(raw)] = canonical
        elif "=" in line:
            # a per-template directive (chart_headers_include, ...)
            key, right = line.split("=", 1)
            if template:
                DIRECTIVES.setdefault(template, {})[key.strip().lower()] = \
                    [v.strip() for v in right.split(",") if v.strip()]
        else:
            template = line          # a bare line starts a template section
    # canonical names map to themselves
    for c in CANONICAL:
        _LOOKUP.setdefault(_norm(c), c)


def reload(path=None):
    """Re-read the alias table, optionally from a user-supplied file — Carmine
    keeps his own .ini on disk so he can add providers/terminology without a
    rebuild. Pass a falsy path to revert to the bundled table. Returns
    (path_loaded, n_aliases)."""
    global _PATH
    _PATH = path or _DEFAULT_PATH
    CANONICAL.clear()
    CANONICAL_UNITS.clear()
    _LOOKUP.clear()
    DIRECTIVES.clear()
    _load()
    return _PATH, len(_LOOKUP)


_load()


def canon(raw_name):
    """Canonical column for a vendor curve name, or None if unmapped."""
    return _LOOKUP.get(_norm(raw_name))


def canon_unit(canonical):
    return CANONICAL_UNITS.get(canonical, "")
