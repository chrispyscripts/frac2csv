"""Mark the notes a printout's export writes (notes.csv) against the mudlog
answer key's notes.

    python3 validation-tools/mudlog_notes_score.py ~/dev/wellsight-answer-key READER_OUT
    python3 validation-tools/mudlog_notes_score.py KEYS READER_OUT --csv notes-marks.csv --jobs 4

READER_OUT is a mudlog_pdf_read.py run with the text part read. Each log's
lines are put together as the export puts them (mudlog_pdf_app._notes) and
each note in the key (written in its log, a note of at least two letters or
digits) is looked for among the notes starting within a metre of it: its
mark is the share of its characters the best of them holds in order, case
and spaces aside. A note that comes back whole marks 1; one run together
with the next still marks 1 for the first and nothing for the second.

Prints, over all logs and by the key's top folder (HLG laterals, SLG
builds), the share of notes that come back whole (>= 0.98) and nearly
(>= 0.9), the share of all their characters found, and the share of what
the export writes that the key holds (survey labels and other text the log
draws but does not keep as a note count against it).
"""
import argparse
import bisect
import collections
import csv
import difflib
import gzip
import json
import multiprocessing
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

SUFFIX = ".key.json.gz"
WINDOW = 1.0


def _load(p):
    with (gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else open(p, encoding="utf-8")) as f:
        return json.load(f)


def _squash(s):
    return re.sub(r"\s+", "", str(s or "").lower())


def _held(a, b):
    """the share of a's characters b holds in order"""
    if not a:
        return 0.0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(x.size for x in m.get_matching_blocks()) / len(a)


def mark(key, reading):
    """-> ([(column, mark, characters)] for the key's notes, [(mark, characters)] for the export's)"""
    import mudlog_pdf_app as A
    rows = A._notes(reading.get("text"), reading.get("tracks"), reading.get("printout"), reading.get("curves"))
    rd = [n["depth"] for n in rows]
    kn = [t for t in key.get("text") or []
          if len(re.sub(r"[^a-z0-9]", "", t["text"].lower())) >= 2 and len(t["text"]) <= 2500]
    ks = sorted((t["depth"], _squash(t["text"])) for t in kn)
    kd = [d for d, _ in ks]
    notes = []
    for t in kn:
        kt = _squash(t["text"])
        best = max((_held(kt, _squash(rows[j]["text"]))
                    for j in range(bisect.bisect_left(rd, t["depth"] - WINDOW), bisect.bisect_right(rd, t["depth"] + WINDOW))),
                   default=0.0)
        notes.append((t.get("column") or "", best, len(kt)))
    written = []
    for n in rows:
        rt = _squash(n["text"])[:3000]
        best = max((_held(rt, ks[j][1])
                    for j in range(bisect.bisect_left(kd, n["depth"] - 1.5), bisect.bisect_right(kd, n["depth"] + 1.5))),
                   default=0.0)
        written.append((best, len(rt)))
    return notes, written


def _one(args):
    rel, kp, cp = args
    notes, written = mark(_load(kp), _load(cp))
    return rel, notes, written


def pairs(keys, out):
    for dp, _dirs, files in os.walk(keys):
        for f in sorted(files):
            if f.endswith(SUFFIX):
                rel = os.path.relpath(os.path.join(dp, f), keys)[:-len(SUFFIX)]
                for ext in (".json", ".json.gz"):
                    c = os.path.join(out, rel + ext)
                    if os.path.exists(c):
                        yield rel, os.path.join(dp, f), c
                        break


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keys")
    ap.add_argument("reader_out")
    ap.add_argument("--csv", help="every key note's mark")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    todo = list(pairs(os.path.expanduser(a.keys), os.path.expanduser(a.reader_out)))
    with multiprocessing.Pool(a.jobs) as pool:
        done = pool.map(_one, todo, chunksize=4)
    groups, wrote = collections.defaultdict(list), collections.defaultdict(list)
    for rel, notes, written in done:
        top = rel.split("/")[0] if "/" in rel else ""
        for g in ("all", top):
            groups[g] += [(m, n) for _c, m, n in notes]
            wrote[g] += written
    print("%d logs; %d notes in the key" % (len(done), len(groups["all"])))
    for g in ["all"] + sorted(k for k in groups if k not in ("all", "")):
        v, w = groups[g], wrote[g]
        if not v:
            continue
        chars = sum(n for _m, n in v)
        print("  %-5s notes %6d  whole %.3f  nearly %.3f  characters %.3f  written held by the key %.3f" % (
            g, len(v), sum(m >= 0.98 for m, _n in v) / len(v), sum(m >= 0.9 for m, _n in v) / len(v),
            sum(m * n for m, n in v) / chars, sum(m * n for m, n in w) / max(1, sum(n for _m, n in w))))
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            cw = csv.writer(f)
            cw.writerow(["log", "column", "mark", "characters"])
            for rel, notes, _w in done:
                for col, m, n in notes:
                    cw.writerow([rel, col, round(m, 4), n])


if __name__ == "__main__":
    main()
