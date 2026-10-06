---
trdd-id: 7KI11RH7
title: reference-mem-topic and reference-mem-atom wire downward cross-scope links that lint then flags as errors
column: todo
status: tasked
created: 2026-10-06T21:26:07+0200
updated: 2026-10-06T21:26:07+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:07+0200
---

# reference-mem-topic and reference-mem-atom wire downward cross-scope links that lint then flags as errors

Source: GitHub issue Emasoft/ai-maestro-janitor#330 (opened 2026-10-04). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The two reference verbs have no cross-scope guard and wire a user-scope to local-scope link, which memgrep lint then reports as a privacy error. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:07+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
