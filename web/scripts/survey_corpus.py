#!/usr/bin/env python3
"""Full survey of Carmine's BCER-Frac corpus (external drive).

Per PDF: page classification (vector charts / scans / per-stage text),
template fingerprints (heavy stroke-color sets, software markers, candidate
curve names from colored text), and which of our extractors detect it.
Writes JSONL rows (resumable) + is safe to re-run.

Usage: python3 survey_corpus.py [workers]
"""
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = "/Volumes/CnC-512-ssd/BCER-Frac"
OUT = os.path.expanduser("~/Documents/Chris Vault/frac-pdf-extract/corpus-survey/survey.jsonl")

MARKERS = ["(ifs v", "job date:", "fracpro", "insite", "peloton", "wellview",
           "trican", "calfrac", "step energy", "liberty", "sanjel", "canyon",
           "bj services", "schlumberger", "baker hughes", "iron bird",
           "element technical", "gasfrac", "mview", "casing ign"]
TEXT_KWS = ("breakdown", "avg treating", "average treating", "isip",
            "inst shut", "proppant", "frac #", "slurry")


def survey_pdf(path):
    import fitz
    doc = fitz.open(path)
    n = len(doc)
    markers = set()
    text_frac_pages = 0
    timeish_pages = []
    textless_img_pages = 0
    cand = []
    for pno in range(n):
        page = doc[pno]
        text = page.get_text()
        low = text.lower()
        for m in MARKERS:
            if m in low:
                markers.add(m)
        if sum(k in low for k in TEXT_KWS) >= 2:
            text_frac_pages += 1
        if len(re.findall(r"\b\d{1,2}:\d{2}\b", text)) >= 4:
            timeish_pages.append(pno)
        if len(text.strip()) < 40:
            if page.get_image_info():
                textless_img_pages += 1
            cand.append(pno)
    # candidate pages for expensive drawing analysis
    cand += timeish_pages
    cand += list(range(0, n, max(1, n // 12)))
    cand = sorted(set(cand))[:40]

    color_sets = Counter()
    vector_chart_pages = 0
    curve_names = Counter()
    for pno in cand:
        page = doc[pno]
        segs = Counter()
        try:
            for d in page.get_drawings():
                c = d.get("color")
                if c and d["type"] in ("s", "fs") and max(c) - min(c) >= 0.25:
                    segs[tuple(round(x, 2) for x in c)] += len(d["items"])
        except Exception:
            continue
        heavy = sorted(k for k, v in segs.items() if v >= 300)
        if len(heavy) >= 2:
            vector_chart_pages += 1
            color_sets[str(heavy[:6])] += 1
            # candidate curve names: colored text spans
            try:
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        for span in line["spans"]:
                            t = span["text"].strip()
                            if span.get("color", 0) != 0 and 5 < len(t) < 40 and \
                               not re.fullmatch(r"[\d,.:%\s/-]+", t):
                                curve_names[t] += 1
            except Exception:
                pass

    # our detectors
    detectors = []
    try:
        sys.path.insert(0, os.path.expanduser(
            "~/Documents/Chris Vault/frac-pdf-extract/frac2csv"))
        import frac_core as fc
        import leucrotta as lclib
        import sk_fracr as sklib
        for pno in cand[:20]:
            page = doc[pno]
            t = page.get_text()
            if "(IFS v" in t and "ifs" not in detectors:
                detectors.append("ifs")
            if lclib.detect(page) and "leucrotta" not in detectors:
                detectors.append("leucrotta")
            if sklib.detect(page) and "sk_fracr" not in detectors:
                detectors.append("sk_fracr")
            if fc.page_kind(page) == "vector" and "mview-colors" not in detectors:
                detectors.append("mview-colors")
    except Exception:
        pass
    doc.close()
    return {
        "pages": n, "markers": sorted(markers),
        "text_frac_pages": text_frac_pages,
        "timeish_pages": len(timeish_pages),
        "textless_img_pages": textless_img_pages,
        "vector_chart_pages": vector_chart_pages,
        "color_sets": dict(color_sets.most_common(3)),
        "curve_names": [k for k, _ in curve_names.most_common(12)],
        "detectors": detectors,
    }


def survey_folder(folder):
    fpath = os.path.join(ROOT, folder)
    m = re.match(r"(\d+)-([0-9A-Z]+)_(\d+)", folder)
    base = {"folder": folder,
            "index": m.group(1) if m else "", "uwi": m.group(2) if m else "",
            "wa": m.group(3) if m else ""}
    rows = []
    try:
        pdfs = [f for f in os.listdir(fpath) if f.lower().endswith(".pdf")]
    except OSError as e:
        base["error"] = str(e)
        return [base]
    for pdf in sorted(pdfs):
        row = dict(base)
        row["file"] = pdf
        try:
            row.update(survey_pdf(os.path.join(fpath, pdf)))
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    if not pdfs:
        base["error"] = "no pdf"
        rows.append(base)
    return rows


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["folder"])
                except Exception:
                    pass
    folders = [f for f in sorted(os.listdir(ROOT))
               if re.match(r"\d+-", f) and f not in done]
    print(f"{len(folders)} folders to survey ({len(done)} already done)", flush=True)
    n_done = 0
    with open(OUT, "a") as out, ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(survey_folder, f): f for f in folders}
        for fut in as_completed(futs):
            try:
                rows = fut.result()
            except Exception as e:
                rows = [{"folder": futs[fut], "error": f"worker: {e}"}]
            for r in rows:
                out.write(json.dumps(r) + "\n")
            out.flush()
            n_done += 1
            if n_done % 25 == 0:
                print(f"[{n_done}/{len(folders)}]", flush=True)
    print("survey complete", flush=True)


if __name__ == "__main__":
    main()
