---
trdd-id: ZCODD6YS
title: The janitor meters its OWN heartbeat cost and self-throttles against a user budget
column: proposal
created: 2026-07-23T13:44:58+0200
updated: 2026-07-23T13:44:58+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
approval-tier: 2
relevant-rules: [1]
external-refs: [janitor#78]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-23

- STATUS: PROPOSAL, awaiting Tier-2 (MANAGER) approval. No code written. Do NOT git add/commit here
  (a later sequential step commits; parallel git writes corrupt the index).
- WHAT: Dogfood the janitor's own token-forensics ON ITSELF. Two deliverables:
  1. REPORT — a heartbeat-only weekly rollup ("$N this week on quiet fires") in `/janitor-token-report`.
  2. THROTTLE — a fail-open self-budget check in `dispatch.py` that, when the janitor's OWN rolling
     7-day heartbeat cost crosses a new generous `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET`
     (0 = disabled), escalates a throttle: cap cadence at the SLOW floor → auto-enter LOCAL
     maintenance → auto self-disarm (`[janitor-self-disarm]`).
- KEY FACT: EVERY actuator, telemetry sink, and per-project channel already exists. D2 only wires
  the EXISTING meter's output (`token-meter.jsonl`) back into the EXISTING throttle inputs
  (`_resolve_heartbeat_mode`, `_phase_cadence_tier`). VERIFIED against the tree 2026-07-23: no budget
  mechanism exists; the closest sibling `_phase_heartbeat_cost()` (janitor#78) only LOGS an external
  cost CLI's output — it never throttles.
- NEXT ACTION: on approval → `git mv` to `design/tasks/`, set `column: planned`, then implement per
  "## The fix" file-by-file. Start with the PURE evaluator in `token_meter.py` + its unit tests,
  because every actuator consumes its verdict.
- LOAD-BEARING GOTCHAS (do NOT carry a wrong version forward):
  - The self-budget phase MUST run AFTER every resume/compact early-return in `main()` — else a
    recovery fire could be throttled/disarmed mid-recovery. Place it beside `_phase_cadence_tier`.
  - `token-meter.jsonl` logs BOTH heartbeat AND interactive turns (since TRDD-DLI76AUC #4). The
    budget MUST filter `heartbeat == True` (missing → True). Summing user turns would silence the
    janitor during the user's own expensive work — the exact backwards mistake logged twice before.
  - Actuate ONLY local flags (`state.MAINTENANCE_FLAG` + THIS cron's `[janitor-self-disarm]`). NEVER
    `global_state` maintenance/kill-switch — a per-project budget must never stop the fleet
    (TRDD-X92VBFNF per-project channeling invariant).
  - Fail-open: wrap the whole phase in try/except; a metering exception degrades to "no throttle",
    never raises. A metering bug breaking survival is the cardinal sin.
- SUPERSEDED — do NOT carry forward: (none yet).
- DURABLE ARTIFACTS to read before acting: `scripts/lib/token_meter.py`, `scripts/dispatch.py`
  (`_phase_heartbeat_cost`, `_phase_cadence_tier`, `_resolve_heartbeat_mode`, `main`),
  `scripts/lib/heartbeat_cadence.py`, `scripts/token_report.py`, `scripts/lib/token_baseline.py`.

## The problem

The janitor is a token-forensics tool — it ships `token-usage-anomaly`, `window-burn-rate`,
`pre-tool-token-budget`, `/janitor-token-report`, and a dynamic TTL-aware cadence (TRDD-0QQX9H0G)
specifically to keep other sessions' costs bounded. But it does NOT measure or bound its OWN cost.

The heartbeat is not free. A cron FIRE is a full Claude turn that re-reads the whole cached
transcript. Measured (per the project map): a single quiet fire on a ~510k-context session bills
≈ 507k cache_read ≈ $0.76; at `*/5` (12 fires/h) that is ~$9/h of pure idle heartbeat, versus
~$1.5/h at the `*/30` floor. The dynamic cadence (TRDD-0QQX9H0G) already cuts this ~6x by demoting
an idle session toward SLOW — but it demotes on ACTIVITY signals, never on accumulated COST. A
session that stays "actively waiting" (pending directive / recent resume) is pinned at FAST
indefinitely, and nothing caps the total the janitor spends on itself over a week.

The tool that measures burn should be the FIRST thing to self-throttle. Today it is the only
cost-aware component with no budget of its own. The meter's output (`token-meter.jsonl`, one line
per heartbeat turn since TRDD-a4e41e89) is written and read only for a human-facing report; it is
never fed back into the cadence/mode inputs that could act on it.

## The fix (this TRDD's scope)

Wire the existing per-turn meter into the existing throttle. Two deliverables, seven files (five
edited, two reference-only boundary markers). Grounded in the authoritative Phase-1 map.

### Deliverable 1 — the report rollup (`scripts/token_report.py`)

`main()` (≈L441-555) already partitions heartbeat records (`beats = [r for r in records if
r.get('heartbeat', True)]`, ≈L491) and has rolling-window helpers (`_window_metrics` ≈L63,
`_render_window` ≈L222). Add a heartbeat-ONLY weekly rollup line: the trailing-7d weighted-token
sum of `beats` (via `token_baseline.rolling_sum`), converted to a dollar estimate through a NEW
price knob, rendered as "janitor heartbeat: ~$N this week on quiet fires (WEIGHTED est.)". The report
today deals only in weighted tokens — no dollar conversion exists, so the price knob is net-new. The
$ figure MUST be labeled an ESTIMATE (weighting counts `cache_creation` at 1x though it bills ~2x,
and `cache_read` at 1/10) — it is a relative load index, not a bill.

### Deliverable 2 — the self-throttle actuator (`scripts/dispatch.py` + libs)

- `scripts/lib/token_meter.py` — NEW pure evaluator `evaluate_self_budget(records, *, budget,
  now, cap_frac, maintenance_frac, disarm_frac)` (sibling of the existing pure
  `evaluate_turn_budget` ≈L486 / `BudgetVerdict` ≈L474). It filters `heartbeat == True`, computes
  the rolling-7d weighted cost via `token_baseline.weighted_tokens` + `rolling_sum`, compares to
  `budget`, and returns an escalation verdict: `ok | slow | maintenance | disarm`. Pure, no I/O,
  fully unit-testable. Reuses `load_log` (≈L445) at the call site only.
- `scripts/lib/heartbeat_cadence.py` — add a pure cap so a crossed budget pins the committed tier
  to `SLOW` regardless of live signals: either a `cap_tier` helper or a `budget_cap: bool` argument
  threaded into `commit_tier`. `FAST/MID/SLOW` (≈L32-34) and `_TIER_RANK` are the vocabulary.
- `scripts/dispatch.py` — NEW fail-open `_phase_self_budget()` (sibling of `_phase_heartbeat_cost`
  ≈L1686). It reads THIS project's `token-meter.jsonl` heartbeat records, calls the pure evaluator,
  and threads the verdict into TWO existing consumers:
  - `_resolve_heartbeat_mode` (≈L596) — verdict `maintenance` → return `'maintenance'` (via the
    LOCAL `state.MAINTENANCE_FLAG`, honored by `_maintenance_mode_active()` which already OR-checks
    it); verdict `disarm` → return `'stop'` → `main()` emits the bare `[janitor-self-disarm]` marker
    and the session runs `/janitor-disarm`, deleting its own cron.
  - `_phase_cadence_tier` (≈L1841) — verdict `slow` → cap `committed` at `hc.SLOW`.
  - Placement MIRRORS `_phase_cadence_tier`: strictly AFTER all resume/compact early-returns
    (rate-limit ≈L1999, compact ≈L2008, clear ≈L2017, proactive-idle-compact ≈L2027) so a recovery
    fire is NEVER throttled or self-disarmed. Wired into `main()` at ≈L1957, before the maintenance
    early-return.
- Reversibility / anti-flap: the LOCAL `MAINTENANCE_FLAG` and the throttle must RELEASE when
  rolling cost falls back under budget, with hysteresis mirroring `commit_tier`'s `demote_fires` so
  a transient spike does not permanently pin a session cheap. Self-disarm is cleared the normal way
  (`/janitor-arm`).
- Knob parsing via `state.parse_nonneg_int` / `coerce_int`; enable-gate via `is_truthy_env`.

### New env knobs (all default GENEROUS; primary knob 0 = disabled, spec-mandated)

- `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET` — rolling-7d weighted-cost ceiling. Default generous;
  `0` disables the entire mechanism.
- Escalation fractions (cap-cadence / maintenance / disarm) — as fractions of the budget (e.g.
  0.6 / 0.85 / 1.0), OR three separate knobs. Default tiered so cadence-cap trips well before
  disarm.
- `CLAUDE_PLUGIN_OPTION_TOKEN_PRICE_PER_MTOK` (or similar) — weighted-token → $ conversion for the
  report's "$N this week" line. No sane universal default; when unset the report shows weighted
  tokens only (the $ line is opt-in).

### Reference-only boundary (do NOT edit for auto-throttle)

`scripts/global_control_cli.py` and `scripts/lib/global_state.py` — their maintenance/disarm/
kill-switch flags are MACHINE-WIDE. D2 must NOT use them: a per-project budget must never stop the
whole fleet. Named here only to mark the line the implementation must not cross.

## Interdependencies

Shared files/functions with the other three improvements from the 2026-07-23 janitor-shortcomings
critique (this session), and the required ordering:

- **D1 (daemon-owns-wake)** ↔ D2 — SHARED `scripts/dispatch.py` (resume/renew phases, mode
  resolution) + `scripts/lib/global_state.py` (daemon flags) + `scripts/lib/heartbeat_cadence.py`
  (cadence re-arm). CONFLICT AXIS: D2's auto self-disarm + auto-maintenance must not fight D1's
  wake/keepalive; both mutate the same cron/cadence path. ORDERING: land D1 FIRST if D1 changes the
  mode-resolution/wake contract, then D2 threads its verdict through the settled
  `_resolve_heartbeat_mode`. Coordinate the tier-cap + mode-escalation so a budget stop and a D1
  wake cannot oscillate (a disarmed-by-budget session must stay disarmed until `/janitor-arm`, not
  be re-woken by D1's keepalive).
- **D4 (harness self-test)** ↔ D2 — SHARED `scripts/lib/harness_backend.py`
  (`backend`/`server_is_alive`/`is_harness_session`) + `state.in_ai_maestro_agent_env` + dispatch
  mode resolution. In #J harness (thin) mode the daemon is not spawned and continuity is
  server-delegated — the self-budget throttle MUST detect harness and NOT auto-disarm, or it breaks
  server-owned continuity. ORDERING: D4's harness discriminator should be settled first; D2 gates
  auto-disarm/auto-maintenance behind `not is_harness_session()`.
- **D5 (shrink-protocol)** ↔ D2 — SHARED `scripts/dispatch.py` compact phases
  (`_phase_proactive_idle_compact` ≈L2027, `_phase_compact_resume` ≈L2008) +
  `scripts/lib/cold_cache_compact.py` + `scripts/lib/token_meter.py` (`resolve_context` /
  `latest_context_size`). Both read the same meter + context telemetry and both can trigger
  maintenance/compaction. D5 MUST STATE whether it merges into D1: **D5 is INDEPENDENT of D1** (it
  owns the compact/shrink path, D1 owns the wake path) but SHARES the `token_meter.py` pure layer
  with D2. ORDERING: define ONE ordering of auto-maintenance (D2) vs auto-compact (D5) on an idle
  session so they do not double-fire — self-budget maintenance is evaluated AFTER the proactive
  compact phase (both after the resume early-returns), so a compaction that lowers cost is seen
  before the budget decides.
- **SHARED PURE LAYER** — `scripts/lib/token_meter.py` (`evaluate_turn_budget` / `BudgetVerdict` /
  `load_log`) + `scripts/lib/token_baseline.py` (`weighted_tokens`, `rolling_sum`) are the common
  metering substrate for D2 (budget), D5 (context sizing), and the existing token-usage-anomaly
  detector. Any schema change to the `token-meter.jsonl` record shape (`as_record` ≈L53) ripples to
  ALL readers — D2 adds a READER only, it must not change the record schema.

## Verification

- **Pure evaluator** — `tests/test_token_meter.py`: `evaluate_self_budget` returns
  `ok/slow/maintenance/disarm` at the right thresholds; heartbeat filter drops interactive turns
  (a record with `heartbeat: false` never counts; missing `heartbeat` counts as True); a budget of
  0 always returns `ok` (disabled); a malformed/empty log returns `ok` (fail-open, no raise).
- **Weighting/windows** — `tests/test_token_baseline.py`: `weighted_tokens` + `rolling_sum` already
  covered; add the 7d-window boundary case the budget relies on.
- **Cadence cap** — `tests/test_heartbeat_cadence.py` + `tests/test_dispatch_cadence.py`: a
  budget-cap flag pins `committed == SLOW` even when live signals ask for FAST; cap is inert (not
  erroring) when `heartbeat_cadence_dynamic` is OFF — document this: with dynamic cadence disabled
  the SLOW-cap is a no-op, so the maintenance/disarm tiers are the only effective throttle then.
- **Phase ordering (survival latency)** — `tests/test_dispatch_phases.py`: PROVE `_phase_self_budget`
  runs strictly AFTER every resume/compact early-return. Assert that on a fire with
  `rate-limited.flag` / `resume-after-compact.flag` present, `main()` returns via the recovery path
  and `_phase_self_budget` is NEVER reached — so a recovery fire's cadence is unchanged and it is
  never disarmed. This is the direct proof that survival latency (rate-limit resume, post-compact
  resume, 7-day renew) is UNCHANGED by D2.
- **Maintenance escalation** — `tests/test_maintenance_token_monitoring.py` +
  `tests/test_daemon_maintenance_keepalive.py`: a crossed maintenance-tier budget writes the LOCAL
  `MAINTENANCE_FLAG` (never the global flag) and the fire falls to cheap survival-only behavior.
- **Boundary (no global writes)** — `tests/test_global_control.py`: assert D2's actuator path never
  calls `set_maintenance_mode` / `set_kill_switch` (per-project channeling invariant).
- **Report** — `tests/test_token_report_live.py`: the weekly heartbeat-$ line appears, is computed
  from `beats` only, and is labeled an estimate; absent price knob → weighted-token-only line.
- **Regression** — `tests/test_token_usage_anomaly_detector.py`: the sibling `token-meter.jsonl`
  consumer still parses unchanged (D2 adds no record fields).

## Notes and lessons learned

(none yet)
