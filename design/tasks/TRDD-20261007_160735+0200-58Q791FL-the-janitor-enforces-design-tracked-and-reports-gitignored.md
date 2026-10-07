---
trdd-id: 58Q791FL
title: The janitor enforces design tracked and reports gitignored
column: testing
status: tasked
created: 2026-10-07T16:07:35+0200
updated: 2026-10-07T18:41:58+0200
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

Later the same day: "just correct the janitor plugin to always enforce the design folder as git tracked, and the reports folder as gitignored."

Incident: repo emasoft-complete-ios-app-authoring had a `/design/` line in `.git/info/exclude`; 467 cards stayed untracked.

Plan: new detector design-tracked (probe design paths with check-ignore --no-index, fix info/exclude line or append root negations, warn on nested/global sources, daily untracked-card line). reports-gitignore already enforces reports/ and reports_dev/ (lib/reports_gitignore.py) - unchanged.

## Approval log

- 2026-10-07T16:07:35+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-07: when design/ is hidden because a parent folder is excluded, the append path still writes !/design/ and !/design/** to the root .gitignore, re-probes, finds it still hidden and warns, leaving a .gitignore edit that achieves nothing. Fix: check that the negations would take effect (or revert the append) before keeping it.
2026-10-07T18:41:17+0200: CORRECTION to the line above: the excluded-parent case does not happen for design/. It sits at the repo root, and a root .gitignore with * followed by !/design/ and !/design/** leaves design files NOT ignored (measured, reports/board/20261007_160605+0200-gitignore-precedence-measure.md case 3a). Only a nested .gitignore defeats the repair, and the detector already leaves that case unedited.
2026-10-07T18:41:57+0200: a second unrepaired case (from reading _append_negations): when the root .gitignore already holds !/design/ and !/design/** but a LATER line in it hides design/ again (design/, /design/tasks/, or * after the negations), nothing is appended because both lines are present, and the detector only warns. Fix: append the negations again at the end whenever the hiding rule's line number is after them.
