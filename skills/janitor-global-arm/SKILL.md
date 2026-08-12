---
name: janitor-global-arm
description: FLAG-ONLY revive of a globally-disarmed ai-maestro-janitor — clears the machine-wide kill-switch /janitor-global-disarm set, so the daemon may respawn and every already-armed per-session heartbeat resumes firing. Does NOT arm any per-project heartbeat cron and does NOT fan out across projects (that is /janitor-arm, run inside each project). Trigger with /janitor-global-arm, "revive the janitor daemon", "globally re-arm the janitor", "undo the global disarm".
---

# Janitor global arm (machine-wide FLAG-ONLY revive)

## ⚠ Not a fleet arm — read this first (janitor#77)

**This command arms nothing.** It clears the one machine-wide STOP flag (the
kill-switch) that `/janitor-global-disarm` sets. It does **not** create,
renew, or touch any per-project heartbeat cron anywhere — a project whose
cron already died, or never existed, stays exactly that way after this runs.
The only thing that creates a project's cron is `/janitor-arm`, run **inside
that project's own session**. If the name reads as "arm the whole fleet",
that reading is wrong; the CLI's own printed output repeats this warning so
it is never silently missed.

## Overview

Clears the machine-wide kill-switch `/janitor-global-disarm` set, so the next
heartbeat may lazy-spawn a fresh daemon and every session whose heartbeat is
still armed resumes firing. This is the **revive** half of the global
true-stop pair (`/janitor-global-disarm` ↔ `/janitor-global-arm`).

Pause and maintenance mode are **retired** (owner directive 2026-07-31) —
they left the daemon resident and every heartbeat firing while doing no work,
which from the outside was indistinguishable from a healthy fleet. There is
nothing left to "unpause"; `/janitor-global-pause` / `/janitor-global-unpause`
no longer exist. `arm` still sweeps any retired pause/maintenance flag an
older version may have left on disk, so an upgraded host never looks
suspended.

This is distinct from `/janitor-arm`, which arms only THIS project's
heartbeat cron and deliberately does not touch the global kill-switch.

## Instructions

1. Clear the kill-switch via the backing CLI:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" arm
   ```

2. Relay the printed result **verbatim** — it already states the FLAG-ONLY
   scope in its own words, so paraphrasing it risks dropping the warning. The
   daemon is spawned by the next heartbeat fire (or immediately by
   `ensure_daemon_running` on the next session tick) — there is no re-spawn
   to wait on synchronously here.

## Output

One line confirming the global kill-switch was cleared, explicitly stating
that no per-project cron was touched. If no kill-switch was set, the call is
a harmless no-op.

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

Clears the machine-wide kill-switch (and sweeps any retired pause/maintenance
flag) via the backing CLI. Does **NOT** arm any per-project heartbeat cron —
that is `/janitor-arm`, run per-project — and does **NOT** fan out across the
fleet. A true fleet-wide arm (re-arming every project's cron from one
command) does not exist yet: it needs either the daemon's keystroke-injection
channel or the ai-maestro server's command queue, and neither is wired for
this today (janitor#77, item B — the server isn't running on a plain
install, so that channel isn't exercisable). Wiring that fan-out is a
separate, larger change; this skill does not silently promise it. Does NOT
spawn the daemon itself (the next heartbeat does).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI.
- `/janitor-global-disarm` — sets the kill-switch this skill clears.
- `/janitor-arm` — the per-project heartbeat arm (run inside EACH project
  that needs one; this skill does not fan out to it).
