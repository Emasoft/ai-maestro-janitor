---
trdd-id: 5C42VCUX
title: Idle session never auto handoff-and-clears — the cron beats a huge context for hours and only ever RECOMMENDS /clear to the user
column: todo
created: 2026-08-06T13:23:24+0200
updated: 2026-08-06T13:23:24+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# Idle session never auto handoff-and-clears (owner failure report 2026-08-06, item 2)

## WHY (measured today)

A ~500k-token session sat idle for ~4 hours doing NOTHING but heartbeat fires. At the
`*/15` cadence with >5-min gaps, EVERY fire re-paid a ~400–460k cache-miss WRITE (two
were hook-flagged this session). The auto-clear machinery exists in-tree
(`cold_cache_compact.should_clear_when_long_idle`, `clear_enabled`,
`on-stop-proactive-compact.py` — the TRDD-D3PROACT family) yet it never engaged; the
model spent the whole day RECOMMENDING `/janitor-handoff-and-clear` to the user instead
of the system doing it. The owner's verdict: a whole skill and script wasted.

## The task (one atomic fix: make the idle auto-clear ACTUALLY ENGAGE)

1. Root-cause why `should_clear_when_long_idle` / the D3PROACT Stop-hook path did not
   fire this session: knob default (`clear_enabled()` is gated by its OWN knob — is it
   default-off?), the `user_present`/`active_waiting` gates, cooldown state, or version
   skew (session ran 2.3.0 while the machinery shipped later).
2. Decide + set the default so an idle session past the clear threshold clears ITSELF
   (with the handoff written first — see TRDD-PXP08ZQC for the zero-model-turn writer;
   until that lands, the existing skill flow fired via the ratified
   `run_chained_inject` chain is acceptable).
3. Regression evidence: an idle session with a big context must be observed to
   handoff-and-clear UNATTENDED within one clear-threshold window.

## Acceptance

- [ ] root cause named with the exact gate/knob that blocked today's engagement
- [ ] default-on decision recorded (or the owner's explicit choice if default stays off)
- [ ] one observed unattended handoff-and-clear on an idle big-context session
- [ ] the "recommend to the user" path demoted to fallback-only

## Pointers

- Failure narrative: this session's transcript 2026-08-06 morning (burn alarm at 3.3x,
  repeated stand-down turns, two ~400k cache-miss hook warnings).
- Machinery: `scripts/lib/cold_cache_compact.py`, `scripts/hooks/on-stop-proactive-compact.py`.
- Sibling: TRDD-PXP08ZQC (cache-expiry-aware EXTERNAL clear, zero model turns).
- Version-skew amplifier: the session ran 2.3.0 all day with 2.4.1 cached-pending-restart.
