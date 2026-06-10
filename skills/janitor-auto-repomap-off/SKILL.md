---
name: janitor-auto-repomap-off
description: Disable the auto-maintained project map - removes the fenced repo-map block from this project's CLAUDE.md entirely (human narrative untouched, byte-preserved) and clears the opt-in flag so the stale-map heartbeat nudge stops. Use when the user says "turn off the repo map", "remove the auto map from CLAUDE.md", "disable the project map", "stop the repomap nudges".
---

# Janitor auto-repomap OFF

## Overview

Turns OFF the auto-maintained project map (TRDD-e247a349) for THIS project:
splices the fenced `JANITOR-REPO-MAP` block out of `CLAUDE.md` (everything
outside the fences is preserved byte-for-byte; the removal is atomic and
backed up) and clears the project-scoped opt-in flag so the
`project-map-drift` detector goes back to a total no-op.

## Instructions

1. Remove the fenced block (atomic; backs up CLAUDE.md first; takes the same
   generator lock as writes, so it can never interleave with a refresh):

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py" \
     --root "${CLAUDE_PROJECT_DIR:-$(pwd)}" --remove
   ```

2. Clear the opt-in flag:

   ```bash
   rm -f "${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state/repomap-opt-in.flag"
   ```

3. Report one line: block removed (or "no block"), nudge disarmed.

## Output

`CLAUDE.md` without the fenced block (narrative untouched), no opt-in flag.
The rolling backup at `.janitor/state/CLAUDE.md.pre-repomap.bak` and the
persisted excludes file are left in place (harmless state; re-enabling reuses
the excludes).

## Error handling

- No block present → exit 0, "no map block to remove" (flag still cleared).
- Malformed fences → exit 3, CLAUDE.md untouched — fix the fence pair by hand
  (the block is plain text between two unique marker lines).
- Lock held → exit 3; re-run in a moment.

## Scope

ONLY this project. Re-enable any time with `/janitor-auto-repomap-on`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py` — the backing script
  (`--remove` path).
- `/janitor-auto-repomap-on` — the enable side.
