---
trdd-id: 8SC3YEIG
title: Clear chain stops typing janitor-arm
column: backburner
status: tasked
created: 2026-10-03T03:41:57+0200
updated: 2026-10-10T12:37:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:57+0200
project-id: ai-maestro-janitor

parent-trdd: K9AHY1ZB


 
---

# Clear chain stops typing janitor-arm

- **C5**: the clear chain's bootstrap becomes `(RESUME_CMD,)` (crons survive `/clear`, verified). The reload triggers keep `/janitor-arm`. Test: the dry-run keystroke plan.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:41:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T09:30:32+0200 — column → dev. C5 in progress
- 2026-10-03T09:33:00+0200 — column → backburner. deferred: waits on the owner's plain-edit decision for module-level constants (see STATE) Cleared blocked-by (--clear-blocker override).
2026-10-10 12:08 BOARD DRAIN: this card asks that the clear chain's bootstrap become (RESUME_CMD,) because 'crons survive /clear, verified'. THAT PREMISE IS CONTRADICTED on Claude Code 2.1.296: the post-clear diagnostic of 2026-10-10 09:09 reports 'cron id changed 6e812941 to 5a840a7a (destroyed by /clear, recreated by re-arm)' (reports/continuity-build/20261010_090954+0200-handoff-clear-verify.md). Removing /janitor-arm from the clear bootstrap as written would leave a cleared session with no heartbeat unless SessionStart's own self-check re-arms it, which was not examined. DO NOT BUILD AS WRITTEN. It stays in backburner; pull it only after measuring, on the current Claude Code, whether a clear with no arm command still ends with a live heartbeat cron. Its old block reason (the edit tool cannot change module-level constants) has a verified workaround: rewrite the file through fastedit create and check the result with git diff, as done for scripts/oauth_rotator/rotate_to.py on 2026-10-10.
2026-10-10 12:09 WITHDRAWN: the line of 12:08 above saying this card's premise is CONTRADICTED and 'DO NOT BUILD AS WRITTEN'. It rested on the post-clear diagnostic's wording 'cron id changed 6e812941 to 5a840a7a (destroyed by /clear, recreated by re-arm)', which cannot tell a cron destroyed by the clear from one deleted by the re-arm, since every arm changes the id. DIRECT EVIDENCE the other way, from the resumed session's own first tool calls on 2026-10-10 at about 09:09 (Claude Code 2.1.296): arm_prepare.py printed prior-cron-id=6e812941 and sweep=no, and CronDelete 6e812941 answered 'Cancelled job 6e812941'. A cron already destroyed would have answered not found. So that cron was ALIVE after the clear, which supports this card's premise that crons survive a clear. One case; not excluded: that SessionStart on a clear recreated a cron under the same stamped id before the arm ran (not examined). The diagnostic's check 1 wording is itself misleading and is noted on TRDD-JK2MLS8Z's subject (the post-clear diagnostic). This card stays in backburner on its own earlier reasons; the edit-tool workaround noted at 12:08 still applies.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

Design: the clear-only bootstrap types only /janitor-resume; the reload chains keep (/janitor-arm, /janitor-resume). Verified: on-session-start.py keeps the live cron for every source other than startup/resume, so dropping /janitor-arm after /clear leaves the cron in place. Held: the change is to module-level constants in scripts/clear_trigger.py (_BOOTSTRAP_CMDS / BOOTSTRAP_CMDS, lines ~77-90), which fastedit cannot edit; building the tuples inside functions would open-code them at six call sites. Waits on the owner's plain-edit decision tracked on TRDD-MMUSDJHQ. Worker report: docs_dev/20261003_093051+0200-c5-clear-bootstrap-blocked.md.
2026-10-03: parked in backburner, not blocked: the blocker is an owner decision, not a card or a machine-checkable condition.

## Corrections

2026-10-10 12:37 CORRECTION to the 2026-10-10 12:09 line: 'the cron was alive after the clear' should read 'was still registered'. A CronDelete that answers Cancelled proves a job with that id existed in the resumed session, not that it would have fired; no fire was observed between the clear and the re-arm. Second instance today: after the clear of 12:32 the CronDelete of the prior id 5a840a7a also answered Cancelled. The one measurement that settles this card's premise is a heartbeat fire after a clear with no re-arm; do not build before it.
