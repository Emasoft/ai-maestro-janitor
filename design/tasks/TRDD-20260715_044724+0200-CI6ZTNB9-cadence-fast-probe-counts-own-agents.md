---
trdd-id: CI6ZTNB9
title: The cadence FAST probe counts the janitor's OWN background agents, so memory chores force re-arm churn
column: backburner
created: 2026-07-15T04:47:24+0200
updated: 2026-07-15T04:47:24+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: high
labels: [heartbeat, cadence, token-economy, memory-agents]
relevant-rules: [1]
parent-trdd: 0QQX9H0G
---

# The cadence FAST probe counts the janitor's own background agents

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**NEXT ACTION:** exclude janitor-spawned background agents from the FAST-tier signal in
`_cadence_active_waiting` (`scripts/dispatch.py:1400`). The narrowest fix (issue #89 option 1):
the pending-agent count must not include the janitor's own memory-maintenance agents.

**Source of truth:** GitHub issue #89 (filed by the ai-maestro Claude, 2026-07-14). VERIFIED
against the live code this session — see Evidence. UNTRACKED before this TRDD.

**Sibling, not parent:** [[TRDD-DLI76AUC]] priced the re-arm turn and deferred a hysteresis fix.
This is a DIFFERENT root cause (a self-perturbing controller input) with a different fix
(agent-source filtering). Either alone reduces churn; both together kill it. Do not fold them —
they touch different code and can land independently.

## The bug (verified 2026-07-15)

`_cadence_active_waiting(sd, now)` returns FAST when `_pending_agent_count() > 0`
(`dispatch.py:1400`). `_pending_agent_count()` (`dispatch.py:661`) returns
`len(pending_agents.pending())` — EVERY in-flight background agent recorded by the
`on-subagent-start` / `on-subagent-stop` hooks, with no distinction for who spawned it.

The janitor spawns its OWN background agents: every `[janitor-memory-*]` marker instructs the
session to launch a `janitor-memory-subconscious-agent` (observed live this session — an
`[janitor-memory-atomize]` fire spawned one). So the control loop reads an input it CREATES:

```
dispatch emits [janitor-memory-harvest]  → agent spawns → pending=1 → FAST (*/5)  ≠ armed → [janitor-renew] → re-arm  (turn #1 burned)
agent finishes                            → pending=0 → SLOW/MID     ≠ armed → [janitor-renew] → re-arm  (turn #2 burned)
```

**Two wasted re-arm turns per memory chore**, and the janitor schedules memory chores
constantly (harvest / consolidate / conflict / repair / atomize / split). A re-arm is a full
billed model turn (`CronDelete` + `CronCreate` + state writes) — so the feature spends tokens in
proportion to how much housekeeping the janitor itself queues, which inverts its purpose on a
busy corpus.

The issue's author confirmed it was not the resume path: `last-resume.ts` was 2407s old (past
`_RESUME_RECENCY_WINDOW_S = 1800`), no keep-going, empty `resume-directive.txt`. The only live
FAST input was the pending-agent probe.

## Evidence

- `scripts/dispatch.py:1377-1400` — `_cadence_active_waiting`, last line `return _pending_agent_count() > 0`.
- `scripts/dispatch.py:661-666` — `_pending_agent_count` → `len(pending_agents.pending())`.
- `scripts/hooks/on-subagent-start.py` / `on-subagent-stop.py` — record EVERY spawn; no source tag.
- The probe's own docstring says FAST means "waiting on something time-sensitive" — a background
  consolidate pass is housekeeping, definitionally not that.

## The fix (issue #89 option 1 — narrowest, recommended)

Exclude janitor-spawned agents from the FAST probe. The three options the issue lists, any one
of which breaks the loop:

1. **Exclude janitor-spawned agents from the FAST probe** (recommended) — a memory-maintenance
   agent is housekeeping, not a time-sensitive wait.
2. Minimum dwell time — refuse `[janitor-renew]` unless the tier has held ≥ N minutes.
3. Dead-band — only renew when the tier moves more than one step.

## DERIVED tasks (do these, they are the real work)

1. **Decide the discrimination mechanism.** `pending_agents.add()` is called by
   `on-subagent-start`; the janitor's memory agents are spawned via the `[janitor-memory-*]`
   marker with a known `subagent_type` (`ai-maestro-janitor:janitor-memory-subconscious-agent`)
   and a recognizable description. EITHER tag janitor-spawned entries at record time (needs the
   hook to see the subagent_type/description — verify the SubagentStart payload carries it), OR
   filter by that signature in `_pending_agent_count`. Prefer tag-at-record (single source of
   truth) if the payload exposes the type.
2. **Keep the resume/keep-going/directive FAST signals intact** — only the pending-agent term is
   self-perturbing; the other three (`_cadence_active_waiting` lines 1391-1397) are legitimate.
3. **Guard against the opposite failure:** a USER-spawned background agent (a real time-sensitive
   wait) must still flip to FAST. The filter must be janitor-agents-only, not all-agents.
4. **Test:** a janitor memory agent in flight must NOT flip the tier to FAST; a user background
   agent in flight MUST. Assert no `[janitor-renew]` is emitted across a memory-chore lifecycle.

## Verification

1. Spawn a mock janitor-memory agent (record it in `pending_agents` with the janitor signature),
   run the cadence phase → tier stays at its idle value, no `[janitor-renew]`.
2. Record a non-janitor agent → tier flips to FAST (the legitimate case preserved).
3. Full `pytest` + `ruff check` green.

## Notes and lessons learned

[^1]: [ocd:2026-07-15 lmd:2026-07-15] A control loop whose FAST input is a condition it produces
  itself will oscillate for free. The cadence feature (TRDD-0QQX9H0G) treated "a background agent
  is running" as a proxy for "the user is waiting", but the janitor is the biggest spawner of
  background agents on the machine — its own memory maintenance. Lesson: before wiring a signal
  into a controller, ask "can the controller cause this signal?" If yes, it is feedback, not
  input, and it needs either exclusion or damping.
