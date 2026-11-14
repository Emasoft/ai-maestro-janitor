---
trdd-id: 3GP0D06D
title: secret-shield tests run in the release gate and CI
column: human_review
status: tasked
created: 2026-11-04T01:26:43+0100
updated: 2026-11-14T08:03:27+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T01:26:43+0100
eht: [Z41A13XV]
implementation-commits: [c0da4a21]
---

# secret-shield tests run in the release gate and CI

## Problem
The secret-shield mod's tests (hooks/secret-shield/tests, run through the mods test kit) are run today only by a scratch runner script outside the repo. No committed runner exists. A grep found no reference to secret-shield in scripts/, tests/ or .github/ apart from the wiring-gate test, so publish.py and CI most likely do not run them; confirm this by reading publish.py's gate step first. If so, a release can ship a shield that fails its own tests, and every 'no behaviour change' step of TRDD-Q6LPJTPO rests on a worker happening to run the scratch script.
## Do
Commit a runner for the mod tests (assembling the mod the way the scratch script does), add it to the publish gate next to pytest, ruff, mypy and pyright, and run it in CI. It fails closed when the runtime it needs is missing.
Open question: can a CI runner get the mods test kit (claude-code/testing) and its runtime without interaction? If it cannot, the gate runs locally in publish.py only, and CI reports the missing step as a coverage gap rather than going permanently red.
## Done when
A deliberate failing shield test makes the gate step fail when that step is run on its own, without publishing, and makes CI fail on a feature branch.
Found during TRDD-Q6LPJTPO (review of commit baeecd80).
- The runner names hooks/secret-shield/tests explicitly and never runs a root-level bun test: _corpus_dev/ holds about 130 cloned untrusted repos with their own *.test.ts and *.spec.* files, which a root discovery would run (review finding, 2026-11-04).

## Approval log

- 2026-11-04T01:26:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-14T04:18:49+0100 — column → human_review by main-agent@ai-maestro-janitor. local half landed in c0da4a21; CI half and claude dependency await two owner decisions

## Notes

- 2026-11-14 — Local half built: scripts/run_secret_shield_tests.py assembles a temp dir (repo plugin.json + hooks.json holding only the modules entry + a copy of hooks/secret-shield), runs claude plugin test in its own session, and fails closed (no claude, non-zero exit, timeout, unparseable count, count below the 800 floor, any *.test.ts / *.test.tsx of the copy with no `<path>:` header line in the output). The step runs BEFORE pytest: 2b in stage_tests ([2b/11]) and G3b in run_gate (after G3 validate, before G4); _PUSH_TIMEOUT_SEC now includes its bound. The Done-when local half (a deliberate failing shield test fails the step on its own, without publishing) is proven by tests/test_run_secret_shield_tests.py::test_a_deliberately_failing_shield_test_fails_the_script. The CI half is NOT done: ci.yml runs only on main, pull requests and merge_group, has no claude install step, and proving it needs a pushed feature branch — owner decision below.
- 2026-11-14 — Observed once under host load (loadavg ~45): patterns.test.ts:661 (linear(small.ms, big.ms) ratio assert, line 664) failed inside the pytest run; three reruns passed. A timing-ratio assertion can therefore block the new gate step on a loaded host.
- 2026-11-14 — Review fixes: the shield step now runs BEFORE pytest (so the load-sensitive timing assert is less exposed). The script now also checks that every *.test.ts / *.test.tsx of the copied tests/ has a header line in the output of claude plugin test (a file the run did not execute fails it). Releases and the pre-push gate now depend on the installed, unpinned Claude Code (claude): a change in its output format or test engine can block a publish. ANSI colour codes in claude's output (FORCE_COLOR or a changed default) would make every header miss; that fails closed, not open. This card cannot close until the EHT TRDD-Z41A13XV (make the patterns.test.ts:661 timing-ratio assert load-robust) is terminal.
- 2026-11-14 — Landed in c0da4a21. The Done-when local half is proven at the script level (scripts/run_secret_shield_tests.py is the gate step; publish.py's run_shield_tests only adds the outer timeout and the BLOCKED line). The real claude plugin test output format is pinned only by tests that skip without claude, so CI does not check it. Moved to human_review: the CI half and the claude dependency wait on decision:ci-claude-install and decision:release-requires-claude; the card cannot reach complete until TRDD-Z41A13XV is terminal.
- 2026-11-14 — publish.py's run_shield_tests was renamed run_mod_tests and now loops over secret-shield and liveness (TRDD-KADV0ZO6).
2026-11-14: TRDD-LAUPB305 tracks an intermittent gate failure (claude plugin test exited 0, output cut at line 525, counts unparsable; a re-run passed 841/0). The gate fails closed, so it can block a release; it must not be loosened to pass.

## Owner decisions open

- decision:ci-claude-install — run the shield tests in CI (needs claude on the runner and a push to prove) or accept the local gate only.
- decision:release-requires-claude — publish and the pre-push gate now hard-require claude and gate on the installed, unpinned Claude Code version; accept, or pin a version.
- 2026-11-14: the acceptance criterion of this card's EHT TRDD-Z41A13XV changed while this card sits in human_review. Old: the ratio assert passes 20 runs at load 45 or more. New: it, or its increment-1b replacement, passes 20 probes of the real module while 35 CPU-only workers run under the TRDD-OD5Z90YL D8 harness. Reason: load average lags and is moved by other sessions; contention is what the check must survive. Main-agent ruling under TRDD-S6GX1DHN; veto it here if the old criterion must stand.
