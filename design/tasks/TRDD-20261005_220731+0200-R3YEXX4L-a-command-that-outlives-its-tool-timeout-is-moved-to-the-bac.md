---
trdd-id: R3YEXX4L
title: A command that outlives its tool timeout is moved to the background and keeps running unwatched
column: todo
status: tasked
created: 2026-10-05T22:07:31+0200
updated: 2026-10-05T22:07:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:07:31+0200
---

# A command that outlives its tool timeout is moved to the background and keeps running unwatched

Goal: investigate, verify and fix the root cause. Observed 2026-10-05 in another project's session: a shell line ('fastedit undo' followed by a batch-edit) did not complete within its 180 s tool limit and the harness moved it to the background instead of ending it. The host degraded in the following minutes and was power-cycled about fifteen minutes later; that this command was the cause is NOT established (no memory report exists for that window).

To do: establish from the Claude Code documentation and a controlled test what happens to a foreground command at its timeout (ended, or left running in the background, and with what limit); check whether an inner 'timeout N' prefix on the command is honoured; decide what the janitor can do about a backgrounded command that nobody reads again (report it, cap its lifetime, or nothing), and propose it to the owner. Related: TRDD-BZ3BT0NJ (memory guard), TRDD-8X7C7TU9 (fastedit memory growth).

## Approval log

- 2026-10-05T22:07:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
