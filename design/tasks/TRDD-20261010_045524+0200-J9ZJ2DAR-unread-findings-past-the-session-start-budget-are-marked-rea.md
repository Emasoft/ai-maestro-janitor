---
trdd-id: J9ZJ2DAR
title: Unread findings past the session-start budget are marked read without being shown
column: testing
status: tasked
created: 2026-10-10T04:55:24+0200
updated: 2026-10-16T17:23:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T04:55:24+0200
parent-trdd: 6ESS2MGE
derived: true
implementation-commits: [2f57054a, af6b1ac5]
---

# Unread findings past the session-start budget are marked read without being shown

scripts/lib/findings_ledger.py surface_block pushes unread ledger lines until 10 lines or 1024 bytes (the loop breaks at the first line that does not fit), adds one fold line, then advance_cursor acks the WHOLE ledger. Everything folded is never pushed again; /janitor-findings still lists it. Since ab532c56 the order is severity first, so what folds is the LOW tail, and every advisory line is written as LOW (scripts/dispatch.py:839), including the lines of the detectors whose finding the coding agent must act on (dirty-tree, trdd-drift, gitignore-coverage and others; worker-read table reports/board/20261010_044453+0200-6ess2mge-detector-table.md). Measured 2026-10-10: at most 23 of this project's 30 session transcripts contain a fold line (an upper bound, later transcripts quote earlier ones), with counts from 1 to 90. Not measured: how many real session starts folded, and how many lines fit (about 5 by one sample). Rejected already, with reasons on TRDD-6ESS2MGE: hiding all advisory lines; grouping by code. Options to measure before choosing: ack only what was shown plus what is excluded; skip a line that does not fit and continue; a second push later in the session. Start by logging, per session start, unread count, shown count and folded count by severity, so the choice rests on real starts.

## Approval log

- 2026-10-10T04:55:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Implementation notes

2026-10-16: implemented on branch fix/J9ZJ2DAR-findings-fold (2f57054a + af6b1ac5, not yet merged to main or published). surface_block now acks only shown events and NEVER_SURFACE_CODES; folded events are kept as content hashes in the cursor's pending list and drain on later session starts; a line that does not fit the byte budget is skipped instead of stopping the loop. Every session-start surface logs unread/shown/folded counts per severity to findings-surface.log, which is the measurement this card asked for. Adversarial review done; findings applied or rejected with reasons in af6b1ac5. Tests 46 passed; ruff, mypy, pyright clean. Remaining: merge into main and ship through scripts/publish.py.
