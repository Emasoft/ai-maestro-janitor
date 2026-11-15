---
name: janitor-auto-repomap-off
description: Disable the auto-maintained project map - deletes the generated root PROJECT_MAP.md (only a file the generator wrote) and clears the opt-in flag so the stale-map heartbeat nudge stops. Use when the user says "turn off the repo map", "remove the auto map", "disable the project map", "stop the repomap nudges".
---

# Janitor auto-repomap OFF

## Overview

Turns OFF the auto-maintained project map (TRDD-e247a349) for THIS project:
deletes the generated root `PROJECT_MAP.md` (a file this generator wrote; a
hand-written one is never removed) and clears the project-scoped opt-in flag so
the `project-map-drift` detector goes back to a total no-op. `CLAUDE.md` is
not touched.

## Instructions

1. Remove the generated map file (only one this generator wrote, recognized by its
   header; takes the same generator lock as writes, so it can never interleave with a refresh):

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py" \
     --root "${CLAUDE_PROJECT_DIR:-$(pwd)}" --remove
   ```

2. Clear the opt-in flag:

   ```bash
   rm -f "${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state/repomap-opt-in.flag"
   ```

3. Report one line: map file removed (or "no map file"), nudge disarmed.

## Output

No generated `PROJECT_MAP.md` at the project root, no opt-in flag; `CLAUDE.md` is never
touched. The rolling backup at `.janitor/state/CLAUDE.md.pre-repomap.bak` (from the
one-time legacy-fence strip) and the persisted excludes in `.repomapignore` are left in
place (harmless state; re-enabling reuses the excludes).

## Error handling

- No `PROJECT_MAP.md` present → exit 0, "no PROJECT_MAP.md to remove" (flag still cleared).
- `PROJECT_MAP.md` without a generated-map header (hand-written) → exit 3, file left in
  place; delete it yourself if it is really unwanted.
- Lock held → exit 3; re-run in a moment.

## Scope

ONLY this project. Re-enable any time with `/janitor-auto-repomap-on`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py` — the backing script
  (`--remove` path).
- `/janitor-auto-repomap-on` — the enable side.
