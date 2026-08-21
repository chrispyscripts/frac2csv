"""Which files on either drive are Liberty filings.

Two signals, because the class we care about has no text to search:
  * the printed marker, on any sampled page (fast, catches text-layer files)
  * a file that is almost ALL textless, which is the outlined class — those
    get one OCR'd page to confirm, in a second pass, not here.
"""
import os, sys, glob, json, re
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz
from multiprocessing import Pool

MARK = re.compile(r"Liberty\s+(?:Energy|Oilfield)", re.I)
OTHER = [("halliburton", re.compile(r"Halliburton", re.I)),
         ("calfrac", re.compile(r"CalFrac", re.I)),
         ("trican", re.compile(r"Trican", re.I)),
         ("step", re.compile(r"STEP Energy", re.I)),
         ("slb", re.compile(r"Schlumberger|SLB", re.I)),
         ("canyon", re.compile(r"Canyon", re.I)),
         ("sanjel", re.compile(r"Sanjel", re.I)),
         ("bj", re.compile(r"BJ Services", re.I))]

def scan(path):
    try:
        doc = fitz.open(path)
        n = doc.page_count
        # spread the sample: covers carry the vendor, charts carry it too
        idx = sorted(set([0, 1, 2] + [int(n * f) for f in
                     (.1, .2, .3, .4, .5, .6, .7, .8, .9)] + [n - 1]))
        idx = [i for i in idx if 0 <= i < n]
        text = []
        textless = 0
        for i in idx:
            t = doc[i].get_text()
            text.append(t)
            if len(t.strip()) < 50: textless += 1
        blob = "\n".join(text)
        vendors = [k for k, r in OTHER if r.search(blob)]
        doc.close()
        return {"path": path, "pages": n, "liberty": bool(MARK.search(blob)),
                "textless": textless, "sampled": len(idx), "vendors": vendors}
    except Exception as e:
        return {"path": path, "error": f"{type(e).__name__}: {e}"}

if __name__ == "__main__":
    files = []
    for root in ("/Volumes/For-Chris-CnC-1TB", "/Volumes/CnC-2TB-ssd"):
        files += [f for f in glob.glob(os.path.join(root, "**", "*.pdf"),
                                       recursive=True)
                  if "$RECYCLE" not in f and "__LIB" not in f]
    # the provider-sorted mirrors on the 2TB duplicate loose files; keep one
    seen, uniq = set(), []
    for f in files:
        b = os.path.basename(f)
        if b in seen: continue
        seen.add(b); uniq.append(f)
    print(f"{len(files)} pdfs, {len(uniq)} unique names", file=sys.stderr, flush=True)
    with Pool(6) as p:
        rows = []
        for i, r in enumerate(p.imap_unordered(scan, uniq, chunksize=4)):
            rows.append(r)
            if (i + 1) % 200 == 0:
                print(f"  {i+1}/{len(uniq)}", file=sys.stderr, flush=True)
    json.dump(rows, open(sys.argv[1], "w"))
    lib = [r for r in rows if r.get("liberty")]
    tl = [r for r in rows if not r.get("liberty") and not r.get("error")
          and r.get("textless", 0) >= r.get("sampled", 1) - 1]
    print(f"marker Liberty: {len(lib)}   near-textless (OCR candidates): {len(tl)}",
          file=sys.stderr, flush=True)
