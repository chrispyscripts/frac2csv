"""Did the CONTINUOUS splice help, hurt, or do nothing — per Trican file?

    python3 validation-tools/tricansplice.py --sample 14 --workers 4 \
        --out ../exports/tricansplice

One JSON line per file: every stage's exported minutes, what the STAGE
INFORMATION sheet says that stage ran, how many minutes were spliced, and
whether a CONTINUOUS page survived as a nameless stage. The question this
answers is the one the 00218 fix was only ever measured against one file:
does a stage now agree with its own sheet more often than it did, and did
anything get worse.
"""
import argparse, glob, json, os, re, sys, time
from multiprocessing import get_context

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
_INDEX = {}


def resolve(path):
    import localapp, pipeline_export as pe
    if os.path.exists(path):
        return path
    for root in localapp.find_drive_roots(path):
        real = pe.resolve_manifest_path(path, root)
        if real is None:
            if root not in _INDEX:
                _INDEX[root] = pe.index_pdfs(root)
            real = pe.resolve_manifest_path(path, root, _INDEX[root])
        if real:
            return real
    return None


def spread(items, n):
    if n >= len(items):
        return list(items)
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def one(job):
    path, out_dir = job
    import fitz, pipeline, trican2
    t0 = time.time()
    doc = fitz.open(path)
    try:
        sheets = trican2.stage_clock(doc)
    except Exception:
        sheets = {}
    # The sheet's own Total Time per stage, straight off the page: the
    # number the export should agree with, read independently of anything
    # the pipeline decides.
    totals = {}
    for i in range(doc.page_count):
        t = doc[i].get_text()
        if "STAGE INFORMATION" not in t:
            continue
        m = re.search(r"Total Time:.*?([\d.]+)\s*min", t, re.S)
        st = None
        for back in (1, 2, 3):
            if i - back < 0:
                break
            mm = re.search(r"Stage (\d+):", doc[i - back].get_text())
            if mm:
                st = int(mm.group(1))
                break
        if st is not None and m:
            totals[st] = float(m.group(1))
    res, notes = pipeline.extract_document(doc, filename=os.path.basename(path))
    doc.close()
    ser = [r for r in res if r.get("type") == "series"
           and str(r.get("source") or "").startswith("Trican")]
    stages = []
    for r in ser:
        md = r["meta"]
        mins = len(r["samples"]) * pipeline._sample_sec(r) / 60.0
        ho = len(r["handover"]["samples"]) * pipeline._sample_sec(r) / 60.0 \
            if r.get("handover") else 0.0
        m = re.match(r"\d+", str(md.get("stage") or "").strip())
        num = int(m.group(0)) if m else None
        stages.append({"stage": md.get("stage") or "", "num": num,
                       "page": r.get("page"), "min": round(mins, 1),
                       "handover": round(ho, 1),
                       "sheet": totals.get(num),
                       "cont": bool(md.get("continuous")),
                       "spliced": sum(
                           float(x) for x in re.findall(
                               r"the first ([\d.]+) min of this stage",
                               " ".join(str(w) for w in md.get("warnings", []))))})
    rec = {"file": os.path.basename(path), "path": path,
           "stages": stages, "n_stages": len(stages),
           "nameless": sum(1 for s in stages if not str(s["stage"]).strip()),
           "continuous_kept": sum(1 for s in stages if s["cont"]),
           "spliced_min": round(sum(s["spliced"] for s in stages), 1),
           "sheets_read": len(totals),
           "notes": [n for n in notes
                     if "CONTINUOUS" in str(n) or "added to its" in str(n)],
           "seconds": round(time.time() - t0)}
    with open(os.path.join(out_dir, "tricansplice.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _safe(job):
    try:
        return one(job)
    except Exception as e:
        return {"file": os.path.basename(job[0]), "error": f"{type(e).__name__}: {e}"}


def summary(path):
    recs = [json.loads(l) for l in open(path) if l.strip()]
    print(f"{len(recs)} files\n")
    print(f"{'file':52} {'st':>3} {'sheets':>6} {'spliced':>8} {'nameless':>8} "
          f"{'cont':>5} {'|exp-sheet| median':>18}")
    tot_spliced = tot_nameless = 0
    for r in sorted(recs, key=lambda r: -r.get("spliced_min", 0)):
        if r.get("error"):
            print(f"{r['file'][:52]:52} ERROR {r['error'][:60]}")
            continue
        # how far each stage's export sits from its own sheet's Total Time
        d = sorted(abs(s["min"] + s["handover"] - s["sheet"])
                   for s in r["stages"]
                   if s["sheet"] and not s["cont"])
        med = d[len(d) // 2] if d else None
        tot_spliced += r["spliced_min"]; tot_nameless += r["nameless"]
        print(f"{r['file'][:52]:52} {r['n_stages']:3d} {r['sheets_read']:6d} "
              f"{r['spliced_min']:8.0f} {r['nameless']:8d} {r['continuous_kept']:5d} "
              f"{(f'{med:.1f}' if med is not None else '-'):>18}")
    print(f"\ntotal spliced {tot_spliced:.0f} min, {tot_nameless} nameless stage(s) left")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", nargs="*",
                    default=[os.path.join(HERE, "..", "batch-lists", "by-type",
                                          "trican1__*.txt")])
    ap.add_argument("--sample", type=int, default=14)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "exports", "tricansplice"))
    ap.add_argument("--summary")
    a = ap.parse_args()
    if a.summary:
        return summary(a.summary)
    import pipeline_export as pe
    os.makedirs(a.out, exist_ok=True)
    jl = os.path.join(a.out, "tricansplice.jsonl")
    done = {json.loads(l)["file"] for l in open(jl)} if os.path.exists(jl) else set()
    rows = []
    for pat in a.lists:
        for lst in sorted(glob.glob(pat)):
            for uwi, path in pe.parse_manifest(
                    open(lst, encoding="utf-8", errors="replace").read()):
                rows.append(path)
    pick, jobs = spread(rows, a.sample), []
    for path in pick:
        real = resolve(path)
        if not real:
            print(f"unresolved: {path}", flush=True); continue
        if os.path.basename(real) in done:
            continue
        jobs.append((real, a.out))
    print(f"{len(rows)} listed, {len(pick)} sampled, {len(jobs)} to read", flush=True)
    ctx = get_context("spawn")
    with ctx.Pool(a.workers) as pool:
        for r in pool.imap_unordered(_safe, jobs):
            if r.get("error"):
                print(f"FAIL {r['file']}: {r['error']}", flush=True)
            else:
                print(f"done {r['file']}: {r['n_stages']} stages, "
                      f"spliced {r['spliced_min']:.0f} min, "
                      f"{r['nameless']} nameless, {r['seconds']}s", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
