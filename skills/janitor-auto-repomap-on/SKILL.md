---
name: janitor-auto-repomap-on
description: Enable the auto-maintained project map in this project's CLAUDE.md - generates the fenced repo-map block (one line per file + public symbols, convention-collapsed) and turns on the stale-map heartbeat nudge. Use when the user says "turn on the repo map", "enable the project map", "add the auto map to CLAUDE.md", "keep the CLAUDE.md map updated". Safe by construction - the generator holds a project lock, guards against concurrent CLAUDE.md edits (lost-update retry), verifies byte-preservation of the human narrative before every write, and backs up CLAUDE.md first. The janitor heartbeat itself NEVER rewrites CLAUDE.md (cache + co-ownership safety) - it only nudges.
---

# Janitor auto-repomap ON

## Overview

Turns ON the auto-maintained project map (TRDD-e247a349) for THIS project:
inserts the fenced `JANITOR-REPO-MAP` block into `CLAUDE.md` (generated from
the AST of every tracked source file, convention-collapsed) and sets the
project-scoped opt-in flag so the `project-map-drift` detector nudges when the
map goes stale. **The heartbeat never writes CLAUDE.md** — refreshes are run
by you/the agent via the generator, which carries the full anti-corruption
contract (lock, lost-update guard, byte-preservation invariant, backup,
atomic replace).

## Instructions

1. Set the project-scoped opt-in flag (atomic):

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   printf 'on' > "$STATE_DIR/repomap-opt-in.flag.tmp.$$" && \
     mv -f "$STATE_DIR/repomap-opt-in.flag.tmp.$$" "$STATE_DIR/repomap-opt-in.flag"
   ```

2. Generate + insert (or refresh) the fenced block. Pass `--exclude` globs for
   trees whose symbols would bloat the map (they persist, so later refreshes
   and `--check` use the same set; test trees are the usual exclusion):

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py" \
     --root "${CLAUDE_PROJECT_DIR:-$(pwd)}" --exclude 'tests/*'
   ```

   Exit 0 prints what was written (or "already current"). Exit 3 = safe bail
   (another generator holds the lock, CLAUDE.md is being actively edited, or
   the fences are malformed) — nothing was corrupted; re-run later.

3. Report one line: map size, file count, and that the drift nudge is armed.

## Cache discipline (when to refresh)

CLAUDE.md sits in the cached prompt prefix — rewriting it mid-session busts
the cache for the whole context. Run the generator at a CACHE-CHEAP moment:
a fresh session, right after a compaction, or just before a commit. The
`project-map-drift` nudge says exactly this when the map is stale.

## Output

The fenced block in `CLAUDE.md` (human narrative untouched — byte-verified),
the opt-in flag, a rolling backup at `.janitor/state/CLAUDE.md.pre-repomap.bak`,
and the persisted excludes at `.janitor/state/repomap-excludes.txt`.

## Error handling

- Lock held / active editing → exit 3, nothing written; re-run later.
- Malformed fences (a fence line was hand-edited) → exit 3 with the reason;
  fix the fence pair (or delete both fence lines and re-run to re-insert).
- No supported sources (non-Python project today; ts/go/rust adapters are
  TRDD-e247a349 P3) → exit 3, no flag harm.

## Scope

ONLY this project (flag + CLAUDE.md block + excludes are project-scoped).
Does NOT touch other projects, the daemon, or user-scope config. Disable with
`/janitor-auto-repomap-off` (removes the block AND the flag).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py` — the generator (the
  anti-corruption contract lives in its module docstring).
- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/project-map-drift.py` — the
  nudge-only heartbeat detector.
- `design/tasks/TRDD-20260528_203014+0200-e247a349-auto-project-map.md` — the
  full design (format, economics, acceptance criteria).
