"""Which names a folder of converted WellSight logs uses that the log
vocabulary (log_vocab.txt) does not know yet, most used first.

    python3 -I validation-tools/log_vocab_harvest.py ~/dev/wellsight-converted
    python3 -I validation-tools/log_vocab_harvest.py FOLDER --top 60 --csv spellings.csv

FOLDER holds wellsight-convert's .json files (any depth). For each kind of
name (curve names, curve mnemonics, units, curve track titles, column
titles, symbol categories, symbol codes, rock codes, header labels and
header boxes) it prints how many distinct spellings there are, how many of
them and how many of their uses the vocabulary knows, and the unknown ones
by use. --csv writes every spelling with its count and what it resolved to.

The report holds names straight out of the logs, which can include well
names, locations and people. Keep it out of the repository; copy only the
names themselves into log_vocab.txt.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import log_vocab as V                     # noqa: E402
import wellsight_symbols as W             # noqa: E402

KINDS = ("curve name", "curve mnemonic", "unit", "curve track", "column", "symbol category", "symbol code",
         "rock code", "header label", "header box")
_UNNAMED = re.compile(r"^column\s*\d+$", re.I)


def _column(title):
    """what a column title resolves to, or None"""
    t = title.strip()
    if _UNNAMED.match(t):
        return "unnamed"
    low = t.lower()
    for k, cols in W_COLUMNS.items():
        if low in cols:
            return k
    return V.key("column", t) or V.depth_column(t) or ("curves" if V.curve_track(t) else None)


W_COLUMNS = {e.key: tuple(s.strip().lower() for s in e.spellings) for e in V.entries("column")}


def _header_labels(lines):
    """labels written "LABEL: value" in a custom header page's lines"""
    for line in lines or []:
        for chunk in re.split(r"\s{3,}|\t|\|", line):
            if ":" not in chunk:
                continue
            label = chunk.split(":", 1)[0].strip()
            if 1 < len(label) <= 45 and re.search(r"[A-Za-z]{2}", label) \
                    and sum(c.isdigit() for c in label) <= 2:
                yield label


def harvest(folder):
    """{kind: Counter(spelling)}, number of logs read"""
    seen = {k: collections.Counter() for k in KINDS}
    n = 0
    for path in glob.glob(os.path.join(folder, "**", "*.json"), recursive=True):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not isinstance(d.get("curves"), list):
            continue
        n += 1
        for c in d.get("curves") or []:
            for kind, field in (("curve name", "name"), ("curve mnemonic", "source_mnemonic"),
                                ("unit", "units"), ("curve track", "track")):
                v = str(c.get(field) or "").strip()
                if v and not (kind == "curve mnemonic" and _UNNAMED.match(v)):
                    seen[kind][v] += 1
        for col in d.get("columns") or []:
            if str(col).strip():
                seen["column"][str(col).strip()] += 1
        for s in (d.get("accessories") or {}).get("symbols") or []:
            cat = str(s.get("category") or "").strip()
            if cat:
                seen["symbol category"][cat] += 1
                g = W.group_of(cat)
                g = W._REFILE.get((g, W._key(s.get("code"))), g)
                if g not in W.PASSTHROUGH:
                    seen["symbol code"]["%s:%s" % (g, s.get("code"))] += 1
        for iv in (d.get("lithology") or {}).get("intervals") or []:
            if iv.get("code"):
                seen["rock code"][str(iv["code"])] += 1
        for label in _header_labels((d.get("custom_header") or {}).get("lines")):
            seen["header label"][label] += 1
        for b in d.get("header_boxes") or []:
            if str(b.get("title") or "").strip():
                seen["header box"][str(b["title"]).strip()] += 1
    return seen, n


def resolve(kind, spelling):
    """what the vocabulary makes of one spelling: a key or None"""
    if kind == "curve name" or kind == "curve mnemonic":
        return V.curve(spelling)["key"]
    if kind == "unit":
        return V.unit(spelling)["key"]
    if kind == "curve track":
        # curves sit in curve tracks, and now and then in another column
        return "curves" if V.curve_track(spelling) else _column(spelling)
    if kind == "column":
        return _column(spelling)
    if kind == "symbol category":
        return V.key("category", spelling)
    if kind == "symbol code":
        g, code = spelling.split(":", 1)
        t = W.normalise(g, code)[0]
        return None if t.startswith("raw:") else "%s:%s" % (g, t)
    if kind == "rock code":
        t = W.rock_term(spelling)[0]
        return None if t.startswith("raw:") else t
    if kind == "header label":
        return V.header(spelling)["key"]
    if kind == "header box":
        return V.key("header box", spelling)
    raise KeyError(kind)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--top", type=int, default=25, help="unknown spellings to list for each kind")
    ap.add_argument("--csv", help="write every spelling here")
    a = ap.parse_args(argv)
    seen, n = harvest(os.path.expanduser(a.folder))
    print("%d logs read from %s\n" % (n, a.folder))
    rows = []
    for kind in KINDS:
        c = seen[kind]
        if not c:
            continue
        res = {s: resolve(kind, s) for s in c}
        known = [s for s in c if res[s]]
        uses = sum(c.values())
        print("%-16s %5d spellings, %5.1f%% known; %8d uses, %5.1f%% known" % (
            kind, len(c), 100.0 * len(known) / len(c), uses, 100.0 * sum(c[s] for s in known) / uses))
        unknown = sorted((s for s in c if not res[s]), key=lambda s: (-c[s], s))
        for s in unknown[:a.top]:
            print("    %7d  %s" % (c[s], s))
        if len(unknown) > a.top:
            print("    ... %d more" % (len(unknown) - a.top))
        rows += [(kind, s, c[s], res[s] or "") for s in sorted(c, key=lambda s: -c[s])]
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["kind", "spelling", "uses", "means"])
            w.writerows(rows)
        print("\nevery spelling: %s" % a.csv)


if __name__ == "__main__":
    main()
