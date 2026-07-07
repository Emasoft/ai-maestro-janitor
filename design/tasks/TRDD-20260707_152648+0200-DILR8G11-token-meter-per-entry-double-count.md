---
trdd-id: DILR8G11
title: Token meter double-counts — per-ENTRY usage summing inflates turns 2.1-3.7x
column: complete
created: 2026-07-07T15:26:48+0200
updated: 2026-07-07T15:26:48+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: S
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
labels: [token-meter, observability]
implementation-commits: [29d2506]
---

# TRDD-DILR8G11 — Token meter per-entry double-count (USER bug report 2026-07-07)

## The bug

USER: "the janitor own meter is FLAWED.. it reports wrong token data." Confirmed on the
live session transcript: Claude Code writes one `assistant` transcript ENTRY per streamed
CONTENT BLOCK, and every entry of the same API response repeats the SAME `message.usage`
object. `token_meter.tail_turn_usage` summed usage per ENTRY, so a response with N blocks
was counted N times. Measured inflation on real turns: cache_read 21.0M reported vs 9.8M
real (2.14x); cache_creation 998k vs 267k (3.7x); max 10 entries for one message.

Every consumer inherited it: `pre-tool-token-budget`'s spike warnings (the "~1M cache-miss"
lines that were really ~270-360k), `token-meter.jsonl` (TRDD-a4e41e89),
the `token-usage-anomaly` baseline (TRDD-EDSFEQ5C — learned a 2-3x inflated median),
`/janitor-token-report`, and the `window-exhaustion.jsonl` "empirical cap" snapshots.
NOT affected: `latest_context_size` (reads ONE message) — it matches the CC statusline
(verified 425k vs the ~400k/1.0M shown while drifting live), so the context-watchdog
numbers were always right.

## The fix (shipped in 29d2506)

Dedupe by `message.id` — count usage ONCE per unique id, last entry wins (identical today;
last-wins stays correct if CC ever streams cumulative usage). Missing-id entries fall back
to the entry `uuid` (never merged, never dropped). `tool_use` blocks stay per-entry (each
entry carries its own distinct block). `assistant_messages` now counts unique messages.
Regression test: `test_duplicated_usage_entries_counted_once_per_message`.

Pre-fix history logs were quarantined to `.janitor/state/*.pre-dedupe-fix.bak` so the
anomaly baseline re-learns from clean data instead of the inflated median.

## Residual notes

- Any tuning done against pre-fix readings (budget-hook thresholds, baseline expectations,
  the "empirical cap >= X" claims in old reports) referred to inflated numbers — treat
  historical claims as 2-3x overstated.
- The per-origin attribution follow-up lives in TRDD-YXY992BN.
