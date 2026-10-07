---
trdd-id: QX59MA4H
title: C33 — hook-timeout-scan detector
column: blocked
status: tasked
created: 2026-10-01T19:45:20+0200
updated: 2026-10-07T04:57:38+0200
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
- 2026-10-01 — SCOPE EXTENDED (absorbs superseded C1B, TRDD-B9YPSF02): besides HOOK-001 from hook_cancelled/timedOut=true, also emit HOOK-002 hook-near-timeout from hook_success/hook_cancelled entries whose durationMs >= 80% of the hook timeout (timeoutMs when the record has it, else the timeout configured for that exact command in hooks/hooks.json; skip hooks with no known timeout). Dedupe one HOOK-002 per (hook command, hour). Reference implementation of the threshold and dedupe: reports/dsn035un/c1b-superseded/hook_timing.py (local).
- 2026-10-01 — MAPPING (wave-1 review finding 3): hook_success.command holds the literal ${CLAUDE_PLUGIN_ROOT} text; match on the script path relative to the plugin root against the janitor own hooks/hooks.json entries. HOOK-002 covers janitor hooks only (other plugins have no timeout in success records and their hooks.json is not ours to parse); HOOK-001 covers every plugin via hook_cancelled.timeoutMs.

## STATE

2026-10-07: requirement added from TRDD-U32EVMI9: every cancelled guard hook must become a recorded finding, and where possible the guard's own check is replayed afterwards over the recorded input so that a harmless cancellation is told apart from a real miss.
