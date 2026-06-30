---
name: janitor-global-disarm
description: TRUE machine-wide STOP of the global ai-maestro-janitor daemon AND every per-session heartbeat. Sets the kill-switch so the daemon exits and removes its OS keepalive, AND raises the global-pause flag so every armed session's heartbeat goes silent (runs no detectors) on its next fire — halting all janitor activity across ALL projects and instances, not just the daemon. The teardown sibling of /janitor-global-pause (which only idles). Trigger with /janitor-global-disarm, "stop all janitors", "globally disarm the janitor", "halt the janitor daemon everywhere".
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
- **every armed session's heartbeat goes SILENT** — `disarm` also raises the
  global-pause flag, which `dispatch.py` honors at Phase 0, so the heartbeat runs
  NO detectors on its next fire (TRDD-NJ22HNC3). This closes the gap where a
  disarmed machine kept running ~45 detectors per session every 5 min. The cron
  itself stays armed (the silence is teardown-free); to remove a project's cron
  entirely use `/janitor-disarm` in that session.

To revive: run `/janitor-global-arm` (clears the kill-switch; the next heartbeat
spawns a fresh daemon). For a temporary, teardown-free silence use
`/janitor-global-pause` instead.

## When NOT to use

- A temporary quiet block machine-wide → `/janitor-global-pause` (daemon stays
  alive, instant resume).
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
exits) AND the global-pause flag (heartbeats go silent). Does NOT remove any
per-project heartbeat cron (that is `/janitor-disarm`), does NOT uninstall the
plugin, and does NOT delete any state. The daemon's own shutdown path removes the OS
keepalive; this skill just trips the switches.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI (`disarm`/`arm`/`pause`/`unpause`/`status`).
- `/janitor-global-arm` — clears the kill-switch and revives the daemon.
- `/janitor-global-pause` — the lighter machine-wide suspend (daemon idles, no teardown).
- `/janitor-disarm` — the narrower per-project heartbeat stop.
