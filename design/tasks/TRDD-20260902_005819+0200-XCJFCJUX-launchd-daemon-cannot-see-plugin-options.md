---
trdd-id: XCJFCJUX
title: The launchd-run daemon never sees CLAUDE_PLUGIN_OPTION_* — every daemon knob, including the external-clear lever, is stuck at its default
column: blocked
pre-block-column: testing
created: 2026-09-02T00:58:19+0200
updated: 2026-09-02T03:09:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: [TRDD-O7UCNNN2]
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-NDAARSXT, TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-2F3I2P18, TRDD-O7UCNNN2]
implementation-commits: [dec760ed, 19a52dc8, d6c82d60]
---

# The lever is ON in settings.json and the daemon still runs the clear in shadow mode

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02 01:50

**The os.environ mirror (dec760ed) is SUPERSEDED — do not carry it forward.** Publish #5
(3.4.4) failed at the remote CPV gate: `[MAJOR] skillaudit:persistence ENV_INJECTION` on
`os.environ[key] = text`. CPV's three Python carve-outs (literal key+value, build-cache vars,
read-modify-write) correctly do not match a dynamic key with a file-sourced value, and the
documented audit-consent sentinel does NOT apply — `_EXECUTION_CLASS_RULES` omits
`ENV_INJECTION` in every CPV version on this machine (filed as claude-plugins-validation#223;
the sentinel commit 19a52dc8 is therefore dead weight and is removed by the redesign). A plist
`EnvironmentVariables` route was also rejected: the installer writes its plist through a
scanned heredoc by design, and `test_config_injects_no_code_loading_env` guards exactly that
surface.

**Design now: no process-environment writes at all.** `state.py` keeps a dict mirror
(`_SETTINGS_OPTIONS`, filled by `load_plugin_options_from_settings`, refreshed on mtime) and
exposes ONE accessor, `state.plugin_option(name)` — a real env var always wins, then the
mirror — plus `state.plugin_options_env()` for what a CHILD must inherit. `is_truthy_env`,
`_env_interval` and the daemon-lane direct reads route through the accessor; the daemon's
spawn points and `cold_cache_clear_task` merge the mirror into the child env. Session-lane
detectors and hooks are untouched (they already have the env). Implemented by a lean-worker
from this spec; verified first-hand before commit.

**NEXT ACTION:** verify the worker's diff (`grep -rn 'os.environ\[' scripts/lib/state.py` must
be empty), run ruff/mypy/tests, commit, re-run `uv run scripts/publish.py --patch`.

### ⛔ 2026-09-02 03:09 — SHIPPED in 3.4.4 (d6c82d60), daemon restaged 02:28:33; box 4 blocked on TRDD-O7UCNNN2

The accessor is live: a probe with the installed 3.4.4 libs run the way the daemon task runs
gives `enabled() = True` with 6 mirrored options. But box 4 (an `evaluating <root>` line
WITHOUT `[SHADOW]`) cannot be produced: the same probe shows all 5 fleet instances
`active=True` at every beat, and TRDD-O7UCNNN2 measured why — a heartbeat fire is a
substantive turn and `ACTIVE_FRESH_S` equals the heartbeat cadence, so an armed session is
never idle to the clear lane. Blocked on that card; do NOT re-verify this one's code.

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

- [x] loader test: a settings file with the lever + one non-option key ⇒ only the option lands
      in `os.environ`; a pre-set real env value is NOT overridden; a changed/removed file value
      updates/drops only the keys the loader injected — 6 tests in
      `tests/test_state_plugin_options_from_settings.py`, tmp_path files only
- [x] applied before the intervals are read — the call sits at daemon.py module level right
      after `_KEEPALIVE_INSTANCE` and before the first `_env_interval(`, since the intervals
      are computed at IMPORT time (not in `main()` as first written above); gated on
      `_KEEPALIVE_INSTANCE` so a bare `import daemon` in a test never inhales the real file.
      The loop refresh is one `stat` per tick and only affects call-time knobs.
- [x] ruff clean on the three files, `mypy scripts/` clean (496 files) and clean on the test
      file, 39/39 in the new test + the daemon keepalive/path/cold-cache-clear tests —
      re-run by the approver, not taken from the worker's report
- [ ] after publish + restage: `cold-cache-clear.log` shows `evaluating <root>` WITHOUT
      `[SHADOW — dry-run]` while the lever is on (the drill NDAARSXT/PXP08ZQC/1QJIZFFW waits on)

## Notes and lessons learned

- A knob that is read from `os.environ` is only as configurable as the process's LAUNCHER.
  When the launcher changes (heartbeat Bash → launchd), re-check every `os.environ` read on
  the daemon path, not just the one you are debugging.
