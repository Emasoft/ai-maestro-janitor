---
name: janitor-arm
description: Arms or renews the ai-maestro-janitor heartbeat cron. Use when first installing the plugin, upgrading from pre-stub (≤ v0.4.10), or in response to a [janitor-renew] nudge before the 7-day auto-expiry. Trigger with /janitor-arm or "arm the janitor heartbeat".
---

# Janitor arm

## Overview

Creates (or replaces) the single CronCreate heartbeat. The cron is **session-scoped by platform design** — it does NOT survive a Claude restart; see [Known limitations](#known-limitations-claude-code-platform). The cron prompt points at an **auto-rolling stub** in `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` (path survives every plugin *version* update — but not a load-source change; see Known limitations). The stub re-resolves the highest cached plugin version on every fire and `os.execv`'s into its `scripts/dispatch.py`, so future plugin updates roll forward without re-arming.

Re-arming is needed only on: first install, upgrade from pre-stub (≤ v0.4.10) once, or `[janitor-renew]` nudge. Re-running is safe and idempotent.

Full design rationale, atomic install, path-traversal safety, survival contract: [janitor-architecture](references/janitor-architecture.md): [Why the stub exists](references/janitor-architecture.md#why-the-stub-exists), [Operational rules](references/janitor-architecture.md#operational-rules), [Responsibility split and safety](references/janitor-architecture.md#responsibility-split-and-safety).

## Prerequisites

- `ai-maestro-janitor` plugin installed; `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` resolve at skill-invocation time.
- `CronCreate` / `CronList` / `CronDelete` available (Claude Code v2.1.98+).

## Instructions

0. **Refuse a non-user install (TRDD-db169d9e R5).** The janitor MUST be a
   USER-scope install — it guards OAuth, the global single-instance daemon, and
   drift for the WHOLE machine. Arming a project/local-scope janitor would create
   a per-project heartbeat and bind a machine-global guardian to one repo. Verify
   first:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/detectors/janitor-install-scope.py" --check
   ```

   If it exits NON-ZERO (prints a `[janitor-install-scope]` warning), **STOP — do
   NOT arm.** Relay the warning to the user: the janitor is installed at
   project/local scope and must be moved to user scope (the exact `claude plugin
   uninstall … / install … --scope user` commands are in the warning). Only
   proceed to step 1 when it prints `OK user-scope`.

1. Revoke this project's opt-out, then install (or refresh) the stub atomically.
   `/janitor-arm` arms only THIS project's heartbeat; it deliberately does NOT touch the
   machine-wide global kill-switch — a project arm must not silently undo a deliberate
   `/janitor-global-disarm`. To revive a globally-disarmed daemon, use `/janitor-global-arm`.

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   rm -f "$STATE_DIR/disarmed.flag"
   mkdir -p "${CLAUDE_PLUGIN_DATA}"
   STUB_SOURCE="${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py"
   STUB_DEST="${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py"
   TMP_DEST="${STUB_DEST}.tmp.$$"
   cp -f "$STUB_SOURCE" "$TMP_DEST"
   chmod +x "$TMP_DEST"
   mv -f "$TMP_DEST" "$STUB_DEST"
   ```

   The `disarmed.flag` removal is FIRST, before `CronCreate`, on purpose. Every step of this
   skill can be cut short by a rate limit or an ended turn, so the ordering decides which way
   a half-finished arm fails. Clearing the flag first means a turn that dies before step 5
   leaves *no cron and no opt-out* — the fleet guardian reads `cron_dead` and re-arms, and the
   arm self-heals. Clearing it last would leave *a cron and a stale opt-out*, and the guardian
   would file this project under "the user opted out" and never touch it again.

2. Resolve the cron cadence. The dynamic TTL-aware cadence tier (TRDD-0QQX9H0G, #83)
   writes the desired cron to `.janitor/state/desired-cadence.cron` on each fire; read
   THAT first so a dispatcher-driven re-arm (the `[janitor-renew]` marker) bakes the
   chosen tier — then fall back to config, then the `*/5` default:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   CRON=""
   [ -s "$STATE_DIR/desired-cadence.cron" ] && CRON="$(tr -d '\n' < "$STATE_DIR/desired-cadence.cron")"
   [ -z "$CRON" ] && CRON="${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON:-*/5 * * * *}"
   printf 'cron=%s\n' "$CRON"
   ```

   Use the resolved `$CRON` for `CronCreate` in step 5.

3. `CronList` → for each job whose prompt starts with `[janitor-heartbeat]`, `CronDelete`. Guarantees one heartbeat after arming.

4. Build the heartbeat prompt with `STUB_DEST` baked in:

   ```text
   [janitor-heartbeat]
   {{STUB_DEST}}
   Handle this fire's stdout per the janitor-heartbeat-protocol rule (in ~/.claude/rules/). If that rule is NOT loaded: surface stdout verbatim, act only on a line that is exactly `[janitor-resume]` (resume the pending task; the next lines carry the directive), and warn that the heartbeat-protocol rule is missing.
   ```

   > Rollout (TRDD-82OP4EN9): the marker-handling PROTOCOL lives in the installed rule
   > `janitor-heartbeat-protocol.md` (rules_installer refreshes it at every SessionStart),
   > so protocol/marker changes reach every session WITHOUT re-arming — the rule rides the
   > CACHED prefix at the 0.1× read rate instead of ~945 fresh input tokens per fire (the
   > pre-W3 fat prompt). Only THIS stub prompt (stub path + fallback line) and the cadence
   > still bake at arm time; changing those needs `/janitor-arm` (or the 7-day auto-expiry's
   > `[janitor-renew]`). Pre-W3 fat-prompt crons keep working — their inline protocol is a
   > superset the rule supersedes; re-arm them once to shed the per-fire input cost. An
   > ALREADY-armed pre-self-disarm cron still won't self-disarm on a global stop until
   > re-armed; stop such a cron with a one-time `/janitor-disarm`.

5. `CronCreate` with the resolved `$CRON` from step 2, `prompt` from step 4, `recurring: true`. The response will say **"Session-only (not written to disk…)"** — that is CORRECT and expected, not a failure: Claude Code scheduled tasks are session-scoped by design. Do NOT pass `durable: true` expecting persistence; no such guarantee exists (see [Known limitations](#known-limitations-claude-code-platform)).

6. Record arm timestamp + clear stale renew-dedupe:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"
   NOW=$(date +%s)
   printf '%s' "$NOW" > "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" && \
     mv -f "$STATE_DIR/heartbeat-armed-at.ts.tmp.$$" "$STATE_DIR/heartbeat-armed-at.ts"
   rm -f "$STATE_DIR/heartbeat-renew-seen.txt"
   # Record the cadence actually armed (TRDD-0QQX9H0G, #83) so the dispatcher's
   # cadence phase knows the live tier and stops re-emitting [janitor-renew] once
   # reconciled. Re-resolve the SAME way step 2 did (deterministic within an arm).
   CRON=""
   [ -s "$STATE_DIR/desired-cadence.cron" ] && CRON="$(tr -d '\n' < "$STATE_DIR/desired-cadence.cron")"
   [ -z "$CRON" ] && CRON="${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON:-*/5 * * * *}"
   printf '%s' "$CRON" > "$STATE_DIR/armed-cadence.cron.tmp.$$" && \
     mv -f "$STATE_DIR/armed-cadence.cron.tmp.$$" "$STATE_DIR/armed-cadence.cron"
   ```

7. **Report honestly.** The job WILL come back session-only — that is the platform's
   documented behavior, not a defect. Report:

   `Janitor armed: <cron> → auto-rolling stub (target: <version>). Heartbeat ID: <id>. Session-scoped (re-arms at the next SessionStart).`

   Append `(replaced <N>)` if step 3 deleted any. **Never claim "survives restarts"** — no
   CronCreate job does. Do not warn about a "downgrade": nothing was downgraded.

## Output

One line: cron expression, heartbeat ID, current stub target version (durable vs session-only per step 7). The stub file is written atomically to `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`; in this project's `.janitor/state/` it reads `desired-cadence.cron` (the dynamic cadence tier, #83), writes `heartbeat-armed-at.ts` + `armed-cadence.cron`, and removes `disarmed.flag` + `heartbeat-renew-seen.txt`. No other files written.

## Known limitations (Claude Code platform)

Two properties the heartbeat design must live with. See
[janitor-architecture](references/janitor-architecture.md#known-limitations).

1. **The heartbeat cron is SESSION-SCOPED — by design, not by defect.** Claude Code
   scheduled tasks live in the current conversation, are restored only on
   `--resume`/`--continue`, and auto-expire after 7 days; **there is no `durable`
   parameter** (verified against the official `tools-reference` / `scheduled-tasks`
   docs, 2026-07-13 — CC 2.1.207). The heartbeat therefore does NOT survive a Claude
   restart (crash / OOM / relaunch), and no argument can make it.

   This corrects a long-held misreading in this project — that "some CC builds silently
   downgrade `durable: true` to session-only" (ai-maestro-janitor#23). Nothing was ever
   downgraded: `durable: true` was simply an argument the platform ignores. We inferred a
   guarantee from a parameter NAME we passed, then filed a bug against the platform when
   observation disagreed, instead of reading the spec.

   **Consequence (load-bearing):** the SessionStart re-arm nudge + the `[janitor-renew]`
   marker are the **only** survival mechanism — they are NOT a workaround for an upstream
   bug and must never be removed on the theory that #23 got "fixed". For work that must
   genuinely outlive a session, the docs point elsewhere (Routines / desktop scheduled
   tasks / GitHub Actions) — which is exactly why the global **daemon** exists.
2. **`${CLAUDE_PLUGIN_DATA}` is not stable across load-source changes.** It
   resolves to `…-inline` for an inline/local load and `…-ai-maestro-plugins`
   for the marketplace load, so re-arming under a different load source writes a
   second stub dir and the prior cron keeps firing the old path. It survives
   plugin *version* updates (the reason the stub indirection exists); it does not
   survive a *load-source* change. Each `/janitor-arm` re-bakes the current path,
   so the active cron self-corrects on the next arm; orphaned dirs are harmless
   but accumulate.

**Assessed-safe CC interactions (no mitigation needed).** CC 2.1.183 reclassified
scheduled-task and webhook-trigger deliveries as *task-notifications*: in auto mode
they can no longer auto-approve a pending action or set the session title. The
heartbeat was verified UNAFFECTED on CC 2.1.191 — a heartbeat fire starts a fresh
turn whose tools are policy-approved; it never relied on the scheduled delivery
auto-approving a *pending* prompt. Recorded so the next CC-version compatibility
audit has a baseline (TRDD-6F7F7D60). CC 2.1.198 made subagents run in the
background by DEFAULT, so the `run_in_background: true` on the
`[janitor-memory-*]` marker's agent spawn is now REDUNDANT but harmless — kept
for clarity/explicitness.

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
