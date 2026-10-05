---
trdd-id: EMCS2S0B
title: The rotator computes its verdicts from a mirror copy of the login that it cannot verify
column: todo
status: tasked
created: 2026-10-05T22:11:14+0200
updated: 2026-10-05T22:11:14+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:14+0200
---

# The rotator computes its verdicts from a mirror copy of the login that it cannot verify

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Every tick of the headless daemon logs that the primary credential is unreadable and that the identity is untrusted, then judges usage and expiry from the mirror copy. All three false verdicts of 2026-10-05 were computed this way. TRDD-A2JLFIQ5 owns only the log wording and TRDD-QQ7QCS3T only the default; this card owns the root question of what the daemon may conclude from an unverified copy.

## Approval log

- 2026-10-05T22:11:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
