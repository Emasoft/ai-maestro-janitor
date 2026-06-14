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

Read-only — it never writes or changes anything; the hook does the logging.
