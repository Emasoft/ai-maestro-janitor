---
name: janitor-auto-manage-oauth-both
description: Turns OAuth auto-rotation ON or OFF on BOTH sides at once - the janitor's opt-in flag and the ai-maestro server's R16 flag file - so the two halves can never disagree. Pass on or off. Writes both flags or neither. Trigger with /janitor-auto-manage-oauth-both on|off, "turn oauth rotation on for janitor and server", or "disable rotation on both sides".
---

# Janitor auto-manage OAuth both

## Overview

`/janitor-auto-manage-oauth-on` and `-off` only touch the janitor's `opt-in.flag`. The ai-maestro
server has its own gate, `~/.aimaestro/oauth-rotator-tick.enabled` (presence enables its rotation
tick). This skill flips both together; which owner actually runs the chore while both are ON is
decided by the ORH lease, never by this command. A disagreeing start is driven to the requested
state. If the second write fails the first is undone and the command exits non-zero.

OFF renames the server flag to `oauth-rotator-tick.enabled.DISABLED-<date>-janitor-toggle`
(nothing is deleted).

## Instructions

1. Run, with `on` or `off` as the argument:

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/oauth_rotation_toggle.py" on
   ```

2. For `on`, the preconditions of `/janitor-auto-manage-oauth-on` (no pinning env var, macOS) still
   apply to the janitor side; run that skill's checks first if unsure.

## Output

One line: `OAuth rotation: ON|OFF on both sides`. Exit 1 on a failed write (janitor side restored),
2 on a bad argument.

## Error Handling

- `CLAUDE_PLUGIN_DATA` unset: abort, nothing written.
- Server state dir not writable: janitor flag restored, exit 1.

## Examples

```text
User: /janitor-auto-manage-oauth-both off
```

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/oauth_rotation_toggle.py`

## Checklist

- [ ] Run the script with on or off
- [ ] Confirm the one-line output
