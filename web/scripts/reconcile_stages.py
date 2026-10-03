"""Audit Gundy treatment summaries against independent completion depths.

Only a unique printed depth within 0.1 m corroborates a link. Ordinal stage
numbers, equal counts and dates alone are not evidence of the same interval.
Source well files are never rewritten. Run from any directory with Python 3.
"""
import json
from collections import Counter
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / 'public'


def reconcile(doc):
    summaries = doc.get('engineering_stages', [])
    depths = doc.get('depth_intervals', [])
    rows = []
    linked = set()
    for e in summaries:
        top = e.get('top_m')
        candidates = [] if top is None else [
            d for d in depths if abs(d['top_m'] - top) <= .100001
        ]
        # Do not choose between overlapping/duplicate source records.
        if top is None:
            status = 'no_printed_depth'
        elif len(candidates) == 1:
            status = 'matched_printed_depth'
        elif len(candidates) > 1:
            status = 'ambiguous_depth'
        else:
            status = 'summary_depth_only'
        match = candidates[0] if status == 'matched_printed_depth' else None
        if match:
            linked.add(match['n'])
        rows.append(dict(summary_n=e['n'], label=e['label'], status=status,
                         printed_top_m=top, printed_base_m=e.get('base_m'),
                         depth_order=match['n'] if match else None,
                         workover_key=match.get('workover_key') if match else None,
                         source=e.get('source')))
    counts = dict(Counter(r['status'] for r in rows))
    unlinked = [dict(depth_order=d['n'], top_m=d['top_m'], base_m=d['base_m'],
                     workover_key=d.get('workover_key'))
                for d in depths if d['n'] not in linked]
    return dict(wa=str(doc['well']['wa']), summaries=len(summaries),
                depth_intervals=len(depths), chart_records=len(doc.get('stages', [])),
                count_mismatch=len(summaries) != len(depths), counts=counts,
                rows=rows, intervals_without_verified_summary=unlinked)


def main():
    cluster = json.loads((PUBLIC / 'data/underground.json').read_text())
    wells = {}
    for pad in cluster['pads']:
        for w in pad['wells']:
            wa = str(w['well']['wa'])
            doc = json.loads((PUBLIC / f'data/wells/{wa}.json').read_text())
            wells[wa] = reconcile(doc)
    totals = Counter()
    for w in wells.values():
        totals.update(w['counts'])
    report = dict(method='Unique printed summary port depth within 0.1 m of completion top; no ordinal joins.',
                  totals=dict(totals), wells=wells)
    (PUBLIC / 'data/stage-reconciliation.json').write_text(json.dumps(report, separators=(',', ':')) + '\n')
    lines = ['# Gundy stage-depth reconciliation', '',
             'Summary records and completion intervals remain separate source entities. '
             'A link is corroborated only by a unique printed port depth within 0.1 m. '
             'Equal stage numbers or counts do not establish a link.', '',
             '## Totals', '']
    lines += [f'- {key}: {value}' for key, value in totals.items()]
    lines += ['', '## Wells with differing counts', '',
              '| WA | Summaries | Intervals | Depth matches | Summary depth only | No printed depth |',
              '|---|---:|---:|---:|---:|---:|']
    for w in wells.values():
        if w['count_mismatch']:
            c = w['counts']
            lines.append(f"| {w['wa']} | {w['summaries']} | {w['depth_intervals']} | {c.get('matched_printed_depth',0)} | {c.get('summary_depth_only',0)} | {c.get('no_printed_depth',0)} |")
    lines += ['', '## Unlinked intervals in wells with printed summary depths', '',
              'These are missing depth-matched summaries, not proof that no treatment occurred.', '']
    for w in wells.values():
        if w['count_mismatch'] and not w['counts'].get('no_printed_depth'):
            items = ', '.join(f"{r['depth_order']} ({r['top_m']} m)" for r in w['intervals_without_verified_summary']) or 'none'
            extras = ', '.join(f"{r['label']} ({r['printed_top_m']} m)" for r in w['rows'] if r['status'] == 'summary_depth_only') or 'none'
            lines.append(f"- WA {w['wa']}: intervals without a matching summary: {items}. Summary ports absent from the depth table: {extras}.")
    lines += ['', '## Remaining evidence needed', '',
              'WA 28748, 28751, 28752 and 33667 have differing counts and no printed summary depths. '
              'Their numerical labels alone cannot identify which intervals correspond. Supply the report stage/port table '
              'or a reviewed chart-to-interval crosswalk with source references. No summary values are shifted or invented.', '',
              'Existing chart records may carry older depth assignments based on stage number. '
              'The single-well view labels those assignments as provisional; this audit does not certify them.', '',
              'Reproduce: `python3 web/scripts/reconcile_stages.py`. Source files and curve samples are preserved.', '']
    (PUBLIC.parent / 'STAGE-RECONCILIATION.md').write_text('\n'.join(lines))
    print(json.dumps(dict(wells=len(wells), totals=dict(totals))))


if __name__ == '__main__':
    main()
