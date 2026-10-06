---
trdd-id: ZYX8B2RA
title: C40 — fix dominant recall wait
column: todo
status: tasked
created: 2026-10-01T19:45:21+0200
updated: 2026-10-06T05:07:09+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:21+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, ZYX8B2RA]
blocker-holds-if: not-match:READY
---

# C40 — fix dominant recall wait

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C40, wave W4.

Writes (exclusive): set in the card from C1D's report (depends on the cause)
Task: Fix the dominant wait C1D names. Candidate fixes: open the index once, avoid per-file stats when --use-index is given, or pass scope dirs instead of 369 file paths.
Verify: Rerun C1D's benchmark on an idle host; recall over 3 scopes takes under 1 s, and an autorecall prompt produces no HOOK-003
Depends on: C1D
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:43+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on V12ZHM1B per DSN035UN wave order
- 2026-10-04T13:11:02+0200 — column → todo by main-agent@ai-maestro-janitor. blocker V12ZHM1B is complete and archived Cleared blocked-by (--clear-blocker override).

## Findings 2026-10-06

Measured on a loaded host (load average about 17), by a worker, report reports_dev/20261006_042323+0200-MEASURE-AND-VERIFY-REPORT-c40-recall-wait.md, read in full by the session: the prompt hook's own call (314 file paths, --top 3 --use-index) takes 0.44 to 0.62 s over 5 runs, under the 1 s target of this card. Three directories without the flag take 2.2 to 3.0 s. An idle-host figure was not taken.
Checked by the session with three queries: the hook-shaped call returns the same hits with and without --use-index, and the hits come from all three scopes. Why it walks (first path is a file, so no index is found) is a reading of the code, not shown by the equal outputs.
FAULT found, confirmed by a second worker on a rerun: with --use-index and two directories, recall searches only the first directory's index; the results change when the two directories are swapped. Code: scripts/memgrep/src/memory.rs, cmd_recall_cli, the use_index block near line 9145. The find command has the same fault near line 9878. No shipped caller is known to use that shape today; card RQMJFJGR (autorecall passes scope dirs) would.
DECISION by the session, after one adversarial review: the per-root merge of index rows and walk rows is DROPPED. Reasons from the measurement, not rechecked by the session: index rows are not passed through the realpath dedup that the walk uses, and the user-scope directory holds 15 symlinks to project notes, so a merge would return those notes twice; a directory served from its index also returns whatever the index holds, which bypasses the hook's exclusion of the user-mem subtree. Scores of the two gatherers are comparable (same scoring function), so that was not the obstacle.
CHOSEN FIX, not applied: --use-index is honoured only when exactly one path is given; with several paths recall and find take the walk. Additive form: after the use_index block in each function, one line that sets use_index to use_index and a.paths.len() <= 1, with a comment naming this card.
STATE of the tree: two tests were added to scripts/memgrep/tests/cli.rs and are NOT committed: recall_use_index_with_two_roots_searches_both and find_use_index_with_two_roots_searches_both. A worker reports both fail on today's code (tests/cli.rs lines 1687 and 1719); the session did not run them.
BLOCKED on a write tool, not on the design: fastedit refused the source edit six times across two workers (three snippets that changed a line on the real file, three additive snippets on a scratch copy of the function), each time leaving the file unchanged. Reports: reports_dev/20261006_043713+0200-c40-use-index-multi-root-fix.md and reports_dev/20261006_050500+0200-c40-use-index-fix-additive.md (the second not read by the session). The owner was asked on 2026-10-06 whether a worker may make this one change with the plain edit tool; no answer yet.
NOT covered by the chosen fix: the three-directory form stays at walk speed; making it fast belongs to card RQMJFJGR, which must then solve the duplicate and user-mem points in line 4. HOOK-003 is the hook's own 4 s limit on its recall call (scripts/lib/issue_codes_gen.py line 37); the hook's end-to-end time was not measured.
