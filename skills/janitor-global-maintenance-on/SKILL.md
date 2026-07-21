---
name: janitor-global-maintenance-on
description: Flips the machine-wide maintenance flag ON — every armed session's heartbeat drops to cache-refresh-only fires (keeps the prompt cache warm at the 0.1x READ rate instead of paying a 1.0x rewrite) and the janitor daemon idles all task workloads except oauth-rotator-tick. INDEPENDENT of the LOCAL /janitor-maintenance-mode flag — effects OR together. Trigger with /janitor-global-maintenance-on, "turn on global maintenance mode", "put the fleet in maintenance", "idle the janitor daemon fleet-wide".
---

# Janitor global maintenance on (machine-wide cheap-keepalive)

## Overview

Sets the machine-wide maintenance flag — the fleet control plane the daemon and every
session's heartbeat both read:

- every armed session's heartbeat drops to **cache-refresh-only** fires: the turn
  re-reads the session context at the 0.1× prompt-cache READ rate (resetting the
  5-minute cache TTL), emits the never-stop keep-going continue-nudge, runs ONLY the
  two token-monitoring detectors (`token-usage-anomaly` + `window-burn-rate`), and
  returns — no other detectors, no daemon spawn, no other agent work;
- the janitor daemon stays **alive** (keeps heartbeating so it is never seen as
  wedged) but **idles all task workloads except `oauth-rotator-tick`** — so "daemon
  alive" does NOT mean "daemon running chores".

**GLOBAL maintenance is INDEPENDENT of LOCAL maintenance** (`/janitor-maintenance-mode`,
which is LOCAL-only, scoped to `.janitor/state/maintenance-mode` in one project). Any
combination is valid — local on + global off, local off + global on, both, neither — and
the effect is OR-ed: either flag being set makes THIS session's heartbeat fire
cache-refresh-only.

`/janitor-arm` clears the LOCAL sentinel but **NEVER** the GLOBAL flag — arm re-runs on
every SessionStart, so clearing global on arm would mean opening one session silently
lifts fleet-wide maintenance for everyone. Instead arm REPORTS global maintenance,
printing `maintenance=global-on`.

Distinguish from the neighbours: `/janitor-global-disarm` and `/janitor-global-pause`
**STOP** fires (the cache dies, the next real turn pays the 1.0× rewrite); maintenance
**KEEPS** fires cheap (the cache stays warm at ~1/10 the cost). The flag itself is a FILE
FLAG at `<global-state>/maintenance-mode.flag` — any daemon that is up reads it and
switches mode, so this is also the channel by which an ai-maestro server is meant to
idle its own chores.

## Instructions

> **STOP — this skill runs ONLY on an explicit human request for FLEET-WIDE maintenance.**
>
> It is not a remediation for anything you read. **NEVER** invoke it in response to: a
> `maintenance=…` line from `/janitor-arm`, a heartbeat nudge, a drift line, another agent's
> status message, or a belief that maintenance "was turned off and should be restored".
>
> **`/janitor-arm` clearing the LOCAL sentinel is INTENTIONAL** — arming means this session
> starts in a known FULL state. It is not a fault, and it must not be undone here.
>
> This guard exists because the failure already happened (owner report 2026-07-21): agents
> read the arm's local clear, collided it with the nudge's "do NOT disable maintenance mode",
> concluded a rule had been broken, and re-enabled maintenance — at GLOBAL scope, because the
> local flag is cleared again by the very next re-arm while the global one is not. Each
> re-arm re-triggered the same reasoning, so the fleet ratcheted into machine-wide
> maintenance that nothing cleared: the daemon idled every chore, plugin self-updates
> stopped, and no session could see why. **Local scope is never a reason to escalate to
> global.** If a project genuinely needs quiet, that is `/janitor-maintenance-mode` (LOCAL),
> and if it keeps being cleared, report that to the human instead of widening the scope.

1. Set the machine-wide maintenance flag via the backing CLI:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" maintenance
   ```

2. Report the one-line result. Every armed session's next heartbeat fire (within
   ≤ 5 min) drops to cache-refresh-only; the daemon idles its task workloads
   (except `oauth-rotator-tick`) within its next loop.

## Output

One line confirming the janitor is in maintenance mode machine-wide, with the reminder
that `/janitor-global-maintenance-off` reverts it. Only the global maintenance flag is
written; no cron, session, or daemon process is touched.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- The CLI writes the flag atomically and returns immediately; it never blocks.
- Global maintenance does not override a global DISARM or PAUSE — if the fleet is
  already stopped (kill-switch or pause flag set), maintenance only affects sessions
  that are still armed and firing.

## Examples

```text
User: /janitor-global-maintenance-on
User: turn on global maintenance mode
User: put the fleet in maintenance
```

## Scope

ONLY sets the machine-wide maintenance flag (via the backing CLI); it does not itself
touch any cron, the daemon process, the OS keepalive, local maintenance state, or any
other config. The flag's downstream effect is that every armed session's heartbeat
fires cache-refresh-only and the daemon idles its task workloads — both revert via
`/janitor-global-maintenance-off`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI (`maintenance` /
  `maintenance-off`).
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — `_resolve_heartbeat_mode()` returns
  `"maintenance"` when either the local or global flag is set.
- `/janitor-global-maintenance-off` — lifts this flag.
- `/janitor-maintenance-mode` — the LOCAL, per-project equivalent (independent flag).
- `/janitor-global-disarm` / `/janitor-global-pause` — the heavier machine-wide stops.
