"""How often does a filing yield a TABLE, by provider folder.

Charts and tables succeed and fail independently — a document whose plots read
perfectly can still carry a Stage Summary nobody parses — so table coverage
has to be counted on its own rather than inferred from chart coverage.

Counted per FILE (did this filing produce any table at all) and per TABLE TYPE
(which parser produced it), because "60% of CalFrac files yield a table" and
"the CalFrac summary parser fires on 60% of pages" are different claims.

Provider is taken from the folder the corpus is already sorted into, plus the
chart sources the document reports, since a filing's real vendor is only
knowable after extraction.
"""
import os, sys, json, glob, random, collections, traceback
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
from multiprocessing import Pool
import fitz, pipeline

PER_FOLDER = int(os.environ.get("PER_FOLDER", "14"))
GROUPS = [
    ("Halliburton", "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/__HAL"),
    ("CalFrac",     "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/__CALFRAC"),
    ("Schlumberger","/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/__SCHLUM"),
    ("STEP",        "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/__STEP"),
    ("Trican",      "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/__TRICAN"),
    ("mixed-ARC",   "/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC"),
    ("mixed-BCER",  "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023"),
]


def one(job):
    group, path, out = job
    dst = os.path.join(out, group + "__" +
                       os.path.basename(path).rsplit(".", 1)[0] + ".json")
    if os.path.exists(dst) and os.path.getsize(dst) > 2:
        return "skip", ""
    try:
        doc = fitz.open(path)
        res, _n = pipeline.extract_document(doc, filename=os.path.basename(path))
        tabs = [r for r in res if r.get("type") == "table"]
        ser = [r for r in res if r.get("type") == "series"]
        rec = {"group": group, "file": os.path.basename(path),
               "pages": doc.page_count,
               "tables": len(tabs), "series": len(ser),
               "table_rows": sum(len(t.get("rows") or []) for t in tabs),
               "table_sources": dict(collections.Counter(
                   t.get("source", "?") for t in tabs)),
               "chart_sources": dict(collections.Counter(
                   r.get("source", "?") for r in ser))}
        doc.close()
    except Exception:
        rec = {"group": group, "file": os.path.basename(path),
               "fatal": traceback.format_exc()[-300:]}
    json.dump(rec, open(dst, "w"))
    return "done", (f"{group:<13} {rec['file'][:38]:<40} "
                    f"tables={rec.get('tables','-'):<3} series={rec.get('series','-')}")


if __name__ == "__main__":
    out, nproc = sys.argv[1], int(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    jobs = []
    for g, folder in GROUPS:
        if not os.path.isdir(folder):
            continue
        hits = [h for h in sorted(glob.glob(folder + "/*.pdf"))
                if os.path.getsize(h) > 10000]
        rnd = random.Random(g)          # stable sample across re-runs
        rnd.shuffle(hits)
        jobs += [(g, h, out) for h in hits[:PER_FOLDER]]
    print(f"{len(jobs)} files, {nproc} workers", file=sys.stderr, flush=True)
    n = 0
    with Pool(nproc) as pool:
        it = pool.imap_unordered(one, jobs, chunksize=1)
        while True:
            try:
                kind, msg = next(it)
            except StopIteration:
                break
            except Exception as e:
                print(f"WORKER ERROR {e}", file=sys.stderr, flush=True); continue
            n += 1
            if kind == "done":
                print(f"[{n}/{len(jobs)}] {msg}", file=sys.stderr, flush=True)
    print("TABLE SWEEP COMPLETE", file=sys.stderr, flush=True)
