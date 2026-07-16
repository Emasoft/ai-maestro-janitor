---
name: janitor-keep-going
description: Control the janitor's never-stop continue-nudge for this session — every due heartbeat prints a resume cue telling the agent to keep working on its pending task instead of silently idling between turns. The nudge is ON BY DEFAULT (user directive 2026-07-16); this skill re-asserts it after an opt-out, or turns it off. Trigger with /janitor-keep-going, "keep going", "never stop", "don't stall between turns"; add "off" to disable this session's full-mode nudge.
---

# Janitor keep-going

## Overview

Keep-going mode makes every due heartbeat fire emit a `[janitor-resume]` cue plus a short
"continue your pending task" nudge, so an unattended agent never silently stalls between turns.
As of the 2026-07-16 user directive this nudge is **ON BY DEFAULT** in every mode — the whole
point of the janitor is to keep the fleet working in the user's absence, and a FULL-mode
heartbeat that stayed silent (no rate-limit resume, no compact resume, no drift) let unattended
agents idle overnight. This skill's ON path re-asserts the default after an opt-out; its OFF path
writes the explicit opt-out sentinel that silences THIS session's full-mode nudge.

**WHY it exists (TRDD-TKNSTP82 Part B, user 2026-07-02; DEFAULT-ON user 2026-07-16):** "even in
maintenance mode the janitor must nudge the agent to continue … they must never stop." Maintenance
mode nudges unconditionally (see `/janitor-maintenance-mode`); full mode now nudges by default too,
without giving up detectors/daemon/drift reporting. The default is set by the `keep_going_default`
config knob (true); set it false to restore the pre-2026-07-16 opt-IN behaviour.

| trigger | scope | nudge fires when |
|---|---|---|
| default (`keep_going_default=true`) | every armed session | every fire, unless opted out |
| `/janitor-maintenance-mode` | this session (or global) | every fire, unconditionally |
| `/janitor-keep-going off` | this session only | writes the opt-out that silences full-mode fires |

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (locates `.janitor/state/`).
- The heartbeat is armed (`/janitor-arm`) — keep-going governs what an ARMED fire prints; with
  no cron there is nothing to nudge. With no cron it still records the flag so a later
  `/janitor-arm` honors it.

## Instructions

1. Parse the request into an action: contains "off" / "stop" / "disable" → action = OFF;
   otherwise ON.

   The nudge is **ON BY DEFAULT** (user directive 2026-07-16): every armed session
   nudges in every mode unless explicitly turned off. So ON clears the opt-out sentinel,
   and OFF *writes* it (removing the on-flag alone would not silence the default).

2. **ON** — clear the opt-out sentinel and (re)assert the on-flag atomically:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   rm -f "$STATE_DIR/keep-going-off"          # clear the explicit opt-out (default-ON resumes)
   printf '%s' 'keep-going: never-stop continue-nudge active' > "$STATE_DIR/keep-going.tmp.$$"
   mv -f "$STATE_DIR/keep-going.tmp.$$" "$STATE_DIR/keep-going"
   ```

   **OFF** — write the explicit opt-out sentinel (the ONE lever that silences the
   default full-mode nudge) and drop the on-flag:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   rm -f "$STATE_DIR/keep-going"              # drop the on-flag
   printf '%s' 'keep-going-off: full-mode continue-nudge suppressed' > "$STATE_DIR/keep-going-off.tmp.$$"
   mv -f "$STATE_DIR/keep-going-off.tmp.$$" "$STATE_DIR/keep-going-off"
   ```

   OFF silences only FULL-mode fires — maintenance mode always nudges and is exited with
   `/janitor-maintenance-mode off`.

3. Report one line:
   - ON → `Janitor keep-going ON — every due heartbeat nudges you to continue your pending task (this is the default; the opt-out is cleared).`
   - OFF → `Janitor keep-going OFF — full-mode heartbeats stop emitting the continue-nudge (a deliberate opt-out; maintenance mode, if active, still nudges on its own).`
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
