---
trdd-id: BEA87JS1
title: Token-spike advisory renders output ~0k and still recommends compaction
column: testing
status: tasked
created: 2026-10-18T08:58:49+0200
updated: 2026-11-16T02:04:05+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T08:58:49+0200
parent-trdd: 9WPZE2NQ
implementation-commits: [9f7abe3e, 417297cd]
---

# Token-spike advisory renders output ~0k and still recommends compaction

janitor#342 item 5c, CONFIRMED 2026-10-18 by TRDD-9WPZE2NQ (reports/board/20261018_085812+0200-9wpze2nq-342-items-3-5.md). scripts/hooks/pre-tool-token-budget.py _bucket_tokens (line 230) floors every count to 10k for cache-stable text (TRDD-YRPUSIFY), so any count under 10k renders '~0k'. The advisory threshold is baseline-relative (scripts/lib/token_meter.py about 803-816: max(p95, median+3*1.4826*MAD, 4*median)), so on a low-output session it fires below 10k and prints 'Token spike: this turn output ~0k ... or compact' (message built near line 440). Reproduced by the worker with history [800,1000,900,1100,1000,950,1050,1200] and output 6000. Overlaps #246, whose fix made the bar baseline-relative but left the bucket floor. Fix direction: finer buckets below 10k that stay byte-identical within a band, and/or no compact recommendation below a fixed floor. Acceptance: a test with that history asserts the advisory text has no '~0k' and no compact advice, fails before and passes after; the bucket-stability tests still pass; full gate green.

## Approval log

- 2026-10-18T08:58:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T09:27:49+0200 — column → testing by main-agent@ai-maestro-janitor. fix committed 9f7abe3e with discriminating tests and a green full gate; waits for a release

## Implementation 2026-10-18

Built as an absolute floor in the hook, not finer buckets (design revision 2, after a MEASURE pass and two review rounds): an advisory verdict becomes ok when the turn's output is under min(10_000, 0.75 x the output hard limit), before _track_tier (commit 9f7abe3e). Evidence: tests test_advisory_floor_suppresses_a_sub_10k_turn_over_the_baseline_bar, test_advisory_floor_boundary_9999_silent and test_suppressed_sub_floor_advisory_is_tracked_as_ok_so_a_real_one_still_fires fail on the pre-fix hook and pass now; guards for 12k, 10000, the 40k hard tier and a lowered hard limit; full gate 18,632 passed, ruff, mypy and pyright clean. BEHAVIOUR CHANGE: a session whose turns are normally tiny no longer gets a relative-spike advisory below 10k (for example 1k to 8k); #246 asked for genuinely extreme cases only. NOT FIXED HERE: scripts/hooks/pre-tool-context-usage.py has its own _bucket_tokens copy that still renders '~0k' in its own text. Stays in testing until a release carries it.

## Follow-up 2026-11-16

417297cd fixes the sibling renderer in scripts/hooks/pre-tool-context-usage.py: its own _bucket_tokens now renders a distance under 10k in 1k buckets (~9k down to ~1k; ~0k only under 1k) instead of ~0k for every value under 10k. Checks: that hook's test file 64 passed; ruff, mypy and pyright clean on the hook.
Correction: the 417297cd commit message says 9f7abe3e fixed the budget hook's own renderer. It did not change the renderer: 9f7abe3e added an absolute floor (_ADVISORY_MIN_OUTPUT = 10_000, pre-tool-token-budget.py:84 and :512) that turns an advisory verdict under that output into ok, so the advisory ~0k text is no longer shown. _bucket_tokens there (line 237) still floors to 10k; a hard-tier or cache-miss line can still print a floored bucket (not checked).
Stays in testing: 9f7abe3e is in the released v3.9.3 (checked 2026-11-16 with git merge-base --is-ancestor); 417297cd is in no release tag yet and ships with the next publish; live check = no "~0k" in a context-usage or budget advisory line after that release.
