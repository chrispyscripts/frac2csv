"""Capping the threads must not change what tesseract READS. Several pages,
three vendors, upright and rotated, compared as text."""
import os, sys, hashlib, time
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz, numpy as np
import auto_raster as ar

JOBS = [
 ("BJ textless", "/Volumes/For-Chris-CnC-1TB/BCER-Frac/00956-202D037H093P0900_32287/00956-202D037H093P0900_32287_COMP_2025JUL01.PDF", [192, 194]),
 ("CalFrac MView", "/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/00340-100041006625W500_0500193_COMP.pdf", [72, 73]),
 ("Peloton outlined", "/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/00440-100032606204W600_0503868_COMP.pdf", [0, 10]),
]

def digest(arr):
    b = ar.ocr_boxes(arr, psm=6, whitelist="")
    s = "|".join(f"{w['text']}@{round(w['x0'])},{round(w['y0'])}" for w in b)
    return hashlib.sha1(s.encode()).hexdigest()[:12], len(b)

imgs = []
for lab, path, pages in JOBS:
    doc = fitz.open(path)
    for p in pages:
        pix = doc[p].get_pixmap(dpi=200)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4: a = a[..., :3]
        imgs.append((f"{lab} p{p+1}", a.astype(int)))

for limit in (None, "1"):
    if limit is None:
        os.environ.pop("OMP_THREAD_LIMIT", None); tag = "default"
    else:
        os.environ["OMP_THREAD_LIMIT"] = limit; tag = "limit=1"
    t0 = time.time()
    res = [(lab,) + digest(a) for lab, a in imgs]
    print(f"--- {tag}  total={time.time()-t0:.1f}s", flush=True)
    for lab, h, n in res:
        print(f"      {lab:<22} {h}  words={n}", flush=True)
