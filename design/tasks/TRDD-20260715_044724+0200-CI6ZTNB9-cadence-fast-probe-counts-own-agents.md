---
trdd-id: CI6ZTNB9
title: The cadence FAST probe counts the janitor's OWN background agents, so memory chores force re-arm churn
column: testing
created: 2026-07-15T04:47:24+0200
updated: 2026-07-16T03:20:26+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: high
labels: [heartbeat, cadence, token-economy, memory-agents]
relevant-rules: [1]
parent-trdd: 0QQX9H0G
---

# The cadence FAST probe counts the janitor's own background agents

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-16

**NEXT ACTION:** none — BOTH halves of issue #89 are implemented, tested, and lint-clean.
Awaiting human review (`testing` → `ai_review`/`human_review` → `complete`) and a commit (no git
command was run under this pass — the constraint of the assigning task).

**Half 1 (self-exclusion, this TRDD's original scope) — DONE, already landed on `main` before this
pass** (verified in the live tree, not re-implemented): `pending_agents.is_janitor_agent` /
`pending_agents.pending_external` (`scripts/lib/pending_agents.py`) filter the janitor's own
`janitor-memory-subconscious-agent` / `janitor-security-agent` spawns out of the cadence FAST
probe; `dispatch._cadence_active_waiting` calls `_pending_external_agent_count()` instead of
`_pending_agent_count()`. Covered by `tests/test_dispatch_cadence.py`'s
`test_is_janitor_agent_recognizes_housekeeping_agents` / `test_pending_external_excludes_only_janitor_agents`
/ `test_cadence_probe_ignores_a_lone_janitor_memory_agent` / `test_cadence_probe_still_flips_for_a_user_agent`.

**Half 2 (re-arm dwell, issue #89 option 2) — implemented THIS pass** (2026-07-16), as defense in
depth on top of half 1: `scripts/lib/heartbeat_cadence.py` gained `CadenceState.last_rearm_ts`,
`should_emit_renew()`, and `stamp_rearm()`; `dispatch._phase_cadence_tier` now gates
`[janitor-renew]` on `hc.should_emit_renew(...)`, env-tunable via
`CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DWELL_S` (default 1200s / 20 min,
`hc.DEFAULT_DWELL_S`). A tier PROMOTION always bypasses the dwell (recovery latency must stay
immediate); a demotion or same-tier cron change is gated by BOTH `demote_fires` (which tier wins)
and the dwell (how often the winning tier may actually pay for a re-arm). See "The fix, half 2"
below for the full design and "Verification" for the real command output.

**Relationship to [[TRDD-DLI76AUC]]:** that TRDD's deferred item #1 ("the demote hysteresis...plus
a hard re-arm cooldown") is a DIFFERENT, NOT-yet-approved mechanism scoped to tuning
`heartbeat_cadence_demote_fires` itself — explicitly "awaiting the USER's decision", and this pass
did **not** touch `heartbeat_cadence_demote_fires` (its default stayed 2, its semantics are
unchanged). The dwell implemented here is a SEPARATE, ADDITIVE axis (a new field + a new pure
function), matching issue #89's own option 2, not DLI76AUC's deferred item. Flagging the overlap
so the human reviewer can decide whether DLI76AUC's item #1 is now superseded/no-longer-needed, or
still wanted on top of this.

**Source of truth:** GitHub issue #89 (filed by the ai-maestro Claude, 2026-07-14). VERIFIED
against the live code this session — see Evidence.

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

1. **Decide the discrimination mechanism.** ✅ DONE. Filter-at-read via
   `pending_agents.is_janitor_agent` (substring match on `description`, itself sourced from the
   SubagentStart payload's `agent_type`/`description`) — not tag-at-record; `pending_external()`
   applies the filter and is the ONLY thing the cadence probe calls.
2. **Keep the resume/keep-going/directive FAST signals intact.** ✅ DONE — unchanged;
   `_cadence_active_waiting` only swapped its LAST line's `_pending_agent_count()` for
   `_pending_external_agent_count()`.
3. **Guard against the opposite failure.** ✅ DONE — `pending_external()` keeps a USER-spawned
   fork; `pending()` (the resume-directive source) is untouched, so a janitor agent that died is
   still listed there.
4. **Test.** ✅ DONE — `tests/test_dispatch_cadence.py`'s
   `test_cadence_probe_ignores_a_lone_janitor_memory_agent` /
   `test_cadence_probe_still_flips_for_a_user_agent`.
5. **[ADDED this pass] Half 2 — re-arm dwell.** ✅ DONE — see "The fix, half 2" + Verification below.

## The fix, half 2 — re-arm dwell (issue #89 option 2, implemented 2026-07-16)

Half 1 alone stops the SPECIFIC self-perturbation issue #89 reported, but does nothing for any
OTHER source of tier flapping (e.g. a real but short-lived user background agent, or repeated
`recent_activity` boundary crossings). Issue #89's own text lists dwell as an independent,
composable fix ("Any one of three fixes breaks it... both together kill it"), so this pass adds it
as defense in depth, entirely in the pure layer:

- `heartbeat_cadence.CadenceState` gained `last_rearm_ts: int = 0` (the epoch of the last fire that
  ACTUALLY emitted `[janitor-renew]`, default 0 = never). `commit_tier` carries it forward
  unchanged — it decides which tier WINS, never whether a re-arm fires.
- `heartbeat_cadence.should_emit_renew(*, desired_differs, committed, prev, now, dwell_s) -> bool`
  — pure. `False` immediately if the cron doesn't differ. `True` immediately on a tier PROMOTION
  (`committed`'s rank > `prev`'s rank, or `prev is None`) — recovery latency must never wait out a
  dwell. Otherwise (a demotion or a same-tier cron change) `True` only once
  `now - committed.last_rearm_ts >= dwell_s` (or `dwell_s<=0`/never-armed).
- `heartbeat_cadence.stamp_rearm(state, now)` — returns `state` with `last_rearm_ts=now`; called
  ONLY on a fire that actually emits the marker.
- `dispatch._phase_cadence_tier` wires it: computes `committed` via `commit_tier` as before, writes
  `desired-cadence.cron` unconditionally (so `/janitor-arm` always has the right target once dwell
  allows it), then calls `should_emit_renew` before deciding whether to `stamp_rearm` + persist +
  print `[janitor-renew]`. `CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DWELL_S` (default
  `hc.DEFAULT_DWELL_S = 1200`) is the env knob, `0` disables it entirely.

Two independent hysteresis axes now exist and are NOT redundant: `demote_fires` (inside
`commit_tier`) decides WHICH tier wins after N consecutive idle fires; the dwell decides how OFTEN
the winning tier may actually pay for the re-arm turn. A controller that flips its committed tier
every `demote_fires`-th fire would still re-arm every time without the dwell.

## Verification

1. Spawn a mock janitor-memory agent (record it in `pending_agents` with the janitor signature),
   run the cadence phase → tier stays at its idle value, no `[janitor-renew]`. ✅ PASS
   (`test_cadence_probe_ignores_a_lone_janitor_memory_agent`).
2. Record a non-janitor agent → tier flips to FAST (the legitimate case preserved). ✅ PASS
   (`test_cadence_probe_still_flips_for_a_user_agent`).
3. **[ADDED this pass]** A demotion within the dwell window emits no `[janitor-renew]`; the same
   demotion after the dwell expires does; a promotion always bypasses the dwell regardless of
   recency; the `_DWELL_S` env var (0 = disable, custom value) is honored; two consecutive
   suppressed fires both stay silent and neither resets the dwell anchor. ✅ PASS — 15 new tests
   across `test_heartbeat_cadence.py` (11 pure-function tests) and `test_dispatch_cadence.py` (6
   end-to-end phase tests via real state-dir I/O, no mocks).
4. Full `pytest` + `ruff check` green. ✅ VERIFIED 2026-07-16:
   - `uv run pytest tests/ -q -k "cadence or pending_agents or subagent"` → 161 passed.
   - `uv run pytest tests/ -q` (full suite, 2 runs) → 13087 passed, 1 skipped, 1 pre-existing
     unrelated failure (`test_rules_installer.py::test_shipped_rules_stay_under_the_context_floor_cap`,
     a `rules/*.md` byte-size cap, zero relation to cadence/pending-agents — not touched this pass).
     Zero NEW failures from this change. (A transient failure batch in `test_pre_tool_token_budget.py`
     during the first run was traced to a LIVE, unrelated concurrent process editing
     `scripts/hooks/pre-tool-token-budget.py` mid-run — confirmed via `git diff` growing between
     checks and the file's own tests going green in isolation once that process settled; that file
     was never touched by this pass.)
   - `uv run ruff check` on all 5 touched scripts + 3 touched test files → clean.

## Notes and lessons learned

[^1]: [ocd:2026-07-15 lmd:2026-07-15] A control loop whose FAST input is a condition it produces
  itself will oscillate for free. The cadence feature (TRDD-0QQX9H0G) treated "a background agent
  is running" as a proxy for "the user is waiting", but the janitor is the biggest spawner of
  background agents on the machine — its own memory maintenance. Lesson: before wiring a signal
  into a controller, ask "can the controller cause this signal?" If yes, it is feedback, not
  input, and it needs either exclusion or damping.

[^2]: [ocd:2026-07-16 lmd:2026-07-16] Exclusion (half 1) and damping (half 2, the dwell) are not
  substitutes for each other even though either alone reduces the SPECIFIC churn issue #89
  reported. Exclusion fixes a KNOWN self-perturbing input; damping bounds the re-arm RATE
  regardless of what caused the tier to flip, including causes nobody has identified yet. Keeping
  them as two independently-testable functions (`pending_agents.is_janitor_agent` /
  `heartbeat_cadence.should_emit_renew`) rather than folding the dwell logic into
  `_cadence_active_waiting` is what let this pass add half 2 without touching or re-verifying half
  1's tests at all — the two changes are provably orthogonal in the test suite, not just by
  argument.
