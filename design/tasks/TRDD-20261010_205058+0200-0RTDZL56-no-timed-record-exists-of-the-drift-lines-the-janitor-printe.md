---
trdd-id: 0RTDZL56
title: No timed record exists of the drift lines the janitor printed
column: testing
status: tasked
created: 2026-10-10T20:50:58+0200
updated: 2026-10-18T03:00:34+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T20:50:58+0200
implementation-commits: [ed848ae5]
---

# No timed record exists of the drift lines the janitor printed

Found while working TRDD-IJR1OBZO on 2026-10-10: the repeats of the CPU runaway line could not be measured, because nothing records WHEN a human-facing drift line was printed. drift-lines-seen.txt holds dedupe keys with a date at most and no time; the findings ledger deliberately excludes human-facing drift; the detector's own log holds no emission. So a claim such as 'this line repeated every 20 minutes' can only be inferred from code. Wanted: one appended line per PRINTED drift line (time, detector, the dedupe key or a short hash, never the full text if it can hold private data), bounded in size like the other logs. To decide first: whether dispatch.log is the place (it already logs suppressions), and what the per-fire cost is. Verify: a test that a printed drift line leaves one timed record and a suppressed one leaves none.

## Approval log

- 2026-10-10T20:50:58+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T03:00:34+0200 — column → testing by main-agent@ai-maestro-janitor. built in ed848ae5, gate green; field check after a release

## Implementation

2026-10-18 BUILT in ed848ae5: dispatch.log gets 'drift printed: detector=<name> key=<12 hex>' for each printed detector drift line (key = sha256 of detector plus dedupe key, no day, so repeats group across days; text never written; dispatcher-own lines not covered). dispatch.log is the place (it already logs suppressions; state.log_line rotates it at 1 MiB). Per-fire cost: one log append per printed line, none for suppressed ones. Verify met in tests (printed leaves one record, suppressed none). Gate green: 18615 passed. Field check after a release: a repeated human-facing line shows as several records with the same key.
