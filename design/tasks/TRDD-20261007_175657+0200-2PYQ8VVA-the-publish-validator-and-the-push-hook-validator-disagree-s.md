---
trdd-id: 2PYQ8VVA
title: The publish validator and the push-hook validator disagree, so a nit fails only after the bump
column: testing
status: tasked
created: 2026-10-07T17:56:57+0200
updated: 2026-10-18T03:49:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T17:56:57+0200
implementation-commits: [24eb3afa]
---

# The publish validator and the push-hook validator disagree, so a nit fails only after the bump

On 2026-10-07 the 3.8.8 publish's step-4 validator passed card 58Q791FL, but the push hook's validator run refused the push on markdownlint MD028 (blank line between two blockquotes) in that card, after the version bump commit and tags existed locally. Find why the two runs lint different file sets or rules, and make step 4 run exactly what the push hook runs, so a nit fails before the bump. Also: worker briefs that write cards should run markdownlint on the card.

## Approval log

- 2026-10-07T17:56:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings 2026-10-07

Measured (log reports/publish/20261007_162213+0200-publish-patch.log): the two validator command lines are IDENTICAL, uvx --from git+https://github.com/Emasoft/claude-plugins-validation@v5.16.2 --with pyyaml cpv-remote-validate plugin . --strict (scripts/publish.py:1801-1814 step 4, and :1488-1496 push-gate G3), same cwd, pin and strictness; no env differs.
The difference is inside CPV: in step 4 (log line 423) CPV printed 'WARNING markdownlint timed out - skipping markdown lint' (and a pyright timeout, line 424), so the lint never ran and SUMMARY showed NIT=0 (line 826). In the G3 run markdownlint completed and reported NIT MD028 (log lines 4983, 5385). CPV downgrades its own markdownlint timeout to a WARNING, which --strict passes, under heavy load right after the test stage.
No code change here: a shared command builder changes nothing because the commands already match. CPV side must change: under --strict a linter timeout must be a blocking finding, or CPV must raise and expose its markdownlint timeout. Optional follow-up here, not done: fail step 4 when CPV output contains 'timed out - skipping'.

## STATE

2026-10-10 23:10. BUILT, in testing; the code is in the commit that carries this line. WHAT: scripts/publish.py gains run_cpv_strict, which runs the strict validator in its own session with one output pipe, echoes each line, and returns the exit code plus every line matching 'timed out ... skipping'; publish step 4 (stage_validate) and the push gate's validator step (new _gate_validate, called by run_gate) both use it and stop when a line was collected; if the output is still open 10 s after the validator exits, the run is blocked too, since an incomplete read proves nothing. CONFIRMED BEFORE THE BUILD (reports/board/20261010_224836+0200-2pyq8vva-measure.md): in the 2026-10-07 log the first validator run printed the markdownlint and pyright timeout lines and summed NIT=0 WARNING=44, the second summed NIT=1 (MD028); it is the only one of 28 retained publish logs with such a line; step 4 exits on any non-zero code, so that pass was exit 0; the push gate also lets 5 and above through, and the block covers both. TESTS: tests/test_publish_cpv_skipped_check.py, 11 tests with real child processes and a real stand-in uvx on PATH; deleting either blocked branch fails test_skipped_check_with_exit_0_blocks_both_sites. GATE on the working tree: ruff, mypy, pyright exit 0; 18375 passed, 2 skipped (reports/board/gate-2pyq8vva.txt). LIMITS: the match is on the validator's wording at pin v5.16.2 and a reword upstream silently disables it; the validator's other skips (a linter not installed, printed as info) are not matched; whether the validator colours its lines under a pipe was not checked; the fail-closed branch was seen passing, never failing (no red run captured for round 2); test_unfinished_reader_fails_closed leaves a child sleeping 30 s; the stand-in uvx breaks if the Python path holds a space; on a timeout the push gate still ends in a raw traceback, as before; run_gate itself has no test (its line after the validator step was read: return 1). NOT DONE HERE, the owner's: the validator should treat its own linter timeout as blocking under strict mode; that is a second paragraph for the issue on Emasoft/claude-plugins-validation that already waits for the owner's word. The card's note that worker briefs should lint the cards they write stays a process note. FIELD CASE UNOBSERVED for the fix: DETECT, in a publish log after the next release: the text 'the validator skipped a check'. Stays in testing until a release carries it.
2026-10-10 23:12. NOTES from the reviews of the build and of 24eb3afa, recorded: the gate ran on the working tree whose code is exactly the code of 24eb3afa (only three card files were written between the gate's end at 23:10:15 and the commit); the earlier timeout test's last-resort os.kill(pid, 9) on a grandchild would be refused by the test sandbox, and it is reached only when that test is already failing; the worker's '34 passed' for two test files was not reconciled against the 11 tests of the new file (the other file's count was not read).
