---
trdd-id: M6QJ3IUN
title: UserPromptSubmit hooks time out at 10 seconds under load while a sibling hook runs at 30
column: complete
status: archived
created: 2026-10-06T21:26:01+0200
updated: 2026-10-07T07:01:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:01+0200
implementation-commits: [760a44d2]
---

# UserPromptSubmit hooks time out at 10 seconds under load while a sibling hook runs at 30

Source: GitHub issue Emasoft/ai-maestro-janitor#325 (opened 2026-10-01). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Under ordinary machine load two prompt-submit hooks timed out at 10 seconds and their output was discarded, while a sibling hook on the same event has a 30 second timeout. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:46+0200 — COMPLETE by main-agent@ai-maestro-janitor. resolved, evidence in STATE.

## STATE

2026-10-07 already fixed before this card was worked: commit 760a44d2 raised all three UserPromptSubmit hook timeouts to 60 s; first released in v3.7.0. GitHub issue 325 is closed. A session started on an older plugin version keeps that version's hooks until restarted (see TRDD-GLDLS7UM).

## Acceptance checklist

- [x] All three UserPromptSubmit hook timeouts are 60 s (commit 760a44d2, first released in v3.7.0); GitHub issue 325 closed.
