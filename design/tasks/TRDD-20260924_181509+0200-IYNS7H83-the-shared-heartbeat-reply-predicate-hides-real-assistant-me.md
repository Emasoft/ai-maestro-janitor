---
trdd-id: IYNS7H83
title: The shared heartbeat-reply predicate hides real assistant messages from the recent-turns tail
column: backburner
status: tasked
created: 2026-09-24T18:15:09+0200
updated: 2026-09-24T18:15:18+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-24T18:15:09+0200
---

# The shared heartbeat-reply predicate hides real assistant messages from the recent-turns tail

`transcript_roles.is_heartbeat_reply` matches a bare 'janitor heartbeat' reply plus up to two more lines. On session b2bf5b7b it matched 9 assistant messages that carried real content ('janitor heartbeat\nThe live account is ...'), i.e. drift lines the heartbeat protocol says to surface verbatim, not noise.

TRDD-D7RLXAN1's extract_items now drops only the exact bare 'janitor heartbeat' reply (scripts/lib/jev_compaction.py:660-661) when building the conversation/exchanges block -- a deliberate narrowing found during that card's acceptance run (a). But `external_clear.recent_messages` and the precompact hook still use the WIDE `is_heartbeat_reply` predicate (scripts/lib/transcript_roles.py:288-293 area), so two different definitions of 'heartbeat reply' now exist in this codebase: a narrow one (bare-only) in Jev's own path, and a wide one (bare + up to 2 more lines) everywhere else.

Fix at the root: one predicate, not two. First decide the actual question the wide predicate is dodging -- is a heartbeat reply that carries drift lines noise (correctly excluded, same as today) or content (should survive into recent-turns/exchanges, same as D7RLXAN1 now does for Jev)? Whichever answer wins, make is_heartbeat_reply (or its narrow counterpart) the single source of truth every caller uses, so external_clear.recent_messages and the precompact hook agree with Jev's conversation block instead of silently disagreeing about what a heartbeat reply is.

## Approval log

- 2026-09-24T18:15:09+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Related

TRDD-D7RLXAN1 -- the acceptance run that found the 9-message false-drop (jev_compaction.py extract_items narrowing to the bare-reply-only exclusion) is what surfaced this predicate split.
