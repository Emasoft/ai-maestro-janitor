---
name: janitor-arm
description: Arms or renews the ai-maestro-janitor heartbeat cron. Use when first installing the plugin, upgrading from pre-stub (≤ v0.4.10), or in response to a [janitor-renew] nudge before the 7-day auto-expiry. Trigger with /janitor-arm or "arm the janitor heartbeat".
---

# Janitor arm

## Overview

Creates (or replaces) the single durable CronCreate heartbeat. The cron prompt points at an **auto-rolling stub** in `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` (path survives every plugin update). The stub re-resolves the highest cached plugin version on every fire and `os.execv`'s into its `scripts/dispatch.py`, so future plugin updates roll forward without re-arming.

Re-arming is needed only on: first install, upgrade from pre-stub (≤ v0.4.10) once, or `[janitor-renew]` nudge. Re-running is safe and idempotent.

Full design rationale, atomic install, path-traversal safety, survival contract: [janitor-architecture](references/janitor-architecture.md): [Why the stub exists](references/janitor-architecture.md#why-the-stub-exists), [Operational rules](references/janitor-architecture.md#operational-rules), [Responsibility split and safety](references/janitor-architecture.md#responsibility-split-and-safety).

## Prerequisites

- `ai-maestro-janitor` plugin installed; `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` resolve at skill-invocation time.
- `CronCreate` / `CronList` / `CronDelete` available (Claude Code v2.1.98+).

## Instructions

1. Install (or refresh) the stub atomically:

   ```bash
   mkdir -p "${CLAUDE_PLUGIN_DATA}"
   STUB_SOURCE="${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py"
   STUB_DEST="${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py"
   TMP_DEST="${STUB_DEST}.tmp.$$"
   cp -f "$STUB_SOURCE" "$TMP_DEST"
   chmod +x "$TMP_DEST"
   mv -f "$TMP_DEST" "$STUB_DEST"
   ```

2. Read cron from `${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON}`, default `"*/5 * * * *"`.

3. `CronList` → for each job whose prompt starts with `[janitor-heartbeat]`, `CronDelete`. Guarantees one heartbeat after arming.

4. Build the heartbeat prompt with `STUB_DEST` baked in:

   ```text
   [janitor-heartbeat]
   {{STUB_DEST}}
   Surface stdout verbatim with two exceptions: a line of exactly `[janitor-renew]` (no other text on that line) means "silently run /janitor-arm" — execute the slash-command to renew the cron before its 7-day auto-expiry and do NOT echo the marker line; a line of exactly `[janitor-reload]` (no other text on that line) means "silently run /reload-plugins" — execute the slash-command to pick up updated plugin hooks and skills after an auto-update and do NOT echo the marker line. `[janitor-resume]` = resume prior task. No output = silent. One pass, no sub-agents.
   ```

5. `CronCreate` with `cron` from step 2, `prompt` from step 4, `durable: true`, `recurring: true`.

6. Record arm timestamp + clear stale renew-dedupe:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   NOW=$(date +%s)
   printf '%s' "$NOW" > "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" && \
     mv -f "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" "$STATE_DIR/heartbeat-armed-at.ts"
   rm -f "$STATE_DIR/heartbeat-renew-seen.txt"
   ```

7. Report one line: `Janitor armed: <cron> → auto-rolling stub (target: <version>). Heartbeat ID: <id>. Future updates roll forward without re-arming.` Append `(replaced <N>)` if step 3 deleted any.

## Output

One line: cron expression, heartbeat ID, current stub target version. The stub file is written atomically to `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`; no other files written.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- `${CLAUDE_PLUGIN_DATA}` unset → abort "Claude Code v2.1+ required".
- `STUB_SOURCE` missing → abort; cache state is unexpected.
- `cp` / `chmod` / `mv` fails → surface error, stop before `CronCreate`. A bad stub is worse than no arm.
- `CronList` fails → skip step 3. Duplicates are harmless (dedupe).
- `CronCreate` fails → surface verbatim; do not retry automatically.

## Examples

```text
User: /janitor-arm
User: arm the janitor heartbeat
User: re-arm after the plugin update
```

## Scope

ONLY installs the stub and arms the heartbeat cron. Does NOT run detectors (use `/janitor-audit`), install the plugin, or modify userConfig. To stop: `/janitor-disarm`.

## Resources

- [janitor-architecture](references/janitor-architecture.md) — full design rationale.
  - [Why the stub exists](references/janitor-architecture.md#why-the-stub-exists)
  - [Operational rules](references/janitor-architecture.md#operational-rules)
  - [Responsibility split and safety](references/janitor-architecture.md#responsibility-split-and-safety)
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py` — stub source.
- `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` — installed stub the cron fires.
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — per-version dispatcher.
- `$CLAUDE_PROJECT_DIR/.janitor/state/` — per-project state files.
