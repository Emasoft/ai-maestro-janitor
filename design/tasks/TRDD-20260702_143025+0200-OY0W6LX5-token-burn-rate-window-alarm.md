---
trdd-id: OY0W6LX5
title: Window burn-rate alarm — warn when 5h/7d usage outpaces its linear budget (early-exhaustion)
column: proposal
created: 2026-07-02T14:30:25+0200
updated: 2026-07-02T14:30:25+0200
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
implementation-commits: []
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

## Existing machinery to REUSE (don't rebuild)
- `token_baseline.estimate_window_cap` (util%+spent → cap), `rolling_sum`, `bucketize`,
  `max_window_sum`, `project_exhaustion_minutes` — extend, don't duplicate.
- `rotator.usage_request`/`account_usage` — the read-only usage probe (OAuth READ-ONLY: no
  rotation, no mutation).
- `window-exhaustion.jsonl` (only 5 events) — keep as a corroborating cap-lower-bound source.

## Open confirmations (build-time)
- Exact `/api/oauth/usage` payload shape (does it return the reset/boundary + both windows?).
- Are the 5h/7d windows rolling or fixed-reset? (User treats 7d as a fixed Jul 1→8 weekly.)

## Approval
Tier-3 (touches the OAuth read path + a new fleet-wide heartbeat alarm). Proposal — awaiting
USER go-ahead before implementation.

## Approval log
