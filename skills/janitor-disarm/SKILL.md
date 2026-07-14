---
name: janitor-disarm
description: Stops the ai-maestro-janitor heartbeat cron. Use when pausing janitor activity without uninstalling, debugging heartbeat behaviour, or switching projects. Trigger with /janitor-disarm, "stop the janitor", or "kill the heartbeat".
---

# Janitor disarm

## Overview

Removes the janitor heartbeat entirely. After this skill runs, no further cron fires of `[janitor-heartbeat]` will occur, no drift lines will be emitted from dispatch.py, and the auto-renewal nudge chain stops. Detectors can still be invoked manually via `/janitor-audit`.

This is also the command the heartbeat **self-disarms** with: when a machine-wide stop flag is set (`/janitor-global-disarm` or `/janitor-global-pause`), `dispatch.py` emits a bare `[janitor-self-disarm]` marker and the session silently runs `/janitor-disarm` to delete its own cron — the only way a fired heartbeat turn costs zero (TRDD-RQ9FIFX6).

Use this when you want to pause janitor activity without uninstalling the plugin, when debugging heartbeat behaviour, or when moving to another project and want the current project's janitor silenced.

## Prerequisites

- `CronList` / `CronDelete` tools available (Claude Code v2.1.98+).
- `$CLAUDE_PROJECT_DIR` set (used to locate the per-project state directory).

## Instructions

1. Call `CronList`. Filter the returned jobs to only those whose `prompt` starts with `[janitor-heartbeat]`. Count them as `N`.

2. For each matched job, call `CronDelete` with its ID. If any `CronDelete` returns an error, continue with the rest — surface the error in the final report.

3. Remove the arm-timestamp and the renewal-dedupe file so a future `/janitor-arm` starts cleanly, then ask the **disarm guard** whether this disarm may record `disarmed.flag`:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   rm -f "$STATE_DIR/heartbeat-armed-at.ts" \
         "$STATE_DIR/heartbeat-renew-seen.txt"
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/disarm_guard.py"
   ```

   **Do NOT write `disarmed.flag` yourself.** The flag does not merely stop the heartbeat: it tells the FLEET GUARDIAN that a *human* deliberately stopped it, so the project becomes sacrosanct and is never re-armed — and it also suppresses the SessionStart re-arm nudge. It is the OFF switch for **both** of the heartbeat's survival paths, and it is the reason an agent-initiated disarm used to be *permanent* instead of self-healing. (On 2026-07-14 an agent disarmed to save tokens during a rate limit and the session sat dead for hours — TRDD-RDFWQIFA.)

   The guard prints one token:
   - `DISARM_RECORDED:<reason>` — the user asked (or a machine-wide stop is in force). The opt-out is recorded and the guardian will honor it.
   - `DISARM_UNVERIFIED` — nobody with authority asked. The cron is **still deleted**, so the heartbeat stops now; the flag is simply not written, and the fleet guardian may re-arm this project on a later beat. Report this honestly (see step 4) — do not retry, do not write the flag another way.

4. Report one line: `Janitor disarmed: <N> heartbeat(s) deleted.` If any `CronDelete` failed, append `; <M> deletion(s) failed — check CronList and retry`.

   If step 3 printed `DISARM_UNVERIFIED`, append: `— opt-out NOT recorded (no user request seen), so the fleet guardian may re-arm this project. If you want it to stick, type /janitor-disarm yourself.`

   **NEVER disarm on your own initiative.** The heartbeat is what guarantees an agent never stalls — after a turn, a compaction, or a rate limit, it is the ONLY thing that re-drives the session. If the problem is COST (a rate limit, an exhausted budget), the answer is `/janitor-global-maintenance`, which keeps firing at the 0.1× cache-read rate and keeps emitting the continue nudge: **go cheaper, never silent**. An agent that finds the token-economy argument for silence persuasive has just rediscovered the bug this guard exists to prevent.

**Do NOT delete `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`.** Removing it reads like the inverse of `/janitor-arm` step 1, but it is not: the data dir is per-PLUGIN, so that stub is a single machine-wide file every project's cron execs. This skill is also what a session runs on the bare `[janitor-self-disarm]` marker, so a `/janitor-global-disarm` has every armed session reach this skill at once — the first one to delete the stub strands all the others firing at a missing file, burning a full billed turn per fire, which is the exact cost TRDD-RQ9FIFX6 exists to eliminate. The stub is inert without a cron, and `/plugin uninstall` owns the data dir.

## Output

One line describing how many heartbeats were deleted. Writes exactly one file (`disarmed.flag`) and removes two (`heartbeat-armed-at.ts`, `heartbeat-renew-seen.txt`), all inside this project's `.janitor/state/`. Nothing outside the project is touched.

## Error Handling

- `CronList` fails → abort with the error verbatim. Cannot disarm without a list.
- Some `CronDelete` calls fail → continue processing the rest, report failures in the final line.
- `STATE_DIR` doesn't exist → the `mkdir -p` creates it; the `rm -f` is then a no-op. The `disarmed.flag` write must still happen: a never-armed project that the user explicitly disarms is opting out, and the guardian must honor that.
- Zero `[janitor-heartbeat]` jobs found → still run step 3 and report `Janitor disarmed: 0 heartbeat(s) deleted (nothing was armed).`

## Examples

```text
User: /janitor-disarm
User: stop the janitor
User: disarm the heartbeat
User: kill the janitor cron
```

## Scope

PROJECT-SCOPED. This skill ONLY withdraws this project's heartbeat crons, clears its arm-timestamp, and records its opt-out. It does NOT uninstall the plugin, prune logs, affect drift-detector seen-files, or touch anything shared between projects — in particular it never removes the machine-wide dispatcher stub. To re-arm, run `/janitor-arm` (which clears `disarmed.flag`).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — the cron-fire entry point; will no longer be invoked by any `[janitor-heartbeat]` cron once this skill completes.
- `$CLAUDE_PROJECT_DIR/.janitor/state/heartbeat-armed-at.ts` — arm timestamp, removed by this skill.
- `$CLAUDE_PROJECT_DIR/.janitor/state/heartbeat-renew-seen.txt` — renewal-nudge dedupe file, removed by this skill.
- `$CLAUDE_PROJECT_DIR/.janitor/state/disarmed.flag` — the opt-out record, written by this skill and read by `scripts/lib/fleet_scan.py` (`deliberately_unarmed`) so the fleet guardian leaves this project alone.

## Checklist

Copy this checklist and track your progress:

- [ ] `CronList` and filter prompts starting with `[janitor-heartbeat]`
- [ ] `CronDelete` each matched job, continue past per-job errors
- [ ] Remove `.janitor/state/heartbeat-armed-at.ts` and `heartbeat-renew-seen.txt`
- [ ] Write `.janitor/state/disarmed.flag` (the opt-out the fleet guardian honors)
- [ ] Leave `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` alone — it is machine-wide
- [ ] Report the deletion count (plus failure count if any) in one line
