---
trdd-id: DD0M4QL7
title: The branch-protection baseline cannot be MAINTAINED after first creation — present-by-name masks stale-by-content
column: todo
created: 2026-08-18T20:14:25+0200
updated: 2026-08-18T20:14:25+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [ai-maestro TRDD-BRRJK57P @ 9562b2a4]
npt: []
eht: []
---

# Baseline freeze — gate 6 short-circuits on names, so content drift is never repaired

## Why (hub-verified P1, ledgered in ai-maestro TRDD-BRRJK57P commit 9562b2a4)

`scripts/guard/branch_protection_apply.py` (~:152) short-circuits on
`branch_protection_lib.baselines_present` (`:459-475`), which answers "do rulesets with the
baseline NAMES exist?" — never "do they still carry the baseline CONTENT?". So the baseline can
be CREATED once but never MAINTAINED: a repo whose ruleset was hand-loosened, or created by an
older janitor with different parameters, stays "converged" forever. This explains the fleet's
8-of-9 baseline staleness better than ordinary drift (the hub's re-scope, adopted as the
finding). The applier's payload SSOT is `branch_protection_lib.baseline_ruleset_payloads` —
comparison must run against THAT, never prose.

Related sequencing constraint from a maintainer-session finding: CPV's
`setup_branch_rules.py:807` PUTs a wrong-shape payload — fix or gate that BEFORE or WITH this
card, or the two writers fight (that fix lives in CPV's repo; file there per
how-to-fix-issues-of-other-projects if still unfixed when this card enters dev).

## What

1. Replace/augment the name-presence short-circuit with a CONTENT comparison against
   `baseline_ruleset_payloads` (normalize the GitHub API's response shape first — echoed
   payloads gain server-side defaults; compare on the fields the baseline pins, not the whole
   response).
2. **The load-bearing half is the TEST (hub's condition):** a repo PRESENT BY NAME but STALE BY
   CONTENT must REDDEN before any patch is trusted — write that failing test first, then fix.
3. Post-apply acceptance stands: a non-admin actor is still refused `deletion` /
   `non_fast_forward` after re-apply.
4. The converged path must not be SILENT: give the no-op ≡ healthy short-circuit one honest
   line or a findings-ledger row, so "no output" stops being ambiguous between "checked and
   converged" and "never checked".

## Acceptance

- [ ] failing-first test: name-present + content-stale ⇒ detector/applier reddens
- [ ] content comparison runs against `baseline_ruleset_payloads` (code SSOT), tolerant of
      server-added response fields
- [ ] non-admin still refused deletion/non_fast_forward after a repair apply (live check)
- [ ] converged short-circuit leaves one honest trace (log line or ledger row)

## Approval log
