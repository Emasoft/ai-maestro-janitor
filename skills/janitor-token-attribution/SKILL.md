---
name: janitor-token-attribution
description: Rank every project on this machine by how many tokens it is burning right now and name the one to throttle — the fleet token-attribution dashboard. The account 5h/7d utilization% is aggregate across all your parallel projects; this scans each project's transcripts to say WHICH one is over-consuming (large 5h share AND above its own baseline) and where its spike came from. Read-only. Use when the user asks which project is eating the token budget / which session to throttle / who is burning the rate-limit window.
---

# Janitor token-attribution

## Overview

The ATTRIBUTION half of the burn-rate alarm. The account `/api/oauth/usage` utilization% only reports
one aggregate number per subscription — it can't say which of ~10 parallel projects is burning the
window. This scan answers that: it streams every project's Claude Code transcripts under
`~/.claude/projects/<slug>/` (mtime-pruned to the last 7 days, so a 100+ MB transcript is never read
whole) and ranks by 5h weighted-token consumption. It is what the `window-burn-rate` detector
consults (via a shared 30-minute machine-wide cache) so the heartbeat advisory can name the culprit.

## When to use

- The user asks which project / session is eating the token budget or should be throttled.
- A `window-burn-rate` drift line fired and you want to name the specific over-consuming project.

## Instructions

Run the backing script and surface its output verbatim:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --attribution
```

Table columns: **project** (harness slug, shortened), **5h** / **7d** (rolling weighted-token sums),
**share5h** (fraction of the fleet 5h total), **spike** (recent rate vs its OWN trailing baseline; `—`
= no baseline yet), **subagents** (Task/Agent spawns in the last hour). A **top consumer** line names
the one project that is both large (≥ 20% of fleet 5h) AND above its own norm (spike ≥ 1.5× or no
baseline) — the one to advise to compact / throttle / stop idle subagents.

Every row + the fleet header separate the FOUR raw token categories — `output` (full price), `input`
(uncached, full price), `cache_wr` (~1.25× cache-miss write), `cache_rd` (~0.1× context re-read) —
beside the weighted blend, so expensive work is never conflated with cache re-reads.

Window / interval selectors (all take `--json` and `--graph`):

```bash
# EXACTLY the current subscription window (bounds = resets_at − W → now, from the live probe):
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --window 5h
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --window 7d
# The LAST completed window instead:
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --window 5h --last
# An arbitrary exact interval (naive ISO = LOCAL time):
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --attribution --since "2026-07-02T14:40" --until "2026-07-02T19:40"
```

`--graph` appends this project's unicode sparklines per category: per-bucket **rate** (the derivative) +
**cumulative** running sum, with a time axis (5-min bins for 5h, hourly for 7d). No live probe → the
window degrades to a labeled TRAILING interval; bounds are never silently wrong.

### The burn-rate alarm (heartbeat) + knobs

The `window-burn-rate` detector fires on the ~15-min heartbeat. A fixed-reset window should reach
100% exactly at its reset if spent evenly, so `burn_ratio = utilization% ÷ (100 × elapsed-fraction)`.
It reads each account's live utilization% + reset boundary **READ-ONLY** via the OAuth rotator (never
writes/rotates/mutates a credential) and emits one drift line per account+window when
`burn_ratio ≥ RATIO`, with projected exhaustion + the top-consuming project.

That read is served by the throttled `usage_probe` (TRDD-WEBA1RMF): a 10-min per-account cache with
`Retry-After`-aware back-off, so this 15-min detector and the rotator's 60 s beat share one request
budget instead of competing for it. A stale readout is reported as stale rather than rendered as
live — a cached `resets_at` may describe a window that has already reset, so showing its countdown
would be worse than showing nothing. Knobs:
- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED` (default `true`) — opt out entirely.
- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_RATIO` (default `1.5`) — the pace multiple that trips it.
- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_MIN_UTIL` (default `10.0`) — floor so a fresh window never alarms early.
- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_INTERVAL` (default `900`) — cadence (s).

## Scope

Read-only — it never writes or changes anything.
