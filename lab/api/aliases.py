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

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alias_table.txt")

CANONICAL = []          # ordered canonical columns
CANONICAL_UNITS = {}    # canonical -> unit
_LOOKUP = {}            # normalized raw name -> canonical


def _norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def _load():
    if not os.path.exists(_PATH):
        return
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
    # canonical names map to themselves
    for c in CANONICAL:
        _LOOKUP.setdefault(_norm(c), c)


_load()


def canon(raw_name):
    """Canonical column for a vendor curve name, or None if unmapped."""
    return _LOOKUP.get(_norm(raw_name))


def canon_unit(canonical):
    return CANONICAL_UNITS.get(canonical, "")
