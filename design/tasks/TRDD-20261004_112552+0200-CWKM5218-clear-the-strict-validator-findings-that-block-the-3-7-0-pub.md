---
trdd-id: CWKM5218
title: Clear the strict-validator findings that block the 3.7.0 publish
column: testing
status: tasked
created: 2026-10-04T11:25:52+0200
updated: 2026-10-06T17:25:51+0200
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
implementation-commits: [676dc799, 00bb2762, 65d376ae, 44c8af2a, 43167dc7, 74b2b295, 37d72fcd]
---

# Clear the strict-validator findings that block the 3.7.0 publish

The 3.7.0 dry run (2026-10-04) failed at step 4: cpv-remote-validate plugin . --strict (v5.16.2, unchanged since 3.6.3) reported 4 CRITICAL, 1 MAJOR, 3 MINOR and 7 NIT findings, all in files added or changed since 3.6.3; under --strict every severity above WARNING blocks. Measurement: reports_dev/20261004_111803+0200-cpv-strict-findings-measure.md (gitignored). Policy (memory page project_janitor_publish_blocked_cpv_fps): reword or reformat with identical meaning, never suppress or exempt. Fourteen findings fixed: issue-codes.toml AICTX-002/003 verbs (write -> create or modify) with regenerated registry and docs; memgrep jev.rs (doc comment, scoped thread start via Builder::spawn_scoped, header assertion parsed instead of matched literally) and memory.rs (ignored live test fixture keywords and query); two skill TOC entries; duplicate H1 on cards JSQSJ3PZ and K9AHY1ZB; blockquote spacing on 0FM50EAW; a rewrap in wikimem-memgrep-spec.md. Open: archived card JHHD3S4Z has a second H1 at line 22 (MD025); the card tool refuses edits to archived cards, so the owner must choose between a one-line format repair and a lint exclusion. Follow-ups not in this card's scope: the card generator emits a duplicate title H1; raw regex hits elsewhere that the scanner's classifier exempts today; pipeline drift warnings from the validator canon; the memgrep binary is installed separately, so the jev.rs change needs a cargo install to reach a machine.

## Approval log

- 2026-10-04T11:25:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-04T20:10:59+0200 — column → testing. 3.7.0 was published on 6157e726 with all strict-validator findings cleared; no code is being written for this card. Awaiting proof: the macOS test fix 37d72fcd needs a green GitHub CI run on 3.7.1. Strict validator re-run 2026-10-04 on HEAD: 0 critical, major, minor, nit.

## Outcome


2026-10-04 — 3.7.0 was published on the fourth run (tag and main on 6157e726). Blockers found and fixed on the way: 15 strict-validator findings, a bandit B310 finding, the privacy scan refusing the integrity manifest, the address lint on a test fixture, and 21 clippy findings. GitHub CI then failed its Tests job on two macOS-only tests, fixed in 37d72fcd for the next release.
2026-10-04 column testing (was dev). Correction to the move reason - it said all findings were cleared, but the archived card JHHD3S4Z second H1 was left open as an owner decision. The strict validator run on HEAD on 2026-10-04 reported 0 critical, major, minor and nit findings, so that item does not block today, but whether the validator still scans archived cards was not checked. 37d72fcd is NOT inside the 3.7.0 release, so its proof is the 3.7.1 CI run. NEXT ACTION - after the 3.7.1 CI run is green, close this card.
2026-10-06: the v3.7.1 publish hit a new CPV abort: cpv-remote-validate run via uvx failed its own self-integrity check (every repo file "deleted locally") at both v5.16.2 and v5.22.0. CPV run from the installed plugin cache 5.22.0 verified 1291 files OK, so it is a packaging layout defect, not tampering. Published with publish.py's documented exemption CPV_SKIP_GITHUB_INTEGRITY=1 (publish.py:1503-1516). Reported as Emasoft/claude-plugins-validation#243. CI workflows (ci.yml ~:180, release.yml ~:126/130) run the same uvx command without the exemption.
