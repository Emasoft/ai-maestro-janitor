---
trdd-id: CWKM5218
title: Clear the strict-validator findings that block the 3.7.0 publish
column: dev
status: tasked
created: 2026-10-04T11:25:52+0200
updated: 2026-10-04T11:28:34+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-04T11:25:52+0200
implementation-commits: [676dc799, 00bb2762, 65d376ae]
---

# Clear the strict-validator findings that block the 3.7.0 publish

The 3.7.0 dry run (2026-10-04) failed at step 4: cpv-remote-validate plugin . --strict (v5.16.2, unchanged since 3.6.3) reported 4 CRITICAL, 1 MAJOR, 3 MINOR and 7 NIT findings, all in files added or changed since 3.6.3; under --strict every severity above WARNING blocks. Measurement: reports_dev/20261004_111803+0200-cpv-strict-findings-measure.md (gitignored). Policy (memory page project_janitor_publish_blocked_cpv_fps): reword or reformat with identical meaning, never suppress or exempt. Fourteen findings fixed: issue-codes.toml AICTX-002/003 verbs (write -> create or modify) with regenerated registry and docs; memgrep jev.rs (doc comment, scoped thread start via Builder::spawn_scoped, header assertion parsed instead of matched literally) and memory.rs (ignored live test fixture keywords and query); two skill TOC entries; duplicate H1 on cards JSQSJ3PZ and K9AHY1ZB; blockquote spacing on 0FM50EAW; a rewrap in wikimem-memgrep-spec.md. Open: archived card JHHD3S4Z has a second H1 at line 22 (MD025); the card tool refuses edits to archived cards, so the owner must choose between a one-line format repair and a lint exclusion. Follow-ups not in this card's scope: the card generator emits a duplicate title H1; raw regex hits elsewhere that the scanner's classifier exempts today; pipeline drift warnings from the validator canon; the memgrep binary is installed separately, so the jev.rs change needs a cargo install to reach a machine.

## Approval log

- 2026-10-04T11:25:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
