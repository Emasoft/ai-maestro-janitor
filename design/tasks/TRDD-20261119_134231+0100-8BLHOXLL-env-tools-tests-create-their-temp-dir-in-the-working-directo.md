---
trdd-id: 8BLHOXLL
title: Env tools tests create their temp dir in the working directory
column: todo
status: tasked
created: 2026-11-19T13:42:31+0100
updated: 2026-11-19T13:42:43+0100
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
approval-datetime: 2026-11-19T13:42:31+0100
relevant-rules: [34]
---

# Env tools tests create their temp dir in the working directory

## Symptom

The owner env tools tests (test_envkey.py, test_envget.py under scripts/janitor-env-tools/) create TemporaryDirectory(dir=Path.cwd()), so a run from the repo root leaves envkey-tests-* folders there (an untracked envkey-tests-6mq9puzf/ sat in the repo root on 2026-11-19). The tests are the owner code (PRRD G27.1-G33.1), so a change needs care: a temp dir under the system temp folder, or the runner moves into a temp folder.

## Done means

- [ ] No test leaves a folder in the working directory.

Filed under PRRD G34.1 (every issue becomes a ticket or a TRDD).

## Approval log

- 2026-11-19T13:42:31+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
