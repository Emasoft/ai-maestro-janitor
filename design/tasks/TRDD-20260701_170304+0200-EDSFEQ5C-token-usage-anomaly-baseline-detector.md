---
trdd-id: EDSFEQ5C
title: Adaptive token-usage baseline + anomaly detector (5h/7d window awareness)
column: complete
created: 2026-07-01T17:03:04+0200
updated: 2026-07-01T17:22:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: MEDIUM
effort: L
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

# Adaptive token-usage baseline + anomaly detector (5h/7d window awareness)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-01

- **USER DIRECTIVE (verbatim):** "estimate the average amount of tokens used in the 5h and 7d
  windows, and log when the window is exhausted before the time … reveal the maximum amount of
  tokens for opus 4.8 allowed in a 5h/7d window … compute the average per minute … baseline to
  launch an alert when the usage per minute is above the baseline. maybe an estimate on 5 minutes
  interval … usage is often intermittent and concentrated at the moment new agents are spawned. the
  anomalies detector must be smart … examine the token usage log to track normal behaviour and
  identify patterns to distinguish sudden anomalous behaviour."
- **DATA EXAMINED (this session's `token-meter.jsonl`, 11.1 days, 1559 records — a "weighted" proxy
  = output + input + cache_creation + cache_read//10):**
  - Per-5-min bucket: **median 70k, p90 219k, p95 688k, p99 2.17M, max 4.77M** — HEAVY-TAILED.
  - **BURSTY: top 1% of buckets hold 19% of tokens; top 10% hold 61%** — matches "concentrated at
    agent spawns". ⇒ mean+stddev is useless; the baseline MUST be robust (median + MAD / percentiles).
  - Rolling: **last 5h = 8.06M weighted (~26.9k/min); last 7d = 152.3M weighted (~15.1k/min).**
  - median+K·MAD flags: K=3→15.5%, K=5→10.3%, K=10→8.0%; p95→5%, p99→1% of buckets. A conservative
    detector uses a HIGH bar (robust-z ≥ ~6 AND above p95-ish floor) so normal bursts don't false-alarm.
- **WINDOW LIMITS — the authoritative source is the OAuth usage endpoint** (`/api/oauth/usage`,
  already polled by the rotator): it returns `five_hour` / `seven_day` **`utilization` as a PERCENT
  (0-100)**, NOT absolute tokens (`rotator._util(data, window)`). So the absolute Opus-4.8 cap is
  ESTIMATED by pairing a utilization% sample with the window's weighted-token sum
  (`cap ≈ weighted / (util/100)`); the % itself is the true window-fullness for pace alerts. The
  endpoint is rotator-opt-in, so the detector must WORK without it (statistical anomaly on the log)
  and ENRICH with it when present (absolute cap + pace).
- **DESIGN (build):**
  - Pure `scripts/lib/token_baseline.py`: `weighted_tokens(rec)`; `bucketize(records, bucket_s)`;
    `robust_baseline(values) -> (median, mad)`; `anomaly_score(v, median, mad)` (robust z, 0 when
    mad=0); `classify_recent(records, *, bucket_s, k, floor, now)` → verdict (is_anomaly, score,
    current, median, mad); `rolling_sum(records, window_s, now)`; `per_minute(sum, window_s)`;
    `estimate_window_cap(util_pct, window_weighted)`; `project_exhaustion(util_pct, window_s,
    recent_rate_per_s)`. All pure → unit-tested against the real distribution shape above.
  - Detector `scripts/detectors/token-usage-anomaly.py` (heartbeat, DEFAULT-ON, conservative):
    reads the log, classifies the most-recent COMPLETE 5-min bucket vs the trailing baseline, emits
    ONE drift line on a genuine anomaly (robust-z ≥ K AND above the floor), deduped. Bounded/cheap
    (a few ms over 1559 records). Config `CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_*`
    (ENABLED, BUCKET_SECONDS=300, Z=6, FLOOR_PCT=95). This is the SLOW pattern signal — the
    complementary FAST per-turn spike signal is the PreToolUse guard (TRDD-KI24GR5Z).
  - Extend `/janitor-token-report`: add the rolling 5h/7d weighted sums + per-min rate + the robust
    baseline (median/p95/p99) + recent anomaly buckets; when a utilization% is supplied, show the
    estimated absolute cap + pace-to-exhaustion.
- **"log when the window is exhausted before the time":** the rotator already records rate-limit
  events; the report/detector correlate a 5h/7d exhaustion (utilization→100 before reset, or the
  `rate-limited.flag`) with the window's weighted sum to log the EMPIRICAL cap. v1 provides the pure
  `estimate_window_cap`; wiring the live OAuth utilization poll is the rotator-opt-in enrich step.
- **SHIPPED (this session, all tested):** `scripts/lib/token_baseline.py` (weighted_tokens,
  bucketize, robust_baseline, anomaly_score, percentile, `classify_recent` with the
  `max(p99-floor, robust-z band, median×ratio)` threshold — the ratio term FIXED a real gap
  where a huge spike in a perfectly-FLAT/MAD=0 history scored z=0 and slipped through —
  rolling_sum, max_window_sum, per_minute, estimate_window_cap, project_exhaustion_minutes).
  Heartbeat detector `scripts/detectors/token-usage-anomaly.py` (default-on, per-bucket dedupe,
  registered in `dispatch.py` at 300s cadence, config `…TOKEN_ANOMALY_{ENABLED,BUCKET_SECONDS,Z,
  FLOOR_PCT}`). `/janitor-token-report` extended: rolling 5h/7d weighted + per-min + busiest-window
  (cap lower bound) + baseline; `--util5h/--util7d` → estimated absolute cap + pace. 58 tests
  (26 lib + 6 detector-e2e + the report smoke); full suite 11,799 green; ruff+pyright clean.
- **DATA the report surfaced (this session's log):** busiest 5h ever = 20.2M weighted, busiest 7d
  = 152.3M weighted — the empirical LOWER BOUNDS on the Opus-4.8 caps (exact cap needs the live
  utilization% pairing, which `--util5h/--util7d` does).
- **NEXT ACTION:** none — shipped. Ships with the v0.26.0 batch (task #250, gated on CPV#154). The
  cross-session GLOBAL 5h/7d monitor (account-wide via the OAuth endpoint, in the rotator/daemon)
  reusing this lib is the deferred follow-up (TRDD-ME8V2YJF territory).

## Why

The per-turn guard (KI24GR5Z) catches an in-flight spike; it does NOT learn what "normal" is or
know the 5h/7d window budget. The user wants an ADAPTIVE baseline (from the real, bursty,
heavy-tailed log) that distinguishes a normal agent-spawn burst from a SUDDEN anomaly, plus
awareness of the subscription window so it can warn before the window exhausts early. The data
proves the baseline must be robust (median/MAD), not mean-based.

## Acceptance

- `token_baseline` computes a robust baseline + a robust-z anomaly score; `classify_recent` flags a
  genuine outlier and NOT a normal burst (tested against the measured distribution shape).
- Rolling 5h/7d weighted sums + per-min rate are computed; `estimate_window_cap(util%, weighted)`
  returns a sane cap; `project_exhaustion` returns minutes-to-exhaust at the current rate.
- The heartbeat detector is DEFAULT-ON, conservative (few false alarms), deduped, cheap, disable-able.
- `/janitor-token-report` shows the window sums, rates, baseline, and recent anomalies.
- Real unit tests for every pure fn (incl. the heavy-tailed/bursty edge: a normal burst is NOT an
  anomaly, a true outlier IS). ruff + pyright clean.

## Notes and lessons learned
