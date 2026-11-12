#!/usr/bin/env python3
"""Export WellSight logs (.sl6 .slg .hl6 .hlg) to LAS 2.0, choosing what goes in and the depth step.

    python3 -I export_las.py SRC_ROOT OUT_ROOT --what curves [--step 0.2] [--jobs 6] [--limit N] [--match TEXT] [--list FILE]

What can be exported (--what):
    curves   The curve-track data only: every curve in a track that holds curves (gamma, ROP, gas, mud
             weight, ...), on one regular depth step. Each output depth takes the nearest recorded reading:
             data recorded at a coarser step (0.5 m, 1 m) repeats over its interval, data recorded at a finer
             step (0.1 m) is thinned to every other reading. Nothing is averaged or interpolated.

Output mirrors the source tree: OUT_ROOT/<dir>/<file>.las, plus OUT_ROOT/index.csv and summary.json.
Standard library only. More export options plug into EXPORTS below.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert as cv  # noqa: E402
import wellsight as ws  # noqa: E402

TOOL = 'wellsight-convert export_las 1.0'


def curve_track_curves(log):
    """Curves with data from tracks that hold curves, depth-registered, minus '- unused -' slots."""
    return [c for c in log['curves'] if c['pad'] is not None and c['nonnull'] and (c['name'] or '').strip() != '- unused -']


def resample(c, top, step, k0, k1):
    """Values of curve c at depths top + k*step for k in [k0, k1]: nearest recorded reading (ties go deeper)."""
    s, n, vals = c['step'], c['samples'], c['values']
    out = []
    for k in range(k0, k1 + 1):
        x = k * step / s                     # position in the curve's own samples
        i = int(math.floor(x + 0.5 + 1e-9))
        if 0 <= i < n and abs(x - i) * s <= s / 2 + 1e-9:
            out.append(vals[i])
        else:
            out.append(None)
    return out


def export_curves(log, step):
    cs = curve_track_curves(log)
    if not cs or log['top'] is None:
        return None
    top = log['top']
    k1 = max(int(math.floor(((c['samples'] - 1) * c['step']) / step + 1e-9)) for c in cs)
    cols = [resample(c, top, step, 0, k1) for c in cs]
    rows = [k for k in range(0, k1 + 1) if any(col[k] is not None for col in cols)]
    if not rows:
        return None
    first, last = rows[0], rows[-1]
    grid = [top + k * step for k in range(first, last + 1)]
    cols = [col[first:last + 1] for col in cols]
    used, meta = set(), []
    for c in cs:
        mn = cv.mnemonic_for(c, used)
        s = c['step']
        if abs(s - step) < 1e-9:
            how = 'as recorded'
        elif s > step:
            how = 'recorded every %g m, nearest reading repeated' % s
        else:
            how = 'recorded every %g m, thinned to nearest reading' % s
        c2 = dict(c)
        c2['description'] = '%s (track %s; %s; source %s)' % (c['name'] or c['source_mnemonic'] or mn, c.get('track') or '-',
                                                          how, c['source_mnemonic'] or '-')
        meta.append((mn, c2))
    notes = [
        'Exported by %s from a WellSight %s %s file, without WellSight software.' % (TOOL, log['app'], log['version']),
        'Content: curve-track data only (no lithology, text or survey).',
        'Regular %g m step from the log top. Each depth takes the nearest recorded reading of each curve:' % step,
        'coarser data repeats over its interval, finer data is thinned; nothing is averaged or interpolated.',
        'Recorded depths are the stored depths; WellSight LogViewer draws most curves half a recorded step shallower.',
        'Header values are copied as written on the log.',
    ]
    return (grid, step), cols, meta, notes


EXPORTS = {
    'curves': export_curves,
}


def export_one(args):
    src_root, out_root, rel, what, step = args
    row = {'file': rel, 'status': '', 'reason': ''}
    try:
        raw = open(os.path.join(src_root, rel), 'rb').read()
        sha1 = hashlib.sha1(raw).hexdigest()
        log = ws.read_log(raw)
    except ws.NotReadable as ex:
        row.update(status='not_readable', reason=str(ex))
        return row
    except Exception as ex:  # noqa: BLE001
        row.update(status='error', reason='%s: %s' % (type(ex).__name__, ex))
        return row
    try:
        h = log['header']
        row.update(app=log['app'], version=log['version'], well_name=h.get('well_name', ''), licence=h.get('licence', ''),
                   well_id=h.get('well_id', ''))
        row['depth_axis'], row['depth_axis_basis'] = ws.decide_axis(log.get('axis_votes') or (0, 0), os.path.basename(rel))
        res = EXPORTS[what](log, step)
        if not res:
            row['status'] = 'nothing_to_export'
            return row
        table, cols, meta, notes = res
        out = os.path.join(out_root, rel + '.las')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cv.write_las(out, log, rel, sha1, table, cols, meta, notes=notes)
        row.update(status='ok', start=round(table[0][0], 4), stop=round(table[0][-1], 4), step=step, rows=len(table[0]),
                   curves=len(meta), curve_list=';'.join(mn for mn, _ in meta),
                   recorded_steps=';'.join('%g' % c['step'] for _, c in meta),
                   tracks=';'.join(sorted({c.get('track') or '-' for _, c in meta})))
    except Exception as ex:  # noqa: BLE001
        import traceback
        tb = traceback.extract_tb(ex.__traceback__)[-1]
        row.update(status='error', reason='%s: %s (%s line %d)' % (type(ex).__name__, ex, os.path.basename(tb.filename), tb.lineno))
    return row


FIELDS = ['file', 'status', 'reason', 'app', 'version', 'depth_axis', 'depth_axis_basis', 'well_name', 'licence', 'well_id', 'start', 'stop', 'step', 'rows',
          'curves', 'curve_list', 'recorded_steps', 'tracks']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('out')
    ap.add_argument('--what', choices=sorted(EXPORTS), default='curves')
    ap.add_argument('--step', type=float, default=0.2, help='output depth step in metres (default 0.2)')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--match', default='')
    ap.add_argument('--list', help='file with paths relative to SRC_ROOT, one per line (any extension)')
    a = ap.parse_args()
    if a.list:
        rels = [x for x in open(a.list).read().split('\n') if x and a.match in x]
    else:
        rels = []
        for dp, dn, fn in os.walk(a.src):
            dn[:] = sorted(dn)
            for n in sorted(fn):
                if n.lower().endswith(cv.EXTS) and not n.startswith('._'):
                    rel = os.path.relpath(os.path.join(dp, n), a.src)
                    if a.match in rel:
                        rels.append(rel)
    if a.limit:
        rels = rels[:a.limit]
    os.makedirs(a.out, exist_ok=True)
    t0, rows = time.time(), []
    with Pool(a.jobs) as pool:
        for i, row in enumerate(pool.imap(export_one, [(a.src, a.out, r, a.what, a.step) for r in rels], chunksize=4), 1):
            rows.append(row)
            if i % 500 == 0 or i == len(rels):
                print('%d/%d files, %.0fs' % (i, len(rels), time.time() - t0), flush=True)
    with open(os.path.join(a.out, 'index.csv'), 'w', encoding='utf-8', newline='') as f:
        cw = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        cw.writeheader()
        cw.writerows(rows)
    summary = {'tool': TOOL, 'what': a.what, 'step_m': a.step, 'source_root': a.src, 'files': len(rows),
               'status': dict(Counter(r['status'] for r in rows)), 'curves': sum(int(r.get('curves') or 0) for r in rows),
               'seconds': round(time.time() - t0, 1)}
    with open(os.path.join(a.out, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
