---
name: janitor-global-pause
description: Temporarily SUSPENDS the ai-maestro-janitor machine-wide without tearing it down — the global daemon stays alive but idles (runs no tasks), and every session's heartbeat goes silent. The teardown-free sibling of /janitor-global-disarm. Use for a quiet block across ALL projects. Trigger with /janitor-global-pause, "pause all janitors", "globally quiet the janitor", "silence every janitor heartbeat".
---

# Janitor global pause (machine-wide suspend)

## Overview

Suspends ALL janitor activity machine-wide **without tearing anything down** by
setting the global-pause flag:

- the daemon stays **alive** (keeps ticking its heartbeat so it is never seen as
  wedged) but **idles** — it runs no task workloads while paused;
- every session's heartbeat fire exits silently — no detectors, no drift lines.

This is the lighter, instant-resume sibling of `/janitor-global-disarm` (which makes
the daemon EXIT and removes its keepalive). Pause when you want a quiet block across
every project; disarm when you want a true machine-wide stop. The per-project
equivalent is `/janitor-pause`.

To resume: `/janitor-global-unpause` (instant — the daemon was never stopped, so
there is no re-spawn).

## Instructions

1. Set the global-pause flag via the backing CLI:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" pause "via /janitor-global-pause"
   ```

2. Report the one-line result. The daemon stops running tasks within ≤ 60 s and
   resumes within ~1 s of an unpause.

## Output

One line confirming the janitor is paused machine-wide, with the reminder that
`/janitor-global-unpause` resumes it. Only the global-pause flag is written; nothing
is torn down.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- The CLI writes the flag atomically and returns immediately; it never blocks.
- A global PAUSE does not override a global DISARM — if the daemon is disarmed
  (kill-switch set) it is already stopped; pausing is moot until `/janitor-global-arm`.

## Examples

```text
User: /janitor-global-pause
User: pause all janitors for a bit
User: globally quiet the janitor
```

## Scope

ONLY sets the machine-wide global-pause flag (via the backing CLI). Does NOT remove
any cron, does NOT stop the daemon process, does NOT remove the OS keepalive, and
does NOT delete state. It is a teardown-free, instantly-reversible suspend.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI.
- `/janitor-global-unpause` — lifts this pause.
- `/janitor-global-disarm` — the heavier machine-wide true stop (daemon exits).
- `/janitor-pause` — the per-project suspend.
