"""Which of the textless files are LIBERTY, by OCR'ing a few pages.

The outlined class cannot be found by searching text: there is none. But
identifying a file is much cheaper than analysing it — a handful of pages
carries the vendor name, so this narrows 253 candidates down to the ones
worth spending an OCR pass on.
"""
import os, sys, json, re
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz, ocr_labels
from multiprocessing import Pool

MARK = re.compile(r"Liberty\s+(?:Energy|Oilfield)", re.I)
STAGE = re.compile(r"\b(?:Stage|STG)\s+(?:[A-Z]{2,4}\s+)?\d", re.I)
OTHER = [("halliburton", r"Halliburton"), ("calfrac", r"CalFrac"),
         ("trican", r"Trican"), ("step", r"STEP Energy"),
         ("slb", r"Schlumberger|SLB"), ("canyon", r"Canyon"),
         ("sanjel", r"Sanjel"), ("bj", r"BJ Services"),
         ("ovintiv", r"Ovintiv|WellOps")]

def ident(path):
    try:
        doc = fitz.open(path)
        n = doc.page_count
        # a chart page, not the cover: sample through the body
        idx = [int(n * f) for f in (.25, .45, .65, .85)]
        idx = sorted(set(i for i in idx if 0 <= i < n))
        blob = []
        for i in idx:
            page = doc[i]
            t = page.get_text()
            if len(t.strip()) < 50:
                try: t = ocr_labels.page_text(page) or ""
                except Exception: t = ""
            blob.append(t)
        doc.close()
        s = "\n".join(blob)
        return {"path": path, "pages": n,
                "liberty": bool(MARK.search(s)),
                "stage_token": bool(STAGE.search(s)),
                "others": [k for k, r in OTHER if re.search(r, s, re.I)],
                "chars": len(s.strip())}
    except Exception as e:
        return {"path": path, "error": f"{type(e).__name__}: {e}"}

if __name__ == "__main__":
    rows = json.load(open(sys.argv[1]))
    def tl(r): return (not r.get("error")
                       and r.get("textless", 0) * 2 >= r.get("sampled", 1))
    done = set()
    import os as _os
    if len(sys.argv) > 3 and _os.path.exists(sys.argv[3]):
        done = {r["path"] for r in json.load(open(sys.argv[3]))}
    cand = [r["path"] for r in rows
            if not r.get("liberty") and tl(r) and r["path"] not in done]
    print(f"{len(cand)} textless candidates", file=sys.stderr, flush=True)
    got = []
    with Pool(5) as p:
        for i, r in enumerate(p.imap_unordered(ident, cand, chunksize=2)):
            got.append(r)
            if r.get("liberty"):
                print(f"  LIBERTY {os.path.basename(r['path'])[:44]} "
                      f"{r['pages']}pp", file=sys.stderr, flush=True)
            if (i + 1) % 25 == 0:
                print(f"  ..{i+1}/{len(cand)}", file=sys.stderr, flush=True)
    json.dump(got, open(sys.argv[2], "w"))
    lib = [r for r in got if r.get("liberty")]
    print(f"DONE: {len(lib)} Liberty of {len(cand)}, "
          f"{sum(r['pages'] for r in lib)} pages", file=sys.stderr, flush=True)
