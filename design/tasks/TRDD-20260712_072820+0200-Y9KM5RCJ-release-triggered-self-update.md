---
trdd-id: Y9KM5RCJ
title: Release-triggered janitor self-update — the per-session detector signals the daemon to update NOW
column: complete
created: 2026-07-12T07:28:20+0200
updated: 2026-07-12T08:27:10+0200
current-owner: janitor-claude
assignee: null
priority: 3
severity: MEDIUM
effort: S
labels: [daemon, self-update, plugin-updates, latency]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: [2]
release-via: publish
delivery: direct-push
target-branch: main
merge-strategy: squash
must-pass-tests-before-merge: true
publish-target: ai-maestro-plugins
publish-channel: stable
test-requirements: [unit, lint]
review-requirements: []
runtime-targets: [macos, linux]
impacts: [config-schema]
attempts: 1
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-12T08:27:10+0200
implementation-commits: [5554a51]
external-refs: []
---

# Release-triggered janitor self-update

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**2026-07-12 — IMPLEMENTED + TESTED (commit `5554a51`). `column: complete`.** All 4
pieces landed exactly as designed below:
1. `global_state.{request,version_update_requested_present,clear}_version_update...` —
   the boolean request-flag trio (`version-update-requested.flag`, atomic, fail-open, no
   legacy dual-read).
2. `version_update_lib.should_request_prompt_update(installed, published, auto,
   trigger_enabled)` — the detector's pure decision (extracted for testing).
3. `version-update.py` Branch A auto-arm — raises `gs.request_version_update()` (still
   read-only w.r.t. the actual update); opt-out
   `CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER` (default true).
4. `daemon._consume_version_update_request(tasks)` — clear-before-run, then the
   `version-update` Task `.run()`; called AFTER stop/pause/maintenance, BEFORE the
   due-loop.
`plugin.json` registers the opt-out. 14 new tests (`test_release_triggered_self_update.py`,
real/no-mocks) + full suite 12585 passed, 1 skipped; ruff clean. CLAUDE.md prose +
state-file inventory + repomap updated.

**NEXT ACTION — STOP before publish.** `release-via: publish` is NON-EXEMPT: the code is
committed on `main` (ahead of origin, NOT pushed). The USER approves the release; this
ships on the next `publish.py` run.

**Broader publish-origin auto-update is a SEPARATE task (Phase 2), NOT this TRDD.** This
TRDD is the NARROW janitor SELF-update only. Detecting a publish ORIGINATING from the
armed project and updating ANY installed plugin at its scope (marketplace-diff, git-push
detection, source-matching, workflow-mediated propagation) is a distinct atomic task with
its own TRDD — it REUSES this request-flag→daemon-consume substrate generalized to an
arbitrary `<plugin>@<marketplace>:<scope>` update request.

**Prior USER decision (2026-07-12, AskUserQuestion):** make a new janitor release land in
~5-10 min instead of on the daemon's 6 h `version-update` beat — via a **release-triggered**
path (detect per-session → signal daemon → daemon updates NOW), NOT by merely tightening
the poll cadence. — DELIVERED.

## Problem (verified from code, 2026-07-12)

Today the janitor's own self-update is the daemon's `task_version_update`
(`scripts/daemon.py`), gated on `AUTO_UPDATE_ON_NEW_RELEASE` (default on) and run on a
**6 h** cadence (`_INTERVAL_VERSION_UPDATE = 21600`). The per-session detector
`scripts/detectors/version-update.py` *detects* a new GitHub release every ~5 min
(Branch A: `latest_published > latest_installed`) but, when auto-update is enabled, is
deliberately **read-only** — it just logs "the daemon will run the update on its next
cycle" and stays silent (TRDD-be2efa56 §9: the daemon is the single global writer so N
sessions don't race the network call). So detection is prompt but ACTION waits up to
6 h. That is why v0.41.0 sat at cache 0.39.0 for hours.

This is the janitor SELF-update only. Project/local plugins are already prompt
(`plugin-updates.py`, ~5 min); user-scope non-fleet plugins are the daemon's 1 h
sweep; other ai-maestro fleet plugins are intentionally excluded (TRDD-db169d9e R2,
fleet-skew avoidance) — none of those change here.

## Design — a global trigger flag the daemon consumes (single-writer preserved)

The detector must NOT run `claude plugin update` itself (that would break the
single-writer scope invariant, PRRD S2.1 / issue #7). Instead it raises a **request**;
the daemon — still the only writer — consumes it and runs the existing
`task_version_update` immediately.

1. **`scripts/lib/global_state.py`** — a flag-helper trio mirroring the reload-flag /
   pause-flag pattern, backed by `<global-state-dir>/version-update-requested.flag`
   (atomic write):
   - `request_version_update(reason: str = "") -> None`
   - `version_update_requested_present() -> bool`
   - `clear_version_update_request() -> None`

2. **`scripts/detectors/version-update.py`** (Branch A, the `auto_enabled` arm) — when
   the cache is behind GitHub AND auto-update is on, ALSO call
   `gs.request_version_update(f"{latest_installed}->{latest_published}")`. Still
   read-only w.r.t. the actual update; it only signals. Idempotent (re-writing the same
   flag is harmless; the daemon clears it on consume). Gated by a new opt-out
   `CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER` (default true) so the prompt
   path can be disabled back to the pure 6 h beat.

3. **`scripts/daemon.py` main loop** — after the kill-switch / maintenance / pause
   branches (so a stopped/paused/maintenance daemon never acts) and BEFORE the regular
   due-check task loop: if `gs.version_update_requested_present()`, **clear the flag
   first** (clear-before-run, like the reload flag — a failed run is re-signalled by the
   detector's next ~5 min fire), then run the `version-update` Task via its `.run()`
   (reusing the Task wrapper: last-run stamp resets the 6 h clock, failcount/backoff
   apply). The flag is checked every loop iteration; the loop sleep is capped at
   `_LOOP_CEILING_SEC = 60`, so consume latency ≤ ~60 s.

4. **`.claude-plugin/plugin.json`** — register
   `CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER` (boolean, default true).

**Resulting latency:** detector fire (~5 min) + daemon consume (≤60 s) ≈ **~5-6 min**,
vs 6 h. When the update lands, `task_version_update` already sets the reload flag →
next heartbeat emits `[janitor-reload]` (unchanged).

## Preserved invariants

- **Single writer** (PRRD S2.1 / issue #7): the detector only requests; the daemon runs
  the update. No session ever runs `claude plugin update --scope user`.
- **Fleet-skew avoidance** (TRDD-db169d9e R2): unchanged — only the janitor self-updates
  this way; other fleet plugins untouched.
- **Auto-update opt-out**: `task_version_update` still returns early when
  `AUTO_UPDATE_ON_NEW_RELEASE` is off, so the flag is consumed into a no-op — the
  master gate still governs.
- **Fail-open**: every flag op best-effort; a flag/daemon hiccup falls back to the 6 h
  beat, which is unchanged.

## Verification

- Unit (real, no mocks): `global_state` request/present/clear round-trip under
  `JANITOR_GLOBAL_STATE_DIR`; a pure predicate `should_request_prompt_update(installed,
  published, auto, trigger_enabled)` for the detector's decision; a daemon
  consume-helper that, given the flag set + a fake task list, runs the version-update
  task exactly once and clears the flag.
- Full suite + ruff green before commit.

## Approval log

- 2026-07-12 — USER chose "Release-triggered self-update (rec.)" via AskUserQuestion;
  approval to implement the approach. Publish remains separately USER-gated.
