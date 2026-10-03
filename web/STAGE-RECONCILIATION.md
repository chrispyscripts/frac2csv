# Gundy stage-depth reconciliation

Summary records and completion intervals remain separate source entities. A link is corroborated only by a unique printed port depth within 0.1 m. Equal stage numbers or counts do not establish a link.

## Totals

- no_printed_depth: 2231
- matched_printed_depth: 919
- ambiguous_depth: 5
- summary_depth_only: 1

## Wells with differing counts

| WA | Summaries | Intervals | Depth matches | Summary depth only | No printed depth |
|---|---:|---:|---:|---:|---:|
| 28748 | 39 | 44 | 0 | 0 | 39 |
| 28751 | 34 | 37 | 0 | 0 | 34 |
| 28752 | 42 | 43 | 0 | 0 | 42 |
| 38175 | 57 | 58 | 56 | 0 | 0 |
| 38176 | 60 | 59 | 59 | 1 | 0 |
| 38181 | 51 | 55 | 51 | 0 | 0 |
| 38185 | 57 | 58 | 56 | 0 | 0 |
| 38186 | 57 | 58 | 56 | 0 | 0 |
| 38197 | 57 | 58 | 56 | 0 | 0 |
| 38173 | 55 | 56 | 54 | 0 | 0 |
| 33667 | 33 | 32 | 0 | 0 | 33 |

## Unlinked intervals in wells with printed summary depths

These are missing depth-matched summaries, not proof that no treatment occurred.

- WA 38175: intervals without a matching summary: 1 (4904.2 m), 2 (4904.2 m). Summary ports absent from the depth table: none.
- WA 38176: intervals without a matching summary: none. Summary ports absent from the depth table: 60 (2345.8 m).
- WA 38181: intervals without a matching summary: 52 (2669.7 m), 53 (2623.9 m), 54 (2578.1 m), 55 (2532.7 m). Summary ports absent from the depth table: none.
- WA 38185: intervals without a matching summary: 1 (4783.2 m), 2 (4783.2 m). Summary ports absent from the depth table: none.
- WA 38186: intervals without a matching summary: 1 (4974.2 m), 2 (4974.2 m). Summary ports absent from the depth table: none.
- WA 38197: intervals without a matching summary: 1 (5006.1 m), 2 (5006.1 m). Summary ports absent from the depth table: none.
- WA 38173: intervals without a matching summary: 1 (4607.3 m), 2 (4607.3 m). Summary ports absent from the depth table: none.

## Remaining evidence needed

WA 28748, 28751, 28752 and 33667 have differing counts and no printed summary depths. Their numerical labels alone cannot identify which intervals correspond. Supply the report stage/port table or a reviewed chart-to-interval crosswalk with source references. No summary values are shifted or invented.

Existing chart records may carry older depth assignments based on stage number. The single-well view labels those assignments as provisional; this audit does not certify them.

Reproduce: `python3 web/scripts/reconcile_stages.py`. Source files and curve samples are preserved.
