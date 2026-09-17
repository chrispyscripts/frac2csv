# Handoff — 2026-09-16 evening

Carry this into the next session. Repo: `frac-pdf-extract/frac2csv` (the git
repo is that directory; `main`; remote `chrispyscripts/frac2csv`). The
long-lived notes are `HANDOFF.md`; this file is only what is in flight tonight.

## 1. What was done tonight

**"The export button for seconds data isn't working"** — it was working, silently.
- The SSD is NTFS, which macOS mounts read-only, so the Lab's `/api/save` falls
  back to `~/Downloads`. Pad 8's ten wells landed there (20 files, 19:33–19:36).
- A 40-stage well is a 15 MB CSV and its XLSX takes the browser ~20 s to build,
  so a 66-well batch ran 20+ minutes with no progress shown, and the new
  export-options pop-up (outside `.exportwrap`) closed the export panel, hiding
  the one line it prints at the end.
- Fixed in `lab/public/index.html`: `exportBatch()` (per-file progress on each
  row and in the panel, every CSV before any XLSX, failures listed, batch keeps
  going), `emit` throws the server's reason, the pop-up no longer closes the
  panel, Settings → "Earlier analyses" (Reuse / Re-read every file).
- `localapp.py`: results cache. Every `/api/process-path` result is stored as
  gzip JSON in `~/Library/Application Support/Frac2CSV/results/`
  (`%LOCALAPPDATA%\Frac2CSV\results` on Windows), newest ~2 GB kept, key =
  sha1(path | size | mtime | code stamp). `code_stamp()` = newest mtime among the
  reader modules (everything in `_NOT_A_READER` is excluded: localapp, version,
  the GUI shell, the Stratum builders). A re-dropped list comes back in <1 s
  (`cached: true`, row says "reused earlier analysis").
- `lab/tools/export-analyzed.js`: paste into the JS console of a tab analysed
  BEFORE the cache existed; saves every well's seconds CSV from memory.
- Verified on a test portal: batch export with progress, modal shown, panel
  stays open, files identical to the earlier Downloads copies, cache hit 0.6 s.

**v1.10.0 released** (commit `8af9f45`, tag `v1.10.0`, pushed).
- `version.py` = 1.10.0, download page `download/index.html` has the v1.10.0
  notes and is deployed: https://frac2csv-download.vercel.app (shows v1.10.0).
- GitHub Actions run 35173203549 (`build-windows`) was in progress when this
  was written. It creates the release with only the auto "Full Changelog" line.
- **To do once the build finishes:** put the descriptions on the release:
  ```bash
  cd "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv" && gh run view 35173203549 --json status,conclusion -q '.status+" "+.conclusion' && gh release edit v1.10.0 --notes-file release-notes/v1.10.0.md && gh release view v1.10.0 --json assets -q '.assets|map(.name)|join(", ")'
  ```
  Expect `completed success` and the asset `Frac2CSV.exe`. If the run failed,
  `gh run view 35173203549 --log-failed`.

**Stratum: pad 8 (10 wells) has treatment curves on the site** (local only, not
deployed yet). `stages_from_csv.py` now merges the BCER port skeleton (depth by
stage number, kept under `bcer_stages`); `pad_json.py` preserves every key a
well file already carries (another session adds `engineering_stages` /
`depth_intervals`). 601 tests pass.

## 2. What is still running (do not kill)

- **`validation-tools/exportrun.py`** (copy of the scratchpad script), launched
  with nohup at ~19:55: 5 workers reading the 66 Gundy filings that had no
  export, writing `../exports/bc-gundy-cluster/lab-seconds/<report>-seconds.csv`
  + the stage table CSV, and filling the results cache. ~3–5 min a file, 16/66
  done at 20:15, 0 failures, ETA ~21:00. Log:
  `/private/tmp/claude-501/-Users-chrisharder-Documents-Chris-Vault/0ddd20c9-5c61-4a53-9c0a-2fd3bc825797/scratchpad/exportrun.log`
  (lines `done <file>: N stages…` / `FAIL …` / `ALL DONE`). Check with:
  ```bash
  ls "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/exports/bc-gundy-cluster/lab-seconds"/*-seconds.csv | wc -l; pgrep -f exportrun.py | wc -l
  ```
  76 seconds CSVs = complete. It skips files whose seconds CSV exists, so if it
  died, just run it again: `python3 validation-tools/exportrun.py` (from
  `frac2csv/`, drive `/Volumes/CnC-2TB-ssd` mounted).
- **Portals** (`lsof -nP -iTCP -sTCP:LISTEN | grep -i python`):
  - 61103, 50903, 50904 — Chris's own Lab portals, OLD code (no cache). His
    tab with the 66 analysed wells is on one of these. **Never kill these.**
  - 56157 (pid 31056) — my test portal, code from just before the version
    bump. Safe to kill when done: `kill 31056`. A fresh portal on the new code:
    `cd frac2csv && F2C_NO_BROWSER=1 python3 localapp.py` (URL printed to the
    log in `~/Library/Logs/Frac2CSV/`).
  - 8766 — `python3 -m http.server` on `web/public` (Stratum static preview).
    8765 belongs to another session. 50821 / 60066 are Sep 13–14 desktop
    instances; leave them.

## 3. Next steps, in order

1. **Release notes on GitHub** — command in §1 above.
2. **When exportrun says ALL DONE, re-key its cache files.** The workers
   stamped them with the pre-bump formula (`1.9.0-1789609855`); the new stamp is
   `1789593075` (`python3 -c "import localapp; print(localapp.code_stamp())"`
   from `frac2csv/`). Rename so a new portal reuses them:
   ```bash
   cd "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv" && python3 - <<'EOF'
   import csv, hashlib, os, localapp
   d = localapp.data_dir("results"); root = "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023"
   n = 0
   for r in csv.DictReader(open("../batch-lists/bc-cluster-2026-09-16.tsv"), delimiter="\t"):
       p = os.path.join(root, r["FILE"]); st = os.stat(p)
       old = hashlib.sha1(f"{os.path.abspath(p)}|{st.st_size}|{int(st.st_mtime)}|1.9.0-1789609855".encode()).hexdigest()
       src = os.path.join(d, old + ".json.gz"); dst = os.path.join(d, localapp.cache_key(p) + ".json.gz")
       if os.path.exists(src) and not os.path.exists(dst): os.rename(src, dst); n += 1
   print("re-keyed", n)
   EOF
   ```
   (The 10 pad-8 files were cached by the test portal with the same old stamp;
   the same loop covers them.) Then drop `batch-lists/bc-cluster-2026-09-16.txt`
   on a NEW portal: all 76 rows should say "reused earlier analysis" within
   seconds, and Export → Seconds → all works from there.
3. **Load all 76 wells into Stratum and deploy:**
   ```bash
   cd "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv" && python3 stages_from_csv.py --folder ../exports/bc-gundy-cluster/lab-seconds --cluster ../batch-lists/bc-cluster-2026-09-16.tsv && python3 pad_json.py --cluster ../batch-lists/bc-cluster-2026-09-16.tsv --surveys ../exports/bc-gundy-cluster/gundy-cluster-trajectories.csv --surface ../exports/bc-gundy-cluster/surface.csv --pad-set gundy
   ```
   Expect "76 wells with Lab exports, 0 without". Check
   http://127.0.0.1:8766/well.html?wa=28744 and `pad.html?set=gundy` (the
   "With curves" column). Then commit **only** these paths (another session
   has uncommitted edits in `web/public/` — `cluster-underground.*`,
   `underground.json`, `engineering-import.json`; never `git add -A`):
   ```bash
   cd "/Users/chrisharder/Documents/Chris Vault/frac-pdf-extract/frac2csv" && git add web/public/data/pads/gundy.json web/public/data/wells/index.json web/public/data/wells/[0-9]*.json && git commit -m "Stratum: every Gundy well with its treatment curves" && cd web && npx vercel deploy --prod --yes
   ```
   Production alias: https://frac2csv-web.vercel.app (map.html / pad.html / well.html).
4. Optional: also copy the 66 new seconds CSVs to `~/Downloads` if Chris wants
   them beside pad 8's (`cp ../exports/bc-gundy-cluster/lab-seconds/*-seconds.csv ~/Downloads/`).
5. Update `HANDOFF.md` §"The Lab keeps its results" if anything above changes.

## 4. Gotchas that cost time tonight

- `/api/manifest` wants `{"text": "<the list text>"}` in the Lab's format
  (`UWI<TAB>K:\BCER-Frac\Spud-2019-2023\<file>.pdf`); paths must be resolved
  through it before `/api/process-path` accepts them (`ALLOWED_FILES`).
- The Lab's log is `~/Library/Logs/Frac2CSV/frac2csv-<stamp>.log`; `/api/save`
  failures return JSON and are NOT logged.
- `pytest` for the Xcode python3 was installed tonight (`python3 -m pytest tests -q`).
- Editing any reader `.py` changes `code_stamp()` and retires every cached
  result; that is intended. Editing `localapp.py`, `version.py` or the
  Stratum builders does not.
- Claude-in-Chrome was not connected, so the user's analysed tab could not be
  driven from here; the paste-in script is the fallback for that tab.
- eLibrary credentials: `~/.netrc` (files.bc-er.ca) and `BCER_FTP_USER/PASS` on
  Vercel. Never print or commit them.

## 5. Open reader items (unchanged)

CalFrac "Surface 2" overview pages read as a last-zone stage; Trican pasted
screenshots (00564/00565/00569); SLB whole-job-only books (splittable via
"Interval summaries"); Trican scan dating. See `HANDOFF.md`.
