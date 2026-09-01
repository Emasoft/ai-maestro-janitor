---
trdd-id: 7KRF99WI
title: the branch-protection guard proposes a matrix job name that can never report
column: blocked
pre-block-column: testing
blocked-by: [AMAMA-peer-matrix-repo-re-measure]
created: 2026-08-30T00:39:59+0200
updated: 2026-09-01T19:55:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
npt: []
eht: []
relevant-rules: []
external-refs: [janitor#294, TRDD-H8WRCW0I]
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

## The hazard is LATENT — and what holds it back is a misconfiguration anyone might fix

Reported by the AMAMA peer session 2026-08-29 on their repo, where
`detect_required_status_checks()` returns `['Commitlint', 'Lint', 'Test', 'Test matrix',
'Validate']`. They had already removed the unsatisfiable context by hand, so
`baselines_content_current` reports that repo as DRIFTED — contexts compare as exact SETS
(`_params_match:606-611`, `want_ctx != got_ctx` ⇒ drift), which means the applier SHOULD restore
`Test matrix` on its next pass.

**It did not — and the reason is now measured**, from the applier's OWN log
(`.janitor/logs/branch-protection-apply.log`), which had been saying the same thing four times a
day for days:

```
[2026-08-30T00:01:41+0200] skip: cannot resolve owner/repo slug from plugin.json
```

`CLAUDE_PROJECT_DIR` is unset there, so the project root resolves to cwd — the workspace PARENT —
while the manifest lives one level down in the repo. `detect_repo_slug` returns `None` and **gate
3 returns before anything else runs**: it never reached the drift comparison, never reached gate
7, never attempted an apply. That divergence is its own defect, carded as **TRDD-H8WRCW0I**.

**So severity goes back to HIGH, for a better reason than the one it lost.** The matrix hazard is
blocked neither by luck nor by a dead guard, but by a **misconfiguration any reasonable person
might fix**. Setting `CLAUDE_PROJECT_DIR`, moving the manifest, or re-arming from the repo
directory are each ordinary, well-intentioned actions — and the very next pass then installs an
unsatisfiable required context. **Fix THIS card before TRDD-H8WRCW0I**, or repairing repo
resolution converts a silent no-op into an active breakage across every affected repo at once.
Guard-first is load-bearing sequencing, not prudence.

The `bypass_actors` entry (admin, `bypass_mode: always`) is what would make a realized wedge hard
to notice: the OWNER merges straight past a pending check while contributors are hard-blocked, so
the failure is invisible from the only account likely to look.

### Retracted — an earlier version of this card was wrong here

This section previously read *"right now a dead guard is the only thing protecting this repo from
the guard"*, citing a 78-day-stalled `last-run-guard-branch-protection.ts`. **Both facts were
false.** The peer had read an ABANDONED `.janitor/state/` inside a repo subdirectory while the
live one — resolved from cwd per `state.py:_resolve_project_root` — sat one level up with 76
current stamps. Their guard is alive and ran 40 minutes before the retraction.

Kept rather than deleted, because the shape is the point: a true measurement
(`ls .janitor/state/last-run-*.ts` really does list what is in the state dir relative to cwd)
was used to support a claim it does not license (*when did this project's detectors last run*).
The wrong directory is not visible in the output. **This card's own severity was set from that
false premise**. The lesson that outlived it: **when a tool declines, read its OWN log rather
than inferring from what it did not do.** Six `skip:` lines had been sitting in
`branch-protection-apply.log` for days saying exactly what was wrong, while both sessions
reasoned about gates instead of reading them.

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

- [x] **SEQUENCING**: land this BEFORE TRDD-H8WRCW0I — satisfied: this card's fix landed as
      `df8ff661` (00:58), H8WRCW0I's as `49294902`/`3d549068` (01:02/02:15), same night, in order
- [x] a job carrying `strategy.matrix` is NEVER emitted as a bare required context — OMITTED,
      not expanded (`branch_protection_lib.py`, the job loop). Expansion was rejected: the real
      contexts depend on `include`/`exclude`, so a subtly-wrong expansion recreates this defect
      with different strings, and an unsatisfiable required check is strictly worse than an
      unrequired satisfiable one
- [x] a `name:` containing `${{ ... }}` is never emitted verbatim as a context — second guard,
      reached by a different route (a template name on a job whose `strategy` this parser did not
      recognise)
- [x] a test with a PR-triggered matrix workflow fixture asserts the above, and FAILS against the
      pre-fix code — PROVEN by running both versions on one fixture rather than assuming:
      `OLD: [{'context': 'Lint'}, {'context': 'Test matrix'}]` vs `NEW: [{'context': 'Lint'}]`.
      Two tests added to `tests/test_branch_protection_guard.py`
- [ ] the fix is verified against a repo that HAS a PR-triggered matrix job, not only against this
      one, since this one does not reproduce it — the peer (AMAMA) has such a repo and offered to
      re-measure; ask before assuming safe
- [x] `uv run pytest -q` (guard file: 56 passed) + ruff clean + mypy clean. **Full-suite run still
      owed** — see TRDD-CI9AC02Y for the one known suite-only failure

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
