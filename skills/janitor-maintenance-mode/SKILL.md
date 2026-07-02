---
name: janitor-maintenance-mode
description: Keep the janitor heartbeat ARMED but make every fire cache-refresh-only (no detectors, no daemon, no agents), so the prompt cache stays warm at ~1/10 the cost of letting it die and rewriting — the cheap middle ground between a full heartbeat and disarm. Trigger with /janitor-maintenance-mode, "maintenance mode", "keep the cache warm cheaply", "cheap heartbeat"; add "off" to disable, or "global" to apply fleet-wide.
---

# Janitor maintenance-mode

## Overview

Maintenance-mode keeps the heartbeat firing every 5 min but does close to the ABSOLUTE MINIMUM
each fire: the turn re-reads the session context at the 0.1x prompt-cache READ rate (which
RESETS the 5-minute cache TTL), then `dispatch.py` emits the never-stop keep-going nudge
(`[janitor-resume]` + a short "continue your pending task" line — TRDD-TKNSTP82) and returns —
no detectors, no daemon spawn, no other agent work.

**WHY it exists:** letting the cache DIE (disarm → no fires) forces the next real turn to
REWRITE the whole context at the 1.0x rate — ~10x a cache read. So a maintenance fire costs
~1/10 of a cache-death rewrite. It is the middle mode between FULL and DISARM:

| mode | fires? | per-fire cost | when |
|---|---|---|---|
| FULL | yes | cache-read + due chores + daemon | active dev |
| MAINTENANCE | yes | cache-read + continue-nudge (~0.1x) | keep the cache warm, cheap, never stall |
| DISARM | no | $0 (cache dies → 1.0x on return) | genuine long idle / shutdown |

Maintenance always carries the never-stop continue-nudge (see `/janitor-keep-going` for the
standalone opt-in to the same nudge while staying in FULL mode with detectors/daemon active).

Two scopes:

- **local** (default) — THIS session only (`.janitor/state/maintenance-mode`).
- **global** (say "global" / "fleet") — every armed session drops to cache-refresh-only
  fires and the daemon idles its task workloads.

A session in maintenance keeps its cache warm WITHOUT spawning the daemon/fleet-recovery, so
it stays warm even while the fleet is globally disarmed (maintenance wins over a stop).

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (locates `.janitor/state/`).
- The heartbeat is armed (`/janitor-arm`) — maintenance governs what an ARMED fire does; with
  no cron there is nothing to keep cheap. With no cron it still records the flag so a later
  `/janitor-arm` honors it.

## Instructions

1. Parse the request into (scope, action):
   - contains "off" / "stop" / "disable" → action = OFF; otherwise ON.
   - contains "global" / "fleet" / "all projects" → scope = GLOBAL; otherwise LOCAL.

2. **LOCAL ON** — write the sentinel atomically:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   printf '%s' 'maintenance-mode: cache-refresh-only fires' > "$STATE_DIR/maintenance-mode.tmp.$$"
   mv -f "$STATE_DIR/maintenance-mode.tmp.$$" "$STATE_DIR/maintenance-mode"
   ```

   **LOCAL OFF** — remove it:

   ```bash
   rm -f "${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state/maintenance-mode"
   ```

3. **GLOBAL ON / OFF** — go through the machine-wide CLI (the single source of truth for the
   global flag):

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" maintenance
   # to turn it off:
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" maintenance-off
   ```

4. Report one line:
   - LOCAL ON → `Janitor maintenance-mode ON (local) — heartbeat stays armed; each fire refreshes the cache only (~1/10 of a cache-death rewrite).`
   - GLOBAL ON → `Janitor maintenance-mode ON (global, fleet-wide) — every armed session fires cache-refresh-only; the daemon idles its tasks.`
   - OFF → `Janitor maintenance-mode OFF (<scope>) — full fires resume.`
   - If the heartbeat is not armed, append `Note: heartbeat not armed; run /janitor-arm to start the cheap keep-warm beat.`

## Output

One line. Side effect: writes/removes `.janitor/state/maintenance-mode` (local) or sets/clears
the machine-wide flag via `global_control_cli.py` (global). No cron change — arm/disarm is
separate.

## Error handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)` (dispatch resolves the same path).
- Cannot create `$STATE_DIR` (permission denied) → report `Janitor maintenance-mode failed: <error>`.
- Global CLI unavailable → report the error verbatim; the local flag path is unaffected.

## Scope

ONLY sets/clears the maintenance flag (local or global). Does NOT arm/disarm the cron, run
detectors, or change any other config. To STOP firing entirely, use `/janitor-disarm`; to arm,
use `/janitor-arm`; for a temporary silence, `/janitor-pause`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — `_resolve_heartbeat_mode()` returns
  `"maintenance"` when this flag (local or global) is set; the fire then refreshes the cache,
  `_phase_keep_going_nudge(mode)` emits the continue-nudge, and the fire returns before any
  detector/daemon phase.
- `/janitor-keep-going` — the standalone opt-in for the same never-stop nudge in FULL mode.
- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — `maintenance` / `maintenance-off`
  set/clear the machine-wide flag (and the daemon idles its tasks while it is set).
- `$CLAUDE_PROJECT_DIR/.janitor/state/maintenance-mode` — the per-session sentinel.

## Checklist

Copy this checklist and track your progress:

- [ ] Parse (scope, action) from the request
- [ ] LOCAL: atomically write / remove `.janitor/state/maintenance-mode`
- [ ] GLOBAL: call `global_control_cli.py maintenance` / `maintenance-off`
- [ ] Report one line (note if the heartbeat is not armed)
