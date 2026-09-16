---
trdd-id: 0NRVNDSZ
title: Window-aligned attribution — bounds from resets_at, not trailing intervals
column: published
created: 2026-07-02T16:20:52+0200
updated: 2026-07-02T17:16:00+0200
current-owner: janitor-session
assignee: janitor-session
priority: 1
severity: MEDIUM
effort: S
labels: [tokens, attribution, observability]
task-type: feature
parent-trdd: TRDD-OY0W6LX5
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint]
review-requirements: []
implementation-commits: [f5d6e2e, 173cabf]
published-version: 0.29.1
published-at: 2026-07-02T17:09:39+0200
---

# TRDD-0NRVNDSZ — Window-aligned attribution — bounds from resets_at, not trailing intervals

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **USER requirement (verbatim, 2026-07-02):** "the current 5h interval started
  at 14:40 and will end at 19:40... the current 7d week interval started 17:00
  jul 1 and will end 17:00 jul 7... **those are the ones you need to monitor**
  for the current state and to discover why the tokens are consumed at an
  abnormal rhythm NOW."
- **Problem:** `token_history.project_metrics` computes `roll_5h`/`roll_7d` as
  TRAILING `now−5h`/`now−7d` sums. The subscription bills FIXED windows whose
  start is `resets_at − window_s` (both already parsed per account by
  `token_burn.windows_from_usage`). Trailing ≠ billed window → attribution
  numbers don't match what the user sees on the usage meter.
- **Design (minimal, one source of truth):**
  1. `token_burn.window_starts(accounts_usage, now)` → `(w5_lo, w7_lo)` pure
     helper: first account (live first) with a parseable window yields
     `resets_at_epoch − window_s` per label.
  2. `token_history.project_metrics(events, now, *, w5_lo=None, w7_lo=None)` —
     aligned bounds override the trailing defaults for `roll_5h`/`roll_7d`
     ONLY. Baseline/spike stay trailing (they are the project's own-norm
     signal, not a billing window).
  3. `fleet_attribution(..., w5_lo=None, w7_lo=None)` passes through and
     records the bounds in the returned dict. `since_epoch` default stays
     `now−7d` (widest scan; aligned bounds are always inside it because
     `resets_at ≥ now`).
  4. `token_attribution_cache.get/compute` accept the bounds; a cached fleet
     whose stored bounds differ from the requested ones is STALE (recompute).
     Bounds change once per rollover, so the 30-min cache stays effective.
  5. Consumers derive bounds from the live probe fail-soft (probe dead → None
     → trailing, previous behavior): `window-burn-rate.py` (it already gathers
     `accounts`) and `token_report.py --attribution` (adds a read-only probe).
- **WAVE 2 (user: "the commands report wrong values… fix them", 2026-07-02 ~17:00):**
  three MORE correctness bugs found + fixed on top of wave 1:
  1. `scan_project` globbed only TOP-LEVEL `*.jsonl` — every subagent transcript
     (`<session>/subagents/agent-*.jsonl`) was silently dropped: publish
     pipelines/fleet scans/memory agents (the heaviest burners) never counted.
     Fix: `rglob`, shared seen-set. Real-data effect: fleet-since-14:40 40M → 65.6M;
     janitor 10M/167msgs → 20.7M/400msgs. `SCAN_VERSION=2` stamped in the fleet
     dict; the cache treats an older/absent stamp as stale.
  2. `--attribution --since <ts> [--until <ts>]` — EXACT-interval mode: fresh
     uncached recursive scan summed over precisely the requested bounds (the
     user quotes the meter's own window start).
  3. `_parse_when` naive-ISO bug caught in validation: `th.parse_ts` read
     "14:40" as UTC (= 16:40 local, wrong window). fromisoformat-first so naive
     strings resolve LOCAL.
- **NEXT ACTION:** commit wave 2 + publish v0.29.1 (the user runs the CACHED
  plugin's commands — only a release makes the fixed numbers reachable via
  /janitor-token-report; until reload, run the repo script directly).

## Notes

Parent TRDD-OY0W6LX5 shipped the trailing version in v0.29.0 plus the
message.id dedupe fix (10471c2). This TRDD is the user-corrected window
semantics. Ad-hoc validation already exists: `scratchpad/window_aligned.py`
reproduced the user's exact bounds (14:40 / Jul 1 17:00) on real data.

## Approval log

- 2026-07-02T16:20:52+0200 — Tier 0 (derived task of OY0W6LX5, explicit USER
  instruction). Authored directly as planned/dev.
