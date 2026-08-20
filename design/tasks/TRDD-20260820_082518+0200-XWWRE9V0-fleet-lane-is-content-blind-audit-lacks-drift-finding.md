---
trdd-id: XWWRE9V0
title: The fleet lane is content-blind — the audit has no ruleset-content-drift finding, so baseline changes never propagate finding-driven
column: todo
created: 2026-08-20T08:25:18+0200
updated: 2026-08-20T08:25:18+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [janitor#282, TRDD-DD0M4QL7]
npt: [KDLJ04AM]
eht: []
---

# janitor#282's residue — the audit lane cannot see content drift (VERIFIED, claim refined)

## Verified first-hand 2026-08-20 08:20 — the hub's #282 claim, corrected

The hub reported `baselines_present` name-only ⇒ payloads frozen forever, 0/24 fleet
propagation of the 2026-08-13 ruling. Verification against HEAD refines that:

- `baselines_present` IS name-only — by design; but the GUARD path already has the content
  half: `scripts/guard/branch_protection_apply.py:155-163` (gate 6) checks name-present AND
  `baselines_content_current`, content drift falls through to the PATCH — TRDD-DD0M4QL7,
  **shipped in v3.3.17** with tests (`tests/test_branch_protection_content.py`, including
  loosened-parameter/missing-rule/disabled-enforcement drift cases — the "fails on
  name-present/content-stale" ask is already covered FOR THE GUARD LANE). This morning's
  fire on this repo PATCHED live ("baseline-history-protect=updated"), proving it.
- The REAL residue is the FLEET lane: `fleet-github-config` detector → `github_config_audit`
  findings → `/janitor-github-config-fix`. The AUDIT checks rule-type PRESENCE only — a
  name-present/content-stale repo yields NO finding, so the fix path never fires, so a
  ruling propagates to the fleet only when someone runs the guard per-repo (opt-in,
  per-project) or applies by hand (what the hub did for 24 repos). That is the measured
  0/24, explained.

## What

1. New audit finding class (e.g. `BASELINE_CONTENT_DRIFT`) built on the EXISTING
   `branch_protection_lib.ruleset_content_drift` (one SSOT — DD0M4QL7's comparator, not a
   new one), emitted per repo whose baseline-named rulesets drift from the ratified
   payloads. Respect the DD0M4QL7 asymmetry (live checks-rule the payload omits ≠ drift).
2. Map it FIXABLE in `github_config_fix.py` — the fix is the EXEMPT idempotent re-apply
   (manager-approval-defaults §F).
3. NPT: KDLJ04AM first — adding a content finding on top of a false-positive-emitting
   audit would auto-fix repos back into the pre-ruling shape (the #283 sharp edge).
4. Hub's test ask, fleet-lane version: a name-present/content-stale repo must produce the
   drift finding (fails pre-fix); a converged repo must stay silent.
5. Reply on janitor#282 with this split (guard lane fixed in 3.3.17; fleet lane = this card).

## Acceptance

- [ ] name-present/content-stale ⇒ BASELINE_CONTENT_DRIFT (test fails pre-fix); converged ⇒ silent
- [ ] fix path re-applies via the ratified SSOT payloads; solo-owner conditionality respected
- [ ] grep-proven: ONE comparator (`ruleset_content_drift`) across guard + audit lanes
- [ ] pytest, ruff, mypy clean; janitor#282 answered with the lane split

## Approval log
