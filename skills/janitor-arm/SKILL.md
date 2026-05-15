---
name: janitor-arm
description: Arms or renews the ai-maestro-janitor heartbeat cron. Use when first installing the plugin, upgrading from pre-stub (≤ v0.4.10), or in response to a [janitor-renew] nudge before the 7-day auto-expiry. Trigger with /janitor-arm or "arm the janitor heartbeat".
---

# Janitor arm

## Overview

Creates (or replaces) the single durable CronCreate heartbeat. From v0.4.11 the cron prompt points at an **auto-rolling stub** in `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` (path survives every plugin update). The stub re-resolves the highest cached plugin version on every fire and `os.execv`'s into its `scripts/dispatch.py`, so future plugin updates roll forward without re-arming.

Re-arming is needed only on: first install, upgrade from pre-stub (≤ v0.4.10) once, or `[janitor-renew]` nudge before the 7-day cron auto-expiry. Re-running this skill at any time is safe and idempotent.

For the full design rationale, atomic install reasoning, path-traversal safety analysis, stub-vs-dispatch responsibility split, and survival contract for future versions, read [janitor-architecture](references/janitor-architecture.md): [Why the stub exists](references/janitor-architecture.md#why-the-stub-exists), [Operational rules](references/janitor-architecture.md#operational-rules), [Responsibility split and safety](references/janitor-architecture.md#responsibility-split-and-safety).

## Prerequisites

- `ai-maestro-janitor` plugin installed; `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` both resolve at skill-invocation time.
- `CronCreate` / `CronList` / `CronDelete` tools available (Claude Code v2.1.98+).

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

   Atomic `mv` guarantees the stub is either fully present (and executable) or unchanged from the prior install — partial writes never leave a corrupt half-stub for the cron to fire.

2. Read the heartbeat cron from `${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON}`, default `"*/5 * * * *"`.

3. Call `CronList`. For each job whose prompt begins with `[janitor-heartbeat]`, call `CronDelete`. This guarantees exactly one heartbeat after arming, even on re-runs.

4. Build the heartbeat prompt with `STUB_DEST` baked in (replace `{{STUB_DEST}}`):

   ```text
   [janitor-heartbeat]
   {{STUB_DEST}}
   Surface stdout verbatim. `[janitor-resume]` = resume prior task. No output = silent. One pass, no sub-agents.
   ```

   The stub is a `#!/usr/bin/env python3` shebang script invoked directly — no `bash` prefix needed.

5. Call `CronCreate` with `cron` from step 2, `prompt` from step 4, `durable: true`, `recurring: true`.

6. Record arm timestamp + clear stale renew-dedupe:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   NOW=$(date +%s)
   printf '%s' "$NOW" > "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" && \
     mv -f "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" "$STATE_DIR/heartbeat-armed-at.ts"
   rm -f "$STATE_DIR/heartbeat-renew-seen.txt"
   ```

7. Report one line: `Janitor armed: <cron> → runs auto-rolling stub (current target: <latest-version>). Heartbeat ID: <returned-id>. Future plugin updates roll forward without re-arming.` If step 3 deleted existing heartbeats, append `(replaced <N>)` at the end.

## Output

One line describing the arm + heartbeat ID + current stub target version. The stub file is written atomically to `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`; no other files written.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort: "ai-maestro-janitor not installed in this session."
- `${CLAUDE_PLUGIN_DATA}` unset → abort: "Claude Code v2.1+ required."
- `STUB_SOURCE` missing → abort; plugin cache is in an unexpected state.
- `cp` / `chmod` / `mv` fails → surface error and stop before `CronCreate`. A bad stub is worse than no arm.
- `CronList` fails → skip step 3 and proceed. Duplicate heartbeats are harmless (seen-files dedupe).
- `CronCreate` fails → surface error verbatim; do not retry automatically.

## Examples

```text
User: /janitor-arm
User: arm the janitor heartbeat
User: re-arm after the plugin update
```

## Scope

ONLY installs the stub and arms the heartbeat cron. Does NOT run detectors (use `/janitor-audit`), install the plugin, or modify userConfig. To stop: `/janitor-disarm`.

## Resources

- [janitor-architecture](references/janitor-architecture.md) — full design rationale, stub indirection, atomic install, path-traversal safety, survival contract.
  - [Why the stub exists](references/janitor-architecture.md#why-the-stub-exists)
  - [Operational rules](references/janitor-architecture.md#operational-rules)
  - [Responsibility split and safety](references/janitor-architecture.md#responsibility-split-and-safety)
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py` — auto-rolling stub source.
- `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` — installed stub the cron fires.
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — per-version dispatcher the stub `execv`'s into.
- `$CLAUDE_PROJECT_DIR/.janitor/state/` — per-project state and dedupe seen-files.
