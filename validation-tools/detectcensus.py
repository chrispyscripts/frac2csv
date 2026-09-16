"""Which reader would fire on each file of a batch list — a fast look at
whether a book can be read, without running the extraction.

    python3 validation-tools/detectcensus.py ../batch-lists/aer-new-2026-09-14 out.tsv
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fitz                                              # noqa: E402

DRIVES = {"F:\\": "/Volumes/CnC-2TB-ssd/", "K:\\": "/Volumes/For-Chris-CnC-1TB/"}


def local(p):
    for d, m in DRIVES.items():
        if p.upper().startswith(d):
            return m + p[len(d):].replace("\\", "/")
    return p.replace("\\", "/")


def detectors():
    import bj1, bj_summary, canyon, step1, step_vec, step_summary, trican_charts, liberty_summary, calfrac_summary
    import hal1, lib1
    try:
        import cprog
    except Exception:
        cprog = None
    page = {"trican-A": trican_charts.detect, "trican-B": trican_charts.detect_b, "step-raster": step1.detect,
            "step-vector": step_vec.detect, "bj": bj1.detect, "canyon": canyon.detect,
            "hal": hal1.detect, "liberty": lib1.detect}
    if cprog is not None and hasattr(cprog, "is_chart_page"):
        page["calfrac-vector"] = cprog.is_chart_page
    doc = {"bj-totals": bj_summary.detect_document, "step-summary": step_summary.detect,
           "liberty-summary": liberty_summary.detect_document, "calfrac-summary": calfrac_summary.detect}
    return page, doc


def main(folder, out):
    page_det, doc_det = detectors()
    seen = set()
    if os.path.exists(out):
        seen = {l.split("\t")[1] for l in open(out) if "\t" in l}
    with open(out, "a") as f:
        if not seen:
            f.write("vendor\tfile\tpages\tpage_readers\tdoc_readers\n")
        for lst in sorted(glob.glob(os.path.join(folder, "*__*.txt"))):
            vendor = os.path.basename(lst).split("__")[1]
            for line in open(lst):
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                p = local(parts[1].strip()); name = os.path.basename(p)
                if name in seen or not os.path.exists(p):
                    continue
                try:
                    d = fitz.open(p)
                    hits = {}
                    for i in range(0, len(d), 5):        # every fifth page: a template shows on many
                        pg = d[i]
                        for k, fn in page_det.items():
                            try:
                                if fn(pg):
                                    hits[k] = hits.get(k, 0) + 1
                            except Exception:
                                pass
                    dh = []
                    for k, fn in doc_det.items():
                        try:
                            if fn(d):
                                dh.append(k)
                        except Exception:
                            pass
                    f.write(f"{vendor}\t{name}\t{len(d)}\t{';'.join(f'{k}:{v}' for k, v in sorted(hits.items(), key=lambda x: -x[1]))}\t{';'.join(dh)}\n")
                    d.close()
                except Exception as e:
                    f.write(f"{vendor}\t{name}\t-\tERR {str(e)[:60]}\t\n")
                f.flush()
    print("done")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
