---
trdd-id: 8BNV75TV
title: trdd-state-reconciliation flags testing cards that are correctly waiting on a live event
column: testing
status: tasked
created: 2026-10-07T00:45:39+0200
updated: 2026-10-07T02:03:58+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T00:45:39+0200
implementation-commits: [b9a2377e, b0247a30, dab24584, 67d29e91, 91fca406, 8b587dd1, d737816c, 8d1f1929, 9bc0cf20, a5930dfc, 6958622d]
---

# trdd-state-reconciliation flags testing cards that are correctly waiting on a live event

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07

- Code merged on main: closeable becomes a one-time TRDD-CLOSEABLE ledger note, re-recorded only on a new citing SHA; it is no longer in the report or the drift line.
- Shipped for the title's problem: check3 reads only the card's own STATE declarations (b9a2377e, d737816c); fresh live-wait `testing` cards are not called closeable (b0247a30, dab24584); testing-too-long flags `testing` cards past 40 days, counted from `created` when `updated` is missing (8b587dd1); the design-only closeable rule was added and reverted (67d29e91, 91fca406).
- SUPERSEDED: the body's 'skip a testing card whose STATE records a field check within N days' proposal; the shipped design is the live-wait skip plus the 40-day flag above.
- Recount on the real board with main's code: old detector 96 rows including 34 closeable-candidate; new 65 rows plus 34 ledger notes; a second run is silent.
- 3 cards that were closeable plus another class re-emit one drift line once.
- NEXT ACTION: after 3.8.2 is released and installed, confirm one live weekly audit run shows no closeable list, then complete this card.
- Owner of GitHub #332 is TRDD-6ESS2MGE.
- TRDD-9UVLOHED, the one card the triage found really closeable, was closed with its acceptance checklist in 2587a694.
- Nobody yet reads TRDD-CLOSEABLE notes; that routing belongs to TRDD-6ESS2MGE.

The detector's closeable-candidate class means only that a commit citing the card is in a released tag. On 2026-10-07 a triage of 32 such candidates found 1 closeable, 16 waiting on a live event that cannot be forced, 7 open and 8 owner decisions (the 2026-10-07 triage report). GitHub #332 therefore re-surfaces the same cards every week.

Proposed fix, tests first: skip a testing card whose STATE names a pending live event and records a field check within the last N days; keep flagging cards with no recent field check.

## Approval log

- 2026-10-07T00:45:39+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Implementation commits

8d1f1929 (closeable becomes a one-time ledger note), 9bc0cf20 (merge of that branch), a5930dfc (tests: mixed-class and no-closeable-in-report guards).

## Known gaps (accepted)

emit_once marks the SHA seen BEFORE findings_ledger.record writes: a failed ledger write loses that card's closeable note until a new citing SHA appears. Accepted, rare.
The findings ledger keeps the last 500 lines, so the first live run's ~34 closeable notes evict the oldest ledger entries.
