---
trdd-id: NGLPQ7SW
title: Headless account switch skips filing the outgoing credential into its slot and logs nothing
column: todo
status: tasked
created: 2026-10-06T21:08:38+0200
updated: 2026-10-06T21:08:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:08:38+0200
---

# Headless account switch skips filing the outgoing credential into its slot and logs nothing

Found by the 2026-10-06 field check of TRDD-IT5GEZDZ (reports/board/20261006_210400+0200-testing-field-check.md). Two real switches today (17:22:16 and 20:18:14) ran in the daemon with the primary live credential skipped by policy (JANITOR_ROTATOR_HEADLESS) and the -livebak mirror in use. Per the code (rotator.py around lines 2074-2096, read by the field-check worker, not re-read by the main agent), read_live_blob then returns None and the filing step returns early without any log line, so the outgoing credential is never filed and nothing says so. Fail-silent regardless of the policy choice. Fix options for the owner: file from the mirror, or log the skip explicitly; at minimum the skip must be logged. Acceptance: a headless switch either files the slot or logs a line naming the skip.

## Approval log

- 2026-10-06T21:08:38+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
