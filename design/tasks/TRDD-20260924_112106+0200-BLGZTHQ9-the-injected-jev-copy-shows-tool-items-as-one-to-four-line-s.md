---
trdd-id: BLGZTHQ9
title: The injected Jev copy shows tool items as one-to-four-line stubs
column: todo
created: 2026-09-24T11:21:06+0200
updated: 2026-09-24T13:29:00+0200
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
implementation-commits: [0c607b36]
---

# The injected Jev copy shows tool items as one-to-four-line stubs

Found by a fresh real-transcript run on HEAD f06621c6 (reports/compaction-replacement/20260924_112500+0200-jev-real-run-verification.md, E1). After the per-item byte cap, a kept tool item in the injected copy is a command echo plus one output line, card frontmatter, a two-line heading fragment or seven lines of a diff hunk: it counts as a non-owner item inline while carrying no information. Seen on all three transcripts (b2bf5b7b, d30bf250, 4eb7bf5d). Proposed direction (pending the advisor): a tool item that does not fit its injected cap is shown as a pointer only, never as a truncated stub. Acceptance: on the three transcripts no injected tool item is a truncated prefix (mechanical check), and every non-owner item shown states a fact, command result or decision that the recent-turns tail does not (read by hand); a test fails without the fix. Release blocker for TRDD-RAEGS1D5.

## Approval log

- 2026-09-24T11:21:06+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review corrections 2026-09-24

Advisor root cause: E1 and E3 share one root. The non-owner floor force-admits 350-byte tool stubs over budget (jev_compaction.py ~2086), and the byte backstop then evicts the owner's directives to pay for them (~2186-2204). Fix, injected mode only: a tool item over its cap goes to the pointer pool (assistant and event prose may still be a verbatim prefix); drop the protected-segment boost from the injected non-owner order; replace the floor's force-admit with a reservation made before the owner tier. Acceptance is judged by reading the three injected copies, not by an item count. Lands after EFA4P42B, DZ1KOGAC and O2FNJ4KW and a re-measure.
SPEC AMENDMENT S2 (docs_dev/20260924_1300-injected-selection-spec.md said "NO render() edit"), accepted: 0c607b36 made ONE render() edit. S4 needs a newest-owner cap that render() reads, so NEWEST_OWNER_ITEM_BYTES became the closure variable guaranteed_item_cap, read at call time so the backstop's re-renders use the cap the selection costed. It equals the constant unless the injected branch sets it, and that branch is guarded by max_item_bytes is not None, so --out cannot change: cmp byte-identical on 4/4 real transcripts. The advisor's decision-pointer render edit was NOT made. Still untested: the byte backstop firing in injected mode with this closure cap (the exactness argument says an ordinary run never reaches it). Only 6 of the 8 new tests test behaviour; 2 fail on the parent only because _select_injected is new (review of 0c607b36).
Not closable on 0c607b36: read by hand, 2 of b2bf5b7b's 3 non-owner items are a message intro and task-notification metadata, and fd5cc3e0's 3 of 3 are metadata shells; non-owner items inline went 4/4/8/4 -> 3/4/4/3. The whole-tool 20-character bar also passes a bare call echo, since the body starts with the synthetic name(input) line. F1 (event content gate, uncommitted at 2026-09-24 13:20) addresses both.
