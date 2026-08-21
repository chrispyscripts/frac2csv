"""How many pages of each marker file are Liberty CHART pages.

A filing can name Liberty in a service list and be charted by somebody else,
so the marker is not the question — detect firing is. This is cheap on a page
that has text, which is the whole point of running it before the extraction
sweep: it turns 403 files into the ones that actually hold charts.
"""
import os, sys, json
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz, lib1
from multiprocessing import Pool

def count(path):
    try:
        doc = fitz.open(path)
        n = doc.page_count
        hits = []
        for i in range(n):
            try:
                if lib1.detect(doc[i]): hits.append(i + 1)
            except Exception:
                pass
        doc.close()
        return {"path": path, "pages": n, "chart_pages": hits}
    except Exception as e:
        return {"path": path, "error": f"{type(e).__name__}: {e}"}

if __name__ == "__main__":
    paths = json.load(open(sys.argv[1]))
    print(f"{len(paths)} files", file=sys.stderr, flush=True)
    out = []
    with Pool(4) as p:
        for i, r in enumerate(p.imap_unordered(count, paths, chunksize=2)):
            out.append(r)
            if (i + 1) % 25 == 0:
                tot = sum(len(x.get("chart_pages", [])) for x in out)
                print(f"  {i+1}/{len(paths)}  chart pages so far {tot}",
                      file=sys.stderr, flush=True)
    json.dump(out, open(sys.argv[2], "w"))
    withc = [r for r in out if r.get("chart_pages")]
    print(f"DONE: {len(withc)} files hold Liberty charts, "
          f"{sum(len(r['chart_pages']) for r in withc)} chart pages",
          file=sys.stderr, flush=True)
