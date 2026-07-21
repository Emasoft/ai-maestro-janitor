---
name: janitor-maintenance-mode
description: Keep THIS project's janitor heartbeat ARMED but make every fire cache-refresh-only (no chores, no daemon spawn, no agents — only the token-burn monitors stay on), so the prompt cache stays warm at ~1/10 the cost of letting it die and rewriting — the cheap middle ground between a full heartbeat and disarm. LOCAL-only; see /janitor-global-maintenance-on for the fleet-wide equivalent. Trigger with /janitor-maintenance-mode, "maintenance mode", "keep the cache warm cheaply"; add "off" to disable.
---

# Janitor maintenance-mode

## Overview

Maintenance-mode keeps the heartbeat firing every 5 min but does close to the ABSOLUTE MINIMUM
each fire: the turn re-reads the session context at the 0.1x prompt-cache READ rate (which
RESETS the 5-minute cache TTL), then `dispatch.py` emits the never-stop keep-going nudge
(`[janitor-resume]` + a short "continue your pending task" line — TRDD-TKNSTP82), runs ONLY
the token-monitoring detectors (`token-usage-anomaly` + `window-burn-rate` — a long unattended
maintenance session is exactly the one whose burn most needs watching, and both are cheap
local reads), and returns — no other detectors, no daemon spawn, no other agent work.

**WHY it exists:** letting the cache DIE (disarm → no fires) forces the next real turn to
REWRITE the whole context at the 1.0x rate — ~10x a cache read. So a maintenance fire costs
~1/10 of a cache-death rewrite. It is the middle mode between FULL and DISARM:

| mode | fires? | per-fire cost | when |
|---|---|---|---|
| FULL | yes | cache-read + due chores + daemon | active dev |
| MAINTENANCE | yes | cache-read + continue-nudge + token monitors (~0.1x) | keep the cache warm, cheap, never stall |
| DISARM | no | $0 (cache dies → 1.0x on return) | genuine long idle / shutdown |

Maintenance always carries the never-stop continue-nudge (see `/janitor-keep-going` for the
standalone opt-in to the same nudge while staying in FULL mode with detectors/daemon active).

This skill is **LOCAL-ONLY** — it writes `$CLAUDE_PROJECT_DIR/.janitor/state/maintenance-mode`
and affects THIS session's heartbeat only. The machine-wide equivalent is
`/janitor-global-maintenance-on` and `/janitor-global-maintenance-off` — two INDEPENDENT
settings. Any combination is valid (local on + global off, local off + global on, both,
neither); the EFFECT is OR-ed, so either flag being set makes THIS session's fires
cache-refresh-only.

`/janitor-arm` CLEARS this LOCAL sentinel (arming means the session starts in a known FULL
state) but never the GLOBAL flag — so a local maintenance does not survive a re-arm and a
global one does. The arm reports `maintenance=global-on` when the global flag is set.

A session in maintenance keeps its cache warm WITHOUT spawning the daemon/fleet-recovery, so
it stays warm even while the fleet is globally disarmed (maintenance wins over a stop).

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (locates `.janitor/state/`).
- The heartbeat is armed (`/janitor-arm`) — maintenance governs what an ARMED fire does; with
  no cron there is nothing to keep cheap. With no cron it still records the flag so a later
  `/janitor-arm` honors it.

## Instructions

1. Parse the request into an action:
   - contains "off" / "stop" / "disable" → action = OFF; otherwise ON.

2. **ON** — write the sentinel atomically:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   printf '%s' 'maintenance-mode: cache-refresh-only fires' > "$STATE_DIR/maintenance-mode.tmp.$$"
   mv -f "$STATE_DIR/maintenance-mode.tmp.$$" "$STATE_DIR/maintenance-mode"
   ```

   **OFF** — remove it:

   ```bash
   rm -f "${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state/maintenance-mode"
   ```

3. Report one line:
   - ON → `Janitor maintenance-mode ON (local) — heartbeat stays armed; each fire refreshes the cache only (~1/10 of a cache-death rewrite).`
   - OFF → `Janitor maintenance-mode OFF (local) — full fires resume.`
   - If the heartbeat is not armed, append `Note: heartbeat not armed; run /janitor-arm to start the cheap keep-warm beat.`

## Output

One line. Side effect: writes/removes `.janitor/state/maintenance-mode` (this project only).
No cron change — arm/disarm is separate. Does not touch the machine-wide flag; see
`/janitor-global-maintenance-on` / `/janitor-global-maintenance-off` for that.

## Error handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)` (dispatch resolves the same path).
- Cannot create `$STATE_DIR` (permission denied) → report `Janitor maintenance-mode failed: <error>`.

## Scope

ONLY sets/clears THIS project's LOCAL maintenance flag. Does NOT arm/disarm the cron, run
detectors, change any other config, or touch the machine-wide flag. To STOP firing entirely,
use `/janitor-disarm`; to arm, use `/janitor-arm`; for a temporary silence, `/janitor-pause`;
for the fleet-wide equivalent, `/janitor-global-maintenance-on` / `/janitor-global-maintenance-off`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — `_resolve_heartbeat_mode()` returns
  `"maintenance"` when this flag (local or global) is set; the fire then refreshes the cache,
  `_phase_keep_going_nudge(mode)` emits the continue-nudge, and the fire returns before any
  detector/daemon phase.
- `/janitor-keep-going` — the standalone opt-in for the same never-stop nudge in FULL mode.
- `/janitor-global-maintenance-on` / `/janitor-global-maintenance-off` — the machine-wide,
  independent equivalent of this LOCAL flag.
- `$CLAUDE_PROJECT_DIR/.janitor/state/maintenance-mode` — the per-session sentinel.

## Checklist

Copy this checklist and track your progress:

- [ ] Parse the action (ON/OFF) from the request
- [ ] Atomically write / remove `.janitor/state/maintenance-mode`
- [ ] Report one line (note if the heartbeat is not armed)
