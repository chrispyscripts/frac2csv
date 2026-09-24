"""Diff two abdigest.py outputs. Exit 1 on any difference at all.

There is no tolerance here on purpose: the change under test only removes
repeated parses of geometry that cannot have changed between them, so the
arrays must come back identical. A "close enough" result is a failed test.
"""
import sys, json

old = json.load(open(sys.argv[1]))
new = json.load(open(sys.argv[2]))
diffs, errs, ok = [], [], 0

for name in sorted(set(old) | set(new)):
    a, b = old.get(name), new.get(name)
    if a is None or b is None:
        diffs.append(f"{name}: present on only one side")
        continue
    if "error" in a or "error" in b:
        errs.append(f"{name}: OLD={a.get('error','-')} NEW={b.get('error','-')}")
        if a.get("error") != b.get("error"):
            diffs.append(f"{name}: different errors")
        continue
    if a == b:
        ok += 1
        continue
    if a["n_results"] != b["n_results"]:
        diffs.append(f"{name}: n_results {a['n_results']} -> {b['n_results']}")
    ra, rb = a["results"], b["results"]
    for i in range(max(len(ra), len(rb))):
        x = ra[i] if i < len(ra) else None
        y = rb[i] if i < len(rb) else None
        if x == y:
            continue
        if x is None or y is None:
            diffs.append(f"{name}[{i}]: result on only one side")
            continue
        for k in sorted(set(x) | set(y)):
            if x.get(k) == y.get(k):
                continue
            if k == "ch":
                for c in sorted(set(x.get(k, {})) | set(y.get(k, {}))):
                    ca, cb = x.get(k, {}).get(c), y.get(k, {}).get(c)
                    if ca != cb:
                        diffs.append(
                            f"{name} p{x.get('page')} {x.get('source')} "
                            f"ch[{c}]: {ca} -> {cb}")
            else:
                diffs.append(f"{name} p{x.get('page')} {x.get('source')} "
                             f"{k}: {x.get(k)!r} -> {y.get(k)!r}")

print(f"files identical: {ok}/{len(set(old) | set(new))}")
if errs:
    print(f"\nfiles that errored on BOTH sides ({len(errs)}) "
          f"— not a regression, but nothing was compared:")
    for e in errs[:20]:
        print("  " + e)
if diffs:
    print(f"\n!!! {len(diffs)} DIFFERENCE(S):")
    for d in diffs[:60]:
        print("  " + d)
    sys.exit(1)
print("\nNO DIFFERENCES.")
