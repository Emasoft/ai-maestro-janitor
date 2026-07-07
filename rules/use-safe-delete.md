<!-- ai-maestro-janitor:installed-rule — copied into your rules dir by the ai-maestro-janitor
     plugin. SAFE TO REMOVE if the plugin is uninstalled; removing it never affects any MEMORY
     store, only this rule file. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — CONDITIONAL on the janitor being active.** Check the janitor's
> state first (cheap `$HOME` existence checks), then act:
> - **UNINSTALLED** — if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` is
>   ABSENT, the plugin was uninstalled and this file is an ORPHAN it could not remove (Claude
>   Code does not clean a plugin's `~/.claude/rules/` or a project's `.claude/rules/` on
>   uninstall). Treat this rule as INERT, and tell the user it is an orphaned janitor rule they
>   may delete. NEVER delete any MEMORY store — only this rule file, and only with the user's ok.
> - **DISARMED** — else if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/kill-switch.flag`
>   OR the legacy `~/.claude/janitor-global-state/kill-switch.flag` EXISTS (set by
>   `/janitor-global-disarm`), the janitor is intentionally stopped → treat this rule as INERT
>   this session.
> - **ACTIVE** — otherwise the janitor is running; apply the rule as written below.

# Use the janitor's safe-delete for **risky** deletions

When you delete a file or directory inside a project, decide first
whether the deletion is *risky*. If it is, use the
**ai-maestro-janitor `safe-delete`** entry point instead of `rm`,
`rmdir`, `Path.unlink`, or `shutil.rmtree`. If it isn't, plain `rm`
(or `rmdir`, `Path.unlink`, `shutil.rmtree`) is the right tool —
do not push every deletion through `.trashcan/` or it will balloon.

`safe-delete` does not delete; it MOVES the targets into
`<project_root>/.trashcan/<timestamp>/` (mirroring the original
layout) plus a sibling `<timestamp>.txt` manifest listing every
project-relative path that was moved. Recovery is then a single `mv`
on any platform, no special tooling required.

## Risk judgement (use this, not a checklist of paths)

Ask yourself one question: **"If this deletion is wrong, can I get
the content back without human intervention?"**

- **Yes, trivially recoverable** → plain `rm` is correct.
  Examples: build outputs (`dist/`, `build/`, `target/`, `__pycache__/`,
  `.pyc`, `.o`, `.class`), package manager caches (`node_modules/`,
  `.venv/`, `vendor/`, `.uv-cache/`), test artefacts that the test
  runner regenerates (`.pytest_cache/`, `.coverage`, `htmlcov/`),
  scratch tmpfiles the script itself just created and wrote, log
  rotation, lock files about to be regenerated.
- **No, or only with effort, or it represents human work** →
  `safe-delete` is correct. Examples: source files, configuration
  the user edited, reports/audits/handoffs the user may still want,
  uncommitted scratch the user created, anything inside the project
  tree that is not obviously a regeneratable artefact, anything
  whose status as "regeneratable" you are not sure about.

When in doubt, treat it as risky and use `safe-delete`. The cost of
a false alarm is one extra `mv` on recovery; the cost of a
mis-classified `rm` on real work is permanent loss.

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

The script writes to stdout the relative paths it moved, each line
prefixed with `safe-deleted:`. Failure modes (path outside the project
root, target not found, etc.) exit non-zero with a one-line diagnostic;
nothing is moved on partial failure.

## When NOT to use it

- The user explicitly typed `rm` / `rmdir` / `del` / `git clean`
  themselves. They have already made the call; do not second-guess.
- The targets are clearly regeneratable artefacts (see the "Yes,
  trivially recoverable" list above) — those don't belong in
  `.trashcan/` and would balloon it.
- The targets live OUTSIDE the project tree — system caches, OS
  temp files, package-manager mirrors, etc. `safe-delete` will
  refuse to move them anyway.

## Why this exists

`rm` is irreversible across crashes, partial successes, and
surprised agents. For *risky* deletions — anything representing
human work or whose status as "throwaway" is not obvious — the
`.trashcan/` folder gives a recovery window without committing to
git first. The folder is gitignored, survives `git clean -fdx` via
two tracked markers (`.gitkeep` + `README.txt`), and is purged
automatically by the `trashcan-purge` detector after
`CLAUDE_PLUGIN_OPTION_TRASHCAN_MAX_AGE_DAYS` (default: 90 days).

Recovery of a single file is just:

```bash
mv .trashcan/<timestamp>/<original-relative-path> <original-relative-path>
```

The manifest `.trashcan/<timestamp>.txt` lists every path so a bulk
restore is a one-liner with `xargs`.

The whole point of the risk gate is to keep `.trashcan/` small and
useful: only the deletions that *would actually hurt to lose* end
up there, so when something does go wrong the trashcan is short
enough to scan by eye and the right candidate is obvious.
