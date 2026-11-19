#!/usr/bin/env python3
"""Saskatchewan wells for FracView, from the WellSight mud logs.

The logs are not public data, so nothing this writes belongs in the repo or on
the live site: it writes to a folder outside both (default
~/dev/fracview-sk-wellsight). build_viking.py then adds the Viking wells and
writes the set the pages use (~/dev/fracview-sk), which the local server
mounts at /data/sk/ (scripts/serve.py --mount). The
pages find it there and add a Saskatchewan set; where it is missing (the live
site) they carry on without it.

Reads
  CONVERTED   the WellSight conversion (wellsight-convert): index.csv and, per
              log, <log>.json (header, curves, survey), <log>.csv (curves on
              the log's step), <log>.lithology.csv, <log>.accessories.csv
  RAW         the logs themselves (s-h-sl/HLG, s-h-sl/SLG), for the Porosity
              cells, which the conversion does not keep (wellsight_cells.py)
  GRID        SaskGrid 2015 sections (NAD83 lat/lon shapefile), to place each
              well from its legal location and its surface coordinates
  LAB         the frac2csv wellsight branch, for its modules: the decoder,
              wellsight_cells, wellsight_symbols, log_vocab

Writes OUT/
  index.json        the set for the 3D view: every pad's place, plus the rock
                    names, the log types and each one's scale
  pads.json         the set for the map: pads, wells and their paths overhead
  pads/<id>.json    a pad's wells: survey, and their logs along MD
  wells/<id>.json   a well on its own, for the well section

A well is one licence. Its path is its horizontal log's survey (minimum
curvature), or straight down for a vertical well's strip log; a horizontal
well with no survey has no path and is left out (counted in index.json). Its
logs are every log of it on a measured-depth axis (the strip log above the
lateral, the horizontal log along it; where both read, the horizontal log's),
binned every BIN metres of MD:

  gamma, curves     each curve-track curve by kind (log_vocab), the mean of its
                    readings in the bin, in the kind's own unit
  rock              the rock the lithology column shows at the bin's middle
                    (wellsight_symbols terms; blank rows left out)
  por               the Porosity cells: where the bar ends, %, the most in the bin
  show              the Oil Show symbols: 0 dead .. 4 strong, the strongest whose
                    sample (its depth down to the next sample) reaches the bin

Usage:
  python3 -I web/scripts/build_sk.py --jobs 6
"""
import argparse
import csv
import json
import math
import os
import re
import statistics
import struct
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

HOME = os.path.expanduser("~")
BIN = 2.0                        # metres of MD a log bin covers
PAD_M = 60.0                     # wells whose surface holes are this close share a pad
DEFAULTS = {
    "converted": os.path.join(HOME, "dev", "wellsight-converted"),
    "raw": "/Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl",
    "grid": "/Volumes/CnC-2TB-ssd/SK-VIKING/SaskGrid_2015_SECTION/SaskGrid_2015_SECTION-Nad83-ESPG-4269",
    "lab": os.path.join(HOME, "dev", "frac-wt", "wellsight"),
    "out": os.path.join(HOME, "dev", "fracview-sk-wellsight"),    # build_viking.py adds the Viking wells -> ~/dev/fracview-sk
}

LAB = None          # the modules, once --lab is on the path
ws = wcells = wsym = V = None


def use_lab(path):
    global LAB, ws, wcells, wsym, V
    for p in (path, os.path.join(path, "wellsight_convert")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import wellsight as _ws
    import wellsight_cells as _wc
    import wellsight_symbols as _sy
    import log_vocab as _v
    LAB, ws, wcells, wsym, V = path, _ws, _wc, _sy, _v


# ---------------------------------------------------------------- where a well is

# a DLS location: [prefix] LSD-SEC-TWP-RGE W MER, the prefix being a UWI's
# "191/" or a location exception and event such as "2B" (2B7-14-21-11 W2M)
_DLS = r"(?:\d{3}/)?(?:\d[A-Z])?(\d{1,2})-(\d{1,2})-(\d{1,3})-(\d{1,2})\s*W\s*([1-6])"
DLS = re.compile(r"(?<![\d/])" + _DLS, re.I)
# a surface and a bottom hole in one township: 3A2-14/2B7-14-21-11 W2M
PAIR = re.compile(r"(?<![\d/])(?:\d[A-Z])?(\d{1,2})-(\d{1,2})\s*/\s*" + _DLS, re.I)
# Lsd. 7, Sec. 14, Twp. 021, Rge. 11 W2
WORDS = re.compile(r"Lsd\.?\s*(?:\d[A-Z])?(\d{1,2})\s*,?\s*Sec\.?\s*(\d{1,2})\s*,?\s*Twp\.?\s*(\d{1,3})\s*,?\s*"
                   r"Rg?e?\.?\s*(\d{1,2})\s*,?\s*W\s*([1-6])", re.I)
SURF_WORD = re.compile(r"\b(surf\w*|sfc|s\.?l\.?|surface)\b\W*$", re.I)
BH_WORD = re.compile(r"\b(bh\w*|btm|bottom\w*|hole|uwi|u\.w\.i\.?|b\.h\.?l?\.?|#)\W*$", re.I)


def locations(text):
    """[(role, (lsd, sec, twp, rge, mer))] in the order written; role is
    "surface", "bh" or "" where the text does not say"""
    text = str(text or "")
    out, taken = [], []

    def add(m, role, loc):
        if any(a < m.end() and m.start() < b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        before = text[max(0, m.start() - 14):m.start()]
        if not role:
            role = "surface" if SURF_WORD.search(before) else "bh" if BH_WORD.search(before) else ""
        # a UWI (191/07-14-021-11W2/00) names the bottom hole
        if not role and "/" in m.group(0):
            role = "bh"
        out.append((m.start(), role, loc))
    for m in PAIR.finditer(text):
        l1, s1, l2, s2, t, r, mer = (int(x) for x in m.groups())
        add(m, "surface", (l1, s1, t, r, mer))
        out.append((m.start() + 1, "bh", (l2, s2, t, r, mer)))
    for rx in (WORDS, DLS):
        for m in rx.finditer(text):
            add(m, "", tuple(int(x) for x in m.groups()))
    out.sort()
    return [(role, loc) for _, role, loc in out if 1 <= loc[0] <= 16 and 1 <= loc[1] <= 36]


# 123.40 m NORTH of SOUTH and 456.70 m EAST OF WEST Bdy of Section # 14;
# 999.99 m S; 99.99 m W; as measured from the NE corner of Sec. 9;
# 99.99m N of S & 999.99m W of E (2B7-14). The direction says which edge a
# distance is measured from: north from the south edge, west from the east one.
# Sec 14-21-11W2: a section with no LSD
SECDLS = re.compile(r"Sec(?:tion)?\.?\s*(?:#|No\.?)?\s*(\d{1,2})\s*-\s*(\d{1,3})\s*-\s*(\d{1,2})\s*W\s*([1-6])", re.I)
OFF = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m(?:etres|eters|m)?\.?)?\s*(NORTH|SOUTH|EAST|WEST|N|S|E|W)\b", re.I)
SEC = re.compile(r"Sec(?:tion)?\.?\s*(?:#|No\.?)?\s*(\d{1,2})\b|\((?:\d[A-Z])?\d{1,2}-(\d{1,2})\)", re.I)
EDGE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def surface_offsets(text):
    """((edge, metres), (edge, metres), section or None) from the header's
    surface coordinates: how far the hole is from its section's south or
    north edge, and from its west or east edge; None if they are not given"""
    text = str(text or "").replace("\n", " ")
    ns = ew = None
    for m in OFF.finditer(text):
        d = m.group(2)[0].upper()
        v = float(m.group(1))
        if not 0 <= v <= 1700:
            continue
        if d in "NS" and ns is None:
            ns = (EDGE[d], v)
        elif d in "EW" and ew is None:
            ew = (EDGE[d], v)
    if ns is None or ew is None:
        return None
    sec = SEC.search(text)
    return ns, ew, int(sec.group(1) or sec.group(2)) if sec else None


class Sections:
    """SaskGrid 2015 sections: (sec, twp, rge, mer) -> the section's corners
    (SW, SE, NW, NE as (lon, lat)), all of them, with a coarse grid to find
    the sections near a point"""
    CELL = 0.05                                     # degrees

    def __init__(self, base):
        self.base = base
        self.corners = {}
        self.cells = defaultdict(list)
        self.last_lsd = None

    def load_all(self):
        keys = []
        with open(self.base + ".dbf", "rb") as f:
            h = f.read(32)
            n = struct.unpack("<I", h[4:8])[0]
            hl, rl = struct.unpack("<HH", h[8:12])
            fields, p = [], 1
            while True:
                d = f.read(32)
                if d[0] == 0x0D:
                    break
                name, ln = d[:11].split(b"\0")[0].decode(), d[16]
                fields.append((name, p, ln))
                p += ln
            at = {nm: (a, a + ln) for nm, a, ln in fields}
            f.seek(hl)
            for i in range(n):
                r = f.read(rl)
                try:
                    keys.append(tuple(int(r[at[x][0]:at[x][1]]) for x in ("SECT", "PTWP", "PRGE", "PMER")))
                except ValueError:
                    keys.append(None)
        with open(self.base + ".shp", "rb") as fs:
            fs.seek(100)
            for k in keys:
                hdr = fs.read(8)
                if len(hdr) < 8:
                    break
                ln = struct.unpack(">i", hdr[4:8])[0] * 2
                body = fs.read(ln)
                if k is None or struct.unpack("<i", body[:4])[0] != 5:
                    continue
                nparts, npts = struct.unpack("<ii", body[36:44])
                pts = struct.unpack_from("<%dd" % (2 * npts), body, 44 + 4 * nparts)
                c = _corners(list(zip(pts[0::2], pts[1::2])))
                self.corners[k] = c
                lon, lat = sum(q[0] for q in c) / 4, sum(q[1] for q in c) / 4
                self.cells[(int(lat // self.CELL), int(lon // self.CELL))].append(k)
        return self

    def _mid(self, k):
        c = self.corners[k]
        return sum(q[1] for q in c) / 4, sum(q[0] for q in c) / 4

    def find(self, lat, lon, sec=None, km=3.0):
        """the section with the point in it (numbered `sec` if given), else the
        nearest one so numbered within km; None if there is none"""
        r = int(math.ceil(km / (self.CELL * 111.32 * math.cos(math.radians(lat))))) + 1
        ci, cj = int(lat // self.CELL), int(lon // self.CELL)
        best = None
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                for k in self.cells.get((i, j), ()):
                    if sec is not None and k[0] != sec:
                        continue
                    mlat, mlon = self._mid(k)
                    d = _dist((lon, lat), (mlon, mlat))
                    inside = _inside(self.corners[k], lon, lat)
                    score = (not inside, d)
                    if d <= km * 1000 and (best is None or score < best[0]):
                        best = (score, k)
        return best[1] if best else None

    def place(self, sec, twp, rge, mer, ns=None, ew=None, lsd=None):
        """(lat, lon) inside a section: (edge, metres) from its south or north
        edge and its west or east edge, or else an LSD's centre; None if the
        section is not in the grid"""
        c = self.corners.get((sec, twp, rge, mer))
        if not c:
            return None
        sw, se, nw, ne = c
        if ns is not None:
            hgt = (_dist(sw, nw) + _dist(se, ne)) / 2
            wid = (_dist(sw, se) + _dist(nw, ne)) / 2
            v = ns[1] / hgt if ns[0] == "S" else 1 - ns[1] / hgt
            u = ew[1] / wid if ew[0] == "W" else 1 - ew[1] / wid
            v, u = min(1, max(0, v)), min(1, max(0, u))
            row, col = min(3, int(v * 4)), min(3, int(u * 4))
            self.last_lsd = [4 - col, 5 + col, 12 - col, 13 + col][row]
        elif lsd:
            row = (lsd - 1) // 4
            col = (lsd - 1) % 4
            col = 3 - col if row % 2 == 0 else col          # 1-4 run east to west, 5-8 back
            v, u = (row + .5) / 4, (col + .5) / 4
        else:
            v = u = .5
        lon = (1 - v) * ((1 - u) * sw[0] + u * se[0]) + v * ((1 - u) * nw[0] + u * ne[0])
        lat = (1 - v) * ((1 - u) * sw[1] + u * se[1]) + v * ((1 - u) * nw[1] + u * ne[1])
        return lat, lon


def _inside(c, lon, lat):
    sw, se, nw, ne = c
    poly = [sw, se, ne, nw]
    n, inside = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-15) + x1:
            inside = not inside
    return inside


def _dist(a, b):
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * 111320 * k, (a[1] - b[1]) * 111320)


def _corners(xy):
    """a section polygon's SW, SE, NW, NE corners: the vertices furthest that way"""
    lat0 = sum(p[1] for p in xy) / len(xy)
    k = math.cos(math.radians(lat0))
    m = [(p[0] * k, p[1], p) for p in xy]
    pick = lambda f: max(m, key=f)[2]
    return (pick(lambda q: -q[0] - q[1]), pick(lambda q: q[0] - q[1]),
            pick(lambda q: -q[0] + q[1]), pick(lambda q: q[0] + q[1]))


def place_surface(header, index_location, grid, bh_off=None):
    """where the well's surface hole is: (lat, lon, (sec, twp, rge, mer, lsd),
    how), or None. The surface coordinates, where they name their own
    section, place it outright; otherwise a rough place (the surface
    location's LSD, or the bottom hole's less its offset) is snapped into
    the section the surface coordinates are measured in. bh_off is (metres
    north, metres east) from the surface to the bottom hole, when known."""
    sfco = str(header.get("surface_coordinates") or "")
    off = surface_offsets(sfco)
    own = [l for r, l in locations(sfco) if r != "bh"]
    m = SECDLS.search(sfco)
    sure = None
    if off:
        key = own[0][1:5] if own else tuple(int(x) for x in m.groups()) if m else None
        if key and key in grid.corners:
            lat, lon = grid.place(*key, off[0], off[1])
            sure = (lat, lon, key + (grid.last_lsd,), "surface coordinates")
    rough = _rough_surface(header, index_location, grid, bh_off, off)
    if sure:
        # a section the surface coordinates name, kept unless the bottom hole and
        # its offset put the surface well away from it (a header copied from
        # another well, or a mistyped meridian)
        if rough and rough[3].startswith("bottom hole location less") and _dist((sure[1], sure[0]), (rough[1], rough[0])) > 3000:
            return rough[0], rough[1], rough[2], rough[3] + " (the surface coordinates' own section is too far from it)"
        return sure
    return rough


def _rough_surface(header, index_location, grid, bh_off, off):
    locs = locations(header.get("location") or index_location)
    surf = [l for r, l in locs if r == "surface"] or [l for r, l in locs if r == ""]
    bh = [l for r, l in locs if r == "bh"] or ([l for r, l in locs][1:2] if len(locs) > 1 else [])
    if surf and bh and surf[0] == bh[0]:
        bh = []
    approx = None
    # a surface location written as a pair (3A2-13/2B7-14-21-11W2) borrows the
    # bottom hole's township, which the surface may not be in: where the bottom
    # hole and its offset are known, the surface is found back from them
    if bh and bh_off and bh[0][1:5] in grid.corners:
        c = grid.place(*bh[0][1:5], lsd=bh[0][0])
        approx = (c[0] - bh_off[0] / 111320, c[1] - bh_off[1] / (111320 * math.cos(math.radians(c[0]))))
        base, how = bh[0], "bottom hole location less its offset"
    elif surf and surf[0][1:5] in grid.corners:
        approx, base, how = grid.place(*surf[0][1:5], lsd=surf[0][0]), surf[0], "surface location"
    elif bh and bh[0][1:5] in grid.corners:
        approx, base, how = grid.place(*bh[0][1:5], lsd=bh[0][0]), bh[0], "bottom hole location (rough: no offset to the surface)"
    if approx is None:
        return None
    sec_no = off[2] if off and off[2] else surf[0][1] if surf else None
    if off:
        k = grid.find(approx[0], approx[1], sec=sec_no)
        if k:
            lat, lon = grid.place(*k, off[0], off[1])
            return lat, lon, k + (grid.last_lsd,), how + ", put in its section by the surface coordinates"
    if how.startswith("bottom hole location less") and surf:
        # no surface coordinates: the surface LSD, in the section it names nearest the rough place
        k = grid.find(approx[0], approx[1], sec=surf[0][1])
        if k:
            lat, lon = grid.place(*k, lsd=surf[0][0])
            return lat, lon, k + (surf[0][0],), how + ", at its LSD"
    k = grid.find(approx[0], approx[1], km=1.0)
    return approx[0], approx[1], (k or base[1:5]) + (base[0] if how == "surface location" else None,), how


def bh_location(header, index_location=None, surface=None):
    """the bottom hole's location as the header writes it (lsd, sec, twp, rge,
    mer): the one marked so, else the second of two, else a lone location in
    another section than the surface (sec, twp, rge, mer); None if not given"""
    locs = locations(header.get("location") or index_location)
    for role, l in locs:
        if role == "bh":
            return l
    if len(locs) > 1:
        return locs[1][1]
    if locs and surface and tuple(locs[0][1][1:5]) != tuple(surface[:4]):
        return locs[0][1]
    return None


REL = re.compile(r"well\s*cent|wellhead|w/?c\b|surface|surf\.?\s*loc|from\s+surf|of\s+surf", re.I)
DIR_FIRST = re.compile(r"\b(NORTH|SOUTH|EAST|WEST)\s*:?\s*(\d+(?:\.\d+)?)\s*m", re.I)


def bh_offsets(text):
    """(metres north, metres east) of the bottom hole from the surface hole,
    from the header's bottom hole coordinates when they are written that way
    ("123.40 m NORTH and 1456.70 m EAST of surface location"); the final TD's
    where they give the intermediate casing point too; else None"""
    text = str(text or "").replace("\n", " ")
    icp = re.search(r"ICP|intermediate", text, re.I)
    ftd = re.search(r"\bF?TD\b|\btoe\b", text[icp.end():], re.I) if icp else None
    if ftd:                                 # the casing point first, then the bottom hole: the bottom hole's
        text = text[icp.end() + ftd.start():]
    m = REL.search(text)
    if not m:
        return None
    # the offsets before the words ("123.40 m NORTH and 1456.70 m EAST of surface
    # location"), or after them ("Referenced to well center: 1234.50 m South, ...")
    part = text[:m.end()]
    if not OFF.search(part) and not DIR_FIRST.search(part):
        part = text[m.end():m.end() + 160]
    if re.search(r"\bof\s+(?:the\s+)?(?:south|north|east|west|s|n|e|w)\b|bound|bdy|bdry|N-S|E-W", part, re.I):
        return None
    n = e = None
    pairs = [(float(x.group(1)), x.group(2)[0].upper()) for x in OFF.finditer(part)]
    pairs += [(float(x.group(2)), x.group(1)[0].upper()) for x in DIR_FIRST.finditer(part)]
    for v, d in pairs:
        if d in "NS" and n is None:
            n = v if d == "N" else -v
        elif d in "EW" and e is None:
            e = v if d == "E" else -v
    if n is None or e is None or math.hypot(n, e) < 30 or math.hypot(n, e) > 6000:
        return None
    return n, e


def md_tvd_path(points, az):
    """[(md, tvd)] with no inclinations, and the direction the well heads in
    (degrees) -> [(md, tvd, ns, ew, inc, az)]: each step's sideways run is what
    its MD has over its TVD; above the first point the hole goes straight down,
    then builds on an arc to the first point's slope"""
    pts = sorted((p for p in points if p[0] is not None and p[1] is not None), key=lambda p: p[0])
    pts = [p for i, p in enumerate(pts) if i == 0 or p[0] > pts[i - 1][0] + 1e-6]
    if len(pts) < 2:
        return None
    a = math.radians(az)
    out = []
    m1, t1 = pts[0]
    dm, dt = pts[1][0] - m1, pts[1][1] - t1
    th = math.acos(max(-1, min(1, dt / dm))) if dm > 0 else 0
    h = 0.0
    if m1 > t1 + 0.5 and th > math.radians(2):
        # straight down to K, then an arc of radius R to (m1, t1) at slope th
        k = (m1 * math.sin(th) - t1 * th) / (math.sin(th) - th)
        if 0 <= k < t1:
            r = (t1 - k) / math.sin(th)
            out.append((0.0, 0.0, 0.0, 0.0, 0.0, az))
            for f in (.25, .5, .75):
                q = th * f
                out.append((k + r * q, k + r * math.sin(q), r * (1 - math.cos(q)) * math.cos(a), r * (1 - math.cos(q)) * math.sin(a), math.degrees(q), az))
            h = r * (1 - math.cos(th))
        else:
            h = math.sqrt(max(0, m1 * m1 - t1 * t1))
            out.append((0.0, 0.0, 0.0, 0.0, 0.0, az))
    elif m1 > 0:
        h = math.sqrt(max(0, m1 * m1 - t1 * t1))
        out.append((0.0, 0.0, 0.0, 0.0, 0.0, az))
    out.append((m1, t1, h * math.cos(a), h * math.sin(a), math.degrees(th), az))
    for (ma, ta), (mb, tb) in zip(pts, pts[1:]):
        dm, dt = mb - ma, tb - ta
        dh = math.sqrt(max(0, dm * dm - dt * dt))
        h += dh
        out.append((mb, tb, h * math.cos(a), h * math.sin(a), math.degrees(math.atan2(dh, dt)), az))
    return out


# a stated point's offset from the surface hole, in the text beside it:
# "TOE COORDINATES: 12.50 m S;  905.50 m E", "-0.5 m South, 310.5 m East",
# "Final Coordinates: 1104.50 m N; 8.50 m E"
COORD_NUM = re.compile(r"(-?)(\d+(?:\.\d+)?)\s*(?:m(?:etres|eters)?\.?)?\s*(NORTH|SOUTH|EAST|WEST|N|S|E|W)\b(?!\s*(?:of\s+(?:the\s+)?(?:north|south|east|west|n|s|e|w)\b|bound|bdy|bdry))", re.I)


def text_coords(text):
    """(metres north, metres east) a stated point's text gives it from the
    well, or None. A minus before a direction is the direction written twice
    ("-310.50m South" is south). Offsets measured from a section's corner or
    edge are passed over for the ones from the well ("410.5m S; 285.5m W; NE
    corner of Sec 14 ...; 188.5m S & 4.5m W of well centre")."""
    text = str(text or "").replace("\n", " ")
    ms = list(COORD_NUM.finditer(text))
    pairs = []
    for x, y in zip(ms, ms[1:]):
        dx, dy = x.group(3)[0].upper(), y.group(3)[0].upper()
        if (dx in "NS") == (dy in "NS") or y.start() - x.end() > 40:
            continue
        ns, ew = (x, y) if dx in "NS" else (y, x)
        n = float(ns.group(2)) * (1 if ns.group(3)[0].upper() == "N" else -1)
        e = float(ew.group(2)) * (1 if ew.group(3)[0].upper() == "E" else -1)
        after = text[y.end():y.end() + 45]
        if re.match(r"[\s;,.:()&-]*(?:as measured from\s+)?(?:the\s+)?(?:[NS][EW]\s+corner|corner|bound|bdy|bdry|of\s+sec|sec(?:tion)?\b)", after, re.I):
            continue
        rank = 0 if re.match(r"[\s;,.:()&-]*(?:of|from)?\s*(?:the\s+)?(?:well|surface|w/?c\b|wellhead)", after, re.I) else 1
        if math.hypot(n, e) < 6000:
            pairs.append((rank, n, e))
    if not pairs:
        return None
    best = min(pairs, key=lambda p: p[0])
    return best[1], best[2]


def station_path(points, az=None):
    """[(md, tvd, north or None, east or None)] -> [(md, tvd, ns, ew, inc, az)]
    from the surface, for a well whose log states depths and offsets but has no
    survey. Each step's sideways run is what its MD has over its TVD (above the
    first point the hole goes down, then builds on an arc to it, as in
    md_tvd_path); the run follows the line between the points whose offsets are
    known (the surface is one), and past the last of them carries on its way,
    or heads `az` degrees where no offset is known. None if there is no way to
    point it."""
    pts = sorted((p for p in points if p[0] is not None and p[1] is not None and p[1] <= p[0] + 1), key=lambda p: p[0])
    clean = []
    for p in pts:
        if clean and p[0] <= clean[-1][0] + 1e-6:
            if p[2] is not None and clean[-1][2] is None:
                clean[-1] = p
            continue
        if clean and p[1] < clean[-1][1] - 50:          # a TVD that goes back up by much: a typo
            continue
        clean.append(p)
    if not clean:
        return None
    known = [p for p in clean if p[2] is not None]
    if not known and az is None:
        return None
    base = md_tvd_path([(p[0], p[1]) for p in clean], 0.0)
    if base is None:                                     # one point: down, then the arc to it
        m1, t1 = clean[0][0], clean[0][1]
        base = [(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), (m1, t1, math.sqrt(max(0, m1 * m1 - t1 * t1)), 0.0, 90.0, 0.0)]
    # the run sideways along the hole at each station (md_tvd_path heads north)
    h = {round(b[0], 3): b[2] for b in base}
    # an offset further from the surface than the hole has run sideways by then
    # cannot be: a misread or mistyped one, left out
    anchors = [(0.0, 0.0, 0.0)] + [(h[round(p[0], 3)], p[2], p[3]) for p in known
                                   if math.hypot(p[2], p[3]) <= h[round(p[0], 3)] + max(50.0, .1 * h[round(p[0], 3)])]
    if len(anchors) == 1 and az is None:
        known_az = [p for p in known]
        if not known_az:
            return None
        az = math.degrees(math.atan2(known_az[-1][3], known_az[-1][2]))
    out = []
    for md, tvd, run, _e, inc, _a in base:
        prev = max((a for a in anchors if a[0] <= run + 1e-6), key=lambda a: a[0])
        nxt = [a for a in anchors if a[0] > run + 1e-6]
        if nxt:
            b = min(nxt, key=lambda a: a[0])
            f = (run - prev[0]) / (b[0] - prev[0])
            n, e = prev[1] + f * (b[1] - prev[1]), prev[2] + f * (b[2] - prev[2])
        else:
            # past the last known offset: on in the last leg's direction (or `az`)
            last = anchors[-1]
            before = anchors[-2] if len(anchors) > 1 else None
            if before and math.hypot(last[1] - before[1], last[2] - before[2]) > 1:
                th = math.atan2(last[2] - before[2], last[1] - before[1])
            elif az is not None:
                th = math.radians(az)
            else:
                th = math.atan2(last[2], last[1]) if math.hypot(last[1], last[2]) > 1 else 0.0
            n, e = last[1] + (run - last[0]) * math.cos(th), last[2] + (run - last[0]) * math.sin(th)
        out.append((md, tvd, n, e, inc, 0.0))
    # each station's heading, from the step that reaches it
    res = [out[0]]
    for a, b in zip(out, out[1:]):
        hdg = math.degrees(math.atan2(b[3] - a[3], b[2] - a[2])) % 360 if math.hypot(b[2] - a[2], b[3] - a[3]) > .01 else res[-1][5]
        res.append(b[:5] + (hdg,))
    return res


def stated_points(logs_json):
    """the MD/TVD points a well's logs state in their text ("1793.6 m MD //
    1793.5 m TVD", the decoder's own pattern), each with the offset its text
    gives it: [(md, tvd, north, east)], north/east None where not given. Read
    from the whole annotation, which the conversion's md_tvd_points_from_text
    cuts at 120 characters, often before the offsets."""
    out = {}
    for j in logs_json:
        for a in j.get("annotations") or []:
            text = a.get("text") or ""
            for m in ws._MDTVD_TEXT.finditer(text):
                md, tvd = float(m.group(1)), float(m.group(2))
                if not 0 < tvd <= md + 0.5:
                    continue
                c = text_coords(text[m.start():]) or text_coords(text)
                k = round(md, 1)
                if k not in out or (out[k][2] is None and c):
                    out[k] = (md, tvd, c[0] if c else None, c[1] if c else None)
    return [out[k] for k in sorted(out)]


def stated_path(pts, rel=None, surface=None, target=None):
    """a path for a horizontal well with no survey, from the depths (and
    offsets) its logs state: (traj, how), or (None, why). rel: the header's
    bottom hole offset from the surface (metres north, east); surface: the
    surface hole (lat, lon); target: the bottom hole's own location (lat,
    lon). Stated offsets are sometimes mirrored (on wells with a survey too,
    the survey and the bottom hole's location agree against them 38 times to
    7), so where the path's end misses the bottom hole's location by far
    more than heading straight for it would, it heads for it instead."""
    if not pts:
        return None, "no stated depths"
    az = math.degrees(math.atan2(rel[1], rel[0])) if rel else None
    traj = station_path(pts, az=az)
    how = ("the depths and offsets its log states" if any(p[2] is not None for p in pts)
           else "the depths its log states, toward the bottom hole coordinates" if az is not None else None)
    to_target = None
    if surface and target:
        k = math.cos(math.radians(surface[0]))
        dn, de = (target[0] - surface[0]) * 111320, (target[1] - surface[1]) * 111320 * k
        if math.hypot(dn, de) > 150:
            to_target = (math.degrees(math.atan2(de, dn)), math.hypot(dn, de))
    if traj and to_target:
        k = math.cos(math.radians(surface[0]))
        end = traj[-1]
        miss = _dist((surface[1] + end[3] / (111320 * k), surface[0] + end[2] / 111320), (target[1], target[0]))
        run = math.hypot(end[2], end[3])
        if miss > max(600.0, .5 * run) and abs(to_target[1] - run) < max(600.0, .5 * run):
            traj, how = None, None
    if traj is None and to_target:
        traj = station_path([(p[0], p[1], None, None) for p in pts], az=to_target[0])
        how = "the depths its log states, toward the bottom hole location"
    if traj is None:
        return None, "stated depths, but nothing to say which way the well heads"
    return traj, how


def dls_text(k):
    """(sec, twp, rge, mer, lsd) -> 7-14-21-11W2"""
    if not k:
        return ""
    return ("%d-" % k[4] if k[4] else "") + "%d-%d-%dW%d" % k[:4]


# ---------------------------------------------------------------- a well's path

def min_curvature(stations):
    """[(md, tvd, inc, az)] -> [(md, tvd, ns, ew, inc, az)] from the surface,
    from the stations that have an inclination and azimuth. Many surveys
    start deep, already in the build: above the first station the hole goes
    straight down and then builds on an arc that reaches that station at its
    own TVD and inclination (curving all the way from the surface would put
    the lateral hundreds of metres too shallow)."""
    st = sorted(((s[0], s[1], s[2], s[3]) for s in stations if s[0] is not None and s[2] is not None and s[3] is not None),
                key=lambda s: s[0])
    st = [s for i, s in enumerate(st) if i == 0 or s[0] > st[i - 1][0]]
    if not st:
        return [(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
    m1, t1, i1, a1 = st[0]
    out = [(0.0, 0.0, 0.0, 0.0, 0.0, a1)]
    if m1 > 1 and t1 is not None and t1 < m1 - 0.5 and i1 > 0.5:
        th, az = math.radians(i1), math.radians(a1)
        k = (m1 * math.sin(th) - t1 * th) / (math.sin(th) - th)
        if 0 <= k < t1:
            r = (t1 - k) / math.sin(th)
            out.append((k, k, 0.0, 0.0, 0.0, a1))
            for f in (.25, .5, .75):
                q = th * f
                out.append((k + r * q, k + r * math.sin(q), r * (1 - math.cos(q)) * math.cos(az), r * (1 - math.cos(q)) * math.sin(az), math.degrees(q), a1))
            h = r * (1 - math.cos(th))
        else:
            h = math.sqrt(max(0.0, m1 * m1 - t1 * t1))
        out.append((m1, t1, h * math.cos(az), h * math.sin(az), i1, a1))
        rest = st[1:]
    else:
        out[0] = (0.0, 0.0, 0.0, 0.0, 0.0, a1)
        rest = st if m1 > 0 else st[1:]
        if m1 <= 0:
            out[0] = (0.0, 0.0, 0.0, 0.0, i1, a1)
    for b in rest:
        md0, tvd, ns, ew, inc0, az0 = out[-1]
        dm = b[0] - md0
        if dm <= 0:
            continue
        i1_, i2, a1_, a2 = (math.radians(x) for x in (inc0, b[2], az0, b[3]))
        cosd = math.cos(i2 - i1_) - math.sin(i1_) * math.sin(i2) * (1 - math.cos(a2 - a1_))
        dl = math.acos(max(-1.0, min(1.0, cosd)))
        rf = 1.0 if dl < 1e-9 else 2 / dl * math.tan(dl / 2)
        ns += dm / 2 * (math.sin(i1_) * math.cos(a1_) + math.sin(i2) * math.cos(a2)) * rf
        ew += dm / 2 * (math.sin(i1_) * math.sin(a1_) + math.sin(i2) * math.sin(a2)) * rf
        tvd += dm / 2 * (math.cos(i1_) + math.cos(i2)) * rf
        out.append((b[0], tvd, ns, ew, b[2], b[3]))
    # a station's TVD as the survey states it (the log's own TVD curve), where it does:
    # the minimum curvature places the hole sideways
    told = {s[0]: s[1] for s in st if s[1] is not None}
    return [(x[0], told.get(x[0], x[1])) + x[2:] for x in out]


def read_survey(conv, log):
    path = os.path.join(conv, log["file"] + ".survey.csv")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            md, tvd, inc, az = (_num(r.get(k)) for k in ("md_m", "tvd_m", "inclination_deg", "azimuth_deg"))
            if md is not None:
                out.append((md, tvd, inc, az))
    return out


def survey_rank(sv):
    """a survey with inclinations first, then the most points"""
    full = sum(1 for s in sv if s[2] is not None and s[3] is not None)
    return (full >= 3, full if full >= 3 else sum(1 for s in sv if s[1] is not None))


def heel_of(traj):
    for a, b in zip(traj, traj[1:]):
        dm = b[0] - a[0]
        if dm > 0 and (b[1] - a[1]) / dm < math.cos(math.radians(80)):
            return a[0]
    return None


# ---------------------------------------------------------------- a log, binned

def _num(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


CURVE_COL = re.compile(r"^(.*?)\s*\[(.*)\]\s*$")
SKIP_COLS = re.compile(r"^(DEPTH|DEPT|LITH|PCT_|SLIDE|TVD|MD\b)", re.I)
# a track's placeholder name, not a curve's: "C 15", "New Track", "Zero"
JUNK = re.compile(r"^(c|col|column|curve|track|new[ _]?track|zero|blank|dummy|none|unknown|pason)[ _#.]*\d*$", re.I)
PICKS = re.compile(r"^(P|SH|F)?(TOP|BASE|BOT)S?\d*$", re.I)        # formation picks stored as a depth "curve"


def curve_kind(name, mnem):
    """(type key, title, unit) for a curve: gamma ray is the "gamma" type every
    view knows; any other kind log_vocab names is "c:<kind>", and a curve it
    does not know keeps its own name"""
    for raw in (name, mnem):
        c = V.curve(raw) if raw else None
        if c and c.get("key"):
            return ("gamma" if c["key"] == "gamma" else "c:" + c["key"]), c["name"], c.get("unit")
    nm = (name or mnem or "?").strip()
    if JUNK.match(nm):
        return None, None, None
    if re.search(r"GAMMA|\bGR\b|\bAPI\b", nm.upper()):
        return "gamma", "Gamma ray", "API"
    return "x:" + re.sub(r"[^a-z0-9]+", "_", nm.lower()).strip("_"), nm, None


def bin_log(job):
    """one log -> {"bins": {type: {bin index: value}}, "meta": {...}} on MD
    (BIN-metre bins from 0 m), or {"error": why}"""
    conv, raw_dir, log = job
    base = os.path.join(conv, log["file"])
    try:
        d = json.load(open(base + ".json"))
    except Exception as e:
        return {"error": "json: %s" % e}
    bins = defaultdict(dict)
    meta = {"types": {}, "notes": []}
    sums = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    names = {}
    for c in d.get("curves") or []:
        names[(c.get("mnemonic") or "").upper()] = c
    # curves: the mean of each bin's readings, in the kind's own unit
    try:
        with open(base + ".csv", newline="") as f:
            rd = csv.reader(f)
            head = next(rd)
            cols = []
            for j, h in enumerate(head[1:], 1):
                m = CURVE_COL.match(h)
                mnem, unit = (m.group(1), m.group(2)) if m else (h, "")
                if SKIP_COLS.match(mnem) or PICKS.match(mnem) or unit.strip().lower() in ("m", "metres", "ft"):
                    continue
                c = names.get(mnem.upper()) or {}
                k, title, kunit = curve_kind(c.get("name") or mnem, mnem)
                if k is None:
                    continue
                conv_to = kunit if kunit and unit and V.convert(1.0, unit, kunit) is not None else None
                cols.append((j, k, title, conv_to or unit, unit if conv_to else None))
                meta["types"].setdefault(k, {"t": title, "u": conv_to or unit or ""})
            for r in rd:
                md = _num(r[0])
                if md is None:
                    continue
                b = int(md // BIN)
                for j, k, _t, to, frm in cols:
                    v = _num(r[j]) if j < len(r) else None
                    if v is None:
                        continue
                    if frm:
                        v = V.convert(v, frm, to)
                        if v is None:
                            continue
                    s = sums[(k, j)][b]
                    s[0] += v
                    s[1] += 1
    except FileNotFoundError:
        pass
    best = {}
    for (k, j), by in sums.items():
        n = sum(s[1] for s in by.values())
        if n and (k not in best or n > best[k][0]):
            best[k] = (n, by)
    for k, (_n, by) in best.items():
        bins[k] = {b: round(s[0] / s[1], 3) for b, s in by.items() if s[1]}
    # rock: the lithology column at each bin's middle
    rocks = []
    try:
        with open(base + ".lithology.csv", newline="") as f:
            for r in csv.DictReader(f):
                t, b = _num(r.get("top_m")), _num(r.get("base_m"))
                if t is None or b is None or b <= t:
                    continue
                rocks.append({"top": t, "base": b, "code": r.get("code"), "rock": r.get("rock")})
    except FileNotFoundError:
        pass
    if rocks:
        for iv in wsym.rocks_from(rocks):
            if iv["rock"] == "blank":
                continue
            for b in range(int(iv["top"] // BIN), int(iv["base"] // BIN) + 1):
                mid = (b + .5) * BIN
                if iv["top"] <= mid < iv["base"]:
                    bins["rock"][b] = iv["rock"]
                    meta.setdefault("rock_names", {})[iv["rock"]] = iv["name"]
    # shows: each show symbol reaches from its depth to the next sample
    acc = []
    try:
        with open(base + ".accessories.csv", newline="") as f:
            for r in csv.DictReader(f):
                dm = _num(r.get("depth_m"))
                if dm is not None:
                    acc.append({"depth_m": dm, "category": r.get("category"), "code": r.get("code")})
    except FileNotFoundError:
        pass
    syms = wsym.symbols_from(acc)
    shows = [s for s in syms if s["group"] == "show" and s["rank"] is not None]
    if shows:
        sp = wsym._spacing([s["depth"] for s in (shows if len(shows) >= 3 else syms)])
        sp = min(10.0, max(0.5, sp or 1.0))
        for s in shows:
            for b in range(int(s["depth"] // BIN), int((s["depth"] + sp - 1e-6) // BIN) + 1):
                if bins["show"].get(b) is None or s["rank"] > bins["show"][b]:
                    bins["show"][b] = s["rank"]
    # porosity: the Porosity cells, from the log itself
    if raw_dir:
        try:
            raw = open(os.path.join(raw_dir, log["file"]), "rb").read()
            body, _ = ws.inflate(raw, [])
            titles = {t[2] for t in ws.tracks(body) if t[2]} | set(d.get("columns") or [])
            found = [g for g in wcells.grids(body, titles) if g["kind"] == wcells.KIND_POROSITY]
            top = (d.get("depth") or {}).get("log_top")
            if found and top is not None:
                sp = wcells.span(found, top)
                if sp:
                    b0, b1 = int(sp[0] // BIN), int(sp[1] // BIN)
                    depths = [b * BIN for b in range(b0, b1 + 1)]
                    curves, notes = wcells.las_curves(found, top, depths, BIN)
                    meta["notes"] += notes
                    for mn, _u, _d, vals in curves:
                        if mn == wcells.POROSITY_MNEM:
                            for b, v in zip(range(b0, b1 + 1), vals):
                                if v is not None:
                                    bins["por"][b] = v
                elif not sp:
                    meta["notes"] += wcells.las_curves(found, top, [top], BIN)[1]
        except FileNotFoundError:
            meta["notes"].append("the log file is not on the drive")
        except Exception as e:                      # one log's cells never stop the build
            meta["notes"].append("porosity cells unreadable (%s)" % type(e).__name__)
    return {"bins": {k: v for k, v in bins.items() if v}, "meta": meta, "header": d.get("header") or {},
            "lith_source": (d.get("lithology") or {}).get("along_hole_source")}


# ---------------------------------------------------------------- wells

YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)|(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2})(?!\d)|\b\w+\s+\d{1,2}\s*/\s*(\d{2})\b")


def year_of(*texts):
    for t in texts:
        m = YEAR.search(str(t or ""))
        if not m:
            continue
        if m.group(1):
            return int(m.group(1))
        yy = m.group(4) or m.group(5)
        if yy:
            y = int(yy)
            return 2000 + y if y < 50 else 1900 + y
    return None


def metres(t):
    m = re.search(r"(-?\d+(?:\.\d+)?)", str(t or ""))
    return float(m.group(1)) if m else None


HZ_NAME = re.compile(r"\b(hz|horiz\w*|hor)\b", re.I)


def build(args):
    use_lab(args.lab)
    conv = args.converted
    rows = [r for r in csv.DictReader(open(os.path.join(conv, "index.csv"), newline=""))
            if r["status"] == "ok" and not r["duplicate_of"]]
    # one licence, one well
    groups = defaultdict(list)
    for r in rows:
        lic = re.sub(r"\s+", "", r["licence"]).upper()
        key = lic or ("~" + (r["well_name"].strip().upper() + "|" + r["location"].strip().upper()))
        if key == "~|":
            continue
        groups[key].append(r)
    print("%d logs, %d wells" % (len(rows), len(groups)), file=sys.stderr)

    # every log on an MD axis, binned (the slow part: it reads the logs' own cells)
    md_logs = [r for r in rows if r["depth_axis"] == "MD"]
    if args.limit:
        keep = set(sorted(groups)[:args.limit])
        md_logs = [r for r in md_logs if any(r in groups[k] for k in keep)]
        groups = {k: groups[k] for k in keep}
    jobs = [(conv, None if args.no_cells else args.raw, r) for r in md_logs]
    binned = {}
    with Pool(args.jobs, initializer=use_lab, initargs=(args.lab,)) as pool:
        for n, (r, res) in enumerate(zip(md_logs, pool.imap(bin_log, jobs, chunksize=8)), 1):
            binned[r["file"]] = res
            if n % 500 == 0:
                print("  %d / %d logs read" % (n, len(md_logs)), file=sys.stderr)

    grid = Sections(args.grid)
    wells, skipped = [], Counter()
    plan = []
    for key, logs in groups.items():
        hz = [r for r in logs if r["app"] == "HORIZONTAL.LOG"]
        surveys = sorted(((read_survey(conv, r), r) for r in hz), key=lambda x: survey_rank(x[0]), reverse=True)
        survey, path_log = surveys[0] if surveys and surveys[0][0] else ([], None)
        mds = [r for r in logs if r["depth_axis"] == "MD" and r["file"] in binned and "error" not in binned[r["file"]]]
        if not mds:
            skipped["no log on a measured-depth axis"] += 1
            continue
        head_log = path_log or (hz[0] if hz else mds[0])
        header = (binned.get(head_log["file"]) or {}).get("header") or json.load(open(os.path.join(conv, head_log["file"] + ".json"))).get("header") or {}
        name = header.get("well_name") or head_log["well_name"]
        vertical = not survey and not hz and not HZ_NAME.search(name or "")
        stated = None
        if not survey and not vertical:
            # no survey: the depths (and offsets) its logs state in their text
            stated = stated_points([json.load(open(os.path.join(conv, r["file"] + ".json"))) for r in logs])
            if not stated:
                skipped["horizontal, no survey and no depths stated in its logs"] += 1
                continue
        plan.append((key, logs, hz, survey, path_log, mds, header, name, vertical, stated))
    print("reading the SaskGrid sections", file=sys.stderr)
    grid.load_all()
    checks, est_checks = [], []

    for key, logs, hz, survey, path_log, mds, header, name, vertical, stated in plan:
        heads = [header] + [(binned.get(r["file"]) or {}).get("header") or {} for r in logs]
        # the path: the survey; or, where it has only MD and TVD, those heading
        # for the bottom hole the header gives
        traj0, path_how, bh_off = None, None, None
        rel = next((o for o in (bh_offsets(h.get("bottom_hole_coordinates")) for h in heads) if o), None)
        if survey and survey_rank(survey)[0]:
            traj0, path_how = min_curvature(survey), "survey"
            bh_off = (traj0[-1][2], traj0[-1][3])
        elif survey and rel:
            traj0 = md_tvd_path([(q[0], q[1]) for q in survey], math.degrees(math.atan2(rel[1], rel[0])))
            path_how, bh_off = "MD and TVD, toward the bottom hole coordinates", (traj0[-1][2], traj0[-1][3]) if traj0 else rel
        elif stated:
            toe = [p for p in stated if p[2] is not None]
            bh_off = (toe[-1][2], toe[-1][3]) if toe else None
        placed = None
        for h, r in zip(heads, [path_log or logs[0]] + logs):
            placed = place_surface(h, r["location"], grid, rel or bh_off)
            if placed:
                break
        if not placed:
            skipped["no legal location in its headers"] += 1
            continue
        lat0, lon0, skey, how = placed
        bhl = bh_location(header, (path_log or logs[0])["location"], skey)
        tgt = grid.place(*bhl[1:5], lsd=bhl[0]) if bhl and bhl[1:5] in grid.corners else None
        if survey and not traj0 and not tgt:
            # the bottom hole written from its own section's edges ("345m S of N Bdy,
            # 210.5m E of W Bdy, Sec 23"): that section, nearest the surface hole
            for h in heads:
                ab = surface_offsets(h.get("bottom_hole_coordinates"))
                if ab and ab[2]:
                    k = grid.find(lat0, lon0, sec=ab[2], km=4.0)
                    if k:
                        tgt = grid.place(*k, ab[0], ab[1])
                        break
        if survey and not traj0 and tgt:
            dn, de = (tgt[0] - lat0) * 111320, (tgt[1] - lon0) * 111320 * math.cos(math.radians(lat0))
            if math.hypot(dn, de) > 150:
                traj0 = md_tvd_path([(q[0], q[1]) for q in survey], math.degrees(math.atan2(de, dn)))
                path_how = "MD and TVD, toward the bottom hole location"
        if stated:
            traj0, path_how = stated_path(stated, rel, (lat0, lon0), tgt)
            if not traj0:
                skipped["horizontal, no survey, stated depths but no way to tell which way it heads"] += 1
                continue
        if survey and not traj0:
            skipped["horizontal, MD and TVD only, no bottom hole to head for"] += 1
            if args.debug:
                with open(args.debug, "a") as dbg:
                    dbg.write(json.dumps({"nodir": 1, "loc": header.get("location"), "sfco": header.get("surface_coordinates"),
                                          "bhco": header.get("bottom_hole_coordinates"), "how": how}) + "\n")
            continue
        # logs: strip logs first, the horizontal log over them where both read
        order = sorted(mds, key=lambda r: (r["app"] == "HORIZONTAL.LOG", r is path_log))
        merged, types, notes, rock_names, srcs = defaultdict(dict), {}, [], {}, []
        for r in order:
            res = binned[r["file"]]
            for k, by in res["bins"].items():
                merged[k].update(by)
            for k, t in res["meta"]["types"].items():
                if k in res["bins"]:
                    types.setdefault(k, t)
            rock_names.update(res["meta"].get("rock_names") or {})
            notes += res["meta"]["notes"]
            srcs.append({"log": r["app"].split(".")[0].lower(), "from": _num(r["log_top"]), "to": _num(r["log_bottom"]),
                         "lith": res.get("lith_source")})
        if not any(merged.values()):
            skipped["logs hold no curves, rock, porosity or shows"] += 1
            continue
        lo = min(min(by) for by in merged.values() if by)
        hi = max(max(by) for by in merged.values() if by)
        logs_out = {"bin": BIN, "md0": lo * BIN, "n": hi - lo + 1, "types": {}, "src": srcs}
        for k, by in merged.items():
            if not by:
                continue
            arr = [by.get(b) for b in range(lo, hi + 1)]
            logs_out["types"][k] = arr
        bottom = (hi + 1) * BIN
        td = max([metres(header.get("total_depth")) or 0, bottom] + [s[0] for s in survey])
        if traj0:
            traj = list(traj0)
            if traj[-1][0] < bottom - 1:            # logged past the last station
                md, tvd, n_, e_, inc, az = traj[-1]
                dm = bottom - md
                if rel and math.hypot(rel[0] - n_, rel[1] - e_) > 300 and math.hypot(rel[0] - n_, rel[1] - e_) < dm * 1.05:
                    # the survey stops short of the bottom hole the header gives: on to it, level
                    traj.append((bottom, tvd, rel[0], rel[1], 90.0, math.degrees(math.atan2(rel[1] - e_, rel[0] - n_)) % 360))
                    if "bottom hole coordinates" not in path_how:
                        path_how += ", then on to the bottom hole coordinates"
                else:                                # hold the last station's line
                    i, a = math.radians(inc), math.radians(az)
                    traj.append((bottom, tvd + dm * math.cos(i), n_ + dm * math.sin(i) * math.cos(a), e_ + dm * math.sin(i) * math.sin(a), inc, az))
        else:
            traj = [(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), (td, td, 0.0, 0.0, 0.0, 0.0)]
        # the check: the bottom hole, from the surface and the path, against the
        # location the header gives it (where neither was made from the other)
        if traj0 and tgt and not path_how.endswith("toward the bottom hole location") and not how.startswith("bottom hole"):
            k = math.cos(math.radians(lat0))
            miss = _dist((lon0 + traj[-1][3] / (111320 * k), lat0 + traj[-1][2] / 111320), (tgt[1], tgt[0]))
            (est_checks if stated else checks).append(miss)
            if args.debug and miss > 1000:
                with open(args.debug, "a") as dbg:
                    dbg.write(json.dumps({"miss": round(miss), "how": how, "path": path_how, "end": [round(traj[-1][2]), round(traj[-1][3])],
                                          "loc": header.get("location"), "sfco": header.get("surface_coordinates"),
                                          "bhco": header.get("bottom_hole_coordinates"), "target": bhl, "surf": skey}) + "\n")
        k = math.cos(math.radians(lat0))
        trajectory = {"md": [round(t[0], 1) for t in traj], "inc": [round(t[4], 2) for t in traj], "az": [round(t[5], 2) for t in traj],
                      "tvd": [round(t[1], 1) for t in traj], "ns": [round(t[2], 1) for t in traj], "ew": [round(t[3], 1) for t in traj],
                      "lat": [round(lat0 + t[2] / 111320, 6) for t in traj], "lon": [round(lon0 + t[3] / (111320 * k), 6) for t in traj]}
        heel = heel_of(traj)
        wells.append({
            "key": key, "lat": lat0, "lon": lon0, "types": types, "rock_names": rock_names, "notes": sorted(set(notes)),
            "well": {"name": name, "licence": key if not key.startswith("~") else "", "uwi": header.get("well_id") or "",
                     "prov": "SK", "td_m": round(td, 1), "tvd_m": round(max(t[1] for t in traj), 1),
                     "lateral_m": round(traj[-1][0] - heel) if heel is not None else 0, "heel_md": round(heel, 1) if heel is not None else None,
                     "year": year_of(header.get("spud_date"), header.get("completion_date")),
                     "lat": round(lat0, 6), "lon": round(lon0, 6), "elev_m": metres(header.get("kb_elevation")),
                     "ground_m": metres(header.get("ground_elevation")),
                     "surface_loc": dls_text(skey), "placed_by": how, "path_from": path_how or ("vertical" if vertical else None),
                     "path_estimated": bool(stated), "operator": header.get("operator") or "",
                     "formation": header.get("formation") or "", "curves": 0, "logs": 1, "vertical": vertical},
            "trajectory": trajectory, "stages": [], "depth_intervals": [], "logs": logs_out})
    print("%d wells placed; left out: %s" % (len(wells), dict(skipped)), file=sys.stderr)
    for label, cs in (("surveyed", checks), ("estimated from stated depths", est_checks)):
        if cs:
            cs.sort()
            print("bottom hole vs its own location's LSD centre, %d %s wells: median %.0f m, 90th %.0f m, %d over 1 km"
                  % (len(cs), label, cs[len(cs) // 2], cs[int(.9 * (len(cs) - 1))], sum(1 for c in cs if c > 1000)), file=sys.stderr)
    stat = lambda cs: {"wells": len(cs), "median": round(cs[len(cs) // 2]) if cs else None,
                       "p90": round(cs[int(.9 * (len(cs) - 1))]) if cs else None, "over_1km": sum(1 for c in cs if c > 1000)}
    skipped_checks = {"bottom_hole_check_m": stat(checks), "bottom_hole_check_estimated_m": stat(est_checks)}
    skipped = dict(skipped, **skipped_checks)
    write(args.out, wells, skipped)


# ---------------------------------------------------------------- output

def pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))] if s else None


SIG = 4     # significant figures a log's binned values keep in a pad file (they colour wells; the LAS keeps the rest)


def sig(v, n=SIG):
    """v to n significant figures (None, ints and zero as they are)"""
    if not isinstance(v, float) or v == 0 or not math.isfinite(v):
        return v
    r = round(v, n - 1 - int(math.floor(math.log10(abs(v)))))
    return int(r) if r == int(r) and abs(r) < 1e15 else r


def compact_well(w):
    """a well as a pad file holds it: log values to SIG figures, and a
    stage's or interval's empty fields left out (the pages read a missing
    field as they read null)"""
    logs = w["logs"]
    if logs:
        logs = dict(logs, types={k: (arr if k in ("rock", "show") else [sig(v) for v in arr])
                                 for k, arr in logs["types"].items()})
    drop = lambda rows: [{k: v for k, v in r.items() if v is not None} for r in rows]
    return {"well": w["well"], "trajectory": w["trajectory"], "stages": drop(w["stages"]),
            "depth_intervals": drop(w["depth_intervals"]), "logs": logs}


def write(out, wells, skipped, name="Saskatchewan (WellSight logs)",
          source="WellSight mud logs (private, local only); placed on SaskGrid 2015 sections"):
    """a well's "logs" may be None: a well with a path and no log"""
    # pads: surface holes within PAD_M of each other (the first pad made that is
    # near enough; pads looked up by a grid of PAD_M cells)
    wells.sort(key=lambda w: (w["lat"], w["lon"]))
    pads, cells = [], defaultdict(list)
    cell = lambda lat, lon: (int(math.floor(lat * 111320 / PAD_M)), int(math.floor(lon * 111320 * 0.62 / PAD_M)))
    for w in wells:
        k = math.cos(math.radians(w["lat"]))
        cy, cx = cell(w["lat"], w["lon"])
        near = [p for dy in (-1, 0, 1) for dx in (-2, -1, 0, 1, 2) for p in cells.get((cy + dy, cx + dx), ())
                if math.hypot((p["lat"] - w["lat"]) * 111320, (p["lon"] - w["lon"]) * 111320 * k) <= PAD_M]
        if near:
            min(near, key=lambda p: p["i"])["wells"].append(w)
        else:
            p = {"lat": w["lat"], "lon": w["lon"], "wells": [w], "i": len(pads)}
            pads.append(p)
            cells[(cy, cx)].append(p)
    # ids: SK + licence (a well), sk-<lowest licence> (a pad)
    seen = Counter()
    for p in pads:
        for w in p["wells"]:
            base = "SK" + re.sub(r"[^A-Z0-9]", "", w["key"].upper())[:24]
            seen[base] += 1
            w["well"]["wa"] = base if seen[base] == 1 else "%s-%d" % (base, seen[base])
    # a pad's id is its lowest well's licence, as a BC pad's is its lowest WA:
    # the same pad keeps it from one build to the next
    pads.sort(key=lambda p: min(w["well"]["wa"] for w in p["wells"]))
    for p in pads:
        p["id"] = "sk-" + min(w["well"]["wa"] for w in p["wells"])[2:].lower()
        ws_ = p["wells"]
        p["lat"] = sum(w["lat"] for w in ws_) / len(ws_)
        p["lon"] = sum(w["lon"] for w in ws_) / len(ws_)
        p["name"] = ws_[0]["well"]["surface_loc"] or p["id"]
    # the log types, their names and their scales across every well
    types, values = {}, defaultdict(list)
    rock_m, rock_names = Counter(), {}
    for p in pads:
        for w in p["wells"]:
            for k, t in w["types"].items():
                types.setdefault(k, {"t": t["t"], "u": t["u"], "wells": 0})
            rock_names.update(w["rock_names"])
            for k, arr in ((w["logs"] or {}).get("types") or {}).items():
                if k in types:
                    types[k]["wells"] += 1
                if k == "rock":
                    rock_m.update(x for x in arr if x)
                elif k not in ("show",):
                    values[k].extend(v for v in arr if v is not None)
    for k in ("rock", "por", "show"):
        n = sum(1 for p in pads for w in p["wells"] if k in ((w["logs"] or {}).get("types") or {}))
        if n:
            types[k] = {"t": {"rock": "Rock type", "por": "Porosity", "show": "Oil show"}[k], "u": "%" if k == "por" else "", "wells": n}
    scales = {}
    for k, vals in values.items():
        if len(vals) >= 20:
            lo, mid, hi = pct(vals, .02), pct(vals, .5), pct(vals, .98)
            if hi > lo:
                scales[k] = {"lo": round(lo, 3), "p50": round(mid, 3), "hi": round(hi, 3)}
    # rocks as an index into one list, the commonest first
    rocks = [r for r, _ in rock_m.most_common()]
    rix = {r: i for i, r in enumerate(rocks)}
    for p in pads:
        for w in p["wells"]:
            arr = ((w["logs"] or {}).get("types") or {}).get("rock")
            if arr:
                w["logs"]["types"]["rock"] = [rix[x] if x else None for x in arr]
    os.makedirs(os.path.join(out, "pads"), exist_ok=True)
    os.makedirs(os.path.join(out, "wells"), exist_ok=True)
    dump = lambda path, obj: json.dump(obj, open(os.path.join(out, path), "w"), separators=(",", ":"))
    for p in pads:
        dump("pads/%s.json" % p["id"], {"id": p["id"], "name": p["name"], "lat": round(p["lat"], 6), "lon": round(p["lon"], 6), "set": "sk",
                                         "wells": [compact_well(w) for w in p["wells"]]})
        for w in p["wells"]:
            dump("wells/%s.json" % w["well"]["wa"], {"well": w["well"], "pad": {"id": p["id"], "name": p["name"]}, "stages": [], "units": {},
                                                    "log_notes": w["notes"]})
    def plan_path(w):
        t = w["trajectory"]
        n = len(t["md"])
        idx = sorted(set([0, n - 1] + [int(i * (n - 1) / 23) for i in range(24)]))
        return [[t["lon"][i], t["lat"][i]] for i in idx]
    years = lambda p: [y for y in (w["well"]["year"] for w in p["wells"]) if y]
    lat_c = sum(p["lat"] for p in pads) / max(1, len(pads))
    lon_c = sum(p["lon"] for p in pads) / max(1, len(pads))
    dump("pads.json", {"v": 1, "set": "sk", "pads": [
        {"id": p["id"], "name": p["name"], "lat": round(p["lat"], 6), "lon": round(p["lon"], 6), "wells": [
            {"wa": w["well"]["wa"], "name": w["well"]["name"], "uwi": w["well"]["uwi"], "td": w["well"]["td_m"], "tvd": w["well"]["tvd_m"],
             "lateral": w["well"]["lateral_m"], "lat": w["well"]["lat"], "lon": w["well"]["lon"], "stations": len(w["trajectory"]["md"]),
             "path": plan_path(w), "stages": len(w["stages"]), "ports": 0, "logs": 1 if w["logs"] else 0, "ws": 1 if w["logs"] else 0,
             "depth_intervals": len(w["depth_intervals"]), "summaries": 0, "file": None}
            for w in p["wells"]]} for p in pads]})
    dump("index.json", {
        "v": 1, "set": "sk", "name": name, "center": [round(lat_c, 4), round(lon_c, 4)],
        "wells": sum(len(p["wells"]) for p in pads), "bin_m": BIN,
        "source": source,
        "left_out": dict(skipped), "types": types, "scales": scales,
        "rocks": [[r, rock_names.get(r) or r] for r in rocks],
        "pads": [{"id": p["id"], "name": p["name"], "set": "sk", "lat": round(p["lat"], 6), "lon": round(p["lon"], 6), "wells": len(p["wells"]),
                  "field": Counter(w["well"].get("pool") or "" for w in p["wells"]).most_common(1)[0][0],
                  "operator": Counter(w["well"]["operator"] for w in p["wells"]).most_common(1)[0][0],
                  "years": [min(years(p)), max(years(p))] if years(p) else None, "curves": 0,
                  "logs": sum(1 for w in p["wells"] if w["logs"]), "stages": sum(len(w["stages"]) for w in p["wells"])} for p in pads]})
    print("wrote %d pads, %d wells to %s" % (len(pads), sum(len(p["wells"]) for p in pads), out), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k, default=v)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="only the first N wells (by licence), for a quick look")
    ap.add_argument("--no-cells", action="store_true", help="skip the Porosity cells (no drive needed)")
    ap.add_argument("--debug", help="append the wells whose bottom hole misses its location by over 1 km to this file")
    args = ap.parse_args(argv)
    for k in ("out",):
        setattr(args, k, os.path.expanduser(getattr(args, k)))
    build(args)


if __name__ == "__main__":
    main()
