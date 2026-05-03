---
name: janitor-safe-delete
description: Recoverable alternative to rm. Use when an agent needs to delete, remove, dispose of, prune, or clean up files or directories inside a project — especially when a hook blocks rm or CLAUDE.md RULE 0 forbids deleting uncommitted files. Moves targets into project-local .trashcan/[timestamp]/ plus a sibling .txt manifest, so recovery is a single mv on any platform. Trigger with /janitor-safe-delete or by asking the janitor to "safe-delete", "trash", or "dispose of" something.
---

# Janitor safe-delete

## Overview

Disposes of files or directories without `rm`. Each invocation moves the
named paths into the project's `.trashcan/<timestamp>/` folder, mirroring
the original layout, and writes a sibling `<timestamp>.txt` manifest with
one project-relative path per line. Nothing is deleted; the move is
reversible on any platform. See README.md for the rationale,
survival-against-`git clean -fdx` mechanism, and restore recipes.

## Prerequisites

- `ai-maestro-janitor` plugin installed (project scope).
- `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh` resolvable from the
  current session (Claude Code sets `CLAUDE_PLUGIN_ROOT`).
- Bash for invocation. Skill access is not required — agents with no
  Skill tool can call the script directly through Bash.

## Instructions

1. Resolve `SCRIPT_PATH` = `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh`.

2. Parse `$ARGUMENTS` into a whitespace-separated list of paths. Treat
   quoted paths as single tokens. Do not glob — the shell will, and the
   script's safety check refuses anything outside the project root.

3. If no paths were supplied, abort with the message:
   `Usage: /janitor-safe-delete <path>... — give me one or more paths.`

4. Invoke the script via Bash, forwarding paths after `--`:

   ```bash
   bash "$SCRIPT_PATH" -- path1 path2 ...
   ```

   The leading `--` ensures paths starting with `-` are treated as
   positional arguments. Hoist `--dry-run` or `-n` before `--` if the
   user passed it.

5. Surface the script's stdout verbatim. The script already prints a
   complete report: items moved, manifest path, restore one-liners
   (whole-batch and manifest-driven), purge command, and on first use
   a hint to commit the trashcan markers.

6. If the script exits non-zero (every supplied path failed), surface
   the refusal lines on stderr. Do not retry — refusals are path-based
   and unchanged on retry.

## Output

The script's report unchanged. On first use the report ends with a
one-time NOTE prompting the operator to commit the `.gitkeep` and
`README.txt` markers so `.trashcan/` survives `git clean -fdx` and
fresh clones.

## Refusals

The script silently refuses paths that are: outside the project root
(canonically resolved — symlink tricks are caught), the project root
itself, or anywhere inside `.git/`, `.claude/`, `.claude-plugin/`, or
`.trashcan/`.

A run that refuses every path exits non-zero. Mixed runs still move
the safe paths and report refusals on stderr.

## Subagent invocation

Two channels — every agent has at least one:

- Skill: `Skill({skill: "janitor-safe-delete", args: "p1 p2"})`
- Bash: `bash "$CLAUDE_PLUGIN_ROOT/scripts/safe-delete.sh" -- p1 p2`

When briefing a subagent, mention the Bash channel — it works
regardless of tool surface.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort: "ai-maestro-janitor not
  installed in this session."
- `safe-delete.sh` missing at `SCRIPT_PATH` → abort; reinstall via
  `claude plugin install`.
- Non-zero exit with at least one moved item → surface both the
  success report and the per-path refusals.
- Non-zero exit with zero moved items → every path was refused or
  missing. Do not retry without correcting paths.
- Filesystem error during `mv` → surface the script's `failed:` line.
  The path is still at its original location; no partial state.

## Examples

```text
User: /janitor-safe-delete src/old.ts
User: safe-delete the docs/draft folder
User: trash src/legacy/auth.ts src/legacy/session.ts
User: dispose of build/output (regeneratable)
User: I'm blocked from rm, can the janitor do it?
```

## Scope

This skill ONLY moves paths into `.trashcan/`. It NEVER empties the
trashcan, restores anything, or modifies files outside `.trashcan/`
and `.gitignore`. See README.md for the survival mechanism and
restore recipes.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh` — backing script.
  Self-contained, callable from any Bash context.
- README.md — full explanation of the trashcan layout and restore
  options.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `SCRIPT_PATH` from `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh`
- [ ] Parse user arguments (treat `--dry-run`/`-n` as a flag if present)
- [ ] Invoke `bash "$SCRIPT_PATH" [--dry-run] -- <paths>`
- [ ] Surface stdout (including any first-time NOTE) verbatim
- [ ] On non-zero exit, surface refusal lines for path correction
