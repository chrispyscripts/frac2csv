"""Wall and CPU seconds per file for one tree, over a provider-labelled list.

Reports CPU separately from wall because the corpus lives on a spinning USB
drive: wall time on a cold file is mostly the drive, and a speedup measured
that way would be measuring the cable. CPU time is ours.

usage: abtime.py <tree-root> <sample.tsv> <out.json> [--warm]
"""
import sys, os, json, time

root, listp, outp = sys.argv[1], sys.argv[2], sys.argv[3]
warm = "--warm" in sys.argv
os.chdir(root)
sys.path.insert(0, root)

import fitz, pipeline

rows = []
for line in open(listp):
    line = line.rstrip("\n")
    if not line.strip():
        continue
    prov, path = line.split("\t")[0], line.split("\t")[-1]
    rows.append((prov, path))

out = {}
for prov, path in rows:
    if not os.path.exists(path):
        continue
    if warm:                      # pull the bytes through the page cache once
        try:
            with open(path, "rb") as f:
                while f.read(1 << 22):
                    pass
        except Exception:
            pass
    t0, c0 = time.perf_counter(), time.process_time()
    try:
        doc = fitz.open(path)
        res, _ = pipeline.extract_document(doc, filename=os.path.basename(path))
        n = len(res)
        pages = doc.page_count
        doc.close()
        err = None
    except Exception as e:
        n, pages, err = 0, 0, f"{type(e).__name__}: {e}"
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    out[path] = {"prov": prov, "wall": round(wall, 3), "cpu": round(cpu, 3),
                 "results": n, "pages": pages, "error": err}
    print(f"{prov:12s} {wall:8.2f}s wall {cpu:8.2f}s cpu  "
          f"{pages:4d}p  {os.path.basename(path)[:52]}", flush=True)

with open(outp, "w") as f:
    json.dump(out, f, sort_keys=True, indent=1)
tw = sum(v["wall"] for v in out.values())
tc = sum(v["cpu"] for v in out.values())
tp = sum(v["pages"] for v in out.values())
print(f"\nTOTAL {len(out)} files, {tp} pages: {tw:.1f}s wall, {tc:.1f}s cpu")
