"""Bring lab_batch.py's exports into Stratum's well files.

    python3 web/scripts/import_lab.py --out ~/stratum-lab/clusters [--out <another>]

lab_batch.py writes <out>/<WA>/<pdf name>-seconds.csv for every completion
report it read. A well with several reports (a frac job and a tubing job, a
re-frac) has several; the one charting the most stages is the frac job and is
the one imported. The choice goes to a WA/WELL/FILE list and stages_from_csv.py
does the merge, exactly as it does for the Lab's own exports.
"""
import argparse
import csv
import glob
import json
import os
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WELLS = os.path.join(_REPO, "web", "public", "data", "wells")


def stage_count(path):
    labels = set()
    with open(path, newline="") as f:
        rd = csv.reader(f)
        head = next(rd, [])
        next(rd, None)
        i = head.index("LABEL") if "LABEL" in head else (head.index("STAGE") if "STAGE" in head else None)
        if i is None:
            return 0
        for row in rd:
            if len(row) > i and row[i]:
                labels.add(row[i])
    return len(labels)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", action="append", required=True)
    a = ap.parse_args()
    for out in a.out:
        rows = []
        for wa_dir in sorted(glob.glob(os.path.join(os.path.expanduser(out), "[0-9]" * 5))):
            wa = os.path.basename(wa_dir)
            cands = [(stage_count(p), p) for p in glob.glob(os.path.join(wa_dir, "*-seconds.csv"))]
            cands = [c for c in cands if c[0] > 0]
            path_w = os.path.join(_WELLS, f"{wa}.json")
            if not cands or not os.path.exists(path_w):
                continue
            best = max(cands)[1]
            name = json.load(open(path_w)).get("well", {}).get("name", "")
            rows.append((wa, name, os.path.basename(best)[:-len("-seconds.csv")] + ".pdf"))
        tsv = os.path.join(os.path.expanduser(out), "import.tsv")
        with open(tsv, "w") as f:
            f.write("WA\tWELL\tFILE\n" + "".join("\t".join(r) + "\n" for r in rows))
        print(f"{out}: {len(rows)} wells with a Lab export", flush=True)
        if rows:
            subprocess.run([sys.executable, os.path.join(_REPO, "stages_from_csv.py"),
                            "--folder", os.path.expanduser(out), "--cluster", tsv], cwd=_REPO, check=True)


if __name__ == "__main__":
    main()
