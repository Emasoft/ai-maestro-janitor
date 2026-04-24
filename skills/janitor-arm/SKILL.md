---
name: janitor-arm
description: Arms or renews the ai-maestro-janitor heartbeat cron. Use when first installing the plugin, after a plugin update, or in response to a [janitor-renew] nudge before the 7-day auto-expiry. Trigger with /janitor-arm or "arm the janitor heartbeat".
---

# Janitor arm

## Overview

Creates (or replaces) the single durable CronCreate heartbeat that drives the ai-maestro-janitor plugin. Each cron fire is a fresh user turn that runs `scripts/dispatch.sh` and surfaces drift lines. Also keeps the Anthropic prompt cache warm during idle (every fire inside the 5-min TTL refreshes the cache) and recovers from rate-limit windows (fires queue during 429 and deliver in batch when the window clears).

This skill is the ONLY way to start or renew the janitor. Hooks and dispatch.sh cannot call CronCreate; only an in-session turn can. That's why dispatch.sh emits `[janitor-renew]` one day before the 7-day expiry — the model sees the nudge, runs this skill, and the cron is refreshed. Re-running the skill at any time is safe.

## Prerequisites

- `ai-maestro-janitor` plugin installed at project scope.
- `CronCreate` / `CronList` / `CronDelete` tools available (Claude Code v2.1.98+).
- `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin's installed root at skill-invocation time.

## Instructions

1. Resolve `DISPATCH_PATH` = `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh`. The env var is set by Claude Code when the skill runs.

2. Read the heartbeat cron from `${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON}`, defaulting to `"*/5 * * * *"`.

3. Call `CronList`. For each job whose prompt begins with `[janitor-heartbeat]`, call `CronDelete`. This guarantees exactly one heartbeat after arming, even on re-runs.

4. Build the heartbeat prompt with `DISPATCH_PATH` baked in (replace `{{DISPATCH_PATH}}`):

   ```text
   [janitor-heartbeat]
   bash {{DISPATCH_PATH}}
   Surface stdout verbatim. `[janitor-resume]` = resume prior task. No output = silent. One pass, no sub-agents.
   ```

5. Call `CronCreate` with `cron` from step 2, `prompt` from step 4, `durable: true`, `recurring: true`.

6. Record the arm timestamp so dispatch.sh can compute age and emit `[janitor-renew]` before the 7-day expiry. Resolve `STATE_DIR` as `$CLAUDE_PROJECT_DIR/.janitor/state` (or `$(pwd)/.janitor/state` if the env var is unset), `mkdir -p` it, then write the current epoch into `heartbeat-armed-at.ts` using an atomic tmp+rename. Also clear any prior `heartbeat-renew-seen.txt` so the next renew cycle starts fresh.

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   NOW=$(date +%s)
   printf '%s' "$NOW" > "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" && \
     mv -f "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" "$STATE_DIR/heartbeat-armed-at.ts"
   rm -f "$STATE_DIR/heartbeat-renew-seen.txt"
   ```

7. Report one line to the user: `Janitor armed: <cron> → runs dispatch.sh each fire. Heartbeat ID: <returned-id>. Auto-renewal nudge at ~6 days.` If step 3 deleted existing heartbeats, append `(replaced <N>)`.

## Output

One line describing what was armed and the heartbeat ID from `CronCreate`. No files written, no side effects beyond CronCreate/CronDelete.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort: "ai-maestro-janitor not installed in this session. Run `claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope project` first."
- `CronList` fails → skip step 3 and proceed. A duplicate heartbeat is harmless (dispatch.sh is idempotent, seen-files dedupe).
- `CronCreate` fails → surface the error verbatim; do NOT retry automatically.
- Dispatch script missing at `DISPATCH_PATH` → abort; the plugin cache is in an unexpected state.

## Examples

```text
User: /janitor-arm
User: arm the janitor heartbeat
User: re-arm after the plugin update
```

## Scope

This skill ONLY arms (or renews) the heartbeat cron. It does NOT run detectors (that is `/janitor-audit`), does NOT install the plugin, does NOT modify userConfig. To stop the heartbeat, use `/janitor-disarm`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh` — the cron-fire entry point.
- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/` — the drift detectors dispatch invokes (iterate the directory rather than hard-coding the list).
- `$CLAUDE_PROJECT_DIR/.janitor/state/` — per-project state and dedupe seen-files.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `DISPATCH_PATH` from `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh`
- [ ] `CronList` + `CronDelete` any existing `[janitor-heartbeat]` job
- [ ] `CronCreate` with durable=true, recurring=true, and the heartbeat prompt
- [ ] Write `.janitor/state/heartbeat-armed-at.ts` + clear `heartbeat-renew-seen.txt`
- [ ] Report heartbeat ID to the user in one line
