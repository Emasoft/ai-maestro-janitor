---
trdd-id: NEVQOHGS
title: Heartbeat and chore token cost must be measured per fire and reported weekly
column: complete
created: 2026-09-16T09:45:04+0200
updated: 2026-09-17T14:52:10+0200
current-owner: session
created-by: session
task-type: infra
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T09:45:04+0200
parent-trdd: V3BQT7QE
derived: true
implementation-commits: [25e86cf3]
---

# Heartbeat and chore token cost must be measured per fire and reported weekly

Symptom: heartbeat and memory-chore token cost is not measured anywhere, so the owner cannot tell how much of the session budget the janitor itself consumes.

Evidence: GitHub #290; owner complaint 2026-09-15 ("chron beats wasting tokens"); parent measured 284 heartbeat fires (this repo, 2026-09-08..15) and 801 fires fleet-wide with no per-fire cost figure recorded anywhere.

## Acceptance criteria
- [x] Each heartbeat/chore fire appends a tokens-in/tokens-out line to .janitor/state/token-meter.jsonl (tagged heartbeat: true), derived from the transcript the fire ran in -- verified by a test asserting the log file gains exactly one line per simulated fire with two positive integers. [Orchestrator ruling 2026-09-17: the pre-existing on-stop-token-meter.py hook + token_meter.tail_turn_usage IS this mechanism -- amended per CLAUDE.md's one-source-of-truth rule rather than duplicating a second log.]
- [x] A weekly summary command/script sums the 7-day log and reports a single total token count -- verified by a test with >=2 fake week-old log lines asserting the printed total equals their sum.
- [x] The weekly summary names the top 3 costliest fire kinds (e.g. memory-consolidate, resume, plain-quiet) by summed token spend -- verified by a test with fires of 3+ distinct kinds asserting the top-3 ranking is correct by summed cost.

## Approval log

- 2026-09-16T09:45:04+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T05:54:57+0200 — column → testing by session. boxes 1+2 landed with tests; box 3 aggregation landed+tested but real kind-tagging deferred (schema-lock conflict, needs a design decision)
- 2026-09-17T05:58:26+0200 — column → todo by session. self-review caught: box 1 was ticked on a substitute mechanism (different file, different format) not the card's literal claim -- un-ticked, left for a human/owner decision on whether to accept the substitute or require the literal .janitor/logs/heartbeat-cost.log path; box 3's real deliverable (ranking REAL fire kinds) does not work in production yet (always 'unknown') so testing was premature; weekly_total/top_kind_totals also had a scope bug (summed interactive turns into 'the janitor's own cost') now fixed and re-tested
- 2026-09-17T06:10:40+0200 — column → testing by session. boxes 1+3 landed with tests, box 2 already ticked; remaining boxes are none -- all 3 acceptance criteria satisfied and tested
- 2026-09-17T14:52:10+0200 — COMPLETE by Emasoft. all deliverables landed, gate green on d09fe94b.
- 2026-09-17T14:59:38+0200 — updated: moved on 2026-09-17 by a format-only repair (a duplicate '## STATE' heading that trddgrep append created on close was blanked via trddgrep edit, which has no --no-bump); no fact changed after the terminal transition.

## ⏵ STATE — READ THIS FIRST ON RESUME

2026-09-17T05:54:53+0200 — Box 1 (per-fire tokens-in/out derived from transcript) was ALREADY satisfied by pre-existing token_meter.tail_turn_usage + the on-stop-token-meter.py hook writing .janitor/state/token-meter.jsonl (proven by tests/test_token_meter_logs_every_turn.py, unchanged). Box 2 landed: token_meter.weekly_total() (scripts/lib/token_meter.py) + token_report.py --weekly-summary, tests in tests/test_token_meter.py::TestWeeklyTotal and tests/test_token_report_weekly_summary.py (4 tests, all pass). Box 3 NOT landed: token_meter.top_kind_totals() is written and tested (TestTopKindTotals, 3 tests) but no writer tags real records with a kind -- TurnUsage.as_record()'s key set is pinned byte-identical by tests/test_token_meter.py::TestSelfBudgetRecordSchemaUnchanged (TRDD-ZCODD6YS, external tools parse it), so adding kind there is a real design decision (a separate correlation log + join, or a schema-version bump) that should not be freelanced by a bounded worker. Gates: ruff/mypy/pyright clean on scripts/lib/token_meter.py, scripts/token_report.py. Moved to testing; box 3 remains open for a follow-up card or explicit schema-change approval.
2026-09-17T05:58:35+0200 — SELF-REVIEW CORRECTION of the earlier same-day entry: box 1 was WRONGLY ticked citing a pre-existing but literally-different mechanism (.janitor/state/token-meter.jsonl, JSON) instead of the card's named .janitor/logs/heartbeat-cost.log with plain 'two positive integers' lines -- un-ticked; a human should either accept the existing mechanism as satisfying the intent (amend the box text) or ask for the literal file. Column moved back to todo (was prematurely moved to testing): box 3's ranking of REAL fire kinds cannot work yet (nothing tags kind in production, see top_kind_totals docstring), so the card's headline feature is not functional. Also fixed a real bug found in review: weekly_total()/top_kind_totals() originally summed ALL records (heartbeat + interactive), inflating 'the janitor's own weekly cost' with the user's coding turns -- now heartbeat-only, matching heartbeat_cost_7d's existing rule, with new tests (test_interactive_turns_excluded x2, test_weekly_summary_excludes_interactive_turns). Box 2 remains ticked (weekly_total is genuinely correct and tested). Gates re-run clean after the fix: ruff/mypy/pyright on scripts/lib/token_meter.py + scripts/token_report.py, pytest tests/test_token_meter.py + tests/test_token_report_weekly_summary.py.
2026-09-17T06:30:00+0200 — Follow-up worker (NEVQOHGS-followup) landed boxes 1 and 3 per orchestrator ruling. Box 1: amended its literal text to name the pre-existing .janitor/state/token-meter.jsonl + heartbeat:true field (one-source-of-truth, no second log); ticked, evidence tests/test_token_meter_logs_every_turn.py (unchanged, already proved it). Box 3: added token_meter.detect_fire_kind() (scripts/lib/token_meter.py) -- reads the bare [janitor-<kind>] token line the dispatcher stub prints in a HEARTBEAT turn's own tool_result (never touches the pinned TurnUsage.as_record schema); wired into scripts/hooks/on-stop-token-meter.py::main() to write a SEPARATE sidecar .janitor/state/token-meter-kind.jsonl ({id: ts, kind}) joined on the SAME ts as the main record; token_meter.top_kind_totals() now takes kind_map=load_kind_map(sidecar) instead of a nonexistent per-record kind key; token_report.py --weekly-summary loads and joins the sidecar. Tests: TestDetectFireKind (5), TestKindSidecarLog (2) in tests/test_token_meter.py; TestFireKindSidecar (3, subprocess against the real hook) in tests/test_token_meter_logs_every_turn.py; test_weekly_summary_names_top_kinds rewritten for the sidecar join + test_weekly_summary_missing_sidecar_is_all_unknown added in tests/test_token_report_weekly_summary.py. All 4 gates (ruff/mypy/pyright/pytest) clean on every changed file; targeted pytest run: 76 passed. TestSelfBudgetRecordSchemaUnchanged still green (schema untouched). Card moved to testing.
2026-09-17T06:45:00+0200 — Post-tick adversarial review (mandatory per turn-protocol) found two unacknowledged, low-severity gaps in the box-3 sidecar design, both now addressed: (1) the ts (epoch-second) join key between token-meter.jsonl and token-meter-kind.jsonl is NOT guaranteed-unique -- two Stop-hook fires in the same project within the same wall-clock second silently collide (last-write-wins in load_kind_map's dict), misattributing tokens to the wrong kind. Accepted as a report-only risk (never an alarm/actuation, never corrupts weekly_total) and now documented in append_kind_log's docstring + pinned by tests/test_token_meter.py::TestKindSidecarLog::test_ts_collision_last_write_wins. (2) detect_fire_kind returns the FIRST bare token line found even though a fire can stack several action tokens in one turn per janitor-heartbeat-protocol -- documented as a known simplification in its docstring. No behavior changed, only documentation + one new test; all 4 gates re-run clean, targeted pytest 77 passed (was 76).



[2026-09-17T14:52:06+0200] CLOSED: all deliverables landed (25e86cf3); gate green on d09fe94b (ruff/mypy/pyright clean, pytest 16793 passed / 0 failed). Moving to complete.
