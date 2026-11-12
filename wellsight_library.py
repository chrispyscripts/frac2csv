"""The printouts already on disk, found for a log by its name.

The WellSight drive keeps LogViewer printouts beside the logs: HLG\\Pdf and
SLG\\PDF-with-PNG hold the prints as LogViewer made them (Microsoft Print to
PDF, one Letter page after another), named like the log they print
("0005--07I231_LP-LAT_LEG_1.hl6" -> "0005--07I231_LP-LAT_LEG_1.pdf"). Deeper
folders hold the hand-made versions: pages turned (".pdf.pdf"), stacked into
one page ("_stitched"), turned again ("_stitched_rot270"), and SVGs.

So the Lab is pointed at one folder -- the one that holds all of those
(Settings, WellSight printouts) -- and every PDF under it is indexed once. A
log dropped on the Lab then takes its printout from there: the print as
LogViewer made it first, since the stitch places each of its pages by its
own depth labels; a turned copy next; a hand-stacked one only when nothing
else is there.

With no folder set, a "SK-VIKING\\WellSight" folder at the top of any drive is
used if there is one.
"""
import os
import re
import sys
import threading
import time

_LOCK = threading.Lock()
_INDEX = {}                     # folder -> index
_ID = re.compile(r"^(\d{3,5})--")
_EXTS = (".pdf", ".hl6", ".hlg", ".sl6", ".slg", ".hl8", ".sl8", ".ml6", ".mlg", ".ml8")
KIND_RANK = {"print": 0, "turned": 1, "stacked": 2}


def stem(name):
    """The name a log and its printouts share, lower case, with the
    extensions and the hand-stitching suffixes taken off."""
    n = os.path.basename(str(name)).lower()
    while True:              # "x.pdf_stitched_rot270.pdf" -> "x"
        b, e = os.path.splitext(n)
        if e in _EXTS:
            n = b
            continue
        m = re.sub(r"_stitched(_rot\d+)?$", "", n)
        if m != n:
            n = m
            continue
        break
    return n


def kind(path):
    b = os.path.basename(path).lower()
    if "_stitched" in b:
        return "stacked"            # pages laid end to end by hand
    if b.endswith(".pdf.pdf"):
        return "turned"             # each page turned a quarter
    return "print"                  # as LogViewer printed it


def _walk(folder):
    by_stem, by_id = {}, {}
    n = 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() != "svg"]
        for f in files:
            if f.startswith("._") or not f.lower().endswith(".pdf"):
                continue
            p = os.path.join(root, f)
            s = stem(f)
            by_stem.setdefault(s, []).append(p)
            m = _ID.match(s)
            if m:
                by_id.setdefault(m.group(1), []).append(p)
            n += 1
    return by_stem, by_id, n


def index(folder, refresh=False):
    """{folder, pdfs, prints, at, seconds} for the folder, walked once and
    kept; refresh walks it again."""
    folder = os.path.abspath(folder)
    with _LOCK:
        ix = _INDEX.get(folder)
        if ix and not refresh:
            return ix
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"{folder} is not a folder on this computer"
                                + (" (is the drive plugged in?)" if _on_removable(folder) else ""))
    t = time.time()
    by_stem, by_id, n = _walk(folder)
    ix = {"folder": folder, "by_stem": by_stem, "by_id": by_id, "pdfs": n,
          "prints": sum(1 for ps in by_stem.values() for p in ps if kind(p) == "print"),
          "at": time.strftime("%Y-%m-%d %H:%M"), "seconds": round(time.time() - t, 1)}
    with _LOCK:
        _INDEX[folder] = ix
    return ix


def summary(ix):
    return {k: ix[k] for k in ("folder", "pdfs", "prints", "at", "seconds")}


def _on_removable(folder):
    return folder.startswith("/Volumes/") or (len(folder) > 1 and folder[1] == ":"
                                               and folder[0].upper() not in "C")


def find(ix, log_name):
    """The best printout for a log in the index: (path, kind) or (None, why)."""
    s = stem(log_name)
    cands = list(ix["by_stem"].get(s, []))
    if not cands:
        # the corpus numbers every log ("0005--"); a renamed log still has its number
        m = _ID.match(s)
        same = ix["by_id"].get(m.group(1), []) if m else []
        prints = [p for p in same if kind(p) == "print"]
        cands = prints if len(prints) == 1 else []
    if not cands:
        return None, f'no printout named "{s}.pdf" under {ix["folder"]}'
    cands.sort(key=lambda p: (KIND_RANK[kind(p)], p.count(os.sep), len(p)))
    return cands[0], kind(cands[0])


# The drive letters worth looking at. localapp sets this to its own list,
# which skips letters with no device and network drives that would hang.
DRIVE_LETTERS = None


def default_folder():
    """A SK-VIKING\\WellSight folder at the top of any drive, or None."""
    names = (os.path.join("SK-VIKING", "WellSight"), "WellSight")
    roots = []
    if sys.platform == "win32":
        letters = DRIVE_LETTERS() if DRIVE_LETTERS else []
        roots = [f"{d}:\\" for d in letters if d not in ("A", "B")]
    elif sys.platform == "darwin":
        try:
            roots = [os.path.join("/Volumes", v) for v in os.listdir("/Volumes")]
        except OSError:
            roots = []
    for r in roots:
        for n in names:
            p = os.path.join(r, n)
            try:
                if os.path.isdir(p):
                    return p
            except OSError:
                continue
    return None
