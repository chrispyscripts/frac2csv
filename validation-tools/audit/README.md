# Audit harness

The scripts that turned Carmine's week of Flag Error reports into a
scorecard, kept so they are not rebuilt next time. `audit.py` at the repo
root is the scanner; these run it over a set of files and read the result.

    sweep.sh  <out-dir> <pdf>...        extract + audit each PDF, two at a time,
                                        <out>/<name>-payload.json / -findings.json / -report.txt
    scorecard.py <out-dir> flags.json   each flag: FOUND / REPAIRED / MISSED / STILL
    ab_coverage.py before.json after.json "WH Prop Conc"
                                        per-stage filled% and peak, one tree against another
    dump_tree.py <pdf> <out.json>       extraction through the tree named in $F2C_REPO —
                                        `git worktree add /tmp/before <sha>^` then
                                        F2C_REPO=/tmp/before — so a before/after runs the
                                        REAL old code, not a reimplementation of it

flags.json is a list of {issue, file, said, stages, channel, kinds, expect}:
`kinds` are the finding kinds that would answer the report, `expect` is
false for a report the current tree is believed to have repaired — the
scorecard then says REPAIRED when the audit is quiet and STILL when it is
not. Copy PDFs off the drives first; both have dropped mid-run.
