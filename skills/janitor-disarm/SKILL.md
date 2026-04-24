---
name: janitor-disarm
description: Stops the ai-maestro-janitor heartbeat cron. Use when pausing janitor activity without uninstalling, debugging heartbeat behaviour, or switching projects. Trigger with /janitor-disarm, "stop the janitor", or "kill the heartbeat".
---

# Janitor disarm

## Overview

Removes the janitor heartbeat entirely. After this skill runs, no further cron fires of `[janitor-heartbeat]` will occur, no drift lines will be emitted from dispatch.sh, and the auto-renewal nudge chain stops. Detectors can still be invoked manually via `/janitor-audit`.

Use this when you want to pause janitor activity without uninstalling the plugin, when debugging heartbeat behaviour, or when moving to another project and want the current project's janitor silenced.

## Prerequisites

- `CronList` / `CronDelete` tools available (Claude Code v2.1.98+).
- `$CLAUDE_PROJECT_DIR` set (used to locate the per-project state directory).

## Instructions

1. Call `CronList`. Filter the returned jobs to only those whose `prompt` starts with `[janitor-heartbeat]`. Count them as `N`.

2. For each matched job, call `CronDelete` with its ID. If any `CronDelete` returns an error, continue with the rest — surface the error in the final report.

3. Remove the arm-timestamp and the renewal-dedupe file so a future `/janitor-arm` starts cleanly:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   rm -f "$STATE_DIR/heartbeat-armed-at.ts" \
         "$STATE_DIR/heartbeat-renew-seen.txt"
   ```

4. Report one line: `Janitor disarmed: <N> heartbeat(s) deleted.` If any `CronDelete` failed, append `; <M> deletion(s) failed — check CronList and retry`.

## Output

One line describing how many heartbeats were deleted. No files written beyond the two removed state files. No side effects other than CronDelete + filesystem cleanup.

## Error Handling

- `CronList` fails → abort with the error verbatim. Cannot disarm without a list.
- Some `CronDelete` calls fail → continue processing the rest, report failures in the final line.
- `STATE_DIR` doesn't exist → fine; the `rm -f` is a no-op in that case.
- Zero `[janitor-heartbeat]` jobs found → still remove the state files and report `Janitor disarmed: 0 heartbeat(s) deleted (nothing was armed).`

## Examples

```text
User: /janitor-disarm
User: stop the janitor
User: disarm the heartbeat
User: kill the janitor cron
```

## Scope

This skill ONLY removes heartbeat crons and clears the arm-timestamp. It does NOT uninstall the plugin, delete `.janitor/state/` data, remove logs, or affect drift-detector seen-files. To re-arm, run `/janitor-arm`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh` — the cron-fire entry point; will no longer be invoked by any `[janitor-heartbeat]` cron once this skill completes.
- `$CLAUDE_PROJECT_DIR/.janitor/state/heartbeat-armed-at.ts` — arm timestamp, removed by this skill.
- `$CLAUDE_PROJECT_DIR/.janitor/state/heartbeat-renew-seen.txt` — renewal-nudge dedupe file, removed by this skill.

## Checklist

Copy this checklist and track your progress:

- [ ] `CronList` and filter prompts starting with `[janitor-heartbeat]`
- [ ] `CronDelete` each matched job, continue past per-job errors
- [ ] Remove `.janitor/state/heartbeat-armed-at.ts` and `heartbeat-renew-seen.txt`
- [ ] Report the deletion count (plus failure count if any) in one line
