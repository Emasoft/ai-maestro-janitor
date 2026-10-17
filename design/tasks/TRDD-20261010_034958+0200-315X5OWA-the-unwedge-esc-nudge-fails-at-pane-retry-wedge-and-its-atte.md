---
trdd-id: 315X5OWA
title: The unwedge ESC nudge fails at pane retry_wedge and its attempts climb with no recovery
column: todo
status: tasked
created: 2026-10-10T03:49:58+0200
updated: 2026-10-17T14:26:49+0200
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
---

# The unwedge ESC nudge fails at pane retry_wedge and its attempts climb with no recovery

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

- column: todo
- DONE: 36287c9c adds reads=/presses= to the failed pane-policy line, 82a167e5 pins the per-step reads slice with a test. Diagnostic only: the failing nudge is NOT fixed.
- CAVEAT: on a FAILED step presses= always equals the step's repeat_max (1 unqueued, 2 with one queued row), and it counts type_keys calls, not delivered keystrokes. Only reads= discriminates a wall that persists after every ESC.
- PREREQUISITE for the log path: the daemon runs the installed plugin build, so reads= appears in global-state/daemon.log only after a publish via scripts/publish.py and a local plugin update. Until then the old 'failed (observed X)' text is logged.
- FINDING 2026-10-17 (reports/pane-policy/20261017_144357+0200-315X5OWA-retry-wedge-root-cause.md, key points re-read by the main session): retry_wedge is Claude Code's 'Retrying in … attempt N/M' countdown under an account-side wall (the three real-wedged-* fixtures read 'Session limit reached', 'Fable limit reached · Retrying in 5h', '429 Rate limited'). ESC cancels the retrying request but cannot lift the limit, so WEDGE_GONE cannot hold and the step fails by construction; the episodes cleared only after a rotation. Remedy belongs in TRDD-BBGDUCSE: daemon.py:2122 requests a rotator tick only for diagnosis retry_wedged, not for a failed fire at a retry_wedge pane. Secondary defect, not the root cause: _flush_wedge (pane_policy.py:184-191) gives an empty-field wedge repeat_max 1, so no second ESC. NEXT ACTION: build BBGDUCSE; after publish, close this card as explained once a post-publish failed line shows reads=retry_wedge x3.
- NEXT ACTION (after publish): on the next 'unwedge: failed', read reads= to confirm.
- GOTCHA: the ok line text is unchanged on purpose (TRDD-UA4FAX67 greps it).
- NOTE: the 2026-10-17 Approval-log line about 36287c9c duplicates this block and is not an approval event; Approval log is append-only, so it stays. The 82a167e5 commit message wrongly says this block replaced it.

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN, step vi); not investigated beyond what is written here. Read in global-state/daemon.log: 10 lines containing '[frozen] attempt=' between 2026-10-09T19:21:26 and 19:56:23 (count by the main session); a worker read them as 5 episodes in two other projects (ai-maestro, llm-externalizer), each 'FIRE-FAILED esc_nudge' at pane=retry_wedge followed by 'unwedge: failed', attempts 0, 1, 2. The line is written at scripts/daemon.py:1602. Related: TRDD-L32WC0H7 (its success case is unseen), TRDD-WKTD5JTC (wedge detection, complete), TRDD-KE88RIKX. To do: read why the fire fails (typing gate, pane kind, or the injector itself), and whether a third failed attempt should change remedy.

## Approval log

- 2026-10-10T03:49:58+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 03:51 CORRECTION to the body (review of af8d1b1e; lines read by the main session): the 10 '[frozen] attempt=' lines are 5 pairs, an 'unwedge: failed' pane-policy line and then a 'FIRE-FAILED esc_nudge' line in the same second. That is 5 failed fires in TWO episodes, not five episodes: ai-maestro at 19:21:26, 19:40:46 and 19:56:23 (attempts 0, 1, 2) and llm-externalizer at 19:30:06 and 19:45:13 (attempts 0, 1), all 2026-10-09. No other FIRE-FAILED esc_nudge line is in the logs on disk. The file and line daemon.py:1602 is worker-read; the session-liveness FIRE-FAILED line is built at daemon.py:2108 (grep hit).
2026-10-17 — 36287c9c: diagnostic only. A failed pane-policy step now logs reads=<every classification read in that step> and presses=<counted presses>, so the next failed unwedge in daemon.log shows whether retry_wedge persists after each ESC or too few ESCs were sent. Root cause not yet fixed; card stays in todo.
