---
trdd-id: DD0M4QL7
title: The branch-protection baseline cannot be MAINTAINED after first creation — present-by-name masks stale-by-content
column: complete
created: 2026-08-18T20:14:25+0200
updated: 2026-08-21T03:55:00+0200
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

- [x] failing-first test: 7 tests written FIRST against the absent function, all 7 watched RED,
      then `ruleset_content_drift` implemented → 7 green (`tests/test_branch_protection_content.py`)
- [x] content comparison runs against `baseline_ruleset_payloads` (code SSOT) via the same
      inputs the apply path uses (`detect_required_status_checks` + `require_pull_request_for`);
      subset-shaped so server-added response fields can never false-positive; the documented
      `required_status_checks` cwd-dependence is carved out (a live checks rule the foreign-cwd
      payload omits is stricter, never stale)
- [x] non-admin still refused deletion/non_fast_forward after a repair apply (live check) —
      **CLOSED 2026-08-21. Both halves proven; my own "still unobserved" caveat below was
      WRONG, and the correction came from the ai-maestro hub reading MY log.**

      THE REPAIR APPLY HAPPENED, unattended, in `.janitor/logs/branch-protection-apply.log`:

      ```text
      [2026-08-20T08:21:53+0200] [s:d30bf250] content drift on Emasoft/ai-maestro-janitor:
         baseline-pr-and-checks: rule required_status_checks parameters loosened/changed; …
      2026-08-20T08:21:58+0200  OK  Emasoft/ai-maestro-janitor  main
         baseline-history-protect=updated id=17286452; baseline-pr-and-checks=updated …
      ```

      Five seconds apart, same session. Those two lines are emitted by NOTHING ELSE:
      `branch_protection_apply.py:185` (the gate-6 content-drift fallthrough) and
      `_audit_append` at `:233` (only reached after a successful apply). A manual `gh api`
      session cannot produce that pair. The applied payload in the log already carries
      `bypass_actors: [{actor_id: 5, RepositoryRole, always}]`, i.e. the post-2026-08-13
      ratified shape. Same pattern independently in ai-maestro-plugin (08:38:18 → 08:38:29)
      and ai-maestro-maintainer-agent (2026-08-19 20:28:29 → 20:28:34).

      NON-ADMIN STILL REFUSED, read live from the API afterwards: `baseline-history-protect`
      `enforcement: active`, rules `["deletion", "non_fast_forward"]`, sole bypass actor
      RepositoryRole 5. And the `converged: …` lines at 16:11:24 and 02:40:47 are the fix's
      own new trace doing its job — the silent no-op this card is about is gone.

      **MY ERROR, recorded because it is the more useful half.** I asserted unattended repair
      was unobserved, reasoning from the hub's report that THEY applied payloads on 08-20 —
      and never opened my own applier's log to check whether it had also run. It had, hours
      earlier. Being conservative about a claim is not the same as verifying it: I refused to
      tick a box on someone else's evidence, then failed to look for my own. `#282`'s
      "the ruling reached 0/9 repos" was true of the other 8 and NOT of this repo, which
      self-healed at 08:21.

      SUPERSEDED — do NOT carry forward: the paragraph below, which claims this is open.
      The old text said "the RUNNING plugin is cached v3.3.16 whose gate 6 still
      short-circuits on names". That is no longer true: 3.3.26 is installed and carries
      `baselines_content_current` in both the guard and the lib, and it was run LIVE against
      the API — `names-present: True`, `content-current: True`. The gate fix is verified.

      The SAFETY half is also verified live (read-only, `gh api …/rulesets/<id>`):
      `baseline-history-protect` is `enforcement: active`, rules `["deletion",
      "non_fast_forward"]`, and its ONLY bypass actor is `{actor_id: 5, RepositoryRole,
      always}` — admin per the 2026-08-13 Tier-3 ruling, `required_linear_history` correctly
      absent per 2026-08-08. **A non-admin IS still refused deletion and force-push.**

      What remains unproven is PROVENANCE, and it is deliberately not ticked on the evidence
      above: this repo is content-current because the **hub applied the payloads directly on
      2026-08-20**, not because the janitor's own repair detected drift and fixed it. So the
      end-to-end claim — "the janitor repairs a drifted repo unattended" — has still never
      been observed. Ticking this box now would record the hub's manual apply as the
      janitor's autonomous one, which is the specific thing this card exists to distrust.
- [x] converged short-circuit leaves one honest trace — one `state.log_line` per converged
      pass; drift logs its named reasons before falling through to the exempt re-apply

## ⏵ STATE — 2026-08-18 21:30: detection VERIFIED LIVE on this very repo (3 real drifts)

`baselines_content_current("Emasoft/ai-maestro-janitor", "main", ".")` from the repo tree
found, and manual `gh api` fetches CONFIRMED, three genuine drifts on our own repo — the
card's thesis demonstrated on the first live run:
1. `baseline-history-protect` live `bypass_actors: []` — predates the USER's 2026-08-13
   Tier-3 ruling (admin bypass); the ruling changed the SSOT and no repo was ever re-applied.
2. `baseline-pr-and-checks` live checks list is missing the `Tests` context — PRs are not
   gated on the test job.
3. live carries a `pull_request` rule while `require_pull_request_for(slug)` is False — the
   ratified per-slug state is PR-less (same 2026-08-13 ruling); a repair apply removes it.
The repair itself is the EXEMPT idempotent re-apply and runs autonomously once the released
plugin carries this change. NEXT ACTION: after the next publish + fleet update, confirm the
repair fired (audit log), then run the non-admin refusal live check and tick the last box.

## Approval log
