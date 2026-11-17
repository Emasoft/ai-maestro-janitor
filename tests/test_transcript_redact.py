"""Real-bun tests of the fail-closed transcript redaction helper (TRDD-TKQ274RE increment A).

No mock of the redactor: every test runs the real `hooks/secret-shield/redact_bridge.ts` under real bun.
The fake credential is generated at call time by `_fake_secrets.secret` from a fragmented prefix, so no
contiguous credential literal sits in this file (see tests/test_secret_fixture_hygiene.py).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, cast

import pytest
import transcript_redact as tr
from _fake_secrets import secret

HOMES = ["/Users/runner"]
FAKE_KEY = secret("gh" + "p_", "tkq-inc-a", 36)
KEY_MARK = "[JANITOR-REDACTED:github-token]"
TIMEOUT_S = 120.0
# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun and the REAL bridge, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun")


def _record(n: int) -> str:
    """One transcript-shaped JSON line holding a fake key and a home path."""
    return json.dumps({"type": "user", "n": n, "message": {"content": f"token {FAKE_KEY} at /Users/runner/proj/file{n}.py"}})


def _write_transcript(path: Path, lines: list[str], *, final_newline: bool = True) -> None:
    path.write_bytes(("\n".join(lines) + ("\n" if final_newline else "")).encode("utf-8"))


def test_redact_texts_removes_secret_and_home_and_keeps_order() -> None:
    """Secret and home path are both removed; output order and length match the input."""
    texts = ["plain 0", f"key {FAKE_KEY} end", "home /Users/runner/a/b", "plain 3"]
    out = tr.redact_texts(texts, homes=HOMES, timeout_s=TIMEOUT_S)
    assert len(out) == len(texts)
    assert out[0] == "plain 0" and out[3] == "plain 3"
    assert FAKE_KEY not in out[1] and KEY_MARK in out[1]
    assert "runner" not in out[2] and "~/a/b" in out[2]


def test_redact_texts_empty_input_returns_empty_list() -> None:
    """No texts is a valid request and yields no texts."""
    assert tr.redact_texts([], homes=HOMES, timeout_s=TIMEOUT_S) == []


def test_copy_removes_secret_and_home_keeps_json_valid_and_line_count(tmp_path: Path) -> None:
    """The copy has no key and no home name, every JSON line still parses, and the line count is the same."""
    src = tmp_path / "s.jsonl"
    lines = [_record(i) for i in range(40)]
    _write_transcript(src, lines)
    dest = tr.redacted_transcript_copy(src, tmp_path / "out", timeout_s=TIMEOUT_S, homes=HOMES)
    assert dest == tmp_path / "out" / "s.jsonl"
    raw = dest.read_text(encoding="utf-8")
    assert FAKE_KEY not in raw and "runner" not in raw
    got = raw.split("\n")
    assert got[-1] == "" and len(got) - 1 == len(lines)
    for i, line in enumerate(got[:-1]):
        parsed = json.loads(line)
        assert parsed["n"] == i and KEY_MARK in parsed["message"]["content"] and "~/proj/file" in parsed["message"]["content"]


def test_copy_non_json_line_is_redacted_and_missing_final_newline_kept(tmp_path: Path) -> None:
    """A line that is not JSON is still redacted; a source with no final newline gets none."""
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0), f"not json {FAKE_KEY} /Users/runner/x"], final_newline=False)
    dest = tr.redacted_transcript_copy(src, tmp_path / "out", timeout_s=TIMEOUT_S, homes=HOMES)
    data = dest.read_bytes()
    assert not data.endswith(b"\n")
    assert b"runner" not in data and FAKE_KEY.encode() not in data
    assert len(data.split(b"\n")) == 2


def test_copy_is_mode_0600_and_leaves_no_temp_file(tmp_path: Path) -> None:
    """The copy is owner-only and only the copy and its sidecar remain in the destination."""
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0)])
    out_dir = tmp_path / "out"
    dest = tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert sorted(p.name for p in out_dir.iterdir()) == ["s.jsonl", "s.jsonl" + tr._SIDECAR_SUFFIX]


def test_unchanged_source_is_reused_without_a_new_write(tmp_path: Path) -> None:
    """A second call on an unchanged source returns the same file and does not rewrite it."""
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0), _record(1)])
    out_dir = tmp_path / "out"
    first = tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    before = (first.stat().st_mtime_ns, first.stat().st_ino)
    second = tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    assert second == first
    assert (second.stat().st_mtime_ns, second.stat().st_ino) == before


def test_changed_source_is_redacted_again(tmp_path: Path) -> None:
    """When the source size or mtime changes the copy is rebuilt from the new content."""
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0)])
    out_dir = tmp_path / "out"
    tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    _write_transcript(src, [_record(0), _record(1)])
    dest = tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    assert len(dest.read_text(encoding="utf-8").splitlines()) == 2


def test_different_homes_do_not_reuse_the_copy(tmp_path: Path) -> None:
    """A copy made for other home literals is not reused: it would leave this home visible."""
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0)])
    out_dir = tmp_path / "out"
    tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=["/Users/someoneelse"])
    dest = tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    assert "runner" not in dest.read_text(encoding="utf-8")


def test_unresolvable_bun_raises_and_writes_no_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With bun on neither PATH nor a fallback location, the copy raises and leaves nothing in the destination."""
    monkeypatch.setattr(tr.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(tr, "_BUN_FALLBACKS", (str(tmp_path / "no" / "bun"),))
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0)])
    out_dir = tmp_path / "out"
    with pytest.raises(tr.RedactionUnavailable):
        tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    assert not out_dir.exists()
    with pytest.raises(tr.RedactionUnavailable):
        tr.redact_texts(["x"], homes=HOMES, timeout_s=TIMEOUT_S)


def test_error_response_from_the_bridge_raises(tmp_path: Path) -> None:
    """A request the real bridge rejects (homes not strings) comes back as an error line and raises."""
    with pytest.raises(tr.RedactionUnavailable, match="reported an error"):
        tr.redact_texts(["x"], homes=cast(Any, [123]), timeout_s=TIMEOUT_S)
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0)])
    with pytest.raises(tr.RedactionUnavailable):
        tr.redacted_transcript_copy(src, tmp_path / "out", timeout_s=TIMEOUT_S, homes=cast(Any, [123]))
    assert not any((tmp_path / "out").iterdir())


def test_timeout_kills_the_bridge_and_raises() -> None:
    """A timeout far shorter than a bun start raises instead of returning a partial result."""
    with pytest.raises(tr.RedactionUnavailable, match="timed out"):
        tr.redact_texts(["x"] * 50, homes=HOMES, timeout_s=0.001)


def test_invalid_utf8_source_raises_and_leaves_no_destination_file(tmp_path: Path) -> None:
    """A source line that is not UTF-8 cannot be redacted faithfully: raise, and leave no copy and no temp file."""
    src = tmp_path / "s.jsonl"
    src.write_bytes(_record(0).encode("utf-8") + b"\n" + b"\xff\xfe bad\n")
    out_dir = tmp_path / "out"
    with pytest.raises(tr.RedactionUnavailable):
        tr.redacted_transcript_copy(src, out_dir, timeout_s=TIMEOUT_S, homes=HOMES)
    assert os.listdir(out_dir) == []


def test_bridge_that_exits_nonzero_silently_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bridge that exits nonzero with no error line still raises: the exit status alone fails closed."""
    (tmp_path / "exit1.ts").write_text("process.exit(1)\n", encoding="utf-8")
    monkeypatch.setattr(tr, "_BRIDGE", tmp_path / "exit1.ts")
    with pytest.raises(tr.RedactionUnavailable, match="exited with status"):
        tr.redact_texts(["x"], homes=HOMES, timeout_s=TIMEOUT_S)


def test_unwritable_destination_raises_redaction_unavailable(tmp_path: Path) -> None:
    """A destination that cannot be created raises RedactionUnavailable, never a bare OSError."""
    src = tmp_path / "s.jsonl"
    _write_transcript(src, [_record(0)])
    blocked = tmp_path / "out"
    blocked.write_bytes(b"a regular file where the destination directory should be\n")
    with pytest.raises(tr.RedactionUnavailable):
        tr.redacted_transcript_copy(src, blocked, timeout_s=TIMEOUT_S, homes=HOMES)
