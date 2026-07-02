"""Regression tests for the message.id dedupe in token_history (TRDD-OY0W6LX5).

One streamed API response is written to the transcript as SEVERAL `type:assistant`
jsonl lines (one per content block), each repeating the same `message.id` and the
same full `usage`. Summing every line over-counted attribution 1.5-2.1x on real
projects (measured 2026-07-02; the user caught the inflated numbers). These tests
pin the dedupe: one message id = one counted event, across lines AND across files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import token_history as th  # noqa: E402

TS = "2026-07-02T10:00:00Z"
TS_EPOCH = th.parse_ts(TS)
assert TS_EPOCH is not None
SINCE = TS_EPOCH - 3600
NOW = TS_EPOCH + 3600


def _assistant_line(mid: str | None, output: int = 100) -> str:
    """One type:assistant transcript line with a fixed-usage message."""
    msg: dict = {
        "usage": {
            "input_tokens": 10,
            "output_tokens": output,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "content": [{"type": "text", "text": "x"}],
    }
    if mid is not None:
        msg["id"] = mid
    return json.dumps({"type": "assistant", "timestamp": TS, "message": msg})


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_scan_transcript_dedupes_repeated_message_id(tmp_path: Path) -> None:
    """Three content-block lines of ONE message count once; a distinct id counts too."""
    f = tmp_path / "s.jsonl"
    _write(f, [_assistant_line("msg_a")] * 3 + [_assistant_line("msg_b")])
    events = th.scan_transcript(f, SINCE, set())
    assert len(events) == 2


def test_scan_transcript_without_seen_set_keeps_legacy_behavior(tmp_path: Path) -> None:
    """No seen_ids passed -> no dedupe (explicit opt-in keeps the function pure-ish)."""
    f = tmp_path / "s.jsonl"
    _write(f, [_assistant_line("msg_a")] * 3)
    assert len(th.scan_transcript(f, SINCE)) == 3


def test_scan_transcript_keeps_idless_lines(tmp_path: Path) -> None:
    """Malformed id-less lines are kept (counted once each) — never silently dropped."""
    f = tmp_path / "s.jsonl"
    _write(f, [_assistant_line(None), _assistant_line(None)])
    assert len(th.scan_transcript(f, SINCE, set())) == 2


def test_scan_project_dedupes_across_files(tmp_path: Path) -> None:
    """A resume/replay copy of the same message in a SECOND file counts once project-wide."""
    _write(tmp_path / "a.jsonl", [_assistant_line("msg_a"), _assistant_line("msg_b")])
    _write(tmp_path / "b.jsonl", [_assistant_line("msg_a"), _assistant_line("msg_c")])
    events = th.scan_project(tmp_path, SINCE)
    assert len(events) == 3
    total = th._window_sum(events, SINCE, NOW)
    assert total == pytest.approx(3 * 110.0)


def test_out_of_window_line_does_not_shadow_future_duplicate(tmp_path: Path) -> None:
    """A rejected (pre-window) first line must not mark its id as seen."""
    old = json.dumps(
        {
            "type": "assistant",
            "timestamp": "2026-07-01T00:00:00Z",
            "message": {
                "id": "msg_a",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "content": [],
            },
        }
    )
    f = tmp_path / "s.jsonl"
    _write(f, [old, _assistant_line("msg_a")])
    events = th.scan_transcript(f, SINCE, set())
    assert len(events) == 1 and events[0].output == 100
