---
trdd-id: MYQGMAQZ
title: the publish gate lacks the pyright check CI enforces so a release can be tagged before CI rejects it
column: todo
created: 2026-09-04T01:12:30+0200
updated: 2026-09-04T01:12:30+0200
current-owner: main-session
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
priority: high
relevant-rules: []
npt: []
eht: []
implementation-commits: []
---

## Symptom
`scripts/publish.py`'s release gate runs ruff + mypy. GitHub CI's Lint job additionally runs `uvx --with pyright pyright` with no `continue-on-error`. So the gate can pass, tag, push, publish a GitHub release and install the plugin, and only THEN have CI reject the commit.

## What actually happened (2026-09-04, release 3.4.14)
- publish.py reported all gates green and published 3.4.14 from commit `4326519d`.
- CI run 33814952562 on `4326519d` FAILED: job "Lint", step "Pyright (type check)", `7 errors, 0 warnings, 0 informations`.
- 6 errors in `tests/test_pane_actuate.py` (lines 88, 89, 185, 270, 307, 460 — `reportOptionalSubscript`), 1 in `tests/test_capture_all_logins.py:253` (`reportArgumentType`, `Popen[bytes]` vs `Popen[str]`).
- The release was already tagged, released, and installed to the user scope before this was noticed.

## Why "just drop pyright" is the wrong fix
`pyproject.toml` (around lines 45-58) documents the split as DELIBERATE, citing TRDD-BMDZK4RA: mypy does NOT check calls between `scripts/lib/` siblings, because those modules import each other bare (`import state`) and under `mypy_path = "scripts"` that name cannot resolve, so `ignore_missing_imports` degrades it to `Any`. Pyright owns that class instead via `extraPaths` in `pyrightconfig.json`. It caught a real `atomic_write(str)` vs `Path` mismatch that mypy passed clean (fixed in `a08d14fd`). The two checkers cover different classes on purpose.

`CLAUDE.md` says "the publish gate runs ruff + mypy, not pyright" — that describes the gate as it is, and is the text that made this look intentional. It is describing the hole, not defending it.

## Why the fix belongs in stage 4b specifically
`publish.py` already has a MANDATORY, no-skip stage `[4b/11] CI-parity preflight` (see `stage_ci_preflight`, publish.py:1655 onward), whose stated purpose is to catch CI-parity defects before the push. Pyright — the one CI check that blocks a merge and that mypy structurally cannot replace — is simply absent from it. This is a hole in a stage built for exactly this job, not a missing stage.

## Proposed fix
Add `uvx --with pyright pyright` to stage 4b, invoked the same way CI invokes it (no path argument — `pyrightconfig.json`'s `include` covers `scripts/` and `tests/`), with the same `uv sync --extra dev` precondition CI performs so imports resolve. Treat a non-zero exit as BLOCKED, like the rest of 4b.

## Acceptance criteria
- [ ] Stage 4b runs pyright with the same invocation and preconditions as ci.yml's Lint job.
- [ ] The gate's ruff scope matches CI's (`scripts/ tests/`, not `scripts/` alone).
- [ ] The remaining rows of the divergence table are each either adopted into the
      gate or explicitly declared out of scope ON THIS CARD with a reason — an
      undocumented gap is what produced this defect.
- [ ] The GitHub release is not created until CI is green for the pushed sha
      (the ordering defect above), or that ordering is explicitly rejected here
      with a reason.
- [ ] A tree with a deliberate pyright error is BLOCKED by publish.py before any tag or push.
- [ ] A test pins that the gate's checker set is not a strict subset of CI's Lint job, so a future CI check added without a gate counterpart is caught.
- [ ] The CLAUDE.md sentence describing the gate's checkers is updated once the gate changes.

## The divergence is wider than pyright — measured 2026-09-04

Pyright is what bit, but it is not the only gap. Comparing what publish 3.4.14
actually ran (`/tmp/publish6.txt`, the `$` command echoes) against
`.github/workflows/ci.yml`:

| check | publish gate | CI |
|---|---|---|
| ruff | `scripts/` only | `scripts/ tests/` |
| pyright | **absent** | `uvx --with pyright pyright` (whole project, blocks merge) |
| mypy | `scripts/ --ignore-missing-imports` | **absent** (gate-only, fine — a superset) |
| pytest | `tests/ -x -q -n auto --dist loadgroup` | `-m "not integration"` PLUS a separate serial `-m integration` run |
| shellcheck | absent | "Lint shell scripts" |
| hooks.json validation, dispatch smoke-run, per-hook smoke-run, per-detector strict-run | absent | present |
| memgrep build + staged-binary run | absent | present |

So the gate is NOT a superset of CI, and "add pyright" fixes one row of a
seven-row table. The ruff row matters immediately: the gate lints only
`scripts/`, and all seven of today's pyright errors were in `tests/` — the
directory the gate's ruff does not read either.

## The ordering defect, which is the bigger half

`publish.py` bumps, tags, pushes, creates the GitHub release, and runs an
install smoke test — all before CI has rendered a verdict on the pushed
commit. So every defect CI catches is caught after the artifact is public and
installable. On 2026-09-04 the release existed, was installed to user scope,
and the janitor daemon had already respawned onto it before anyone knew CI
was red.

Making the gate a superset of CI narrows the window; it does not close it,
because the gate runs on a local tree and CI runs on the pushed commit under
different load — which is exactly how the other post-publish defect this day
(a load-dependent `git_utils` probe timeout) slipped through a green gate.
The closing move is to gate the RELEASE (not the push) on CI green for the
pushed sha.

Note this does not conflict with the working rule "after publish.py, do NOT
sit and watch CI" — that rule governs the operator's attention, not the
pipeline's ordering. A pipeline that waits costs the human nothing to watch.

## Related
- The 7 errors themselves are being fixed separately; this card is about the GATE, not those errors.
- `pyproject.toml` lines ~45-58 and TRDD-BMDZK4RA for the deliberate mypy/pyright split.
