"""Fetch wells' files from the BCER eLibrary: completion reports and LAS logs.

    python3 web/scripts/fetch_elibrary.py --wells wells.json --out <dir> [--comp] [--las] [--threads 3]

wells.json is a list of WA numbers. For each well the anonymous BIL-184 index
names what the eLibrary holds; --comp fetches every `<WA>_COMP_*.PDF`, --las
every `.LAS`, over FTP with the credentials in ~/.netrc (machine
files.bc-er.ca) -- see fetch_bc_wellfiles.py, whose lookups this reuses.
Files land in <out>/<WA>/; a file already there is skipped, so a run can be
repeated. <out>/manifest.jsonl gets one line per well: what the index listed
and what arrived.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_bc_wellfiles as fb  # noqa: E402


def fetch_well(wa, out, comp, las):
    try:
        names = fb.index_filenames(wa)
    except Exception:
        return {"wa": wa, "listed": None, "wanted": [], "got": [], "failed": ["index lookup failed"],
                "t": time.strftime("%Y-%m-%d %H:%M:%S")}
    wanted = [n for n in names if (comp and "_COMP_" in n.upper() and n.upper().endswith(".PDF"))
              or (las and n.upper().endswith(".LAS"))]
    got, failed = [], []
    if wanted:
        well_dir, listing = fb.find_well_dir(wa)
        if well_dir is None:
            failed = wanted
        else:
            os.makedirs(os.path.join(out, wa), exist_ok=True)
            lookup = {l.lower(): l for l in listing}
            for name in wanted:
                remote = lookup.get(name.lower(), name)
                dest = os.path.join(out, wa, remote)
                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    got.append(remote)
                    continue
                try:
                    r = fb.curl(["-o", dest, f"{fb.FTP}/{well_dir}/{remote}"], timeout=900)
                except Exception:          # a stalled transfer: drop it, keep going
                    r = None
                if r is not None and r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 200:
                    got.append(remote)
                else:
                    failed.append(remote)
                    if os.path.exists(dest):
                        os.remove(dest)
    return {"wa": wa, "listed": len(names), "wanted": wanted, "got": got, "failed": failed,
            "t": time.strftime("%Y-%m-%d %H:%M:%S")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wells", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--comp", action="store_true")
    ap.add_argument("--las", action="store_true")
    ap.add_argument("--threads", type=int, default=3)
    a = ap.parse_args()
    was = [str(w).zfill(5) for w in json.load(open(a.wells))]
    os.makedirs(a.out, exist_ok=True)
    with ThreadPoolExecutor(a.threads) as ex, open(os.path.join(a.out, "manifest.jsonl"), "a") as man:
        for res in ex.map(lambda w: fetch_well(w, a.out, a.comp, a.las), was):
            man.write(json.dumps(res) + "\n"); man.flush()
            print(f"{res['wa']}: {len(res['got'])}/{len(res['wanted'])} files", flush=True)


if __name__ == "__main__":
    main()
