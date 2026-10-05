---
trdd-id: 6NMQ95TQ
title: fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script
column: todo
status: tasked
created: 2026-10-05T22:08:49+0200
updated: 2026-10-05T22:08:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:49+0200
---

# fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed three times in one day in this repository: fastedit refused a pure deletion of a block inside a function, an addition to a module docstring, and a new module-level constant. In the first case the worker edited a scratch copy by script and applied it as a full-function replacement, which the standing rule forbids; in the second the item was skipped and a stale docstring remains; in the third the text was written inline instead. To do: reproduce each refusal on a scratch file, find the supported way to make each edit, report upstream what has none, and state in worker prompts what to do on a refusal.

## Approval log

- 2026-10-05T22:08:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
