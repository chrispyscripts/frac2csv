"""The plainest PDF reader there is, to mark against the mudlog answer key:
the header and the notes, read straight off the printout's text layer.

    python3 validation-tools/mudlog_text_baseline.py ~/dev/wellsight-answer-key /Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl OUT --jobs 6
    python3 validation-tools/mudlog_key_score.py ~/dev/wellsight-answer-key OUT --parts header,text

It reads the PDF only, with mudlog_pdf's header and text reading (see
there). The key is used to find which printout to read and where to write
the reading, nothing else.

What it marks is what a reader gets for nothing; the curves, rocks and
symbols, which are drawing and not text, it does not try.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

SUFFIX = ".key.json.gz"


def read(pdf_path):
    """the header and the notes only (mudlog_pdf reads the rest too)"""
    import mudlog_pdf as M
    r = M.read(pdf_path, parts=("header", "text"))
    r["reader"] = "text-layer baseline"
    return r


def _one(args):
    key_path, root, out_path = args
    import mudlog_key as K
    t = time.time()
    try:
        key = K.load(key_path)
        po = key.get("printout") or {}
        if not po.get("file"):
            return out_path, "no printout", 0
        r = read(os.path.join(root, po["file"]))
    except Exception as e:  # noqa: BLE001 - a reading that fails is a reading of nothing
        r = {"error": "%s: %s" % (type(e).__name__, e)}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(r, f)
    return out_path, r.get("error", "ok"), round(time.time() - t, 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keys")
    ap.add_argument("root", help="the folder the logs and printouts are in")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--every", type=int, default=1, help="read every n-th log")
    a = ap.parse_args(argv)
    keys, out = os.path.expanduser(a.keys), os.path.expanduser(a.out)
    todo = []
    for dp, dirs, files in os.walk(keys):
        dirs.sort()
        for f in sorted(files):
            if f.endswith(SUFFIX):
                rel = os.path.relpath(os.path.join(dp, f), keys)[:-len(SUFFIX)]
                todo.append((os.path.join(dp, f), os.path.expanduser(a.root), os.path.join(out, rel + ".json")))
    todo = todo[::a.every][:a.limit] if a.limit else todo[::a.every]
    done = {}
    with ProcessPoolExecutor(a.jobs) as ex:
        for fu in as_completed([ex.submit(_one, t) for t in todo]):
            _p, status, _s = fu.result()
            done[status if status in ("ok", "no printout") else "error"] = done.get(
                status if status in ("ok", "no printout") else "error", 0) + 1
    print(len(todo), "printouts read:", done)


if __name__ == "__main__":
    main()
