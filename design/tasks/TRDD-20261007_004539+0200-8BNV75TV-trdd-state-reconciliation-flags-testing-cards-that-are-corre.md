---
trdd-id: 8BNV75TV
title: trdd-state-reconciliation flags testing cards that are correctly waiting on a live event
column: testing
status: tasked
created: 2026-10-07T00:45:39+0200
updated: 2026-10-07T02:06:31+0200
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
implementation-commits: [b9a2377e, b0247a30, dab24584, 67d29e91, 91fca406, 8b587dd1, d737816c, 8d1f1929, a5930dfc, 6958622d]
---

# trdd-state-reconciliation flags testing cards that are correctly waiting on a live event

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07

- 2026-10-07 (after 3.8.2): sizing on the real board with 3.8.2 code (reports/board/20261007-332-drift-sizing.md, gitignored): check3 14 flags of which 1 real (TRDD-JD2QR5SQ); check4 2 of 2 false; partially-shipped-review 56 rows of which 37 need no action; idle 53 of which 51 are backburner cards (drift-eligible by rule); reminders 37; dead-symbol 3 of which 1 real (TRDD-BMITQ2MN).
- 2026-10-07 NOT MERGED: branch worktree-agent-ad55b68799d2d9c8c (ec35f21c, 0d97a605) narrows check3/check4 with seven more exclusion rules (14 -> 4 and 2 -> 0 on today's board). A pre-merge review rejected it: fourth regex round fitted to the current board; one true positive in the sample, so the miss rate is unmeasured; it would miss real declarations such as a quoted status (STATE: "blocked on the owner"), a heading that is the declaration, 'blocked from release until X', and for check4 'Blocked. See TRDD-X.'; one stray double quote can blank a paragraph; any 8-char uppercase token with a digit is treated as a card id. The branch is kept, unmerged.
- 2026-10-07 STEP BACK: stop adding exclusions to a word match. Two replacement designs, owner picks: (A) positive patterns — check3 fires only when THIS card is the subject ('this card' / 'the card' / its own id / line start) directly followed by a copula and 'blocked', or a line beginning 'BLOCKED'; check4 uses the blocked-by field plus ids that directly follow 'blocked by|on'. (B) demote check3 and check4 prose matching to one-time findings-ledger notes, as was done for closeable, and keep only frontmatter-based checks in the weekly report. Either way compare old vs new on the same board, by card, before landing.
- Code merged on main: closeable becomes a one-time TRDD-CLOSEABLE ledger note, re-recorded only on a new citing SHA; it is no longer in the report or the drift line.
- Shipped for the title's problem: check3 reads only the card's own STATE declarations (b9a2377e, d737816c); fresh live-wait `testing` cards are not called closeable (b0247a30, dab24584); testing-too-long flags `testing` cards past 40 days; when the date the card entered testing is unknown, the age is counted from `created:` instead of `updated:`, since any edit resets `updated:` (8b587dd1); the design-only closeable rule was added and reverted (67d29e91, 91fca406).
- SUPERSEDED: the body's 'skip a testing card whose STATE records a field check within N days' proposal; the shipped design is the live-wait skip plus the 40-day flag above.
- Recount on the real board with main's code: old detector 96 rows including 34 closeable-candidate; new 65 rows plus 34 ledger notes; a second run is silent.
- 3 cards that were closeable plus another class re-emit one drift line once.
- NEXT ACTION (replaces the earlier one for the prose checks): owner picks (A) or (B); the closeable class still waits on the first weekly audit on 3.8.2.
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
