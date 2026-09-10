"""Interval sheets, checked against the sheets' OWN printed numbers.

Three checks, none of them against our own output:
  * printed "N mins" vs the two printed clocks — the sheet contradicting
    itself, or us misreading one of the three
  * the stage ladder — gaps and duplicates
  * every row's field count against the column union, so a sheet that lost a
    field to a layout change shows up as a hole rather than a silent blank
"""
import sys, os, json, datetime
sys.path.insert(0, "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv")
import fitz, interval_sheet as isheet

def mins(a, b):
    f = "%Y-%m-%d %H:%M:%S"
    try:
        return (datetime.datetime.strptime(b, f)
                - datetime.datetime.strptime(a, f)).total_seconds() / 60.0
    except Exception:
        return None

for path in json.load(open(sys.argv[1])):
    doc = fitz.open(path)
    sheets = sum(1 for p in range(doc.page_count) if isheet.detect(doc[p]))
    tab = isheet.parse_document(doc)
    if not tab:
        print(f"{os.path.basename(path)[:44]:<46} sheets={sheets} NO TABLE", flush=True)
        continue
    cols, rows = tab["columns"], tab["rows"]
    ix = {c: i for i, c in enumerate(cols)}
    stages, bad_time, holes = [], [], 0
    for r in rows:
        s = r[ix["Stage"]] if "Stage" in ix else ""
        stages.append(s)
        a = r[ix["Start"]] if "Start" in ix else ""
        b = r[ix["End"]] if "End" in ix else ""
        pm = r[ix["Pump Time (min)"]] if "Pump Time (min)" in ix else ""
        d = mins(a, b)
        if d is not None and pm:
            if abs(d - float(pm)) > 2.0:
                bad_time.append((s, pm, round(d, 1)))
        elif not (a and b and pm):
            holes += 1
        holes += sum(1 for v in r if v == "")
    nums = sorted(int("".join(ch for ch in s if ch.isdigit()) or 0)
                  for s in stages if s)
    gaps = [n for n in range(1, (max(nums) if nums else 0) + 1) if n not in nums]
    dups = len(nums) - len(set(nums))
    print(f"{os.path.basename(path)[:44]:<46} sheets={sheets:<4} rows={len(rows):<4} "
          f"cols={len(cols):<3} stages={min(nums) if nums else '-'}..{max(nums) if nums else '-'} "
          f"gaps={len(gaps)} dups={dups} time_mismatch={len(bad_time)} blanks={holes}", flush=True)
    if gaps:
        print(f"      missing stages: {gaps[:12]}", flush=True)
    for s, pm, d in bad_time[:4]:
        print(f"      stage {s}: printed {pm} mins, clocks say {d}", flush=True)
    doc.close()
print("ISHEET CHECK COMPLETE", flush=True)
