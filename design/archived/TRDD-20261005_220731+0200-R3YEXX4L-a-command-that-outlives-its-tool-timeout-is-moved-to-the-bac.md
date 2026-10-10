---
trdd-id: R3YEXX4L
title: A command that outlives its tool timeout is moved to the background and keeps running unwatched
column: complete
status: archived
created: 2026-10-05T22:07:31+0200
updated: 2026-10-10T15:00:08+0200
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
- 2026-10-10T15:00:08+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Findings 2026-10-05

Investigated read-only (report 20261005_230718 investigate-R3YEXX4L). VERIFIED in the Claude Code documentation and by a live check on version 2.1.285: a foreground command that reaches its tool timeout is moved to the background by design, the tool result says so and names a task id, and the session is notified again when it ends; on this version a moved command is stopped 30 minutes after the move. READ in the documentation, not run: from version 2.1.288 an interactive session has no time limit on a moved command. The recorded tool result carries the fields timedOutAfterMs and backgroundTaskId. No janitor hook reads them. NOT VERIFIED: that the PostToolUse hook fires for a moved call and carries those fields; one logging probe settles it. So the title's word unwatched is wider than the facts: the harness watches for the end; nothing watches memory or a hang in between, and nothing records which commands were still running when a host degrades. Options, least to most intervention: (A) record a moved command in a per-project log and tell the session once, after the probe; (B) a rule line for agents on long commands; (C) ending a moved command after a time, which is intervention and belongs to TRDD-DKID2PYP.
Provenance and corrections (review, 2026-10-05): the paragraph above is from a fork's report; the session read the report in full and did not re-run it. The stop 30 minutes after the move is from the documentation and from the tool's own message, not observed: the live check ended by itself at 40 s. Not carried above: the setting that makes a timed-out command stop instead of move also disables background commands and background agents, so it is not an option; an inner timeout prefix works on this host only because GNU coreutils is installed; which signal ends a command at its limit is unknown.

## Decision

2026-10-10 15:00, wave 9 card 1, decided by the main session under the mandate of 2026-10-09: NO janitor change. To-do items, each answered or named as skipped: (1) what happens at the timeout: answered in the Findings (moved by design, the tool result names a task id, the session is notified at the end); (2) inner timeout prefix: answered (honoured on this host through GNU coreutils); (3) what the janitor can do: none of A, B, C is built. MEASURED 2026-10-10 by the main session: this project's 35 retained transcripts hold 2 real moved results (both at the 500 s limit); one was reported completed to the session 23 minutes later, the other was stopped by the session with TaskStop 20 s after the move; neither ran unwatched. Across all projects, files with a real moved result are common (22, 16, 15, 9 in the four busiest project folders, of 4699 transcripts), so a move is ordinary and option A would tell the session what the tool result already told it. Option B is a rule for agents and the owner's global rules already ask for background commands; option C is intervention and stays on TRDD-DKID2PYP. SKIPPED, named: the probe of whether a PostToolUse hook receives timedOutAfterMs (no hook is built; the transcript carries the fields and one grep for timedOutAfterMs followed by a digit finds them, which is the observer if this is ever reopened). NOT ESTABLISHED: the 30 minute stop was never observed; that version 2.1.288 and later put no limit on a moved command is read, not run (this host runs 2.1.296); the incident session in the other project was not examined. Ranking: R3YEXX4L was first among todo cards in trddgrep next.

## Acceptance

- [x] The behaviour of a foreground command at its timeout is established from the documentation and one live check (the 30 minute stop unobserved).
- [x] The inner timeout prefix is checked on this host.
- [x] A decision on the janitor's part is recorded with its measurement: no change; the owner is told in the session report, no proposal card is opened.
