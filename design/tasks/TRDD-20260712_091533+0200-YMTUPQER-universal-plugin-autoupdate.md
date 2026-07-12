---
trdd-id: YMTUPQER
title: Universal per-heartbeat plugin auto-update — all enabled scopes, user-scope via the daemon
column: complete
created: 2026-07-12T09:15:33+0200
updated: 2026-07-12T09:30:47+0200
current-owner: janitor-claude
assignee: null
priority: 2
severity: MEDIUM
effort: M
labels: [plugin-updates, daemon, user-scope, auto-update, single-writer]
task-type: feature
parent-trdd: null
npt: [TRDD-Y9KM5RCJ]
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
last-test-at: 2026-07-12T09:30:47+0200
implementation-commits: [92bb9af, 38cb35d]
external-refs: []
---

# Universal per-heartbeat plugin auto-update

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**USER directive (2026-07-12):** make plugin updating COMPLETELY AUTOMATIC — at each
heartbeat the janitor must check EVERY plugin enabled in the current project across ALL
scopes (user + local + project), compare each installed version to its marketplace's
available version, and auto-update the ones that are behind at their own scope.

**USER decision (2026-07-12, AskUserQuestion):** cover all user-scope plugins EXCEPT the
ai-maestro fleet (maintainer/orchestrator/CPV/…). The fleet stays on its coordinated,
lockstep beat (fleet-skew avoidance, TRDD-db169d9e R2) — never updated one-at-a-time by
this path. The janitor ITSELF keeps its fast release-triggered self-update via
[[TRDD-Y9KM5RCJ]] (the NPT this builds on).

**STATUS (2026-07-12): COMPLETE.** All 4 pieces implemented + committed `92bb9af`
(impl) and `38cb35d` (20 real no-mock tests); full suite 12605 passed / 1 skipped,
ruff clean. Column → `complete`. **NEXT ACTION: none for this TRDD** — it is DONE and
awaiting the v0.42.0 publish, which is NON-EXEMPT (`release-via: publish`) and gated on
explicit USER approval. Nothing pushed/published yet; it rides the next release with
[[TRDD-Y9KM5RCJ]].

## Problem (verified from code, 2026-07-12)

`scripts/detectors/plugin-updates.py` ALREADY auto-updates project- and local-scope
plugins enabled in the current project, every heartbeat (~5 min): it reads
`claude plugin list --json`, compares each installed version to the plugin's
marketplace.json `version`, and runs `claude plugin update <id> --scope <scope>` when
behind (gated `CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_ENABLED`, default on). BUT it
HARD-EXCLUDES `user` and `managed` scope (`_scope_allowed`): the janitor is project-scoped
infra and, per the single-writer invariant (issue #7 / PRRD S2.1), N sessions across N
projects must not each run `claude plugin update --scope user` and stampede — the daemon is
the sole user-scope writer, on a slow 1 h (`task_user_plugins_update`) / 6 h beat. That 1 h
sweep ALSO excludes the ai-maestro fleet. Net: a behind user-scope plugin can lag up to 1 h
(the exact symptom the USER hit — the janitor's own 0.39→0.41 sat for hours until a manual
`claude plugin update`).

## Design — detector SIGNALS, daemon WRITES (single-writer preserved)

Extend the SAME per-heartbeat detector to cover user scope, but route the actual update
through the daemon so #7 holds. Reuses [[TRDD-Y9KM5RCJ]]'s request-flag→daemon-consume
substrate, generalized from "self-update" to a per-plugin update QUEUE.

1. **`scripts/lib/global_state.py`** — a per-plugin update-request QUEUE (JSON set in
   `plugin-update-requests.json`, atomic; sibling of the Y9KM5RCJ self flag):
   - `request_plugin_update(plugin_id: str, scope: str, reason: str = "") -> None`
   - `plugin_update_requests() -> list[dict]`  (each `{plugin_id, scope, reason}`)
   - `clear_plugin_update_request(plugin_id: str, scope: str) -> None`
   Keyed `<plugin_id>|<scope>`; idempotent re-enqueue; fail-open (a write hiccup falls back
   to the daemon's 1 h sweep). No legacy dual-read (new-code-only writer + reader).

2. **`scripts/detectors/plugin-updates.py`** — ALSO build user-scope candidates (enabled,
   `scope == "user"`, NOT `SELF_PLUGIN_NAME`, NOT `state.is_ai_maestro_plugin_id(id)` —
   fleet excluded per the USER decision). For a behind user-scope plugin, DO NOT update it
   here; call `gs.request_plugin_update(id, "user", "<cur>-><latest>")` (signal the daemon).
   project/local candidates keep updating DIRECTLY (unchanged). User-scope marketplaces are
   NOT refreshed per-session (that global op is the daemon's job) — the detector compares
   against the daemon-refreshed marketplace.json and signals; the daemon refreshes+updates.
   New opt-out `CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_USER_SCOPE` (default true) gates the
   user-scope arm back off (→ today's project/local-only behavior).

3. **`scripts/daemon.py`** — `_consume_plugin_update_requests(tasks)`, called each loop
   AFTER the stop/pause/maintenance branches, BESIDE `_consume_version_update_request`
   (Y9KM5RCJ): for each queued request, clear-before-run, then (defense-in-depth: skip
   `is_ai_maestro_plugin_id` + self) run `claude plugin marketplace update <mkt>` +
   `claude plugin update <id> --scope user` under `gs.marketplace_lock()`. On success set
   the reload generation (`set_reload_flag`) so the target's session reloads. Consume
   latency ≤ ~60 s. A persistent failure retries at most at the detector's ~5 min re-signal
   cadence (the flag is cleared here, re-set only on the detector's next fire).

4. **`.claude-plugin/plugin.json`** — register
   `CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_USER_SCOPE` (boolean, default true).

**Resulting latency:** user-scope plugin behind → detected next heartbeat (~5 min) → daemon
consumes (≤60 s) → updated in ~5-6 min (vs up to 1 h). Fleet plugins untouched; janitor self
via Y9KM5RCJ.

## Preserved invariants

- **Single writer** (#7 / PRRD S2.1): the detector only REQUESTS user-scope updates; only
  the daemon runs `claude plugin update --scope user`. project/local stays per-session
  (per-repo, not a machine-global race — the existing, accepted behavior).
- **Fleet-skew avoidance** (TRDD-db169d9e R2): ai-maestro-* fleet plugins excluded in BOTH
  the detector (don't signal) AND the daemon consumer (don't act) — the USER-chosen policy.
- **Fail-open**: every flag/queue op best-effort; a hiccup falls back to the daemon's
  existing 1 h user-scope sweep.
- **Self-terminating**: the detector only signals while a plugin is genuinely behind; once
  updated it stops (like Y9KM5RCJ).

## Verification

- Unit (real, no mocks): `global_state` queue enqueue/read/clear round-trip + idempotency;
  a pure predicate for the detector's user-scope decision (behind AND enabled AND not-self
  AND not-fleet AND user-scope-opt-in); the daemon consume-helper runs each queued update
  once + clears + skips a fleet id.
- Full suite + ruff green before commit.

## Approval log

- 2026-07-12 — USER directive "make plugin updating completely automatic (all enabled
  scopes, monitored each heartbeat)"; AskUserQuestion → "all user plugins EXCEPT the
  ai-maestro fleet". Approval to implement the approach. Publish remains separately
  USER-gated.
