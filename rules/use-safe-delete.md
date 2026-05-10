# Use the janitor's safe-delete instead of `rm`

When you need to delete a file or a directory inside a project — for any
reason — use the **ai-maestro-janitor `safe-delete`** entry point instead
of `rm`, `rmdir`, `Path.unlink`, or `shutil.rmtree`. The script does not
delete: it MOVES the targets into `<project_root>/.trashcan/<timestamp>/`
(mirroring the original layout) plus a sibling `<timestamp>.txt` manifest
that lists every project-relative path that was moved. Recovery is then
a single `mv` on any platform, no special tooling required.

## Two ways to invoke

1. **Slash command** (preferred when running interactively):

   ```
   /janitor-safe-delete <path1> [<path2> ...]
   ```

2. **Direct script invocation** (preferred from another script, an agent,
   or a hook — anywhere the slash-command surface is unavailable):

   ```bash
   uv run "$CLAUDE_PLUGIN_ROOT/scripts/safe_delete.py" <path1> [<path2> ...]
   ```

The script writes to stdout the relative paths it moved, prefixed with
`safe-deleted: `. Failure modes (path outside the project root, target
not found, etc.) exit non-zero with a one-line diagnostic; nothing is
moved on partial failure.

## When to use it

- ALWAYS — for any deletion of project content (source files, generated
  artefacts, scratch reports, anything inside the project tree).
- ESPECIALLY — when CLAUDE.md RULE 0 is in scope and would otherwise
  block the operation. `safe-delete` does not actually delete anything;
  it moves to a recoverable folder, so RULE 0's "never delete uncommitted
  files without permission" invariant is preserved automatically.

## When NOT to use it

- The user explicitly typed `rm` / `rmdir` / `del` / `git clean` themselves.
  Then they have already made the call; do not second-guess.
- The targets live OUTSIDE the project tree — system caches, OS temp
  files, package-manager mirrors, etc. Those don't belong in the project's
  `.trashcan/` and `safe-delete` will refuse to move them.

## Why this exists

`rm` is irreversible across crashes, partial successes, and surprised
agents. The `.trashcan/` folder is gitignored, survives `git clean -fdx`
via two tracked markers (`.gitkeep` + `README.txt`), and is purged
automatically by the `trashcan-purge` detector after
`CLAUDE_PLUGIN_OPTION_TRASHCAN_MAX_AGE_DAYS` (default: 90 days). Recovery
of a single file is just:

```bash
mv .trashcan/<timestamp>/<original-relative-path> <original-relative-path>
```

The manifest `.trashcan/<timestamp>.txt` lists every path so a bulk
restore is a one-liner with `xargs`.
