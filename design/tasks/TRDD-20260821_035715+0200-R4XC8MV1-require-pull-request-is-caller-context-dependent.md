---
trdd-id: R4XC8MV1
title: require_pull_request_for is caller-context dependent so two appliers flip-flop the same ruleset
column: todo
created: 2026-08-21T03:57:15+0200
updated: 2026-08-21T08:24:48+0200
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

## Acceptance

- [ ] the predicate returns the same verdict for a given repo regardless of the calling process's env
- [ ] a test pins BOTH caller shapes (harness env set / unset) against one slug and asserts agreement
- [ ] the 9-repo census converges: no ruleset changes shape between a janitor apply and a hub apply
- [ ] the fleet's 6 non-conforming `baseline-pr-and-checks` rulesets are reconciled to the verdict
- [ ] pytest, ruff, mypy, pyright clean

## Approval log
