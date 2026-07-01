---
trdd-id: KI24GR5Z
title: Real-time token-spike + cache-miss guard — nudge the agent to stop runaway subagents/skills
column: complete
created: 2026-07-01T16:41:37+0200
updated: 2026-07-01T16:55:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: M
task-type: feature
parent-trdd: TRDD-a4e41e89
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: [config-schema]
attempts: 0
implementation-commits: []
---

# Real-time token-spike + cache-miss guard — nudge the agent to stop runaway subagents/skills

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-01

- **USER DIRECTIVE (verbatim):** "use janitor token report yourself to estimate and cap the token
  consumption. there must be a global token usage monitor that will immediately report any spike in
  token usage or any cache write caused by cache miss, and nudge the main claude to stop the
  subagents or the skill immediately."
- **ESTIMATE (ran `/janitor-token-report` on this live session, 2026-07-01):** 1559 heartbeat fires
  logged; **6.02M total output tokens**; mean 3861/fire, p50 162, p95 18295, **max 256820**; 79
  fires over the spike threshold; one fire wrote 84k output + **110k cache_creation** (a cache-miss
  spike + long reply). So spikes are real and large; the meter ALREADY records `output` +
  `cache_creation` per turn.
- **WHAT ALREADY EXISTS (TRDD-a4e41e89 + SMZFJVZ3 — do NOT rebuild):**
  - `token_meter.tail_turn_usage(transcript)` → the in-progress turn's `output_tokens`,
    `cache_creation_input_tokens` (the CACHE-MISS/cache-write signal), `input`, `cache_read`,
    `assistant_messages`, `tool_calls`. Tested turn-boundary parser.
  - `on-stop-token-meter.py` (Stop) logs per-heartbeat-turn usage; `/janitor-token-report` reports.
  - `pre-tool-token-budget.py` (PreToolUse) — Phase 2: reads `tail_turn_usage`, but is **OPT-IN
    (default OFF)**, checks **only `output_tokens`**, and only soft-advises "be concise".
  - `pre-tool-context-usage.py` (PreToolUse, DEFAULT-ON) — the analogous context-%-guard: advisory
    ≥60%, ENFORCE (auto-compact + deny) ≥85%. Precedent for a default-on per-tool-call guard.
- **THE GAP (this TRDD):** the budget hook must become the real-time monitor the user named —
  DEFAULT-ON, catch a CACHE-MISS spike (not just output), and issue a STRONG stop-the-subagents/skill
  nudge (with an OPT-IN hard enforcement that DENIES a new subagent spawn when in runaway territory).
- **DESIGN (extend, testable):**
  - NEW pure fn `token_meter.evaluate_turn_budget(usage, thresholds) -> BudgetVerdict` (tier =
    ok|advisory|hard + the tripped signals). Two signals: `output_tokens` and
    `cache_creation_input_tokens`; two tiers each (advisory / hard). Pure → unit-tested.
  - `pre-tool-token-budget.py`: flip DEFAULT to **ON** (opt-out `…TOKEN_BUDGET_ENABLED`); call
    `evaluate_turn_budget`; on `advisory` → `additionalContext` nudge (which signal, how much); on
    `hard` → STRONG nudge to STOP now — end the step, `TaskStop` background subagents, `/compact`;
    and when the tool being called is a SUBAGENT SPAWNER (`Task`/`Agent`) AND opt-in
    `…TOKEN_BUDGET_ENFORCE` is set → `permissionDecision: deny` (stop spawning MORE subagents — the
    biggest multiplier). Advisory is the always-on default (the user said "nudge"); the deny is opt-in.
  - Thresholds (all `CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_*`, generous so it is SILENT in normal use):
    `TURN_OUTPUT` advisory 10k (existing) / `TURN_OUTPUT_HARD` 40k; `TURN_CACHE_CREATION` advisory
    25k / `TURN_CACHE_CREATION_HARD` 75k. Any 0 disables that check.
- **"GLOBAL" scoping:** a PreToolUse hook is the ONLY surface that fires MID-TURN, so real-time
  per-session self-monitoring IS the actuator (a daemon can't nudge a turn in flight). A
  cross-fleet daemon monitor that injects a stop into an offending OTHER session reuses the
  fleet-inject substrate — deferred to TRDD-ME8V2YJF, noted not built here.
- **SHIPPED (this session, all tested):** `token_meter.evaluate_turn_budget` (pure classifier,
  output + cache-miss, two tiers, 0-disables) + `BudgetVerdict`. `pre-tool-token-budget.py` now
  DEFAULT-ON, calls the classifier, and via the pure `_response` helper emits an advisory nudge,
  a strong hard stop nudge, or (opt-in `…ENFORCE`) a `permissionDecision: deny` of a `Task`/`Agent`
  spawn at the hard tier. Tests: `evaluate_turn_budget` (7 unit cases) + the hook end-to-end via
  subprocess (default-on, cache-miss-independent-of-output, hard nudge, deny-under-enforce,
  no-deny-without-enforce, no-deny-non-spawner + the updated legacy cases). Full suite green; ruff +
  pyright clean. Docs: CLAUDE.md hook line (Phase 2→3), README troubleshooting + config knobs.
- **CAVEAT surfaced to the user:** a running session's hook env is baked at session start, so THIS
  session's guard only takes effect after a plugin reload / new session; the guard protects future
  turns/sessions, not the turn that shipped it.
- **NEXT ACTION:** none — shipped. Ships with the v0.26.0 batch (task #250, still gated on CPV#154).

## Why

The meter MEASURES (passive, after the turn) but nothing CAPS in real time. A single interactive
turn hit 256,820 output tokens here; cache-miss turns wrote 110k cache_creation (1.25× premium).
The user wants the monitor to fire the moment a turn spikes — especially a cache-miss cache write —
and tell the agent to stop the subagents/skill before the cost compounds. A PreToolUse hook sees the
in-progress turn's cumulative usage before each tool call, so it can nudge (or deny a new spawn)
exactly when the runaway is happening.

## Acceptance

- `evaluate_turn_budget` returns `ok` below both advisory thresholds, `advisory` at/above either
  advisory threshold, `hard` at/above either hard threshold; reasons name the tripped signal(s).
- The hook is DEFAULT-ON; SILENT below advisory; emits a nudge naming output AND/OR cache-miss at
  advisory; a STRONG stop nudge at hard; and (opt-in ENFORCE) DENIES a `Task`/`Agent` spawn at hard.
- Cache-miss (`cache_creation`) spikes are detected independently of output.
- Real unit tests for the pure fn (both signals, both tiers, disable-by-0) + the hook decision
  (advisory nudge / hard nudge / spawn-deny under ENFORCE / silent when disabled). ruff+pyright clean.

## Notes and lessons learned
