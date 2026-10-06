---
trdd-id: ZYX8B2RA
title: C40 — fix dominant recall wait
column: todo
status: tasked
created: 2026-10-01T19:45:21+0200
updated: 2026-10-06T15:08:29+0200
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
unblock-when: [decision:owner-allows-plain-edit-of-memory-rs]
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

## Corrections

2026-10-06 (review of commit 53ecf23c): "under the 1 s target of this card" is too strong. The card's target is on an idle host; the figure is from a loaded host and the idle-host condition is not measured.
2026-10-06 (same review): "the hits come from all three scopes" was judged by page name only; which directory holds each hit was not checked by the session.
2026-10-06 (same review): the first-root-only fault is shown by a rerun for recall only, by a worker, not by the session. For find it is a code reading by a worker (near line 9878, not read by the session) plus a worker's report that its new test fails; no swapped-order run on find exists. The recall code near line 9145 was read by the session.
2026-10-06 (same review): "No shipped caller is known to use that shape" rests on the hook and the documented manual form only; other callers were not searched. Card RQMJFJGR would meet the fault only if it passes directories and keeps --use-index; the session read only its title and writes line.
2026-10-06 (same review): the 15 symlinks in the user-scope directory were counted by a worker; where they point was not checked. "A merge would return those notes twice" is a deduction from the code (index rows skip the realpath dedup, the final ranking has no dedup); no merged run exists.
2026-10-06 (same review): the user-mem point came from the adversarial review as a risk, not from the measurement, and is unmeasured: nobody checked whether any index holds files of the user-mem subtree. Read "bypasses" as "may bypass". The last findings line says card RQMJFJGR "must then solve" the duplicate and user-mem points "in line 4": that reference means the DECISION line, and both points are open questions for that card to measure, not established requirements.
2026-10-06 (same review): "scores are comparable", the HOOK-003 definition and its file line, "three additive snippets on a scratch copy" and "the file was left unchanged" for the second worker all come from workers' reports; the session checked only that git shows the source file unmodified.
2026-10-06 (same review): the DECISION line omits that the smaller fix was named by the adversarial review and adopted by the session without a second review round.
2026-10-06 (same review): how this card and card RQMJFJGR split. The archived benchmark card V12ZHM1B assigned the speed fix to RQMJFJGR. This card now carries only the wrong-answer fix for --use-index with several paths; speed of the directory form stays with RQMJFJGR. The Writes line of this card was never set: the fix writes scripts/memgrep/src/memory.rs and scripts/memgrep/tests/cli.rs.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

NEXT ACTION: wait for the owner's answer to the question asked on 2026-10-06: may a worker make the one source change with the plain edit tool. Do NOT retry fastedit on cmd_recall_cli or on the find function: six snippets were refused across two workers.
IF YES: add, after the use_index block in cmd_recall_cli and in the find function of scripts/memgrep/src/memory.rs, one line that sets use_index to use_index and a.paths.len() <= 1, with a comment naming this card. Then run the whole crate test suite, clippy with warnings as errors, and the two-order check on the real corpus with the binary built from the repo, not the older memgrep on PATH. Then one adversarial review of prompt and result, then commit source and tests together.
IF NO: move the two uncommitted tests out of scripts/memgrep/tests/cli.rs into tests_dev so the crate suite is green, and leave this card blocked.
WORKING TREE: scripts/memgrep/tests/cli.rs holds two uncommitted tests that fail until the fix lands, so the crate suite is red in the working tree. A publish must not start in that state.
OPEN, unmeasured: recall time on an idle host; the hook's end-to-end time against its 4 s limit.
2026-10-06 OWNER DECISION: plain edit NOT allowed (owner, verbatim: 'the answer is no. if the trddgrep tool is not flexible enough to make the changes you need, open an issue on Emasoft/ai-maestro'). Applied the IF-NO branch: the two failing tests (recall_use_index_with_two_roots_searches_both, find_use_index_with_two_roots_searches_both) were removed from scripts/memgrep/tests/cli.rs by git stash (stash message names this card) and saved as tests_dev/20261006-ZYX8B2RA-two-root-use-index-tests.patch; the crate suite no longer carries them. NEXT ACTION: the source fix waits on fastedit accepting the edit (fastedit is the Emasoft/fastedit repo, not ai-maestro; trddgrep was not the refusing tool).
