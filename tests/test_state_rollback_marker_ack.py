"""Tests for state.rollback_marker_ack() — the janitor#257 fix, shared by both reload triggers.

A `[janitor-*]` marker that is emitted once per generation has its ack advanced at EMISSION time,
because dispatch cannot know whether the receiver actually did the thing. When the receiver
DECLINES (the user is at the keyboard), the signal is gone unless the ack is put back. These tests
pin the three properties that make the rollback safe: it restores the signal, it never invents an
ack that never existed, and it never raises — a refusal must not become a traceback.

`state_dir()` is lru_cache'd (read once per process, which in production is at first use), so each
test clears the cache to simulate a fresh process picking up CLAUDE_PROJECT_DIR at start.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def _clear() -> None:
    state.project_root.cache_clear()
    state.janitor_root.cache_clear()
    state.state_dir.cache_clear()
    state.log_dir.cache_clear()


def _project(tmp_path: Path, monkeypatch) -> Path:
    """A throwaway project whose .janitor/state the helper may write to."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    _clear()
    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    return sd


def test_rolls_an_existing_stamp_back_to_zero(tmp_path, monkeypatch) -> None:
    """0 (not the previous generation): 0 means "nothing acked", so ANY current generation
    compares as newer. A stored previous generation would hold only until the daemon bumped it."""
    sd = _project(tmp_path, monkeypatch)
    stamp = sd / "reload-acked.ts"
    stamp.write_text("1755000000\n", encoding="utf-8")
    try:
        assert state.rollback_marker_ack("reload-acked.ts", actor="t", why="test") is True
        assert stamp.read_text().strip() == "0"
    finally:
        _clear()


def test_absent_stamp_is_left_absent(tmp_path, monkeypatch) -> None:
    """Creating one would fabricate an ack that never happened — the same bug inverted."""
    sd = _project(tmp_path, monkeypatch)
    try:
        assert state.rollback_marker_ack("reload-acked.ts", actor="t", why="test") is False
        assert not (sd / "reload-acked.ts").exists()
    finally:
        _clear()


def test_unwritable_state_dir_reports_false_and_does_not_raise(tmp_path, monkeypatch) -> None:
    """The caller is DECLINING to type. If the disk says no, that must stay a decline, not a
    traceback — so the failure is reported by the return value, never by an exception."""
    sd = _project(tmp_path, monkeypatch)
    stamp = sd / "reload-acked.ts"
    stamp.write_text("1755000000\n", encoding="utf-8")
    original = sd.stat().st_mode
    sd.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x: the tmp file atomic_write needs cannot be created
    try:
        assert state.rollback_marker_ack("reload-acked.ts", actor="t", why="test") is False
    finally:
        sd.chmod(original)
        _clear()
