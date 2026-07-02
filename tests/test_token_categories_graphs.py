"""Regression tests for per-category token accounting + terminal graphs (TRDD-4MMXTJFB).

Pins the surfaces the user's precision complaint produced: Events carry all four raw
usage categories, window sums report them separately, bucket_series produces the
graphable derivative series, and the sparkline renderer never lies about zeros.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import token_graph as tg  # noqa: E402
import token_history as th  # noqa: E402

NOW = int(time.time()) - 3600  # a PAST epoch so mtime pruning keeps fixture files


def _write_transcript(d: Path, ts: int) -> None:
    d.mkdir(parents=True, exist_ok=True)
    line = {
        "type": "assistant",
        "timestamp": th.datetime.fromtimestamp(ts, tz=th.timezone.utc).isoformat(),
        "message": {
            "id": f"msg_{ts}",
            "usage": {
                "output_tokens": 100,
                "input_tokens": 20,
                "cache_creation_input_tokens": 300,
                "cache_read_input_tokens": 5000,
            },
            "content": [],
        },
    }
    (d / "s.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")


def test_event_carries_all_four_categories(tmp_path: Path) -> None:
    """input + cache_read must be parsed raw, not folded into weighted (the precision bug)."""
    _write_transcript(tmp_path / "p", NOW)
    events = th.scan_project(tmp_path / "p", NOW - 10)
    assert len(events) == 1
    e = events[0]
    assert (e.output, e.input, e.cache_creation, e.cache_read) == (100, 20, 300, 5000)
    assert e.weighted == 100 + 20 + 300 + 5000 / 10.0


def test_category_sums_partition_and_metrics_expose_them(tmp_path: Path) -> None:
    """project_metrics.cat_5h/cat_7d report the four categories over the SAME window as
    roll_5h/roll_7d; the last-hour source shares partition to 1.0 from REAL fields."""
    _write_transcript(tmp_path / "p", NOW - 60)
    events = th.scan_project(tmp_path / "p", NOW - 3600)
    m = th.project_metrics(events, NOW)
    assert m["cat_5h"]["output"] == 100.0
    assert m["cat_5h"]["input"] == 20.0
    assert m["cat_5h"]["cache_creation"] == 300.0
    assert m["cat_5h"]["cache_read"] == 5000.0
    assert m["cat_5h"]["weighted"] == m["roll_5h"]
    src = m["source"]
    shares = src["output_share"] + src["input_share"] + src["cache_creation_share"] + src["cache_read_tenth_share"]
    assert abs(shares - 1.0) < 1e-9


def test_scan_version_is_3() -> None:
    """The per-category schema bump: cached v2 fleets must be treated as stale."""
    assert th.SCAN_VERSION == 3


def test_bucket_series_derivative_and_bounds() -> None:
    """Events land in the right bins; empty bins are 0; junk bounds/field → []."""
    ev = [
        th.Event(ts=1000, weighted=10.0, output=1, cache_creation=0, tool_calls=0, subagent_spawns=0),
        th.Event(ts=1150, weighted=5.0, output=2, cache_creation=0, tool_calls=0, subagent_spawns=0),
        th.Event(ts=1290, weighted=7.0, output=4, cache_creation=0, tool_calls=0, subagent_spawns=0),
    ]
    assert th.bucket_series(ev, 1000, 1300, 3) == [10.0, 5.0, 7.0]
    assert th.bucket_series(ev, 1000, 1300, 3, "output") == [1.0, 2.0, 4.0]
    assert th.bucket_series(ev, 1000, 1300, 0) == []
    assert th.bucket_series(ev, 1300, 1000, 3) == []
    assert th.bucket_series(ev, 1000, 1300, 3, "nope") == []


def test_sparkline_scaling_zeros_and_empty() -> None:
    """Zeros render as the gap glyph (distinct from tiny values); the peak gets the top bar."""
    s = tg.sparkline([0.0, 1.0, 100.0])
    assert s[0] == "·"
    assert s[2] == "█"
    assert s[1] != "·"  # tiny-but-nonzero must be visible
    assert tg.sparkline([]) == ""
    assert tg.sparkline([0.0, 0.0]) == "··"


def test_render_series_has_rate_cumulative_axis() -> None:
    """The graph block is rate + cumulative + axis, with the correct total annotation."""
    lines = tg.render_series([5.0, 0.0, 15.0], 0, 900, label="weighted", bucket_label="5min")
    assert len(lines) == 3
    assert "rate/5min" in lines[0] and "peak 15" in lines[0]
    assert "cumulative" in lines[1] and "total 20" in lines[1]
    assert "axis" in lines[2] and "(3 bins)" in lines[2]
    assert tg.render_series([], 0, 900, label="weighted", bucket_label="5min") == []


def test_render_window_graphs_skips_dead_categories() -> None:
    """A category with zero activity must not print an all-gap chart."""
    ev = [th.Event(ts=100, weighted=10.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0, input=0, cache_read=100)]
    lines = tg.render_window_graphs(ev, 0, 200, buckets=4, bucket_label="5min", fields=("weighted", "output"))
    text = "\n".join(lines)
    assert "weighted" in text
    assert "output" not in text


def test_graph_bins_resolution() -> None:
    """5h-class → 5-min bins; 7d-class → hourly capped at 168."""
    import importlib

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    tr = importlib.import_module("token_report")  # dynamic: scripts/ isn't a static package

    assert tr._graph_bins(5 * 3600) == (60, "5min")
    assert tr._graph_bins(7 * 86400) == (168, "1h")
    bins, label = tr._graph_bins(24 * 3600)
    assert label == "30min" and bins == 48
