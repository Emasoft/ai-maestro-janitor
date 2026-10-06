---
trdd-id: SFWYVPGC
title: memory_dispatch_claim peek ignores the chore option and returns the first candidate
column: todo
status: tasked
created: 2026-10-06T21:25:54+0200
updated: 2026-10-06T21:25:54+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:54+0200
---

# memory_dispatch_claim peek ignores the chore option and returns the first candidate

Source: GitHub issue Emasoft/ai-maestro-janitor#319 (opened 2026-09-29). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Run with peek and a chore name, the script returns the same pending record whatever chore is requested, because the candidate list is chore-blind. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:54+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
