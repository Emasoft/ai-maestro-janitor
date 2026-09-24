---
trdd-id: U6C3YXEL
title: Items excluded from the injected Jev copy get a pointer and are counted in the elided line
column: todo
created: 2026-09-24T08:29:57+0200
updated: 2026-09-24T08:29:57+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:29:57+0200
---

# Items excluded from the injected Jev copy get a pointer and are counted in the elided line

Follow-up to TRDD-AW4XD53Q (complete). Measured 2026-09-24 on three cached real transcripts: items that survive the token stage but are excluded by the injected copy's byte admission (or evicted by the backstop) get neither a body nor a pointer, and are missing from the '[[elided: N more items]]' count. That is 39/24/18 items, including 21/22/7 decision-passing owner messages. Fix: every excluded decision-passing item gets at least a pointer line, and the elided count includes byte-stage exclusions, reserving the line's width up front so counting cannot change the fit. Tests must fail without the fix.

## Approval log

- 2026-09-24T08:29:57+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
