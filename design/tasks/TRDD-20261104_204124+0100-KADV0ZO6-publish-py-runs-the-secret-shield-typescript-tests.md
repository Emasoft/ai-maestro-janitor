---
trdd-id: KADV0ZO6
title: publish.py runs the secret shield TypeScript tests
column: blocked
status: tasked
created: 2026-11-04T20:41:24+0100
updated: 2026-11-14T07:49:05+0100
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
approval-datetime: 2026-11-04T20:41:24+0100
npt: []
eht: [OD5Z90YL]
blocked-by: [OD5Z90YL]
unblock-when: [trdd:OD5Z90YL terminal, decision:kadv0zo6-first-real-publish-run]
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show OD5Z90YL | cut -f3 | grep -cE '^(complete|published|live)$'
blocker-holds-if: not-match:^1$
---

# publish.py runs the secret shield TypeScript tests

The secret shield's TypeScript tests (hooks/secret-shield/tests) run in no automated gate; TRDD-TEP6F3A3 records this as a prerequisite of wiring the mod, and this card blocks the wiring card TRDD-2V7OAUPE. Where the gate runs and how is decided under Decision 2026-11-04 below. Found during TRDD-TEP6F3A3.

## Approval log

- 2026-11-04T20:41:24+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-14T04:26:14+0100 — column → blocked by main-agent@ai-maestro-janitor. Done-when 1 and liveness met, 2 met in code; waits on OD5Z90YL (ReDoS harness) and the first real publish.py run

## Decision 2026-11-04

- 2026-11-04 main-agent: the gate is a publish.py stage that runs before stage_bump, like the other pre-bump checks, and fails closed when the claude CLI is missing or cannot run the tests, as pyright does here. A CI job may be added beside it, never instead of it: CI runs after publish.py has pushed the tag, so it cannot block the publish. Before writing the stage, record the exact claude plugin test invocation the workers ran on the shield. That claude plugin test runs the tests in Claude Code's bundled runtime is inferred from its passing on (?i:...) groups and lookbehinds; the bundled Bun cannot be invoked directly to confirm it. Before the gate goes live, the shield's timing tests with absolute limits (for example under 1 s) become growth-ratio checks, because this host's load has stayed above its core count (TRDD-Q6LPJTPO), so an absolute limit in a blocking gate would flake.

## Done when

- The exact claude plugin test invocation that runs hooks/secret-shield/tests is recorded on this card.
- A publish.py stage before stage_bump runs that invocation and exits non-zero, blocking the publish, both when a shield test fails and when the claude CLI is missing or cannot run; each case is shown by a real run, including one where publish.py itself runs inside a Claude Code session.
- The publish stage runs the ReDoS harness of TRDD-OD5Z90YL over every regex in hooks/secret-shield, and that card's Done-when is met.
- [x] the publish gate stage also runs hooks/liveness/tests/liveness.test.ts (scope change 2026-11-13)

## Scope change 2026-11-13

2026-11-13: scope widened - hooks/liveness/tests/liveness.test.ts (TRDD-R9NLNV3W, commit 3a73c1b9) is a second TypeScript test suite that no CI or publish gate runs; the gate stage added here must run both.

## Notes

- 2026-11-14 main-agent (worker run): invocation recorded. `python scripts/run_secret_shield_tests.py [--mod secret-shield|liveness]` builds a temp dir holding the repo .claude-plugin/plugin.json, hooks/hooks.json = {"modules": ["./<mod>/register.ts"]} and a copy of hooks/<mod>, then runs `claude plugin test <tmpdir>` with cwd = tmpdir, in its own process group, 300 s kill. Measured here: secret-shield 841 pass 0 fail (4 files), liveness 15 pass 0 fail (1 file, hooks/liveness/tests/liveness.test.ts). Hand assembly for liveness: mkdir -p T/.claude-plugin T/hooks; cp .claude-plugin/plugin.json T/.claude-plugin/; write {"modules": ["./liveness/register.ts"]} to T/hooks/hooks.json; cp -R hooks/liveness T/hooks/liveness; claude plugin test T (exit 0, "15 pass / 0 fail / Ran 15 tests across 1 file").
- 2026-11-14 stage position: the stage landed in c0da4a21 (TRDD-3GP0D06D) as publish.py step 2b inside stage_tests and as gate G3b in run_gate; this change generalizes it to both mods (run_mod_tests loops over _MOD_TESTS = secret-shield, liveness; the script gained --mod with a per-mod floor, liveness 15). In main() the order is stage_bypass_guard, stage_check_clean, stage_lint, stage_tests (2b runs first inside it, before pytest), stage_validate, stage_ci_preflight, stage_marketplace_registration, stage_consistency, stage_bump, so 2b runs before stage_bump. Fail-closed branches kept: no claude, failed or timed-out run, unparseable counts, a test file missing from the output, count below the floor.
- 2026-11-14 Done-when status. (1) invocation recorded: met, above. (2) stage before stage_bump that blocks on a failing test or a missing claude: met in code; shown by real runs of the script (tests/test_run_secret_shield_tests.py: missing claude on PATH, an injected failing shield test, an injected failing liveness test, timeout, floor, no test files, all passed), and run_mod_tests(root) was called directly and returned 0. OPEN: no full publish.py run was made (a bump is not allowed here), so there is no real run of publish.py itself, and none of publish.py itself inside a Claude Code session. The script and pytest runs above did execute inside this Claude Code session tool calls (claude plugin test was a child of a Bash tool call), but that is the script run from a session, not publish.py run from a session, and this note does not count it as the item. (3) ReDoS harness: OPEN, TRDD-OD5Z90YL is in column todo. (4) liveness checkbox: met, ticked. CI is not changed. The card was not moved.
- 2026-11-14 — This card and TRDD-3GP0D06D overlapped; 3GP0D06D (c0da4a21) delivered the publish stage, this card added the liveness suite. The open publish.py-run item can only be met at the next owner-approved publish.
2026-11-14: before the first real publish run, check whether CPV flags the known-quadratic regex fixture hooks/secret-shield/tests/load/old-quadratic.ts (committed in bbe8bbf4, shipped with the plugin, used only by the TRDD-OD5Z90YL load harness); a CPV finding there must be resolved without deleting the fixture's purpose.
