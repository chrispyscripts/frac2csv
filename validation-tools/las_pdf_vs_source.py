"""Test cases: each log's LAS from its printout PDF alone against its LAS
from the log file, both made the way the Lab's Save LAS makes them.

    python3 validation-tools/las_pdf_vs_source.py ~/dev/wellsight-answer-key /Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl ~/dev/las-compare --per 12 --jobs 7

Cases are chosen by kind of log, from logs the PDF reader was not tuned on
(every 28th log, the one it was marked on while built, is left out):

  strip_md       strip logs on measured depth, up to four curves, one scale
  tvd_gamma      TVD gamma logs (a strip log with "TVD" in its name)
  horizontal     horizontal logs (printed sideways)
  scale_change   a curve's printed scale changes down the log
  heavy_wrap     curves run past their printed scale 20 or more times
  reversed       a curve printed high value on the left
  many_curves    five or more printed curves
  chromatograph  gas broken into C1 ... C5
  large_scale    printed at 30 pt a metre or more (core logs, 1:48)
  long           20 or more pages of log
  control        any log, at random

--exclude names an earlier batch's cases.csv, so a new batch (another
--seed) is logs no batch has seen.

For each case: wellsight_server.decode + save writes OUT/las/source/<name>.las,
decode_pdf + save writes OUT/las/pdf/<name>.from-printout.las, and
las_compare.compare marks one against the other, each difference as a
share of the curve's printed scale width (from the answer key), with its
cause. OUT gets cases.csv, curves.csv (one row per source curve), logs.csv,
results.json and summary.json. The LAS files and the tables hold well names:
OUT stays out of the repository.
"""
import argparse
import base64
import collections
import csv
import json
import os
import random
import re
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

SUFFIX = ".key.json.gz"
GAS_SPLIT = re.compile(r"\bC[1-5]\b|methane|ethane|propane|butane|pentane", re.I)
CATS = ("strip_md", "tvd_gamma", "horizontal", "scale_change", "heavy_wrap", "reversed", "many_curves",
        "chromatograph", "large_scale", "long", "control")


def features(path):
    import mudlog_key as K
    try:
        k = K.load(path)
    except Exception:  # noqa: BLE001
        return None
    po = k.get("printout") or {}
    cs = [c for c in k.get("curves") or [] if c.get("printed") and sum(v is not None for v in c["values"]) >= 10]
    name = os.path.basename(k["log"]["file"])
    return {"log": k["log"]["file"], "printout": po.get("file"), "kind": k["log"]["file"].split("/")[0],
            "tvd": "TVD" in name.upper(), "curves": len(cs),
            "scale_change": any(len(c.get("scale") or []) > 1 for c in cs),
            "wraps": sum(len(c.get("wraps") or []) for c in cs),
            "reversed": any(s[1] > s[2] for c in cs for s in c.get("scale") or []),
            "chromatograph": any(GAS_SPLIT.search(c["name"] or "") for c in cs),
            "ppm": po.get("pt_per_m") or 0, "pages": len(po.get("log_pages") or [])}


def category_test(cat, f):
    return {"strip_md": f["kind"] == "SLG" and not f["tvd"] and f["curves"] <= 4 and not f["scale_change"]
            and not f["reversed"],
            "tvd_gamma": f["kind"] == "SLG" and f["tvd"],
            "horizontal": f["kind"] == "HLG",
            "scale_change": f["scale_change"],
            "heavy_wrap": f["wraps"] >= 20,
            "reversed": f["reversed"],
            "many_curves": f["curves"] >= 5,
            "chromatograph": f["chromatograph"],
            "large_scale": f["ppm"] >= 30,
            "long": f["pages"] >= 20,
            "control": True}[cat]


def choose(keys, per, seed, jobs, exclude=()):
    import mudlog_pdf_read as R
    dev = {rel for _p, rel in R.keys_under(keys, every=28)} | set(exclude)
    todo = [(p, rel) for p, rel in R.keys_under(keys) if rel not in dev]
    feats = []
    with ProcessPoolExecutor(jobs) as ex:
        for f in ex.map(features, [p for p, _r in todo], chunksize=32):
            if f and f["curves"] and f["printout"]:
                feats.append(f)
    rnd = random.Random(seed)
    picked, seen = [], set()
    for cat in CATS:
        pool = [f for f in feats if category_test(cat, f) and f["log"] not in seen]
        rnd.shuffle(pool)
        for f in pool[:per]:
            seen.add(f["log"])
            picked.append(dict(f, category=cat))
    return picked, len(feats)


def _keep(folder, _dest):
    return folder, ""


def run_case(args):
    case, keys, root, out = args
    import mudlog_key as K
    import wellsight_server as wss
    import las_compare as C
    t0 = time.time()
    rel = case["log"]
    res = {"log": rel, "category": case["category"]}
    try:
        key = K.load(os.path.join(keys, rel + SUFFIX))
        sdir = os.path.join(out, "las", "source", os.path.dirname(rel))
        pdir = os.path.join(out, "las", "pdf", os.path.dirname(rel))
        os.makedirs(sdir, exist_ok=True)
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(root, rel), "rb") as f:
            data = f.read()
        code, r = wss.decode({"filename": os.path.basename(rel), "data": base64.b64encode(data).decode()})
        code, s = wss.save({"id": r["id"], "folder": sdir}, _keep)
        if code != 200:
            return dict(res, status="no source LAS: " + s.get("error", str(code)))
        t1 = time.time()
        with open(os.path.join(root, case["printout"]), "rb") as f:
            pdf = f.read()
        try:
            pr = wss.decode_pdf(pdf, os.path.basename(rel).rsplit(".", 1)[0] + ".pdf")
        except Exception as e:  # noqa: BLE001
            return dict(res, status="PDF not read: %s" % e)
        code, p = wss.save({"id": pr["id"], "folder": pdir}, _keep)
        if code != 200:
            return dict(res, status="no PDF LAS: " + p.get("error", str(code)))
        t2 = time.time()
        with open(os.path.join(sdir, s["written"][0]), encoding="utf-8", errors="replace") as f:
            S = C.read_las(f.read())
        with open(os.path.join(pdir, p["written"][0]), encoding="utf-8", errors="replace") as f:
            P = C.read_las(f.read())
        scales = {C._norm(c["name"]): [tuple(x) for x in c["scale"]] for c in key.get("curves") or []
                  if c.get("scale")}
        printed = {C._norm(c["name"]): c.get("printed") for c in key.get("curves") or []}
        cmp = C.compare(S, P, scales)
        for c in cmp["curves"]:
            c["printed"] = printed.get(C._norm(c["name"]))
        res.update(status="ok", compare=cmp, seconds_source=round(t1 - t0, 2), seconds_pdf=round(t2 - t1, 2),
                   source_las=s["written"][0], pdf_las=p["written"][0])
        return res
    except Exception as e:  # noqa: BLE001 - one bad case must not stop the run
        return dict(res, status="error %s: %s" % (type(e).__name__, e))


def pct(x):
    return "" if x is None else round(100 * x, 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keys")
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--per", type=int, default=12, help="cases per category")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--exclude", action="append", default=[],
                    help="a cases.csv of an earlier batch: its logs are not chosen again (repeatable)")
    a = ap.parse_args(argv)
    keys, root, out = (os.path.expanduser(x) for x in (a.keys, a.root, a.out))
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    exclude = set()
    for path in a.exclude:
        with open(os.path.expanduser(path), newline="", encoding="utf-8") as f:
            exclude |= {r["log"] for r in csv.DictReader(f)}
    cases, pool = choose(keys, a.per, a.seed, a.jobs, exclude)
    with open(os.path.join(out, "cases.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cases[0]))
        w.writeheader()
        w.writerows(cases)
    print("%d cases from %d logs (%.0f s)" % (len(cases), pool, time.time() - t0), flush=True)
    results = []
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(run_case, (c, keys, root, out)) for c in cases]
        for i, fu in enumerate(as_completed(futs), 1):
            results.append(fu.result())
            if i % 20 == 0:
                print(i, "/", len(cases), flush=True)
    results.sort(key=lambda r: (CATS.index(r["category"]), r["log"]))
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f)

    # one row per source curve
    rows = []
    for r in results:
        for c in (r.get("compare") or {}).get("curves") or []:
            rows.append({"log": r["log"], "category": r["category"], "curve": c["name"], "kind": c["kind"] or "",
                         "printed": c["printed"], "paired_with": c["pdf"] or "", "readings": c["n"],
                         "coverage_pct": pct(c["coverage"]), "lag_m": c["lag_m"],
                         "within_1pct": pct(c["within_1"]), "within_2pct": pct(c["within_2"]),
                         "median_err_pct": pct(c["median"]), "mae_pct": pct(c["mae"]), "p95_err_pct": pct(c["p95"]),
                         "max_err_pct": pct(c["max"]), "bias_pct": pct(c["bias"]),
                         **{"n_" + k: v for k, v in c["causes"].items()}})
    with open(os.path.join(out, "curves.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    logs = []
    for r in results:
        cm = r.get("compare") or {}
        cs = [c for c in cm.get("curves") or [] if c["pdf"]]
        n = sum(c["n"] for c in cm.get("curves") or [])
        logs.append({"log": r["log"], "category": r["category"], "status": r["status"],
                     "source_curves": len(cm.get("curves") or []), "paired": len(cs),
                     "extra_pdf_curves": "; ".join(cm.get("extra") or []),
                     "within_2pct": pct(sum(c["within_2"] * c["n"] for c in cm.get("curves") or []) / n) if n else "",
                     "header": "; ".join("%s %s" % (k, v) for k, v in (cm.get("header") or {}).items() if v != "same"),
                     "source_range": cm.get("depth", {}).get("source"), "pdf_range": cm.get("depth", {}).get("pdf"),
                     "seconds_pdf": r.get("seconds_pdf")})
    with open(os.path.join(out, "logs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(logs[0]))
        w.writeheader()
        w.writerows(logs)

    # summary
    ok = [r for r in results if r["status"] == "ok"]
    allc = [c for r in ok for c in r["compare"]["curves"]]
    printed = [c for c in allc if c["printed"] is not False]

    def agg(cs):
        n = sum(c["n"] for c in cs)
        if not n:
            return None
        causes = collections.Counter()
        for c in cs:
            causes.update(c["causes"])
        lags = [c["lag_m"] for c in cs if c["pdf"]]
        return {"curves": len(cs), "paired": sum(1 for c in cs if c["pdf"]), "readings": n,
                "within_1pct": round(sum(c["within_1"] * c["n"] for c in cs) / n, 4),
                "within_2pct": round(sum(c["within_2"] * c["n"] for c in cs) / n, 4),
                "coverage": round(sum(c["coverage"] * c["n"] for c in cs) / n, 4),
                "median_curve_within_2pct": round(statistics.median(c["within_2"] for c in cs), 4),
                "lag_m_median": statistics.median(lags) if lags else None,
                "lag_m_counts": dict(collections.Counter(lags).most_common(5)),
                "off_by_cause": {k: round(v / n, 4) for k, v in causes.items()}}
    summary = {"cases": len(cases), "read": len(ok),
               "not_read": dict(collections.Counter(r["status"] for r in results if r["status"] != "ok")),
               "all_printed_curves": agg(printed),
               "unprinted_curves_in_log": len(allc) - len(printed),
               "by_category": {cat: agg([c for r in ok if r["category"] == cat for c in r["compare"]["curves"]
                                         if c["printed"] is not False]) for cat in CATS},
               "by_kind": {k: agg(v) for k, v in sorted(collections.defaultdict(list, {
                   kk: [c for c in printed if (c["kind"] or "unknown") == kk]
                   for kk in {c["kind"] or "unknown" for c in printed}}).items(), key=lambda kv: -len(kv[1]))},
               "header": {f: dict(collections.Counter(r["compare"]["header"][f] for r in ok))
                          for f in ("well name", "licence", "UWI", "location", "operator")},
               "extra_pdf_curves": sum(len(r["compare"]["extra"]) for r in ok),
               "seconds": round(time.time() - t0, 1)}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: summary[k] for k in ("cases", "read", "not_read", "all_printed_curves", "seconds")},
                     indent=1))


if __name__ == "__main__":
    main()
