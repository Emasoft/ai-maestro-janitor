---
name: janitor-global-pause
description: Temporarily SUSPENDS the ai-maestro-janitor machine-wide without tearing the daemon down — the global daemon stays alive but idles (runs no tasks), and every armed session's heartbeat self-disarms (deletes its own cron) so it is truly free, not just silenced. The keep-the-daemon sibling of /janitor-global-disarm (which also exits the daemon). Use for a quiet block across ALL projects. Trigger with /janitor-global-pause, "pause all janitors", "globally quiet the janitor", "silence every janitor heartbeat".
---

# Janitor global pause (machine-wide suspend)

## Overview

Suspends the janitor machine-wide **without tearing down the daemon** by setting the
global-pause flag:

- the daemon stays **alive** (keeps ticking its heartbeat so it is never seen as
  wedged) but **idles** — it runs no task workloads while paused;
- every armed session's heartbeat **self-disarms** — on its next fire `dispatch.py`
  sees the global-pause flag and emits a bare `[janitor-self-disarm]` marker, so the
  session runs `/janitor-disarm` and **deletes its own cron** (TRDD-RQ9FIFX6). This is
  a TRUE stop, not a silence: a cron FIRE is a full Claude turn that re-reads the whole
  session context (~618k cached tokens, billed at the 0.1× cache-read rate, **not**
  free) whether or not detectors run, so the only way a fired turn costs zero is to
  stop firing.

So `/janitor-global-pause` is the **"stop every project's heartbeat but keep the
daemon"** control — the sibling of `/janitor-global-disarm`, which ALSO makes the
daemon EXIT and removes its keepalive. The per-project equivalent is `/janitor-pause`.

To resume: `/janitor-global-unpause` clears the flag (the daemon was never stopped, so
it needs no re-spawn); re-arm each session with `/janitor-arm` to restart its heartbeat.

**Rollout caveat.** The `[janitor-self-disarm]` marker is baked into the cron prompt at
arm time, so crons armed BEFORE this shipped won't self-disarm on their own — run
`/janitor-disarm` once in each such session (or `/janitor-arm` to pick up the new prompt).

## Instructions

1. Set the global-pause flag via the backing CLI:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" pause "via /janitor-global-pause"
   ```

2. Report the one-line result. The daemon stops running tasks within ≤ 60 s and
   resumes within ~1 s of an unpause.

## Output

One line confirming the janitor is paused machine-wide, with the reminder that
`/janitor-global-unpause` resumes it. Only the global-pause flag is written; the daemon
is not torn down.

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

ONLY sets the machine-wide global-pause flag (via the backing CLI); it does not itself
touch any cron, the daemon process, the OS keepalive, or state. The flag's downstream
effect is that each armed session's heartbeat self-disarms (deletes its own cron) on its
next fire, while the daemon idles — both reverse via `/janitor-global-unpause` (the
daemon needs no re-spawn; sessions re-arm with `/janitor-arm`).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI.
- `/janitor-global-unpause` — lifts this pause.
- `/janitor-global-disarm` — the heavier machine-wide true stop (daemon exits).
- `/janitor-pause` — the per-project suspend.
