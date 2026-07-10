#!/usr/bin/env python3
"""Survey the BC corpus: which operators file time-series frac CHARTS in
their completion reports vs per-stage TEXT reports vs plain scans?

Samples ~2 fracked wells per top operator (from BCER's open per-stage frac
CSV), fetches their COMP PDFs over the eLibrary FTP (~/.netrc auth), and
classifies every page. Output: bc-corpus/survey.json + printed matrix.
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

import fitz
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_bc_wellfiles import index_filenames, find_well_dir, curl, FTP  # noqa: E402

FRAC_CSV = "/tmp/frac_csv/hydraulic_fracture.csv"
OUT_DIR = os.path.expanduser("~/Documents/Chris Vault/frac-pdf-extract/bc-corpus")
N_OPERATORS = 15
WELLS_PER_OP = 2

TEXT_KWS = ("breakdown", "avg treating", "average treating", "isip",
            "inst shut", "proppant", "frac #", "slurry")


def pick_wells():
    """Top operators by fracked-well count; 2 wells each (max stages, recent)."""
    by_op = defaultdict(lambda: defaultdict(int))   # op -> wa -> stage rows
    year = {}
    with open(FRAC_CSV, newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f):
            name = (row.get("WELL NAME") or "").strip()
            wa = (row.get("WA NUM") or "").strip()
            if not name or not wa:
                continue
            op = name.split()[0].upper()
            by_op[op][wa] += 1
            d = (row.get("COMPLTN DATE") or "").strip()
            if len(d) >= 9:
                try:
                    y = int(d[-2:]); y += 2000 if y < 50 else 1900
                    year[wa] = max(year.get(wa, 0), y)
                except ValueError:
                    pass
    ops = sorted(by_op.items(), key=lambda kv: -len(kv[1]))[:N_OPERATORS]
    picks = []
    for op, wells in ops:
        ranked = sorted(wells.items(), key=lambda kv: (-kv[1], -year.get(kv[0], 0)))
        chosen = [wa for wa, _ in ranked[:WELLS_PER_OP]]
        picks.append((op, chosen, len(wells)))
    return picks


def fetch_comp(wa):
    """Download COMP PDFs for a WA; returns local paths."""
    names = [n for n in index_filenames(wa)
             if "_COMP_" in n and n.upper().endswith(".PDF")]
    if not names:
        return []
    well_dir, listing = find_well_dir(wa)
    if well_dir is None:
        return []
    lookup = {l.lower(): l for l in (listing or [])}
    out = []
    os.makedirs(os.path.join(OUT_DIR, wa), exist_ok=True)
    for n in names[:3]:
        remote = lookup.get(n.lower(), n)
        dest = os.path.join(OUT_DIR, wa, remote)
        if not (os.path.exists(dest) and os.path.getsize(dest) > 1000):
            curl(["-o", dest, f"{FTP}/{well_dir}/{remote}"], timeout=900)
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            out.append(dest)
    return out


def classify_page(page):
    """-> set of labels for this page."""
    labels = set()
    text = page.get_text().lower()
    if sum(k in text for k in TEXT_KWS) >= 2:
        labels.add("text-frac")
    # vector chart: >=2 saturated stroke colors with lots of segments,
    # or one heavy curve color plus a time axis mention
    segs = Counter()
    try:
        for d in page.get_drawings():
            c = d.get("color")
            if c is None or d["type"] not in ("s", "fs"):
                continue
            r, g, b = c
            if max(c) - min(c) < 0.25:          # gray/black: frame, tables
                continue
            segs[tuple(round(x, 2) for x in c)] += len(d["items"])
    except Exception:
        pass
    heavy = [n for n in segs.values() if n >= 300]
    if len(heavy) >= 2 or (len(heavy) == 1 and max(segs.values()) > 1000 and "time" in text):
        labels.add("vector-chart")
    # raster chart candidate: big image page with little text and colored curves
    if len(text.strip()) < 60:
        big = any(fitz.Rect(i["bbox"]).width * fitz.Rect(i["bbox"]).height > 0.35 * abs(page.rect)
                  for i in page.get_image_info())
        if big:
            try:
                pix = page.get_pixmap(dpi=50)
                if pix.alpha or pix.colorspace.n != 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, 3).astype(int)
                mx = img.max(axis=2); mn = img.min(axis=2)
                sat = (mx - mn > 50) & (mx > 90)
                labels.add("scan-color" if sat.sum() > 400 else "scan")
            except Exception:
                labels.add("scan")
    return labels


def classify_pdf(path):
    doc = fitz.open(path)
    counts = Counter()
    step = 1 if len(doc) <= 250 else 2
    for pno in range(0, len(doc), step):
        for lab in classify_page(doc[pno]):
            counts[lab] += step
    n = len(doc)
    doc.close()
    return n, dict(counts)


def main():
    picks = pick_wells()
    print("operators:", [(op, n) for op, _, n in picks])
    results = []
    for op, was, n_wells in picks:
        for wa in was:
            print(f"\n== {op} WA {wa} ==", flush=True)
            try:
                paths = fetch_comp(wa)
            except Exception as e:
                print("  fetch error:", e)
                continue
            if not paths:
                print("  no COMP pdf")
                results.append({"op": op, "wa": wa, "file": None})
                continue
            for p in paths:
                try:
                    n, counts = classify_pdf(p)
                except Exception as e:
                    print("  classify error:", os.path.basename(p), e)
                    continue
                rec = {"op": op, "wa": wa, "file": os.path.basename(p),
                       "pages": n, "counts": counts,
                       "size_kb": os.path.getsize(p) // 1024}
                results.append(rec)
                print(f"  {os.path.basename(p)}: {n}pp {counts}", flush=True)
    with open(os.path.join(OUT_DIR, "survey.json"), "w") as f:
        json.dump(results, f, indent=1)

    print("\n\n===== OPERATOR MATRIX =====")
    by_op = defaultdict(lambda: Counter())
    for r in results:
        if r.get("counts") is not None:
            by_op[r["op"]].update(r["counts"])
            by_op[r["op"]]["pages"] += r.get("pages", 0)
    print(f"{'operator':14s} {'pages':>6s} {'vec-chart':>9s} {'scan-color':>10s} {'text-frac':>9s} verdict")
    for op, c in by_op.items():
        verdict = ("CHARTS(vector)" if c["vector-chart"] >= 3 else
                   "charts(scanned?)" if c["scan-color"] >= 3 else
                   "text reports" if c["text-frac"] >= 3 else "scans/other")
        print(f"{op:14s} {c['pages']:6d} {c['vector-chart']:9d} {c['scan-color']:10d} "
              f"{c['text-frac']:9d} {verdict}")


if __name__ == "__main__":
    main()
