---
trdd-id: AR9IUGIJ
title: Eliminate the re-arm requirement — no session should need /janitor-arm on every start, update, or tier change
column: todo
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T13:31:48+0200
current-owner: claude-ai-maestro-janitor
task-type: spike
scope: project
severity: major
relevant-rules: []
implementation-commits: []
---

# Eliminate the re-arm requirement (owner failure report 2026-08-06, item 6)

## WHY

The heartbeat cron is session-only by platform design (`CronCreate durable:true` is
documented no-effect), so today the arm must re-run: at every SessionStart, after /clear,
on every `[janitor-renew]` tier change, and whenever the stub path moves. Each arm costs
~6 quiet fires' worth of tokens (TRDD-DLI76AUC measured it), the renew loop churns on
tier flapping (TRDD-CI6ZTNB9 — corroborated again today: one */5 promotion cycle right
after a background agent finished, then straight back to */15), and a missed re-arm means
a dark session. The auto-rolling stub already removed the per-UPDATE re-arm; the rest of
the requirement still stands and the owner wants it GONE.

## The spike (evaluate, pick, implement the winner)

- **A. Upstream durable crons**: file the ask on the Claude Code side (durable:true is
  accepted-but-inert today). Cleanest end state; timeline not ours.
- **B. External trigger**: the machine-global daemon (or the TRDD-PXP08ZQC watcher)
  detects an armed-project session whose cron died (restart//clear) and TYPES the
  heartbeat/resume via the ratified injection chain — the cron stops being the only wake
  source, so a lost cron self-heals without a model-side arm. Builds on
  fleet_scan's cron_dead diagnosis + fleet_inject (both exist).
- **C. Cost-floor the arm**: if A and B both fail, collapse the 4-call arm to fewer
  calls and stop re-arming on tier changes below a threshold (widen
  `should_emit_renew` hysteresis) so the requirement stays but costs ~nothing.

## Acceptance

- [ ] one option chosen with measured/argued costs for all three
- [ ] after implementation: a killed cron (restart or /clear) is re-armed with ZERO
      model-turn arm cost in the common case, or the upstream ask is filed + linked
- [ ] renew churn from tier flapping measurably reduced (ties into TRDD-CI6ZTNB9)

## Pointers

- Arm cost + 4-call contract: the janitor-arm skill (TRDD-DLI76AUC).
- Tier machinery: `lib/heartbeat_cadence.py` (`should_emit_renew`, hysteresis).
- Recovery rungs that already type commands into panes: `lib/fleet_inject.py`,
  `lib/fleet_restart.py` (`cron_dead → rearm` exists TODAY as a daemon recovery —
  option B may be mostly wiring + defaults, not new machinery).
