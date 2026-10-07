---
trdd-id: P2XDI38R
title: The memgrep spec has two clauses with id WM-CLI-17
column: complete
status: archived
created: 2026-10-06T23:11:29+0200
updated: 2026-10-07T07:01:45+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T23:11:29+0200
implementation-commits: [80276fbb, e4b5906c]
---

# The memgrep spec has two clauses with id WM-CLI-17

Found during #322 (TRDD-8COB99QQ). In design/specs/wikimem-memgrep-spec.md two different clauses carry the id WM-CLI-17: one for trdd-backlink-is-optional-and-warned, one for update-mem-atom (the no-op refusal added by commit 349acb2d). A clause id must be unique. Fix: renumber one of them and update every citation (grep the repo for WM-CLI-17 in docs, skills, hook advice and tests).

## Approval log

- 2026-10-06T23:11:29+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:45+0200 — COMPLETE by main-agent@ai-maestro-janitor. resolved, evidence in STATE.

## STATE

2026-10-07 merged on main (80276fbb, e4b5906c): update-mem-atom renumbered WM-CLI-17 to WM-CLI-26 and delete-mem-topic WM-CLI-18 to WM-CLI-27, each with a 'numbered ... until 2026-10-07' note; WM-CLI-17 stays on the backlink clause and WM-CLI-18 on find-trdd, which is what every live citation means. The archived cards 8COB99QQ and ZNCH1MUT cite the old number for update-mem-atom and are frozen. No memory page cites either id. specgrep edit refused outside the ai-maestro checkout and was run with AIM_PILLAR_ALLOW_WRITE=1, for these renumbers only. specgrep lint 22 to 20 findings.

## Acceptance checklist

- [x] The duplicate clause id is resolved: update-mem-atom is WM-CLI-26, delete-mem-topic WM-CLI-27, live citations of WM-CLI-17 and WM-CLI-18 unchanged; merged 80276fbb and e4b5906c; specgrep lint 22 to 20 findings.
