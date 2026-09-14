"""Client reports against the audit of each file.

    python3 scorecard.py <out-dir> flags.json

Three outcomes and they are different things:
  FOUND     the audit warns on the flagged stage/channel with an answering kind
  REPAIRED  expect=false and the audit is quiet — the fix shipped
  STILL     expect=false and the audit still warns — the fix did not take
  MISSED    expect=true and the audit says nothing: a detector to write
"""
import json
import os
import sys


def main(out, flags_path):
    flags = json.load(open(flags_path))
    print(f"{'flag':<7} {'file':<6} {'verdict':<9} {'stage':<8} what the audit says")
    for fl in flags:
        path = os.path.join(out, f"{fl['file']}-findings.json")
        if not os.path.exists(path):
            print(f"{fl['issue']:<7} {fl['file']:<6} {'(no run)':<9}")
            continue
        r = json.load(open(path))
        stages, chan, kinds = fl.get("stages") or [""], fl.get("channel"), set(fl["kinds"])
        hits = [x for x in r["findings"] if x["kind"] in kinds and x["stage"] in stages
                and (chan is None or x["channel"] == chan)]
        warn = [x for x in hits if x["severity"] == "warn"]
        expect = fl.get("expect", True)
        if warn:
            verdict = "FOUND" if expect else "STILL"
            detail = "; ".join(f"{x['kind']}[{x['stage'] or 'file'}] {x['evidence'][:70]}" for x in warn[:2])
        elif hits:
            verdict = "found(i)"
            detail = f"{hits[0]['kind']} info: {hits[0]['evidence'][:80]}"
        else:
            verdict = "REPAIRED" if not expect else "MISSED"
            detail = f"no {'/'.join(sorted(kinds))} on stage {'/'.join(stages) or 'file'}"
        print(f"{fl['issue']:<7} {fl['file']:<6} {verdict:<9} {'/'.join(stages) or 'file':<8} "
              f"{fl['said'][:38]:<38} → {detail}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
