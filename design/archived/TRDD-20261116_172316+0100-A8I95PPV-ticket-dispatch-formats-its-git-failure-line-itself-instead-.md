---
trdd-id: A8I95PPV
title: ticket-dispatch formats its git failure line itself instead of git_root_error_reason
column: complete
status: archived
created: 2026-11-16T17:23:16+0100
updated: 2026-11-16T19:25:59+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T17:23:16+0100
implementation-commits: [3d89064c]
---

# ticket-dispatch formats its git failure line itself instead of git_root_error_reason

scripts/detectors/ticket-dispatch.py lines 180-187 build their own GitRootError line; reuse trdd_common.git_root_error_reason so paths are scrubbed the same way (TRDD-7KPG2PCO).

## Approval log

- 2026-11-16T17:23:16+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T19:12:35+0100 main-agent: evidence. Fix in commit 3d89064c; test_ticket_dispatch.py 15 passed; ruff clean on the fixed file and its test.
- 2026-11-16T19:12:46+0100 main-agent: move complete refused (exit 2): no acceptance checklist. Column stays todo; card NOT archived; checklist decision pending.
- 2026-11-16T19:25:59+0100 main-agent: the new test in test_ticket_dispatch.py was red on the pre-fix code (checked with git stash before commit 3d89064c); acceptance checklist added and ticked; closing.
- 2026-11-16T19:25:59+0100 — COMPLETE by main-agent@ai-maestro-janitor. archived as complete (from column todo).

## Acceptance checklist

- [x] ticket-dispatch prints its git failure through git_root_error_reason (one scrubbed line, no machine path), with a test that was red on the pre-fix code
