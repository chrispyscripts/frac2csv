"""Compare two digests. A channel that MOVED is a regression; one that
appeared is the fix. They are counted apart because only one of them is
allowed on a text-layer file."""
import json, sys
b = json.load(open(sys.argv[1])); a = json.load(open(sys.argv[2]))
for f in sorted(set(b) | set(a)):
    B, A = b.get(f, {}), a.get(f, {})
    moved = gained = lost = 0
    pfix = pbroke = 0
    dates = []
    for p in sorted(set(B) | set(A), key=lambda x: int(x[1:])):
        rb, ra = B.get(p, {}), A.get(p, {})
        if rb.get("error") and not ra.get("error"): pfix += 1
        if ra.get("error") and not rb.get("error"):
            pbroke += 1; print(f"  !! {f} {p} BROKE: {ra['error']}")
        cb, ca = rb.get("ch", {}), ra.get("ch", {})
        for k in set(cb) & set(ca):
            if cb[k] != ca[k]:
                moved += 1
                if moved <= 3: print(f"  ~~ {f} {p} {k} MOVED")
        gained += len(set(ca) - set(cb))
        lost += len(set(cb) - set(ca))
        for key in ("date", "time", "stage"):
            if rb.get(key) != ra.get(key) and not rb.get("error") and not ra.get("error"):
                dates.append((p, key, rb.get(key), ra.get(key)))
    print(f"{f}")
    print(f"   pages fixed {pfix}   pages broken {pbroke}")
    print(f"   channels moved {moved}   gained {gained}   lost {lost}")
    print(f"   meta changed on {len(dates)} page-fields")
    for d in dates[:6]: print(f"     {d[0]} {d[1]}: {d[2]!r} -> {d[3]!r}")
