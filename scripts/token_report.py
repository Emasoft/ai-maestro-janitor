#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-token-report (TRDD-a4e41e89, Phase 1).

Reads the per-heartbeat token log written by the on-stop-token-meter hook
(`$PROJECT/.janitor/state/token-meter.jsonl`) and prints recent per-fire costs
plus distribution stats (mean / p50 / p95 / max) so spikes or a too-high
average are visible. `--json` for scripting.

Cost view: `output` tokens are the headline (full-price, the clearest driver of
agent work); `input` + `cache_creation` are full/premium price too; `cache_read`
is the cheap (~0.1x) context re-read, shown for context but not the alarm metric.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import token_meter  # noqa: E402

# A heartbeat whose output exceeds this is a "spike" worth the user's eye; also
# flagged relative to the run's own p95. Env-overridable.
_SPIKE_OUTPUT = int(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_SPIKE_OUTPUT", "4000"))
_HIGH_MEAN_OUTPUT = int(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_HIGH_MEAN_OUTPUT", "2500"))


def _state_dir() -> Path:
    proj = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    return Path(proj) / ".janitor" / "state"


def _fmt_ts(epoch: int) -> str:
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(epoch)


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-heartbeat token report")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--recent", type=int, default=15, help="how many recent fires to list")
    args = ap.parse_args()

    log_path = _state_dir() / "token-meter.jsonl"
    records = token_meter.load_log(log_path)

    if not records:
        if args.json:
            print(json.dumps({"count": 0, "log": str(log_path)}))
        else:
            print("[janitor-token-report] no heartbeat token data yet.")
            print(f"  (the on-stop-token-meter hook logs to {log_path} after each heartbeat fire)")
        return 0

    out_stats = token_meter.summarize(records, field="output")
    in_stats = token_meter.summarize(records, field="input")
    assert out_stats is not None and in_stats is not None
    p95_out = out_stats["p95"]
    spikes = [r for r in records if int(r.get("output", 0) or 0) >= max(_SPIKE_OUTPUT, p95_out)]

    if args.json:
        print(json.dumps({
            "count": out_stats["count"],
            "output": out_stats,
            "input": in_stats,
            "spike_threshold": max(_SPIKE_OUTPUT, p95_out),
            "spikes": len(spikes),
            "log": str(log_path),
        }, separators=(",", ":")))
        return 0

    print(f"[janitor-token-report] {out_stats['count']} heartbeat fires logged  ·  {log_path}")
    print()
    print(f"  output tokens/fire   mean {out_stats['mean']:.0f}  ·  p50 {out_stats['p50']}  ·  "
          f"p95 {out_stats['p95']}  ·  max {out_stats['max']}  ·  total {out_stats['total']}")
    print(f"  input  tokens/fire   mean {in_stats['mean']:.0f}  ·  p95 {in_stats['p95']}  ·  "
          f"max {in_stats['max']}")
    print()
    print(f"  {'when':<12} {'output':>7} {'input':>7} {'cache_rd':>9} {'cache_cr':>8} {'tools':>5}")
    print(f"  {'-'*12} {'-'*7} {'-'*7} {'-'*9} {'-'*8} {'-'*5}")
    for r in records[-args.recent:]:
        flag = "  ⚠ spike" if int(r.get("output", 0) or 0) >= max(_SPIKE_OUTPUT, p95_out) else ""
        print(f"  {_fmt_ts(r.get('ts', 0)):<12} {r.get('output', 0):>7} {r.get('input', 0):>7} "
              f"{r.get('cache_read', 0):>9} {r.get('cache_creation', 0):>8} {r.get('tool_calls', 0):>5}{flag}")
    print()
    if spikes:
        print(f"  ⚠ {len(spikes)} fire(s) above the spike threshold "
              f"({max(_SPIKE_OUTPUT, p95_out)} output tokens).")
    if out_stats["mean"] >= _HIGH_MEAN_OUTPUT:
        print(f"  ⚠ mean output/fire ({out_stats['mean']:.0f}) is above {_HIGH_MEAN_OUTPUT} — "
              "consider lengthening the heartbeat interval or pushing more work into scripts.")
    if not spikes and out_stats["mean"] < _HIGH_MEAN_OUTPUT:
        print("  ✓ no spikes; mean per-fire cost is within budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
