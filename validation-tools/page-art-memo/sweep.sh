#!/bin/zsh
# The A/B sweep for the page-art memo, once both corpus drives are mounted.
#
#   ./sweep.sh <OLD-tree> <NEW-tree> [files-per-provider]
#
# OLD and NEW must be FROZEN checkouts — separate worktrees, clean, and left
# alone for the duration. Editing a tree while the sweep runs measures
# neither version.
#
#   git worktree add --detach /tmp/OLD <base-commit>
#   git worktree add --detach /tmp/NEW <memo-commit>
set -e
HERE="${0:A:h}"
OLD="$1"; NEW="$2"; PER="${3:-6}"
[[ -n "$OLD" && -n "$NEW" ]] || { sed -n '2,12p' "$0"; exit 2; }
OUT="${TMPDIR:-/tmp}/page-art-memo-sweep"
mkdir -p "$OUT"

for v in /Volumes/CnC-2TB-ssd /Volumes/For-Chris-CnC-1TB; do
  [[ -d "$v" ]] || { echo "NOT MOUNTED: $v"; exit 1; }
done

echo "=== frozen trees ==="
for t in "$OLD" "$NEW"; do
  git -C "$t" log --oneline -1
  [[ -z "$(git -C "$t" status --porcelain)" ]] || { echo "$t is DIRTY"; exit 1; }
done

echo "\n=== 1. sample ==="
python3 "$HERE/sample.py" "$OUT/sample.tsv" "$PER"
cut -f2 "$OUT/sample.tsv" > "$OUT/paths.txt"

echo "\n=== 2. digest OLD ==="
python3 "$HERE/abdigest.py" "$OLD" "$OUT/old.json" $(cat "$OUT/paths.txt")
echo "\n=== 3. digest NEW ==="
python3 "$HERE/abdigest.py" "$NEW" "$OUT/new.json" $(cat "$OUT/paths.txt")

echo "\n=== 4. compare — ANY difference is a failure ==="
python3 "$HERE/abcompare.py" "$OUT/old.json" "$OUT/new.json"

echo "\n=== 5. which readers actually fired ==="
python3 - "$OUT/new.json" <<'PY'
import sys, json, collections
d = json.load(open(sys.argv[1]))
c = collections.Counter()
for f, v in d.items():
    for r in v.get("results", []):
        c[r.get("source") or r.get("type")] += 1
for k, n in sorted(c.items(), key=lambda kv: -kv[1]):
    print(f"  {n:6d}  {k}")
print("\nA reader missing from this list was NOT exercised — widen the sample "
      "before calling it verified.")
PY

echo "\n=== 6. thread safety, on NEW ==="
python3 "$HERE/threadsafe.py" "$NEW" $(head -8 "$OUT/paths.txt")

echo "\n=== 7. speed, warm cache both sides ==="
python3 "$HERE/abtime.py" "$OLD" "$OUT/sample.tsv" "$OUT/told.json" --warm
python3 "$HERE/abtime.py" "$NEW" "$OUT/sample.tsv" "$OUT/tnew.json" --warm
python3 "$HERE/abtimecmp.py" "$OUT/told.json" "$OUT/tnew.json"
