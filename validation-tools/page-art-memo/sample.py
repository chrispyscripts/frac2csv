"""Build a spread sample of corpus files, per provider, for the A/B sweep.

Draws on the provider-labelled batch lists the project already keeps, so the
sample is the same population the sweeps use rather than whatever a glob
happened to return. Files are taken evenly spaced through each list (not the
first N), because the lists are ordered by size and the first N would be all
small files — and size is what decides whether a reader takes its raster or
its vector path.

usage: sample.py <out.tsv> [per-provider]
"""
import os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
# …/frac2csv/validation-tools/page-art-memo -> the folder holding frac2csv
BL = os.environ.get("BATCH_LISTS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "batch-lists")
OUT = sys.argv[1]
PER = int(sys.argv[2]) if len(sys.argv) > 2 else 6

LISTS = {
    "bj":          [f"{BL}/aer-full-2026-09-15/aer-full__bj__195-files.txt",
                    f"{BL}/bj__tier1of6__28-files.txt",
                    f"{BL}/bj__tier4of6__28-files.txt",
                    f"{BL}/bj__tier6of6__28-files.txt"],
    "halliburton": [f"{BL}/aer-full-2026-09-15/aer-full__halliburton__153-files.txt",
                    f"{BL}/aer-new-2026-09-14/aer-new__halliburton__30-files.txt"],
    "slb":         [f"{BL}/aer-full-2026-09-15/aer-full__schlumberger__48-files.txt",
                    f"{BL}/aer-new-2026-09-14/aer-new__schlumberger__30-files.txt"],
    "trican":      [f"{BL}/aer-full-2026-09-15/aer-full__trican__520-files.txt"]
                   + sorted(glob.glob(f"{BL}/by-type/trican1__batch0[136]*.txt")),
    "step":        [f"{BL}/aer-full-2026-09-15/aer-full__step__57-files.txt"]
                   + sorted(glob.glob(f"{BL}/by-type/step1__batch0[147]*.txt")),
    "calfrac":     [f"{BL}/aer-full-2026-09-15/aer-full__calfrac__83-files.txt",
                    f"{BL}/aer-new-2026-09-14/aer-new__calfrac__30-files.txt"],
    "canyon":      [f"{BL}/aer-full-2026-09-15/aer-full__canyon__1-files.txt",
                    f"{BL}/aer-new-2026-09-14/aer-new__canyon__1-files.txt"],
    "baker":       [f"{BL}/aer-full-2026-09-15/aer-full__baker__4-files.txt"],
    "liberty":     [f"{BL}/aer-full-2026-09-15/aer-full__liberty__118-files.txt"],
    "ncs":         [f"{BL}/aer-full-2026-09-15/aer-full__ncs__7-files.txt"],
    "bcer-mixed":  [f"{BL}/bc-files-2026-09-16.txt"],
    "duvernay":    [f"{BL}/cnc-2tb-ssd__aer-frac-duvernay__738-files.txt"],
    "spirit-river": [f"{BL}/cnc-2tb-ssd__aer-frac-spirit-river__453-files.txt"],
}

# Providers with no labelled list: take them off the sorted folders the
# corpus already keeps, if those folders are there.
FOLDERS = {
    "sanjel":    ["SANJEL"],
    "leucrotta": ["LEUCROTTA", "LEUC"],
    "ogc":       ["OGC", "DATACAPTURE", "DATA-CAPTURE"],
}


# Carmine's lists carry Windows drive letters; quickpass.py maps them the
# same way. Without this the whole AER half of the corpus reads as missing.
DRIVES = {"F:\\": "/Volumes/CnC-2TB-ssd/",
          "K:\\": "/Volumes/For-Chris-CnC-1TB/",
          "A:\\": "/Volumes/CnC-2TB-ssd/"}


def local_path(p):
    for d, m in DRIVES.items():
        if p.upper().startswith(d):
            return m + p[len(d):].replace("\\", "/")
    return p


def paths_from(fn):
    out = []
    if not os.path.exists(fn):
        return out
    for line in open(fn, errors="replace"):
        line = line.rstrip("\n")
        if not line.strip():
            continue
        p = line.split("\t")[-1].strip()
        if p.lower().endswith(".pdf"):
            out.append(local_path(p))
    return out


def spread(items, n):
    items = list(dict.fromkeys(items))
    if len(items) <= n:
        return items
    step = len(items) / float(n)
    return [items[int(i * step)] for i in range(n)]


rows, missing = [], []
for prov, files in LISTS.items():
    pool = []
    for f in files:
        pool += paths_from(f)
    picked = spread(pool, PER)
    here = [p for p in picked if os.path.exists(p)]
    gone = [p for p in picked if not os.path.exists(p)]
    # a list entry whose drive is down would silently shrink the sample
    if gone:
        extra = spread([p for p in pool if os.path.exists(p)], PER)
        for p in extra:
            if p not in here and len(here) < PER:
                here.append(p)
        missing += gone
    for p in here:
        rows.append((prov, p))

# The sorted-folder names are the corpus's own, not ours, so find them
# rather than assume them: any __FOO directory on either drive whose name
# carries the provider's token counts.
ROOTS = ["/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023",
         "/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC",
         "/Volumes/CnC-2TB-ssd/BCER-Frac",
         "/Volumes/For-Chris-CnC-1TB/BCER-Frac"]
sorted_dirs = []
for r in ROOTS:
    if os.path.isdir(r):
        sorted_dirs += [d for d in sorted(glob.glob(os.path.join(r, "__*")))
                        if os.path.isdir(d)]
if sorted_dirs:
    print("sorted provider folders found: "
          + ", ".join(sorted({os.path.basename(d) for d in sorted_dirs})))

for prov, tokens in FOLDERS.items():
    pool = []
    for d in sorted_dirs:
        base = os.path.basename(d).lstrip("_").upper()
        if any(t.upper() in base or base in t.upper() for t in tokens):
            pool += sorted(glob.glob(os.path.join(d, "*.[pP][dD][fF]")))
            pool += sorted(glob.glob(os.path.join(d, "*", "*.[pP][dD][fF]")))
    for q in spread(pool, PER):
        rows.append((prov, q))
    if not pool:
        print(f"  (no sorted folder matched {prov}: {tokens} — "
              f"it will have to come out of the mixed lists)")

with open(OUT, "w") as f:
    for prov, p in rows:
        f.write(f"{prov}\t{p}\n")

by = {}
for prov, _ in rows:
    by[prov] = by.get(prov, 0) + 1
print(f"{len(rows)} files -> {OUT}")
for k in sorted(by):
    print(f"  {k:14s} {by[k]}")
if missing:
    print(f"\n{len(missing)} listed path(s) not present (drive down or moved); "
          f"first few:")
    for m in missing[:5]:
        print("   " + m)
