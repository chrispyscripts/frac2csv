"""Analyse the cluster's remaining filings straight through the reader, in
parallel, writing the Lab's own exports (seconds CSV + stage tables) and
filling the Lab's results cache so a portal reuses them."""
import csv, json, os, sys, time, traceback
from multiprocessing import get_context
HERE = "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv"
sys.path.insert(0, HERE)
CLUSTER = os.path.join(HERE, "..", "batch-lists", "bc-cluster-2026-09-16.tsv")
OUT = os.path.join(HERE, "..", "exports", "bc-gundy-cluster", "lab-seconds")
ROOT = "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023"

def one(path):
    import fitz, pipeline, pipeline_export as pe, localapp
    t0 = time.time()
    base = os.path.splitext(os.path.basename(path))[0]
    doc = fitz.open(path)
    results, notes = pipeline.extract_document(doc, filename=os.path.basename(path))
    doc.close()
    stages, tables, notes2, summary = localapp.serialize(results, notes)
    localapp.cache_put(path, {"stages": stages, "tables": tables, "notes": notes2, "summary": summary})
    series = [r for r in results if r["type"] == "series"]
    written = []
    if series:
        model = pe.build_well(series, fallback_uwi=pe.filename_uwi(os.path.basename(path)))
        with open(os.path.join(OUT, base + "-seconds.csv"), "w", newline="") as f:
            f.write(pe.well_csv(model))
        written.append(base + "-seconds.csv")
    used = set()
    for i, t in enumerate(r for r in results if r["type"] == "table"):
        nm = localapp.table_csv_name(base, t.get("title", ""), i, used)
        with open(os.path.join(OUT, nm), "w", newline="") as f:
            w = csv.writer(f); w.writerow(t["columns"]); w.writerows(t["rows"])
        written.append(nm)
    return base, len(stages), written, round(time.time() - t0)

def main():
    rows = list(csv.DictReader(open(CLUSTER), delimiter="\t"))
    todo = []
    for r in rows:
        base = os.path.splitext(r["FILE"])[0]
        if os.path.exists(os.path.join(OUT, base + "-seconds.csv")):
            continue
        todo.append(os.path.join(ROOT, r["FILE"]))
    print(f"{len(todo)} files to analyse", flush=True)
    ctx = get_context("spawn")
    with ctx.Pool(5) as pool:
        jobs = [(p, pool.apply_async(one, (p,))) for p in todo]
        for p, j in jobs:
            try:
                base, n, written, secs = j.get(timeout=1800)
                print(f"done {base}: {n} stages, {len(written)} files, {secs}s", flush=True)
            except Exception as e:
                print(f"FAIL {os.path.basename(p)}: {type(e).__name__}: {e}", flush=True)
    print("ALL DONE", flush=True)

if __name__ == "__main__":
    main()
