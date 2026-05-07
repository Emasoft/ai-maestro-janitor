---
name: janitor-pause
description: Suppresses ai-maestro-janitor heartbeat output without removing the cron. Use when starting a large refactor, doing focused exploration, or any block of work where drift nudges would be noise. Trigger with /janitor-pause, "pause the janitor", "silence the janitor for 2h", or "quiet the heartbeat for the rest of today".
---

# Janitor pause

## Overview

Writes a sentinel file `.janitor/state/paused` that `dispatch.sh` checks at the top of every heartbeat. While the file exists (and its expiry has not passed), all heartbeat fires exit silently with a single log entry — detectors do not run, drift lines are not emitted, the rate-limit resume cue is suppressed.

The cron itself stays armed. No `CronDelete` happens. When the pause expires (or `/janitor-resume` runs), the next heartbeat fires normally.

This is the lighter alternative to `/janitor-disarm`: pause when you want a quiet block of work; disarm when you're moving away from the project.

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (used to locate `.janitor/state/`).
- The janitor heartbeat is armed (otherwise pausing is a no-op).

## Instructions

1. Determine the pause duration from the user's request:
   - "pause indefinitely" / no duration → `EXPIRY=0`
   - "pause for 2h" / "for 30m" / "until 18:00" → compute `EXPIRY` as epoch seconds
   - Recognize `m` (minutes), `h` (hours), `d` (days) suffixes

2. Write the sentinel file atomically:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   printf '%s' "$EXPIRY" > "$STATE_DIR/paused.tmp.$$"
   mv -f "$STATE_DIR/paused.tmp.$$" "$STATE_DIR/paused"
   ```

3. Report the outcome in one line. If `EXPIRY=0`: `Janitor paused (no expiry — run /janitor-resume to lift).` Otherwise: `Janitor paused until <local-time-with-offset> (~<N>h<M>m from now).`

## Output

One line confirming the pause and its expiry. The next heartbeat will emit nothing until the expiry passes or `/janitor-resume` runs.

## Error Handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)`. The sentinel still works because `dispatch.sh` resolves the same path.
- Cannot create `$STATE_DIR` (permission denied) → abort with the error verbatim. Report `Janitor pause failed: <error>`.
- User asks for a past-time expiry → refuse, report `Janitor pause refused: expiry <ts> is in the past.`
- User asks to pause an already-paused janitor → overwrite the sentinel with the new expiry and report the new value.

## Examples

```text
User: /janitor-pause
User: pause the janitor
User: silence the janitor for 2h
User: pause until 18:00
User: quiet the heartbeat for the rest of today
```

## Scope

This skill ONLY writes the paused sentinel. It does not delete the cron, clear detector seen-files, modify state, or remove logs. To re-enable normal heartbeat behaviour, run `/janitor-resume` (or wait for the expiry to pass — `dispatch.sh` auto-cleans the sentinel on the first heartbeat after expiry).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh` — checks for `paused` sentinel and exits early when present and not expired.
- `$CLAUDE_PROJECT_DIR/.janitor/state/paused` — the sentinel file itself; first line is the expiry epoch (or `0` for indefinite).

## Checklist

Copy this checklist and track your progress:

- [ ] Parse the user's duration request (or default to indefinite)
- [ ] Compute `EXPIRY` as epoch seconds (or `0`)
- [ ] Atomically write the sentinel via tmp+rename
- [ ] Report the pause outcome in one line, including the local-time expiry if set
