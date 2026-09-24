"""Does the page-art memo survive the threading the Lab actually does?

Two checks:

1. TARGETED. Several threads hammer fc.drawings() on pages of DIFFERENT
   documents at once and each compares what it got against that page's own
   uncached get_drawings(). A memo that is shared rather than thread-local
   hands one thread another thread's geometry, and this sees it directly.

2. END TO END. The same files, read sequentially and then all at once
   through localapp.process_bytes (the path _READ_GATE actually gates), must
   serialize to identical output.

usage: threadsafe.py <tree-root> <pdf> [pdf ...]
"""
import sys, os, json, hashlib, threading, traceback

root, pdfs = sys.argv[1], sys.argv[2:]
os.chdir(root)
sys.path.insert(0, root)

import fitz
import frac_core as fc
import localapp

HAS_MEMO = hasattr(fc, "drawings")
print(f"tree: {root}\nmemo present: {HAS_MEMO}\n")


def sig(art):
    """A signature of a page's vector art that does not depend on identity."""
    parts = []
    for d in art:
        parts.append((str(d.get("type")), str(d.get("color")),
                      str(d.get("rect")), len(d.get("items") or ())))
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:16]


# ---------------- 1. targeted memo cross-talk ----------------
failures = []


def hammer(path, tag, rounds=12):
    try:
        doc = fitz.open(path)
        n = min(doc.page_count, 6)
        truth = {}
        for p in range(n):
            truth[p] = sig(doc[p].get_drawings())
        for _ in range(rounds):
            for p in range(n):
                got = sig(fc.drawings(doc[p]) if HAS_MEMO
                          else doc[p].get_drawings())
                if got != truth[p]:
                    failures.append(
                        f"{tag} page {p}: got another page's art "
                        f"({got} != {truth[p]})")
        doc.close()
    except Exception:
        failures.append(f"{tag}: {traceback.format_exc()[-300:]}")


ts = [threading.Thread(target=hammer, args=(p, os.path.basename(p)))
      for p in pdfs]
for t in ts:
    t.start()
for t in ts:
    t.join()
print(f"[1] targeted cross-talk: {len(failures)} failure(s)")
for f in failures[:10]:
    print("    " + f)


# ---------------- 2. sequential vs concurrent, end to end ----------------
def read(path):
    with open(path, "rb") as f:
        data = f.read()
    with localapp._READ_GATE:
        out = localapp.process_bytes(data, os.path.basename(path))
    return hashlib.sha256(
        json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()[:16]


seq = {}
for p in pdfs:
    try:
        seq[p] = read(p)
    except Exception as e:
        seq[p] = f"ERR {type(e).__name__}: {e}"

con = {}
lock = threading.Lock()


def one(p):
    try:
        v = read(p)
    except Exception as e:
        v = f"ERR {type(e).__name__}: {e}"
    with lock:
        con[p] = v


ts = [threading.Thread(target=one, args=(p,)) for p in pdfs]
for t in ts:
    t.start()
for t in ts:
    t.join()

bad = [p for p in pdfs if seq.get(p) != con.get(p)]
print(f"\n[2] sequential vs concurrent over {len(pdfs)} file(s): "
      f"{len(bad)} mismatch(es)")
for p in bad[:10]:
    print(f"    {os.path.basename(p)}: seq={seq.get(p)} con={con.get(p)}")

sys.exit(1 if (failures or bad) else 0)
