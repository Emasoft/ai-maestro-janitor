---
trdd-id: WQAJZ5V6
title: Harden ci.yml CPV-validate against the flaky REPO-LINT hang — retry-once was insufficient
column: published
created: 2026-06-25T14:57:20+0200
updated: 2026-06-25T15:10:50+0200
last-test-result: pass
last-test-at: 2026-06-25T15:01:54+0200
test-failures: 0
implementation-commits: [e63e4b8]
published-version: 0.24.5
published-at: 2026-06-25T15:10:50+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
priority: 4
severity: LOW
effort: S
labels: [ci, github-actions, cpv, flaky, resilience]
task-type: infra
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [lint]
impacts: [ci-pipeline]
external-refs: []
---

# TRDD-WQAJZ5V6 — Harden ci.yml CPV-validate retry against the flaky REPO-LINT hang

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

### The problem (VERIFIED on the v0.24.4 release CI)
`.github/workflows/ci.yml`'s `Validate plugin (strict)` step wraps
`cpv-remote-validate … --strict` in `timeout 300` + **retry ONCE on a 124 hang**.
The CPV REPO-LINT stage intermittently HANGS (zero progress, no network) while
publish.py's identical local `--strict` passes on the same commit — a documented
flake first seen at **v0.8.5** (the wrapper's own comment records it). On the
**v0.24.4** release CI it hit the hang on **BOTH** the first attempt AND the
single retry (exit 124 each, 300s each), so the step failed red; a **manual job
re-run went green** (effectively the 3rd attempt). So retry-once is empirically
insufficient — the gate produced a false-red on a good release and needed a human
re-run. This is a reliability defect in the gate, not a relaxation of it.

Raw evidence (run 28170536230, job Validate): install OK → `[REPO LINT]` banner →
no progress → `timeout` 124 → warn "retrying once" → `[REPO LINT]` again → no
progress → 124 → `::error::Validation failed (exit code 124)`. The manual
`gh run rerun --failed` then passed all jobs (`conclusion=success`).

### The fix (minimal, semantics-preserving)
Replace the single retry-on-124 with a **3-attempt loop** that retries ONLY on a
124 hang and still **fails fast on any real validation failure** (non-124 — CPV's
1-4 severity exits break immediately, no pointless retry). `timeout 300` per
attempt is unchanged; the job-level `timeout-minutes` stays the hard backstop.
3 attempts is what the v0.24.4 case needed (2 hangs + 1 clean) — it would have
self-healed with no human re-run.

### Why NOT touch release.yml (scope discipline)
`.github/workflows/release.yml`'s validate did NOT fail on v0.24.4 and is NOT in
scope. It currently runs CPV with **no `timeout` and no retry**, and treats only
exit codes **1-4** as failures (its job-level `timeout-minutes` is its hang
backstop). Adding the wrapper there means ALSO reconciling that `[1..4]`-only
exit-code semantics with a fail-on-persistent-124 — a real semantic change that
could regress how a hang is handled there. That deserves its own deliberate
change, not a ride-along. **Follow-up:** unify release.yml onto the same robust
wrapper (timeout + 3-attempt retry + explicit fail-on-persistent-124) once
thought through + tested.

### Root cause is CPV-side (upstream follow-up)
The actual hang lives in `cpv-remote-validate`'s REPO-LINT stage
(Emasoft/claude-plugins-validation). It is intermittent and has no local repro
(local `--strict` passes), so a precise upstream bug report needs more data. The
ci.yml retry is the in-project mitigation; the CPV REPO-LINT hang is the root fix
and belongs upstream (per the cross-project rule — file an issue, don't edit CPV
from here). **Follow-up:** capture a hanging-stage stack/trace next recurrence and
file a CPV issue.

### STATUS: IMPLEMENTED + VERIFIED — publishing
ci.yml's Validate step now uses a 3-attempt loop (`run_cpv && { … }; rc=$?` — the
`&&` form, NOT `if run_cpv; then …; fi` which swallows the exit code; verified
set-e-safe). Logic proven under `bash -e` (the workflow's exact shell), 6/6
scenarios: pass-attempt-1→0; hang,hang,pass→0 (self-heals the v0.24.4 case);
hang×3→124 (gives up RED); real-fail-attempt-1→2 (FAIL FAST); hang-then-real-fail→3
(fail fast attempt 2); hang-then-pass→0. YAML parses. A near-miss caught in review:
the first draft used `if run_cpv; then …; fi; rc=$?`, where the no-else if returns 0
on failure → `rc=0` → gate would PASS on every failure; rewritten to the `&&` form.

### NEXT ACTION
`publish.py --patch` (the new wrapper is active on its OWN release CI — self-
validating), verify green, set `column: published` + `published-version`.

## Why this TRDD exists
The v0.24.4 release CI produced a false-red from the documented CPV REPO-LINT
flake because retry-once was insufficient. "Never relax quality gates" requires
the gate to be RELIABLE, not just strict — a gate that false-reds a good release
and needs a manual re-run is a defect. One TRDD per change.
