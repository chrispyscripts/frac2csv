"""The plainest PDF reader there is, to mark against the mudlog answer key:
the header and the notes, read straight off the printout's text layer.

    python3 validation-tools/mudlog_text_baseline.py ~/dev/wellsight-answer-key /Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl OUT --jobs 6
    python3 validation-tools/mudlog_key_score.py ~/dev/wellsight-answer-key OUT --parts header,text

It reads the PDF only. The key is used to find which printout to read and
where to write the reading, nothing else:
  depth     the printout's own depth labels give the range; stitch() maps
            every log page to depth
  header    rows of words on the pages before the log; "Label:" starts a
            field, log_vocab names it (in its box: "Company:" under
            OPERATOR is the operator); a unit in the label goes on the value
  text      every line of text on the log pages, at the depth of its top
            edge

What it marks is what a reader gets for nothing; the curves, rocks and
symbols, which are drawing and not text, it does not try.
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

SUFFIX = ".key.json.gz"
GAP_PT = 12.0          # words further apart than this on a row are separate fields


def depth_range(doc):
    """the log's range as its printout labels it: (top, bottom) or None"""
    import wellsight_print as wp
    lines = []
    for pg in doc:
        ax = wp.page_axis(pg, 1, 99999)
        if ax and len(ax[3]) >= 5:
            lines.append((abs(ax[1]), [d for _c, d in ax[3]]))
    if not lines:
        return None
    # the log's pages share one scale; a header page's numbers do not
    scale = sorted(s for s, _ in lines)[len(lines) // 2]
    ds = [d for s, on in lines if abs(s - scale) <= 0.02 * scale for d in on]
    return (min(ds), max(ds)) if ds else None


def rows_of(pg):
    """the page's words in rows, top to bottom, each row left to right"""
    words = sorted(pg.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows = []
    for w in words:
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - yc) < 3:
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    return [sorted(r[1], key=lambda w: w[0]) for r in rows]


def chunks(row):
    """a row's words split where they stand apart"""
    out, cur = [], [row[0]]
    for w in row[1:]:
        if w[0] - cur[-1][2] > GAP_PT:
            out.append(cur)
            cur = [w]
        else:
            cur.append(w)
    out.append(cur)
    return [" ".join(w[4] for w in c) for c in out]


def pieces(text, box):
    """a row's text -> [(label or None, value)]: a label ends with ":", and
    is the longest run of words before it that log_vocab knows (else the
    one word)"""
    import log_vocab as V
    words = text.split()
    out, label, start = [], None, 0
    for j, w in enumerate(words):
        if not w.endswith(":") or len(w) < 2:
            continue
        n = 1
        for k in range(min(6, j + 1), 0, -1):
            if V.header(" ".join(words[j - k + 1:j + 1]), box)["key"]:
                n = k
                break
        lo = max(start, j - n + 1)
        if lo > start or label is not None:
            out.append((label, " ".join(words[start:lo])))
        label, start = " ".join(words[lo:j + 1]), j + 1
    out.append((label, " ".join(words[start:])))
    return [(l, v.strip()) for l, v in out if l is not None or v.strip()]


def read_header(pages):
    import log_vocab as V
    out = {}
    for pg in pages:
        box = None
        for row in rows_of(pg):
            parts = chunks(row)
            whole = " ".join(parts).strip()
            if len(parts) == 1 and ":" not in whole and V.key("header box", whole):
                box = whole
                continue
            field, unit, last = None, None, None
            for label, value in pieces(" ".join(parts), box):
                if label is not None:
                    if field and unit and out.get(field) and not out[field].endswith(unit):
                        out[field] += " " + unit
                    h = V.header(label, box)
                    if h["key"] is None and last == "logged_interval_top":
                        h = V.header(label, "LOGGED INTERVAL")
                    field, unit, last = h["key"], h["unit"], h["key"]
                if field and value:
                    out[field] = (out.get(field, "") + " " + value).strip()
            if field and unit and out.get(field) and not out[field].endswith(unit):
                out[field] += " " + unit
    return out


def read_text(doc, info):
    text = []
    for pl in info["placed"]:
        pg = doc[pl["page"] - 1]
        dm = pl["depth"]
        for b in pg.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                s = "".join(sp["text"] for sp in ln["spans"]).strip()
                if not s:
                    continue
                x0, y0, x1, y1 = ln["bbox"]
                c0, c1 = (y0, y1) if dm["coord"] == "y" else (x0, x1)
                d = min(dm["a"] * c0 + dm["b"], dm["a"] * c1 + dm["b"])
                if pl["from"] - 0.5 <= d <= pl["to"] + 0.5:
                    text.append({"depth": round(d, 3), "text": s})
    return text


def read(pdf_path):
    import fitz
    import wellsight_print as wp
    doc = fitz.open(pdf_path)
    rng = depth_range(doc)
    if not rng:
        return {"error": "no depth labels found"}
    _strip, info = wp.stitch(pdf_path, rng[0], rng[1])
    first_log = min(p["page"] for p in info["placed"]) - 1
    return {"reader": "text-layer baseline", "depth": {"top": rng[0], "bottom": rng[1]},
            "header": read_header([doc[i] for i in range(first_log)]), "text": read_text(doc, info)}


def _one(args):
    key_path, root, out_path = args
    import mudlog_key as K
    t = time.time()
    try:
        key = K.load(key_path)
        po = key.get("printout") or {}
        if not po.get("file"):
            return out_path, "no printout", 0
        r = read(os.path.join(root, po["file"]))
    except Exception as e:  # noqa: BLE001 - a reading that fails is a reading of nothing
        r = {"error": "%s: %s" % (type(e).__name__, e)}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(r, f)
    return out_path, r.get("error", "ok"), round(time.time() - t, 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keys")
    ap.add_argument("root", help="the folder the logs and printouts are in")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--every", type=int, default=1, help="read every n-th log")
    a = ap.parse_args(argv)
    keys, out = os.path.expanduser(a.keys), os.path.expanduser(a.out)
    todo = []
    for dp, dirs, files in os.walk(keys):
        dirs.sort()
        for f in sorted(files):
            if f.endswith(SUFFIX):
                rel = os.path.relpath(os.path.join(dp, f), keys)[:-len(SUFFIX)]
                todo.append((os.path.join(dp, f), os.path.expanduser(a.root), os.path.join(out, rel + ".json")))
    todo = todo[::a.every][:a.limit] if a.limit else todo[::a.every]
    done = {}
    with ProcessPoolExecutor(a.jobs) as ex:
        for fu in as_completed([ex.submit(_one, t) for t in todo]):
            _p, status, _s = fu.result()
            done[status if status in ("ok", "no printout") else "error"] = done.get(
                status if status in ("ok", "no printout") else "error", 0) + 1
    print(len(todo), "printouts read:", done)


if __name__ == "__main__":
    main()
