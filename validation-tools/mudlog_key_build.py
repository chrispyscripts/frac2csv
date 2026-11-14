"""Write the mudlog answer key (mudlog_key.py) for every WellSight log in a
folder that has its LogViewer printout beside it.

    python3 validation-tools/mudlog_key_build.py /Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl ~/dev/wellsight-answer-key --jobs 6

OUT gets one <log>.key.json.gz per log, at the log's path under FOLDER;
index.jsonl, one line per log as it is done (a run stopped part way picks up
where it left off); and, at the end, index.csv and summary.json.

Only a printout as LogViewer printed it is used; one turned or stacked by
hand is not an answer sheet for a reader of the original. The keys hold the
logs' data, well names and all: keep OUT off the repository and out of any
synced folder.
"""
import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

EXTS = (".sl6", ".slg", ".hl6", ".hlg")
FIELDS = ["log", "printout", "status", "reason", "printout_ok", "pages", "log_pages", "labels_within_0.1m",
          "gaps", "tracks", "tracks_snapped", "curves", "curves_known", "rocks", "symbols", "intervals", "text",
          "header_fields", "seconds"]


def _one(args):
    root, out, rel = args
    import mudlog_key as K
    import wellsight_library as L
    t = time.time()
    row = {"log": rel, "printout": "", "status": "", "reason": ""}
    try:
        ix = L.index(root)
        pdf, kind = L.find(ix, os.path.basename(rel))
        if not pdf or kind != "print":
            row.update(status="no_printout", reason=kind if pdf else "none found")
            return row
        row["printout"] = os.path.relpath(pdf, root)
        key = K.build(os.path.join(root, rel), pdf, rel, row["printout"])
        K.save(key, os.path.join(out, rel + ".key.json.gz"))
        po = key["printout"]
        ck = po.get("check") or {}
        row.update(status="ok" if po.get("ok") else "printout_doubtful" if "error" not in po else "printout_unread",
                   reason=po.get("error", ""), printout_ok=po.get("ok"), pages=po.get("pages"),
                   log_pages=len(po.get("log_pages") or []), **{"labels_within_0.1m": ck.get("within_0.1m")},
                   gaps=len(po.get("gaps") or []), tracks=len(key["tracks"]),
                   tracks_snapped=sum(1 for x in key["tracks"] if x["snapped"]), curves=len(key["curves"]),
                   curves_known=sum(1 for c in key["curves"] if c["kind"]), rocks=len(key["rocks"]),
                   symbols=len(key["symbols"]), intervals=len(key["intervals"]), text=len(key["text"]),
                   header_fields=len(key["header"]))
    except K.Skip as e:
        row.update(status=e.args[0], reason=e.args[1])
    except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
        row.update(status="error", reason="%s: %s" % (type(e).__name__, e))
    row["seconds"] = round(time.time() - t, 2)
    return row


def _refresh_one(args):
    root, path, printed_only = args
    import mudlog_key as K
    try:
        key = K.load(path)
        if not printed_only:
            K.refresh_curves(key, os.path.join(root, key["log"]["file"]))
        if (key.get("printout") or {}).get("log_pages"):
            K.mark_printed(key, os.path.join(root, key["printout"]["file"]))
        K.save(key, path)
        return "ok", sum(1 for c in key["curves"] if c.get("scale")), len(key["curves"]), \
            sum(1 for c in key["curves"] if c.get("wraps"))
    except Exception as e:  # noqa: BLE001 - one bad key must not stop the run
        return "%s: %s" % (type(e).__name__, e), 0, 0, 0


def refresh(root, out, jobs, limit=None, printed_only=False):
    paths = []
    for dp, _dirs, files in os.walk(out):
        paths += [os.path.join(dp, f) for f in files if f.endswith(".key.json.gz")]
    paths.sort()
    if limit:
        paths = paths[:limit]
    print("%d keys to refresh" % len(paths), flush=True)
    done, scaled, curves, wrapped, errs = 0, 0, 0, 0, []
    with ProcessPoolExecutor(jobs) as ex:
        for st, s, n, w in ex.map(_refresh_one, [(root, p, printed_only) for p in paths], chunksize=8):
            done += 1
            scaled, curves, wrapped = scaled + s, curves + n, wrapped + w
            if st != "ok":
                errs.append(st)
            if done % 1000 == 0:
                print("%d / %d" % (done, len(paths)), flush=True)
    print(json.dumps({"keys": done, "curves": curves, "with_printed_scale": scaled, "wrapped_somewhere": wrapped,
                      "errors": len(errs), "first_errors": errs[:5]}, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, help="stop after this many logs (a trial run)")
    ap.add_argument("--refresh-curves", action="store_true",
                    help="write the curves of the keys already in OUT again from their logs (printed "
                         "scales and wraps), without stitching the printouts again")
    ap.add_argument("--refresh-printed", action="store_true",
                    help="mark which curves of the keys already in OUT their printouts print (by caption)")
    a = ap.parse_args(argv)
    root, out = os.path.abspath(os.path.expanduser(a.folder)), os.path.abspath(os.path.expanduser(a.out))
    if a.refresh_curves or a.refresh_printed:
        return refresh(root, out, a.jobs, a.limit, printed_only=a.refresh_printed and not a.refresh_curves)
    os.makedirs(out, exist_ok=True)
    jl = os.path.join(out, "index.jsonl")
    done = set()
    if os.path.exists(jl):
        for line in open(jl, encoding="utf-8"):
            try:
                done.add(json.loads(line)["log"])
            except (ValueError, KeyError):
                pass
    logs = []
    for dp, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$")))
        for f in sorted(files):
            if f.lower().endswith(EXTS) and not f.startswith("._"):
                rel = os.path.relpath(os.path.join(dp, f), root)
                if rel not in done:
                    logs.append(rel)
    if a.limit:
        logs = logs[:a.limit]
    print("%d logs to do (%d done before)" % (len(logs), len(done)), flush=True)
    t0, n = time.time(), 0
    with ProcessPoolExecutor(a.jobs) as ex, open(jl, "a", encoding="utf-8") as f:
        futs = [ex.submit(_one, (root, out, rel)) for rel in logs]
        for fu in as_completed(futs):
            f.write(json.dumps(fu.result()) + "\n")
            f.flush()
            n += 1
            if n % 250 == 0:
                print("%d / %d  %.0f s" % (n, len(logs), time.time() - t0), flush=True)
    rows = [json.loads(line) for line in open(jl, encoding="utf-8")]
    rows.sort(key=lambda r: r["log"])
    with open(os.path.join(out, "index.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    status = {}
    for r in rows:
        status[r["status"]] = status.get(r["status"], 0) + 1
    ok = [r for r in rows if r.get("tracks")]
    summary = {"schema": "frac2csv/mudlog-key/1", "folder": root, "logs": len(rows), "status": status,
               "tracks": sum(r["tracks"] for r in ok), "tracks_snapped": sum(r["tracks_snapped"] for r in ok),
               "curves": sum(r.get("curves") or 0 for r in rows),
               "curves_known": sum(r.get("curves_known") or 0 for r in rows),
               "rocks": sum(r.get("rocks") or 0 for r in rows), "symbols": sum(r.get("symbols") or 0 for r in rows),
               "text": sum(r.get("text") or 0 for r in rows), "at": time.strftime("%Y-%m-%d %H:%M")}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
