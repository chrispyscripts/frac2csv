# Proving the page-art memo changed nothing but the clock

`frac_core.drawings()` replaced thirteen `page.get_drawings()` calls per page.
That is either a pure speed change or it is nothing, so the bar here is
**byte-identical output**, not "close enough" — every channel's full sample
array is hashed, not just its n/min/max.

## Run it

Both corpus drives must be mounted (`CnC-2TB-ssd`, `For-Chris-CnC-1TB`).

```
git worktree add --detach /tmp/OLD 3c1abbb     # v1.11.26, before the memo
git worktree add --detach /tmp/NEW e500cfa     # the memo
validation-tools/page-art-memo/sweep.sh /tmp/OLD /tmp/NEW 6
```

Frozen worktrees, not the working checkout: editing a tree while the sweep is
in flight measures neither version.

## What each piece is for

| | |
|---|---|
| `sample.py` | A spread sample per provider off the project's own `batch-lists`, so it is the population the sweeps already use. Takes files evenly spaced through each list, not the first N — the lists are size-ordered and the first N would be all small files, and size is what decides whether a reader takes its raster or its vector path. Maps Carmine's `F:\`/`K:\` paths onto the mac mounts. |
| `abdigest.py` | Runs `pipeline.extract_document` — the real router, so every reader a file touches is exercised — and digests each series and table. |
| `abcompare.py` | Diffs two digests. Exits non-zero on any difference at all. |
| `threadsafe.py` | The memo is thread-local because `localapp._READ_GATE` reads whole documents in threads and fitz drops the GIL. Shared, it would hand one reader another file's geometry. Checks that directly, and end to end. |
| `abtime.py` / `abtimecmp.py` | Speedup per provider. Reports CPU separately from wall: the corpus is on a USB drive, and a wall-clock number on cold files is mostly the cable. |
| `undef.py` | Finds names a function reads but nothing binds. Diff it across the two trees — the baseline noise cancels and only regressions show. This is what caught the Sanjel break. |

## Step 5 is not decoration

The sweep prints which readers actually fired. A provider missing from that
list was not tested, however many of its files went in. That is how the
Sanjel regression stayed invisible: the suite was green because nothing
reached the code.
