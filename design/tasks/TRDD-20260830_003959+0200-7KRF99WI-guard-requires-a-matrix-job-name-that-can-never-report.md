---
trdd-id: 7KRF99WI
title: the branch-protection guard requires a matrix job name that can never report and wedges every PR
column: todo
created: 2026-08-30T00:39:59+0200
updated: 2026-08-30T00:39:59+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [janitor#294]
---

# The guard restores a required check that can never pass

## The defect

`detect_required_status_checks` (`scripts/lib/branch_protection_lib.py:804`) computes a job's
required context as:

```python
name = (job_cfg.get("name") if isinstance(job_cfg, dict) else None) or job_id
```

read straight from the CONFIGURED workflow. There is **no matrix expansion anywhere in the
function**. GitHub, however, does not report a check named `Test matrix` for a matrix job — it
reports one check per combination (`Test matrix (ubuntu-latest, 3.12)` and so on). So the bare
configured name is required, is never reported, and stays permanently pending.

`apply_baseline_rulesets` then puts that context into `baseline-pr-and-checks`. **Every PR on such
a repo is blocked forever**, and `required_status_checks` is exactly the rule that cannot be
waited out.

## Why this is worse than a wrong value: the guard FIGHTS a correct fix

Reported by the AMAMA peer session 2026-08-29, measured on their repo. They had already removed
the unsatisfiable context by hand. `baselines_content_current` therefore reports their repo as
DRIFTED right now, and the next guard pass would "heal" it by putting the broken context back:

```
detect_required_status_checks() -> ['Commitlint', 'Lint', 'Test', 'Test matrix', 'Validate']
```

Their sentence for it is the one worth keeping: **"right now a dead guard is the only thing
protecting this repo from the guard."** Their `last-run-guard-branch-protection.ts` has not
advanced since 2026-06-13 — 78 days — and that stall is the only reason the repo is not wedged.
A stalled detector and a wrong applier are the same incident seen from opposite ends.

The `bypass_actors` entry (admin, `bypass_mode: always`) completes the trap: the OWNER merges
straight past the pending check and sees nothing wrong, while any contributor is hard-blocked.
The failure is invisible from the only account likely to look.

## The exposure is NARROWER than "any matrix job" — measured, not assumed

`detect_required_status_checks` already filters to PR-triggered workflows
(`branch_protection_lib.py:798`):

```python
if not ({"pull_request", "pull_request_target"} & _workflow_triggers(wf)):
    continue
```

So the condition is precisely: **a matrix job in a workflow that triggers on `pull_request`.**

This repo does NOT currently qualify, and that was verified by running the function rather than
reading it:

```
detect_required_status_checks(.) -> ['Audit .github/workflows', 'Lint', 'Smoke', 'Tests',
                                     'Validate', 'memgrep build+stage smoke']
```

Six clean contexts — even though `.github/workflows/memgrep-release.yml:35` carries
`name: Build memgrep (${{ matrix.asset }})`, which would be **worse** than the peer's case: an
uninterpolated GitHub expression emitted as a literal required context, unsatisfiable by
construction and confusing to diagnose. It is excluded only because that workflow is not
PR-triggered. **The PR-trigger filter is the sole thing standing between this function and
requiring `${{ matrix.asset }}` — that is a narrow escape, not a design.** Adding a
`pull_request:` trigger to `memgrep-release.yml` would wedge this repo with no other change.

## Acceptance

- [ ] a job carrying `strategy.matrix` is NEVER emitted as a bare required context — either
      expanded to its real per-combination names, or omitted with a logged reason
- [ ] a `name:` containing `${{ ... }}` is never emitted verbatim as a context (belt and braces:
      it is unsatisfiable whatever the matrix logic does)
- [ ] a test with a PR-triggered matrix workflow fixture asserts the above, and FAILS against
      today's code — a test that passes before the fix proves nothing here
- [ ] the fix is verified against a repo that HAS a PR-triggered matrix job, not only against this
      one, since this one does not reproduce it
- [ ] `uv run pytest -q` + `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

- **Do NOT "fix" this by dropping `required_status_checks` from the baseline.** The rule is the
  point — `NO_REQUIRED_CHECKS` exists because "a red build can merge". Removing the gate to stop
  emitting a bad context trades a wedged PR for an unguarded merge.
- **Expansion is not free and must not guess.** Per-combination names depend on the matrix values,
  including `include`/`exclude` entries; a wrong expansion is the same defect with different
  strings. Omitting a matrix job (with a log line) is a correct, conservative first fix and is
  strictly better than the status quo, which is to require something impossible.
- **This was found by a peer measuring MY code on THEIR repo**, and it is the second finding
  tonight that this repo could not have produced on its own — the local run is clean. A function
  that behaves correctly on every repo you own is not evidence about the function.
