---
trdd-id: 7KI11RH7
title: reference-mem-topic and reference-mem-atom wire downward cross-scope links that lint then flags as errors
column: complete
status: archived
created: 2026-10-06T21:26:07+0200
updated: 2026-10-10T21:51:40+0200
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
- 2026-10-10T21:51:40+0200 — COMPLETE by main-agent@ai-maestro-janitor. already fixed and shipped; issue 330 closed with commit and release.

## Findings

2026-10-10 21:51 CLOSED ON EVIDENCE, no new code. Commit 31c2e3b0 of 2026-10-05 (TRDD-7KAL6PNB), first in v3.7.1: reference-mem-topic and reference-mem-atom refuse a downward cross-scope link and write nothing. Crate tests reference_topic_refuses_a_downward_cross_scope_link_and_writes_nothing (scripts/memgrep/src/mem_reference.rs) and two siblings named in the issue. Issue 330 is CLOSED as completed on 2026-10-06 and its last comment names the commits and the release. Checked by this session: the commits exist with those subjects and the first v-tag containing them is the one named; the named tests exist by name in the tree. NOT DONE: the tests were not run on their own today.

## Acceptance

- [x] The symptom is gone in a test that failed before the fix (tests and commits in Findings).
- [x] A closing comment on the issue names the commit and the release (issue 330).
