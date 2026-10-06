---
trdd-id: V13M5YY1
title: Wikimem page shipped with duplicated sections and validate and lint cannot see body duplication
column: complete
status: archived
created: 2026-10-06T21:25:47+0200
updated: 2026-10-07T00:25:04+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:47+0200
implementation-commits: [00e80ac2, 6f45acf8]
---

# Wikimem page shipped with duplicated sections and validate and lint cannot see body duplication

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #315 closed https://github.com/Emasoft/ai-maestro-janitor/issues/315#issuecomment-6025973258. Landed on main as 00e80ac2,6f45acf8.
NEXT ACTION: move to complete once v3.8.1 is released and CI is green. Ships in v3.8.1.


Source: GitHub issue Emasoft/ai-maestro-janitor#315 (opened 2026-09-28). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: A project wikimem page carried two full copies of two sections. Neither validate nor lint detects duplicated body sections, and a hand repair left part of the duplicate in place. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.
Note: the memgrep crate version stayed 0.2.0 although validate's output gained WARN lines in v3.8.1 (additive; exit code unchanged).

## Approval log

- 2026-10-06T21:25:47+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:20+0200 — column → testing by main-agent@ai-maestro-janitor.
- 2026-10-07T00:25:04+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.1; acceptance items proven; self-approved by this standalone session.





## Acceptance

- [x] lint reports a section pasted twice (WMPAGE-012, WARN). Proof: 00e80ac2, 6f45acf8; scripts/memgrep/src/memory.rs::verbatim_duplicate_section_is_flagged_but_look_alikes_are_not; tests/test_memory_lint_gate_coverage.py page-duplicated-section row.
- [x] validate also reports a pasted-twice section (non-blocking WARN, exit code unchanged). Proof: 88f6b1f8; spec WM-CLI-05; memgrep validate prints one WARN line per section pasted twice (same check as lint WMPAGE-012).
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/315#issuecomment-6025973258
