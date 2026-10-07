---
trdd-id: 58Q791FL
title: The janitor enforces design tracked and reports gitignored
column: testing
status: tasked
created: 2026-10-07T16:07:35+0200
updated: 2026-10-07T16:21:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T16:07:35+0200
implementation-commits: [de7475f3]
---

# The janitor enforces design tracked and reports gitignored

Owner directives (verbatim, 2026-10-07):

> "the janitor must automatically track the design folder and since its project scoped. and must warn the agent that it must not be gitignored."

> "just correct the janitor plugin to always enforce the design folder as git tracked, and the reports folder as gitignored."

Incident: repo emasoft-complete-ios-app-authoring had a `/design/` line in `.git/info/exclude`; 467 cards stayed untracked.

Plan: new detector design-tracked (probe design paths with check-ignore --no-index, fix info/exclude line or append root negations, warn on nested/global sources, daily untracked-card line). reports-gitignore already enforces reports/ and reports_dev/ (lib/reports_gitignore.py) - unchanged.

## Approval log

- 2026-10-07T16:07:35+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
