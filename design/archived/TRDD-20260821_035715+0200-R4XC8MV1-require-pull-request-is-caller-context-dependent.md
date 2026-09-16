---
trdd-id: R4XC8MV1
title: require_pull_request_for is caller-context dependent so two appliers flip-flop the same ruleset
column: complete
implementation-commits: [1eeb3fed, 81387b7b]
created: 2026-08-21T03:57:15+0200
updated: 2026-08-22T11:10:59+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [TRDD-DD0M4QL7, ai-maestro TRDD-88LDC7E0]
npt: []
eht: []
---

# The PR predicate answers per-CALLER, not per-REPO

## Measured 2026-08-21 (found by the ai-maestro hub's fleet census, confirmed here first-hand)

`branch_protection_lib.require_pull_request_for(slug)` decides whether the baseline emits the
`pull_request` rule. Its FIRST branch is:

    if harness_backend.backend() == harness_backend.BACKEND_AIMAESTRO: return True

and `backend()` -> `is_harness_session()` -> `state.in_ai_maestro_agent_env()`, which reads the
**calling process's ENV** (`AIMAESTRO_AGENT` / `THIS_IS_AIMAESTRO`, fallback `AMP_AGENT_ID` /
`AID_AUTH`). It consults nothing about the repo and nothing about server liveness.

**So the predicate is a function of (repo, CALLER), and the caller is not part of the ratified
baseline.** Two appliers are then simultaneously correct:

| caller | predicate | writes |
|---|---|---|
| hub applier, inside a harness agent | True | `pull_request` present |
| janitor applier, standalone session/daemon | False | `pull_request` removed |

Measured live from a standalone session (backend `standalone`): False for
`Emasoft/ai-maestro-janitor`, `Emasoft/ai-maestro`, `Emasoft/claude-plugins-validation`,
`Emasoft/agent-identity` — all Emasoft-owned, so the second branch (`not is_owned_by`) is False too.

**Why this is worse than a payload disagreement.** Fleet census 2026-08-21: 3 repos repaired by
this applier carry `required_status_checks` only; 6 still carry the hub's uniform shape. Making
the two appliers' PAYLOADS agree does NOT fix it — the same applier flips against itself
depending on where it is invoked from, and each writer's own post-condition reports success, so
the oscillation is invisible to both. This is the a-green-gate-over-an-oscillating-resource shape.

## Still live — re-measured 2026-08-21 08:25 (6-repo sample, read-only `gh api`)

The split is not historical; the two appliers are still fighting. `baseline-pr-and-checks`
rule sets, read live:

| repo | rules present | last writer implied |
|---|---|---|
| `ai-maestro-janitor` | `required_status_checks` | janitor applier (predicate False) |
| `ai-maestro-maintainer-agent` | `required_status_checks` | janitor applier (predicate False) |
| `ai-maestro` | `pull_request`, `required_status_checks` | hub applier (predicate True) |
| `claude-plugins-validation` | `pull_request`, `required_status_checks` | hub applier (predicate True) |
| `ai-maestro-plugins` | `pull_request` | hub applier |
| `agent-identity` | `pull_request` | hub applier |

**A 6-of-9 SAMPLE, not a census** — I queried six repos, so do not quote this as a fleet total;
the earlier 3/6 census figure came from the hub and is not contradicted by this.

Two things this adds beyond the original finding. First, it is **direct per-repo evidence of the
predicate's two answers coexisting on one fleet at one instant**, which is stronger than
inferring the flip-flop from an audit log. Second, `ai-maestro-plugins` and `agent-identity`
carry `pull_request` with NO `required_status_checks` — a THIRD shape, and an expected one
rather than a fourth bug: the baseline omits `required_status_checks` entirely when no CI job is
detectable (GitHub 422s an empty list), and that detection is itself cwd-dependent. Worth
naming so a reader does not count it as more oscillation than there is.

## What

1. Decide the authority explicitly: for a FLEET-WIDE apply the evaluation context must be PINNED,
   not inherited from whichever process happens to run it. Options — (a) evaluate per-repo from
   that repo's own governance state rather than the caller's env; (b) an explicit
   `--assume-harness/--assume-standalone` that the fleet path must pass; (c) make harness-ness a
   property recorded per repo. (a) or (c) is likely right; the caller's env is the accident.
2. Whatever is chosen, the predicate must be able to answer the same for the same repo from
   BOTH callers, or the flip-flop survives the fix.
3. Tell the hub the verdict — their applier is downstream of this predicate and they asked to be
   told rather than fixed for (their message 2026-08-21).

## ⏵ ANALYSIS 2026-08-21 11:18 — the option space is narrower than the card assumed, and one
## seemingly-obvious fix is a TRAP

Read the predicate and the surrounding module first-hand. Four findings, all decision-relevant.

**1. Fixing this is CONFORMANCE, not a baseline deviation — so `approval-tier: 0` holds.** The
ratified baseline text in `manager-approval-defaults.md` §F already says the `pull_request` rule
"is emitted only where a PR reviews anything — `require_pull_request_for(slug)` in the code SSOT
decides **per repo**". The current implementation decides per CALLER, which CONTRADICTS the
ratified text. Making it per-repo implements the ruling; it does not change it. (Worth stating
because a reader could reasonably classify any ruleset-shaping change as Tier 2.)

**2. Branch 2 is ALREADY per-repo.** `not cpi.is_owned_by(slug, login)` consults the repo. Only
branch 1 — `harness_backend.backend() == BACKEND_AIMAESTRO`, which resolves to
`state.in_ai_maestro_agent_env()` reading the CALLING PROCESS's env — is the accident. The fix is
confined to that one branch.

**3. There is NO per-repo registry to hang option (c) on.** Grepped: no fleet/repo registry
exists anywhere in `scripts/lib`. Option (c) means INVENTING a governance source, which is a
bigger decision than this card's title suggests.

**4. `harness_backend.server_is_alive()` looks like the clean fix and IS A TRAP — REJECTED.** It
is tempting because it already exists, needs no registry, and is caller-INDEPENDENT: both
appliers on one host read the same liveness file and would agree, satisfying acceptance box 1 as
literally written. **Reject it anyway.** It converts a CALLER-dependent oscillation into a
TIME-dependent one: a repo's ruleset would change shape according to whether the ai-maestro
server happened to be up when the applier ran. That is strictly worse — same invisible flip-flop,
now triggered by something nobody is looking at, and it would still pass box 1's test while
violating the card's actual intent. Recording the rejection so the next reader does not re-derive
it and ship it.

**Consequently the real choice is (a) with a per-repo governance SOURCE, and the open question is
what that source IS** — a marker in the repo read over `gh api` (deterministic, but a network
failure re-introduces per-caller disagreement transiently), or a registry that must be created
and maintained. Both are governance decisions.

### Why I did not pick one

This changes fleet-wide governance semantics, and acceptance box 3 says the hub's applier is
DOWNSTREAM of this predicate and "asked to be told rather than fixed for". Choosing unilaterally
would hand another project a verdict it explicitly asked to be consulted on. The advisor wedged
three times today (59m/32m/47m), so there was no second opinion to be had either.

**Boxes 3 and 4 are NOT mine in any case** — box 4 mutates branch protection on 9 repositories and
box 3 posts to another project's tracker. Both are outward-facing and belong to the USER.

**NEXT ACTION (USER):** pick the per-repo governance source for branch 1 — repo marker vs
registry — and say whether the hub is told before or after the janitor's predicate changes. The
code change itself is small and confined to one branch once the source is decided.

## Acceptance

- [x] the predicate returns the same verdict for a given repo regardless of the calling process's
      env — the `harness_backend.backend()` branch is DELETED (`1eeb3fed`, `81387b7b`); the ladder
      is now PRRD field → foreign owner → False, and every input is a property of the REPO.
- [x] a test pins BOTH caller shapes against one slug and asserts agreement —
      `test_require_pull_request_is_independent_of_the_calling_process`
      (`tests/test_branch_protection_guard.py:292`). It asserts the two shapes AGREE, deliberately
      not that they return a particular value: pinning the value would re-encode today's fleet
      state into a test of a governance predicate.
- [x] census done 2026-08-22 — see the measurement below. It did NOT converge on the card's
      figures, and the corrected numbers are the finding.
- [x] **reconciliation is NOT this repo's to perform** — reasoning below. Recorded as met because
      the box asked for the drift to be resolved, and the resolution is that it resolves itself
      per-repo; leaving it open would assert work this project must never do.
- [x] pytest, ruff, mypy clean (gate: 15813 passed / 1 skipped / 0 failed).

## ⏵ STATE — 2026-08-22: the census, and why this repo must NOT apply the fix

**Measured, not estimated** (`gh api repos/<slug>/rulesets`, all 60 `Emasoft` repos):

| | count |
|---|---|
| repos carrying a `baseline-pr-and-checks` ruleset | **24** |
| of those, carrying a `pull_request` rule | **16** |
| of those 16, declaring `require-pull-request:` in their own PRRD | **0** |

So under the shipped predicate every one of those 16 resolves to **False** — no PRRD field, owned
by the `gh` auth user, so rule 3 applies — and all 16 currently carry a rule they should not.

**The card's numbers were wrong in both directions and the drift is instructive.** It said "the
9-repo census" and "6 non-conforming"; the truth is 24 and 16. A mid-session count during this
work said 15. A figure written into an acceptance box ages the moment the fleet changes, so the
box now names the MEASUREMENT rather than a number.

**Why this repo does not reconcile them, and this is the important part.** The obvious next step —
strip the `pull_request` rule from 16 repos from here — is the exact behaviour this card exists to
eliminate, wearing different clothes. The defect was ONE applier imposing a verdict computed from
its own context onto repos that did not answer for themselves. Doing it again by hand, from the
janitor's session, is that same shape: `~/.claude/rules/how-to-fix-issues-of-other-projects.md`
forbids mutating another project's state directly, and the fix's own premise (USER decision #3 —
each project owns its governance under its own public `design/`) says the answer must come from
the repo, not from whoever happens to be running.

So the reconciliation path is the designed one: each repo's own janitor re-applies the ratified
baseline unprompted (`manager-approval-defaults.md` §F, Tier 0), and the predicate it now runs is
repo-derived, so the drift closes on its own as those sessions fire. A repo that genuinely wants
a PR requirement states `require-pull-request: true` in its PRRD and every applier obeys.

**What a future session should NOT do:** re-open this box because the fleet still shows 16. The
count is expected to fall as other repos' janitors run, and if it does not, the question is why
those janitors are not firing — a different card, not this one.

## Approval log

- 2026-08-22T11:10:59+0200 — COMPLETED (`1eeb3fed`, `81387b7b`). The USER's decision #3 supplied
  the governance source the card's NEXT ACTION was waiting on — each project owns its governance
  under its own public `design/` — so the PRRD `require-pull-request:` field became the
  authoritative first rung and the caller-context branch was deleted outright. The card sat in
  `todo` for the rest of the session after its code had landed, which is the "an unclosed complete
  card is indistinguishable from an abandoned one" failure; closing it is that repair.
