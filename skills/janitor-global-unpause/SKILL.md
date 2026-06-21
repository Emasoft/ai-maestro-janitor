---
name: janitor-global-unpause
description: Lifts a machine-wide ai-maestro-janitor pause set by /janitor-global-pause, so the global daemon resumes running tasks and every session's heartbeat resumes emitting drift. The resume half of /janitor-global-pause. Trigger with /janitor-global-unpause, "unpause all janitors", "resume the janitor everywhere", "lift the global janitor pause".
---

# Janitor global unpause (machine-wide resume)

## Overview

Clears the global-pause flag set by `/janitor-global-pause`. The daemon — which was
idling, not stopped — resumes running due tasks on its next loop (within ~1 s), and
every session's heartbeat resumes emitting drift lines. There is nothing to re-spawn,
because a pause never tore anything down.

This lifts a PAUSE only. To revive a daemon that was truly stopped with
`/janitor-global-disarm`, use `/janitor-global-arm` instead.

## Instructions

1. Clear the global-pause flag via the backing CLI:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" unpause
   ```

2. Report the one-line result. The daemon resumes work within ~1 s of the flag
   clearing.

## Output

One line confirming the machine-wide pause was lifted. If no pause was set, the call
is a harmless no-op.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- Clearing a global-pause that is not present is idempotent (no error).

## Examples

```text
User: /janitor-global-unpause
User: unpause all janitors
User: resume the janitor everywhere
```

## Scope

ONLY clears the machine-wide global-pause flag (via the backing CLI). Does NOT clear
a global DISARM (that is `/janitor-global-arm`), does NOT lift a per-project pause
(that is `/janitor-unpause`), and does NOT arm any cron.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI.
- `/janitor-global-pause` — sets the global-pause flag this skill clears.
- `/janitor-global-arm` — the revive for a true DISARM (different flag).
- `/janitor-unpause` — the per-project pause lift.
