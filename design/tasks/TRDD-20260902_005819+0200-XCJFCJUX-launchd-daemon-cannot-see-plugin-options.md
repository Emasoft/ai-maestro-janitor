---
trdd-id: XCJFCJUX
title: The launchd-run daemon never sees CLAUDE_PLUGIN_OPTION_* — every daemon knob, including the external-clear lever, is stuck at its default
column: dev
created: 2026-09-02T00:58:19+0200
updated: 2026-09-02T00:58:19+0200
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
external-refs: [TRDD-NDAARSXT, TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-2F3I2P18]
implementation-commits: []
---

# The lever is ON in settings.json and the daemon still runs the clear in shadow mode

## Measured 2026-09-02 (not inferred)

- `~/.claude/settings.json` `env` block: `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED: "true"`,
  mtime 2026-09-01 21:30 — BEFORE the daemon's last respawn (23:43:56, after the 3.4.3
  auto-update).
- `cold-cache-clear.log` at 00:42 and 00:47: `evaluating <root> [SHADOW — dry-run]` — the
  daemon computes `external_clear.enabled()` as False.
- `ps -E -p <daemon pid>` snapshot: **0** `CLAUDE_PLUGIN_OPTION_*` variables in the daemon's
  environment. `~/Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist` has no
  `EnvironmentVariables` block; `launchctl getenv` of the lever is empty.
- `external_clear.enabled()` → `state.is_truthy_env(ENABLED_ENV, DEFAULT_ENABLED)` →
  `os.environ.get(name)`. Every other daemon knob (`CLAUDE_PLUGIN_OPTION_DAEMON_*_INTERVAL`,
  `DAEMON_ENABLED`, `COLD_CACHE_CLEAR_SHADOW`, `FLEET_STOP_ENABLED`, …) resolves the same way.

## Why

Claude Code injects the settings.json `env` block into a SESSION's process environment, so a
daemon spawned from a heartbeat's Bash call inherits the options. The OS keepalive
(TRDD-era launchd plist) starts the daemon from launchd with launchd's environment, which has
none of them. Since the keepalive became the production path, every `CLAUDE_PLUGIN_OPTION_*`
knob the user sets has been silently ignored by the daemon lane — the lever flip that
NDAARSXT's drill was waiting on could never have taken effect.

## Fix (option chosen: read the file the harness reads, at boot and on change)

In `scripts/lib/state.py` add `load_plugin_options_from_settings(path=None) -> int`: parse
`~/.claude/settings.json` (reuse `settings_ensurer._settings_path` / `_load_settings`), take
`env`, and for every key starting `CLAUDE_PLUGIN_OPTION_` that is NOT already in
`os.environ` set it (str). Track the injected keys in a module dict so a later call can
UPDATE or DROP a key the file changed, without ever overriding a value that came from the
real environment (a real env var must win — that is how tests and the session lane isolate).
Return the count applied.

Call it (1) once in `daemon.main()` before any task interval is computed, and (2) at the top
of each loop iteration ONLY when the file's mtime changed (one `stat` per tick). Rejected: an
`EnvironmentVariables` block in the plist — it needs a plist rewrite on every settings change
and duplicates the file the harness already treats as the source of truth.

## Acceptance

- [ ] loader test: a settings file with the lever + one non-option key ⇒ only the option lands
      in `os.environ`; a pre-set real env value is NOT overridden; a changed/removed file value
      updates/drops only the keys the loader injected
- [ ] `daemon.main()` applies it before intervals are read (test via the module hook, not a
      live daemon)
- [ ] `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports` + the touched tests
      green
- [ ] after publish + restage: `cold-cache-clear.log` shows `evaluating <root>` WITHOUT
      `[SHADOW — dry-run]` while the lever is on (the drill NDAARSXT/PXP08ZQC/1QJIZFFW waits on)

## Notes and lessons learned

- A knob that is read from `os.environ` is only as configurable as the process's LAUNCHER.
  When the launcher changes (heartbeat Bash → launchd), re-check every `os.environ` read on
  the daemon path, not just the one you are debugging.
