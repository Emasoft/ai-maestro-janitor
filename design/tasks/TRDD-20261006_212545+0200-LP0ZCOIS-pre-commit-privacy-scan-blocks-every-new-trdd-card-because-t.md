---
trdd-id: LP0ZCOIS
title: Pre-commit privacy scan blocks every new TRDD card because the author token looks like an ssh user and host
column: todo
status: tasked
created: 2026-10-06T21:25:45+0200
updated: 2026-10-06T21:25:45+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:45+0200
---

# Pre-commit privacy scan blocks every new TRDD card because the author token looks like an ssh user and host

Source: GitHub issue Emasoft/ai-maestro-janitor#314 (opened 2026-09-28). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The pre-commit privacy scan flags the required author token of a new card as a private-path ssh-user-host leak, so every newly minted card is refused at commit. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
