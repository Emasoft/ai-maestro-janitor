---
name: janitor-autofix-on
description: Re-enables the janitor's "act, don't ask" autofix mode after a /janitor-autofix-off. The janitor will once again apply fixes to rulesets, workflow YAMLs, publish scripts, and push hooks without waiting for confirmation. Idempotent — safe to re-run. Trigger with /janitor-autofix-on, "turn on autofix", "re-enable janitor autofix", or "let the janitor fix things again".
---

# Janitor autofix on

## Overview

Removes the `.janitor/state/autofix-mode.txt` sentinel (or writes `on`
into it) so the janitor's default "act, don't ask" policy resumes in
this project. Drift findings in security/CI/publish surfaces are
auto-remediated rather than queued for human confirmation.

The mode is per-project: this only affects the project whose
`$CLAUDE_PROJECT_DIR` is in scope.

Autofix is the **default** state of a new project (the sentinel is
absent → autofix ON). This command exists so a user who previously ran
`/janitor-autofix-off` can flip back without having to remember which
file to delete.

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (used to locate `.janitor/state/`). Falls
  back to `$(pwd)` when unset.

## Instructions

1. Remove the sentinel (or overwrite with `on`):

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   # Prefer deletion so the default-on semantics are exact; fall back to
   # writing "on" if unlink fails (e.g. permissions).
   if ! rm -f "$STATE_DIR/autofix-mode.txt" 2>/dev/null; then
     printf 'on' > "$STATE_DIR/autofix-mode.txt.tmp.$$"
     mv -f "$STATE_DIR/autofix-mode.txt.tmp.$$" "$STATE_DIR/autofix-mode.txt"
   fi
   ```

2. Report one line: `Janitor autofix: ON (the janitor will apply security/CI/publish fixes without asking; flip back with /janitor-autofix-off).`

## Output

One line confirming the mode change.

## Error Handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)`.
- Cannot remove the sentinel (e.g. read-only filesystem) → fall back to
  writing `on` into it. If both fail, abort with the OS error verbatim:
  `Janitor autofix-on failed: <error>`.
- Re-run while already on → idempotent, the sentinel is already gone
  (or contains `on`); report the same one-line confirmation.

## Examples

```text
User: /janitor-autofix-on
User: turn on autofix
User: re-enable janitor autofix
User: let the janitor fix things again
User: I'm done reviewing manually — go back to auto
```

## Scope

This skill ONLY removes the autofix-off sentinel. It does not affect
the cron, modify detectors, change heartbeat behaviour, or touch any
other state. To suspend autofix again, run `/janitor-autofix-off`.

## Resources

- `$CLAUDE_PROJECT_DIR/.janitor/state/autofix-mode.txt` — the sentinel
  file; absent or `on` means autofix is enabled.
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.py` — `autofix_mode()` and
  `autofix_enabled()` helpers used by detectors and the dispatcher.
- The "act, don't ask" feedback memory at
  `~/.claude/projects/<project>/memory/feedback_security_act_dont_ask.md`
  reads this sentinel before applying any security/CI/publish fix.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `STATE_DIR` from `$CLAUDE_PROJECT_DIR` (or `$(pwd)` fallback)
- [ ] Ensure `STATE_DIR` exists (`mkdir -p`)
- [ ] Remove the sentinel (or fall back to writing `on`)
- [ ] Report one line confirming the mode flip
