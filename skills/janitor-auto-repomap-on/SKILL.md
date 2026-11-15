---
name: janitor-auto-repomap-on
description: Enable the auto-maintained project map - generates the root PROJECT_MAP.md (one line per file + public symbols, convention-collapsed, git-excluded) and turns on the stale-map heartbeat nudge. Use when the user says "turn on the repo map", "enable the project map", "add the auto map". Safe by construction - the generator holds a project lock, refuses a tracked map file, verifies the write, and backs up CLAUDE.md before the one-time legacy-fence strip. The heartbeat itself NEVER writes the map or CLAUDE.md - it only nudges.
---

# Janitor auto-repomap ON

## Overview

Turns ON the auto-maintained project map (TRDD-e247a349) for THIS project:
writes the generated map (from the AST of every tracked source file,
convention-collapsed) to the root `PROJECT_MAP.md`, git-excluded via the path
`git rev-parse --git-path info/exclude` names, and sets the project-scoped opt-in
flag so the `project-map-drift` detector nudges when the map goes stale. The first
generate also strips a legacy `JANITOR-REPO-MAP` fence from `CLAUDE.md` once.
**The heartbeat never writes anything** — refreshes are run by you/the agent via
the generator, which carries the full anti-corruption contract (lock, lost-update
guard, byte-preservation invariant, backup, atomic replace).

## Instructions

1. Set the project-scoped opt-in flag (atomic):

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   printf 'on' > "$STATE_DIR/repomap-opt-in.flag.tmp.$$" && \
     mv -f "$STATE_DIR/repomap-opt-in.flag.tmp.$$" "$STATE_DIR/repomap-opt-in.flag"
   ```

2. Generate (or refresh) the root `PROJECT_MAP.md`. Pass `--exclude` globs for
   trees whose symbols would bloat the map (they persist in the tracked `.repomapignore`,
   so later refreshes and `--check` use the same set; test trees are the usual exclusion):

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py" \
     --root "${CLAUDE_PROJECT_DIR:-$(pwd)}" --exclude 'tests/*'
   ```

   Exit 0 prints what was written (or "already current"). Exit 3 = safe bail
   (another generator holds the lock, `PROJECT_MAP.md` is tracked by git, or a legacy
   CLAUDE.md fence is malformed or being edited) — nothing was corrupted; re-run later.

3. Report one line: map size, file count, and that the drift nudge is armed.

## Cache note

The map lives in its own file, not in `CLAUDE.md`, so a refresh never touches `CLAUDE.md`
(apart from the one-time legacy-fence strip) and can run at any time. A `CLAUDE.md` write
mid-session does NOT measurably bust the cache (MEASURED 2026-08-26, TRDD-LFSWY0C6: across
307 turns right after a CLAUDE.md edit the median cache_creation was 1,525 tokens), so
there is no cache-cheap moment to wait for. The `project-map-drift` nudge says when the map
is stale.

## Output

The root `PROJECT_MAP.md` (generated, git-excluded via the path
`git rev-parse --git-path info/exclude` names, never committed), the opt-in flag, and the
persisted excludes in the tracked `.repomapignore`. The first generate also strips a
legacy map fence from `CLAUDE.md` once (human narrative byte-verified; rolling backup at
`.janitor/state/CLAUDE.md.pre-repomap.bak`).

## Error handling

- Lock held → exit 3, nothing written; re-run later.
- `PROJECT_MAP.md` already tracked by git, or not ignorable → exit 3; untrack it and re-run.
- A legacy `CLAUDE.md` map fence that is malformed, or a `CLAUDE.md` being edited at that
  moment → exit 3 with the reason; fix the fence pair (or delete both fence lines) and re-run.
- No supported sources (non-Python project today; ts/go/rust adapters are
  TRDD-e247a349 P3) → exit 3, no flag harm.

## Scope

ONLY this project (flag + `PROJECT_MAP.md` + excludes are project-scoped).
Does NOT touch other projects, the daemon, or user-scope config. Disable with
`/janitor-auto-repomap-off` (removes the generated map file AND the flag).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/repomap_generate.py` — the generator (the
  anti-corruption contract lives in its module docstring).
- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/project-map-drift.py` — the
  nudge-only heartbeat detector.
- `design/tasks/TRDD-20260528_203014+0200-e247a349-auto-project-map.md` — the
  full design (format, economics, acceptance criteria).
