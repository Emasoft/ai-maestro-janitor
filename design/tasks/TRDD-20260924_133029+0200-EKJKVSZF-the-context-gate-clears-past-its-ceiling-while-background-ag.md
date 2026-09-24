---
trdd-id: EKJKVSZF
title: The context gate clears past its ceiling while background agents are live, and their results land in a fresh session with no context
column: backburner
created: 2026-09-24T13:30:29+0200
updated: 2026-09-24T13:39:05+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: spike
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T13:30:29+0200
parent-trdd: null
---

# The context gate clears past its ceiling while background agents are live, and their results land in a fresh session with no context

Question, not yet a decision. Evidence: .janitor/logs/token-meter.log lines 157-176, 2026-09-24, session accccb8b. From 12:56:15 to 13:08:55 the Stop-hook gate deferred the clear because 1-6 background agents were live ("clear deferred: N agent(s) live, 85-90% < ceiling 92%"). From 13:09:34 it logged "clear: past ceiling (92% >= 92%) -- clearing regardless" and "chain spawned" six times (13:09:34, 13:11:27, 13:11:38, 13:12:13, 13:16:21, 13:17:05, reaching 94% / 851,646 tokens) before the clear landed at 13:17:11. The session had background workers in flight (F1 finished at 13:16:55; F4's end was never seen), and a clear at that point means their completion notices, if they still arrive, land in a fresh session that holds none of the context that dispatched them. Questions: (1) is clearing regardless the right policy past the ceiling, or should the gate wait for the live agents up to a hard limit such as the harness auto-compact threshold; (2) should the chain record the live agents' ids and report paths in the resume state so the fresh session can adopt them; (3) why the chain spawned six times before one clear landed (each spawn while the session was mid-turn?) and whether repeated spawns are harmless. Related: TRDD-4P4Y2KBR (the same clear injected a foreign handoff).

## Approval log

- 2026-09-24T13:30:29+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Related

TRDD-911PCSFZ (backburner): the idle-clear gate clears a session with live subagents using a stale handoff. A different trigger (idle-clear, not the Stop-hook ceiling) with the same outcome; decide the two together.
TRDD-L32WC0H7 (testing): the trigger and loop-guard card (card 1 of the Jev program). This spike is NOT one of its derived tasks (it is not an effect of L32WC0H7's change, and adding it to L32WC0H7's eht would block that card's completion on a backburner question), so there is no parent-trdd link; the relation is recorded here only. parent-trdd was cleared on 2026-09-24 because it named L32WC0H7 while L32WC0H7's npt/eht do not list this card (a one-directional derivation edge).
