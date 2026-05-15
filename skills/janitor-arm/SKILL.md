---
name: janitor-arm
description: Arms or renews the ai-maestro-janitor heartbeat cron. Use when first installing the plugin, after a plugin update to a version that introduces or changes the dispatcher stub, or in response to a [janitor-renew] nudge before the 7-day auto-expiry. Trigger with /janitor-arm or "arm the janitor heartbeat".
---

# Janitor arm

## Overview

Creates (or replaces) the single durable CronCreate heartbeat that drives the ai-maestro-janitor plugin. From v0.4.11 onward the cron prompt points at an **auto-rolling stub** in `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` — a path that survives every plugin update — instead of a version-stamped `dispatch.py` path. The stub re-resolves the highest cached plugin version on every fire and `os.execv`'s into its `scripts/dispatch.py`, so future plugin updates roll forward automatically without re-arming.

Re-arming is still necessary in three cases:
- First install of the plugin in this session.
- After upgrading FROM a pre-stub janitor (≤ v0.4.10) TO v0.4.11+. The pre-stub cron points at a versioned `dispatch.py` that will become stale; only re-arming with v0.4.11+ switches the cron to the stub.
- In response to a `[janitor-renew]` nudge before the 7-day cron auto-expiry.

Every cron fire is a fresh user turn that runs `dispatcher-stub.py` → `dispatch.py` and surfaces drift lines. Also keeps the Anthropic prompt cache warm during idle (every fire inside the 5-min TTL refreshes the cache) and recovers from rate-limit windows (fires queue during 429 and deliver in batch when the window clears).

This skill is the ONLY way to start or renew the janitor. Hooks and dispatch.py cannot call CronCreate; only an in-session turn can. That's why dispatch.py emits `[janitor-renew]` one day before the 7-day expiry — the model sees the nudge, runs this skill, and the cron is refreshed. Re-running the skill at any time is safe and idempotent.

## Prerequisites

- `ai-maestro-janitor` plugin installed.
- `CronCreate` / `CronList` / `CronDelete` tools available (Claude Code v2.1.98+).
- `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin's installed root at skill-invocation time.
- `${CLAUDE_PLUGIN_DATA}` resolves to the plugin's persistent data dir at skill-invocation time (auto-created on first reference per Claude Code's plugin-data contract).

## Instructions

1. Resolve `STUB_SOURCE` = `${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py` and `STUB_DEST` = `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`. The placeholders are substituted by Claude Code before this skill content is read.

2. Install (or refresh) the stub atomically:

   ```bash
   mkdir -p "${CLAUDE_PLUGIN_DATA}"
   STUB_SOURCE="${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py"
   STUB_DEST="${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py"
   TMP_DEST="${STUB_DEST}.tmp.$$"
   cp -f "$STUB_SOURCE" "$TMP_DEST"
   chmod +x "$TMP_DEST"
   mv -f "$TMP_DEST" "$STUB_DEST"
   ```

   The atomic `mv` guarantees the stub is either fully present (and executable) or unchanged from the prior install — partial writes never leave a corrupt half-stub for the cron to fire.

3. Read the heartbeat cron from `${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON}`, defaulting to `"*/5 * * * *"`.

4. Call `CronList`. For each job whose prompt begins with `[janitor-heartbeat]`, call `CronDelete`. This guarantees exactly one heartbeat after arming, even on re-runs.

5. Build the heartbeat prompt with `STUB_DEST` baked in (replace `{{STUB_DEST}}`):

   ```text
   [janitor-heartbeat]
   {{STUB_DEST}}
   Surface stdout verbatim. `[janitor-resume]` = resume prior task. No output = silent. One pass, no sub-agents.
   ```

   No `bash` prefix — the stub is a `#!/usr/bin/env python3` shebang script invoked directly. It re-resolves the latest cached plugin version on every fire and `execv`'s into its `scripts/dispatch.py`, so the cron prompt never needs to change when the plugin updates.

6. Call `CronCreate` with `cron` from step 3, `prompt` from step 5, `durable: true`, `recurring: true`.

7. Record the arm timestamp so dispatch.py can compute age and emit `[janitor-renew]` before the 7-day expiry. Resolve `STATE_DIR` as `$CLAUDE_PROJECT_DIR/.janitor/state` (or `$(pwd)/.janitor/state` if the env var is unset), `mkdir -p` it, then write the current epoch into `heartbeat-armed-at.ts` using an atomic tmp+rename. Also clear any prior `heartbeat-renew-seen.txt` so the next renew cycle starts fresh.

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   NOW=$(date +%s)
   printf '%s' "$NOW" > "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" && \
     mv -f "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" "$STATE_DIR/heartbeat-armed-at.ts"
   rm -f "$STATE_DIR/heartbeat-renew-seen.txt"
   ```

8. Report one line to the user: `Janitor armed: <cron> → runs auto-rolling stub each fire (current target: <latest-version>). Heartbeat ID: <returned-id>. Auto-renewal nudge at ~6 days; future plugin updates roll forward without re-arming.` If step 4 deleted existing heartbeats, append `(replaced <N>)` at the end.

## Output

One line describing what was armed, the heartbeat ID from `CronCreate`, and the current target version the stub resolves to. The stub file is written atomically to `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`; no other files are written.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort: "ai-maestro-janitor not installed in this session. Run `claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope project` first."
- `${CLAUDE_PLUGIN_DATA}` unset → abort: "Claude Code v2.1+ required (this version exposes `${CLAUDE_PLUGIN_DATA}`)."
- `STUB_SOURCE` missing at `${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py` → abort; the plugin cache is in an unexpected state.
- `cp` / `chmod` / `mv` fails → surface the error verbatim and stop before `CronCreate`. A bad stub is worse than no arm.
- `CronList` fails → skip step 4 and proceed. A duplicate heartbeat is harmless (the stub is idempotent, seen-files dedupe).
- `CronCreate` fails → surface the error verbatim; do NOT retry automatically.

## Examples

```text
User: /janitor-arm
User: arm the janitor heartbeat
User: re-arm after the plugin update
```

## Scope

This skill ONLY installs the auto-rolling stub and arms (or renews) the heartbeat cron. It does NOT run detectors (that is `/janitor-audit`), does NOT install the plugin, does NOT modify userConfig. To stop the heartbeat, use `/janitor-disarm` — that skill removes the cron AND the stub.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py` — the auto-rolling stub source.
- `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` — the installed stub the cron actually fires.
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — the per-version dispatcher the stub `execv`'s into.
- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/` — the drift detectors dispatch invokes.
- `$CLAUDE_PROJECT_DIR/.janitor/state/` — per-project state and dedupe seen-files.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `STUB_SOURCE` from `${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py`
- [ ] Resolve `STUB_DEST` from `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`
- [ ] Install the stub atomically (cp → chmod +x → mv)
- [ ] `CronList` + `CronDelete` any existing `[janitor-heartbeat]` job
- [ ] `CronCreate` with durable=true, recurring=true, and the stub-path heartbeat prompt
- [ ] Write `.janitor/state/heartbeat-armed-at.ts` + clear `heartbeat-renew-seen.txt`
- [ ] Report heartbeat ID + current stub target version to the user in one line
