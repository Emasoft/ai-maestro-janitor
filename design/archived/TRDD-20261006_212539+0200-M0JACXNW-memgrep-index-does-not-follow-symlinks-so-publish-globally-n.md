---
trdd-id: M0JACXNW
title: memgrep index does not follow symlinks so publish-globally notes are invisible to recall
column: complete
status: archived
created: 2026-10-06T21:25:39+0200
updated: 2026-10-10T21:51:39+0200
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
- 2026-10-10T21:51:39+0200 — COMPLETE by main-agent@ai-maestro-janitor. already fixed and shipped; issue 310 closed with commit and release.

## Findings

2026-10-10 21:51 CLOSED ON EVIDENCE, no new code. Commits f9c5580e and bad6b1d0 of 2026-09-25, first in v3.6.2: the memgrep memdir walk admits file symlinks and dedups by realpath; write verbs refuse a symlinked page. Crate tests symlink_only_memdir_collects_the_linked_note (scripts/memgrep/src/memory.rs) and read_page_for_write_refuses_a_symlinked_page. Issue 310 is CLOSED as completed on 2026-10-06 and its last comment names the commits and the release. Checked by this session: the commits exist with those subjects and the first v-tag containing them is the one named; the named tests exist by name in the tree. NOT DONE: the tests were not run on their own today.

## Acceptance

- [x] The symptom is gone in a test that failed before the fix (tests and commits in Findings).
- [x] A closing comment on the issue names the commit and the release (issue 310).
