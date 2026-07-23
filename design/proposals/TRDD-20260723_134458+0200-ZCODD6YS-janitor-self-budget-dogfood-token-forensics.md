---
trdd-id: ZCODD6YS
title: The janitor meters its OWN heartbeat cost and self-throttles against a user budget
column: proposal
created: 2026-07-23T13:44:58+0200
updated: 2026-07-23T14:07:30+0200
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
  1. REPORT (ship-ready, ISOLATED — land first, in parallel with D4/D1) — a heartbeat-only weekly
     rollup ("$N this week on quiet fires") in `/janitor-token-report`.
  2. THROTTLE — a fail-open self-budget check in `dispatch.py` that, when the janitor's OWN rolling
     7-day heartbeat cost crosses a new generous `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET`
     (0 = disabled), escalates a two-tier throttle: cap cadence at the SLOW floor → auto-enter LOCAL
     maintenance. **MAINTENANCE IS THE CEILING — the automatic self-budget NEVER emits
     `[janitor-self-disarm]`.** Maintenance already gives ≈0.1x cost WITH the survival cron + resume
     preserved; disarm would delete the cron and need a manual `/janitor-arm`, so it is not a safe
     automatic action.
- KEY FACT: EVERY actuator, telemetry sink, and per-project channel already exists. D2 only wires
  the EXISTING meter's output (`token-meter.jsonl`) back into the EXISTING throttle inputs
  (the LOCAL `state.MAINTENANCE_FLAG` honored by `_maintenance_mode_active`, and `_phase_cadence_tier`).
  VERIFIED against the tree 2026-07-23: no budget mechanism exists; the closest sibling
  `_phase_heartbeat_cost()` (janitor#78, dispatch.py L1686) only LOGS an external cost CLI's output —
  it never throttles.
- NEXT ACTION: on approval → `git mv` to `design/tasks/`, set `column: planned`, then implement per
  "## The fix" file-by-file. Start with the PURE evaluator in `token_meter.py` + its unit tests,
  because every actuator consumes its verdict. Deliverable 1 (report) is independent and may land
  first.
- LOAD-BEARING GOTCHAS (do NOT carry a wrong version forward):
  - **THE CARDINAL RULE.** ALL actuation lives in ONE new late phase `_phase_self_budget()`, wired
    into `main()` strictly AFTER every resume/compact early-return (rate-limit L1999, compact L2008,
    clear L2017, proactive-idle-compact L2027) and BEFORE `_phase_cadence_tier` (L2057) /
    the maintenance early-return (L2069). It is placed right after `_phase_heartbeat_cost` (L2048).
    A recovery fire returns at one of L1999–L2028 and NEVER reaches the phase, so a rate-limited /
    post-compact / post-clear session can never be throttled or (were disarm ever added) disarmed.
  - **NEVER route ANY verdict through `_resolve_heartbeat_mode` (Phase 0, L1974).** `mode=='stop'`
    returns at L1980 BEFORE the resume phases — routing a throttle there would delete the survival
    cron on a rate-limited/post-compact session = silent overnight death. The prior draft's
    disarm-via-`_resolve_heartbeat_mode` design shipped exactly that bug; it is DELETED.
  - **Auto-disarm is REMOVED entirely.** The evaluator tops out at `maintenance`; `_phase_self_budget`
    never prints `[janitor-self-disarm]`. This is enforced by a test asserting the marker is never
    emitted by the self-budget path under any budget verdict.
  - **Suppress the whole throttle on any actively-waiting session.** Reuse the cadence
    `_cadence_active_waiting(sd, now)` signal (recent resume stamp <30 min, pending directive,
    pending EXTERNAL agents, keep-going). When it is True: no cap, no flag write, AND clear any
    budget-imposed flag/cap. The fire that ACTUALLY resumes returned early (above); the fire AFTER it
    reaches this phase, and the resume stamp protects it there.
  - **Gate behind `not harness_backend.is_harness_session(os.environ)`.** In #J thin harness mode the
    daemon is not spawned and continuity is server-delegated (D4); an auto-maintenance there would
    break server-owned continuity.
  - `token-meter.jsonl` logs BOTH heartbeat AND interactive turns (since TRDD-DLI76AUC #4). The
    budget MUST filter `heartbeat == True` (missing key → True, per `beats` at token_report.py L491).
    Summing user turns would silence the janitor during the user's own expensive work — the exact
    backwards mistake logged twice before.
  - Actuate ONLY the LOCAL `state.MAINTENANCE_FLAG` (= `"maintenance-mode"`, state.py L40) + the
    local cadence cap. NEVER `global_state` maintenance/kill-switch — a per-project budget must never
    stop the fleet (TRDD-X92VBFNF per-project channeling invariant).
  - **Fail-open is NORMATIVE (body, not just here):** wrap the whole phase in try/except; ANY metering
    exception degrades to "no throttle" (mode unchanged, cap False), never raises. A metering bug
    breaking survival is the cardinal sin.
- SUPERSEDED — do NOT carry forward:
  - The `disarm` escalation tier and `disarm_frac` knob (prior draft). Auto self-disarm is removed;
    the ceiling is MAINTENANCE.
  - "verdict `disarm` → `_resolve_heartbeat_mode` returns `'stop'`" (prior draft, "## The fix"
    Deliverable 2). Deleted — that is the silent-death path.
- DURABLE ARTIFACTS to read before acting: `scripts/lib/token_meter.py` (`load_log` L445,
  `evaluate_turn_budget` L486, `BudgetVerdict` L474), `scripts/dispatch.py` (`main` L1957,
  `_resolve_heartbeat_mode` L596, resume early-returns L1999/L2008/L2017/L2027, `_phase_heartbeat_cost`
  L1686, `_phase_cadence_tier` L1841, maintenance early-return L2069, `_maintenance_mode_active` L577,
  `_cadence_active_waiting` L1786), `scripts/lib/heartbeat_cadence.py` (`FAST/MID/SLOW` L32-34,
  `_TIER_RANK` L35, `commit_tier` L126), `scripts/lib/harness_backend.py`
  (`is_harness_session` L75), `scripts/token_report.py` (`beats` L491), `scripts/lib/token_baseline.py`
  (`weighted_tokens` L29, `rolling_sum` L148).

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

The escalation ladder has exactly TWO rungs above `ok`: `slow` (cap the cadence at the SLOW floor)
and `maintenance` (drop the session to the cheap keep-warm path). **There is NO `disarm` rung** —
maintenance already yields ≈0.1x cost while KEEPING the cron and the resume path alive, whereas
disarm deletes the cron and needs a manual `/janitor-arm`, so deleting a survival cron is never a
safe automatic reaction to cost. This removes the entire "lost survival marker" failure class from
D2's actuator.

- `scripts/lib/token_meter.py` — NEW pure evaluator
  `evaluate_self_budget(records, *, budget, now, cap_frac, maintenance_frac, release_frac,
  in_maintenance)` (sibling of the existing pure `evaluate_turn_budget` L486 / `BudgetVerdict` L474).
  It filters `heartbeat == True` (a record missing the `heartbeat` key counts as True — same rule as
  `beats` at token_report.py L491), computes the rolling-7d weighted cost via
  `token_baseline.weighted_tokens` (L29) + `rolling_sum` (L148, `window_s = 7*86400`), and returns
  an escalation verdict from `{ok, slow, maintenance}` (never `disarm`). Thresholds are fractions of
  `budget`: `cost ≥ maintenance_frac·budget → maintenance`; `cost ≥ cap_frac·budget → slow`; else
  `ok`. `budget == 0 → ok` (disabled). An empty/garbage record list → `ok`. Pure, no I/O, fully
  unit-testable. Reuses `load_log` (L445) at the call site only.
  - **Hysteresis (stateless Schmitt trigger, no new persisted file).** `in_maintenance` is the
    CURRENT flag state (does `state.MAINTENANCE_FLAG` exist for this project?). When already in
    maintenance, the verdict stays `maintenance` until cost falls BELOW the lower `release_frac·budget`
    band (`release_frac < cap_frac`), then returns `ok`. This dead-band is the analogue of
    `commit_tier`'s `demote_fires` (heartbeat_cadence.py L126): it prevents flag flap when cost
    hovers at the trip point. It also self-corrects: once in maintenance the fires are cheap
    (`cache_read // 10`, weighted at 1/10), so the rolling-7d cost naturally decays below the release
    band over days and the session returns to full monitoring — a slow bang-bang controller that
    holds the janitor's own weekly cost near the budget.
- `scripts/lib/heartbeat_cadence.py` — add a pure `cap_tier(state, ceiling)` helper (respecting
  `_TIER_RANK` L35) that returns `state` with `committed_tier` clamped to at most `ceiling`. `FAST/MID/
  SLOW` (L32-34) are the vocabulary. Threaded into `_phase_cadence_tier` via a new
  `budget_cap_slow: bool` parameter; when True, `committed = hc.cap_tier(committed, hc.SLOW)` right
  after `commit_tier` (L1904), before `tier_to_cron`.
- `scripts/dispatch.py` — NEW fail-open `_phase_self_budget() -> bool` (sibling of
  `_phase_heartbeat_cost` L1686). Returns `budget_cap_slow` (whether to clamp the cron to SLOW this
  fire) and, as a side effect, WRITES or CLEARS the LOCAL `state.MAINTENANCE_FLAG`. Whole body wrapped
  in try/except → on ANY exception returns `False` and touches nothing (fail-open, NORMATIVE).
  Sequence inside the phase:
  1. Enable gate: `is_truthy` self-budget knob present AND non-zero → else return `False` (mechanism
     off; also clear a stale flag it owns).
  2. **Harness gate:** `harness_backend.is_harness_session(os.environ)` True → return `False`, no
     actuation (server-delegated continuity, D4).
  3. **Actively-waiting suppression:** `_cadence_active_waiting(sd, now)` True (recent resume stamp,
     pending directive, pending external agents, keep-going) → CLEAR any budget-owned
     `MAINTENANCE_FLAG` and return `False`. A working/resuming session is never throttled.
  4. Read THIS project's `token-meter.jsonl` heartbeat records (`load_log` → filter), read the
     current flag state (`in_maintenance`), call `evaluate_self_budget`.
  5. Verdict `maintenance` → write the LOCAL `state.MAINTENANCE_FLAG` (atomic); return `True`
     (also cap the cron to SLOW). Verdict `slow` → clear the flag (in case it was set), return `True`.
     Verdict `ok` → clear the flag, return `False`.
  - **The flag is the ONLY maintenance actuator, and it takes effect on the NEXT fire's Phase-0
    resolution** — `_resolve_heartbeat_mode` (L596) → `_maintenance_mode_active` (L577) OR-checks the
    local flag (L591). The CURRENT fire's `mode` was already resolved at L1974 and is NOT mutated, so
    the self-budget phase never reorders the current fire's survival logic. On the first
    over-budget fire the session finishes one normal fire, then every subsequent fire resolves
    `maintenance` at Phase 0 (cheap). The self-budget phase still runs on maintenance fires (it sits
    at L2048, before the maintenance early-return at L2069), so it is also the RELEASE point: a
    maintenance fire whose rolling cost has decayed below `release_frac·budget` clears the flag and
    the next fire resolves `full`.
  - **Placement in `main()`:** immediately after `_phase_heartbeat_cost()` (L2048) and before
    `_phase_cadence_tier()` (L2057) — i.e. strictly AFTER all four resume/compact early-returns
    (L1999/L2008/L2017/L2027) and before the maintenance early-return (L2069). Its return value is
    passed as `_phase_cadence_tier(budget_cap_slow=...)`. Wrapped at the call site behind
    `try/except` as a second fail-open layer.
- **NO write to `_resolve_heartbeat_mode` and NO `[janitor-self-disarm]` emission** anywhere in the
  self-budget path — the two are explicitly out of scope, and the survival-test (Verification below)
  asserts the marker is never produced by this path.
- Knob parsing via `state.parse_nonneg_int` / `coerce_int`; enable-gate via `is_truthy_env`;
  fractions via a small float parser (fail-open to the default on a bad value).

### New env knobs (all default GENEROUS; primary knob 0 = disabled, spec-mandated)

- `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET` — rolling-7d weighted-cost ceiling. Default generous;
  `0` disables the entire mechanism.
- `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET_CAP_FRAC` (default ≈0.6) — cadence-cap trip fraction.
- `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET_MAINTENANCE_FRAC` (default ≈0.9) — maintenance trip
  fraction. Ordered `release_frac < cap_frac < maintenance_frac < 1.0` so cadence-cap always trips
  before maintenance and the dead-band sits below the cap.
- `CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET_RELEASE_FRAC` (default ≈0.4) — the lower dead-band; the
  flag clears only when cost falls below this fraction of the budget (anti-flap hysteresis).
- (No disarm fraction — the ceiling is maintenance.)
- `CLAUDE_PLUGIN_OPTION_TOKEN_PRICE_PER_MTOK` (or similar) — weighted-token → $ conversion for the
  report's "$N this week" line. No sane universal default; when unset the report shows weighted
  tokens only (the $ line is opt-in).

### Reference-only boundary (do NOT edit for auto-throttle)

`scripts/global_control_cli.py` and `scripts/lib/global_state.py` — their maintenance/disarm/
kill-switch flags are MACHINE-WIDE. D2 must NOT use them: a per-project budget must never stop the
whole fleet. Named here only to mark the line the implementation must not cross. In particular the
self-budget path must never call `global_state.set_maintenance_mode` / `set_kill_switch` (asserted
in Verification).

## Interdependencies

Shared files/functions with the other three improvements from the 2026-07-23 janitor-shortcomings
critique (this session), and the required ordering:

- **D1 (daemon-owns-wake)** ↔ D2 — SHARED `scripts/dispatch.py` (resume/renew phases, mode
  resolution) + `scripts/lib/heartbeat_cadence.py` (cadence re-arm). CONFLICT AXIS: D2's
  auto-maintenance must not fight D1's wake/keepalive; both mutate the same cron/cadence path. Since
  D2 now caps at MAINTENANCE (the cron survives — no auto-disarm), the "disarmed session re-woken by
  keepalive" oscillation is gone by construction; the residual coupling is only that a
  budget-maintenance session and a D1 keepalive must agree the session stays cheap-but-alive.
  ORDERING: land D1 FIRST if D1 changes the mode-resolution/wake contract, then D2 threads its
  verdict through the settled `_resolve_heartbeat_mode` (read-only — D2 never WRITES that resolver;
  it writes the LOCAL flag the resolver reads) and the settled `_phase_cadence_tier`. D2 must also
  RE-BASELINE its default budget after D1 moves detectors off-turn (else it baselines against
  soon-to-vanish quiet-fire cost).
- **D4 (harness self-test)** ↔ D2 — SHARED `scripts/lib/harness_backend.py`
  (`backend`/`server_is_alive`/`is_harness_session` L75) + `state.in_ai_maestro_agent_env` + dispatch
  mode resolution. In #J harness (thin) mode the daemon is not spawned and continuity is
  server-delegated — the self-budget throttle MUST detect harness and NOT auto-maintenance, or it
  breaks server-owned continuity. ORDERING: D4's harness discriminator should be settled first; D2
  gates ALL actuation behind `not is_harness_session()`.
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

- **Pure evaluator** — `tests/test_token_meter.py`: `evaluate_self_budget` returns `ok/slow/maintenance`
  (and NEVER any `disarm` value — that verdict does not exist) at the right fraction thresholds;
  heartbeat filter drops interactive turns (a record with `heartbeat: false` never counts; missing
  `heartbeat` counts as True); a budget of 0 always returns `ok` (disabled); a malformed/empty log
  returns `ok` (fail-open, no raise); the `in_maintenance` dead-band holds `maintenance` until cost
  falls below `release_frac·budget`, then returns `ok` (Schmitt-trigger release).
- **Weighting/windows** — `tests/test_token_baseline.py`: `weighted_tokens` + `rolling_sum` already
  covered; add the 7d-window boundary case the budget relies on.
- **Cadence cap** — `tests/test_heartbeat_cadence.py` + `tests/test_dispatch_cadence.py`: the new
  pure `cap_tier(state, SLOW)` clamps `committed_tier` to SLOW and is a no-op on an already-SLOW
  state; threading `budget_cap_slow=True` into `_phase_cadence_tier` pins `committed == SLOW` even
  when live signals ask for FAST; the cap is inert (not erroring) when `heartbeat_cadence_dynamic` is
  OFF — document this: with dynamic cadence disabled the SLOW-cap is a no-op, so the maintenance tier
  is the only effective throttle then.
- **THE CARDINAL SURVIVAL TEST (combined resume + budget)** — `tests/test_dispatch_phases.py`:
  a session that is BOTH budget-maintenance-eligible (a `token-meter.jsonl` whose 7d heartbeat cost
  is over `maintenance_frac·budget`) AND simultaneously rate-limited (`rate-limited.flag` present) OR
  post-compacted (`resume-after-compact.flag` present) MUST still emit `[janitor-resume]` on that
  fire and MUST NEVER emit `[janitor-self-disarm]`, and its cron/cadence is unchanged. Assert `main()`
  returns via the recovery early-return (L1999 / L2008) and `_phase_self_budget` is NEVER reached on
  that fire (spy/monkeypatch the phase to record if called). This is the direct proof that a recovery
  fire is untouched by D2 — and it is a STRONGER test than a bare phase-ordering assertion, because it
  binds the two conditions that the prior Phase-0 wiring conflated.
- **Never-disarm invariant** — `tests/test_dispatch_phases.py`: drive `_phase_self_budget` /`main()`
  through EVERY budget verdict (ok/slow/maintenance) on a non-recovery fire and assert `[janitor-self-
  disarm]` is NEVER printed by the self-budget path. (The only legitimate emitter of that marker
  remains the Phase-0 global-stop branch at L1980, untouched by D2.)
- **Maintenance escalation + hysteresis-release** — `tests/test_maintenance_token_monitoring.py`:
  a crossed maintenance-tier budget writes the LOCAL `MAINTENANCE_FLAG` (never the global flag) so the
  NEXT fire's `_resolve_heartbeat_mode` returns `'maintenance'` and falls to cheap survival-only
  behavior; then, when the rolling cost decays below `release_frac·budget`, a subsequent
  (maintenance-mode) fire CLEARS the flag and the following fire resolves `full` again — proving the
  flag and the cadence cap RELEASE, not pin the session cheap forever.
- **Actively-waiting suppression** — `tests/test_dispatch_phases.py`: with `_cadence_active_waiting`
  True (a fresh `last-resume.ts` stamp, a non-empty `resume-directive.txt`, or the `keep-going` flag),
  an over-budget session is NOT throttled — no cap, and any pre-existing budget `MAINTENANCE_FLAG` is
  cleared.
- **Harness gate** — `tests/test_dispatch_phases.py`: with `is_harness_session` True, an over-budget
  session produces no actuation (no flag write, `budget_cap_slow` False).
- **Fail-open (NORMATIVE)** — `tests/test_dispatch_phases.py`: an `evaluate_self_budget` /`load_log`
  that raises leaves `main()` unaffected — the phase returns `False`, nothing is thrown, the fire
  completes. Mirrors the try/except contract stated in "## The fix".
- **Boundary (no global writes)** — `tests/test_global_control.py`: assert D2's actuator path never
  calls `set_maintenance_mode` / `set_kill_switch` (per-project channeling invariant).
- **Report** — `tests/test_token_report_live.py`: the weekly heartbeat-$ line appears, is computed
  from `beats` only, and is labeled an estimate; absent price knob → weighted-token-only line.
- **Regression** — `tests/test_token_usage_anomaly_detector.py`: the sibling `token-meter.jsonl`
  consumer still parses unchanged (D2 adds no record fields).

## Notes and lessons learned

[^1]: [id:ATOM-ZC0D-D6YS, status:valid, keywords:"self_budget_disarm survival_marker_lost early_return_recovery_fire late_phase_actuation", ocd:2026-07-23, lmd:2026-07-23]
  DO NOT actuate a cost throttle (or any escalation) via `_resolve_heartbeat_mode` (dispatch.py
  Phase 0, L1974), and DO NOT let an automatic budget ever emit `[janitor-self-disarm]`, BECAUSE
  `mode=='stop'` returns at L1980 BEFORE the resume/compact early-returns — so a rate-limited or
  post-compact session would have its survival cron deleted = silent overnight death. DO actuate
  ONLY from a LATE `_phase_self_budget` placed strictly after every resume/compact early-return
  (L1999/L2008/L2017/L2027), cap the ceiling at LOCAL maintenance (cron + resume preserved, ≈0.1x
  cost), and prove it with a combined resume+budget test.
