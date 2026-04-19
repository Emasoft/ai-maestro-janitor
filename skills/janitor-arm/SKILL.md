---
name: janitor-arm
description: Arms (or re-arms) the ai-maestro-janitor heartbeat cron in the current Claude Code session. Use when installing the janitor for the first time, after a plugin version bump, or after a long idle when the previous heartbeat has expired. Trigger with `/janitor-arm`, "arm the janitor", "start the janitor heartbeat", or "re-arm the janitor".
---

# Janitor arm

## Overview

Creates (or replaces) the single durable CronCreate heartbeat that drives the ai-maestro-janitor plugin. Each cron fire is a fresh user turn that runs `scripts/dispatch.sh` and surfaces any drift lines the detectors emit. Also keeps the Anthropic prompt cache warm during idle periods (every fire inside the 5-minute TTL refreshes the cache) and recovers from rate-limit windows (fires queue during 429 and deliver in batch when the window clears).

This skill is the ONLY way to start the janitor. Hooks cannot call CronCreate; only an in-session turn can, which is why arming lives in a skill.

## Prerequisites

- `ai-maestro-janitor` plugin installed at project scope in the current project.
- `CronCreate` and `CronList` tools available (Claude Code v2.1.98+).
- `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin's installed root directory at skill-invocation time.

## Instructions

1. Resolve the dispatch-script absolute path. Use `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh` — the env var is set by Claude Code when the skill runs. Save it as `DISPATCH_PATH`.

2. Read the heartbeat cron expression from `${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON}`, defaulting to `"*/4 * * * *"` if unset.

3. Call `CronList` to find any existing janitor heartbeats. Heartbeat jobs are identified by the marker string `[janitor-heartbeat]` at the start of their prompt. For each matching job, call `CronDelete` with its ID. This guarantees exactly one heartbeat after arming — even if this skill was invoked to re-arm or to update the cron expression.

4. Construct the heartbeat prompt with the resolved `DISPATCH_PATH` baked in. Use this exact template (replace `{{DISPATCH_PATH}}` with the absolute path from step 1):

   ```
   [janitor-heartbeat]

   Silently run `bash {{DISPATCH_PATH}}` and process its stdout:

   - If a line starts with `[janitor-resume]`: the rate-limit window cleared. Resume the previous pending task without further prompting — pick up from whatever the user was last doing.
   - If a line starts with `[pr-reconciler]`, `[worktree-janitor]`, `[trdd-drift]`, `[trdd-reminder]`, or `[task-pr-mismatch]`: surface the finding verbatim to the user as a short drift notice and suggest they run `/janitor-audit` for a consolidated report with remediation commands.
   - If dispatch prints nothing: respond with nothing and end the turn. Do not acknowledge the heartbeat.

   Do not spawn sub-agents. Do not start long tasks. Do not re-read unrelated files. This is a periodic heartbeat; process the output in one pass and stop.
   ```

5. Call `CronCreate` with these parameters:
   - `cron`: the expression from step 2
   - `prompt`: the prompt from step 4
   - `durable`: `true` — survives session restarts; on next launch, Claude Code resumes the job automatically.
   - `recurring`: `true` — fires on every match.

6. Report the result to the user as a single line: `Janitor armed: <cron> → runs dispatch.sh each fire. Heartbeat ID: <returned-id>.`

7. If step 3 found and deleted existing heartbeats, mention this in the report: `(replaced <N> existing heartbeat(s))`.

## Output

One line of text to the user describing what was armed and the heartbeat ID returned by `CronCreate`. No files written, no bash side effects.

## Error Handling

- If `${CLAUDE_PLUGIN_ROOT}` is unset, abort with: "ai-maestro-janitor does not appear to be installed in this session. Run `claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope project` first."
- If `CronList` fails, skip step 3 and proceed to `CronCreate`. A duplicate heartbeat is harmless — dispatch.sh is idempotent and the seen-files dedupe repeat drift.
- If `CronCreate` fails, surface the error verbatim. Do NOT retry automatically.
- If the dispatch script does not exist at `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh`, abort — the plugin cache is in an unexpected state.

## Examples

```
User: /janitor-arm
User: arm the janitor
User: start the janitor heartbeat
User: re-arm the janitor after the plugin update
```

## Scope

This skill only ARMS the heartbeat cron. It does NOT run detectors itself (that is `/janitor-audit`). It does NOT install the plugin. It does NOT modify plugin files or userConfig. Once armed, the cron persists via `durable: true` until `CronDelete` is called explicitly, the recurring task hits its 7-day auto-expiry, or the user uninstalls the plugin.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `DISPATCH_PATH` from `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh`
- [ ] Call `CronList` and `CronDelete` any existing `[janitor-heartbeat]` job
- [ ] Call `CronCreate` with durable=true, recurring=true, and the heartbeat prompt
- [ ] Report heartbeat ID to the user in one line
