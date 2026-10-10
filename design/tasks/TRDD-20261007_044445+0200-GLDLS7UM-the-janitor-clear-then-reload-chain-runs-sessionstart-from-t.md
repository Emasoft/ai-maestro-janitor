---
trdd-id: GLDLS7UM
title: The janitor clear-then-reload chain runs SessionStart from the old plugin version
column: backburner
status: tasked
created: 2026-10-07T04:44:45+0200
updated: 2026-10-10T22:45:13+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:44:45+0200
review-after: 2026-12-10
---

# The janitor clear-then-reload chain runs SessionStart from the old plugin version

## Problem
The janitor's reload chain types the clear first and the plugin reload after, so the SessionStart that injects the handoff runs the hooks of the version the process started on.

## Evidence
18 SessionStart log entries since 2026-10-05 name root 3.7.0, the newest at 03:52:24 on 2026-10-07, 4 seconds before the reload. Sessions that only cleared kept 3.7.0 across releases 3.7.3 to 3.8.2.

## Consequence
Fixes that live in SessionStart hooks or their timeouts (cards KVUVV9D2, 9438CGJZ, C7M4RXQ2, D7RLXAN1) cannot be observed in a long-lived session, and the handoff injection of 2026-10-07 ran as 3.7.0.

## Not established
Whether a reload alone moves the hook root (the next clear decides), and whether the logged root is the one the harness ran the hook from.

## Scope
The general rule that a running session keeps old plugin code is already on the memory page claude-code-plugin-rollout-staleness. This card is only about the ORDER inside the janitor's own chain.

## Options (none chosen)
Reload before the clear; or a second SessionStart-equivalent step after the reload.

## Acceptance
- [ ] After one janitor-driven reload, the SessionStart log entry of the resumed session names the newest cached version.

## Approval log

- 2026-10-07T04:44:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-07: not started. NEXT ACTION: read the SessionStart log entry after the next clear-then-reload of a janitor-armed session; if it names 3.7.0, reorder the chain per the options above.
2026-10-07 wording correction: the sentence saying the injection ran as 3.7.0 means only that its log entry names root 3.7.0; whether the harness ran the hook from there is the open point listed under not established.
2026-10-10 22:41. MEASURED in this project's session-start.log, NOT BUILT; parked in backburner by decision of the main session under the mandate of 2026-10-09. FIRST OPEN POINT ANSWERED, by inference: every session-start entry from 2026-10-05 01:12 to the reload of 2026-10-07 03:52 names root 3.7.0, and the next entry that names another root is a clear at 2026-10-07 07:11:26 naming 3.8.2 (session fcc488b3), with no startup or resume entry between them; so a reload does move the hook root and the first clear AFTER the reload runs the new hooks. Inferred, not proven: that those entries belong to one process (the log has no process id), and the second open point (whether the logged root is the one the harness ran from) is untouched. Later clears named 3.8.6, 3.8.10 and 3.8.11, each after a resume entry, that is a new process. SO THE DEFECT IS BOUNDED: the one handoff injection of the clear that precedes the reload runs the old hooks; the next clear runs the new ones. WHY NOT REORDERED: reloading before the clear re-reads the whole uncleared context without the prompt cache, which is the cost the clear-first order exists to avoid (the reload skill shrinks first above 350k tokens for that reason; read in the skill's description, the skill body and code not re-read today); the second option, a session-start-equivalent step after the reload, was not designed. NOT OBSERVABLE NOW: 3.8.11 is the newest cached version and the reload guard has logged 'no enabled plugin changed version' on every check since 2026-10-09, so the Acceptance event needs a release. PULL CONDITION: a fix that must take effect in the same clear that precedes a reload (a session-start hook fix whose one-clear delay loses data), or a measured case of a handoff lost because the old hooks injected it.
2026-10-10 22:45. CORRECTIONS from the review of 67be5640, accepted. (1) 'no startup or resume entry between them': checked afterwards against the whole log, not the change-only table: session-start.log holds no entry of any kind between the clear of 2026-10-07 03:52:24 (session 932fc367, root 3.7.0) and the clear of 07:11:26 (session fcc488b3, root 3.8.2), and reload-trigger.log shows the shrink-then-reload chain spawned at 03:52:04; other sessions of this project write the same log, so one process is still an inference. (2) UNEXPLAINED: the 07:11 entry names 3.8.2 while the cache folder 3.8.3 is dated 06:15 and 3.8.2 is dated 07:24; folder dates change when contents change, so they do not order the installs, and which version a reload at 03:52 could have picked was not established. The bounded-defect conclusion therefore rests on one transition that is not fully explained. (3) The reviewer's point that an event-gated card belongs in a waiting column with a detect command, not in backburner, is noted: DETECT, after the next release and a janitor-driven reload: the session-start entry of the clear that follows the reload names the newest cached version.
