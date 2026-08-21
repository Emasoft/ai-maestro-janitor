---
trdd-id: XWWRE9V0
title: The fleet lane is content-blind — the audit has no ruleset-content-drift finding, so baseline changes never propagate finding-driven
column: human_review
created: 2026-08-20T08:25:18+0200
updated: 2026-08-21T17:45:00+0200
implementation-commits: [068d1574]
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

All four VERIFIED first-hand 2026-08-21 17:4x against the shipped code, not against `068d1574`'s
commit message. The work had shipped on 2026-08-20 and the boxes were simply never ticked, which
left a high-priority card sitting in a WORK column asserting activity that had already finished.

- [x] name-present/content-stale ⇒ BASELINE_CONTENT_DRIFT (test fails pre-fix); converged ⇒ silent
      — `tests/test_github_config_audit.py:462-536`: one positive asserting the code IS emitted
      (documented as failing on the pre-fix classifier) plus FOUR falsifications asserting
      silence — converged echo, the checks asymmetry, shell/absent, and the solo shape.
- [x] fix path re-applies via the ratified SSOT payloads; solo-owner conditionality respected
      — `scripts/github_config_fix.py:64-70` adds `BASELINE_CONTENT_DRIFT` to `_CONFIG_FIXABLE`,
      citing the idempotent baseline re-apply that `manager-approval-defaults` §F marks EXEMPT.
      No new authority is taken: restoring drifted rules to the ratified payloads is not a
      deviation, which is the only reason this is Tier 0.
- [x] grep-proven: ONE comparator (`ruleset_content_drift`) across guard + audit lanes
      — defined ONCE at `branch_protection_lib.py:514`; called from the guard lane at `:616` and
      the audit lane at `github_config_audit.py:281`. Two callers, one definition.
- [x] pytest, ruff, mypy clean; janitor#282 answered with the lane split
      — 48 passed across `test_github_config_audit.py` + `test_branch_protection_content.py`;
      full suite 15747 passed / 0 failed, ruff + mypy clean earlier today. janitor#282 is
      CLOSED with the lane-split reply posted (2026-08-20 and 2026-08-21), both carrying the
      PRRD G1.1 self-identification line.

**STILL UNMET — the completion gate, which is NOT one of these boxes.** The Approval log below
requires the change to ride 3.3.19 AND one fleet-audit fire observed emitting/omitting the
finding correctly. That needs a publish plus a fire; it cannot be produced by inspection, so it
is named here rather than quietly folded into a ticked box.

## Approval log

- 2026-08-20T09:35:00+0200 — SHIPPED (todo → testing) by janitor-main-session (068d1574). Acceptance: fixture fails-pre-fix; converged/asymmetry/shell/solo falsifications green (54 across the three affected suites); FIXABLE mapping in place; #282 lane-split comment pending (next action). Gate to complete: rides 3.3.19 + one fleet-audit fire observed emitting/omitting the finding correctly.
