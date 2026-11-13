"""Where each of a WellSight log's tracks lies on its stitched printout.

The log file stores its layout: one record per track, in order across the
log, each with its title, its printed width in inches and whether it is shown
(a hidden track takes no room on the printout). The columns a track holds
(Oil Shows, Porosity Type, Geol. Descrs., Eng. Data, ...) follow its record.

The printout draws every shown track between long dark lines that run the
length of the log. So the layout is laid down on those lines, starting from
the curve track (found on the printout by its coloured strokes, see
wellsight_print.curve_track) and walking outward through the shown tracks,
each one's far edge snapped to the line at its width. A horizontal log's
pages are turned to stitch them, so its tracks run the other way across the
strip; both ways are tried and the one whose edges land on lines is kept.

A track whose record cannot be read whole (its title and width are not where
they are in the others; two of the drive's samples have one each, the
lithology track of a strip log and the cross-section of a horizontal log)
is taken as shown, and its far edge is the line after which the next track
of known width fits.

Lab data sets are matched to tracks by the names of the columns the track
holds, and by its title: the Oil shows set to the track holding the "Oil
Shows" column, the descriptions to the one holding "Geol. Descrs.".
"""
import collections
import os
import re
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wellsight_convert")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import wellsight as ws        # noqa: E402

import log_vocab as V         # noqa: E402

# A data set's group -> the column names (lower case) that hold it
# (log_vocab.txt [column]).
GROUP_COLUMNS = {e.key: tuple(s.strip().lower() for s in e.spellings) for e in V.entries("column")}
_ACCESSORY = ("mineral", "fossil", "stringer", "texture")
SNAP_PT = 2.0                   # how far a track's edge may land from a line


def _good_title(t):
    return bool(t) and bool(re.search(r"[A-Za-z]{2}", t)) and all(c.isprintable() for c in t)


def read_tracks(raw):
    """The log's tracks in order across the log:
    [{title, width_in (None if unreadable), shown (True/False/None), columns}]."""
    body, _ = ws.inflate(raw, [])
    recs = ws.tracks(body)
    out = []
    for off, _tid, title in recs:
        w = ws.track_width(body, off)
        ok = w is not None and _good_title(title)
        shown = None
        if ok:
            flag = body[off - 11]          # the byte after the width: 1 shown, 0 hidden
            shown = True if flag == 1 else False if flag == 0 else None
        out.append({"title": title if ok else "", "width_in": w if ok else None,
                    "shown": shown, "columns": [], "offset": off})
    for coff, name in ws.columns(body):
        owner = None
        for t in out:
            if t["offset"] < coff:
                owner = t
            else:
                break
        if owner is not None and name not in owner["columns"]:
            owner["columns"].append(name)
    for t in out:
        del t["offset"]
    return out


def keys_of(track, curve_title=None):
    """The data-set keys a track answers for."""
    names = {c.strip().lower() for c in track["columns"]}
    title = (track["title"] or "").strip().lower()
    keys = []
    if curve_title is not None and track["title"] == curve_title:
        keys.append("curves")
    for k, cols in GROUP_COLUMNS.items():
        if names & set(cols) or title in cols:
            keys.append(k)
    if title == "depth":
        keys += ["depth", "interval"]  # cores and tests are drawn in the depth track
    if "%" in title and "lith" in title:
        keys.append("pct")
    elif "lith" in title or any(k in keys for k in _ACCESSORY):
        keys.append("rock")          # the lithology track carries the accessories
    if "descr" in title or "geolog" in title:
        keys.append("descriptions")
    return sorted(set(keys))


def _label(track):
    if track["title"]:
        return track["title"]
    names = {c.strip().lower() for c in track["columns"]}
    acc = bool(names & set(_ACCESSORY))
    if acc and names & set(GROUP_COLUMNS["descriptions"]):
        return "Lithology and descriptions"
    if acc:
        return "Lithology"
    names = [c for c in track["columns"] if c.lower() != "column 1"]
    return ", ".join(names[:4]) if names else "Untitled track"


def place(tracks, lines, curves_pt, width_pt, curve_title=None):
    """Lay the shown tracks on the strip.

    tracks: read_tracks() output. lines: x of the long dark lines across the
    strip (wellsight_print.track_lines). curves_pt: (x0, x1) of the curve
    track on the strip. width_pt: the strip's width. curve_title: the title
    of the track the curves are in (the curves' own record says), if known.

    -> [{title, x0, x1, columns, keys, snapped, clipped}] left to right; the
    tracks the printout leaves off its page are not in it."""
    if not tracks or not curves_pt:
        return []
    lines = sorted(lines)
    c0, c1 = curves_pt
    kc = None
    if curve_title:
        kc = next((i for i, t in enumerate(tracks) if t["title"] == curve_title), None)
    if kc is None:                 # by width: the shown track as wide as the curve track
        best = None
        for i, t in enumerate(tracks):
            if t["shown"] and t["width_in"]:
                d = abs(t["width_in"] * 72 - (c1 - c0))
                if d < 4 and (best is None or d < best[0]):
                    best = (d, i)
        kc = best[1] if best else None
    if kc is None:
        return []
    ct = tracks[kc]
    scale = (c1 - c0) / (ct["width_in"] * 72) if ct["width_in"] else 1.0
    if not 0.8 < scale < 1.25:
        scale = 1.0

    def snap(x):
        best = min(lines, key=lambda v: abs(v - x), default=None)
        return best if best is not None and abs(best - x) <= SNAP_PT else None

    def walk(order, pos, d):
        out = []
        for i, t in enumerate(order):
            if t["shown"] is False:
                continue
            if t["width_in"] is not None:
                tgt = pos + d * t["width_in"] * 72 * scale
                hit = snap(tgt)
                edge, ok = (hit, True) if hit is not None else (tgt, False)
            else:
                nxt = next((u for u in order[i + 1:] if u["shown"] and u["width_in"]), None)
                edge, ok = None, False
                ahead = [v for v in lines if (v - pos) * d > 6]
                ahead.sort(key=lambda v: abs(v - pos))
                if nxt is not None:
                    for v in ahead:
                        if snap(v + d * nxt["width_in"] * 72 * scale) is not None:
                            edge, ok = v, True
                            break
                if edge is None:
                    edge = width_pt if d > 0 else 0.0
                    ok = nxt is None
            out.append((t, min(pos, edge), max(pos, edge), ok))
            pos = edge
        return out

    after, before = tracks[kc + 1:], tracks[:kc][::-1]
    best = None
    for d in (1, -1):              # file order left to right, or turned the other way
        placed = walk(after, c1 if d > 0 else c0, d) + walk(before, c0 if d > 0 else c1, -d)
        score = sum(1 for p in placed if p[3] and -1 <= p[1] and p[2] <= width_pt + 1)
        if best is None or score > best[0]:
            best = (score, placed)
    placed = [(ct, c0, c1, True)] + best[1]
    out = []
    for t, a, b, ok in placed:
        x0, x1 = max(0.0, a), min(width_pt, b)
        if x1 - x0 < 2:            # off the printed page
            continue
        out.append({"title": _label(t), "x0": round(x0, 1), "x1": round(x1, 1),
                    "columns": t["columns"], "keys": keys_of(t, ct["title"]) if t is not ct
                    else sorted(set(keys_of(t, ct["title"]) + ["curves"])),
                    "snapped": bool(ok), "clipped": x0 > a + 1 or x1 < b - 1})
    out.sort(key=lambda r: r["x0"])
    return out


def curve_track_title(curves):
    """The title of the track most of the log's curves are drawn in."""
    c = collections.Counter(x.get("track") for x in curves or [] if x.get("track"))
    return c.most_common(1)[0][0] if c else None
