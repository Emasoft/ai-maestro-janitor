#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""token-usage-anomaly — flag a SUDDEN token-usage spike vs the session's learned normal.

The Stop-hook meter logs every heartbeat turn's token cost to `token-meter.jsonl`. This
heartbeat detector reads that log, learns a ROBUST baseline (median + MAD) of per-5-min
weighted-token usage, and emits ONE drift line when the most-recent COMPLETE 5-min bucket
is a genuine outlier — robust-z >= Z AND above the FLOOR_PCT percentile of history — i.e.
SUDDEN anomalous behaviour, not a normal agent-spawn burst. The log is heavy-tailed +
bursty (measured: top 10% of buckets hold ~61% of tokens), so the threshold is
deliberately conservative and the baseline is robust (never mean/stddev — the tail wrecks
those). Deduped per bucket; silent otherwise.

This is the SLOW, pattern-based signal (recent usage vs the learned baseline); the
complementary FAST in-turn signal is the `pre-tool-token-budget` PreToolUse guard
(TRDD-KI24GR5Z). Together they cover both "this ONE turn spiked" and "recent usage drifted
above normal". For the 5h/7d window view + absolute cap estimate, run
`/janitor-token-report`.

Project-scoped, read-only, fail-open. Config `CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_*`:
  ENABLED (default on), BUCKET_SECONDS (300), Z (6), FLOOR_PCT (99).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import token_baseline as tb  # noqa: E402


def _load(log_path: Path) -> list[dict]:
    """Parse the token-meter JSONL into `{ts, output, …}` dicts; fail-open to []."""
    if not log_path.is_file():
        return []
    out: list[dict] = []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            r = json.loads(s)
        except ValueError:
            continue
        if isinstance(r, dict) and "ts" in r:
            out.append(r)
    return out


def main() -> int:
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_ENABLED", True):
        return 0
    records = _load(state.state_dir() / "token-meter.jsonl")
    if not records:
        return 0

    bucket_s = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_BUCKET_SECONDS"), 300,
        detector_name="token-usage-anomaly", var_name="BUCKET_SECONDS",
    )
    z = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_Z"), 6,
        detector_name="token-usage-anomaly", var_name="Z",
    )
    floor_pct = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_FLOOR_PCT"), 99,
        detector_name="token-usage-anomaly", var_name="FLOOR_PCT",
    )

    verdict = tb.classify_recent(
        records, bucket_s=bucket_s, z=float(z), floor_pct=float(floor_pct), now=int(time.time())
    )
    if verdict is None or not verdict.is_anomaly:
        return 0

    mins = max(1, bucket_s // 60)
    mult = (verdict.current / verdict.median) if verdict.median > 0 else 0.0
    msg = (
        f"[token-anomaly] last {mins} min used ~{verdict.current} weighted tokens — "
        f"{mult:.1f}x the session median ({int(verdict.median)}), robust-z {verdict.score:.1f} "
        f"over {verdict.n_history} buckets (a SUDDEN spike vs your normal). If this is a "
        f"runaway (many agents / long replies), stop background subagents with TaskStop and "
        f"/compact; run /janitor-token-report for the 5h/7d window view. "
        f"(Disable: CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_ENABLED=false.)"
    )
    # Per-BUCKET dedupe: each anomalous 5-min window alerts once (the bucket index is a
    # fixed wall-clock slot, so it never re-alerts across heartbeats or sessions).
    line = dedupe.emit_once(
        state.state_dir() / "token-usage-anomaly-seen.txt", f"bucket-{verdict.bucket}", msg
    )
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
