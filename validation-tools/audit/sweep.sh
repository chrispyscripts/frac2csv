#!/bin/zsh
# sweep.sh <out-dir> <pdf>...  — extract + audit, two at a time.
# macOS xargs -I caps the command at 255 bytes, which is why this is a loop.
set -u
OUT=$1; shift
HERE=$(cd "$(dirname "$0")/../.." && pwd)
PY=${F2C_PYTHON:-"$HERE/.venv-mac/bin/python"}
[ -x "$PY" ] || PY=python3
mkdir -p "$OUT"
one() {
  local pdf=$1 name
  name=$(basename "${pdf%.*}" | cut -d- -f1)
  "$PY" "$HERE/audit.py" "$pdf" --save "$OUT/$name-payload.json" --json "$OUT/$name-findings.json" --matrix \
      > "$OUT/$name-report.txt" 2> "$OUT/$name.log"
  echo "$name exit $?  $(date +%H:%M:%S)" >> "$OUT/sweep.log"
}
while [ $# -gt 0 ]; do
  one "$1" & [ $# -gt 1 ] && one "$2" &
  wait
  shift; [ $# -gt 0 ] && shift
done
echo "done $(date +%H:%M:%S)" >> "$OUT/sweep.log"
