---
description: Rank every project on this machine by how many tokens it is burning right now and name the one to throttle — the fleet token-attribution dashboard. The account 5h/7d utilization% is aggregate across all your parallel projects; this scans each project's transcripts to say WHICH one is over-consuming (large 5h share AND above its own baseline) and where its spike came from. Read-only. Trigger with /janitor-token-attribution or by asking which project is eating the token budget.
---

# /janitor-token-attribution

Run the backing script and surface its output verbatim to the user:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --attribution
```

It streams every project's Claude Code transcripts under
`~/.claude/projects/<slug>/` (mtime-pruned to the last 7 days, so a 100+ MB
transcript is never read whole) and prints a table ranked by 5h weighted-token
consumption:

- **project** — the harness slug (shortened), **5h** / **7d** — its rolling
  weighted-token sums, **share5h** — its fraction of the fleet 5h total,
  **spike** — its recent rate vs its OWN trailing baseline (`—` when it has no
  baseline yet), **subagents** — Task/Agent spawns in the last hour.
- A **top consumer** line: the one project that is both large (≥ 20% of fleet 5h)
  AND above its own norm (spike ≥ 1.5× or no baseline) — the one to advise to
  compact / throttle / stop idle subagents.

This is the ATTRIBUTION half of the burn-rate alarm. The account
`/api/oauth/usage` utilization% only reports one aggregate number per
subscription — it can't say which of ~10 parallel projects is burning the
window. This scan answers that. It is what the `window-burn-rate` detector
consults (via a shared 30-minute machine-wide cache) when a window trips, so the
heartbeat's advisory can name the culprit instead of just "you're 46% at 1.6×
pace".

## Exact windows, per-category columns, graphs (TRDD-4MMXTJFB)

Every row and the fleet header now separate the FOUR raw token categories —
`output` (full price), `input` (uncached, full price), `cache_wr` (the ~1.25×
cache-miss write) and `cache_rd` (the cheap ~0.1× context re-read) — beside the
weighted blend, so the expensive work is never conflated with cache re-reads.

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

`--graph` appends unicode sparkline charts for THIS project's events over the
selected window, per category: the per-bucket **rate** (the derivative — how fast
tokens were consumed) and the **cumulative** running sum, with a time axis.
Bin width auto-scales: 5-min bins for a 5h window, hourly for 7d. When the live
probe is unavailable the window degrades to a TRAILING interval and the header
says so — bounds are never silently wrong.

## The burn-rate alarm (heartbeat) + knobs

The `window-burn-rate` detector fires on the ~15-min heartbeat. A fixed-reset
window (5h rolling / 7d) should reach 100% exactly at its reset if spent evenly,
so `burn_ratio = utilization% ÷ (100 × elapsed-fraction-of-window)`. It reads
each account's live utilization% + reset boundary **READ-ONLY** through the OAuth
rotator (it never writes, rotates, or mutates any credential) and emits one drift
line per account+window when `burn_ratio ≥ RATIO` — heading for an early
rate-limit — with the projected exhaustion time and the top-consuming project.

Tunable env knobs:

- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED` (default `true`) — opt out entirely.
- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_RATIO` (default `1.5`) — the pace multiple
  that trips the alarm.
- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_MIN_UTIL` (default `10.0`) — a floor so a
  fresh, barely-used window never alarms on a huge early ratio.
- `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_INTERVAL` (default `900`) — the cadence (s).

Pass `--json` for machine-readable output. Read-only — it never writes or changes
anything.
