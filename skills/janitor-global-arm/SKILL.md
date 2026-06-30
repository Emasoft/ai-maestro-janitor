---
name: janitor-global-arm
description: Revives a globally-disarmed ai-maestro-janitor by clearing BOTH machine-wide flags that /janitor-global-disarm set — the kill-switch AND the global-pause flag — so the next heartbeat re-spawns the daemon and every per-session heartbeat resumes running detectors. The full-revive half of /janitor-global-disarm. Trigger with /janitor-global-arm, "revive the janitor daemon", "globally re-arm the janitor", "undo the global disarm".
---

# Janitor global arm (machine-wide revive)

## Overview

Clears BOTH machine-wide flags `/janitor-global-disarm` set — the kill-switch (so the
daemon can be lazy-spawned again) AND the global-pause flag (so every per-session
heartbeat resumes running detectors). This is the **full-revive** half of the global
true-stop pair. After this runs, the next per-session heartbeat will spawn a fresh
daemon (which, on a published install, re-installs its OS keepalive) and stop being
silent.

This is distinct from `/janitor-arm`, which arms only THIS project's heartbeat cron
and deliberately does not touch the global kill-switch. Use `/janitor-global-arm`
after a `/janitor-global-disarm`; use `/janitor-global-unpause` after a
`/janitor-global-pause`.

## Instructions

1. Clear the kill-switch via the backing CLI:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" arm
   ```

2. Report the one-line result. The daemon is spawned by the next heartbeat fire (or
   immediately by `ensure_daemon_running` on the next session tick) — there is no
   re-spawn to wait on synchronously here.

## Output

One line confirming the global disarm was cleared. If no kill-switch was set, the
call is a harmless no-op.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- Clearing a kill-switch that is not present is idempotent (no error).

## Examples

```text
User: /janitor-global-arm
User: revive the janitor daemon
User: undo the global disarm
```

## Scope

Clears BOTH machine-wide flags (the kill-switch + the global-pause flag) via the
backing CLI — the full reverse of `/janitor-global-disarm`. Does NOT arm any
per-project heartbeat cron (that is `/janitor-arm`) and does NOT spawn the daemon
itself (the next heartbeat does). A pause set ALONE via `/janitor-global-pause` is
more precisely lifted by `/janitor-global-unpause`, though `arm` also clears it.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI.
- `/janitor-global-disarm` — sets the kill-switch this skill clears.
- `/janitor-arm` — the narrower per-project heartbeat arm.
