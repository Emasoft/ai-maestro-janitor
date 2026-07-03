"""Tests for the cross-project per-account token attribution miner (TRDD-OY0W6LX5).

Real I/O, no mocks: fixture project dirs with hand-built `*.jsonl` transcripts carrying
known usage + timestamps. Covers the weighting math, ISO timestamp parsing (Z / offset /
junk), the `since_epoch` filter + the mtime prune, rolling sums, per-project shares,
the spike factor + step-up detection, subagent-spawn counting, and the culprit pick
(including the no-culprit-below-floors and spike-is-None-passes cases).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import token_history as th  # noqa: E402

# NOW is hour-aligned (NOW % 3600 == 0) so wall-clock hour buckets land predictably:
# the bucket key of NOW is NOW // 3600, and every past event falls in a lower bucket.
NOW = 1_800_000_000
assert NOW % 3600 == 0
_HOUR = 3600


def _iso(epoch: int, *, suffix: str = "Z") -> str:
    """Render an epoch as a UTC ISO-8601 string; `suffix` chooses the `Z` or `+00:00` form."""
    base = datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None).isoformat()
    return base + suffix


def _assistant(epoch: int, *, output: int = 0, inp: int = 0, cache_read: int = 0, cache_creation: int = 0, tools: list[str] | None = None) -> dict:
    """A `type:assistant` transcript entry with the given usage + tool_use blocks."""
    content = [{"type": "tool_use", "name": name} for name in (tools or [])]
    return {
        "type": "assistant",
        "timestamp": _iso(epoch),
        "message": {
            "usage": {
                "output_tokens": output,
                "input_tokens": inp,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            },
            "content": content,
        },
    }


def _write_jsonl(path: Path, entries: list[dict], *, junk: bool = False) -> None:
    """Write `entries` as JSONL; when `junk`, splice in a corrupt line and a blank line."""
    lines = [json.dumps(e) for e in entries]
    if junk:
        lines.insert(1 if len(lines) > 1 else 0, "{not valid json,,,")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _touch(path: Path, epoch: int = NOW - 100) -> None:
    """Set a fixture file's mtime into the scan window. NOW is a synthetic epoch, so a freshly
    written file's REAL mtime would fall OUTSIDE [NOW-7d, NOW] and be pruned by scan_project —
    set it explicitly so the mtime-prune keeps the file."""
    os.utime(path, (epoch, epoch))


def _ev(bucket: int, weighted: float, *, output: int = 0, cache_creation: int = 0, subagent_spawns: int = 0) -> th.Event:
    """An `Event` placed 60s into wall-clock hour `bucket` (so ts // 3600 == bucket)."""
    return th.Event(ts=bucket * _HOUR + 60, weighted=float(weighted), output=output, cache_creation=cache_creation, tool_calls=0, subagent_spawns=subagent_spawns)


# ── weighted ─────────────────────────────────────────────────────────────────────
def test_weighted_math() -> None:
    """weighted = output + input + cache_creation + cache_read/10 (cache_read counts 1/10)."""
    usage = {"output_tokens": 100, "input_tokens": 20, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 500}
    assert th.weighted(usage) == pytest.approx(100 + 20 + 30 + 50.0)


def test_weighted_non_dict_is_zero() -> None:
    """A corrupt / missing usage (non-dict) weighs 0.0 rather than raising."""
    assert th.weighted(None) == 0.0  # type: ignore[arg-type]
    assert th.weighted({}) == 0.0


# ── parse_ts ─────────────────────────────────────────────────────────────────────
def test_parse_ts_z_with_fraction() -> None:
    """A trailing-Z timestamp with fractional seconds parses to floored epoch seconds."""
    assert th.parse_ts("2026-07-02T12:16:37.606Z") == th.parse_ts("2026-07-02T12:16:37Z")
    assert th.parse_ts("1970-01-01T00:00:10Z") == 10


def test_parse_ts_offset_matches_utc() -> None:
    """A numeric-offset timestamp resolves to the same instant as its UTC/Z spelling."""
    assert th.parse_ts("2026-07-02T14:16:37+02:00") == th.parse_ts("2026-07-02T12:16:37Z")


def test_parse_ts_junk_is_none() -> None:
    """Empty, non-ISO, and non-string inputs return None (skipped, never crash)."""
    assert th.parse_ts("") is None
    assert th.parse_ts("not a date") is None
    assert th.parse_ts(None) is None  # type: ignore[arg-type]


# ── scan_transcript ──────────────────────────────────────────────────────────────
def test_scan_transcript_since_filter(tmp_path: Path) -> None:
    """Only assistant entries at or after since_epoch are returned; older ones are dropped."""
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_assistant(NOW - 100, output=10), _assistant(NOW - 10 * 86400, output=99)])
    events = th.scan_transcript(f, NOW - th._7D)
    assert len(events) == 1
    assert events[0].ts == th.parse_ts(_iso(NOW - 100))
    assert events[0].output == 10


def test_scan_transcript_junk_and_nonassistant_tolerated(tmp_path: Path) -> None:
    """Junk lines, blank lines, and non-assistant entries are skipped; the valid turn parses."""
    f = tmp_path / "s.jsonl"
    entries = [{"type": "user", "timestamp": _iso(NOW - 50), "message": {"content": "hi"}}, _assistant(NOW - 40, output=7)]
    _write_jsonl(f, entries, junk=True)
    events = th.scan_transcript(f, NOW - th._7D)
    assert len(events) == 1
    assert events[0].output == 7


def test_scan_transcript_counts_tools_and_subagents(tmp_path: Path) -> None:
    """tool_use blocks count as tool_calls; the Task/Agent subset counts as subagent_spawns."""
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_assistant(NOW - 30, output=5, tools=["Task", "Bash", "Agent", "Read"])])
    ev = th.scan_transcript(f, NOW - th._7D)[0]
    assert ev.tool_calls == 4
    assert ev.subagent_spawns == 2


def test_scan_transcript_missing_file_is_empty(tmp_path: Path) -> None:
    """A nonexistent transcript yields an empty list, never an exception."""
    assert th.scan_transcript(tmp_path / "nope.jsonl", NOW - th._7D) == []


# ── scan_project ─────────────────────────────────────────────────────────────────
def test_scan_project_merges_and_sorts(tmp_path: Path) -> None:
    """Events from every *.jsonl in the dir are merged and sorted ascending by ts."""
    _write_jsonl(tmp_path / "a.jsonl", [_assistant(NOW - 100, output=1)])
    _write_jsonl(tmp_path / "b.jsonl", [_assistant(NOW - 5000, output=2), _assistant(NOW - 50, output=3)])
    _touch(tmp_path / "a.jsonl")
    _touch(tmp_path / "b.jsonl")
    events = th.scan_project(tmp_path, NOW - th._7D)
    assert [e.ts for e in events] == sorted(e.ts for e in events)
    assert [e.output for e in events] == [2, 1, 3]  # NOW-5000, NOW-100, NOW-50


def test_scan_project_mtime_prune(tmp_path: Path) -> None:
    """A file whose mtime predates since_epoch is skipped WITHOUT opening it — even though it
    contains a recent-looking entry — because its last append (hence newest entry) is older."""
    old = tmp_path / "old.jsonl"
    _write_jsonl(old, [_assistant(NOW - 100, output=42)])  # entry LOOKS recent
    stale = NOW - 8 * 86400  # but the file's mtime is 8 days old
    os.utime(old, (stale, stale))
    recent = tmp_path / "recent.jsonl"
    _write_jsonl(recent, [_assistant(NOW - 100, output=7)])
    os.utime(recent, (NOW - 100, NOW - 100))
    events = th.scan_project(tmp_path, NOW - th._7D)
    assert [e.output for e in events] == [7]  # only the un-pruned file's event survives


# ── project_metrics ──────────────────────────────────────────────────────────────
def test_project_metrics_rolling_sums() -> None:
    """roll_5h / roll_7d / recent_1h sum weighted tokens over their respective windows."""
    events = [
        th.Event(ts=NOW - 100, weighted=10.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0),
        th.Event(ts=NOW - 7200, weighted=20.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0),
        th.Event(ts=NOW - 21600, weighted=30.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0),
        th.Event(ts=NOW - 8 * 86400, weighted=40.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0),
    ]
    m = th.project_metrics(events, NOW)
    assert m["recent_1h"] == pytest.approx(10.0)  # only the last-hour event
    assert m["roll_5h"] == pytest.approx(30.0)  # last-hour + 2h-ago (6h-ago excluded)
    assert m["roll_7d"] == pytest.approx(60.0)  # + 6h-ago (8d-ago excluded)


def test_project_metrics_baseline_and_spike() -> None:
    """Baseline = median of the prior-7d hourly buckets (excl. last hour); spike = recent/baseline."""
    events = [
        _ev(NOW // _HOUR - 2, 60),  # baseline hour
        _ev(NOW // _HOUR - 3, 120),  # baseline hour (median)
        _ev(NOW // _HOUR - 4, 600),  # baseline hour
        th.Event(ts=NOW - 600, weighted=300.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0),  # last hour
    ]
    m = th.project_metrics(events, NOW)
    assert m["rate_baseline_per_min"] == pytest.approx(120.0 / 60.0)  # median(60,120,600)=120 → 2/min
    assert m["rate_recent_per_min"] == pytest.approx(300.0 / 60.0)  # 300 in the last hour → 5/min
    assert m["spike_factor"] == pytest.approx(2.5)


def test_project_metrics_spike_none_without_baseline() -> None:
    """With no prior-7d activity, there is no baseline → spike_factor is None (not a division error)."""
    m = th.project_metrics([th.Event(ts=NOW - 600, weighted=300.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0)], NOW)
    assert m["rate_baseline_per_min"] == 0.0
    assert m["spike_factor"] is None


def test_project_metrics_source_breakdown() -> None:
    """The last hour's FOUR source shares partition the weighted total (sum to 1.0) from the
    REAL per-category fields (TRDD-4MMXTJFB — no longer a residual approximation), and count
    spawns. Fixture is self-consistent: weighted = output + input + cache_creation + cache_read/10."""
    events = [th.Event(ts=NOW - 600, weighted=200.0, output=100, cache_creation=50, tool_calls=1, subagent_spawns=1, input=20, cache_read=300)]
    src = th.project_metrics(events, NOW)["source"]
    assert src["output_share"] == pytest.approx(0.5)  # 100/200
    assert src["input_share"] == pytest.approx(0.1)  # 20/200
    assert src["cache_creation_share"] == pytest.approx(0.25)  # 50/200
    assert src["cache_read_tenth_share"] == pytest.approx(0.15)  # (300/10)/200
    total = src["output_share"] + src["input_share"] + src["cache_creation_share"] + src["cache_read_tenth_share"]
    assert total == pytest.approx(1.0)
    assert src["subagent_spawns"] == 1


def test_project_metrics_step_up_ts() -> None:
    """step_up_ts is the start of the CURRENT contiguous elevated run (>= 2x baseline), scanning
    back from now — an old, isolated elevated hour is ignored."""
    cur = NOW // _HOUR
    events = [
        # baseline low hours (weighted 60 → 1/min) — the median stays low.
        _ev(cur - 10, 60),
        _ev(cur - 11, 60),
        _ev(cur - 12, 60),
        _ev(cur - 13, 60),
        _ev(cur - 14, 60),
        # contiguous elevated run in the 3 most-recent hours (weighted 300 → 5/min >= 2/min).
        th.Event(ts=NOW - 600, weighted=300.0, output=0, cache_creation=0, tool_calls=0, subagent_spawns=0),  # bucket cur-1
        _ev(cur - 2, 300),
        _ev(cur - 3, 300),
        # an OLD isolated elevated hour, not contiguous with the recent run — must be ignored.
        _ev(cur - 20, 300),
    ]
    m = th.project_metrics(events, NOW)
    assert m["rate_baseline_per_min"] == pytest.approx(1.0)  # median of the low buckets
    assert m["step_up_ts"] == (cur - 3) * _HOUR  # earliest hour of the contiguous recent run


def test_project_metrics_empty_is_all_zero() -> None:
    """Empty events → zero sums, None spike/step-up, zero source shares — no crash."""
    m = th.project_metrics([], NOW)
    assert m["roll_5h"] == 0.0 and m["roll_7d"] == 0.0 and m["recent_1h"] == 0.0
    assert m["spike_factor"] is None and m["step_up_ts"] is None
    assert m["source"]["output_share"] == 0.0 and m["source"]["subagent_spawns"] == 0


# ── fleet_attribution + culprit ──────────────────────────────────────────────────
def _project_dir(root: Path, slug: str, entries: list[dict]) -> Path:
    d = root / slug
    d.mkdir()
    _write_jsonl(d / "session.jsonl", entries)
    _touch(d / "session.jsonl")  # mtime into [NOW-7d, NOW] so the prune keeps it
    return d


def test_fleet_attribution_shares_and_ranking(tmp_path: Path) -> None:
    """Per-project 5h shares are of the fleet total, ranking is roll_5h-descending, and a dir with
    no *.jsonl is excluded."""
    _project_dir(tmp_path, "alpha", [_assistant(NOW - 100, output=100)])
    _project_dir(tmp_path, "bravo", [_assistant(NOW - 100, output=300)])
    _project_dir(tmp_path, "charlie", [_assistant(NOW - 100, output=50)])
    (tmp_path / "not-a-project").mkdir()  # no *.jsonl → excluded
    fleet = th.fleet_attribution(tmp_path, NOW)
    assert set(fleet["projects"]) == {"alpha", "bravo", "charlie"}
    assert fleet["ranking"] == ["bravo", "alpha", "charlie"]  # 300 > 100 > 50
    assert fleet["totals"]["roll_5h"] == pytest.approx(450.0)
    assert fleet["projects"]["bravo"]["share_5h"] == pytest.approx(300.0 / 450.0)
    assert fleet["projects"]["alpha"]["share_5h"] == pytest.approx(100.0 / 450.0)


def test_fleet_attribution_default_since_prunes_old(tmp_path: Path) -> None:
    """The default since_epoch (now-7d) prunes an old-mtime file: the project appears (it HAS a
    *.jsonl) but contributes zero weighted tokens."""
    d = _project_dir(tmp_path, "delta", [_assistant(NOW - 100, output=500)])
    stale = NOW - 8 * 86400
    os.utime(d / "session.jsonl", (stale, stale))
    fleet = th.fleet_attribution(tmp_path, NOW)  # since_epoch defaults to NOW - 7d
    assert "delta" in fleet["projects"]
    assert fleet["projects"]["delta"]["roll_5h"] == 0.0
    assert fleet["since_epoch"] == NOW - th._7D


def _fleet(projects: dict[str, dict]) -> dict:
    """Build a minimal fleet dict (ranking = roll_5h-descending) for culprit tests."""
    ranking = sorted(projects, key=lambda s: projects[s]["roll_5h"], reverse=True)
    return {"projects": projects, "ranking": ranking}


def test_culprit_picks_biggest_qualifier() -> None:
    """The culprit is the highest-roll_5h slug clearing both floors (share >= 0.2, spike >= 1.5)."""
    fleet = _fleet(
        {
            "big": {"roll_5h": 1000.0, "share_5h": 0.5, "spike_factor": 2.0},
            "med": {"roll_5h": 500.0, "share_5h": 0.25, "spike_factor": 1.2},
            "small": {"roll_5h": 100.0, "share_5h": 0.05, "spike_factor": 5.0},
        }
    )
    assert th.culprit(fleet) == "big"


def test_culprit_skips_failing_leader_to_next() -> None:
    """A bigger leader that fails the spike floor is skipped in favour of the next qualifier."""
    fleet = _fleet(
        {
            "a": {"roll_5h": 900.0, "share_5h": 0.6, "spike_factor": 1.0},  # fails spike
            "b": {"roll_5h": 400.0, "share_5h": 0.3, "spike_factor": 2.0},  # qualifies
        }
    )
    assert th.culprit(fleet) == "b"


def test_culprit_none_below_floors() -> None:
    """When nobody clears both floors, culprit is None."""
    fleet = _fleet(
        {
            "a": {"roll_5h": 900.0, "share_5h": 0.5, "spike_factor": 1.0},  # spike too low
            "b": {"roll_5h": 100.0, "share_5h": 0.05, "spike_factor": 9.0},  # share too low
        }
    )
    assert th.culprit(fleet) is None


def test_culprit_spike_none_passes() -> None:
    """A None spike_factor (no baseline yet) PASSES the spike gate — a big share alone flags it."""
    fleet = _fleet(
        {
            "new": {"roll_5h": 800.0, "share_5h": 0.4, "spike_factor": None},
            "old": {"roll_5h": 200.0, "share_5h": 0.1, "spike_factor": 3.0},
        }
    )
    assert th.culprit(fleet) == "new"
