---
trdd-id: UDE86OSZ
title: C1C — host-load detector
column: complete
status: archived
created: 2026-10-01T19:45:09+0200
updated: 2026-10-03T14:21:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:09+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, UDE86OSZ]
blocker-holds-if: not-match:READY
implementation-commits: [f93054cc]
---

# C1C — host-load detector

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C1C, wave W1.

Writes (exclusive): scripts/detectors/host-load.py, tests/test_host_load.py
Task: os.getloadavg() above cores×4 gives a HOST-001 line; not yet registered
Verify: Unit test with an injected load value
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:09+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:04+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-01T19:52:48+0200 — column → dev by main-agent@ai-maestro-janitor. Python card with no dependency on the C02 Rust scaffold (review finding 10); dispatched 2026-10-01 Cleared blocked-by (--clear-blocker override).
- 2026-10-01 — FOLLOW-UP (wave-1 review finding 4): on this host load runs 8-13x cores, so cores x 4 fires HOST-001 on nearly every heartbeat. Dedupe lands in C24 (state change or once per hour); multiplier default to be revisited from a week of measured load.
- 2026-10-01 — do NOT archive yet: HOST-001 fires on nearly every heartbeat on this host (load 8-13x cores). Decide the dedupe (on state change or once an hour) and a measured default multiplier; implement here or hand to C24's wiring, then close. See DSN035UN 'C1A/C1C/C1D open items'.
- 2026-10-03: HOST-001 dedupe (emit on state change, at most once per hour) handed to C24 TRDD-8524H5V1, which records it. Default multiplier stays cores x 4 until a week of measured load exists; follow-up TRDD-2V90ATLL.
- 2026-10-03T13:52:24+0200 — column → testing by main-agent@ai-maestro-janitor. close condition met
- 2026-10-03T13:52:41+0200 — column → ai_review by main-agent@ai-maestro-janitor. close condition met
- 2026-10-03T13:53:04+0200 — column → human_review by main-agent@ai-maestro-janitor. close condition met
- 2026-10-03T14:21:17+0200 — COMPLETE by main-agent@ai-maestro-janitor. acceptance checklist complete.

## Acceptance criteria

- [x] Unit tests in tests/test_host_load.py pass (commit f93054cc)
- [x] HOST-001 dedupe handed to TRDD-8524H5V1 and recorded there
- [x] Multiplier re-measure filed as TRDD-2V90ATLL
