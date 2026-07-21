---
name: janitor-arm
description: Arms or renews the ai-maestro-janitor heartbeat cron. Use when first installing the plugin, upgrading from pre-stub (≤ v0.4.10), or in response to a [janitor-renew] nudge before the 7-day auto-expiry. Trigger with /janitor-arm or "arm the janitor heartbeat".
---

# Janitor arm

Creates (or replaces) the single heartbeat cron. The cron fires an **auto-rolling stub** in the
plugin DATA dir, which re-resolves the newest cached plugin version on every fire — so plugin
updates roll forward with **no re-arm**. Re-arming is needed only on first install, on a
`[janitor-renew]` marker, or when the user asks. Re-running is safe and idempotent.

**Four tool calls, in this order.** The count is the point: every tool round-trip re-reads the
whole conversation at the 0.1× cache-read rate (~52k weighted at a 520k context), so an arm costs
roughly what six quiet heartbeat fires cost. The dynamic cadence re-arms on every tier change, so
a cheap arm is what keeps that feature from costing more than it saves (TRDD-DLI76AUC). Do not add
calls back.

## 1. Prepare

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/arm_prepare.py"
```

One call does the scope guard, the atomic stub install, the cadence resolve, and hands you the
previous cron's id:

```
scope=ok
cron=*/15 * * * *
prior-cron-id=ff020fd5     # empty ⇒ unknown
sweep=no                   # yes ⇒ CronList and delete EVERY janitor heartbeat
maintenance=off            # global-on ⇒ fleet-wide maintenance is suppressing chores
```

- **`scope=refused` (exit 1)** → **STOP. Do not arm.** The janitor is installed at project/local
  scope, and it guards OAuth, the machine-global daemon, and drift for the whole machine — arming
  it here would bind a machine-global guardian to one repo. Relay the printed warning verbatim.
- **`sweep=yes`** → the prior id is unknown (first arm, or a previous arm died mid-way). Run
  `CronList` and `CronDelete` **every** job whose prompt starts with `[janitor-heartbeat]`. This
  costs one extra call and is how a crashed arm heals: it can never leave two heartbeats firing.
- **`sweep=no`** → skip `CronList` entirely. Go straight to step 2.
- **`maintenance=global-on`** (printed ONLY when fleet-wide maintenance is set; its absence
  means nothing is suppressing this host) → even a freshly armed heartbeat will fire
  cache-refresh-only (no chores, no daemon). Arming does NOT clear it — a project arm must not
  undo a machine-wide decision, and `/janitor-arm` re-runs on every SessionStart, so clearing
  it here would mean merely opening a session lifts fleet maintenance. **Say so in your step-5
  report** so the human knows why chores stay quiet; `/janitor-global-maintenance-off` is the
  lever.

> **The arm clears this project's LOCAL maintenance sentinel, and that is INTENTIONAL** —
> arming means the session starts in a known FULL state. **Do NOT re-enable maintenance in
> response**, at either scope, and never treat it as a fault to repair. Owner report
> 2026-07-21: agents collided this clear with the heartbeat nudge's "do NOT disable
> maintenance mode", concluded a rule had been violated, and restored maintenance at GLOBAL
> scope — where the next re-arm could not clear it. Every re-arm re-ran the same reasoning,
> so the fleet ratcheted into machine-wide maintenance nothing lifted: chores idled, plugin
> self-updates stopped, and no session could see the cause. If a project needs to stay quiet,
> that is a human's `/janitor-maintenance-mode` call, and if it keeps being cleared, report it
> rather than widening the scope.

## 2. Delete the old cron

`CronDelete` the `prior-cron-id` (or every id the sweep found). A delete that fails because the id
is already gone is fine — proceed.

## 3. Create the new cron

Build the heartbeat prompt, then `CronCreate` with `cron` **exactly as step 1 printed it** (it is
the tier the dispatcher asked for — re-arming a different cadence makes the dispatcher ask again on
the next fire, a renew loop that never converges) and `recurring: true`. Do **not** pass
`durable: true`: the CronCreate tool documents it as having no effect — every scheduled job is
session-only by platform design — so sending it implies a persistence that does not exist. Replace
`{{STUB_DEST}}` with the absolute path `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`:

```text
[janitor-heartbeat]
{{STUB_DEST}}
Handle this fire's stdout per the janitor-heartbeat-protocol rule (in ~/.claude/rules/). If that rule is NOT loaded: surface stdout verbatim, act only on a line that is exactly `[janitor-resume]` (resume the pending task; the next lines carry the directive), and warn that the heartbeat-protocol rule is missing.
```

The marker-handling protocol lives in the installed rule `janitor-heartbeat-protocol.md`, not in
this prompt — so protocol changes reach every session without a re-arm, riding the cached prefix
instead of costing fresh input tokens on every fire.

## 4. Record

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/arm_record.py" \
  --cron "<the cron from step 1>" --id "<the id CronCreate returned>"
```

Stores the cron id so the **next** arm can skip `CronList`. It refuses a malformed id rather than
storing one a later `CronDelete` would silently fail to match — which would leak a second live
heartbeat and double the fire cost with nothing reporting it.

## 5. Report honestly

Every scheduled job is **session-only** — it is not written to disk and dies on a Claude restart
(`CronList` shows `[session-only]`; the CronCreate response says the same). The heartbeat re-arms
itself at the next SessionStart, so a restart costs only the gap until the next session begins.

Report: `Janitor armed (session-only): <cron>. Heartbeat ID: <id>. Re-arms at the next SessionStart
after a restart (ai-maestro-janitor#23).` Append `(replaced <N>)` if you deleted any. **Never claim
"survives restarts"** — no scheduled job does on the current platform.

## Scope

ONLY installs the stub and arms the cron. Does NOT run detectors (`/janitor-audit`) or install the
plugin.

Arming puts THIS session into a known FULL state, so it clears this project's local opt-out
(`disarmed.flag`) and its local maintenance sentinel — a sticky local flag otherwise kept every
fire cache-refresh-only forever with nothing on screen saying so. It does NOT touch either
machine-wide flag: neither the global kill-switch nor global maintenance, because a project arm
must not silently undo a deliberate `/janitor-global-disarm` or `/janitor-maintenance-mode global`
— and this skill re-runs on every SessionStart, so it would undo them constantly. Use
`/janitor-global-arm` and `/janitor-maintenance-mode off global` for those. To stop:
`/janitor-disarm`.

## Error handling

- `arm_prepare.py` exits non-zero → surface its output; **do not create a cron**. A bad stub or a
  wrong install scope is worse than no arm.
- `CronList` fails → skip the sweep; duplicates are cleaned up by the next sweep.
- `CronCreate` fails → surface verbatim, do not retry automatically, and do not run step 4. With
  no id stored the next arm sweeps, which is the correct recovery.

## Resources

- [janitor-architecture](references/janitor-architecture.md) — design rationale, the stub
  indirection, the survival contract, and the
  [known platform limitations](references/janitor-architecture.md#known-limitations) (the
  `durable`→session-only downgrade; the DATA path not surviving a load-source change).
  - [Why the stub exists](references/janitor-architecture.md#why-the-stub-exists)
  - [Operational rules](references/janitor-architecture.md#operational-rules)
  - [Responsibility split and safety](references/janitor-architecture.md#responsibility-split-and-safety)
  - [Known limitations](references/janitor-architecture.md#known-limitations)
- `${CLAUDE_PLUGIN_ROOT}/scripts/arm_prepare.py` · `arm_record.py` — steps 1 and 4.
- `$CLAUDE_PROJECT_DIR/.janitor/state/` — reads `desired-cadence.cron`; writes
  `armed-cadence.cron`, `heartbeat-cron-id.txt`, `heartbeat-armed-at.ts`; removes `disarmed.flag`,
  `maintenance-mode` and `heartbeat-renew-seen.txt`.
- `/janitor-maintenance-mode` — sets the flags this skill reports. The LOCAL one is cleared by an
  arm; the GLOBAL one survives it and is only reported.
