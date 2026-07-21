---
name: janitor-global-maintenance-off
description: Flips the machine-wide maintenance flag OFF — every armed session's heartbeat resumes full fires (due chores, agents, the daemon's task workloads) as soon as its next fire lands. INDEPENDENT of the LOCAL /janitor-maintenance-mode flag — clearing global does not touch local, and vice versa. Trigger with /janitor-global-maintenance-off, "turn off global maintenance mode", "take the fleet out of maintenance", "resume full janitor heartbeats fleet-wide".
---

# Janitor global maintenance off (machine-wide resume from cheap-keepalive)

## Overview

Clears the machine-wide maintenance flag set by `/janitor-global-maintenance-on`. Every
armed session's heartbeat — which was firing cache-refresh-only — resumes **FULL**
fires (due chores, agents, drift detection) on its next fire, and the janitor daemon
resumes running its due task workloads on its next loop.

**GLOBAL maintenance is INDEPENDENT of LOCAL maintenance** (`/janitor-maintenance-mode`,
which is LOCAL-only, scoped to `.janitor/state/maintenance-mode` in one project). Any
combination is valid — local on + global off, local off + global on, both, neither —
and the effect while EITHER is set is OR-ed (cache-refresh-only). Clearing the global
flag here has no effect on any project's local flag; each reverts independently.

`/janitor-arm` clears the LOCAL sentinel but **NEVER** the GLOBAL flag — arm re-runs on
every SessionStart, so clearing global on arm would mean opening one session silently
lifts fleet-wide maintenance for everyone. Instead arm REPORTS global maintenance,
printing `maintenance=global-on`, until this skill (or an equivalent CLI call) clears it.

Recap of what maintenance was doing while it was ON: every armed session kept firing
but did only the cache refresh (0.1× cache-READ rate instead of a 1.0× rewrite) plus the
keep-going continue-nudge and the two token-monitoring detectors; the daemon stayed
alive but idled ALL task workloads except `oauth-rotator-tick`. Distinguish from the
neighbours: `/janitor-global-disarm` and `/janitor-global-pause` STOP fires entirely
(the cache dies); maintenance only KEPT fires cheap — this skill lifts that, it is not
a revive from a stop.

## Instructions

1. Clear the machine-wide maintenance flag via the backing CLI:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" maintenance-off
   ```

2. Report the one-line result. Every armed session's next heartbeat fire (within
   ≤ 5 min) resumes full behavior; the daemon resumes running due tasks within its
   next loop (~1 s).

## Output

One line confirming the machine-wide maintenance flag was cleared. If maintenance was
not set, the call is a harmless no-op.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- Clearing a maintenance flag that is not present is idempotent (no error).
- Clearing the global flag does not touch any project's LOCAL maintenance sentinel —
  those still need `/janitor-maintenance-mode off` per project if they were set.

## Examples

```text
User: /janitor-global-maintenance-off
User: turn off global maintenance mode
User: take the fleet out of maintenance
```

## Scope

ONLY clears the machine-wide maintenance flag (via the backing CLI). Does NOT clear a
global DISARM (that is `/janitor-global-arm`), does NOT lift a global PAUSE (that is
`/janitor-global-unpause`), does NOT touch any project's LOCAL maintenance flag (that is
`/janitor-maintenance-mode off`), and does NOT arm any cron.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI (`maintenance` /
  `maintenance-off`).
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — `_resolve_heartbeat_mode()` returns
  `"maintenance"` only while EITHER the local or global flag is still set.
- `/janitor-global-maintenance-on` — sets the flag this skill clears.
- `/janitor-maintenance-mode` — the LOCAL, per-project equivalent (independent flag).
- `/janitor-global-arm` / `/janitor-global-unpause` — the revives for a true DISARM or
  PAUSE (different flags).
