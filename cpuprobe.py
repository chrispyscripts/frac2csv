"""Where a read's CPU actually goes, per page and per call.

Carmine reported his machine pegged at 100% on v1.11.26. Nothing in the app
said which file, which page or which reader, so the answer had to come from a
profiler here rather than from his log — which is the gap this closes.

What it measures, in the order the answers usually arrive:

  * seconds per PAGE, so a 469-page filing that takes nine minutes can name
    the twelve pages that were most of it;
  * how many times the page's vector art was parsed. This is the number that
    found the actual defect: `page.get_drawings()` re-parses the content
    stream AND rebuilds every path into Python objects on each call, and lib1
    was asking thirteen times for the same page — the frame, the time grid,
    the value grid, the panel bands, then once per series for the ink.
    Measured on 00949 pp.97-100: 11.09s, of which 10.30s was inside
    get_drawings and only 1.54s of THAT was the C parse. The rest was five
    million fitz.Point constructions of geometry that cannot have changed;
  * CPU time against wall time, which says whether a slow read is working or
    waiting. A read that is pegged AND slow is ours; a read at 15% CPU is the
    drive.

Usage:

    python3 cpuprobe.py <file.pdf>              # per-page, slowest first
    python3 cpuprobe.py <file.pdf> --pages 1-40
    python3 cpuprobe.py <file.pdf> --profile    # + the hot functions
    python3 cpuprobe.py <folder> --top 20       # every PDF under a folder

Read-only: it opens files, reads pages and writes nothing.
"""
import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz                                                # noqa: E402

# Every module that reads a page. detect() is asked of each in turn, so a
# page that belongs to none of them still costs one detect apiece — which is
# itself worth seeing in the numbers.
READERS = ["lib1", "halliburton_ifs", "hal1", "slb", "trican_charts",
           "trican2", "canyon", "bj1", "sanjel", "step_vec", "step1",
           "calfrac_scan", "leucrotta", "peloton_frac", "sk_fracr",
           "ogc_datacapture"]


def _load():
    out = {}
    for name in READERS:
        try:
            out[name] = __import__(name)
        except Exception:
            pass
    return out


class ArtCounter:
    """Counts get_drawings() parses without changing what anything returns.

    Wraps the real Page method, so it counts what actually reached PyMuPDF —
    a cached accessor shows up here as the drop it is meant to be.
    """

    def __init__(self):
        self._orig = fitz.Page.get_drawings
        self.calls = 0
        self.paths = 0

    def __enter__(self):
        probe = self

        def counted(page, *a, **k):
            probe.calls += 1
            out = probe._orig(page, *a, **k)
            probe.paths += len(out)
            return out

        fitz.Page.get_drawings = counted
        return self

    def __exit__(self, *exc):
        fitz.Page.get_drawings = self._orig
        return False

    def reset(self):
        self.calls = self.paths = 0


def read_page(readers, page):
    """Put one page through the readers the way a real read does: ask each
    detect() in turn and extract with the first that claims it."""
    for name, mod in readers.items():
        try:
            if not hasattr(mod, "detect") or not mod.detect(page):
                continue
        except Exception:
            continue
        for fn in ("extract_page", "parse_page", "read_page"):
            if hasattr(mod, fn):
                try:
                    getattr(mod, fn)(page)
                except Exception:
                    pass
                return name
        return name
    return ""


def probe_file(path, readers, pages=None):
    doc = fitz.open(path)
    rows = []
    with ArtCounter() as art:
        for pno in range(len(doc)):
            if pages and (pno + 1) not in pages:
                continue
            art.reset()
            w0, c0 = time.perf_counter(), time.process_time()
            who = read_page(readers, doc[pno])
            wall = time.perf_counter() - w0
            cpu = time.process_time() - c0
            rows.append({"page": pno + 1, "wall": wall, "cpu": cpu,
                         "reader": who, "parses": art.calls,
                         "paths": art.paths})
    doc.close()
    return rows


def report(path, rows, top):
    wall = sum(r["wall"] for r in rows)
    cpu = sum(r["cpu"] for r in rows)
    parses = sum(r["parses"] for r in rows)
    read = [r for r in rows if r["reader"]]
    print(f"\n{os.path.basename(path)}")
    print(f"  {len(rows)} pages, {len(read)} read by a template")
    print(f"  wall {wall:7.1f}s   cpu {cpu:7.1f}s   "
          f"({100 * cpu / wall if wall else 0:.0f}% busy — "
          f"{'ours' if wall and cpu / wall > 0.7 else 'waiting on I/O'})")
    if read:
        print(f"  {wall / len(read):.2f}s per page read")
    print(f"  page art parsed {parses} times"
          + (f" ({parses / len(read):.1f}x per page read)" if read else ""))
    by = {}
    for r in read:
        b = by.setdefault(r["reader"], {"n": 0, "wall": 0.0})
        b["n"] += 1
        b["wall"] += r["wall"]
    if by:
        print("  by reader:")
        for name, b in sorted(by.items(), key=lambda kv: -kv[1]["wall"]):
            print(f"     {name:18s} {b['n']:4d} pages  {b['wall']:7.1f}s  "
                  f"{b['wall'] / b['n']:5.2f}s/page")
    worst = sorted(rows, key=lambda r: -r["wall"])[:top]
    if worst and worst[0]["wall"] > 0.05:
        print(f"  slowest {len(worst)}:")
        for r in worst:
            print(f"     p{r['page']:<5d} {r['wall']:6.2f}s  "
                  f"{r['reader'] or '(no template)':18s} "
                  f"art x{r['parses']:<3d} {r['paths']:,} paths")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="a PDF, or a folder of them")
    ap.add_argument("--pages", help="1-40 or 3,7,11")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--profile", action="store_true",
                    help="also print the hot functions")
    a = ap.parse_args()

    pages = None
    if a.pages:
        pages = set()
        for part in a.pages.split(","):
            if "-" in part:
                lo, hi = part.split("-")
                pages.update(range(int(lo), int(hi) + 1))
            else:
                pages.add(int(part))

    readers = _load()
    print(f"{len(readers)} readers loaded")
    targets = ([a.target] if a.target.lower().endswith(".pdf")
               else sorted(glob.glob(os.path.join(a.target, "*.pdf"))))
    if not targets:
        print("nothing to read")
        return 1

    if a.profile:
        import cProfile
        import pstats
        pr = cProfile.Profile()
        pr.enable()
    for t in targets:
        report(t, probe_file(t, readers, pages), a.top)
    if a.profile:
        pr.disable()
        print("\nhot functions (cumulative):")
        pstats.Stats(pr, stream=sys.stdout).sort_stats("cumulative").print_stats(18)
    return 0


if __name__ == "__main__":
    sys.exit(main())
