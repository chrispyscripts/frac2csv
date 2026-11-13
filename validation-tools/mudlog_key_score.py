"""Mark a PDF reader's output against the mudlog answer key.

    python3 validation-tools/mudlog_key_score.py ~/dev/wellsight-answer-key READER_OUT
    python3 validation-tools/mudlog_key_score.py KEYS READER_OUT --parts header,text --csv marks.csv

READER_OUT holds one JSON file per log the reader read, at the key's path
with ".key.json.gz" swapped for ".json" (or ".json.gz"), in the key's own
fields (see mudlog_key.py). Logs the reader has no file for are left out of
the marks and counted. --parts marks only the parts the reader tries.

Prints each part's mean mark over the logs, how many logs scored at least
0.9, and the worst few; --csv writes every log's marks.
"""
import argparse
import csv
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import mudlog_key as K          # noqa: E402

SUFFIX = ".key.json.gz"


def pairs(keys, cands):
    for dp, _dirs, files in os.walk(keys):
        for f in sorted(files):
            if not f.endswith(SUFFIX):
                continue
            rel = os.path.relpath(os.path.join(dp, f), keys)[:-len(SUFFIX)]
            for ext in (".json", ".json.gz"):
                c = os.path.join(cands, rel + ext)
                if os.path.exists(c):
                    yield rel, os.path.join(dp, f), c
                    break
            else:
                yield rel, os.path.join(dp, f), None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keys")
    ap.add_argument("reader_out")
    ap.add_argument("--parts", help="comma-separated: " + ",".join(n for n, _ in K.PARTS))
    ap.add_argument("--csv")
    ap.add_argument("--all", action="store_true", help="also mark logs whose printout the key doubts")
    ap.add_argument("--worst", type=int, default=5)
    a = ap.parse_args(argv)
    parts = tuple(p.strip() for p in a.parts.split(",")) if a.parts else None
    rows, missing, doubtful = [], 0, 0
    for rel, kp, cp in pairs(os.path.expanduser(a.keys), os.path.expanduser(a.reader_out)):
        if cp is None:
            missing += 1
            continue
        key = K.load(kp)
        if not (key.get("printout") or {}).get("ok") and not a.all:
            doubtful += 1
            continue
        s = K.score(key, K.load(cp), parts)
        row = {"log": rel, "overall": s["overall"]}
        for name, _f in K.PARTS:
            if name in s:
                row[name] = s[name]["score"] if s[name] else None
        rows.append(row)
    print("%d logs marked; %d with no reader output; %d left out, the key doubting the printout" % (
        len(rows), missing, doubtful))
    if not rows:
        return
    names = [n for n, _ in K.PARTS if n in rows[0]] + ["overall"]
    for n in names:
        v = [r[n] for r in rows if r.get(n) is not None]
        if v:
            print("  %-10s mean %.3f  median %.3f  >=0.9 on %d of %d" % (
                n, statistics.mean(v), statistics.median(v), sum(1 for x in v if x >= 0.9), len(v)))
    worst = sorted((r for r in rows if r["overall"] is not None), key=lambda r: r["overall"])[:a.worst]
    if worst:
        print("worst:")
        for r in worst:
            print("  %.3f  %s" % (r["overall"], r["log"]))
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, ["log"] + names)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
