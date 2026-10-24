---
trdd-id: HCPGY099
title: iTerm alarm ledger rows reach a new session without the HUMAN-ONLY prefix
column: todo
status: tasked
created: 2026-10-24T11:42:25+0200
updated: 2026-10-24T11:42:25+0200
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
---

# iTerm alarm ledger rows reach a new session without the HUMAN-ONLY prefix

Found by the TRDD-F3LVCQ39 census. The two findings_ledger.record calls of the iTerm automation alarm (dispatch.py:3107-3110 resolved, :3395-3398 unreachable) pass no actor, so the rows default to agent; render_line adds the HUMAN-ONLY prefix only when actor is human (findings_ledger.py:244-245). The stdout alarm line carries the prefix, the SessionStart row does not (read in code; observed live at SessionStart 2026-10-24). ACCEPTANCE: pass actor=findings_ledger.HUMAN_ONLY_ACTOR on the unreachable row, decide whether the resolved row should surface at all, and test both.

## Approval log

- 2026-10-24T11:42:25+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
