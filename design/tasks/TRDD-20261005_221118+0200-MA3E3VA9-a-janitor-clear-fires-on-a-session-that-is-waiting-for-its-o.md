---
trdd-id: MA3E3VA9
title: A janitor clear fires on a session that is waiting for its owner's answers
column: todo
status: tasked
created: 2026-10-05T22:11:18+0200
updated: 2026-10-05T22:13:34+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:18+0200
---

# A janitor clear fires on a session that is waiting for its owner's answers

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

On 2026-10-05 a clear fired on a session that had asked the owner five questions and was waiting, and on another with a very large context. Decide whether waiting on the owner should hold a clear, and how the questions survive it.

## Approval log

- 2026-10-05T22:11:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the first clear is known only from the handoff text and the count of questions from the earlier session's own summary; the second clear was on another project and was not shown to be waiting on its owner.
