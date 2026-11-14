"""Read the printouts of the mudlog answer key with mudlog_pdf (the PDF
alone, with its own legend), to mark the reading against the key.

    python3 validation-tools/mudlog_pdf_read.py ~/dev/wellsight-answer-key /Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl OUT --jobs 6 --every 28
    python3 validation-tools/mudlog_key_score.py ~/dev/wellsight-answer-key OUT --parts header,text,rocks,symbols,intervals,curves,tracks

The key is used to find which printout to read and where to write the
reading, nothing else. OUT gets one JSON file per printout at the key's
path, and summary.json: how many were read, the notes, and the seconds.
Readings hold well names: OUT stays out of the repository.
"""
import argparse
import collections
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

SUFFIX = ".key.json.gz"


_LIBRARY = {}


def _one(args):
    key_path, root, out_path, parts, library = args
    if library and library not in _LIBRARY:
        with open(library, encoding="utf-8") as f:
            _LIBRARY[library] = json.load(f)
    import mudlog_key as K
    import mudlog_pdf as M
    t = time.time()
    try:
        key = K.load(key_path)
        po = key.get("printout") or {}
        if not po.get("file"):
            return out_path, "no printout", 0, []
        r = M.read(os.path.join(root, po["file"]), parts, _LIBRARY.get(library))
    except Exception as e:  # noqa: BLE001 - a reading that fails is a reading of nothing
        r = {"error": "%s: %s" % (type(e).__name__, e)}
    r["seconds"] = round(time.time() - t, 2)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(r, f)
    return out_path, ("error" if r.get("error") else "ok"), r["seconds"], r.get("notes") or [r.get("error")]


def keys_under(keys, every=1, limit=None, only_ok=True):
    import csv
    idx = os.path.join(keys, "index.csv")
    rels = None
    if only_ok and os.path.exists(idx):
        with open(idx, newline="", encoding="utf-8") as f:
            rels = {r["log"] for r in csv.DictReader(f) if r["status"] == "ok" and r["printout_ok"] == "True"}
    todo = []
    for dp, dirs, files in os.walk(keys):
        dirs.sort()
        for f in sorted(files):
            if f.endswith(SUFFIX):
                rel = os.path.relpath(os.path.join(dp, f), keys)[:-len(SUFFIX)]
                if rels is None or rel in rels:
                    todo.append((os.path.join(dp, f), rel))
    todo = todo[::every]
    return todo[:limit] if limit else todo


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keys")
    ap.add_argument("root", help="the folder the logs and printouts are in")
    ap.add_argument("out")
    ap.add_argument("--parts", help="comma-separated, of: header,text,rocks,symbols,curves (default all)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--every", type=int, default=1, help="read every n-th printout")
    ap.add_argument("--library", help="a legend library (pdf_legend_library.py) for pictures a legend leaves out")
    a = ap.parse_args(argv)
    keys, out, root = (os.path.expanduser(p) for p in (a.keys, a.out, a.root))
    parts = tuple(p.strip() for p in a.parts.split(",")) if a.parts else None
    lib = os.path.expanduser(a.library) if a.library else None
    todo = [(kp, root, os.path.join(out, rel + ".json"), parts, lib) for kp, rel in keys_under(keys, a.every, a.limit)]
    status, notes, secs = collections.Counter(), collections.Counter(), []
    t0 = time.time()
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(_one, t) for t in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            _p, st, s, ns = fu.result()
            status[st] += 1
            secs.append(s)
            for n in ns:
                if n:
                    notes[" ".join(w if not w.isdigit() else "N" for w in str(n).split())] += 1
            if i % 50 == 0:
                print(i, "/", len(todo), flush=True)
    summary = {"printouts": len(todo), "status": dict(status), "notes": dict(notes.most_common()),
               "seconds_median": sorted(secs)[len(secs) // 2] if secs else None,
               "seconds_total": round(time.time() - t0, 1)}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
