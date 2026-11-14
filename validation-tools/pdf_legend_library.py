"""A library of legend pictures from many printouts: what each picture
means, by the exact picture, as the printouts' own legends label it.

    python3 validation-tools/pdf_legend_library.py /Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl ~/dev/mudlog-legend-library.json --keys ~/dev/wellsight-answer-key --jobs 7 --every 4

A printout whose legend leaves a picture out (a TVD gamma log prints no
legend at all; some legends hold only the rocks) can still have it named:
mudlog_pdf.read(pdf, library=...) looks a picture up here when its own
legend does not hold it. Only pictures the legends agree on are kept: seen
in at least --min-seen printouts, labelled alike in at least --agree of
them.

The library is pictures' checksums and their labels, taken from client
printouts: it stays out of the repository.
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


def legend_pages(doc, most=6):
    """the pages up to and including the first that carries a run of depth
    labels: the legend comes before the log or at its start"""
    import wellsight_print as wp
    out = []
    for i, pg in enumerate(doc):
        out.append(i)
        ax = wp.page_axis(pg, 1, 99999)
        if (ax and len(ax[3]) >= 3) or len(out) >= most:
            break
    return out


def one(path):
    import fitz
    import pdf_legend as L
    try:
        doc = fitz.open(path)
        sw = L.legend(doc, legend_pages(doc))
    except Exception as e:  # noqa: BLE001 - a printout that cannot be read adds nothing
        return path, [], str(e)
    seen = {}
    for s in sw:
        if s.term and s.digest:
            seen[s.digest.hex()] = (s.group, s.term, s.label, list(s.px))
    return path, list(seen.items()), None


def printouts(root, every, keys=None):
    """the printouts under root, or (keys: an answer key folder) the ones
    its index names: one per log, not the stitched and turned copies a
    drive may hold beside them"""
    out = []
    if keys:
        import csv
        with open(os.path.join(keys, "index.csv"), newline="", encoding="utf-8") as f:
            out = sorted(os.path.join(root, r["printout"]) for r in csv.DictReader(f) if r.get("printout"))
    else:
        for dp, dirs, files in os.walk(root):
            dirs.sort()
            for f in sorted(files):
                if f.lower().endswith(".pdf"):
                    out.append(os.path.join(dp, f))
    return out[::every]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", help="a folder of printouts (searched below)")
    ap.add_argument("out", help="the library file to write (JSON)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--keys", help="an answer key folder: read the printouts its index names")
    ap.add_argument("--min-seen", type=int, default=3)
    ap.add_argument("--agree", type=float, default=0.8)
    a = ap.parse_args(argv)
    paths = printouts(os.path.expanduser(a.root), a.every, os.path.expanduser(a.keys) if a.keys else None)
    votes = collections.defaultdict(collections.Counter)
    px = {}
    errors = 0
    t0 = time.time()
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(one, p) for p in paths]
        for i, fu in enumerate(as_completed(futs), 1):
            _p, items, err = fu.result()
            errors += err is not None
            for dig, (g, t, label, size) in items:
                votes[dig][(g, t)] += 1
                px[dig] = size
            if i % 200 == 0:
                print(i, "/", len(paths), flush=True)
    lib, split = {}, 0
    for dig, c in votes.items():
        (g, t), n = c.most_common(1)[0]
        total = sum(c.values())
        if total >= a.min_seen and n >= a.agree * total:
            lib[dig] = {"group": g, "term": t, "seen": total, "px": px[dig]}
        elif total >= a.min_seen:
            split += 1
    out = {"schema": "frac2csv/legend-library/1", "printouts": len(paths), "unreadable": errors,
           "pictures": len(lib), "left_out_disagreeing": split, "seconds": round(time.time() - t0, 1),
           "by_digest": lib}
    with open(os.path.expanduser(a.out), "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(json.dumps({k: v for k, v in out.items() if k != "by_digest"}, indent=1))


if __name__ == "__main__":
    main()
