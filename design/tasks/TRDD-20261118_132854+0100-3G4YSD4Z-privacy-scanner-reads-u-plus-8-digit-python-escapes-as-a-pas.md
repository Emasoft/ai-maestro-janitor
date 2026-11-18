---
trdd-id: 3G4YSD4Z
title: Privacy scanner reads U plus 8 digit Python escapes as a passport number
column: backburner
status: tasked
created: 2026-11-18T13:28:54+0100
updated: 2026-11-18T13:41:12+0100
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
approval-datetime: 2026-11-18T13:28:54+0100
---

# Privacy scanner reads U plus 8 digit Python escapes as a passport number

- Privacy scanner false positive: scripts/lib/staged_privacy_scan.py rule pii-us_passport matched the all-digit Python escapes U+2060 and U+2066 to U+2069 (written as 8-digit Python escapes). Worked around with the 4-digit \uXXXX form (same runtime value, AST equal). Root cause stays in the scanner: own card.

Found while working TRDD-SWQXCIOS.

## Approval log

- 2026-11-18T13:28:54+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Links

Parent context: TRDD-SWQXCIOS (bandit sweep).
