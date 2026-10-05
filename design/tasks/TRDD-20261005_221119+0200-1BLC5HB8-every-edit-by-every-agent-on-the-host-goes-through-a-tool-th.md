---
trdd-id: 1BLC5HB8
title: Every edit by every agent on the host goes through a tool that may load a local model
column: todo
status: tasked
created: 2026-10-05T22:11:19+0200
updated: 2026-10-05T22:11:19+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:19+0200
---

# Every edit by every agent on the host goes through a tool that may load a local model

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The standing rule sends all edits through fastedit. With twenty or more sessions and their workers, several model-sized processes run at once. Measure the real concurrency and memory, and report it to the owner of the rule.

## Approval log

- 2026-10-05T22:11:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
