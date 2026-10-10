---
trdd-id: C0RSMPRG
title: The daemon resume injection fails four times out of five across eight projects
column: todo
status: tasked
created: 2026-10-10T03:51:17+0200
updated: 2026-10-10T03:51:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:51:17+0200
---

# The daemon resume injection fails four times out of five across eight projects

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN); not investigated beyond what is written here. Counted by the main session in global-state/daemon.log.1 and daemon.log (2026-10-07T18:24 to 2026-10-10 about 03:45): 107 lines 'resume-wake: FIRE-FAILED /janitor-resume for <project>' against 23 lines 'resume-wake: FIRED /janitor-resume'. By day: 8 on 2026-10-08, 78 on 2026-10-09, 21 on 2026-10-10. By project: ghbook 19, ai-maestro-web-scenario-tester 19, emasoft-complete-ios-app-authoring 15, reminzer 13, ai-maestro 12, llm-externalizer 8, AgentlensPro 7, ai-maestro-janitor 6. Busiest minutes: 10 failures each at 2026-10-09T17:58 and 18:45. The line is written at scripts/daemon.py:2369 (grep hit, code not read). Not read: why a fire fails (the pane-policy lines beside them may say), and whether each failed session was resumed later by another path. Related: TRDD-HYTKG53C, whose 'NO DETECT POSSIBLE: receipt not logged' of 2026-10-10 should be re-read against these lines; TRDD-N954KWUC.

## Approval log

- 2026-10-10T03:51:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
