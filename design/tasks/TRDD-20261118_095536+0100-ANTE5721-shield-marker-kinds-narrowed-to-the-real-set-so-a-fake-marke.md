---
trdd-id: ANTE5721
title: shield marker kinds narrowed to the real set so a fake marker cannot hide a token
column: todo
status: tasked
created: 2026-11-18T09:55:36+0100
updated: 2026-11-18T09:55:36+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T09:55:36+0100
parent-trdd: BAQB9SYO
---

# shield marker kinds narrowed to the real set so a fake marker cannot hide a token

Split out of TRDD-BAQB9SYO on 2026-11-18 (follow-up of acf280b4). CORE_MARKER and SHIELD_MARKER (scripts/shield_scan/redact.ts lines 10 and 13) and MARK_BODY (hooks/secret-shield/patterns.ts line 16) accept any kind matching [A-Za-z0-9_-]+, which admits most token formats, so a token written as the kind of a fake marker is never read by any pass (known limit, SKILL.md Output). Narrow the kind to the real set: list every kind the core, the passes and the shield scan emit, then make a marker-shaped string with any other kind plain text that the passes read. Tests: a fake token in the Type field of a marker-shaped string is found; every real marker stays opaque; restore still finds every real marker.

## Approval log

- 2026-11-18T09:55:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
