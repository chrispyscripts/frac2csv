"""Speedup, old vs new, per provider and overall. usage: abtimecmp.py old.json new.json"""
import sys, json, collections
old, new = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
keys = sorted(set(old) & set(new))
agg = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0, 0])
for k in keys:
    a, b = old[k], new[k]
    if a.get("error") or b.get("error"):
        continue
    g = agg[a["prov"]]
    g[0] += a["cpu"]; g[1] += b["cpu"]
    g[2] += a["wall"]; g[3] += b["wall"]
    g[4] += a["pages"]; g[5] += 1
print(f"{'provider':14s} {'files':>5s} {'pages':>6s} "
      f"{'cpu old':>9s} {'cpu new':>9s} {'x':>6s} "
      f"{'wall old':>9s} {'wall new':>9s} {'x':>6s}")
tot = [0.0, 0.0, 0.0, 0.0, 0, 0]
for p in sorted(agg):
    g = agg[p]
    for i in range(6):
        tot[i] += g[i]
    print(f"{p:14s} {g[5]:5d} {g[4]:6d} {g[0]:8.1f}s {g[1]:8.1f}s "
          f"{(g[0]/g[1] if g[1] else 0):5.2f}x {g[2]:8.1f}s {g[3]:8.1f}s "
          f"{(g[2]/g[3] if g[3] else 0):5.2f}x")
print(f"{'-'*14} {'-'*5} {'-'*6} {'-'*9} {'-'*9} {'-'*6} {'-'*9} {'-'*9} {'-'*6}")
print(f"{'ALL':14s} {tot[5]:5d} {tot[4]:6d} {tot[0]:8.1f}s {tot[1]:8.1f}s "
      f"{(tot[0]/tot[1] if tot[1] else 0):5.2f}x {tot[2]:8.1f}s {tot[3]:8.1f}s "
      f"{(tot[2]/tot[3] if tot[3] else 0):5.2f}x")
