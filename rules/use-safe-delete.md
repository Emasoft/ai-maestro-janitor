<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active** (`DATA` =
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`): no `DATA` ⇒ orphan — INERT,
> and the user may delete THIS FILE only, never a memory store; `DATA/global-state/kill-switch.flag`
> (or legacy `~/.claude/janitor-global-state/kill-switch.flag`) ⇒ deliberately stopped, INERT this
> session; else ACTIVE.

# Use the janitor's safe-delete for **risky** deletions

Deleting inside a project? Decide first whether it is *risky*; if so use
**`safe-delete`** instead of `rm` / `rmdir` / `Path.unlink` /
`shutil.rmtree`. If not, those are right — do not push every deletion
through `.trashcan/` or it will balloon.

`safe-delete` does not delete: it MOVES targets into
`<project_root>/.trashcan/<timestamp>/` (original layout mirrored) plus a
sibling `<timestamp>.txt` manifest of every path moved, so recovery is
one `mv` on any platform.

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

## Recoverable ⇒ **do NOT ask** (USER, 2026-08-14)

This tool exists so an agent deletes **without stopping to ask**: in
`.trashcan/` nothing is lost, so there is nothing left to authorize.
Risky → `safe-delete` it and keep going (say in one line what moved
where); regeneratable → `rm` it and keep going. **Ask only when the act
cannot be made recoverable** — history rewrite, credential, remote or
shared resource, anything outside the project tree.

An ask on a recoverable delete is not caution, it is a stall: an
unattended run (cron heartbeat, background agent, overnight session) has
nobody to answer, so it protects no file and parks the task to buy a
guarantee `.trashcan/` already gives free. This is RULE 0's own
sanctioned form (commit first, `_dev/`, trashcan); its "ask before
deleting untracked files" clause is aimed at *permanent loss*, not at a
move with a manifest.

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
- The targets are clearly regeneratable (list above) — they would
  balloon `.trashcan/`.
- The targets live OUTSIDE the project tree; `safe-delete` refuses
  them anyway.

## The trashcan itself

Gitignored, survives `git clean -fdx` via two tracked markers
(`.gitkeep` + `README.txt`), purged by the `trashcan-purge` detector
after `CLAUDE_PLUGIN_OPTION_TRASHCAN_MAX_AGE_DAYS` (default 90).
Recovery is `mv .trashcan/<timestamp>/<rel-path> <rel-path>`; the
`<timestamp>.txt` manifest makes a bulk restore an `xargs` one-liner.
