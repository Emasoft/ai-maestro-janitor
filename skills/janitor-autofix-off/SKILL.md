---
name: janitor-autofix-off
description: Disables the janitor's "act, don't ask" autofix mode in this project. After running, the janitor reports security/CI/publish findings but does not apply fixes without explicit confirmation. Idempotent — safe to re-run. Trigger with /janitor-autofix-off, "turn off autofix", "disable janitor autofix", or "make the janitor report-only".
---

# Janitor autofix off

## Overview

Writes the sentinel file `.janitor/state/autofix-mode.txt` with the single
line `off`. While the file contains `off`, the janitor's default
"act, don't ask" policy is suspended in this project: drift detectors still
surface findings, but the Claude session must ask before applying fixes
to rulesets, workflow YAMLs, publish scripts, or push hooks.

When the file is absent OR contains `on`, the default policy (autofix
without asking) applies. New projects start with autofix ON because the
file does not exist — that matches the user's standing instruction
"DO NOT WAIT FOR THE USER TO APPROVE, IT WOULD BE TOO LATE" for the
narrow class of security/CI/publish hardening fixes.

The cron, detectors, and per-finding reports are unchanged. Only the
"act vs ask" decision flips.

This is the lighter alternative to `/janitor-pause`: pause silences
everything; autofix-off keeps findings visible but withholds
auto-remediation.

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (used to locate `.janitor/state/`). Falls
  back to `$(pwd)` when unset.

## Instructions

1. Write the sentinel atomically:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   printf 'off' > "$STATE_DIR/autofix-mode.txt.tmp.$$"
   mv -f "$STATE_DIR/autofix-mode.txt.tmp.$$" "$STATE_DIR/autofix-mode.txt"
   ```

2. Report one line: `Janitor autofix: OFF (report-only mode in this project; flip back with /janitor-autofix-on).`

## Output

One line confirming the mode change. The file is gitignored along with
the rest of `.janitor/state/`.

## Error Handling

- `$CLAUDE_PROJECT_DIR` unset → fall back to `$(pwd)`. The same
  resolution `dispatch.py` and the heartbeat use; consistency is
  preserved.
- Cannot create `$STATE_DIR` (permission denied) → abort with the error
  verbatim. Report `Janitor autofix-off failed: <error>`.
- Re-run while already off → idempotent overwrite, report the same
  one-line confirmation.

## Examples

```text
User: /janitor-autofix-off
User: turn off autofix
User: disable janitor autofix
User: I want to review the findings myself before fixing
User: make the janitor report-only
```

## Scope

This skill ONLY writes the autofix-off sentinel. It does not affect the
cron, modify detectors, suppress heartbeat output, or touch any other
state. To re-enable autofix mode, run `/janitor-autofix-on`.

## Resources

- `$CLAUDE_PROJECT_DIR/.janitor/state/autofix-mode.txt` — the sentinel
  file; one of `on`, `off`, or missing (= `on`).
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.py` — provides
  `autofix_mode()` and `autofix_enabled()` helpers used by detectors
  and the dispatcher.
- The "act, don't ask" feedback memory at
  `~/.claude/projects/<project>/memory/feedback_security_act_dont_ask.md`
  reads this sentinel before applying any security/CI/publish fix.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `STATE_DIR` from `$CLAUDE_PROJECT_DIR` (or `$(pwd)` fallback)
- [ ] Ensure `STATE_DIR` exists (`mkdir -p`)
- [ ] Atomically write `off` to `autofix-mode.txt`
- [ ] Report one line confirming the mode flip
