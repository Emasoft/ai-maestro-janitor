---
name: janitor-stop
description: Machine-wide STOP for the global ai-maestro-janitor daemon. Sets the kill-switch so the daemon exits and removes its OS keepalive, and per-session heartbeats stop re-spawning it. Use to fully halt the janitor across ALL projects (not just one). Trigger with /janitor-stop, "stop the janitor daemon", "global stop the janitor", "halt the janitor everywhere".
---

# Janitor stop (machine-wide)

## Overview

Halts the **global** janitor daemon for the whole machine by setting the
kill-switch flag. Unlike `/janitor-disarm` (which only removes the CURRENT
project's heartbeat cron), this stops the singleton daemon that serves ALL
projects:

- the running daemon sees the kill-switch on its next loop and exits gracefully;
- if the OS keepalive (LaunchAgent / systemd unit) is installed, the daemon
  **removes it on the way out**, so launchd/systemd cannot resurrect it;
- per-session heartbeats stop lazy-spawning a new daemon (`ensure_daemon_running`
  honors the kill-switch), so the stop **holds**.

To revive: run `/janitor-arm` (it clears the kill-switch, and the next heartbeat
spawns a fresh daemon).

Use this when you want a clean global stop of the janitor's background activity —
e.g. before maintenance, debugging, or instead of the blunt "close the terminal"
(which only kills sessions, not the detached daemon).

## When NOT to use

- To silence only the CURRENT project's heartbeat → use `/janitor-disarm`.
- To uninstall the plugin entirely → use Claude Code's plugin uninstall flow.

## Instructions

1. Set the kill-switch via the backing CLI (single source of truth for the flag
   path — never write the flag file by hand):

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/kill_switch_cli.py" set "stopped via /janitor-stop"
   ```

2. Report the one-line result the CLI prints. The daemon may take up to its loop
   interval (≤ 60 s) to notice the flag and exit; that is expected.

## Output

One line confirming the janitor is stopped machine-wide, with the reminder that
`/janitor-arm` revives it. No other side effects — only the kill-switch flag is
written (the daemon performs its own teardown).

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- The CLI never blocks; it writes the flag atomically and returns immediately.
- If the daemon was not running, the flag is still set (harmless) so a future
  lazy-spawn is suppressed until `/janitor-arm` clears it.

## Examples

```text
User: /janitor-stop
User: stop the janitor daemon
User: global stop the janitor everywhere
```

## Scope

ONLY sets the machine-wide kill-switch flag (via the backing CLI). Does NOT remove
the per-project heartbeat cron (that is `/janitor-disarm`), does NOT uninstall the
plugin, and does NOT delete any state. The daemon's own shutdown path removes the OS
keepalive; this skill just trips the switch.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/kill_switch_cli.py` — backing CLI (`set`/`clear`/`status`).
- `/janitor-arm` — clears the kill-switch and revives the daemon.
- `/janitor-disarm` — the narrower per-project heartbeat stop.
