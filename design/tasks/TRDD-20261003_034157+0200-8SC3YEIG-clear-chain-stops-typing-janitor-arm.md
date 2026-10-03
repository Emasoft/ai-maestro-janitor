---
trdd-id: 8SC3YEIG
title: Clear chain stops typing janitor-arm
column: blocked
status: tasked
created: 2026-10-03T03:41:57+0200
updated: 2026-10-03T09:31:38+0200
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
review-after: 2026-10-17
parent-trdd: K9AHY1ZB
unblock-when: [decision: owner approves plain edits for module-level constants]
blocked-by: [MMUSDJHQ]
pre-block-column: dev
---

# Clear chain stops typing janitor-arm

- **C5**: the clear chain's bootstrap becomes `(RESUME_CMD,)` (crons survive `/clear`, verified). The reload triggers keep `/janitor-arm`. Test: the dry-run keystroke plan.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:41:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T09:30:32+0200 — column → dev. C5 in progress

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

Design: the clear-only bootstrap types only /janitor-resume; the reload chains keep (/janitor-arm, /janitor-resume). Verified: on-session-start.py keeps the live cron for every source other than startup/resume, so dropping /janitor-arm after /clear leaves the cron in place. Blocked: the change is to module-level constants in scripts/clear_trigger.py (_BOOTSTRAP_CMDS / BOOTSTRAP_CMDS, lines ~77-90), which fastedit cannot edit; building the tuples inside functions would open-code them at six call sites. Waits on the owner's plain-edit decision tracked on TRDD-MMUSDJHQ. Worker report: docs_dev/20261003_093051+0200-c5-clear-bootstrap-blocked.md.
