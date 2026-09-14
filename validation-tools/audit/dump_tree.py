"""dump.py, but the pipeline is taken from the tree named in F2C_REPO —
the before/after harness. Proves the two sides differ by printing the
tree's own HEAD, so an identical result cannot hide a run on the wrong code.
"""
import json, os, sys, time, subprocess
REPO = os.environ["F2C_REPO"]
sys.path.insert(0, REPO)
import fitz, pipeline, localapp
src, dst = sys.argv[1], sys.argv[2]
head = subprocess.run(["git", "-C", REPO, "log", "--oneline", "-1"], capture_output=True, text=True).stdout.strip()
print("tree:", REPO, "|", head, "| pipeline from:", pipeline.__file__, flush=True)
t0 = time.time()
doc = fitz.open(src)
results, notes = pipeline.extract_document(doc, filename=os.path.basename(src))
doc.close()
stages, tables, notes, summary = localapp.serialize(results, notes)
json.dump({"file": os.path.basename(src), "tree": head, "npages": len(stages), "stages": stages, "notes": notes},
          open(dst, "w"), default=lambda o: getattr(o, "__dict__", str(o)))
print(f"done {len(stages)} series in {time.time()-t0:.0f}s -> {dst}", flush=True)
