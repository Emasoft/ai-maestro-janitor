---
trdd-id: OY0W6LX5
title: Fleet token attribution + window burn-rate alarm — which project over-consumes, and where the spike came from
column: complete
created: 2026-07-02T14:30:25+0200
updated: 2026-07-02T15:36:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: L
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: [a4d2ff7, 391f1aa]
approval-tier: 3
---

# Window burn-rate alarm — warn when 5h/7d usage outpaces its linear budget

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **WHY (user, 2026-07-02, verbatim example):** the 7d window (Jul 1→8) was at **46%
  on day 2/7**, when linear-to-reset would be ~28.6% → **~1.6× pace**; at that rate it
  exhausts ~day 4.3 (≈ Jul 5), i.e. **rate-limited ~2.6 days before the reset**. The user
  wants the janitor to ALARM on this. Reporting raw usage is NOT enough (CC already records
  per-turn usage in the jsonl as metadata — 22.5k records/transcript — but the model can't
  self-know its baseline; only the janitor can).
- **THE METRIC (refined, supersedes "N× historical per-turn average"):**
  `burn_ratio = utilization% / (100 × elapsed_fraction_of_window)`, per window (5h + 7d).
  `elapsed_fraction = (now − window_start) / window_duration`.
  ALARM when `burn_ratio ≥ RATIO` (default 1.5). Also report
  `projected_exhaustion = window_start + window_duration × (elapsed_fraction / util_fraction)`
  and the lead time before reset. The absolute token cap is OPTIONAL — util% already
  normalizes it.
- **DATA SOURCE (primary, already exists, READ-ONLY):** live 5h/7d **utilization% + reset
  boundary** from `/api/oauth/usage`, already fetched by the oauth-rotator
  (`rotator.usage_request` / `account_usage` / `cmd_usage`). Confirm at build time whether the
  payload carries the window reset/boundary; if not, derive `window_start` from the known 5h
  rolling + weekly-reset schedule.
- **DATA SOURCE (fallback):** `token_history.py` mines ALL `~/.claude/projects/*/*.jsonl`
  (per-ACCOUNT, cross-project — NOT just this repo) → unified `(ts, weighted_tokens)` series
  → busiest 5h/7d windows = cap lower bounds; windows that exhausted early tighten the cap.
  Used to express absolute tokens and when the API util% is unavailable. History available:
  ~71 days / 247 MB → ample.
- **THE CORE PROBLEM IS ATTRIBUTION (user, 2026-07-02):** the account util% is AGGREGATE
  across all projects on a subscription — it can't say WHO. The user runs ~10 projects in
  parallel on 2 Pro Max subs; when aggregate usage spikes, they need "which of the 10 is
  consuming above its norm, and where did the spike come from" so the janitor can advise THAT
  claude to cut back. So attribution is the PRIMARY deliverable; the burn-rate alarm is only
  the TRIGGER to look. Enablers already exist: (a) each project's transcripts carry per-turn
  usage → per-project rolling 5h/7d sums + each project's rate-vs-its-own-baseline;
  (b) `fleet_scan.gather_fleet` already enumerates every running claude + its project root;
  (c) `fleet_inject`/`terminal_trigger` already deliver a targeted message to a specific
  session's pane. Attribution = a daemon-owned cross-project scan (the daemon is the machine-
  wide singleton that already fleet-scans), NOT new plumbing.
- **NEXT ACTION:** (1) confirm `/api/oauth/usage` fields (read-only probe). (2) Build the
  pure burn-rate math (`token_baseline`: `burn_ratio`, `projected_exhaustion`, `combine 5h+7d`)
  + tests — reproduce the user's example exactly. (3) `token_history.py` fallback miner. (4)
  Wire an alarm: heartbeat `token-usage-anomaly` (or a new `window-burn-rate` detector) +
  surface in `/janitor-token-report`. (5) TDD throughout; ruff+mypy; publish.

## Design

- **`token_baseline.py` (pure, testable):**
  - `burn_ratio(util_pct, elapsed_fraction) -> float` — `util/(100*elapsed)`; elapsed≈0 → inf-guard.
  - `projected_exhaustion(window_start, window_s, util_fraction, elapsed_fraction) -> epoch|None`.
  - `combine_windows([(label,burn,lead),…])` — report the WORST (soonest exhaustion); keep both
    when non-conflicting; note when 5h vs 7d disagree.
- **`token_history.py` (new script, cross-project miner, fallback):** walk every project's
  transcripts, sum `weighted = output+input+cache_creation+cache_read/10` per turn with its ts,
  compute busiest rolling 5h/7d sums (cap≥) + early-exhaustion detection. Persist estimated
  caps+rates to `${CLAUDE_PLUGIN_DATA}` (cross-project, survives updates).
- **Alarm:** heartbeat-cadenced (auto-fetch util% via the rotator's read path) → emit a drift
  line when `burn_ratio ≥ RATIO` for either window: `⚠ 7d window 46% at 2/7 elapsed — 1.6×
  linear pace; exhausts ~Jul 5 (2.6d early).` Env: `…WINDOW_BURN_RATIO` (1.5),
  `…WINDOW_BURN_MIN_UTIL` (a floor so a barely-used window doesn't alarm), enable flag.
- **Report:** `/janitor-token-report` gains a per-window burn-rate block (util%, elapsed%,
  ratio, projected exhaustion, lead-before-reset).

### Attribution (the CORE — daemon-owned, cross-project)
- **Per-project consumption scan:** for each ACTIVE project (from `fleet_scan.gather_fleet`),
  walk its newest transcript(s) under `~/.claude/projects/<slug>/` → rolling 5h + 7d weighted
  tokens, its share of the fleet total, and its recent rate vs its OWN trailing baseline
  (median) = the per-project spike factor. Persist to `${CLAUDE_PLUGIN_DATA}` so ranking is
  cross-project and survives updates.
- **Culprit ID:** when the aggregate burn-rate trips, rank projects by absolute recent
  consumption AND by spike-vs-own-baseline; the culprit = large AND above its own norm.
- **Spike source (within the culprit):** break the culprit's recent turns into output vs
  cache_creation (context bloat, re-read every turn) vs Task/subagent spawns vs tool_calls +
  the timestamp the rate stepped up → "where the spike came from".
- **Targeted advisory:** the daemon surfaces to the CULPRIT's own session via
  `fleet_inject`/`terminal_trigger` — "you're the top consumer, N× your baseline; aggregate 7d
  46%/1.6× pace — compact / stop idle subagents / throttle". Plus a fleet dashboard
  `/janitor-token-attribution` (and fold into `/janitor-show-global-status`) ranking all
  projects, runnable anywhere.
- **Bounded/safe:** read-only scans; advisory only (never kills a session); opt-in +
  min-floor so a quiet fleet never nags; honors the global kill-switch.

## Existing machinery to REUSE (don't rebuild)
- `token_baseline.estimate_window_cap` (util%+spent → cap), `rolling_sum`, `bucketize`,
  `max_window_sum`, `project_exhaustion_minutes` — extend, don't duplicate.
- `rotator.usage_request`/`account_usage` — the read-only usage probe (OAuth READ-ONLY: no
  rotation, no mutation).
- `window-exhaustion.jsonl` (only 5 events) — keep as a corroborating cap-lower-bound source.

## CONFIRMED (probe 2026-07-02T14:41, read-only, http 200)
- Payload: `five_hour.{utilization, resets_at}` + `seven_day.{utilization, resets_at}` (ISO
  UTC) + a `limits[]` array (`kind: session|weekly_all|weekly_scoped`, `percent`, `severity:
  normal|critical`, `resets_at`, `is_active`). `*_dollars` all None on this plan.
- Both windows are FIXED-reset (resets_at given) → `elapsed_fraction = 1 − (resets_at − now)/window_s`.
- Live validation: seven_day 48% with reset Jul 7 08:00Z → start Jun 30 08:00Z → elapsed
  31.4% → **burn_ratio 1.53×** (matches the user's ~1.6× estimate). five_hour was 100%
  (severity critical) at probe time — the alarm class is real.

## Approval log
- 2026-07-02T14:41:58+0200 — APPROVED by USER (tier 3). Verbatim: "go". Build + publish authorized.
