---
trdd-id: LH84WTL5
title: The keep-going board nudge can wake two sessions of one project onto the same card
column: testing
status: tasked
created: 2026-10-06T19:19:19+0200
updated: 2026-10-07T09:35:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T19:19:19+0200
implementation-commits: [c386b279, b175178f]
---

# The keep-going board nudge can wake two sessions of one project onto the same card

_board_workable_ids (dispatch.py) counts every open dev/todo card regardless of owner, and the nudge text says finishing a card means pulling the next. Two sessions sharing one project (same board, same owner identity, so an owner filter cannot separate them) can both be nudged; since 79255d6e an idle session is woken while the owner works in another pane of the same project, and each card move by the active session changes the board signature and re-arms the idle one. Risk: duplicate work and conflicting writes in one tree. Pre-existing at night (both idle); now reachable in daytime. Fix idea to evaluate, not decided: a per-project nudge lease so only one session at a time receives the zero-agent board nudge, or suppress it while another session of the same project shows recent presence. Also to decide with the owner: whether the nudge should only name cards whose current-owner matches the session agent in ai-maestro projects (RULE 1).

## Approval log

- 2026-10-06T19:19:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T08:45:08+0200 — column → testing by main-agent@ai-maestro-janitor. B7 merged and gated at b175178f

## STATE

NEXT ACTION: measure how often two janitor-armed sessions share one project root on this host (fleet scan), then propose the smallest guard.
2026-10-06: caveat on the fix ideas: "suppress while another session of the same project shows recent presence" would re-create at project scope the mute that 79255d6e removed; prefer a per-project nudge lease. Shipped state: v3.7.5 carries 79255d6e without a guard; owner informed, no reply at release time.
2026-10-07: one session per project root gets the board nudge, via a lease that expires 2700 s after its holder last renewed; the user-active check returns before the lease is taken, so an active session never holds it; known delay: a holder that dies can leave the board un-nudged for up to 45 minutes. Open owner question: should the nudge name only cards owned by the session agent?
2026-10-07: shipped in v3.8.5; release observation starts.
