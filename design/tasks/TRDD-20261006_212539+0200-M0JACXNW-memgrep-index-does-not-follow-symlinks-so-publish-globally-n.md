---
trdd-id: M0JACXNW
title: memgrep index does not follow symlinks so publish-globally notes are invisible to recall
column: todo
status: tasked
created: 2026-10-06T21:25:39+0200
updated: 2026-10-06T21:25:39+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:39+0200
---

# memgrep index does not follow symlinks so publish-globally notes are invisible to recall

Source: GitHub issue Emasoft/ai-maestro-janitor#310 (opened 2026-09-25). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: A memory directory holding only a symlink to a real note is invisible to memgrep recall, although the publish-globally write path creates exactly such symlinks in the user memory directory. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:39+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
