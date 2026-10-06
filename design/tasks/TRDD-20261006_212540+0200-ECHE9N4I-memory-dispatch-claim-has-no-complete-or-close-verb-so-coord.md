---
trdd-id: ECHE9N4I
title: memory_dispatch claim has no complete or close verb so coordinators move state files by hand
column: todo
status: tasked
created: 2026-10-06T21:25:40+0200
updated: 2026-10-06T21:25:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:40+0200
---

# memory_dispatch claim has no complete or close verb so coordinators move state files by hand

Source: GitHub issue Emasoft/ai-maestro-janitor#311 (opened 2026-09-25). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: memory_dispatch_claim.py creates a claim file but no verb closes it. A coordinator that correctly abstains is left holding a live claim and improvises by renaming files and patching status fields. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:40+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
