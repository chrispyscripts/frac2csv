"""Run every file in a set of batch lists through the desktop app's own call
chain and say what came out — charts, tables, nothing, or a failure — and
WHY for the ones that came back empty.

    python3 validation-tools/quickpass.py --lists ../batch-lists/aer-new-2026-09-14 --out quickpass.jsonl --workers 6
    python3 validation-tools/quickpass.py --summary quickpass.jsonl

Resumable: files already in the JSONL are skipped. Paths in the lists are
Carmine's drive letters; F:\\ is the SSD here.
"""
import argparse
import glob
import json
import os
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
DRIVES = {"F:\\": "/Volumes/CnC-2TB-ssd/", "K:\\": "/Volumes/For-Chris-CnC-1TB/",
          "A:\\": "/Volumes/CnC-2TB-ssd/"}


def local_path(p):
    for d, m in DRIVES.items():
        if p.upper().startswith(d):
            return m + p[len(d):].replace("\\", "/")
    return p.replace("\\", "/")


def read_lists(folder):
    out = []
    for lst in sorted(glob.glob(os.path.join(folder, "*.txt"))):
        vendor = os.path.basename(lst).split("__")[1] if "__" in os.path.basename(lst) else "?"
        for line in open(lst, encoding="utf-8", errors="replace"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or not parts[1].strip():
                continue
            out.append({"list": os.path.basename(lst), "vendor": vendor,
                        "uwi": parts[0].strip(), "path": local_path(parts[1].strip())})
    return out


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout()


def run_one(item, limit_s=1500):
    import fitz
    import localapp
    import pipeline
    t0 = time.time()
    row = dict(item, file=os.path.basename(item["path"]))
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(limit_s)
    try:
        doc = fitz.open(item["path"])
        row["pages"] = len(doc)
        results, notes = pipeline.extract_document(doc, filename=row["file"])
        stages, tables, notes, summary = localapp.serialize(results, notes)
        doc.close()
        srcs = {}
        for s in stages:
            srcs[s.get("source", "?")] = srcs.get(s.get("source", "?"), 0) + 1
        row.update(stages=len(stages), tables=len(tables), sources=srcs,
                   table_titles=[t.get("title", "")[:50] for t in tables][:4],
                   notes=[str(n)[:300] for n in notes][:12],
                   empty=(not stages and not tables))
    except Timeout:
        row.update(error=f"timeout after {limit_s} s")
    except Exception as e:                      # noqa: BLE001 - a survey records, it does not stop
        row.update(error=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        signal.alarm(0)
    row["seconds"] = round(time.time() - t0, 1)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists")
    ap.add_argument("--out")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--summary")
    a = ap.parse_args()
    if a.summary:
        return summary(a.summary)
    items = read_lists(a.lists)
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            try:
                done.add(json.loads(line)["path"])
            except (ValueError, KeyError):
                pass
    todo = [i for i in items if i["path"] not in done and os.path.exists(i["path"])]
    missing = [i for i in items if not os.path.exists(i["path"])]
    print(f"{len(items)} listed, {len(done)} done, {len(todo)} to run, {len(missing)} not on disk", flush=True)
    with open(a.out, "a") as out, ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, i): i for i in todo}
        for n, f in enumerate(as_completed(futs), 1):
            row = f.result()
            out.write(json.dumps(row) + "\n"); out.flush()
            tag = row.get("error") or ("EMPTY" if row.get("empty") else f"{row.get('stages')} charts, {row.get('tables')} tables")
            print(f"[{n}/{len(todo)}] {row['vendor']:<12} {row['file'][:48]:<48} {row.get('pages', '-'):>4}p {row['seconds']:>6.0f}s  {tag}", flush=True)
    print("done", flush=True)


def summary(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    by = {}
    for r in rows:
        b = by.setdefault(r["vendor"], {"files": 0, "charts": 0, "tables_only": 0, "empty": 0, "error": 0, "secs": 0.0})
        b["files"] += 1; b["secs"] += r.get("seconds", 0)
        if r.get("error"): b["error"] += 1
        elif r.get("stages"): b["charts"] += 1
        elif r.get("tables"): b["tables_only"] += 1
        else: b["empty"] += 1
    print(f"{'vendor':<12} {'files':>5} {'charts':>6} {'tables only':>11} {'empty':>5} {'error':>5}  avg s")
    for v, b in sorted(by.items(), key=lambda kv: -kv[1]["files"]):
        print(f"{v:<12} {b['files']:>5} {b['charts']:>6} {b['tables_only']:>11} {b['empty']:>5} {b['error']:>5}  {b['secs'] / max(1, b['files']):5.0f}")
    print("\nempty or failed, with the reader's reason:")
    for r in rows:
        if r.get("error") or r.get("empty") or not r.get("stages"):
            why = r.get("error") or next((n for n in r.get("notes", []) if n.startswith("No extractable")), "") \
                or "; ".join(r.get("notes", [])[:2])
            print(f"  {r['vendor']:<12} {r['file'][:52]:<52} {r.get('pages', '-'):>4}p  {'' if r.get('stages') else ('tables:' + str(r.get('tables')) + ' ') if r.get('tables') else ''}{why[:230]}")


if __name__ == "__main__":
    main()
