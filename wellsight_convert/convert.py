#!/usr/bin/env python3
"""Convert WellSight logs (.sl6 .slg .hl6 .hlg) to LAS 2.0 + CSV + JSON.

    python3 -I convert.py SRC_ROOT OUT_ROOT [--jobs 6] [--limit N] [--match TEXT]

For every native file under SRC_ROOT it writes, mirrored under OUT_ROOT:
    <file>.las   LAS 2.0, all depth-registered curves on one depth index (metres)
    <file>.csv   the same table (DEPTH_M + one column per curve, empty = null)
    <file>.json  header, header boxes, custom header page, curve list, depth-tagged text, warnings
and OUT_ROOT/index.csv with one row per source file (including unreadable ones).
Standard library only.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import time
from functools import reduce
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wellsight as ws  # noqa: E402

EXTS = ('.sl6', '.slg', '.hl6', '.hlg')
TOOL = 'wellsight-convert 1.4'
_ASCII = str.maketrans({'°': ' deg', '±': '+/-', 'µ': 'u', '’': "'", '‘': "'",
                        '“': '"', '”': '"', '–': '-', '—': '-', ' ': ' '})


def ascii_line(s):
    s = (s or '').translate(_ASCII).replace('\r\n', ' | ').replace('\n', ' | ').replace('\r', ' | ').replace('\t', ' ')
    s = s.encode('ascii', 'replace').decode('ascii')
    return re.sub(r'\s{2,}', ' ', s).strip()


def mnemonic_for(c, used):
    base = c.get('mnem') or re.sub(r'[^A-Z0-9]+', '_', (c['name'] or c['source_mnemonic'] or 'CURVE').upper()).strip('_')[:24] or 'CURVE'
    if base[0].isdigit():
        base = 'C_' + base
    m, k = base, 2
    while m in used or m == 'DEPT':
        m = '%s_%d' % (base, k)
        k += 1
    used.add(m)
    return m


def fmt(v):
    if v is None:
        return None
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))          # whole numbers (incl. large symbol ids) exactly
    return format(v, '.7g')


def lith_curves(log, lith):
    """Lithology as LAS curves (LITH = symbol id per sample; PCT_<rock> from a % lithology column) + interval table."""
    extra, intervals = [], []
    if not lith or lith.get('error') or log['top'] is None:
        return extra, intervals
    syms = lith.get('_lith_symbols') or {}
    ah = lith.get('along_hole')
    if ah:
        codes = ah['codes']
        vals = [float(c) if c else None for c in codes]
        used = sorted({c for c in codes if c})
        table = {c: ('%s %s' % (syms.get(c, (str(c), ''))[0], ws.ROCK_NAMES.get(syms.get(c, (str(c), ''))[0].upper(), ''))).strip()
                 for c in used}
        extra.append({'mnem': 'LITH', 'name': 'Lithology', 'units': '', 'source_mnemonic': 'LITH', 'step': ah['step_m'],
                      'samples': len(codes), 'pad': 0, 'values': vals, 'nonnull': sum(1 for v in vals if v is not None),
                      'first_depth': log['top'], 'offset': -1, 'code_table': table,
                      'description': 'LITHOLOGY SYMBOL ID (%s; codes in ~Other)' % ah['source']})
        for iv in ws.lith_intervals(log['top'], ah['step_m'], codes, syms):
            iv['source'] = ah['source']
            intervals.append(iv)
    pc = lith.get('percent')
    if pc:
        for k, rid in enumerate(pc['rocks']):
            code = syms.get(rid, (str(rid), ''))[0]
            vals = [row[k] if row is not None else None for row in pc['values']]
            extra.append({'mnem': 'PCT_' + (re.sub(r'[^A-Z0-9]+', '_', code.upper()).strip('_') or str(rid)), 'name': '% ' + code,
                          'units': '%', 'source_mnemonic': '% Lithology', 'step': pc['step_m'], 'samples': len(vals), 'pad': 0,
                          'values': vals, 'nonnull': sum(1 for v in vals if v), 'first_depth': log['top'], 'offset': -2 - k,
                          'description': 'PERCENT %s (%s) FROM %% LITHOLOGY COLUMN' % (code, ws.ROCK_NAMES.get(code.upper(), code))})
    return extra, intervals


def build_table(log, extra=()):
    """Place every registered curve on one depth grid (gcd of steps). Returns (grid, cols, curve_meta)."""
    cs = [c for c in log['curves'] if c['pad'] is not None and c['nonnull'] and (c['name'] or '').strip() != '- unused -']
    cs += [c for c in extra if c['nonnull']]
    if not cs:
        return None, [], []
    ints = [int(round(c['step'] * 10000)) for c in cs]
    g = reduce(math.gcd, ints)
    start = min(c['first_depth'] for c in cs)
    stop = max(c['first_depth'] + (c['samples'] - 1) * c['step'] for c in cs)
    n = int(round((stop - start) * 10000 / g)) + 1
    if n > 3_000_000:
        raise RuntimeError('depth grid too large (%d rows)' % n)
    used, cols, meta = set(), [], []
    for c, si in zip(cs, ints):
        col = [None] * n
        o = int(round((c['first_depth'] - start) * 10000 / g))
        stride = si // g
        for i, v in enumerate(c['values']):
            if v is not None:
                col[o + i * stride] = v
        mn = mnemonic_for(c, used)
        cols.append(col)
        meta.append((mn, c))
    # trim rows where every curve is null
    first = next((i for i in range(n) if any(col[i] is not None for col in cols)), None)
    last = next((i for i in range(n - 1, -1, -1) if any(col[i] is not None for col in cols)), None)
    if first is None:
        return None, [], []
    step = g / 10000.0
    rows = range(first, last + 1)
    finest = min(ints)
    if any(si % finest for si in ints):
        # steps do not nest (e.g. 0.2 and 0.5): keep only depths where some curve has a sample; LAS STEP = 0
        rows = [i for i in rows if any(col[i] is not None for col in cols)]
        step = 0.0
    grid = [start + i * g / 10000.0 for i in rows]
    _DEC[id(grid)] = max(1, _decimals(g / 10000.0), _decimals(start))   # decimals that every grid depth needs
    cols = [[col[i] for i in rows] for col in cols]
    return (grid, step), cols, meta


def _decimals(x):
    s = ('%.4f' % x).rstrip('0')
    return len(s.split('.')[1]) if '.' in s else 0


_DEC = {}


def depth_format(table):
    grid, step = table
    dec = _DEC.get(id(grid)) or max([1, _decimals(step)] + [_decimals(d) for d in grid])
    return '%.' + str(min(dec, 4)) + 'f'


def write_las(path, log, rel, sha1, table, cols, meta, notes=None):
    (grid, step) = table
    h = log['header']
    df = depth_format(table)
    out = io.StringIO()
    w = out.write
    w('~Version Information\n')
    w(' VERS.                 2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0\n')
    w(' WRAP.                  NO : ONE LINE PER DEPTH STEP\n')
    w('~Well Information\n')
    w('#MNEM.UNIT     VALUE : DESCRIPTION\n')

    def line(mn, unit, val, desc):
        w(' %-5s.%-6s %s : %s\n' % (mn, unit, ascii_line(val), desc))
    line('STRT', 'M', df % grid[0], 'START DEPTH')
    line('STOP', 'M', df % grid[-1], 'STOP DEPTH')
    line('STEP', 'M', df % step, 'STEP' if step else 'STEP (0 = VARIABLE: CURVE STEPS DO NOT NEST)')
    line('NULL', '', '-999.25', 'NULL VALUE')
    line('COMP', '', h.get('operator', ''), 'COMPANY (OPERATOR)')
    line('WELL', '', h.get('well_name', ''), 'WELL')
    line('FLD', '', h.get('region', ''), 'FIELD (REGION ON LOG HEADER)')
    line('LOC', '', h.get('location', ''), 'LOCATION')
    line('SRVC', '', h.get('geologist_company', ''), 'SERVICE COMPANY (WELLSITE GEOLOGY)')
    line('DATE', '', h.get('spud_date', ''), 'SPUD DATE (AS WRITTEN ON LOG)')
    line('UWI', '', h.get('well_id', ''), 'UNIQUE WELL ID')
    line('LIC', '', h.get('licence', ''), 'LICENCE NUMBER')
    w('~Curve Information\n')
    w('#MNEM.UNIT     API CODE : CURVE DESCRIPTION\n')
    axis, basis = ws.decide_axis(log.get('axis_votes') or (0, 0), os.path.basename(rel))
    w(' DEPT .M                 : %s\n' % ('TRUE VERTICAL DEPTH' if axis == 'TVD' else 'MEASURED DEPTH'))
    for mn, c in meta:
        unit = re.sub(r'\s+', '_', ascii_line(c['units'] or ''))
        desc = ascii_line(c.get('description') or '%s (source %s, step %g m)' % (c['name'] or c['source_mnemonic'] or mn, c['source_mnemonic'] or '-', c['step']))
        w(' %-5s.%-16s : %s\n' % (mn, unit, desc))
    w('~Parameter Information\n')
    w('#MNEM.UNIT     VALUE : DESCRIPTION\n')
    for mn, key, desc in (('EGL', 'ground_elevation', 'GROUND ELEVATION (AS WRITTEN)'), ('EKB', 'kb_elevation', 'KB ELEVATION (AS WRITTEN)'),
                          ('TDD', 'total_depth', 'TOTAL DEPTH (AS WRITTEN)'), ('LTOP', 'logged_interval_top', 'LOGGED INTERVAL TOP (AS WRITTEN)'),
                          ('LBOT', 'logged_interval_bottom', 'LOGGED INTERVAL BOTTOM (AS WRITTEN)'), ('FORM', 'formation', 'FORMATION'),
                          ('MUD', 'drilling_fluid', 'DRILLING FLUID'), ('CMPL', 'completion_date', 'DRILLING COMPLETED'),
                          ('SFCO', 'surface_coordinates', 'SURFACE COORDINATES'), ('BHCO', 'bottom_hole_coordinates', 'BOTTOM HOLE COORDINATES')):
        line(mn, '', h.get(key, ''), desc)
    line('SCAL', '', log['scale'] or '', 'PRINT SCALE')
    line('LTP', 'M', '%g' % log['top'], 'LOG TOP DEPTH IN SOURCE')
    line('LBT', 'M', '%g' % log['bottom'], 'LOG BOTTOM DEPTH IN SOURCE')
    line('SRC', '', rel, 'SOURCE FILE')
    line('SHA1', '', sha1, 'SOURCE FILE SHA-1')
    line('SAPP', '', '%s %s' % (log['app'], log['version']), 'SOURCE APPLICATION AND VERSION')
    w('~Other Information\n')
    for line in notes if notes is not None else [
            'Converted by %s from a WellSight %s %s file, without WellSight software.' % (TOOL, log['app'], log['version']),
            'Each value sits at its stored depth. WellSight LogViewer draws it half a step shallower,',
            'at the middle of the interval that ends at that depth (checked against the printed PDFs).',
            'Curves with different steps share one depth index; a curve is null between its own samples.',
            'Header values are copied as written on the log. Formation tops, descriptions and comments are in the .json file.']:
        w(' ' + ascii_line(line) + '\n')
    w(' Depth axis: %s - %s.\n' % ('true vertical depth' if axis == 'TVD' else 'measured depth', basis))
    lt = [c for mn, c in meta if c.get('mnem') == 'LITH']
    if lt:
        w(' LITH holds a WellSight lithology symbol id. A value at a depth holds from that depth down to the next LITH sample.\n')
        w(' LITH codes: ' + '; '.join('%d=%s' % (k, ascii_line(v)) for k, v in sorted(lt[0]['code_table'].items())) + '\n')
    if any(c.get('mnem', '').startswith('PCT_') for mn, c in meta):
        w(' PCT_ curves: percent of each rock in the % lithology column (10 % cells).\n')
    w('~A  DEPT ' + ' '.join(mn for mn, _ in meta) + '\n')
    for r, d in enumerate(grid):
        w(df % d)
        for col in cols:
            v = col[r]
            w(' ' + (fmt(v) if v is not None else '-999.25'))
        w('\n')
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        f.write(out.getvalue())


def write_csv(path, table, cols, meta):
    (grid, step) = table
    df = depth_format(table)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        cw = csv.writer(f)
        cw.writerow(['DEPTH_M'] + ['%s [%s]' % (mn, c['units']) if c['units'] else mn for mn, c in meta])
        for r, d in enumerate(grid):
            cw.writerow([df % d] + [fmt(col[r]) or '' for col in cols])


def convert_one(args):
    src_root, out_root, rel = args
    src = os.path.join(src_root, rel)
    row = {'file': rel, 'status': '', 'reason': ''}
    t0 = time.time()
    try:
        raw = open(src, 'rb').read()
        row['size'] = len(raw)
        sha1 = hashlib.sha1(raw).hexdigest()
        row['sha1'] = sha1
        log = ws.read_log(raw)
    except ws.NotReadable as ex:
        row.update(status='not_readable', reason=str(ex))
        return row
    except Exception as ex:  # noqa: BLE001
        row.update(status='error', reason='%s: %s' % (type(ex).__name__, ex))
        return row
    try:
        h = log['header']
        row.update(app=log['app'], version=log['version'], container=log['container'],
                   header_source=log['header_source'] or '', well_name=h.get('well_name', ''), licence=h.get('licence', ''),
                   well_id=h.get('well_id', ''), location=h.get('location', ''), operator=h.get('operator', ''),
                   log_top=log['top'], log_bottom=log['bottom'], annotations=len(log['annotations']))
        row['depth_axis'], row['depth_axis_basis'] = ws.decide_axis(log.get('axis_votes') or (0, 0), os.path.basename(rel))
        out_base = os.path.join(out_root, rel)
        os.makedirs(os.path.dirname(out_base), exist_ok=True)
        lith = log.get('lithology') or {}
        extra, lith_iv = lith_curves(log, lith)
        table, cols, meta = build_table(log, extra) if log['top'] is not None else (None, [], [])
        outputs = []
        if table:
            write_las(out_base + '.las', log, rel, sha1, table, cols, meta)
            write_csv(out_base + '.csv', table, cols, meta)
            outputs += ['las', 'csv']
            row.update(las_start=round(table[0][0], 4), las_stop=round(table[0][-1], 4), las_step=table[1], las_rows=len(table[0]))
        mn_of = {id(c): mn for mn, c in meta}
        pics = []
        for k, bmp in enumerate(log['pictures'], 1):
            try:
                png = ws.bmp_to_png(bmp)
            except Exception:  # noqa: BLE001
                continue
            name = '%s.picture-%d.png' % (os.path.basename(out_base), k)
            with open(os.path.join(os.path.dirname(out_base), name), 'wb') as f:
                f.write(png)
            pics.append(name)
        if pics:
            outputs.append('png')
        base_name = os.path.basename(out_base)
        if lith_iv:
            with open(out_base + '.lithology.csv', 'w', encoding='utf-8', newline='') as f:
                cw = csv.writer(f)
                cw.writerow(['top_m', 'base_m', 'code', 'rock', 'symbol_id', 'source'])
                for iv in lith_iv:
                    cw.writerow([iv['top_m'], iv['base_m'], iv['code'], iv['name'], iv['symbol_id'], iv['source']])
            outputs.append('lithology')
        sv = lith.get('survey') or []
        if sv:
            with open(out_base + '.survey.csv', 'w', encoding='utf-8', newline='') as f:
                cw = csv.writer(f)
                cw.writerow(['md_m', 'tvd_m', 'inclination_deg', 'azimuth_deg', 'source'])
                for st in sv:
                    cw.writerow([st['md'], st['tvd'], '' if st['inc'] is None else st['inc'], '' if st['azi'] is None else st['azi'],
                                 lith.get('survey_source') or ''])
            outputs.append('survey')
        acc = log.get('accessories') or []
        if acc:
            with open(out_base + '.accessories.csv', 'w', encoding='utf-8', newline='') as f:
                cw = csv.writer(f)
                cw.writerow(['depth_m', 'category', 'code', 'symbol_id', 'size'])
                for a in acc:
                    cw.writerow([a['depth_m'], a['category'], a['code'], a['symbol_id'], a['size']])
            outputs.append('accessories')
        lith_doc = None
        if lith:
            used_ids = sorted({x for c in (lith.get('columns') or []) for x in c.get('symbols_used', [])})
            lsyms = lith.get('_lith_symbols') or {}
            lith_doc = {
                'error': lith.get('error'),
                'along_hole_source': (lith.get('along_hole') or {}).get('source'),
                'step_m': (lith.get('along_hole') or {}).get('step_m'),
                'convention': 'an interval runs from top_m down to base_m; sample i covers top + i*step to top + (i+1)*step '
                              '(matches the printed lithology blocks)',
                'intervals': lith_iv,
                'percent_rocks': [lsyms.get(r, (str(r), ''))[0] for r in (lith.get('percent') or {}).get('rocks', [])],
                'symbols': {str(k): {'code': v[0], 'label': v[1], 'rock': ws.ROCK_NAMES.get(v[0].upper(), v[0])}
                            for k, v in sorted(lsyms.items())},
                'symbols_used': used_ids,
                'columns': lith.get('columns'),
                'other_symbol_columns': lith.get('symbol_columns'),
                'survey': sv,
                'survey_source': lith.get('survey_source'),
                'md_tvd_points_from_text': lith.get('md_tvd_points_from_text'),
                'xsection_window': lith.get('xsection_window'),
                'xsection': lith.get('xsection'),
            }
            if lith.get('along_hole') is None and lith.get('xsection') and not sv:
                lith_doc['note'] = ('cross-section lithology present but no drilled well path is stored, so no along-hole lithology. '
                                    'MD/TVD values stated in the log text are listed in md_tvd_points_from_text; they are too sparse '
                                    'to place the bit in the cross-section (tested: no better than guessing).')
        row.update(lith_source=(lith.get('along_hole') or {}).get('source', '') if lith else '',
                   lith_intervals=len(lith_iv), survey_stations=len(sv), accessories=len(acc))
        doc = {
            'tool': TOOL, 'source': {'file': rel, 'sha1': sha1, 'bytes': len(raw), 'container': log['container'],
                                     'app': log['app'], 'version': log['version'], 'inflated_bytes': log['inflated_bytes']},
            'depth': {'unit': 'm', 'axis': row['depth_axis'], 'axis_basis': row['depth_axis_basis'], 'log_top': log['top'], 'log_bottom': log['bottom'], 'print_scale': log['scale'],
                      'convention': 'value at stored depth (top + i*step); LogViewer draws it half a step shallower, mid-interval'},
            'header_source': log['header_source'], 'header': h,
            'header_boxes': [{'title': b['title'], 'fields': b['fields'], 'text': b['text']} for b in log['boxes']
                             if b['fields'] or b['text'].strip()],
            'custom_header': log['custom_header'],
            'curves': [{'las_mnemonic': mn_of.get(id(c)), 'name': c['name'], 'units': c['units'], 'source_offset': c['offset'],
                        'source_mnemonic': c['source_mnemonic'], 'track': c.get('track'), 'step_m': c['step'], 'samples': c['samples'],
                        'non_null': c['nonnull'], 'min': c['min'], 'max': c['max'],
                        'first_sample_depth_m': c['first_depth'], 'depth_registered': c['pad'] is not None}
                       for c in log['curves'] if c['nonnull']],
            'columns': log['columns'],
            'annotations': [{'column': a['column'], 'depth_m': a['depth'], 'x': a['x'], 'text': a['text']} for a in log['annotations']],
            'pictures': pics,
            'pictures_note': ('The file has no text header. These are all pictures stored in it: the header page is a '
                              'picture, and the store often also holds headers of other wells reused as templates, '
                              'so check the well name and licence on each.') if pics else None,
            'outputs': {'las': os.path.basename(out_base) + '.las' if table else None, 'csv': os.path.basename(out_base) + '.csv' if table else None,
                        'las_start_m': row.get('las_start'), 'las_stop_m': row.get('las_stop'), 'las_step_m': row.get('las_step')},
            'lithology': lith_doc,
            'accessories': {'note': 'symbols placed at a depth; depth_m is the top of the symbol as printed; size as stored',
                            'symbols': acc},
            'warnings': log['warnings'],
        }
        with open(out_base + '.json', 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
        outputs.append('json')
        row['curves'] = len(meta)
        row['curve_list'] = ';'.join(mn for mn, _ in meta)
        row['warnings'] = ' | '.join(log['warnings'])
        row['outputs'] = '+'.join(outputs)
        row['status'] = 'ok' if table else 'no_curves'
        row['seconds'] = round(time.time() - t0, 2)
    except Exception as ex:  # noqa: BLE001
        import traceback
        tb = traceback.extract_tb(ex.__traceback__)[-1]
        row.update(status='error', reason='%s: %s (%s line %d)' % (type(ex).__name__, ex, os.path.basename(tb.filename), tb.lineno))
    return row


FIELDS = ['file', 'status', 'reason', 'duplicate_of', 'app', 'version', 'container', 'header_source', 'depth_axis', 'depth_axis_basis', 'well_name', 'licence',
          'well_id', 'location', 'operator', 'log_top', 'log_bottom', 'las_start', 'las_stop', 'las_step', 'las_rows', 'curves',
          'curve_list', 'annotations', 'lith_source', 'lith_intervals', 'survey_stations', 'accessories', 'warnings', 'outputs', 'size', 'sha1', 'seconds']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--match', default='')
    ap.add_argument('--list', help='file with relative paths to convert, one per line')
    a = ap.parse_args()
    only = set(open(a.list).read().split('\n')) - {''} if a.list else None
    rels = []
    for dp, dn, fn in os.walk(a.src):
        dn[:] = sorted(d for d in dn if os.path.join(dp, d) != os.path.abspath(a.out))
        for n in sorted(fn):
            if n.lower().endswith(EXTS) and not n.startswith('._'):
                rel = os.path.relpath(os.path.join(dp, n), a.src)
                if a.match in rel and (only is None or rel in only):
                    rels.append(rel)
    if a.limit:
        rels = rels[:a.limit]
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    rows = []
    with Pool(a.jobs) as pool:
        for i, row in enumerate(pool.imap(convert_one, [(a.src, a.out, r) for r in rels], chunksize=4), 1):
            rows.append(row)
            if i % 250 == 0 or i == len(rels):
                print('%d/%d files, %.0fs' % (i, len(rels), time.time() - t0), flush=True)
    first_by_sha = {}
    for r in rows:
        s = r.get('sha1')
        if s:
            if s in first_by_sha:
                r['duplicate_of'] = first_by_sha[s]
            else:
                first_by_sha[s] = r['file']
    with open(os.path.join(a.out, 'index.csv'), 'w', encoding='utf-8', newline='') as f:
        cw = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        cw.writeheader()
        cw.writerows(rows)
    from collections import Counter
    st = Counter(r['status'] for r in rows)
    summary = {'tool': TOOL, 'source_root': a.src, 'files': len(rows), 'status': dict(st),
               'curves': sum(int(r.get('curves') or 0) for r in rows),
               'annotations': sum(int(r.get('annotations') or 0) for r in rows),
               'seconds': round(time.time() - t0, 1)}
    with open(os.path.join(a.out, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
