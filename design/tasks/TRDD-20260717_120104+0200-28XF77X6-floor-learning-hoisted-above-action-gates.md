---
trdd-id: 28XF77X6
title: Learn the post-compaction floor BEFORE the action gates — the v0.49.0 floor gate never engaged
column: complete
created: 2026-07-17T12:01:04+0200
updated: 2026-07-17T12:14:00+0200
current-owner: session
task-type: bugfix
release-via: publish
parent-trdd: D3PROACT
implementation-commits: [87c8b56]
---

# Learn the post-compaction floor BEFORE the action gates — the v0.49.0 floor gate never engaged

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-17

**NEXT ACTION:** publish (patch bump) on USER go — the janitor runs from the installed CACHE, so
this fix is INERT until released + auto-deployed. Code LANDED in `87c8b56`: `floor_needs_learning`
+ learn-first reorder at both call sites + the test fixes. All 4 new/updated regressions were
proven to FAIL on the pre-fix code (stash → run → restore); 350 related tests + ruff green.

## The bug (found LIVE, 2026-07-17, this session — never reported by any test)

v0.49.0 (TRDD-D3PROACT) shipped TWO stops for the infinite-compact loop: the 350k threshold
(works, verified live) and the post-compaction FLOOR gate (`ctx − floor ≥ min_gain`). The floor
gate is **inert in production**: `refresh_floor` — the measurement that teaches the floor — is
placed BEHIND the three ACTION gates in both call sites:

```
enabled? → in_cooldown? → user_is_present? → active_waiting? → [refresh_floor + decide]
```

**Every one of those gates is stamped closed by the compaction itself:**

| gate | closed by | window |
|---|---|---|
| `in_cooldown` | the compact trigger's own `mark_fired` | 600 s |
| `active_waiting` (resume recency) | the compaction's auto-resume → `last-resume.ts` | 1800 s |
| `active_waiting` (keep-going) | the keep-going sentinel | **forever** |

The floor becomes observable when the compaction lands (`last-compact.ts`); the auto-resume
stamps `last-resume.ts` seconds later. The 30-min resume window swallows the 10-min cooldown
whole, and any session that resumes more often than every 30 min — or has keep-going ON —
**never** opens the gates. That population is exactly the long unattended session the proactive
trigger was written for. The feature's own success conditions permanently disable its own
safety gate.

**Live evidence (this repo, 2026-07-17):** compaction landed 11:34:06 (`last-compact.ts` =
1784280846); auto-resume stamped 11:34:15; three heartbeat fires + several Stops followed;
cooldown expired 11:41:41; at 11:46 (`elapsed=864s`, cooldown long over, resume window still
open) `compact-floor.json` still did not exist. Floor learned: **never**.

**Why the test suite passed:** `test_does_not_loop_after_a_compaction` stamps only
`mark_compacted` — no `mark_fired`, no `last-resume.ts`. That is a state production can never
be in, because the compact that causes a compaction always stamps the cooldown first, and the
auto-resume always stamps the recency. The test proved the gate works in a configuration that
does not exist.

**The category error:** cooldown / presence / active-waiting are sound reasons not to
**compact** (lossy, must not interrupt). None of them is a reason not to **measure** a number
sitting in the transcript. An observation was filed behind action gates.

**Blast radius today:** none — the ~308k floor sits under the 350k threshold, so the threshold
(the belt) holds and no loop occurs. But the floor gate (the suspenders) was the stop that
survives the floor growing past the threshold as plugins are added; without this fix, the day
the floor crosses 350k the loop silently returns.

## The fix

1. **NEW `cold_cache_compact.floor_needs_learning(state_dir) -> bool`** — "has a compaction
   landed that no floor measurement observed?" = `last_compact > floor_ts`. Two tiny state
   reads, never raises.
2. **Reorder BOTH call sites** to: `enabled → learn-if-pending → cooldown → present →
   active-waiting → compact decision`. The transcript is read at the learn step only while a
   compaction is actually unmeasured (once per compaction); the common Stop pays two tiny
   reads. The compact decision then uses `read_floor`.
3. **Fix the loop test** to stamp the REAL post-compaction state (`mark_fired` +
   `mark_compacted` + `last-resume.ts`), and add regressions: hook-level
   floor-learned-through-closed-gates (incl. keep-going + user-present), dispatch-level
   analogue, lib-level `floor_needs_learning` lifecycle.

## Pass criteria

- First Stop/fire after a compaction records the floor even with cooldown active, resume
  recency held, keep-going present, and the user present.
- The compact ACTION still vetoed by all existing gates (no behavior change to firing).
- Loop test reproduces the production state and still proves: no re-fire at the floor, no
  re-fire at floor+34k, fire at floor+391k.
- Full suite + ruff green.

## Out of scope

- The hook's duplicated `1800` recency constant (mirrors dispatch's `_RESUME_RECENCY_WINDOW_S`)
  — pre-existing, harmless to this fix.
- Floor learning at the SessionStart / rate-limit reactive paths — redundant: Stop fires at the
  end of every turn including the first after a restart, so the hoisted Stop-side learn covers
  them.
- The keepalive items (test-isolation leak, flood breaker) — separate, awaiting USER call.

## Notes and lessons learned

[^1]: [id:ATOM-OBSV-GATE, status:valid, keywords:"floor_never_learned observation_behind_action_gates measurement_gated_by_the_thing_it_measures compact_loop_gate_inert", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT place a passive MEASUREMENT behind the gates that veto the ACTION it informs, BECAUSE
  the action's own side effects can hold every gate closed in exactly the target population —
  here the compaction stamped the cooldown AND the resume recency, and keep-going holds
  active-waiting forever, so the floor was never learned and the loop-killing gate never
  engaged. DO gate observations only on "is there something unobserved?" and record before any
  early-return.

[^2]: [id:ATOM-TEST-IMPS, status:valid, keywords:"test_passed_on_impossible_state fixture_missing_side_effects mark_compacted_without_mark_fired", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT hand-build a test fixture's state from the ONE stamp the assertion needs, BECAUSE the
  production event writes SEVERAL stamps and the omitted ones may be exactly what blocks the
  code under test — the loop test stamped `mark_compacted` alone, a state that cannot exist
  (every compaction is preceded by `mark_fired` and followed by a resume stamp), so it proved
  the gate works in a configuration production never reaches. DO reproduce the event's FULL
  side-effect set in the fixture.
