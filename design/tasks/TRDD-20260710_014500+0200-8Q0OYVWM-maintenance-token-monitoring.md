---
trdd-id: 8Q0OYVWM
title: Token monitoring survives maintenance mode, and every reload sends --force
column: dev
created: 2026-07-10T01:45:00+0200
updated: 2026-07-10T01:45:00+0200
current-owner: janitor-session
assignee: janitor-session
priority: 2
severity: MEDIUM
effort: S
labels: [token-economy, maintenance-mode, reload]
task-type: feature
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
impacts: []
external-refs: []
---

# Token monitoring survives maintenance mode, and every reload sends --force

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-10

**IMPLEMENTED locally.** Two same-day user directives (verbatim: "make sure the janitor
heartbeat even in maintenance mode will keep the token monitoring on"; "always use the
--force option when using the /reload-plugins command, to avoid some plugins in the
cache to refuse to be reloaded because they are working").

**NEXT ACTION:** run suite + lint, commit, publish (rides the next release).

## Change 1 — token monitoring in maintenance mode

The maintenance early-return (dispatch Phase 1.5b) idled ALL detectors — including
`token-usage-anomaly` and `window-burn-rate`, the burn alarms. But a maintenance
session is exactly the long unattended one whose token burn most needs watching.

- `dispatch._MAINTENANCE_DETECTORS = {"token-usage-anomaly", "window-burn-rate"}` —
  the subset that survives; both are cheap local reads, self-gated, self-cadenced.
- `dispatch._run_maintenance_detectors()` — same roster entries, same env cadence
  overrides, same `_run_detector` due-gate as Phase 2, called INSIDE the maintenance
  branch before its return. No double-run: maintenance returns before Phase 2; full
  mode never calls the maintenance helper.
- Skill doc `janitor-maintenance-mode` updated (description + overview + mode table).
- `tests/test_maintenance_token_monitoring.py` (4): subset exact, subset-to-roster
  name binding (the four-readers-zero-writers lesson), records-only-subset run, and a
  source-order guard that the call sits inside the branch.

## Change 2 — /reload-plugins always sends --force

Without `--force` a plugin whose code is mid-use can refuse the reload and silently
stay on the old cached version. Changed EVERY janitor sender/advisory:

- `scripts/reload_trigger.py` — iTerm osascript line, terminal_trigger send, dry-run plan.
- `scripts/lib/fleet_inject.py` — the fleet-recovery `"reload"` action command.
- Advisory texts: `detectors/plugin-updates.py`, `hooks/on-prompt-submit-user-mem.py`.
- Docs: `skills/janitor-reload-plugins/SKILL.md` (all typed/manual mentions + the WHY),
  `rules/janitor-heartbeat-protocol.md` (the [janitor-reload] row).
- Tests updated: `test_reload_trigger.py` (3 asserts), `test_fleet_inject.py` (3 asserts).

## Notes and lessons learned
