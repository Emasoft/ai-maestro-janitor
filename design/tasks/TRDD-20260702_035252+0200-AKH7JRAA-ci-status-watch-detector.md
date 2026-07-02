---
trdd-id: AKH7JRAA
title: ci-status detector — after a push, watch the commit's CI and notify the main Claude on failure
column: dev
created: 2026-07-02T03:52:52+0200
updated: 2026-07-02T03:52:52+0200
current-owner: autonomous-go-on-yourself
assignee: autonomous-go-on-yourself
priority: 2
severity: MEDIUM
effort: S
labels: [heartbeat, detector, ci, github, notify]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
runtime-targets: [macos, linux]
impacts: []
attempts: 0
last-test-result: not-run
implementation-commits: []
external-refs: []
---

# TRDD-AKH7JRAA — ci-status watch detector

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **USER ask (verbatim intent):** "one job that the janitor should do is to check
  github after every push to see if the ci/cd run was completed without errors, and
  if not, immediately notify the main claude."
- **DESIGN:** a new heartbeat detector `scripts/detectors/ci-status.py`.
  - **Push detection:** track `git rev-parse @{push}` (the last-pushed SHA). When it
    advances past the stored `ci-status-checked-sha.txt`, there is a new pushed commit
    to watch. (Falls back / fails-open when there is no upstream.)
  - **Poll:** `gh run list --commit <SHA> --json databaseId,status,conclusion,workflowName,url,displayTitle,headBranch --limit 30`
    (via `state.run_subprocess`, timeout, fail-open). Re-checked each heartbeat until
    EVERY run for that SHA is terminal (`status == completed`).
  - **Notify:** if any run's `conclusion ∈ {failure, timed_out, cancelled,
    startup_failure}` → emit ONE drift line (the notification the main Claude sees on
    the heartbeat) naming the failed workflow(s) + run URL, deduped per run id
    (`emit_once`). Then stamp the SHA checked (one notification per push). All-green /
    skipped-neutral → silent + stamp. No runs after a grace window (default 1800s) →
    give up + stamp (a push may legitimately trigger no CI).
  - **Fail-open everywhere:** no git repo / no origin / no `gh` / not authed / network
    error → silent no-op (log only), retried next heartbeat.
- **TESTABILITY:** the decision is a PURE function `classify_ci_runs(runs, *, now,
  first_seen_ts, no_run_grace_s) -> (action, failed_runs)` with action ∈
  {wait, resolved, failed}; `build_ci_failure_line(...)` builds the sanitized drift
  line. Both unit-tested with real run-dict inputs (no gh, no mocks). The thin I/O
  shell reuses `state.run_subprocess` / `dedupe.emit_once` / `state.sanitize_for_drift_line`.
- **WIRING:** register `("ci-status", 60, "CLAUDE_PLUGIN_OPTION_CI_STATUS_INTERVAL")`
  in `dispatch._DETECTORS` (short cadence → checks near-every heartbeat while a run is
  pending; cheap no-op — one `git rev-parse` — when `pushed==checked`). Opt-out
  `CLAUDE_PLUGIN_OPTION_CI_STATUS_ENABLED` (default on). Runs in FULL mode only
  (detectors are skipped in maintenance/stop — correct: CI-watching is active-dev work).
- **NEXT ACTION:** implement detector + tests + register + docs (CLAUDE.md detector
  list) → full suite + ruff → commit → publish.

## Why

After `publish.py` pushes, CI runs; if it goes red (a real failure, or the known
`cpv-remote-validate` network flake), the main Claude currently only finds out by
manually running `gh run watch`. This detector closes that loop: the heartbeat watches
the pushed commit's CI and surfaces a failure as a drift line, so the session knows to
re-run or fix without the human noticing the red first.

## Acceptance criteria

- `classify_ci_runs`: empty+within-grace→wait; empty+past-grace→resolved; any
  non-completed→wait; all success/skipped/neutral→resolved(success, no emit); any
  failure/timed_out/cancelled/startup_failure→failed(returns the failed runs).
- One drift line per failed push (deduped per run id + SHA-stamp); silent on green.
- Fail-open: no repo/remote/gh/auth/network → exit 0, no crash, no drift.
- ruff/mypy clean; full suite green; CLAUDE.md detector list updated.

## Notes and lessons learned
