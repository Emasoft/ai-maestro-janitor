---
trdd-id: CWKM5218
title: Clear the strict-validator findings that block the 3.7.0 publish
column: todo
status: tasked
created: 2026-10-04T11:25:52+0200
updated: 2026-10-07T04:44:14+0200
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
- 2026-10-07T02:38:35+0200 — column → todo. re-columned before 3.8.2: developable, not a live event

## Outcome


2026-10-04 — 3.7.0 was published on the fourth run (tag and main on 6157e726). Blockers found and fixed on the way: 15 strict-validator findings, a bandit B310 finding, the privacy scan refusing the integrity manifest, the address lint on a test fixture, and 21 clippy findings. GitHub CI then failed its Tests job on two macOS-only tests, fixed in 37d72fcd for the next release.
2026-10-04 column testing (was dev). Correction to the move reason - it said all findings were cleared, but the archived card JHHD3S4Z second H1 was left open as an owner decision. The strict validator run on HEAD on 2026-10-04 reported 0 critical, major, minor and nit findings, so that item does not block today, but whether the validator still scans archived cards was not checked. 37d72fcd is NOT inside the 3.7.0 release, so its proof is the 3.7.1 CI run. NEXT ACTION - after the 3.7.1 CI run is green, close this card.
2026-10-06: the v3.7.1 publish hit a new CPV abort: cpv-remote-validate run via uvx failed its own self-integrity check (every repo file "deleted locally") at both v5.16.2 and v5.22.0. CPV run from the installed plugin cache 5.22.0 verified 1291 files OK; the uvx v5.16.2 copy that ran the publish was not verified. The cause is UNKNOWN: the janitor CI Validate job runs the same uvx command, blocking, without any skip variable, and passed on 2026-10-06 with no [CPV integrity] line (CI run for commit 89d21dd8, v3.7.1); the uvx-layout hypothesis on #243 is therefore INFERRED and possibly wrong. v3.7.2 was also published with the exemption. Published with publish.py's documented exemption CPV_SKIP_GITHUB_INTEGRITY=1 (publish.py:1503-1516). Reported as Emasoft/claude-plugins-validation#243. CI workflows (ci.yml ~:180, release.yml ~:126/130) run the same uvx command without the exemption.

## STATE

2026-10-06: v3.7.2 and v3.7.3 were also published with CPV_SKIP_GITHUB_INTEGRITY=1 (three releases so far); the cause of the abort on this host is still unknown.
2026-10-06 NEXT ACTION: find why cpv-remote-validate under uvx aborts on its self-integrity check on this host but not in CI: add a diagnostic CI step that prints the uvx install path and the ~/.cache/cpv manifest names, or reproduce here with ~/.cache/cpv moved aside; or close this point if Emasoft/claude-plugins-validation#243 resolves it.
2026-10-06: v3.7.4 and v3.7.5 were also published with the integrity exemption (five releases so far).
2026-10-07: moved testing -> todo before 3.8.2: remaining work is developable, not a live event: find why cpv-remote-validate under uvx aborts on its self-integrity check on this host but not in CI (diagnostic CI step, or reproduce with ~/.cache/cpv moved aside); the 3.7.1 CI run that was awaited has long since happened.
2026-10-07: v3.8.2 was published with CPV_SKIP_GITHUB_INTEGRITY=1, the latest of at least six such releases (3.7.1-3.7.5 recorded; 3.8.0 and 3.8.1 not checked); run-1 evidence: of 3446 listed files, the 50 printed were all 'deleted locally', none 'differs' (3396 not printed).
2026-10-07 TIME BOMB: CPV says the CPV_ name is deprecated in favour of PLUGIN_SKIP_GITHUB_INTEGRITY and will be removed in a future major release; publish.py's bypass guard refuses every PLUGIN_SKIP_ variable, so once CPV drops the legacy name this host cannot publish until either the uvx integrity abort is fixed or publish.py exempts the new name.
2026-10-07 investigation (reports/board/20261007_042510+0200-tooling-problems.md, gitignored; facts copied here): the validator pinned at v5.16.2 in publish.py and both workflows reads PLUGIN_SKIP_GITHUB_INTEGRITY first and still honours CPV_SKIP_GITHUB_INTEGRITY with a deprecation notice; publish.py's bypass guard exempted only the old name and refused the new one at step 0. Fix in progress on a worktree branch: exempt the new name, refuse the old one, four tests for the guard, which had none. Believed cause of the 3446-file mismatch, from reading the validator's code only: run through uvx it takes the install directory as the plugin root, so every manifest file reads as deleted locally. STILL UNEXPLAINED: why CI passes the same command with no exemption. Do not publish with the new name until one validate run shows steps 0 and 4 pass.
2026-10-07: the exemption rename is merged on main (52eb054e, merge 328bfa30); its four guard tests pass on main. Not yet in a release.
2026-10-07 correction: the publish.py line reference 1503-1516 above is stale; the guard is now at about 1495-1520 of scripts/publish.py
