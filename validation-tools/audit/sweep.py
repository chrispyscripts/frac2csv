"""Audit a folder of reports, any provider, into one report.

    python3 validation-tools/audit/sweep.py <out-dir> <pdf-or-folder>... [-j N] [--cached-only]

Each PDF is read the way the Lab reads it. Where the Lab already holds a
result for this exact file and this code, that result is audited and nothing
is read again; otherwise the file is extracted and the result stored where
the Lab looks, so opening it in the Lab afterwards is instant. --cached-only
audits what the Lab holds and skips the rest. -j is how many files extract at
once (default 2: a big STEP book takes over 1 GB).

Writes
  <out>/<name>-findings.json   one file's findings (audit.audit_stages)
  <out>/audit.json             every file's counts, for a before/after
  <out>/audit.md               one report: what was found, where, file by file

sweep.sh is the older two-at-a-time loop over audit.py and still works; this
one shares the Lab's cache and writes the one report.
"""
import json
import os
import subprocess
import sys
import time
from collections import Counter
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# what each warning means, for the reader of the report
MEANS = {
    "stage.missing": "a stage number the charts skip, or one the report's stage table pumps and no chart carries",
    "stage.single": "every chart of a template carries one stage: the number was read once, not per page",
    "stage.unknown": "a stage-length chart with no stage number (\"Stage ?\" in the Lab)",
    "stage.failed": "a chart page the reader gave up on",
    "stage.doubled": "one stage label produced twice by one template",
    "clock.overlap": "a stage starts before the one before it finished",
    "clock.backwards": "a stage starts before the one before it started",
    "clock.absent": "a chart with no start time where the page prints a clock",
    "clock.in-table": "the stage table prints a start the chart does not carry",
    "clock.none": "no chart of a template carries a clock",
    "channel.absent": "a channel the template's other charts carry is missing here",
    "channel.empty": "a channel present but holding nothing",
    "channel.sparse": "a quarter or more of a stage missing mid-flight",
    "gap.missing": "a run of a curve not read, mid-range on both sides",
    "gap.hold": "a curve dropped wherever it held level",
    "flat.rule": "a run pinned to one value: a rule read as data",
    "spike": "excursions in and out within seconds: a glyph or gridline read as curve",
    "spike.aligned": "the same second spikes on 3+ channels",
    "peak.off-axis": "a value above the printed axis",
    "peak.pinned": "30 s or more at full scale",
    "pair.disagree": "WH and BH Prop Conc peaks disagree",
    "pair.coverage": "one of the WH/BH pair carries far less of the stage",
}
ORDER = list(MEANS)


def pdfs(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            for d, _, fs in os.walk(a):
                out += [os.path.join(d, f) for f in fs if f.lower().endswith(".pdf")]
        elif a.lower().endswith(".pdf"):
            out.append(a)
    return sorted({os.path.abspath(p) for p in out}, key=os.path.basename)


def provider(stages):
    srcs = Counter((st.get("source") or "?").replace(" (raster)", "").replace(" chart", "")
                   for st in stages)
    return ", ".join(k for k, _ in srcs.most_common(3))


def one(job):
    path, out_dir, cached_only = job
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import fitz
    import audit
    import localapp
    name = os.path.splitext(os.path.basename(path))[0]
    rec = {"file": os.path.basename(path), "name": name}
    t0 = time.time()
    try:
        hit = localapp.cache_get(path)
        rec["cached"] = hit is not None
        if hit is None:
            if cached_only:
                rec["skipped"] = "not in the Lab's cache for this code"
                return rec
            stages, tables, notes, _w, summary, _d = localapp.process_path(path, write=False)
            hit = {"stages": stages, "tables": tables, "notes": notes, "summary": summary}
            localapp.cache_put(path, hit)
        stages = hit.get("stages") or []
        with fitz.open(path) as doc:
            audit.clock_hints(stages, doc)
        res = audit.audit_stages(stages, hit.get("notes"), hit.get("tables"))
    except Exception as e:  # noqa: BLE001 — one bad file must not stop a sweep
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec
    warn = [f for f in res["findings"] if f["severity"] == audit.WARN]
    with open(os.path.join(out_dir, name + "-findings.json"), "w") as f:
        json.dump({"file": rec["file"], **res}, f, indent=1, default=str)
    rec.update(seconds=round(time.time() - t0, 1), provider=provider(stages),
               charts=len(stages), ladder=res["ladder"],
               warn=Counter(f["kind"] for f in warn),
               info=Counter(f["kind"] for f in res["findings"] if f["severity"] != audit.WARN),
               # the file-level findings in full; per-chart ones by kind below
               detail=[{"kind": f["kind"], "stage": f["stage"], "channel": f["channel"],
                        "page": f.get("page"), "evidence": f["evidence"]} for f in warn])
    return rec


def code_version():
    sys.path.insert(0, ROOT)
    from version import VERSION
    try:
        sha = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
    return f"v{VERSION}" + (f" ({sha})" if sha else "")


def report(recs, version):
    done = [r for r in recs if "warn" in r]
    clean = [r for r in done if not r["warn"]]
    L = [f"# Audit: {len(recs)} file(s)", "",
         f"Code {version}, {time.strftime('%Y-%m-%d %H:%M')}. "
         f"{sum(1 for r in done if r.get('cached'))} read from the Lab's cache, "
         f"{sum(1 for r in done if not r.get('cached'))} extracted. "
         f"**{len(clean)} with no warnings, {len(done) - len(clean)} with at least one.**", ""]
    bad = [r for r in recs if "warn" not in r]
    if bad:
        L += ["Not audited: " + "; ".join(f"{r['file']} ({r.get('error') or r.get('skipped')})"
                                          for r in bad), ""]
    kinds = Counter()
    files = Counter()
    for r in done:
        kinds.update(r["warn"])
        files.update(set(r["warn"]))
    L += ["## What was found", "", "| Finding | Files | Count | Means |", "|---|---|---|---|"]
    for k in sorted(kinds, key=lambda k: (ORDER.index(k) if k in ORDER else 99, k)):
        L.append(f"| `{k}` | {files[k]} | {kinds[k]} | {MEANS.get(k, '')} |")
    L += ["", "## File by file", "",
          "| File | Provider | Charts | Stages (numbered / top) | Warnings | Kinds |",
          "|---|---|---|---|---|---|"]
    for r in done:
        lad = r["ladder"]
        ks = ", ".join(f"{k} {n}" for k, n in r["warn"].most_common())
        L.append(f"| {r['name'][:40]} | {r['provider']} | {r['charts']} | "
                 f"{lad['numbered']} / {lad['max']} | {sum(r['warn'].values())} | {ks or '—'} |")
    L += ["", "## Detail", ""]
    for r in done:
        if not r["warn"]:
            continue
        L.append(f"### {r['file']}")
        L.append("")
        by = {}
        for f in r["detail"]:
            by.setdefault(f["kind"], []).append(f)
        for k in sorted(by, key=lambda k: (ORDER.index(k) if k in ORDER else 99, k)):
            fs = by[k]
            for f in fs[:4]:
                where = f"stage {f['stage']}" if f["stage"] else "file"
                where += f" p{f['page']}" if f.get("page") else ""
                where += f" · {f['channel']}" if f["channel"] else ""
                L.append(f"- `{k}` {where}: {f['evidence']}")
            if len(fs) > 4:
                L.append(f"- `{k}` … and {len(fs) - 4} more")
        L.append("")
    return "\n".join(L) + "\n"


def main(argv):
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    jobs = 2
    if "-j" in argv:
        i = argv.index("-j")
        jobs = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    cached_only = "--cached-only" in argv
    argv = [a for a in argv if a != "--cached-only"]
    out_dir, paths = argv[0], pdfs(argv[1:])
    os.makedirs(out_dir, exist_ok=True)
    print(f"{len(paths)} PDF(s) → {out_dir}", flush=True)
    recs = []
    with Pool(jobs, maxtasksperchild=1) as pool:
        for r in pool.imap_unordered(one, [(p, os.path.abspath(out_dir), cached_only) for p in paths]):
            state = (r.get("error") or r.get("skipped")
                     or f"{sum(r['warn'].values())} warning(s), {r['seconds']}s"
                        + (" (cached)" if r.get("cached") else ""))
            print(f"{time.strftime('%H:%M:%S')} {r['name'][:40]}: {state}", flush=True)
            recs.append(r)
    recs.sort(key=lambda r: r["file"])
    with open(os.path.join(out_dir, "audit.json"), "w") as f:
        json.dump(recs, f, indent=1, default=str)
    with open(os.path.join(out_dir, "audit.md"), "w") as f:
        f.write(report(recs, code_version()))
    print(os.path.join(out_dir, "audit.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
