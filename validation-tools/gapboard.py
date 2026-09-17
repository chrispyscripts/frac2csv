"""The gap scoreboard: where the blank samples in a corpus come from.

    python3 validation-tools/gapboard.py --lists '../batch-lists/by-type/step1__*.txt' \
        '../batch-lists/by-type/trican1__*.txt' --sample 20 --workers 5 --out ../exports/gapboard
    python3 validation-tools/gapboard.py --summary ../exports/gapboard/gapboard.jsonl

The goal is "zero MISSING, zero UNKNOWN" over the STEP and Trican corpora —
not "no blank samples": the pad and the flush are not drawn, and a pen that
rests at zero is not a loss. This runs the reader and then gaps.py's
classification (the same one the Lab and the audit use) over a spread
sample of each list group, and writes one JSON line per file:

  corpus, file, stages, kinds (vector/image), sources (which reader),
  channels: {key: {n, lead, trail, at-floor, at-ceiling, missing,
                   unclassified, stages, stages_without_axis}}
  findings: the audit's warning kinds, counted
  failed:   the reader's "pN: … failed — reason" notes

`--summary` ranks the MISSING and UNKNOWN columns by corpus, channel, reader
and finding kind, so the answer to "five defects or five hundred" is a table.
"""
import argparse, csv, glob, json, os, re, sys, time
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


def rows_for(pattern):
    import pipeline_export as pe
    out = []
    for lst in sorted(glob.glob(pattern)):
        corpus = os.path.basename(lst).split("__")[0]
        for uwi, path in pe.parse_manifest(open(lst, encoding="utf-8", errors="replace").read()):
            out.append((corpus, uwi, path))
    return out


def spread(items, n):
    """n items evenly spaced through the list — every batch, every vintage."""
    if n >= len(items):
        return list(items)
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def one(job):
    corpus, path, out_dir = job
    import fitz, pipeline, localapp, audit, gaps
    t0 = time.time()
    doc = fitz.open(path)
    results, notes = pipeline.extract_document(doc, filename=os.path.basename(path))
    doc.close()
    stages, tables, notes2, summary = localapp.serialize(results, notes)
    localapp.cache_put(path, {"stages": stages, "tables": tables, "notes": notes2, "summary": summary})
    res = audit.audit_stages(stages, notes2, tables)
    chans, kinds, sources = {}, {}, {}
    for st in stages:
        kinds[st.get("kind", "?")] = kinds.get(st.get("kind", "?"), 0) + 1
        src = re.sub(r"[\s:].*$", "", str(st.get("source", "") or "?"))
        sources[src] = sources.get(src, 0) + 1
        for ch in st.get("channels", []):
            key = ch["key"]
            c = chans.setdefault(key, {"n": 0, "stages": 0, "stages_without_axis": 0,
                                       gaps.LEAD: 0, gaps.TRAIL: 0, gaps.AT_FLOOR: 0,
                                       gaps.AT_CEIL: 0, gaps.MISSING: 0, gaps.UNKNOWN: 0})
            cov = res["coverage"].get(f"{audit._stage_label(st)}|{key}", {})
            c["n"] += len(ch.get("values") or [])
            c["stages"] += 1
            if audit._axis(ch) is None:
                c["stages_without_axis"] += 1
            for k in (gaps.LEAD, gaps.TRAIL, gaps.AT_FLOOR, gaps.AT_CEIL, gaps.MISSING, gaps.UNKNOWN):
                c[k] += int(cov.get(k, 0))
    warn = {}
    for f in res["findings"]:
        if f["severity"] == "warn":
            warn[f["kind"]] = warn.get(f["kind"], 0) + 1
    failed = [n for n in notes2 if re.match(r"^p\d+: .+? failed — ", str(n))]
    rec = {"corpus": corpus, "file": os.path.basename(path), "path": path,
           "stages": len(stages), "kinds": kinds, "sources": sources, "channels": chans,
           "findings": warn, "failed": failed[:20], "failed_n": len(failed),
           "seconds": round(time.time() - t0)}
    with open(os.path.join(out_dir, "gapboard.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def summary(path):
    import gaps
    recs = [json.loads(l) for l in open(path) if l.strip()]
    print(f"{len(recs)} files")
    tot = {}
    for r in recs:
        for key, c in r["channels"].items():
            t = tot.setdefault((r["corpus"], key), {"n": 0, "files": 0, "stages": 0, "noaxis": 0,
                                                    "miss": 0, "unk": 0, "lead": 0, "trail": 0, "floor": 0})
            t["n"] += c["n"]; t["files"] += 1; t["stages"] += c["stages"]; t["noaxis"] += c["stages_without_axis"]
            t["miss"] += c[gaps.MISSING]; t["unk"] += c[gaps.UNKNOWN]
            t["lead"] += c[gaps.LEAD]; t["trail"] += c[gaps.TRAIL]; t["floor"] += c[gaps.AT_FLOOR]
    print(f"\n{'corpus':8} {'channel':16} {'files':>5} {'stages':>6} {'no-axis':>7} {'samples':>9} "
          f"{'MISSING':>8} {'%':>5} {'UNKNOWN':>8} {'%':>5} {'lead+trail':>10} {'at-floor':>8}")
    for (corpus, key), t in sorted(tot.items(), key=lambda kv: -(kv[1]["miss"] + kv[1]["unk"])):
        n = t["n"] or 1
        print(f"{corpus:8} {key:16} {t['files']:5d} {t['stages']:6d} {t['noaxis']:7d} {t['n']:9d} "
              f"{t['miss']:8d} {t['miss'] / n * 100:5.2f} {t['unk']:8d} {t['unk'] / n * 100:5.2f} "
              f"{t['lead'] + t['trail']:10d} {t['floor']:8d}")
    print("\nfiles ranked by MISSING+UNKNOWN samples:")
    ranked = sorted(recs, key=lambda r: -sum(c[gaps.MISSING] + c[gaps.UNKNOWN] for c in r["channels"].values()))
    for r in ranked[:15]:
        m = sum(c[gaps.MISSING] for c in r["channels"].values()); u = sum(c[gaps.UNKNOWN] for c in r["channels"].values())
        worst = sorted(r["channels"].items(), key=lambda kv: -(kv[1][gaps.MISSING] + kv[1][gaps.UNKNOWN]))[:2]
        print(f"  {r['corpus']:8} {r['file'][:58]:58} {r['stages']:3d} st  miss {m:7d}  unk {u:7d}  "
              f"{' '.join(k for k, _ in worst)}  {','.join(r['sources'])}  {r['failed_n']} failed pages")
    fk = {}
    for r in recs:
        for k, v in r["findings"].items():
            fk[k] = fk.get(k, 0) + v
    print("\naudit warnings by kind:")
    for k, v in sorted(fk.items(), key=lambda kv: -kv[1]):
        print(f"  {k:20} {v}")
    src = {}
    for r in recs:
        for k, v in r["sources"].items():
            src[(r["corpus"], k)] = src.get((r["corpus"], k), 0) + v
    print("\nstages by reader:", ", ".join(f"{c}/{k} {v}" for (c, k), v in sorted(src.items())))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lists", nargs="*", default=[])
    ap.add_argument("--sample", type=int, default=20, help="files per list group")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "exports", "gapboard"))
    ap.add_argument("--dry", action="store_true", help="resolve and list the sample, read nothing")
    ap.add_argument("--summary", help="a gapboard.jsonl to summarise")
    a = ap.parse_args()
    if a.summary:
        return summary(a.summary)
    os.makedirs(a.out, exist_ok=True)
    done = set()
    jl = os.path.join(a.out, "gapboard.jsonl")
    if os.path.exists(jl):
        done = {json.loads(l)["file"] for l in open(jl) if l.strip()}
    jobs = []
    for pat in a.lists:
        rows = rows_for(pat)
        pick = spread(rows, a.sample)
        for corpus, uwi, path in pick:
            real = resolve(path)
            if not real:
                print(f"unresolved: {path}", flush=True); continue
            if os.path.basename(real) in done:
                continue
            jobs.append((corpus, real, a.out))
        print(f"{pat}: {len(rows)} listed, {len(pick)} sampled", flush=True)
    print(f"{len(jobs)} files to read", flush=True)
    if a.dry:
        for c, p, _ in jobs:
            print(f"  {c:8} {os.path.basename(p)}")
        return
    ctx = get_context("spawn")
    with ctx.Pool(a.workers) as pool:
        for r in pool.imap_unordered(_safe, jobs):
            if r.get("error"):
                print(f"FAIL {r['file']}: {r['error']}", flush=True)
            else:
                m = sum(c["missing"] for c in r["channels"].values())
                u = sum(c["unclassified"] for c in r["channels"].values())
                print(f"done {r['file']}: {r['stages']} stages, missing {m}, unclassified {u}, "
                      f"{r['failed_n']} failed pages, {r['seconds']}s", flush=True)
    print("ALL DONE", flush=True)


def _safe(job):
    try:
        return one(job)
    except Exception as e:
        return {"file": os.path.basename(job[1]), "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    main()
