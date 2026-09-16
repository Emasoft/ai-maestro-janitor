---
trdd-id: CJU6YV6L
title: Archive the 232 terminal cards still sitting in design/tasks so the zones match their columns
column: dev
created: 2026-09-16T10:03:24+0200
updated: 2026-09-16T10:03:24+0200
current-owner: session
created-by: session
task-type: infra
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T10:03:24+0200
---

# Archive the 232 terminal cards still sitting in design/tasks so the zones match their columns

trddgrep validate (2026-09-16) reports 369 ERROR findings on 289 cards; 232 are ZONE-MISMATCH: cards with column complete (153) or published (79) that were never moved into design/archived/ when they closed. The column is the judgement already made, so the relocation is mechanical: one rename per file into design/archived/ keeping its basename, one commit, no body edits (terminal cards are frozen). Acceptance: (1) trddgrep validate shows 0 ZONE-MISMATCH; (2) the commit contains only renames (232 R lines, 0 content changes); (3) the validate ERROR count drops by exactly 232. Out of scope, follow-up phases needing per-card judgement: 69 TERMINAL-WITHOUT-CHECKLIST, 17 TERMINAL-WITH-OPEN-BOX, 10 DERIVED-FLAG-MISSING, 8 BLOCKED-WITHOUT-PROBE, 7 GRAPH-UNKNOWN-BLOCKER, 6 GRAPH-CHILD-MISSING, 5 ORDER-NPT-VIOLATED, 2 UNPARSEABLE (duplicated mapping key). Note: trddgrep fix is disabled outside the ai-maestro checkout.

## Approval log

- 2026-09-16T10:03:24+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
