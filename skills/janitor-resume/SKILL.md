---
name: janitor-resume
description: Lifts an ai-maestro-janitor pause set by /janitor-pause, restoring normal heartbeat output. Use when ending a focus block, after a refactor lands, or any time the user explicitly wants drift nudges back on. Trigger with /janitor-resume, "resume the janitor", "unpause the heartbeat", or "the janitor is too quiet".
---

# Janitor resume

## Overview

Removes the `.janitor/state/paused` sentinel that `/janitor-pause` wrote. The next heartbeat fire will run all detectors normally and emit drift lines if anything has changed during the pause window.

This is a no-op if no pause is active — calling it on a fresh project (or after an expiry has already auto-lifted the pause) is safe and idempotent.

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
   - If the sentinel existed and had no expiry: `Janitor resumed (was paused indefinitely).`
   - If it existed with an expiry: `Janitor resumed (was paused until <local-time-with-offset>).`
   - If it did not exist: `Janitor resumed (was not paused — no-op).`

## Output

One line confirming the resume. The next heartbeat will run normally.

## Error Handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)`.
- Sentinel file not present → success. Report the no-op variant.
- `rm -f` fails (permission, read-only filesystem) → abort with the error verbatim. Report `Janitor resume failed: <error>`.

## Examples

```text
User: /janitor-resume
User: resume the janitor
User: unpause the heartbeat
User: the janitor is too quiet
```

## Scope

This skill ONLY removes the paused sentinel. It does not arm the cron, restart any detectors mid-fire, or clear seen-files. If `/janitor-arm` was never run (no cron exists), `/janitor-resume` cannot create one — run `/janitor-arm` for that.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh` — no longer skips early once the sentinel is removed.
- `$CLAUDE_PROJECT_DIR/.janitor/state/paused` — the sentinel removed by this skill.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `$STATE_DIR` from `$CLAUDE_PROJECT_DIR` (fallback to `$(pwd)`)
- [ ] Read expiry from sentinel for the report (if it exists)
- [ ] Remove the sentinel via `rm -f`
- [ ] Report one line covering all three cases (was-indefinite, was-expiry, was-not-paused)
