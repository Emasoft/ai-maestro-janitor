---
trdd-id: 4MMXTJFB
title: Precise per-category token accounting, explicit window selectors, terminal graphs, cache audit
column: dev
created: 2026-07-03T00:46:03+0200
updated: 2026-07-03T00:46:03+0200
current-owner: janitor-session
assignee: janitor-session
priority: 1
severity: HIGH
effort: L
labels: [token-meter, attribution, observability]
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint]
review-requirements: []
implementation-commits: []
---

# TRDD-4MMXTJFB — Precise token accounting + window selectors + graphs + cache audit

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-03

- **USER order (2026-07-03, verbatim intent):** "we still got a imprecise token
  usage estimation. not distinguishing cache read from cache writes, input
  tokens from output tokens, etc. improve the system. also check that the cache
  optimization techniques are used across all the janitor. and add explicit
  options to the token reports commands to show only the last or the current 5h
  interval, or 7d interval. even graphs of those windows are important … both
  as cumulative value and as derivative (tokens rate per turn)."
- **Four deliverables / phases:**
  1. **Per-category accounting** — `token_history.Event` gains `input` +
     `cache_read` (today only weighted/output/cache_creation are kept raw);
     `project_metrics` + `_render_interval` + `_render_attribution` report the
     four raw categories (output / input / cache_creation / cache_read)
     SEPARATELY alongside the documented weighted blend. `SCAN_VERSION` → 3
     (cache invalidation). `source` shares computed from REAL fields, not the
     residual approximation.
  2. **Graph lib** — new pure `scripts/lib/token_graph.py`: time-bucketed
     series (`bucket_series` in token_history) rendered as unicode sparklines —
     CUMULATIVE curve + PER-BUCKET rate (the derivative), per category.
  3. **Window selectors** — `token_report.py --window 5h|7d [--last]`
     (default = CURRENT window): bounds derived from the live probe
     (`token_burn.window_starts`; current = [resets_at−W, now], last =
     [resets_at−2W, resets_at−W]) feeding the existing exact-interval scan.
     `--graph` renders the charts for the selected window (current project's
     transcripts; fleet totals stay tabular). Command docs updated.
  4. **Cache-optimization audit** — verify the janitor's own surfaces follow
     the cache economics (heartbeat cadence ≤ TTL, maintenance mode, hook
     output minimalism, stable cron prompt, emit-once dedupe); report +
     fix anything concrete.
- **NEXT ACTION:** Phase 1 implementation (token_history.py + tests).
- **Load-bearing facts:** transcript usage keys are
  `message.usage.{input,output,cache_creation_input,cache_read_input}_tokens`;
  weighted = output + input + cache_creation + cache_read/10; window-aligned
  bounds ship since v0.29.1 (TRDD-0NRVNDSZ); fleet cache checks `scan` version
  + bounds match (token_attribution_cache).
