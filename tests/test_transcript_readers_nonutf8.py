"""Tests for the byte-safe tail read `jsonl_walk.read_jsonl_tail` (TRDD-A8DRRW0I).

The fixture builders live in `_transcript_fixtures`: stage B imports them to prove each
transcript reader survives the same damaged tail.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import jsonl_walk as jw  # noqa: E402
from _transcript_fixtures import build_damaged_tail_transcript, build_plain_transcript  # noqa: E402


def _walk(path: Path, tail_bytes: int) -> tuple[list[dict], list[int]]:
    malformed: list[int] = []
    return jw.read_jsonl_tail(path, tail_bytes, malformed_lines=malformed), malformed


def test_partial_first_line_dropped_and_not_counted(tmp_path: Path) -> None:
    """A seek landing mid-line drops the cut fragment without counting it as malformed."""
    p = tmp_path / "t.jsonl"
    data = build_plain_transcript(p)
    # Start 5 bytes into the last line: the fragment must vanish silently.
    last_start = data.rstrip(b"\n").rfind(b"\n") + 1
    entries, malformed = _walk(p, len(data) - (last_start + 5))
    assert entries == []
    assert malformed == []


def test_tail_keeps_whole_lines_after_cut(tmp_path: Path) -> None:
    """After a mid-line cut, every following whole line is returned."""
    p = tmp_path / "t.jsonl"
    data = build_plain_transcript(p)
    second_start = data.index(b"\n") + 1
    entries, malformed = _walk(p, len(data) - second_start - 3)  # cuts inside line 2
    assert [e["n"] for e in entries] == [2, 3, 4]
    assert malformed == []


def test_seek_on_line_boundary_drops_nothing(tmp_path: Path) -> None:
    """A seek landing exactly on a line boundary keeps that whole line."""
    p = tmp_path / "t.jsonl"
    data = build_plain_transcript(p)
    second_start = data.index(b"\n") + 1
    entries, malformed = _walk(p, len(data) - second_start)
    assert [e["n"] for e in entries] == [1, 2, 3, 4]
    assert malformed == []


def test_damaged_tail_never_raises_and_counts_only_real_malformed(tmp_path: Path) -> None:
    """0xFF byte, non-object line and half-written last line never raise; positions are exact."""
    p = build_damaged_tail_transcript(tmp_path / "t.jsonl")
    entries, malformed = _walk(p, 10_000)
    assert len(entries) == 8
    assert "�" in entries[6]["text"]  # 0xFF line still yields, byte replaced
    assert malformed == [8, 10]  # non-object line and half-written last line, tail positions


def test_damaged_tail_keeps_both_markers(tmp_path: Path) -> None:
    """Good lines on both sides of the damaged ones all survive."""
    p = build_damaged_tail_transcript(tmp_path / "t.jsonl")
    entries, _ = _walk(p, 10_000)
    texts = [e.get("text") for e in entries]
    assert "MARKER_A" in texts
    assert "MARKER_B" in texts


def test_tail_larger_than_file_reads_from_byte_zero(tmp_path: Path) -> None:
    """A window bigger than the file reads every line from byte 0."""
    p = tmp_path / "t.jsonl"
    build_plain_transcript(p)
    entries, malformed = _walk(p, 10_000_000)
    assert [e["n"] for e in entries] == [0, 1, 2, 3, 4]
    assert malformed == []


def test_missing_file_raises_oserror_at_the_call(tmp_path: Path) -> None:
    """The error surfaces at the call itself, with no iteration needed."""
    with pytest.raises(OSError):
        jw.read_jsonl_tail(tmp_path / "absent.jsonl", 100, malformed_lines=[])


def test_nonpositive_tail_bytes_rejected(tmp_path: Path) -> None:
    """tail_bytes < 1 raises ValueError at the call."""
    p = tmp_path / "t.jsonl"
    build_plain_transcript(p)
    with pytest.raises(ValueError):
        _walk(p, 0)


def test_tail_without_any_newline_returns_empty(tmp_path: Path) -> None:
    """One record longer than the window: nothing returned, nothing recorded."""
    p = tmp_path / "t.jsonl"
    p.write_bytes(b'{"type": "user", "text": "' + b"x" * 200 + b'"}')
    entries, malformed = _walk(p, 50)
    assert entries == []
    assert malformed == []


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    """An empty file yields no entries and no malformed lines."""
    p = tmp_path / "t.jsonl"
    p.write_bytes(b"")
    entries, malformed = _walk(p, 100)
    assert entries == []
    assert malformed == []
