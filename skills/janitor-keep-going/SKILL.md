---
name: janitor-keep-going
description: Opt this session into the janitor's never-stop continue-nudge — every due heartbeat prints a resume cue telling the agent to keep working on its pending task instead of silently idling between turns. Trigger with /janitor-keep-going, "keep going", "never stop", "don't stall between turns"; add "off" to disable.
---

# Janitor keep-going

## Overview

Keep-going mode makes every due heartbeat fire emit a `[janitor-resume]` cue plus a short
"continue your pending task" nudge, so an unattended agent never silently stalls between turns.
Without it, a FULL-mode heartbeat with nothing else to say (no rate-limit resume, no compact
resume, no drift) emits nothing at all — correct for an interactive session where a human is
watching, but wrong for an autonomous session that finished a turn mid-task with no external
trigger to continue.

**WHY it exists (TRDD-TKNSTP82 Part B, user 2026-07-02):** "even in maintenance mode the janitor
must nudge the agent to continue … they must never stop." Maintenance-mode ALREADY gets this
nudge unconditionally (see `/janitor-maintenance-mode`) — keep-going is the STANDALONE opt-in
for a session running in normal FULL mode that also wants the never-stop nudge, without giving
up detectors/daemon/drift reporting.

| trigger | scope | nudge fires when |
|---|---|---|
| `/janitor-maintenance-mode` | this session (or global) | every fire, unconditionally |
| `/janitor-keep-going` | this session only | every fire, ONLY while this flag is set |

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (locates `.janitor/state/`).
- The heartbeat is armed (`/janitor-arm`) — keep-going governs what an ARMED fire prints; with
  no cron there is nothing to nudge. With no cron it still records the flag so a later
  `/janitor-arm` honors it.

## Instructions

1. Parse the request into an action: contains "off" / "stop" / "disable" → action = OFF;
   otherwise ON.

2. **ON** — write the sentinel atomically:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   printf '%s' 'keep-going: never-stop continue-nudge active' > "$STATE_DIR/keep-going.tmp.$$"
   mv -f "$STATE_DIR/keep-going.tmp.$$" "$STATE_DIR/keep-going"
   ```

   **OFF** — remove it:

   ```bash
   rm -f "${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state/keep-going"
   ```

3. Report one line:
   - ON → `Janitor keep-going ON — every due heartbeat will nudge you to continue your pending task until you run /janitor-keep-going off.`
   - OFF → `Janitor keep-going OFF — heartbeats stop emitting the continue-nudge (maintenance mode, if active, still nudges on its own).`
   - If the heartbeat is not armed, append `Note: heartbeat not armed; run /janitor-arm to start firing.`

## Output

One line. Side effect: writes/removes `.janitor/state/keep-going`. No cron change — arm/disarm
is separate.

## Error handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)` (dispatch resolves the same path).
- Cannot create `$STATE_DIR` (permission denied) → report `Janitor keep-going failed: <error>`.

## Scope

ONLY sets/clears the keep-going flag for THIS session — unlike `/janitor-maintenance-mode`,
there is no `global` / fleet-wide variant. Does NOT arm/disarm the cron, run detectors, or
change any other config. To stop firing entirely, use `/janitor-disarm`; for a temporary
silence, `/janitor-pause`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — `_phase_keep_going_nudge(mode)` emits the
  `[janitor-resume]` + continue-nudge lines when this flag is present OR the session is in
  maintenance mode; called from `main()` right before the maintenance early-return so both
  modes get it.
- `$CLAUDE_PROJECT_DIR/.janitor/state/keep-going` — the per-session sentinel.
- `/janitor-maintenance-mode` — the sibling that gets this same nudge unconditionally, as part
  of its cache-refresh-only fires.

## Checklist

Copy this checklist and track your progress:

- [ ] Parse action (on/off) from the request
- [ ] ON: atomically write `.janitor/state/keep-going`
- [ ] OFF: remove `.janitor/state/keep-going`
- [ ] Report one line (note if the heartbeat is not armed)
