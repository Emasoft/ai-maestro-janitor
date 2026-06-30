---
name: janitor-global-disarm
description: TRUE machine-wide STOP of the global ai-maestro-janitor daemon AND every per-session heartbeat. Sets the kill-switch so the daemon exits and removes its OS keepalive, AND raises the global-pause flag so every armed session's heartbeat self-disarms (deletes its own cron) on its next fire — halting all janitor activity across ALL projects and instances, not just the daemon. The also-stop-the-daemon sibling of /janitor-global-pause (which keeps the daemon alive). Trigger with /janitor-global-disarm, "stop all janitors", "globally disarm the janitor", "halt the janitor daemon everywhere".
---

# Janitor global disarm (machine-wide TRUE stop)

## Overview

TRUE machine-wide stop of the **global** janitor daemon by setting the kill-switch.
This is the **teardown** stop — distinct from `/janitor-global-pause` (which only
idles the daemon) and from `/janitor-disarm` (which removes only THIS project's
heartbeat cron). It stops the singleton daemon that serves ALL projects:

- the running daemon sees the kill-switch on its next loop and exits gracefully;
- if the OS keepalive (LaunchAgent / systemd unit) is installed, the daemon
  **removes it on the way out**, so launchd/systemd cannot resurrect it;
- per-session heartbeats stop lazy-spawning a new daemon (`ensure_daemon_running`
  honors the kill-switch), so the stop **holds**;
- **every armed session's heartbeat SELF-DISARMS** — `disarm` also raises the
  global-pause flag, which `dispatch.py` honors at Phase 0: on the next fire it emits a
  bare `[janitor-self-disarm]` marker so the session runs `/janitor-disarm` and **deletes
  its own cron** (TRDD-RQ9FIFX6, superseding the silence-only behavior of TRDD-NJ22HNC3).
  This is a TRUE stop, not a silence — a cron FIRE is a full Claude turn that re-reads the
  whole session context (~618k cached tokens, billed at the 0.1× cache-read rate, **not**
  free) whether or not detectors run, so only deleting the cron makes a fire cost zero.
  **Rollout caveat:** the marker is baked into the cron prompt at arm time, so crons armed
  BEFORE this shipped won't self-disarm on their own — run `/janitor-disarm` once in each
  such session.

To revive: run `/janitor-global-arm` (clears the kill-switch; re-arm a session with
`/janitor-arm` and its next heartbeat spawns a fresh daemon). For a temporary stop that
keeps the daemon alive use `/janitor-global-pause` instead.

## When NOT to use

- A temporary stop machine-wide that keeps the daemon alive → `/janitor-global-pause`
  (the daemon resumes instantly; sessions re-arm to restart their heartbeats).
- Silence only THIS project's heartbeat → `/janitor-disarm` (local).
- Uninstall the plugin entirely → Claude Code's plugin uninstall flow.

## Instructions

1. Set the kill-switch via the backing CLI (single source of truth for the flag
   path — never write the flag file by hand):

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" disarm "via /janitor-global-disarm"
   ```

2. Report the one-line result the CLI prints. The daemon may take up to its loop
   interval (≤ 60 s) to notice the flag and exit; that is expected.

## Output

One line confirming the janitor is disarmed machine-wide, with the reminder that
`/janitor-global-arm` revives it. No teardown beyond the kill-switch flag is written
here — the daemon performs its own shutdown + keepalive removal.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- The CLI never blocks; it writes the flag atomically and returns immediately.
- If the daemon was not running, the flag is still set (harmless) so a future
  lazy-spawn is suppressed until `/janitor-global-arm` clears it.

## Examples

```text
User: /janitor-global-disarm
User: stop all janitors everywhere
User: globally disarm the janitor daemon
```

## Scope

ONLY sets the two machine-wide flags via the backing CLI — the kill-switch (daemon
exits) AND the global-pause flag (each armed session's heartbeat self-disarms — deletes
its own cron — on its next fire, TRDD-RQ9FIFX6). The skill does not itself remove a cron,
uninstall the plugin, or delete state; the daemon's own shutdown path removes the OS
keepalive. This skill just trips the switches.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI (`disarm`/`arm`/`pause`/`unpause`/`status`).
- `/janitor-global-arm` — clears the kill-switch and revives the daemon.
- `/janitor-global-pause` — the lighter machine-wide suspend (daemon idles, no teardown).
- `/janitor-disarm` — the narrower per-project heartbeat stop.
