---
name: janitor-unpause
description: Lifts an ai-maestro-janitor pause set by /janitor-pause, restoring normal heartbeat output for THIS project. Use when ending a focus block, after a refactor lands, or any time the user explicitly wants drift nudges back on. Trigger with /janitor-unpause, "unpause the janitor", "lift the janitor pause", or "the janitor is too quiet".
---

# Janitor unpause

## Overview

Removes the `.janitor/state/paused` sentinel that `/janitor-pause` wrote. The next
heartbeat fire will run all detectors normally and emit drift lines if anything has
changed during the pause window.

This is a no-op if no pause is active — calling it on a fresh project (or after an
expiry has already auto-lifted the pause) is safe and idempotent.

This lifts only THIS project's pause. For a machine-wide pause across all projects,
the equivalent is `/janitor-global-unpause`.

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (used to locate `.janitor/state/`).

## Instructions

1. Locate the sentinel and check whether one is active:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   sentinel="$STATE_DIR/paused"
   ```

2. Read the expiry (first line) for the report.

3. Remove the sentinel atomically:

   ```bash
   rm -f "$sentinel"
   ```

4. Report one line:
   - If the sentinel existed and had no expiry: `Janitor unpaused (was paused indefinitely).`
   - If it existed with an expiry: `Janitor unpaused (was paused until <local-time-with-offset>).`
   - If it did not exist: `Janitor unpaused (was not paused — no-op).`

## Output

One line confirming the unpause. The next heartbeat will run normally.

## Error Handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)`.
- Sentinel file not present → success. Report the no-op variant.
- `rm -f` fails (permission, read-only filesystem) → abort with the error verbatim. Report `Janitor unpause failed: <error>`.

## Examples

```text
User: /janitor-unpause
User: unpause the janitor
User: lift the janitor pause
User: the janitor is too quiet
```

## Scope

This skill ONLY removes the paused sentinel for THIS project. It does not arm the
cron, restart any detectors mid-fire, clear seen-files, or touch the machine-wide
global pause (that is `/janitor-global-unpause`). If `/janitor-arm` was never run (no
cron exists), `/janitor-unpause` cannot create one — run `/janitor-arm` for that.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — no longer skips early once the sentinel is removed.
- `$CLAUDE_PROJECT_DIR/.janitor/state/paused` — the sentinel removed by this skill.
- `/janitor-pause` — sets the sentinel this skill removes.
- `/janitor-global-unpause` — the machine-wide equivalent.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `$STATE_DIR` from `$CLAUDE_PROJECT_DIR` (fallback to `$(pwd)`)
- [ ] Read expiry from sentinel for the report (if it exists)
- [ ] Remove the sentinel via `rm -f`
- [ ] Report one line covering all three cases (was-indefinite, was-expiry, was-not-paused)
