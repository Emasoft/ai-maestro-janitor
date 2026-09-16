---
trdd-id: 93TKV769
title: never-stop keep-going nudge is ON by default in every mode (fleet worked idle overnight)
column: published
created: 2026-07-16T17:46:21+0200
updated: 2026-07-16T20:24:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
release-via: publish
implementation-commits: [7cd8ea0]
---

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-16

**What happened.** The whole fleet sat idle overnight. Root cause: the never-stop continue-nudge
(`_phase_keep_going_nudge`) was **opt-in and OFF everywhere** — the `keep-going` flag was absent in
every project and no session was in maintenance mode. A healthy heartbeat therefore ran detectors,
and the daemon guardian even re-armed `cron_dead` sessions (recovery-audit shows repeated `rearm`
rungs on AgentlensPro / llm-externalizer / EMASOFT-ORCHESTRATOR-AGENT), but **nothing ever told the
agents to keep working** — `rearm` restarts the heartbeat, it does not drive the task.

**The fix (this TRDD).** The nudge is now **ON BY DEFAULT in every mode**. The user directive
(2026-07-16): "the very core of the janitor job is to ensure agents continue to work in the user's
absence" + "no matter what, even in maintenance mode, it always nudges the claude to work."

**Current state:**
- **IMMEDIATE (running fleet)** — DONE. Wrote the `keep-going` flag into all **41** armed projects,
  and cleared **6** stray local + the global maintenance flags. The CURRENTLY-CACHED dispatch.py
  (v0.45.0) already honors `keep-going`, so the live fleet nudges on the next fire with NO publish.
- **DURABLE (code)** — DONE + COMMITTED (`7cd8ea0`). `_phase_keep_going_nudge` defaults ON;
  silenced only by the explicit `keep-going-off` sentinel (full mode) or `keep_going_default=false`;
  maintenance always nudges. Full suite 13111 pass (the one inverted test fixed), ruff clean.
- **PUBLISH** — the durable code reaches the fleet only after a release + daemon roll + reload.
  Still HELD by the owner's gate; the IMMEDIATE flag-write is what un-idles the fleet now.

**NEXT ACTION:** none — code complete + committed + verified. `column: complete`, `release-via:
publish`. The ONLY remaining step is the (held) publish; take it only on the owner's explicit go.

## Problem

The janitor's #1 promise — keep the fleet working while the user is away — did not hold. The
mechanism that delivers it (the keep-going continue-nudge, TRDD-TKNSTP82) existed but was
**opt-in**: it fired only under the per-project `keep-going` flag OR maintenance mode. Neither was
set, so every unattended session that finished a turn with no rate-limit / compact / drift signal
went silent and stalled. The guardian's `cron_dead → rearm` kept the *heartbeat* alive but never
drove *work*.

## Decision (user 2026-07-16)

Flip the nudge to **DEFAULT-ON in every mode**. It is a bounded, single-line addition to an
already-scheduled heartbeat turn — not a token runaway — and it is the literal core janitor job.
Silence becomes the deliberate act, via exactly two levers so it stays reversible.

## Change

- `scripts/dispatch.py::_phase_keep_going_nudge` — gate rewritten:
  - `maintenance` → always nudges (unchanged; "even in maintenance it always nudges").
  - full mode → nudges **by default**; returns early ONLY if the `keep-going-off` sentinel exists,
    or `CLAUDE_PLUGIN_OPTION_KEEP_GOING_DEFAULT` is false AND the `keep-going` flag is absent
    (legacy opt-in).
- `.claude-plugin/plugin.json` — new `keep_going_default` boolean userConfig (default true).
- `skills/janitor-keep-going/SKILL.md` — ON clears `keep-going-off` + writes `keep-going`; OFF now
  WRITES the `keep-going-off` sentinel (removing the on-flag alone no longer silences the default);
  overview/table/description updated to default-ON.
- `tests/test_dispatch_phases.py` — the three tests whose premise inverted (full-mode-no-flag) now
  prove default-ON; added: off-sentinel silences full mode, maintenance overrides the off-sentinel,
  and `KEEP_GOING_DEFAULT=false` restores the opt-in.

## Levers (reversibility)

| lever | effect |
|---|---|
| default (`keep_going_default=true`) | every armed session nudges every fire, all modes |
| `/janitor-keep-going off` (writes `keep-going-off`) | silences THIS session's FULL-mode nudge only |
| `/janitor-maintenance-mode off` | the only way to stop a maintenance-mode nudge |
| `keep_going_default=false` | restores the pre-2026-07-16 opt-IN behaviour |

## Bug autopsy (guardrail)

The nudge was opt-in because of an over-cautious reading of RULE-1 (don't take charge unprompted).
But keeping an *already-working* agent going is not "taking charge" — it is the guardian's whole
job, and the user has now made that explicit. The guardrail comment in the code records WHY the
default is ON so a future "simplify back to opt-in" does not silently re-break overnight continuity.

## Verify

`uv run pytest tests/test_dispatch_phases.py -q` (59 pass) + full `pytest` + `ruff check` green
before publish. Live proof: on the next heartbeat, an armed idle session prints
`[janitor-resume]` + "continue your pending task (keep-going mode) …".
