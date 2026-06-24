---
trdd-id: VJ8L465M
title: Memory-maintenance scheduler double-gates on the cadence stamp — the scheduled scope's pass is skipped and a 236k-token agent no-ops
column: todo
created: 2026-06-24T02:39:52+0200
updated: 2026-06-24T02:39:52+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 2
severity: HIGH
effort: M
labels: [memory, scheduler, wikimem, efficiency, correctness]
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
attempts: 0
last-test-result: not-run
implementation-commits: []
audit-trigger: manual
audit-target: scripts/detectors/memory-maintenance.py (the SCHEDULER) + the 6 janitor-memory-* agent skills + scripts/lib/memory_settings.py
audit-conclusion: issue-confirmed
external-refs: []
---

# TRDD-VJ8L465M — the wikimem scheduler stamps the cadence BEFORE the agent runs, so the agent skips the scheduled scope

## ⏵ STATE — READ THIS FIRST — 2026-06-24

**NEEDS USER DECISION — the fix changes the SCHEDULER's documented cross-session
dedupe contract (TRDD-b4b9e27c) and touches 6 agent skills + `memory_settings`; it
is correctness-critical, multi-file, and in the sensitive memory subsystem. I
confirmed the bug (code-traced) but did NOT fix it (a wrong change breaks the
dedupe oracle or the forge-proof marker). Surfaced for the user to decide the fix
shape.**

**Discovered live, 2026-06-24, during the autonomous overnight session:** the
heartbeat scheduler emitted `[janitor-memory-atomize]`, spawning the background
opus subconscious-agent, which abstained: *"ATOMIZE — NOTHING DUE: no scope crossed
its cadence boundary (LOCAL ran ~37 s ago, USER ~2.6 h ago; interval 12 h)."* This
was the **4th no-op memory-agent spawn of the night** (consolidate, split ×2,
atomize) — **~940k tokens spent confirming "nothing to do."**

**Budget + correctness impact:** in unattended overnight autonomy this burns
~236k tokens **per false dispatch** AND silently STARVES the scheduled scope's wiki
maintenance (the scope the scheduler picks never gets its pass run — its cadence
clock is reset without the work) — exactly when no human is watching.

## Confirmed root cause (code-traced, not assumed)

The scheduler and the agent **double-gate on the SAME cadence stamp**, and the
scheduler advances the stamp BEFORE the agent reads it:

1. **Scheduler** (`scripts/detectors/memory-maintenance.py`): `_pick` →
   `_first_due_intervention` selects the first `(scope, intervention)` that is due
   via `memory_settings.is_due(intervention, scope, root, now)` (lines 206-207, 226).
2. Line **278**: `memory_settings.mark_ran(intervention, scope_label, root, now)`
   — stamps the chosen `(intervention, scope, root)` — **BEFORE** the emit at line
   **292** (`print(marker)`). The inline comment (273-276) says this is deliberate:
   "Stamp BEFORE emitting: the stamp is the cross-session dedupe oracle … strictly
   safer than emitting-then-crashing."
3. **Agent** (the `janitor-memory-<pass>` skill it loads — verified in the SPLIT
   skill: *"Use `memory_settings.is_due("split", scope, root, now)` … If the list
   is empty, nothing is due in this scope — STOP cleanly"*) independently calls
   `memory_settings.is_due(intervention, scope, root, now)` and abstains on cadence.
4. `is_due` reads the very last-run stamp `mark_ran` writes (same intervention /
   scope-label / root keys — see `memory_settings` signatures). So ~37 s after the
   scheduler stamped LOCAL, the agent's `is_due(atomize, LOCAL)` → **False** (just
   stamped), `is_due(atomize, USER)` → False (2.6 h < 12 h) → **abstains on cadence,
   before ever examining the scope's CONTENT.**

**Net:** the scheduler stamps the scope's clock (claiming it, for dedupe) and the
agent then skips that scope **because of that very stamp**. The scheduled pass is
never executed; the scope's 12 h clock just resets. A 236k-token agent no-ops.

This reconciles the night's evidence: an EARLIER atomize did real work ("+7
atoms") — that happens only when **≥2 scopes are due**, so the scheduler stamps
one and the agent finds *another* still due and works it. When exactly **1 scope
is due**, the scheduler claims it and the agent finds nothing → no-op + skipped work.

## The gap (precise)

`mark_ran` is overloaded with TWO conflated jobs:
- **(J1) re-emit suppression** — stop the 5-min heartbeat re-emitting the same pass
  for the whole `*_per_day` cadence (the dedupe oracle the scheduler needs).
- **(J2) the agent's work-cadence gate** — "has this pass actually run recently?"

The scheduler's stamp-before-emit (correct for J1) trips the agent's gate (J2),
because both read/write the one stamp. The agent re-checking `is_due` is correct
for the MANUAL path (`/janitor-memory-atomize` with no scheduler pre-stamp) but
self-defeating on the scheduler-DISPATCHED path.

## Fix direction (for the USER to approve — touches the dedupe contract)

The two jobs must be DECOUPLED. Options:

- **(A) Two stamps.** Scheduler writes a short-TTL `dispatched-at` stamp (J1 — TTL
  ~ a few minutes, long enough for the agent to run, NOT the 12 h cadence); the
  AGENT advances the real `ran-at` cadence stamp (J2) **after it works** (or after
  it confirms by CONTENT that nothing is due). `is_due` reads `ran-at`; the
  scheduler's re-emit guard reads `dispatched-at`. Cleanest; touches
  `memory_settings` + the scheduler + the 6 skills' "mark_ran after the pass" step.
- **(B) Dispatch hand-off.** Scheduler passes the picked `(intervention, scope)` to
  the agent via a state file (the marker stays bare/forge-proof; the scope rides a
  side file the agent reads). The agent works EXACTLY that scope and drops its
  redundant `is_due` re-check; the scheduler keeps stamping. Smallest change to the
  scheduler, but removes the agent's independent cadence safety on the dispatched path.
- **(C) Flock-only dedupe for the dispatch window.** Scheduler does NOT advance the
  cadence stamp; J1 within a single heartbeat is already covered by the machine-wide
  dispatch flock (line 257). Add a short "emitted-recently" guard so the next 5-min
  fire doesn't re-emit before the agent finishes; the agent advances the cadence
  stamp after work. (A variant of A with one stamp + a short guard.)

Keep the **forge-proof bare marker** and the **cross-session dedupe** intact under
every option — those are load-bearing (TRDD-b4b9e27c).

## Verification (when the fix is built)

- Unit: scheduler emits `atomize@LOCAL` → the agent (or a simulated `is_due` at
  agent-time) finds LOCAL STILL due and works it (not abstain); the cadence
  (`ran-at`) advances only AFTER the pass, not at emit.
- Unit: two concurrent schedulers do NOT both emit the same `(intervention, scope)`
  (cross-session dedupe preserved).
- Unit: the next 5-min heartbeat does NOT re-emit a pass whose agent is still
  running / just ran (no re-emit storm).
- Manual path unchanged: `/janitor-memory-atomize` with no pre-stamp still gates on
  the real cadence.

## Why this matters

The whole point of the autonomous wikimem librarian is unattended upkeep. This bug
makes the scheduler's chosen scope the ONE that never gets maintained (its clock
resets without work), while paying ~236k tokens to discover the no-op — the worst
of both (no maintenance + max cost), and it compounds across an overnight loop.
