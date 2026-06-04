"""Tests for state.log_dir()'s JANITOR_LOG_DIR override (issue #9, round 2).

The global daemon pins its log to the deterministic global-state dir by
exporting JANITOR_LOG_DIR before its first log_line(); per-session detectors
leave it unset and keep their project-scoped logs. log_dir() is lru_cache'd
(read once per process at first call, which in production is right after the
daemon sets the env), so each test clears the cache to simulate a fresh
process picking up the env at start.
"""

from __future__ import annotations

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


def test_log_dir_honors_override(tmp_path, monkeypatch):
    """JANITOR_LOG_DIR set → log_dir() returns it verbatim."""
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "global-logs"))
    _clear()
    try:
        assert state.log_dir() == tmp_path / "global-logs"
    finally:
        _clear()


def test_log_dir_falls_back_to_project(tmp_path, monkeypatch):
    """JANITOR_LOG_DIR unset → log_dir() = <project>/.janitor/logs."""
    monkeypatch.delenv("JANITOR_LOG_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    _clear()
    try:
        assert state.log_dir() == tmp_path / ".janitor" / "logs"
    finally:
        _clear()


def test_log_line_writes_to_override_not_project(tmp_path, monkeypatch):
    """log_line() appends under the override dir, not the project tree — the
    mechanism the daemon relies on to land daemon.log in global state instead
    of scattering it into whatever project happened to spawn it (issue #9)."""
    logs = tmp_path / "gl"
    proj = tmp_path / "proj"
    monkeypatch.setenv("JANITOR_LOG_DIR", str(logs))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    _clear()
    try:
        state.log_line("daemon", "hello from the daemon")
        target = logs / "daemon.log"
        assert target.is_file()
        assert "hello from the daemon" in target.read_text(encoding="utf-8")
        # It did NOT write into the project tree's logs/.
        assert not (proj / ".janitor" / "logs" / "daemon.log").exists()
    finally:
        _clear()
