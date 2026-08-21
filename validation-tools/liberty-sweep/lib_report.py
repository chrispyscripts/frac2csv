"""What the sweep found, as numbers rather than a pile of JSON.

Every count here is over PAGES, not files, because "19 of 19 files extract"
was true of the sample page and said nothing about the other 900.
"""
import os, sys, json, glob, collections, re

def load(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        try: out.append(json.load(open(f)))
        except Exception as e: print("  bad", f, e)
    return out

def main(d):
    files = load(d)
    nf = len(files)
    tot_pages = sum(f.get("npages", 0) for f in files)
    det = ext = failed = 0
    dated = clocked = staged = 0
    errs = collections.Counter()
    chan = collections.Counter()
    outside = []          # (file, page, channel, range, axis)
    onbound = collections.Counter()
    noaxis = 0
    allnan = []
    unfired_ink = []      # ink-heavy pages the detector passed over
    per_file = []
    for f in files:
        fd = fe = 0
        for p in f.get("pages", []):
            if p.get("sat"): unfired_ink.append((f["file"], p["p"], p["sat"]))
            if not p.get("detect"): continue
            det += 1; fd += 1
            if p.get("error"):
                failed += 1
                errs[re.sub(r"\d+", "N", p["error"])[:90]] += 1
                continue
            if not p.get("channels"): failed += 1; continue
            ext += 1; fe += 1
            if p.get("date"): dated += 1
            if p.get("time"): clocked += 1
            if p.get("stage"): staged += 1
            for name, c in p["channels"].items():
                chan[name] += 1
                if not c.get("range"): allnan.append((f["file"], p["p"], name))
                if not c.get("axis"): noaxis += 1
                if c.get("outside"):
                    outside.append((f["file"], p["p"], name,
                                    c["range"][:2], c["axis"]))
                if c.get("on_bound"): onbound[name] += 1
        per_file.append((f["file"], f.get("npages", 0), fd, fe))

    print(f"FILES {nf}   PAGES {tot_pages}")
    print(f"  chart pages (detect fired) : {det}")
    print(f"  extracted with channels    : {ext}"
          f"  ({100*ext/det:.1f}% of chart pages)" if det else "")
    print(f"  chart pages that FAILED    : {failed}")
    if det:
        print(f"  dated  {dated}/{ext} ({100*dated/max(1,ext):.1f}%)   "
              f"clocked {clocked}/{ext} ({100*clocked/max(1,ext):.1f}%)   "
              f"staged {staged}/{ext} ({100*staged/max(1,ext):.1f}%)")
    print()
    if errs:
        print("FAILURE REASONS")
        for m, n in errs.most_common(12): print(f"  {n:>5}  {m}")
        print()
    print("CHANNEL NAMES (pages carrying each)")
    for n, c in chan.most_common(40): print(f"  {c:>6}  {n}")
    print()
    print(f"VALUES OUTSIDE THEIR PRINTED AXIS: {len(outside)}")
    for r in outside[:20]:
        print(f"  {r[0][:34]} p{r[1]} {r[2]}: {r[3]} vs axis {r[4]}")
    print()
    print(f"CHANNELS PINNED ON AN AXIS BOUND (clipping signature): "
          f"{sum(onbound.values())}")
    for n, c in onbound.most_common(10): print(f"  {c:>6}  {n}")
    print()
    print(f"ALL-NaN CHANNELS: {len(allnan)}")
    for r in allnan[:10]: print(f"  {r[0][:34]} p{r[1]} {r[2]}")
    print()
    print(f"channels with NO printed axis to check against: {noaxis}")
    print()
    print(f"INK-HEAVY PAGES THE DETECTOR PASSED OVER: {len(unfired_ink)}"
          "   (candidates only — a wellbore schematic scores high too)")
    byf = collections.Counter(x[0] for x in unfired_ink)
    for n, c in byf.most_common(10): print(f"  {c:>5}  {n[:50]}")
    print()
    print("PER FILE  (pages / chart pages / extracted)")
    for name, np_, fd, fe in sorted(per_file):
        flag = "" if fd == fe else f"   <-- {fd - fe} FAILED"
        print(f"  {name[:46]:<48} {np_:>4} {fd:>5} {fe:>5}{flag}")

if __name__ == "__main__":
    main(sys.argv[1])
