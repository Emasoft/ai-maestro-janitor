---
name: janitor-token-report
description: Show the per-heartbeat token cost — how many output/input tokens each janitor heartbeat fire spent, plus mean / p50 / p95 / max and spike flags — so you can see if the heartbeat's token consumption is spiking or the average is too high to bear. Reads the log the on-stop-token-meter hook writes after each fire. Also --live (exact current-session context-window usage + last-turn breakdown + auto-compact point), --window 5h|7d (exact subscription windows + graphs), and --attribution (which project is eating the budget). Read-only. Use when the user asks how much the janitor heartbeat costs in tokens, how full the context is, or whether they're near a rate limit.
---

# Janitor token-report

## Overview

Reads `$CLAUDE_PROJECT_DIR/.janitor/state/token-meter.jsonl` — the per-fire token log the
**on-stop-token-meter** Stop hook appends after every heartbeat turn — and reports the heartbeat's
token cost, plus (via flags) exact current-session context usage, exact subscription-window
consumption, and cross-project attribution.

## When to use

- The user asks how much the janitor heartbeat costs in tokens / whether it's spiking.
- The user asks how full the context window is right now, or how close to auto-compact (`--live`).
- The user asks whether they're burning a rate-limit window early (`--window`, `--live` burn line).
- The user asks which project is eating the token budget (`--attribution`).

## Instructions

Run the backing script and surface its output verbatim.

Base report (per-fire breakdown + distribution mean/p50/p95/max + spike/high-mean alarms):

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py"
# more fires:
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --recent 40
```

"no heartbeat token data yet" → the meter hasn't logged a fire in this project yet (one line per
heartbeat turn as those turns end). Spike thresholds (env): `CLAUDE_PLUGIN_OPTION_TOKEN_SPIKE_OUTPUT`
(default 4000), `CLAUDE_PLUGIN_OPTION_TOKEN_HIGH_MEAN_OUTPUT` (default 2500).

### `--live` — exact current-session numbers (no heartbeat log needed)

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --live
```

Prints the CURRENT session's exact **context window** (percent + tokens/window, from the same
statusline-snapshot-or-transcript-fallback source the `pre-tool-context-usage` watchdog uses via
`token_meter.resolve_context`), the **last turn**'s `output` (full price) / `cache_creation` (~1.25×
one-time cache-WRITE, billed once per prefix change — NOT context size) / `cache_read` (~0.1×), and —
when `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is set — the **exact auto-compact point** (env value minus the
~34k the summary itself costs) plus the distance to it. Also appends a per-account **window burn**
line when the OAuth rotator is configured. Use it when a per-turn token-runaway nudge fires and you
want to know whether it's a real context-size problem or a one-time post-compact cache rewrite. This
same prediction drives the watchdog's PREPARE alert (within
`CLAUDE_PLUGIN_OPTION_CONTEXT_PREPARE_TOKENS`, default 30000, of the auto-compact point it warns you
to `/janitor-write-handoff` first; the 34k overhead is `CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS`).

### `--window 5h|7d [--last] [--graph]` — exact subscription windows + charts

`--window 5h` (or `7d`) reports EXACTLY the current subscription window (bounds `resets_at − W → now`
from the live probe), per-project rows split into output / input / cache_write (~1.25×) / cache_read
(~0.1×). `--last` = the previous completed window. `--graph` = this project's unicode sparklines
(per-bucket rate + cumulative, 5-min bins for 5h, hourly for 7d). No live probe → labeled TRAILING
fallback. Full examples: `/janitor-token-attribution`.

### `--attribution` — which project is eating the token budget

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --attribution
```

Every project on this machine ranked by cross-project 5h/7d consumption + its fleet share +
spike-vs-own-baseline + the top consumer to advise. The account `/api/oauth/usage` utilization% is
aggregate across all parallel projects; this scans each project's transcripts to name WHICH one is
over-consuming. Companion to the `window-burn-rate` heartbeat alarm. See `/janitor-token-attribution`
for the full dashboard + burn knobs. Pass `--json` on any variant for machine-readable output.

## Scope

Read-only — it never writes or changes anything; the on-stop-token-meter hook does the logging.
