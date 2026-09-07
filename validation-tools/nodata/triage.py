"""Every file named in an open "No extractable data" report, through the
CURRENT code.

Carmine's reports are a running log, not a to-do state: several whole classes
have been fixed since they were filed (Halliburton with no text layer, IFS v6,
Liberty's elapsed-minute charts), so a report saying a file yields nothing may
simply be out of date. This says which.

Three outcomes matter and they are different things:
  * EXTRACTS   — the report is stale, the fix already shipped
  * EMPTY      — still nothing, and the file needs looking at
  * NO CHARTS  — nothing to extract; an honest empty result, not a defect

One JSON per file so the run is restartable and a drive dropping out costs
one file rather than the run.
"""
import os, sys, json, collections, traceback
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
from multiprocessing import Pool
import fitz, pipeline


def one(job):
    path, out = job
    dst = os.path.join(out, os.path.basename(path).rsplit(".", 1)[0] + ".json")
    if os.path.exists(dst) and os.path.getsize(dst) > 2:
        return "skip", os.path.basename(path)
    try:
        doc = fitz.open(path)
        res, notes = pipeline.extract_document(doc, filename=os.path.basename(path))
        ser = [r for r in res if r.get("type") == "series"]
        tab = [r for r in res if r.get("type") == "table"]
        rec = {"file": os.path.basename(path), "path": path,
               "pages": doc.page_count, "series": len(ser), "tables": len(tab),
               "sources": dict(collections.Counter(r.get("source") for r in ser)),
               "dated": sum(1 for r in ser if (r["meta"].get("date") or "").strip()),
               "clocked": sum(1 for r in ser
                              if (r["meta"].get("start_time") or "").strip()),
               "notes": notes[:30]}
        doc.close()
    except Exception:
        rec = {"file": os.path.basename(path), "path": path,
               "fatal": traceback.format_exc()[-400:]}
    json.dump(rec, open(dst, "w"))
    return "done", (f"{rec['file'][:44]:<46} {rec.get('pages','?'):>4}pp "
                    f"series={rec.get('series','-')} tables={rec.get('tables','-')}")


if __name__ == "__main__":
    listfile, out, nproc = sys.argv[1], sys.argv[2], int(sys.argv[3])
    os.makedirs(out, exist_ok=True)
    todo = [(p, out) for p in json.load(open(listfile))]
    print(f"{len(todo)} files, {nproc} workers", file=sys.stderr, flush=True)
    n = 0
    with Pool(nproc) as pool:
        it = pool.imap_unordered(one, todo, chunksize=1)
        while True:
            try:
                kind, msg = next(it)
            except StopIteration:
                break
            except Exception as e:
                print(f"WORKER ERROR {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                continue
            n += 1
            if kind == "done":
                print(f"[{n}/{len(todo)}] {msg}", file=sys.stderr, flush=True)
    print("TRIAGE COMPLETE", file=sys.stderr, flush=True)
