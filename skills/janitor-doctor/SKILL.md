---
name: janitor-doctor
description: Pre-flight health check for ai-maestro-janitor. Use when the heartbeat is misbehaving, after install/upgrade, before reporting an issue, or any time a detector seems to silently skip. Trigger with /janitor-doctor, "diagnose the janitor", "is the janitor healthy", "check janitor preconditions", or "what's wrong with the heartbeat".
---

# Janitor doctor

## Overview

Runs a series of named pass/fail checks against the project and the plugin install. Each check produces a row in a unicode-bordered table with a short detail and (when failing) a one-line fix hint. Returns exit code 0 when everything passes, 1 when any check fails.

The checks cover three layers:

1. **Plugin install** — dispatch.py executable, detectors executable, plugin.json valid.
2. **Project state** — `.janitor/state/` and `.janitor/logs/` writable, project is a git repo, `/reports/` and `/reports_dev/` are gitignored.
3. **External dependencies** — `uv` (required — every detector uses `uv run --script`), `git`, `gh` (authenticated). `jq` is informational only.

Use this when the heartbeat seems silent for too long, when `pr-reconciler` or `task-pr-mismatch` keep skipping, or as the first step of any "the janitor is broken" investigation.

## Prerequisites

- `$CLAUDE_PROJECT_DIR` set (used to locate the project root).
- `${CLAUDE_PLUGIN_ROOT}` set (used to locate the plugin scripts).

## Instructions

1. Invoke the backing script via Bash:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/commands/doctor.py"
   ```

2. Surface the table verbatim — the unicode borders are intentional and render correctly in Claude Code's terminal.

3. If exit code is non-zero, summarize the failures in plain prose AFTER the table for the user.

## Output

A unicode-bordered table with one row per check, plus an X/Y summary line. When checks fail, a "Fix hints:" section follows the table with one line per failed check.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → use the path from the install location. The skill should still run, but report `Note: CLAUDE_PLUGIN_ROOT was unset; resolved via fallback`.
- Backing script fails to execute → surface the error verbatim. Likely cause is a corrupted install.
- Backing script returns rows but no failures despite an obvious problem (e.g. heartbeat silent for hours) → suggest the user share the full output of `/janitor-audit` next.

## Examples

```text
User: /janitor-doctor
User: diagnose the janitor
User: is the janitor healthy
User: check janitor preconditions
User: what's wrong with the heartbeat
```

## Scope

This skill ONLY runs read-only checks. It writes no files, modifies no state, does not invoke any detector, and never affects the heartbeat cron. Safe to run during any session, including ones where the janitor is paused or disarmed.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/commands/doctor.sh` — the backing script that runs the checks.
- `$CLAUDE_PROJECT_DIR/.janitor/state/` — checked for write access; not modified.
- `$CLAUDE_PROJECT_DIR/.janitor/logs/` — checked for write access; not modified.

## Checklist

Copy this checklist and track your progress:

- [ ] Invoke `"${CLAUDE_PLUGIN_ROOT}/scripts/commands/doctor.py"`
- [ ] Surface the unicode-bordered table verbatim
- [ ] If any FAIL rows, summarize them in plain prose after the table
- [ ] Exit with the same code the backing script returned (0 all-pass, 1 any-fail)
