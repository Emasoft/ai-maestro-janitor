---
trdd-id: QK7M2B0X
title: Publish the global mode flags to a fixed control dir any daemon can read
column: backburner
created: 2026-07-21T19:35:07+0200
updated: 2026-07-21T19:35:07+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
severity: medium
relevant-rules: [1]
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-21

**NOT STARTED.** Contract written and committed (`design/ARCHITECTURE.md` §7.1, rev 5);
no code moved yet. Sibling: TRDD-5ZVS1DDP (§7.2, one daemon per host) — independent, no
ordering constraint between them.

**NEXT ACTION:** add `global_state.control_dir()` returning the literal
`~/.claude/janitor-control/` (honoring `$JANITOR_CONTROL_DIR` for tests only), repoint the
SIX mode-flag path helpers at it, and give each reader a transitional dual-read of the old
location.

**Load-bearing facts, verified 2026-07-21:**

- The six flags and their current helpers in `scripts/lib/global_state.py`:
  `kill-switch.flag` (:241), `reload-needed.flag` (:253), `skills-reload-needed.flag`
  (:257), `maintenance-mode.flag` (:340), `global-pause.flag` (:376),
  `version-update-requested.flag` (:422). Each is `global_state_dir() / "<name>"`.
- `maintenance_mode_present` (:354), `kill_switch_present` (:317) and
  `global_pause_present` (:387) ALREADY carry a `_legacy_read_path(...)` dual-read from
  TRDD-2U8AH82F. This move adds a second transitional source, so keep the dual-read
  helper generic rather than writing a third bespoke fallback per flag.
- `global_state_dir()` keeps its four-rung ladder for everything else — pid, flock,
  heartbeat, last-run stamps, injection stamps, the migration marker. Only the MODE flags
  move. Do not "simplify" by moving the whole dir.

## Why

Owner directives, 2026-07-21: *"all global states must be shared via a file-flag. just
write to it, and whichever daemon is on will read it and switch the mode accordingly"* and
*"put it under some standard janitor folder."*

The flags already are files, and the janitor already reads them correctly. What blocks a
foreign reader is WHERE they are: `global_state_dir()` resolves through
`$JANITOR_GLOBAL_STATE_DIR` → `$XDG_STATE_HOME/janitor/` → the plugin DATA dir → the
legacy dir. An ai-maestro server cannot reproduce that safely — and the failure is silent
in the worst direction. A server that hardcodes the DATA path and runs on a host where
`XDG_STATE_HOME` is set (a normal Linux desktop) stats a file that never exists, reads
"no maintenance", and keeps running chores through a fleet-wide maintenance nobody can
see. A control plane whose miss-mode is "looks fine, ignores the flag" is worse than none.

## The design (ARCHITECTURE.md §7.1)

Split by audience, NOT a reversal of TRDD-2U8AH82F:

| dir | holds | lifecycle |
|---|---|---|
| `~/.claude/janitor-control/` (new, FIXED) | the six MODE flags | ephemeral control; SHOULD vanish on uninstall — a removed janitor must not leave a flag claiming the host is in maintenance |
| `<DATA>/global-state/` (unchanged) | pid, flock, heartbeat, last-run stamps, injection stamps, migration marker | private state; must survive plugin updates, purged on uninstall |

TRDD-2U8AH82F moved STATE into DATA and was right to; this publishes CONTROL and does not
touch that. The standing "prefer `${CLAUDE_PLUGIN_DATA}` over a custom `~/.claude/` folder"
principle keeps governing state — its stated reasons (survives updates, backed up, cleanly
purged) are all about durability, which is the property a mode flag must NOT have.

Steps:

1. `global_state.control_dir()` — literal `~/.claude/janitor-control/`, `$JANITOR_CONTROL_DIR`
   override for tests only, created on demand.
2. Repoint the six `_*_path()` helpers. Writes stay atomic (tmp + `os.replace`).
3. Transitional dual-read: each presence check falls back to the old
   `global_state_dir()/<name>` so a running daemon from the previous version and a session
   from the new one agree during the upgrade window. Writers write ONLY the new path.
4. `rules-cleanup` (or the uninstall path) removes `~/.claude/janitor-control/` when the
   janitor is confirmed uninstalled — the flags must not outlive the plugin.
5. Retire the transitional fallback two releases out, as TRDD-2U8AH82F's own legacy
   fallback is being retired.

## Verification

- Unit: each flag round-trips through the new dir; `$JANITOR_CONTROL_DIR` redirects it.
- Unit: a flag present ONLY at the old path is still seen (the upgrade window), and a
  writer never recreates the old path.
- Unit: `control_dir()` ignores `$XDG_STATE_HOME` and `$JANITOR_GLOBAL_STATE_DIR` — the
  whole point is that it does not move.
- Unit: state paths (pid, flock, heartbeat, last-run) are UNCHANGED and still ladder-resolved.
- Integration: set maintenance, stat the literal `~/.claude/janitor-control/maintenance-mode.flag`
  with no janitor code involved — that is the contract a foreign reader gets.
- Full `uv run pytest` + `ruff check` green before any commit.

## Notes and lessons learned

[^1]: [id:ATOM-QK7M-0001, status:valid, keywords:"external_consumer_hardcodes_path resolution_ladder_silent_miss XDG_STATE_HOME_moves_dir flag_read_returns_false", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT publish a cross-process contract on a path that resolves through a ladder,
  BECAUSE a foreign reader can only hardcode one rung and every other rung then makes it
  read a file that does not exist — which returns "flag absent", i.e. it silently ignores
  the control plane instead of failing loudly. DO give an external contract a literal
  fixed path, and keep ladder-resolved locations for state only this plugin reads.
