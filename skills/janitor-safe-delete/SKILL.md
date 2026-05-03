---
name: janitor-safe-delete
description: Recoverable alternative to `rm` for files and folders. Use ANY time you need to delete, remove, dispose of, drop, discard, throw away, prune, or clean up files or directories inside the project. Also use as the fallback when `rm`/`rm -rf`/`rm -r` is blocked by a hook, when CLAUDE.md RULE 0 forbids deleting an uncommitted file, or when a destructive action otherwise feels risky. Moves the targets into `<project_root>/.trashcan/<timestamp>/` plus a sibling `<timestamp>.txt` manifest — nothing is actually deleted, the move is reversible. Trigger with `/janitor-safe-delete <path>...` or by asking the janitor to "safe-delete", "trash", "throw away", or "dispose of" something.
---

# Janitor safe-delete

## Overview

Disposes of files or directories without `rm`. Each invocation moves the
named paths into `<project_root>/.trashcan/<YYYYMMDD_HHMMSS±HHMM>/`,
mirroring their original layout, and writes a sibling
`<YYYYMMDD_HHMMSS±HHMM>.txt` manifest with one project-relative path per
line. The move is reversible: `mv` (or `cp -R`) can restore the batch on
any platform from those two artefacts alone.

This is the single sanctioned way for the orchestrator and any subagent to
"delete" something inside the project. It side-steps three common problems
at once:

1. **Project hooks that block `rm`** — the script is `mv`-only, so it
   passes any reasonable Bash safety guard.
2. **CLAUDE.md RULE 0** ("never delete uncommitted files") — moving to
   `.trashcan/` is recoverable, so the rule is satisfied even for files
   that were never committed.
3. **Accidental disposal** — every batch is a separate timestamped folder
   plus manifest, so a mistake is one `cp -R` away from being undone.

## Prerequisites

- `ai-maestro-janitor` plugin installed (project scope).
- `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh` resolvable from the
  current session (Claude Code sets `CLAUDE_PLUGIN_ROOT` automatically).
- Bash (used to invoke the script). The Skill tool itself is not strictly
  required — an agent with no Skill access can still reach the same
  behaviour through Bash.

## Instructions

1. Resolve `SCRIPT_PATH` = `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh`.

2. Parse `$ARGUMENTS` (or, in a slash invocation, the user-supplied
   argument string) into a whitespace-separated list of paths. Treat
   quoted paths as single tokens (paths with spaces). Do **not** expand
   globs in the skill — the shell that runs the script will, and the
   script's own `safe_to_trash` check refuses anything outside the
   project root anyway.

3. If no paths were supplied, abort with the message:
   `Usage: /janitor-safe-delete <path>... — give me one or more paths to dispose of.`

4. Run the script via Bash, forwarding the paths verbatim:

   ```bash
   bash "$SCRIPT_PATH" -- <path1> <path2> ...
   ```

   The leading `--` guarantees that paths starting with `-` are treated
   as positional arguments rather than flags. If the user passed
   `--dry-run` or `-n` as their first token, hoist it before the `--`
   so the script honours it:

   ```bash
   bash "$SCRIPT_PATH" --dry-run -- <path1> <path2> ...
   ```

5. Surface the script's stdout verbatim. The script already produces a
   complete report: items moved, manifest path, restore one-liners
   (whole-batch and manifest-driven), purge command, and — on first use
   — a hint to `git add` the trashcan markers.

6. If the script exits non-zero (every supplied path failed — e.g. all
   refused or all missing), surface the error lines and exit. Do not
   retry: the failures are deterministic (refusals are path-based and
   unchanged on retry).

## Output

The script's report, unchanged. Format:

```text
[safe-delete] Trashed <N> item(s) into .trashcan/<timestamp>/:
  src/old.ts -> .trashcan/<timestamp>/src/old.ts
  docs/draft -> .trashcan/<timestamp>/docs/draft

Manifest:
  .trashcan/<timestamp>.txt
Restore (whole batch — overwrites if names collide):
  cp -R .trashcan/<timestamp>/. ./
Restore (manifest-driven, selective):
  while IFS= read -r p; do ... done < .trashcan/<timestamp>.txt
Purge permanently:
  rm -rf .trashcan/<timestamp>/ .trashcan/<timestamp>.txt
```

On the very first invocation in a project, the report ends with a
one-time `NOTE` block prompting the user to commit the trashcan
markers (`.trashcan/.gitkeep` and `.trashcan/README.txt`) so the
directory survives `git clean -fdx` and fresh clones.

## Refusals (always)

The script silently refuses to move:

- paths outside the project root (resolved canonically — symlink tricks
  do not slip past)
- the project root itself
- anything inside `.git/`, `.claude/`, `.claude-plugin/`
- anything already inside `.trashcan/`

A run that hits **every** path with a refusal exits non-zero. A mixed
run still moves the safe paths and reports the refusals on stderr.

## Why a manifest

Each batch's `.trashcan/<timestamp>.txt` holds one project-relative
path per line (prefixed with `./`), preceded by `#`-prefixed header
comments. That is the platform-independent restore key — cross-OS
restore loops can read it with a one-liner:

```bash
while IFS= read -r p; do
  [ -z "$p" ] || [ "${p#\#}" != "$p" ] && continue
  mv ".trashcan/<timestamp>/${p#./}" "$p"
done < ".trashcan/<timestamp>.txt"
```

Without the manifest, restoration would have to walk the mirrored
subfolder and reverse-derive the original layout. With it, restore is
straight-line.

## Why `.trashcan/` survives `git clean -fdx`

The script auto-edits `.gitignore` to ignore the directory's contents
**but un-ignore two marker files**:

```text
/.trashcan/*
!/.trashcan/.gitkeep
!/.trashcan/README.txt
```

The script also creates those two markers. Once committed, they keep
the directory alive across:

- `git clean -fdx` (it never touches tracked files, so the dir stays)
- `git clone` (the dir is materialised from the markers)
- shell wipes targeting ignored files (markers are tracked, not ignored)

The first-time NOTE in the report nudges the user to:

```bash
git add .gitignore .trashcan/.gitkeep .trashcan/README.txt
git commit -m "track .trashcan markers"
```

After that commit, the trashcan is permanent project infrastructure.

## Examples

```text
User: /janitor-safe-delete src/old-feature.ts
User: safe-delete the docs/draft folder
User: trash this — src/legacy/auth.ts src/legacy/session.ts
User: dispose of build/output (it's regeneratable)
User: I'm blocked from `rm`, can the janitor do it?
```

## Subagent invocation

The script is reachable via two channels, so every subagent has at
least one:

- **Skill channel** (any subagent with the Skill tool):
  `Skill({skill: "janitor-safe-delete", args: "<path1> <path2>"})`
- **Bash channel** (any subagent with Bash):
  `bash "$CLAUDE_PLUGIN_ROOT/scripts/safe-delete.sh" -- <path1> <path2>`

When briefing a subagent that needs to dispose of files, mention the
Bash channel explicitly — that path always works regardless of the
agent's tool surface.

## Scope

This skill ONLY moves paths into `.trashcan/`. It NEVER:

- empties the trashcan (use `rm -rf .trashcan/<timestamp>` to purge a
  specific batch — the script prints that exact command)
- restores anything (use `cp -R` or the manifest-driven loop — the
  script prints those exact commands)
- modifies anything outside `.trashcan/` and `.gitignore`

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh` — the backing script.
  Self-contained, callable directly from any Bash context.
- `<project_root>/.trashcan/README.txt` — explanatory marker created on
  first use; explains the layout and restore commands to anyone reading
  the directory cold.
- `<project_root>/.trashcan/.gitkeep` — empty marker that keeps the
  directory tracked.
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh` — sourced for logging to
  `.janitor/logs/safe-delete.log` when reachable.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `SCRIPT_PATH` from `${CLAUDE_PLUGIN_ROOT}/scripts/safe-delete.sh`
- [ ] Parse the user's arguments into a path list (treat `--dry-run`/`-n` as a flag if present)
- [ ] Invoke `bash "$SCRIPT_PATH" [--dry-run] -- <paths>`
- [ ] Surface the script's stdout (including any first-time NOTE) verbatim
- [ ] On a non-zero exit, surface the refusal/skip lines so the user can correct paths and retry
