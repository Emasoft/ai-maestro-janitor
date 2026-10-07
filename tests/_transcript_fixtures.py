"""Shared transcript fixture builders (TRDD-A8DRRW0I): stage B imports them to prove each
transcript reader survives the same damaged tail."""

from __future__ import annotations

import json
from pathlib import Path

GOOD_LINES = [json.dumps({"type": "user", "n": i}).encode() for i in range(5)]
MARKER_A = b'{"type":"assistant","text":"MARKER_A"}'
MARKER_B = b'{"type":"user","text":"MARKER_B"}'


def build_plain_transcript(path: Path, lines: list[bytes] | None = None) -> bytes:
    """Write `lines` (default GOOD_LINES) newline-terminated; return the file's bytes."""
    data = b"\n".join(lines if lines is not None else GOOD_LINES) + b"\n"
    path.write_bytes(data)
    return data


def build_damaged_tail_transcript(path: Path) -> Path:
    """Transcript: GOOD_LINES, MARKER_A, a line with a raw 0xFF byte inside a JSON string, a
    non-object line, MARKER_B, then a half-written last line with no trailing newline."""
    lines = [
        *GOOD_LINES,
        MARKER_A,
        b'{"type": "assistant", "text": "bad \xff byte"}',
        b"[1, 2, 3]",
        MARKER_B,
        b'{"type": "user", "text": "half writ',
    ]
    path.write_bytes(b"\n".join(lines))
    return path
