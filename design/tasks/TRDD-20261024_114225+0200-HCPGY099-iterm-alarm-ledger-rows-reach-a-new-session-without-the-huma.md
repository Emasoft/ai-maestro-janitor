---
trdd-id: HCPGY099
title: iTerm alarm ledger rows reach a new session without the HUMAN-ONLY prefix
column: testing
status: tasked
created: 2026-10-24T11:42:25+0200
updated: 2026-10-24T17:16:19+0200
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
approval-datetime: 2026-10-24T11:42:25+0200
implementation-commits: [aef5ce0e]
---

# iTerm alarm ledger rows reach a new session without the HUMAN-ONLY prefix

Found by the TRDD-F3LVCQ39 census. The two findings_ledger.record calls of the iTerm automation alarm (dispatch.py:3107-3110 resolved, :3395-3398 unreachable) pass no actor, so the rows default to agent; render_line adds the HUMAN-ONLY prefix only when actor is human (findings_ledger.py:244-245). The stdout alarm line carries the prefix, the SessionStart row does not (read in code; observed live at SessionStart 2026-10-24). ACCEPTANCE: pass actor=findings_ledger.HUMAN_ONLY_ACTOR on the unreachable row, decide whether the resolved row should surface at all, and test both.

## Approval log

- 2026-10-24T11:42:25+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-24T17:16:19+0200 — column → testing by main-agent@ai-maestro-janitor. fixed and tested; reaches SessionStart only after a release

## Fix

2026-10-24, commit aef5ce0e: the unreachable row passes actor=HUMAN_ONLY_ACTOR (test_iterm_alarm_unreachable_row_is_human_only failed before, passes after). Decision on the resolved row: it keeps surfacing and stays actor agent, because it asks nothing of the owner and a human actor would re-stamp the surfaced-to-human flag its branch gates on and record a resolution every fire; test_iterm_alarm_records_one_resolution_when_the_condition_clears now asserts actor agent. Verified by reading findings_ledger.record and mark_surfaced_to_human: the extra stamp on the alert path is a second idempotent key under the same code, cleared with the others. The two replay-budget control tests were recalibrated from render_line sizes. tests/test_dispatch_phases.py 254 passed; ruff, mypy, pyright clean. Known effect: at SessionStart a human-only alert can sit next to its unlabelled resolution.

## Acceptance checklist

- [x] The unreachable row carries actor human and renders with the HUMAN-ONLY directive (commit aef5ce0e)
- [x] The resolved row decision is made and tested: it surfaces as actor agent (commit aef5ce0e)
