---
trdd-id: 7WJPSM8W
title: Every quiet-dropped advisory line writes a new findings-ledger row on each run
column: todo
status: tasked
created: 2026-10-24T11:42:25+0200
updated: 2026-10-24T11:48:03+0200
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

# Every quiet-dropped advisory line writes a new findings-ledger row on each run

Found by the TRDD-F3LVCQ39 census. _quiet_filter runs first, as the argument of _dedupe_drift_text (dispatch.py:1590, and the timeout path at :1569), and records every dropped advisory line as a LOW ADVISORY-<DETECTOR> ledger row (:1012-1016) each time the detector runs. findings_ledger.record does not dedupe the row, per its docstring (findings_ledger.py:278-281): the ledger entry is always appended and only the repeat print is suppressed (the append code itself was not read). So a stable advisory condition adds one ledger row per detector run. The contract for repeating conditions is TRDD-5CGPEK4V's; this card fixes only the ledger growth. ACCEPTANCE: a repeated, unchanged advisory line adds no new ledger row (or the owner of 5CGPEK4V rules otherwise), with a test.

## Approval log

- 2026-10-24T11:42:25+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
