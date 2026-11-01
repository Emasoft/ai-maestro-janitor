---
trdd-id: KSUIEPTQ
title: reports dir is git-tracked, the janitor stops gitignoring and purging it
column: dev
status: tasked
created: 2026-11-01T02:44:18+0100
updated: 2026-11-01T02:44:18+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-01T02:44:18+0100
---

# reports dir is git-tracked, the janitor stops gitignoring and purging it

USER 2026-11-01 verbatim: "can you please stop putting the reports/ folder in the gitignore? reports_dev must be git ignored. reports/ is essential to a project and must be project scoped. just use the report sanitizer script to redact private data and paths." and "the janitor is making a mess in every project ... publish asap and install". Spec = GitHub issues #348 (items 1,2,3,4) and #350. Item 5 of #348 (local design path revert) is OUT of scope, separate card.

Changes:
1. scripts/lib/reports_gitignore.py + scripts/detectors/reports-gitignore.py: REQUIRED_DIRS = (reports_dev,). Undo the fleet mess: remove a /reports/ line ONLY when it sits in the janitor's own _BLOCK_HEADER block; if git check-ignore -v names any other rule, emit one deduped advisory naming source:line, never edit a user-authored line.
2. scripts/lib/gitignore_coverage.py: reports is no longer a private class.
3. scripts/detectors/reports-purge.py: retire the reports/ age-purge half (reports/ is tracked work, *_dev contents are never deleted per RULE 0); keep the seen-file cap. Fixes #350.
4. scripts/detectors/screenshot-purge.py + dispatch.py comment: screenshots live in reports_dev/<component>/screenshots/.
5. scripts/commands/doctor.py + skills/janitor-doctor: check reports_dev ignored and reports NOT ignored.
6. Docs: rules/janitor-footprint.md, rules/trdd-design-tasks.md rule 11, rules/references/trdd-design-tasks-full.md, skills/janitor-gitignore-fix, agents (security, repair, memory curator): machine/harness state reports go to reports_dev/<agent>/, anything bound for reports/ is sanitized first with sanitize-reports.
7. This repo: drop /reports/ from .gitignore; move the 862 existing untracked reports/<c>/<f> to reports_dev/<c>/<f> (written under the private regime; not reviewable for publication now).

## Approval log

- 2026-11-01T02:44:18+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
