"""Full per-page analysis over every Liberty file, one JSON per file.

One file per output so a drive that unmounts mid-run costs one file, not the
run — the handoff records two agents killed exactly that way. Files already
done are skipped, so this is restartable.
"""
import os, sys, json, glob
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool
import lib_pages

def one(job):
    path, out = job
    key = os.path.basename(path).replace(".pdf", "") + ".json"
    dst = os.path.join(out, key)
    if os.path.exists(dst) and os.path.getsize(dst) > 2:
        return ("skip", path)
    try:
        r = lib_pages.run(path)
    except Exception as e:
        r = {"file": os.path.basename(path), "path": path,
             "fatal": f"{type(e).__name__}: {e}"}
    json.dump(r, open(dst, "w"))
    det = sum(1 for p in r.get("pages", []) if p.get("detect"))
    ok = sum(1 for p in r.get("pages", []) if p.get("channels"))
    return ("done", f"{os.path.basename(path)[:40]} {r.get('npages','?')}pp "
                    f"det={det} ext={ok}")

if __name__ == "__main__":
    listfile, out, nproc = sys.argv[1], sys.argv[2], int(sys.argv[3])
    os.makedirs(out, exist_ok=True)
    paths = json.load(open(listfile))
    todo = [(p, out) for p in paths]
    print(f"{len(todo)} files, {nproc} workers", file=sys.stderr, flush=True)
    n = 0
    with Pool(nproc) as pool:
        it = pool.imap_unordered(one, todo, chunksize=1)
        while True:
            try:
                kind, msg = next(it)
            except StopIteration:
                break
            except Exception as e:          # one bad file, not the whole run
                print(f"WORKER ERROR {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                continue
            n += 1
            if kind == "done":
                print(f"[{n}/{len(todo)}] {msg}", file=sys.stderr, flush=True)
    print("SWEEP COMPLETE", file=sys.stderr, flush=True)
