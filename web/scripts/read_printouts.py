#!/usr/bin/env python3
"""Mud-log printouts read to LAS, and their logs for FracView.

The printouts are lithology-log PDFs as filed with Saskatchewan (file names
like <seq>-<UWI>.<licence>--SK<doc>_LAT_LITH_LOG_<date>-<maker>.PDF). Most
have no WellSight file to decode, so their curves, rocks and shows are read
off the printout by the Lab's reader (mudlog_pdf_app, the EXE's "LAS
extraction" for a PDF on its own). None of this is public data: it reads and
writes outside the repo.

  read     every printout in the folders given -> OUT/<stem>.las (the curves)
           and OUT/<stem>.json (the reading FracView needs: depth, curves on
           their step, rocks, shows, notes). A printout stitched into one page
           (a "-Stitch" copy) is read in place of its paged copy when both are
           given: its legend names the rocks the paged copy's often cannot.
  attach   (build_viking.py --printouts OUT) each well with no WellSight log
           gets its printouts' logs, binned along MD as build_sk.py bins a
           WellSight log's.

Usage:
  python3 -I web/scripts/read_printouts.py read --out ~/dev/viking-printouts DIR [DIR ...]
"""
import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

HOME = os.path.expanduser("~")
LAB = os.path.join(HOME, "dev", "frac-wt", "wellsight")
NAME = re.compile(r"^(\d+)-(\w{16})\.(_+)(\w+?)--SK(\d+)_LAT_LITH_LOG_(\d{8})-(WLS|TRI|GEO)(-Stitch)?\.PDF$", re.I)
SHOW_RANK = {"dead": 0, "questionable": 1, "trace": 1, "poor": 1, "weak": 1, "spotty": 2, "fair": 2,
             "moderate": 3, "good": 4, "strong": 4, "excellent": 4}


def parse_name(fn):
    m = NAME.match(os.path.basename(fn))
    if not m:
        return None
    return {"seq": m.group(1), "uwi": m.group(2).upper(), "licence": m.group(4).upper(), "doc": m.group(5),
            "date": m.group(6), "maker": m.group(7).upper(), "stitched": bool(m.group(8))}


def _read_one(path, out):
    sys.path.insert(0, LAB)
    import mudlog_pdf_app as mpa
    t0 = time.time()
    stem = os.path.splitext(os.path.basename(path))[0]
    rec = {"file": os.path.basename(path), **(parse_name(path) or {})}
    try:
        res = mpa.read(open(path, "rb").read(), os.path.basename(path))
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error="%s: %s" % (type(e).__name__, str(e)[:300]), seconds=round(time.time() - t0, 1))
        json.dump(rec, open(os.path.join(out, stem + ".json"), "w"))
        return rec["file"], False
    pl, rd = res["payload"], res.get("reading") or {}
    curves = []
    for c in rd.get("curves") or []:
        curves.append({"name": c.get("name"), "kind": c.get("kind"), "unit": c.get("unit"), "top": c.get("top"),
                       "step": c.get("step"), "values": [None if v is None else round(v, 3) for v in c.get("values") or []]})
    rec.update(ok=True, depth=rd.get("depth"), printout=rd.get("printout"), curves=curves,
               rocks=[{"top": r["top"], "base": r["base"], "rock": r["rock"], "name": r.get("name") or r["rock"]}
                      for r in pl.get("rocks") or []],
               shows=[{"depth": s["depth"], "term": s["term"]} for s in pl.get("symbols") or [] if s.get("group") == "show"],
               notes=list((rd.get("notes") or [])), seconds=round(time.time() - t0, 1))
    if res.get("las"):
        las = res["las"]
        with open(os.path.join(out, stem + ".las"), "wb") as f:
            f.write(las if isinstance(las, bytes) else las.encode())
    json.dump(rec, open(os.path.join(out, stem + ".json"), "w"), separators=(",", ":"))
    return rec["file"], True


def read_all(dirs, out, jobs=6, redo=False):
    os.makedirs(out, exist_ok=True)
    files = {}
    for d in dirs:
        for fn in sorted(os.listdir(d)):
            info = parse_name(fn)
            if not info:
                continue
            key = (info["uwi"], info["doc"], info["date"])           # one log, paged or stitched
            if key not in files or (info["stitched"] and not files[key][1]["stitched"]):
                files[key] = (os.path.join(d, fn), info)
    todo = [p for p, _ in files.values()
            if redo or not os.path.exists(os.path.join(out, os.path.splitext(os.path.basename(p))[0] + ".json"))]
    print("%d logs, %d to read" % (len(files), len(todo)), file=sys.stderr)
    done = Counter()
    with ProcessPoolExecutor(jobs) as ex:
        futs = [ex.submit(_read_one, p, out) for p in todo]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                _, ok = f.result()
            except Exception:  # noqa: BLE001
                ok = False
            done["read" if ok else "failed"] += 1
            if i % 100 == 0:
                print("%d/%d %s" % (i, len(todo), dict(done)), file=sys.stderr, flush=True)
    print("done: %s" % dict(done), file=sys.stderr)


# ---------------------------------------------------------------- attach

def attach(wells, folder, rep, bin_m=2.0):
    """wells with no log get their printouts' logs (build_sk.write's form)"""
    import build_sk
    from build_viking import lic_key
    build_sk.use_lab(LAB)
    by = defaultdict(list)
    for fn in sorted(os.listdir(folder)):
        if fn.endswith(".json"):
            r = json.load(open(os.path.join(folder, fn)))
            if r.get("ok") and r.get("licence"):
                by[lic_key(r["licence"])].append(r)
    rep["printout readings"] = sum(len(v) for v in by.values())
    for w in wells:
        if w.get("logs") or not w.get("key"):
            continue
        rs = by.get(lic_key(w["key"]))
        if not rs:
            continue
        binned = defaultdict(dict)      # type -> {bin: [values]}
        types, srcs, names = {}, [], {}
        for r in rs:
            for c in r["curves"]:
                k, title, unit = build_sk.curve_kind(c.get("name"), c.get("kind"))
                if not k or c.get("top") is None or not c.get("step"):
                    continue
                types.setdefault(k, {"t": title, "u": unit or c.get("unit") or ""})
                for i, v in enumerate(c["values"]):
                    if v is not None:
                        binned[k].setdefault(int(math.floor((c["top"] + i * c["step"]) / bin_m)), []).append(v)
            for rk in r["rocks"]:
                names[rk["rock"]] = rk.get("name") or rk["rock"]
                b0, b1 = int(math.floor(rk["top"] / bin_m)), int(math.floor(rk["base"] / bin_m))
                for b in range(b0, b1 + 1):
                    mid = (b + 0.5) * bin_m
                    if rk["top"] <= mid < rk["base"]:
                        binned["rock"].setdefault(b, []).append(rk["rock"])
            shows = sorted(r["shows"], key=lambda s: s["depth"])
            for j, s in enumerate(shows):
                lvl = SHOW_RANK.get(str(s["term"]).lower())
                if lvl is None:
                    continue
                end = shows[j + 1]["depth"] if j + 1 < len(shows) else s["depth"] + bin_m
                for b in range(int(math.floor(s["depth"] / bin_m)), int(math.floor(end / bin_m)) + 1):
                    binned["show"].setdefault(b, []).append(lvl)
            d = r.get("depth") or {}
            srcs.append({"log": "printout", "from": d.get("top"), "to": d.get("bottom"), "lith": bool(r["rocks"]),
                         "maker": r.get("maker"), "file": r["file"]})
        merged = {}
        for k, by_bin in binned.items():
            if k == "rock":
                merged[k] = {b: Counter(v).most_common(1)[0][0] for b, v in by_bin.items()}
            elif k == "show":
                merged[k] = {b: max(v) for b, v in by_bin.items()}
            else:
                merged[k] = {b: round(sum(v) / len(v), 3) for b, v in by_bin.items()}
        merged = {k: v for k, v in merged.items() if v}
        if not merged:
            rep["printouts with nothing to show (no curves, rocks or shows)"] += 1
            continue
        lo = min(min(v) for v in merged.values())
        hi = max(max(v) for v in merged.values())
        w["logs"] = {"bin": bin_m, "md0": lo * bin_m, "n": hi - lo + 1, "src": srcs,
                     "types": {k: [v.get(b) for b in range(lo, hi + 1)] for k, v in merged.items()}}
        w["types"] = {k: t for k, t in types.items() if k in merged}
        w["rock_names"] = {r: names.get(r, r) for r in set(merged.get("rock", {}).values())}
        w["notes"] = sorted({n for r in rs for n in r.get("notes") or []})
        w["well"]["logs"] = len(rs)
        w["well"]["log_from"] = "printout"
        rep["wells given logs read off their printouts"] += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("dirs", nargs="+")
    r.add_argument("--out", default=os.path.join(HOME, "dev", "viking-printouts"))
    r.add_argument("--jobs", type=int, default=6)
    r.add_argument("--redo", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "read":
        read_all([os.path.expanduser(d) for d in args.dirs], os.path.expanduser(args.out), args.jobs, args.redo)


if __name__ == "__main__":
    main()
