---
trdd-id: PPQG9JVP
title: Guard 2 refuses a manual soft compact up to the context wall whenever its upper edge reaches the model's context limit
column: backburner
created: 2026-09-18T06:36:02+0200
updated: 2026-09-18T06:52:30+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-18T06:36:02+0200
---

# Guard 2 refuses a manual soft compact up to the context wall whenever its upper edge reaches the model's context limit

Guard 2's upper edge is min_context_tokens() = max(effective_compact_point + 50k backstop margin, 350k floor), and effective_compact_point = window - 34k summary overhead, so at defaults the upper edge is max(window + 16k, 350k). Once context passes the band's lower edge (0.95 x effective), compact_trigger.py refuses every soft /compact below that upper edge; only --hard escapes. When the upper edge is at or above the model's context limit, that refusal runs all the way to the wall. Affected: the auto-compact window set equal to the model's limit (1M window on a 1M model: band about 918k to 1.016M), and any model whose limit is under 350k, e.g. a 200k model at any window (the floor). Not affected: a 1M model with a 300k or 700k window (upper edge 350k or 716k, below the wall). Probably not affected (inferred, not checked): the floor-gated automatic callers, which only send at or above the floor; since 763b28e3 the floor and guard 2's upper edge can be computed from different environments off-session (see KM0XVVV8). Also stale: compact_trigger.py's --hard exemption comment gave a 200k window's band as roughly [158k, 166k + margin); fixed to [158k, 350k) alongside this card. Options: (a) keep the upper edge below the model limit, which guard 2 does not currently know; (b) drop the 350k floor from guard 2's upper edge and make the backstop margin smaller than the summary overhead; (c) leave it and document --hard as the way past it. Question for the user: which.

## Approval log

- 2026-09-18T06:36:02+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
