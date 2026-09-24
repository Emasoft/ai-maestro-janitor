---
trdd-id: BLGZTHQ9
title: The injected Jev copy shows tool items as one-to-four-line stubs
column: todo
created: 2026-09-24T11:21:06+0200
updated: 2026-09-24T11:29:45+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:06+0200
---

# The injected Jev copy shows tool items as one-to-four-line stubs

Found by a fresh real-transcript run on HEAD f06621c6 (reports/compaction-replacement/20260924_112500+0200-jev-real-run-verification.md, E1). After the per-item byte cap, a kept tool item in the injected copy is a command echo plus one output line, card frontmatter, a two-line heading fragment or seven lines of a diff hunk: it counts as a non-owner item inline while carrying no information. Seen on all three transcripts (b2bf5b7b, d30bf250, 4eb7bf5d). Proposed direction (pending the advisor): a tool item that does not fit its injected cap is shown as a pointer only, never as a truncated stub. Acceptance: on the three transcripts no injected tool item is a truncated prefix (mechanical check), and every non-owner item shown states a fact, command result or decision that the recent-turns tail does not (read by hand); a test fails without the fix. Release blocker for TRDD-RAEGS1D5.

## Approval log

- 2026-09-24T11:21:06+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review corrections 2026-09-24

Advisor root cause: E1 and E3 share one root. The non-owner floor force-admits 350-byte tool stubs over budget (jev_compaction.py ~2086), and the byte backstop then evicts the owner's directives to pay for them (~2186-2204). Fix, injected mode only: a tool item over its cap goes to the pointer pool (assistant and event prose may still be a verbatim prefix); drop the protected-segment boost from the injected non-owner order; replace the floor's force-admit with a reservation made before the owner tier. Acceptance is judged by reading the three injected copies, not by an item count. Lands after EFA4P42B, DZ1KOGAC and O2FNJ4KW and a re-measure.
