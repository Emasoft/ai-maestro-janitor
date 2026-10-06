---
trdd-id: 8SC3YEIG
title: Clear chain stops typing janitor-arm
column: backburner
status: tasked
created: 2026-10-03T03:41:57+0200
updated: 2026-10-03T09:33:12+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

Design: the clear-only bootstrap types only /janitor-resume; the reload chains keep (/janitor-arm, /janitor-resume). Verified: on-session-start.py keeps the live cron for every source other than startup/resume, so dropping /janitor-arm after /clear leaves the cron in place. Held: the change is to module-level constants in scripts/clear_trigger.py (_BOOTSTRAP_CMDS / BOOTSTRAP_CMDS, lines ~77-90), which fastedit cannot edit; building the tuples inside functions would open-code them at six call sites. Waits on the owner's plain-edit decision tracked on TRDD-MMUSDJHQ. Worker report: docs_dev/20261003_093051+0200-c5-clear-bootstrap-blocked.md.
2026-10-03: parked in backburner, not blocked: the blocker is an owner decision, not a card or a machine-checkable condition.
