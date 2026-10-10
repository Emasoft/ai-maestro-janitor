---
trdd-id: MI018FID
title: The stuck alert and the login-needed detector describe the same condition in different words
column: testing
status: tasked
created: 2026-10-05T22:11:15+0200
updated: 2026-10-10T16:10:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:15+0200
---

# The stuck alert and the login-needed detector describe the same condition in different words

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

For all-accounts-maxed the alert says to wait for a window; the detector says the same and adds 'or add another paid account'. Two texts for one condition, kept in two files.

## Approval log

- 2026-10-05T22:11:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 16:10. BUILT, one code commit carrying this line. READ first by the main session: the desktop alert (scripts/lib/rotator_alert.py) and the heartbeat detector (scripts/detectors/oauth-login-needed.py) each kept a table of texts for a stuck rotation, and the detector also sends its own notification with its wording, so the owner could get two differently worded notices for one condition. CHANGE: rotator_alert.stuck_text(kind) is the one source; the detector's five-entry table is gone and its heartbeat line and notification use the shared text. TEST: tests/test_oauth_login_needed.py::test_stuck_line_uses_the_alert_table_text (five kinds and one unknown), red before the detector change (the all-accounts-maxed wording differed at the first kind) and green after, per the worker report reports/board/20261010_160619+0200-mi018fid-worker.md; the main session read the whole diff twice (before and after the layout fix). The redundant control test left by TRDD-DM7IJQ1T is deleted; its case is the no-usable-slot-twin row of test_stuck_alert_text_per_kind. KNOWN LOSSES, accepted from the review of the uncommitted change (0.34 million tokens, no blocker): the detector line no longer carries its longer diagnosis ('the rotator refuses to act on an untrusted identity') nor the login-script command for no-alternates-configured and no-usable-slot-twin; an unknown kind now gets the capture text where the detector said 'see the rotator log'; all-accounts-maxed no longer says 'or add another paid account'; the detector's notification text changed, so a condition already notified is notified once more after the release. CHECKED after the review: that a login capture covers the live account's saved copy rests on the text of skills/janitor-capture-all-logins/SKILL.md (it re-mints every account of the roster and does not switch the live one); the walker script was not read. TOOL FACT: fastedit could not add blank lines around the new function; they were added by regenerating the whole file on stdout into fastedit create --force, verified as exactly four added empty lines with git diff. The new test imports rotator_alert through a path the detector import sets up. FIELD CASE UNOBSERVED. Column testing until the full gate on this commit is green.
