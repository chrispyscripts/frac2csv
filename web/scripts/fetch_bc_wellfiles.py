#!/usr/bin/env python3
"""Fetch BC completion-report PDFs from the BCER eLibrary FTP.

Auth: reads credentials from ~/.netrc (machine files.bc-er.ca) via curl
--netrc — the password never appears in code, args, or process lists.

Flow per WA number:
  1. anonymous BIL-184 index (reports.bc-er.ca) -> exact eLibrary filenames
  2. FTP fetch of the COMP PDFs (layout auto-discovered on first run)

Usage:
  python3 fetch_bc_wellfiles.py --discover           # explore FTP layout
  python3 fetch_bc_wellfiles.py 33088 53559 ...      # fetch COMP PDFs
  python3 fetch_bc_wellfiles.py --all-types 33088    # every filed doc
"""
import argparse
import os
import re
import subprocess
import sys

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 Chrome/126.0 Safari/537.36")
INDEX = "https://reports.bc-er.ca/ogc/r/app001/ams_reports/3?IR_ROWFILTER={wa}"
FTP = "ftp://files.bc-er.ca"
OUT_DIR = os.path.expanduser("~/Documents/Chris Vault/frac-pdf-extract/bc-corpus")


def curl(args, timeout=180):
    return subprocess.run(["curl", "-sS", "--netrc", *args],
                          capture_output=True, text=True, timeout=timeout)


def index_filenames(wa):
    """Anonymous filename lookup from the BIL-184 APEX report."""
    r = subprocess.run(["curl", "-sS", "-A", UA, "-L", INDEX.format(wa=wa)],
                       capture_output=True, text=True, timeout=120)
    names = sorted(set(re.findall(rf"{wa}_[A-Za-z0-9_.-]+", r.stdout)))
    # filenames render as plain text; keep ones with an extension
    return [n for n in names if "." in n]


def ftp_list(path=""):
    r = curl(["--list-only", f"{FTP}/{path}"])
    if r.returncode != 0:
        return None, r.stderr.strip()
    return [l.strip() for l in r.stdout.splitlines() if l.strip()], None


def discover():
    print("== FTP root listing ==")
    entries, err = ftp_list("")
    if err is not None and entries is None:
        print("FTP error:", err)
        print("Check ~/.netrc has: machine files.bc-er.ca / login ... / password ...")
        sys.exit(1)
    for e in entries[:40]:
        print("  ", e)
    if len(entries) > 40:
        print(f"   ... {len(entries) - 40} more")
    # peek into the first few directories
    for e in entries[:5]:
        sub, err = ftp_list(e + "/")
        if sub:
            print(f"== {e}/ ==")
            for s in sub[:10]:
                print("  ", s)
    return entries


def find_well_dir(wa, root_entries=None):
    """eLibrary layout: WellData/{00000-00999 style bucket}/{WA}/"""
    n = int(wa)
    kbucket = f"{n // 1000 * 1000:05d}-{n // 1000 * 1000 + 999:05d}"
    hbucket = f"{n // 100 * 100:05d}-{n // 100 * 100 + 99:05d}"
    path = f"WellData/{kbucket}/{hbucket}/{wa}"
    sub, _ = ftp_list(path + "/")
    if sub:
        return path, sub
    return None, None


def fetch(wa, all_types=False, root_entries=None):
    wa = wa.strip().lstrip("0").zfill(5)
    names = index_filenames(wa)
    wanted = names if all_types else [n for n in names if "_COMP_" in n and n.upper().endswith(".PDF")]
    print(f"\nWA {wa}: index lists {len(names)} files, fetching {len(wanted)}: {wanted}")
    if not wanted:
        return
    well_dir, listing = find_well_dir(wa, root_entries)
    if well_dir is None:
        print(f"  !! couldn't locate WA {wa} directory on FTP — run --discover and "
              f"adjust find_well_dir() to the real layout")
        return
    os.makedirs(os.path.join(OUT_DIR, wa), exist_ok=True)
    lookup = {l.lower(): l for l in listing}
    for name in wanted:
        remote = lookup.get(name.lower(), name)
        dest = os.path.join(OUT_DIR, wa, remote)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"  = {remote} (already here)")
            continue
        r = curl(["-o", dest, f"{FTP}/{well_dir}/{remote}"], timeout=600)
        ok = r.returncode == 0 and os.path.getsize(dest) > 1000
        print(f"  {'✓' if ok else '✗'} {remote} "
              f"({os.path.getsize(dest) // 1024} KB)" if os.path.exists(dest) else f"  ✗ {remote}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("was", nargs="*", help="WA numbers")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--all-types", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(os.path.expanduser("~/.netrc")):
        print("~/.netrc not found — add the files.bc-er.ca entry first.")
        sys.exit(1)
    root = None
    if args.discover or args.was:
        root = discover() if args.discover else None
    for wa in args.was:
        fetch(wa, all_types=args.all_types, root_entries=root)


if __name__ == "__main__":
    main()
