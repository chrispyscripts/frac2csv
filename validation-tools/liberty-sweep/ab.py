"""Before/after over real Liberty pages, digesting every value.

The point is not "did the count go up" — it is "did any value that was
already right MOVE". A text-layer file is in the set on purpose: the v1.5.0
release was gated on those being bit-identical, and any change here that
touches them breaks that promise.
"""
import sys, os, json, hashlib
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz, lib1

def digest(path, pages):
    doc = fitz.open(path)
    out = {}
    for pno in pages:
        try:
            meta, samples, data, units = lib1.extract_page(doc[pno - 1])
        except Exception as e:
            out[f"p{pno}"] = {"error": f"{type(e).__name__}: {e}"}
            continue
        rec = {"stage": getattr(meta, "stage", None),
               "date": getattr(meta, "date", None),
               "time": str(getattr(meta, "start_time", None)), "n": len(samples),
               "ch": {}}
        for k, v in data.items():
            arr = ",".join("" if (x is None or x != x) else f"{x:.6g}" for x in v)
            rec["ch"][k] = hashlib.sha1(arr.encode()).hexdigest()[:12]
        out[f"p{pno}"] = rec
    doc.close()
    return out

if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    got = {}
    for path, pages in spec.items():
        got[os.path.basename(path)] = digest(path, pages)
    json.dump(got, open(sys.argv[2], "w"), indent=1)
    n = sum(len(v) for v in got.values())
    ch = sum(len(p.get("ch", {})) for v in got.values() for p in v.values())
    print(f"{n} pages, {ch} channels", flush=True)
