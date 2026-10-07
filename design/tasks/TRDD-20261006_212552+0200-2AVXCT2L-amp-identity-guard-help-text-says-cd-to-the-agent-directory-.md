---
trdd-id: 2AVXCT2L
title: amp identity guard help text says cd to the agent directory resolves identity but it does not
column: blocked
status: tasked
created: 2026-10-06T21:25:52+0200
updated: 2026-10-07T07:48:10+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:52+0200
blocked-by: [Emasoft/ai-maestro#172]
pre-block-column: todo
---

# amp identity guard help text says cd to the agent directory resolves identity but it does not

Source: GitHub issue Emasoft/ai-maestro-janitor#318 (opened 2026-09-28). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The refusal message of the amp-kanban-list identity guard offers changing into the agent working directory as a resolution. From a session not spawned by the server that does not resolve identity, so the advice misleads. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:48:00+0200 — column → blocked by main-agent@ai-maestro-janitor. refusal text lives in ai-maestro#172; issue 318 closed with that pointer
2026-10-07: moved to blocked (pre-block-column todo), blocked-by Emasoft/ai-maestro#172: the refusal text lives in ai-maestro; issue 318 closed with that pointer.
