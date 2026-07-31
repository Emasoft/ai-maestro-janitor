---
name: janitor-disarm
description: Stops the ai-maestro-janitor heartbeat cron. Use when pausing janitor activity without uninstalling, debugging heartbeat behaviour, or switching projects. Trigger with /janitor-disarm, "stop the janitor", or "kill the heartbeat".
---

# Janitor disarm

## Overview

Deletes this project's `[janitor-heartbeat]` cron. No further fires, no drift lines, no renewal
nudges. Detectors remain available on demand via `/janitor-audit`. To re-arm: `/janitor-arm`.

This is also the skill a session runs on the bare `[janitor-self-disarm]` marker: when a
machine-wide stop is set (`/janitor-global-disarm` / `/janitor-global-pause`), `dispatch.py`
emits that marker so each session deletes its own cron — the only way a fired heartbeat turn
costs zero, since a fire is a full billed turn even when it prints nothing (TRDD-RQ9FIFX6).

## Prerequisites

- `CronList` / `CronDelete` available (Claude Code v2.1.98+).
- `$CLAUDE_PROJECT_DIR` set (locates `.janitor/state/`).

## Three things this skill must never do

Each one is a bug that already happened. They are enforced by `tests/test_disarm_optout_invariant.py`,
which reads this markdown — but the reasons live here, because a test can only catch the mistake
after you have made it.

1. **NEVER disarm on your own initiative.** The heartbeat is the ONLY thing that re-drives a session
   after a turn ends, a compaction, or a rate limit. If the motive is COST, the answer is a SLOWER
   CADENCE (`CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON_SLOW`) — fewer fires, same work, and the
   continue-nudge keeps arriving: **go cheaper, never silent.** An agent that finds the token-economy argument for
   silence persuasive has just rediscovered the bug this guard exists to prevent. (2026-07-14: an
   agent disarmed to save tokens during a rate limit and the session sat dead for hours —
   TRDD-RDFWQIFA.)
2. **NEVER write `disarmed.flag` yourself** — `disarm_guard.py` is its only writer. The flag does not
   merely stop the heartbeat; it tells the FLEET GUARDIAN that a *human* deliberately stopped this
   project, so it becomes sacrosanct and is never re-armed, and the SessionStart re-arm nudge is
   suppressed too. It is the OFF switch for BOTH survival paths, which is why an agent-initiated
   disarm used to be permanent instead of self-healing.
3. **NEVER delete `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`.** It reads like the inverse of
   `/janitor-arm` step 1, but the data dir is per-PLUGIN: that stub is ONE machine-wide file every
   project's cron execs. A `/janitor-global-disarm` has every armed session reach this skill at once,
   so the first to delete it strands all the others firing at a missing file — burning a full billed
   turn per fire, the exact cost TRDD-RQ9FIFX6 exists to eliminate. The stub is inert without a cron;
   `/plugin uninstall` owns the data dir.

## Instructions

1. `CronList` → keep only jobs whose `prompt` starts with `[janitor-heartbeat]`. Count them as `N`.

2. `CronDelete` each one. On a per-job error, continue with the rest and report it in step 4.

3. Clear the arm state, then ask the **disarm guard** whether this disarm may record the opt-out:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   rm -f "$STATE_DIR/heartbeat-armed-at.ts" \
         "$STATE_DIR/heartbeat-renew-seen.txt"
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/disarm_guard.py"
   ```

   The guard prints exactly one token:
   - `DISARM_RECORDED:<reason>` — the user asked, or a machine-wide stop is in force. The opt-out is
     written and the fleet guardian will honor it.
   - `DISARM_UNVERIFIED` — nobody with authority asked. **The cron is still deleted**, so the
     heartbeat stops now; only the flag is withheld, so the fleet guardian may re-arm this project on
     a later beat. That is the intended self-healing behaviour. Report it (step 4) — do not retry and
     do not write the flag by another route.

4. Report ONE line: `Janitor disarmed: <N> heartbeat(s) deleted.`
   - Any `CronDelete` failed → append `; <M> deletion(s) failed — check CronList and retry`.
   - Guard printed `DISARM_UNVERIFIED` → append `— opt-out NOT recorded (no user request seen), so
     the fleet guardian may re-arm this project. To make it stick, type /janitor-disarm yourself.`

## Output

One line. Removes two files from this project's `.janitor/state/` (`heartbeat-armed-at.ts`,
`heartbeat-renew-seen.txt`); the guard writes `disarmed.flag` **only** on `DISARM_RECORDED` — an
unverified disarm writes nothing. Nothing outside the project is touched.

## Error Handling

- `CronList` fails → abort with the error verbatim; you cannot disarm what you cannot enumerate.
- Some `CronDelete`s fail → process the rest, report the failure count.
- `STATE_DIR` absent → `mkdir -p` creates it and the `rm -f` no-ops. Still run the guard: a
  never-armed project that a user explicitly disarms is opting out, and the guardian must honor it.
- Zero `[janitor-heartbeat]` jobs → still run step 3, and report
  `Janitor disarmed: 0 heartbeat(s) deleted (nothing was armed).`

## Scope

PROJECT-SCOPED. Withdraws this project's heartbeat crons, clears its arm state, and asks the guard to
record its opt-out. Does NOT uninstall the plugin, prune logs, touch detector seen-files, or remove
anything shared between projects — in particular never the machine-wide dispatcher stub. For a
machine-wide stop use `/janitor-global-disarm`; to spend less without stopping, slow the cadence.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/disarm_guard.py` — the sole writer of the opt-out flag; decides
  whether this disarm carries a human's authority.
- `$CLAUDE_PROJECT_DIR/.janitor/state/disarmed.flag` — the opt-out record, read by
  `scripts/lib/fleet_scan.py` (`deliberately_unarmed`) so the fleet guardian leaves the project alone.
- `$CLAUDE_PROJECT_DIR/.janitor/state/heartbeat-armed-at.ts`, `heartbeat-renew-seen.txt` — arm
  timestamp + renewal dedupe, both removed here.
- `/janitor-arm` — the inverse; it clears `disarmed.flag` via `arm_prepare.py`.

## Checklist

- [ ] `CronList`, filter to prompts starting with `[janitor-heartbeat]`
- [ ] `CronDelete` each match; continue past per-job errors
- [ ] Run the step-3 block: remove the two state files, then `disarm_guard.py`
- [ ] Do NOT write `disarmed.flag` yourself — the guard decides and writes it
- [ ] Leave `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` alone — it is machine-wide
- [ ] Report the deletion count in one line, honestly flagging `DISARM_UNVERIFIED`
