---
trdd-id: 315X5OWA
title: The unwedge ESC nudge fails at pane retry_wedge and its attempts climb with no recovery
column: todo
status: tasked
created: 2026-10-10T03:49:58+0200
updated: 2026-10-17T23:27:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:49:58+0200
implementation-commits: [36287c9c, 82a167e5]
npt: [XNQUYVT3]
---

# The unwedge ESC nudge fails at pane retry_wedge and its attempts climb with no recovery

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

- column: todo
- DONE: 36287c9c adds reads=/presses= to the failed pane-policy line, 82a167e5 pins the per-step reads slice with a test. Diagnostic only: the failing nudge is NOT fixed.
- CAVEAT: on a FAILED step presses= always equals the step's repeat_max (1 unqueued, 2 with one queued row in the two fixtures), and it counts type_keys calls, not delivered keystrokes. reads= shows whether the retry row stayed on screen; neither field shows delivery.
- PREREQUISITE for the log path: the daemon runs the installed plugin build, so reads= appears in global-state/daemon.log only after a publish via scripts/publish.py and a local plugin update. Until then the old 'failed (observed X)' text is logged.
- FINDING 2026-10-17 (two rival hypotheses, NEITHER proven; no pane frame was ever captured at a real failure). H1 wall persists (INFERRED): retry_wedge is Claude Code's 'Retrying in … attempt N/M' row; the real-wedged-* fixtures read 'Session limit reached', 'Fable limit reached · Retrying in 5h' and '429 Rate limited · Retrying in 0s' (the last is transient, not a quota wall). If ESC does not take the row off screen, WEDGE_GONE never holds and the remedy is TRDD-BBGDUCSE, because the only rotator request on this path is request_rotator_tick('retry-wedged-esc') under diagnosis == 'retry_wedged' in daemon.py, not on a failed fire at a retry_wedge pane. H2 ESC not delivered or ignored: the comment above that call (TRDD-WKTD5JTC §1b, measured) says an ESC that breaks a retry wedge fires plain Stop and the session then sits idle, i.e. a delivered ESC CAN clear the row; that contradicts H1 for the unqueued case and keeps the card's original suspects (typing gate, pane kind, injector) live. Not a defect: _flush_wedge gives an empty-field wedge repeat_max 1 on purpose (a second ESC onto an empty prompt opens the rewind menu). Unverified secondhand: 'episodes cleared after a rotation' (docs_dev scope note, not re-read; one 10-14 failure was followed by an ok with no rotation named). Supporting report (gitignored, local only): reports/pane-policy/20261017_144357+0200-315X5OWA-retry-wedge-root-cause.md. NEXT ACTION: get a DELIVERY signal - a pane frame captured right after the ESC at a real retry_wedge - before choosing; reads=retry_wedge x3 alone cannot separate H1 from H2. If H1 holds, work TRDD-BBGDUCSE's pre-build conditions; if H2, fix delivery here.
- AFTER PUBLISH: a failed line whose every read is a retry_wedge token (retry_wedge@<attempt>[<countdown>] since TRDD-XNQUYVT3) confirms the row stayed on screen, but does NOT say whether the ESC was delivered (see FINDING); it is not a closing criterion on its own. H3 (added by the final review, 2026-10-17): the ESC is delivered and clears the row, then something (e.g. a heartbeat cron that fires only when the REPL is idle) resubmits into the same wall within seconds. Separating H1/H2/H3 needs TRDD-XNQUYVT3 (attempt number per read), now an NPT of this card.
- GOTCHA: the ok line text is unchanged on purpose (TRDD-UA4FAX67 greps it).
- NOTE: the 2026-10-17 Approval-log line about 36287c9c duplicates this block and is not an approval event; Approval log is append-only, so it stays. The 82a167e5 commit message wrongly says this block replaced it.

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN, step vi); not investigated beyond what is written here. Read in global-state/daemon.log: 10 lines containing '[frozen] attempt=' between 2026-10-09T19:21:26 and 19:56:23 (count by the main session); a worker read them as 5 episodes in two other projects (ai-maestro, llm-externalizer), each 'FIRE-FAILED esc_nudge' at pane=retry_wedge followed by 'unwedge: failed', attempts 0, 1, 2. The line is written at scripts/daemon.py:1602. Related: TRDD-L32WC0H7 (its success case is unseen), TRDD-WKTD5JTC (wedge detection, complete), TRDD-KE88RIKX. To do: read why the fire fails (typing gate, pane kind, or the injector itself), and whether a third failed attempt should change remedy.

## Approval log

- 2026-10-10T03:49:58+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 03:51 CORRECTION to the body (review of af8d1b1e; lines read by the main session): the 10 '[frozen] attempt=' lines are 5 pairs, an 'unwedge: failed' pane-policy line and then a 'FIRE-FAILED esc_nudge' line in the same second. That is 5 failed fires in TWO episodes, not five episodes: ai-maestro at 19:21:26, 19:40:46 and 19:56:23 (attempts 0, 1, 2) and llm-externalizer at 19:30:06 and 19:45:13 (attempts 0, 1), all 2026-10-09. No other FIRE-FAILED esc_nudge line is in the logs on disk. The file and line daemon.py:1602 is worker-read; the session-liveness FIRE-FAILED line is built at daemon.py:2108 (grep hit).
2026-10-17 — 36287c9c: diagnostic only. A failed pane-policy step now logs reads=<every classification read in that step> and presses=<counted presses>, so the next failed unwedge in daemon.log shows whether retry_wedge persists after each ESC or too few ESCs were sent. Root cause not yet fixed; card stays in todo.

## Implementation notes

2026-10-17: TRDD-XNQUYVT3 enriches the failed line's reads=: each wedge read is now retry_wedge@<attempt>[<countdown>] instead of bare retry_wedge, so find failed unwedge lines with grep 'unwedge: failed', not by matching the old bare reads= list.
