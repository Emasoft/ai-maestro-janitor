---
trdd-id: 8524H5V1
title: C24 — ledger suppression and host-load registration
column: todo
status: tasked
created: 2026-10-01T19:45:15+0200
updated: 2026-10-03T14:43:59+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:15+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, 8524H5V1]
blocker-holds-if: not-match:READY
---

# C24 — ledger suppression and host-load registration

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C24, wave W2.

Writes (exclusive): scripts/lib/findings_ledger.py, scripts/dispatch.py
Task: Route ledger records and drift lines through is_suppressed; register host-load.py; map system-daemon-runaway to HOST-002
Verify: One heartbeat with ignore=["HOST"] in .janitor.toml prints no HOST line; without it the line prints with its code
Depends on: C1A, C1C
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:12+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on U2VUXGBP, UDE86OSZ per DSN035UN wave order
- 2026-10-01 — REQUIREMENT (wave-1 review finding 2, HIGH): the ledger and drift paths MUST NOT crash on a malformed .janitor.toml. Catch the error from suppression.is_suppressed, record ONE finding CONFIG-001 bad-janitor-toml (add the code to design/specs/issue-codes.toml via the generator flow, coordinate with C10) and fall back to "nothing suppressed". Fail-fast stays right for the CLI, wrong for a background observer. Also dedupe HOST-001 (finding 4): emit on state change or at most once per hour, not every heartbeat.
- 2026-10-01 — OWNS (wave-1 review finding 2): catch C1A's is_suppressed config error in the ledger/drift path, emit CONFIG-001 bad-janitor-toml, treat nothing as suppressed; never let one config typo stop the heartbeat. May also take C1C's HOST-001 dedupe if C1C hands it over.
- 2026-10-03T14:43:59+0200 — column → todo. blockers U2VUXGBP (C1A) and UDE86OSZ (C1C) are complete and archived Cleared blocked-by (--clear-blocker override).
