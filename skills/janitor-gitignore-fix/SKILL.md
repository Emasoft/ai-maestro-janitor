---
name: janitor-gitignore-fix
description: Remedy for a gitignore-coverage / ADVISORY-GITIGNORE-COVER finding — a private class (`.env`, `*.key`, `reports/`, …) missing from `.gitignore`, or a private file already tracked. Plan-first: shows the proposed `.gitignore` diff and the exact `git rm --cached` lines, mutates nothing until you confirm. Trigger with /janitor-gitignore-fix or when asked to "fix the gitignore", "cover the missing patterns", or after a gitignore-coverage heartbeat line.
---

# Janitor gitignore-fix

## Overview

The `gitignore-coverage` detector only SURFACES two faults — a private class with no
`.gitignore` rule, or a private file already tracked despite (or without) one. This skill
is the remedy: it shows the proposed fix and applies it only on confirmation.

## Instructions

1. Resolve `SCRIPT_PATH` = `${CLAUDE_PLUGIN_ROOT}/scripts/gitignore_fix.py`.

2. Run it in **propose mode** (read-only, default):

   ```bash
   uv run "$SCRIPT_PATH" [--repo <path>]
   ```

3. Surface its output verbatim: the unified `.gitignore` diff (missing patterns appended
   at the end, existing lines and negations untouched) and, if any private file is already
   tracked, the exact `git rm --cached <path>` line for each.

4. If there is nothing to propose, say so and stop — do not ask for confirmation.

5. If there is a proposal, **ask the user to confirm** (AskUserQuestion) before doing
   anything further. A refused confirmation leaves `.gitignore` and the index untouched —
   stop here.

6. On confirmation, for the `.gitignore` append only:

   ```bash
   uv run "$SCRIPT_PATH" --apply [--repo <path>]
   ```

   This writes ONLY the missing pattern lines to the end of `.gitignore`. It never touches
   the git index.

7. For tracked private files, **you** (the agent) run the printed `git rm --cached <path>`
   commands yourself, one by one, only for paths the user confirmed — the script never runs
   them. This is a working-tree-safe untrack (the file stays on disk, only the index entry
   is removed); never follow it with a working-tree delete.

## Scope

Reads `lib/gitignore_coverage.py`'s private-class table — the same table the
`gitignore-coverage` detector uses. Never proposes ignoring or untracking anything under
the protected prefixes (`design/**`, `.claude/project/memory/**`) — those are deliberately
tracked, shared PROJECT-scope content.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/gitignore_fix.py` — backing script.
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/gitignore_coverage.py` — the private-class table (single
  source of truth).

## Checklist

Copy this checklist and track your progress:

- [ ] Run `gitignore_fix.py` in propose mode, surface the diff + `git rm --cached` lines
- [ ] Nothing to propose → say so, stop
- [ ] Something to propose → ask the user to confirm before any write
- [ ] Confirmed → run `gitignore_fix.py --apply` for the `.gitignore` append
- [ ] Confirmed tracked-file removals → run `git rm --cached <path>` yourself, per path
- [ ] Refused → leave `.gitignore` and the index untouched
