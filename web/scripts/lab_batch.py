"""Run the Lab over completion-report PDFs, headless and resumable.

    python3 web/scripts/lab_batch.py --lab <Lab checkout> --jobs jobs.tsv --out <dir> [--workers 4]

jobs.tsv has a header and one row per PDF: WA <tab> PDF path. A well can have
several PDFs (a frac report and a tubing job, say); each is read, and
stages_from_csv later takes the export with the most stages.

Every PDF goes through localapp.process_path -- the desktop Lab's own read and
export, from the checkout passed as --lab, so a batch is pinned to one Lab
release -- in a process of its own with a time limit, writing
<out>/<WA>/<pdf name>-seconds.csv plus the stage tables the Lab finds. A PDF
leaves a .done marker (status, stages, seconds taken) whether or not it read,
so a batch stopped at any point picks up where it left off. One line per PDF
goes to <out>/progress.log. A PDF over the time limit (--limit, 1800 s) is
marked timed out; run again with --retry-timeouts and a longer --limit to
give those another go.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

LIMIT_S = 1800          # a PDF that takes longer than this is recorded as timed out


def one(lab, pdf, out_dir):
    """Child process: read one PDF with the Lab, export beside nothing but out_dir."""
    sys.path.insert(0, lab)
    os.chdir(lab)
    import localapp
    t0 = time.time()
    stages, tables, notes, written, summary, folder = localapp.process_path(pdf, fmt="csv", dest_folder=out_dir)
    print(json.dumps({"status": "ok", "stages": len(stages), "tables": len(tables), "written": written,
                      "seconds": round(time.time() - t0, 1)}))


def done(args, marker):
    """A PDF already tried; with --retry-timeouts one that ran out of time isn't."""
    if not os.path.exists(marker):
        return False
    if args.retry_timeouts:
        try:
            return json.load(open(marker)).get("status") != "timeout"
        except ValueError:
            return False
    return True


def run(args, row):
    wa, pdf = row
    out_dir = os.path.join(args.out, wa)
    base = os.path.splitext(os.path.basename(pdf))[0]
    marker = os.path.join(out_dir, base + ".done")
    if done(args, marker):
        return None
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, __file__, "--one", pdf, "--lab", args.lab, "--out", out_dir],
                           capture_output=True, text=True, timeout=args.limit)
        last = (p.stdout.strip().splitlines() or [""])[-1]
        res = json.loads(last) if p.returncode == 0 and last.startswith("{") else \
            {"status": "error", "error": (p.stderr.strip().splitlines() or ["no output"])[-1][:300]}
    except subprocess.TimeoutExpired:
        res = {"status": "timeout"}
    res.update(wa=wa, pdf=pdf, wall=round(time.time() - t0, 1))
    json.dump(res, open(marker, "w"))
    with open(os.path.join(args.out, "progress.log"), "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {wa} {res['status']:7} {res.get('stages', 0):3} stages "
                f"{res['wall']:6.0f}s {os.path.basename(pdf)}\n")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lab", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--one")
    ap.add_argument("--limit", type=int, default=LIMIT_S, help="seconds before a PDF is recorded as timed out")
    ap.add_argument("--retry-timeouts", action="store_true", help="read again the PDFs that timed out before")
    a = ap.parse_args()
    if a.one:
        return one(a.lab, a.one, a.out)
    rows = [(r["WA"].zfill(5), r["PDF"]) for r in csv.DictReader(open(a.jobs), delimiter="\t")]
    os.makedirs(a.out, exist_ok=True)
    todo = [r for r in rows if not done(a, os.path.join(a.out, r[0], os.path.splitext(os.path.basename(r[1]))[0] + ".done"))]
    with open(os.path.join(a.out, "progress.log"), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} batch {os.path.basename(a.jobs)}: {len(rows)} PDFs, {len(todo)} to read, {a.workers} workers\n")
    with ThreadPoolExecutor(a.workers) as ex:
        for _ in ex.map(lambda r: run(a, r), todo):
            pass
    with open(os.path.join(a.out, "progress.log"), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} batch {os.path.basename(a.jobs)} finished\n")


if __name__ == "__main__":
    main()
