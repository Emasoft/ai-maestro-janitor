---
description: Show the per-heartbeat token cost — how many output/input tokens each janitor heartbeat fire spent, plus mean / p50 / p95 / max and spike flags — so you can see if the heartbeat's token consumption is spiking or the average is too high to bear. Reads the log the on-stop-token-meter hook writes after each fire. Read-only. Trigger with /janitor-token-report or by asking how much the janitor heartbeat costs in tokens.
---

# /janitor-token-report

Run the backing script and surface its output verbatim to the user:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py"
```

It reads `$CLAUDE_PROJECT_DIR/.janitor/state/token-meter.jsonl` — the per-fire
token log the **on-stop-token-meter** Stop hook appends after every heartbeat
turn — and prints:

- **Per-fire breakdown** (recent fires): output / input / cache-read /
  cache-creation tokens + tool-call count, with `⚠ spike` on any fire above the
  spike threshold.
- **Distribution**: mean, p50, p95, max, and total output tokens/fire (output is
  the headline — it's full-price and the clearest signal of agent work), plus the
  same for input tokens.
- **Alarms**: a count of spike fires, and a warning if the mean output/fire is
  above budget (suggesting you lengthen the heartbeat interval or push more work
  into scripts).

Pass `--json` for machine-readable output, or `--recent N` to list more fires:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --recent 40
```

If it reports "no heartbeat token data yet", the meter hasn't logged a fire in
this project yet (it logs one line per heartbeat turn as those turns end).

Tunable thresholds (env): `CLAUDE_PLUGIN_OPTION_TOKEN_SPIKE_OUTPUT` (default
4000) and `CLAUDE_PLUGIN_OPTION_TOKEN_HIGH_MEAN_OUTPUT` (default 2500).

## `--live` — exact current-session numbers (no heartbeat log needed)

Pass `--live` for the CURRENT session's exact context-window usage plus the
most recent turn's token breakdown — independent of the heartbeat log above:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --live
```

It prints:

- **Context window**: exact percent used and `tokens/window` (e.g.
  `61% (598k/1.0m) used`) — the same statusline-snapshot-or-transcript-fallback
  source the `pre-tool-context-usage` context watchdog uses
  (`token_meter.resolve_context`, shared between the two so they can never
  silently disagree).
- **Last turn**: `output` (full price), `cache_creation` (a one-time cache-WRITE,
  ~1.25x, billed once per prefix change — NOT the same thing as context size),
  and `cache_read` (cheap re-read, ~0.1x).
- **Auto-compact point** (only when `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is set): the
  EXACT token count at which Claude Code will force an auto-compact — the env-var
  value minus the ~34k the compact routine itself spends writing the summary — plus
  how many tokens remain until it (e.g. `Auto-compact point: 666k (window 700k − 34k
  summary)  ·  ~26k until auto-compact`). This is the true distance-to-compaction,
  not a percent of a fixed 1M.

`--live` finds the current session's transcript by its own most-recently-modified
`.jsonl` file under `~/.claude/projects/<slug>/`; if none is found it says so and
exits cleanly. Combine with `--json` for machine-readable output. Use this when
you see a per-turn token-runaway nudge and want to know whether it's a genuine
context-size problem or just a one-time post-compact cache rewrite.

That same prediction drives the `pre-tool-context-usage` watchdog's **PREPARE
alert**: within `CLAUDE_PLUGIN_OPTION_CONTEXT_PREPARE_TOKENS` (default 30000) of the
auto-compact point it warns you to finish the current step and run
`/janitor-write-handoff` so the compaction summary captures your plan before the
forced compaction. The 34k summary overhead is overridable via
`CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS`.

`--live` also appends a per-account **window burn** line when the OAuth rotator is
configured — each account's live 5h/7d utilization% with its burn ratio (pace vs
the even budget) and projected exhaustion, read-only.

## `--window 5h|7d [--last] [--graph]` — exact subscription windows + charts

`--window 5h` (or `7d`) reports EXACTLY the current subscription window — bounds
derived from the live probe as `resets_at − W → now` — with per-project rows
split into the four raw categories (output / input / cache_write ~1.25× /
cache_read ~0.1×). `--last` selects the PREVIOUS completed window instead.
`--graph` appends this project's unicode sparklines: per-bucket **rate** (the
derivative) + **cumulative** curve per category, with a time axis (5-min bins
for 5h, hourly for 7d). No live probe → labeled TRAILING fallback. Details +
examples: `/janitor-token-attribution`.

## `--attribution` — which project is eating the token budget

Pass `--attribution` for the fleet dashboard: every project on this machine
ranked by its cross-project 5h/7d token consumption, its share of the fleet, its
spike-vs-own-baseline, and the **top consumer** to advise:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/token_report.py" --attribution
```

The account `/api/oauth/usage` utilization% is aggregate across all your parallel
projects; this scans each project's transcripts to name WHICH one is
over-consuming. It is the companion to the `window-burn-rate` heartbeat alarm,
which emits a drift line when a 5h/7d window burns **≥ 1.5×** its even-pace budget
(heading for an early rate-limit) and names that culprit. See
`/janitor-token-attribution` for the full dashboard + the burn-alarm env knobs
(`CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED` / `…_RATIO` / `…_MIN_UTIL`).

Read-only — it never writes or changes anything; the hook does the logging.
