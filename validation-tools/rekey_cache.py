"""Re-key the Lab's cached results after the code stamp changed.

    python3 validation-tools/rekey_cache.py <old_stamp> [cluster.tsv]

The cache key is sha1(path|size|mtime|stamp), and the stamp is the newest
reader module's mtime — so a reader edit (intended) retires every result,
and so does a touch that changed nothing (not intended). When the results
are known good, this renames each cluster file's entry from the old stamp
to the current one. Old stamps: `1.9.0-1789609855` (pre-1.10.0 formula),
`1789593075`, `1789623280`.
"""
import csv, hashlib, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import localapp  # noqa: E402

ROOT = "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023"


def main():
    old_stamp = sys.argv[1]
    cluster = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "batch-lists", "bc-cluster-2026-09-16.tsv")
    d = localapp.data_dir("results")
    moved = have = 0
    for r in csv.DictReader(open(cluster), delimiter="\t"):
        p = os.path.join(ROOT, r["FILE"])
        if not os.path.exists(p):
            continue
        st = os.stat(p)
        old = hashlib.sha1(f"{os.path.abspath(p)}|{st.st_size}|{int(st.st_mtime)}|{old_stamp}".encode()).hexdigest()
        src, dst = os.path.join(d, old + ".json.gz"), os.path.join(d, localapp.cache_key(p) + ".json.gz")
        if os.path.exists(src) and not os.path.exists(dst):
            os.rename(src, dst)
            moved += 1
        have += os.path.exists(dst)
    print(f"re-keyed {moved}; cached under the current stamp {localapp.code_stamp()}: {have}")


if __name__ == "__main__":
    main()
