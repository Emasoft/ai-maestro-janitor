"""Tests for the byte-safe tail walk `jsonl_walk.iter_jsonl_tail` (TRDD-A8DRRW0I stage A).

The module-level `build_*` functions are shared fixture builders: stage B imports them to prove
each transcript reader survives the same damaged tail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import jsonl_walk as jw  # noqa: E402

GOOD_LINES = [json.dumps({"type": "user", "n": i}).encode() for i in range(5)]


def build_plain_transcript(path: Path, lines: list[bytes] | None = None) -> bytes:
    """Write `lines` (default GOOD_LINES) newline-terminated; return the file's bytes."""
    data = b"\n".join(lines if lines is not None else GOOD_LINES) + b"\n"
    path.write_bytes(data)
    return data


def build_damaged_tail_transcript(path: Path) -> Path:
    """Transcript whose tail holds: a line with a raw 0xFF byte inside a JSON string, a
    non-object line, and a half-written last line with no trailing newline."""
    lines = [
        *GOOD_LINES,
        b'{"type": "assistant", "text": "bad \xff byte"}',
        b"[1, 2, 3]",
        b'{"type": "user", "text": "half writ',
    ]
    path.write_bytes(b"\n".join(lines))
    return path


def _walk(path: Path, tail_bytes: int) -> tuple[list[dict], list[int]]:
    malformed: list[int] = []
    return list(jw.iter_jsonl_tail(path, tail_bytes, malformed_lines=malformed)), malformed


def test_partial_first_line_dropped_and_not_counted(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    data = build_plain_transcript(p)
    # Start 5 bytes into the last line: the fragment must vanish silently.
    last_start = data.rstrip(b"\n").rfind(b"\n") + 1
    entries, malformed = _walk(p, len(data) - (last_start + 5))
    assert entries == []
    assert malformed == []


def test_tail_keeps_whole_lines_after_cut(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    data = build_plain_transcript(p)
    second_start = data.index(b"\n") + 1
    entries, malformed = _walk(p, len(data) - second_start - 3)  # cuts inside line 2
    assert [e["n"] for e in entries] == [2, 3, 4]
    assert malformed == []


def test_seek_on_line_boundary_drops_nothing(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    data = build_plain_transcript(p)
    second_start = data.index(b"\n") + 1
    entries, malformed = _walk(p, len(data) - second_start)
    assert [e["n"] for e in entries] == [1, 2, 3, 4]
    assert malformed == []


def test_damaged_tail_never_raises_and_counts_only_real_malformed(tmp_path: Path) -> None:
    p = build_damaged_tail_transcript(tmp_path / "t.jsonl")
    entries, malformed = _walk(p, 10_000)
    assert [e["type"] for e in entries[:5]] == ["user"] * 5
    assert "�" in entries[5]["text"]  # 0xFF line still yields, byte replaced
    assert len(entries) == 6
    assert malformed == [7, 8]  # non-object line and half-written last line, tail positions


def test_tail_larger_than_file_reads_from_byte_zero(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    build_plain_transcript(p)
    entries, malformed = _walk(p, 10_000_000)
    assert [e["n"] for e in entries] == [0, 1, 2, 3, 4]
    assert malformed == []


def test_missing_file_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        _walk(tmp_path / "absent.jsonl", 100)


def test_nonpositive_tail_bytes_rejected(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    build_plain_transcript(p)
    with pytest.raises(ValueError):
        _walk(p, 0)
