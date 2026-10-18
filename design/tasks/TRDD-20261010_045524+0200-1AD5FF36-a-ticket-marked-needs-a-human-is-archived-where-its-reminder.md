---
trdd-id: 1AD5FF36
title: A ticket marked needs a human is archived where its reminder never looks
column: testing
status: tasked
created: 2026-10-10T04:55:24+0200
updated: 2026-10-18T03:49:41+0200
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
implementation-commits: [6697d459, 5beaba31]
---

# A ticket marked needs a human is archived where its reminder never looks

Found 2026-10-10 while reading for TRDD-6ESS2MGE (measured: reports/board/20261010_044030+0200-6ess2mge-measure.md, item A5). scripts/lib/tickets.py:104 lists needs_human as TERMINAL; save() at tickets.py:417-418 writes a terminal ticket to tickets/closed/ and removes the open copy; load_all at tickets.py:350-354 globs only the open directory. scripts/detectors/ticket-dispatch.py:147-149 builds the NEEDS A HUMAN reminder from load_all, so by reading the code it can never print for a ticket saved after the status change. NOT observed in the field: this project has 7 closed tickets and none open; whether any is needs_human is unread. To do: a failing test that saves a needs_human ticket and expects the reminder line; then either keep needs_human tickets in the open directory or have the reminder read closed/ for that status; decide by which one the retry command (ticket_cli retry) already expects.

## Approval log

- 2026-10-10T04:55:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 04:58 WHO READ WHAT (review of fed2df0e): tickets.py:104 and the save() lines 417-418 are worker-read (measure report item A5); load_all (tickets.py:346-358) and ticket-dispatch.py:147-149 were read by the main session; the 7 closed and 0 open tickets are a worker's count; the path from mark_needs_human to save() was not traced.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-16

Implemented (uncommitted, pending orchestrator commit): ARCHIVED set + migrate_needs_human in tickets.py, migrate + age/summary reminder in ticket-dispatch.py; 8 new tests (4 test_tickets, 4 test_ticket_dispatch) shown failing first, 63 pass across the three ticket suites; ruff/mypy/pyright clean. Note: open_ticket dedupe at tickets.py:524 still creates a second ticket for a key held by an open needs_human; both are now visible.
2026-10-16 review of 5beaba31: wikimem-syntax.py _close_stale_tickets only touches OPEN tickets, so it cannot close a needs_human one (checked). Field evidence exists only after a release; this card waits on the release like TRDD-0TSG80CL. On release, 12 hidden needs_human tickets in other projects resurface.

## Acceptance

- [x] needs_human tickets stay in the open dir; dispatch still skips them (tests)
- [x] archived needs_human tickets are migrated back under the dispatch lock (tests)
- [x] reminder names up to 3, else one summary line (tests)
- [ ] field: a real needs_human ticket's reminder fires in a project after a release
