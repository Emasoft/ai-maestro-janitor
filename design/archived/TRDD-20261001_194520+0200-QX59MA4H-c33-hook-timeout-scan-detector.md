---
trdd-id: QX59MA4H
title: C33 — hook-timeout-scan detector
column: complete
status: archived
created: 2026-10-01T19:45:20+0200
updated: 2026-10-09T23:22:36+0200
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
blocked-by: []
pre-block-column: 
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
- 2026-10-07T10:07:58+0200 — column → todo by main-agent@ai-maestro-janitor. blocker B9YPSF02 was superseded and archived 2026-10-01 and its scope absorbed into this card Cleared blocked-by (--clear-blocker override).
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-10-08T20:33:13+0200 — column → todo. blocker B9YPSF02 absorbed by this card per its own SCOPE EXTENSION line; tree quiet; 2026-10-07 owner delegation covers code edits
- 2026-10-08T20:33:36+0200 — column → dev. batch fan-out from main session; owner 2026-10-07 delegation covers code edits
- 2026-10-08T20:37:19+0200 — column → testing. worker verified all deliverables on disk (detector, registry, codes, 18 tests; pytest 18+23 passed, ruff clean) — reports_dev/20261008-fanout-qx59ma4h.md; acceptance fixture evidence recorded in report
2026-10-09 CLOSED by the main session (board drain, wave 3). Fix commits ab1548c9, fa5b8a24, 95806856, 4e9a4694 are ancestors of the v3.8.11 tag; tests/test_hook_timeout_scan.py passes (18). Field, the card's own case: the findings ledger holds 19 HOOK-001 records, the newest 'hook UserPromptSubmit was killed for exceeding its timeout (6027ms of 5000ms)' from this session on 2026-10-09. HOOK-002 was not looked for. NOT assessed here: the later requirement from TRDD-U32EVMI9 (every cancelled guard hook recorded and its check replayed); that stays with U32EVMI9. Assessment: reports/board/20261009_232136+0200-wave3-batchE.md.
- 2026-10-09T23:22:36+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11; tests re-run; see Approval log 2026-10-09.

## STATE

2026-10-07: requirement added from TRDD-U32EVMI9: every cancelled guard hook must become a recorded finding, and where possible the guard's own check is replayed afterwards over the recorded input so that a harmless cancellation is told apart from a real miss.
2026-10-07: the dangling-blocker finding on B9YPSF02 is pre-existing: blocked-by: [B9YPSF02] is identical in this card at 714f72c9^ and now, and B9YPSF02 was superseded and archived on 2026-10-01 (a5d99c10), before today's work; the blocker was not changed.

## Acceptance

- [x] See the Approval log entry of 2026-10-09 for the evidence per promise.
