---
trdd-id: QX59MA4H
title: C33 — hook-timeout-scan detector
column: blocked
status: tasked
created: 2026-10-01T19:45:20+0200
updated: 2026-10-01T19:49:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:20+0200
blocked-by: [B9YPSF02]
pre-block-column: todo
blocker-probe: [trddgrep, why, QX59MA4H]
blocker-holds-if: not-match:READY
---

# C33 — hook-timeout-scan detector

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C33, wave W3.

Writes (exclusive): scripts/detectors/hook-timeout-scan.py, tests
Task: HOOK-001 from the transcript record shape found in U4
Verify: A fixture JSONL line gives one finding
Depends on: C1B
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:39+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on B9YPSF02 per DSN035UN wave order
- 2026-10-01 — detection shape from C00/U4: scan session transcripts (~/.claude/projects/<slug>/*.jsonl) for lines with type=attachment and attachment.type=hook_cancelled and attachment.timedOut=true; fields hookName, hookEvent, command, durationMs, timeoutMs. The text "timed out after" does NOT identify hook timeouts. Emit HOOK-001 once per (session, hookName) with durationMs/timeoutMs.
