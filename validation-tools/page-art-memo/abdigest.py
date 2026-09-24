"""Bit-exact extraction digest for one tree, for an old-vs-new diff.

Runs the REAL router (pipeline.extract_document), so every reader the file
touches is exercised, not just the one we think it should hit.

usage: abdigest.py <tree-root> <out.json> <pdf> [pdf ...]

The digest is deliberately stronger than "n/min/max/axis": every channel's
full sample array is hashed byte-for-byte. A memo that is purely a speed
change must reproduce the arrays exactly, so any tolerance here would be
hiding the only thing worth looking for. n/min/max/axis ride along so a
mismatch can be read by a human instead of just flagged.
"""
import sys, os, json, hashlib, traceback

root, outp, pdfs = sys.argv[1], sys.argv[2], sys.argv[3:]
os.chdir(root)
sys.path.insert(0, root)

import numpy as np
import fitz, pipeline


def h(arr):
    a = np.ascontiguousarray(np.asarray(arr, float))
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def digest_file(path):
    doc = fitz.open(path)
    res, _n = pipeline.extract_document(doc, filename=os.path.basename(path))
    out = []
    for r in res:
        if r.get("type") == "series":
            meta = r.get("meta")
            ch = {}
            for k, v in (r.get("data") or {}).items():
                v = np.asarray(v, float)
                fin = v[np.isfinite(v)]
                ch[k] = {
                    "n": int(v.size),
                    "sha": h(v),
                    "min": repr(float(fin.min())) if fin.size else None,
                    "max": repr(float(fin.max())) if fin.size else None,
                    "axis": [repr(float(x)) for x in
                             (getattr(meta, "axes", {}) or {}).get(k, (0, 0))],
                    "unit": (r.get("units") or {}).get(k),
                    "label": (r.get("labels") or {}).get(k),
                }
            out.append({
                "type": "series",
                "source": r.get("source"),
                "page": r.get("page"),
                "stage": str(getattr(meta, "stage", None)),
                "dur": repr(float(getattr(meta, "duration_min", 0) or 0)),
                "samples_sha": h(r.get("samples")) if r.get("samples") is not None else None,
                "ch": ch,
            })
        elif r.get("type") == "table":
            rows = r.get("rows") or []
            blob = json.dumps(rows, sort_keys=True, default=str)
            out.append({
                "type": "table",
                "source": r.get("source"),
                "title": r.get("title"),
                "well": r.get("well"),
                "uwi": r.get("uwi"),
                "formation": r.get("formation"),
                "columns": r.get("columns"),
                "nrows": len(rows),
                "rows_sha": hashlib.sha256(blob.encode()).hexdigest()[:16],
            })
        else:
            out.append({"type": r.get("type"), "source": r.get("source")})
    # order must not depend on dict iteration luck
    out.sort(key=lambda d: json.dumps(d, sort_keys=True, default=str))
    return {"n_results": len(res), "results": out}


all_out = {}
for p in pdfs:
    try:
        all_out[os.path.basename(p)] = digest_file(p)
    except Exception as e:
        all_out[os.path.basename(p)] = {
            "error": f"{type(e).__name__}: {e}",
            "tb": traceback.format_exc()[-800:]}

with open(outp, "w") as f:
    json.dump(all_out, f, sort_keys=True, indent=1)
print(f"digested {len(pdfs)} file(s) -> {outp}")
