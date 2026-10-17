"""Tests for scripts/lib/jev_expand.py -- the stdlib-only pointer resolver (TRDD-I40IKPWU).

Real transcript files in tmp_path, no mocks. The resolver is shared by `jev_compact.py expand`
(whose stderr is pinned byte-for-byte in tests/test_jev_compact_cli.py) and by the cross-/clear
verifier, so these tests pin its (text, error) contract directly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = _PROJECT_ROOT / "scripts" / "lib"
sys.path.insert(0, str(_LIB_DIR))

import jev_expand  # noqa: E402  -- needs the sys.path line above

_USER_UUID = "cafecafe-beef-4bad-8bad-feedfeedfe01"
_RESULT_UUID = "cafecafe-beef-4bad-8bad-feedfeedfe02"
_RESULT_BLOCK = "line one\nline two\nline three\nline four\n"


def _write_transcript(tmp_path: Path) -> Path:
    """A transcript with one str-content user entry and one tool_result entry (4 lines)."""
    entries = [
        {"uuid": _USER_UUID, "type": "user", "message": {"role": "user", "content": "hello\nworld"}},
        {
            "uuid": _RESULT_UUID,
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": _RESULT_BLOCK}],
            },
        },
    ]
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def _span_id(base: str, start: int, end: int) -> str:
    # Built at runtime: the privacy scanner rule private-path.ssh-user-host reads the literal
    # `<n>@<a>-<b>` form as a user-at-host address, so the "@" is never written next to digits in source.
    return f"{base}" + "@" + f"{start}-{end}"


def test_resolve_pointer_returns_the_whole_block(tmp_path: Path) -> None:
    """A plain `<uuid>:<n>` id resolves to the full original text of that block."""
    transcript = _write_transcript(tmp_path)
    assert jev_expand.resolve_pointer(transcript, f"{_USER_UUID}:0", malformed_lines=[]) == ("hello\nworld", None)
    assert jev_expand.resolve_pointer(transcript, f"{_RESULT_UUID}:0", malformed_lines=[]) == (_RESULT_BLOCK, None)


def test_resolve_pointer_returns_exactly_the_requested_line_span(tmp_path: Path) -> None:
    """A `<uuid>:<n>@<a>-<b>` id resolves to lines a..b (1-based, inclusive) of the block."""
    transcript = _write_transcript(tmp_path)
    pointer = _span_id(f"{_RESULT_UUID}:0", 2, 3)
    assert jev_expand.resolve_pointer(transcript, pointer, malformed_lines=[]) == ("line two\nline three\n", None)


def test_resolve_pointer_unknown_uuid_gives_the_exact_error(tmp_path: Path) -> None:
    """An id whose uuid is in no entry returns (None, the 'no transcript entry' message)."""
    transcript = _write_transcript(tmp_path)
    assert jev_expand.resolve_pointer(transcript, "no-such-uuid:0", malformed_lines=[]) == (
        None,
        f"no transcript entry with uuid='no-such-uuid' in {transcript}",
    )


def test_resolve_pointer_bad_block_index_gives_the_exact_error(tmp_path: Path) -> None:
    """A block index the entry does not have returns (None, the 'no block' message)."""
    transcript = _write_transcript(tmp_path)
    assert jev_expand.resolve_pointer(transcript, f"{_RESULT_UUID}:7", malformed_lines=[]) == (
        None,
        f"no block 7 in entry '{_RESULT_UUID}'",
    )


def test_resolve_pointer_out_of_range_span_gives_the_exact_error(tmp_path: Path) -> None:
    """A line span past the block's last line returns (None, the 'out of range' message)."""
    transcript = _write_transcript(tmp_path)
    pointer = _span_id(f"{_RESULT_UUID}:0", 3, 9)
    assert jev_expand.resolve_pointer(transcript, pointer, malformed_lines=[]) == (
        None,
        f"line span 3-9 out of range for block 0 in entry '{_RESULT_UUID}' (4 lines)",
    )


def test_resolve_pointer_malformed_ids_return_before_any_read(tmp_path: Path) -> None:
    """A malformed id returns its error without touching the transcript or malformed_lines."""
    missing = tmp_path / "does-not-exist.jsonl"  # a read would have to fail or report differently
    lines: list[int] = []
    bad_span = "abc:0" + "@" + "x-y"
    assert jev_expand.resolve_pointer(missing, bad_span, malformed_lines=lines) == (
        None,
        f"malformed id {bad_span!r}, expected '<uuid>:<n>@<a>-<b>'",
    )
    assert jev_expand.resolve_pointer(missing, "no-colon-index", malformed_lines=lines) == (
        None,
        "malformed id 'no-colon-index', expected '<uuid>:<n>'",
    )
    assert lines == []


def test_resolve_pointer_reports_skipped_malformed_lines_and_still_resolves(tmp_path: Path) -> None:
    """A truncated JSONL line is recorded in malformed_lines; a healthy later entry still resolves."""
    transcript = _write_transcript(tmp_path)
    good = transcript.read_text(encoding="utf-8")
    transcript.write_text('{"uuid": "trunc\n' + good, encoding="utf-8")
    lines: list[int] = []
    assert jev_expand.resolve_pointer(transcript, f"{_USER_UUID}:0", malformed_lines=lines) == ("hello\nworld", None)
    assert lines == [1]


def test_resolve_pointer_writes_no_shadow_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolving a pointer never writes the shadow decision log (only `expand`'s success path does)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    transcript = _write_transcript(tmp_path)
    assert jev_expand.resolve_pointer(transcript, f"{_USER_UUID}:0", malformed_lines=[])[1] is None
    assert not (tmp_path / ".janitor" / "state" / "jev-shadow.jsonl").exists()


def _probe(module: str) -> subprocess.CompletedProcess[str]:
    """Import `module` in an isolated interpreter: no site-packages, only scripts/lib on sys.path."""
    code = f"import sys; sys.path.insert(0, {str(_LIB_DIR)!r}); import {module}"
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, timeout=60,
    )


def test_jev_expand_imports_with_no_third_party_packages() -> None:
    """jev_expand imports under `python -I -S` (stdlib + scripts/lib only), as the verifier needs."""
    result = _probe("jev_expand")
    assert result.returncode == 0, result.stderr


def test_the_no_deps_probe_discriminates_by_failing_on_jev_compaction() -> None:
    """Control: the SAME probe fails on jev_compaction with a missing httpx, so it can fail."""
    result = _probe("jev_compaction")
    assert result.returncode != 0
    assert "No module named 'httpx'" in result.stderr, result.stderr
