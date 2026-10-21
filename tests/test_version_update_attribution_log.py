"""Tests for the dedicated daemon-version-update.log sink (TRDD-R8DRK3DG)."""

from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
import dispatch  # type: ignore[import-not-found]  # noqa: E402
import state  # noqa: E402

_DAEMON_SRC = _PROJECT_ROOT / "scripts" / "daemon.py"


def _clear() -> None:
    state.project_root.cache_clear()
    state.janitor_root.cache_clear()
    state.state_dir.cache_clear()
    state.log_dir.cache_clear()


def _task_node() -> ast.FunctionDef:
    tree = ast.parse(_DAEMON_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "task_version_update":
            return node
    raise AssertionError("task_version_update not found")


def _is_call_to(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == name) or (
        isinstance(f, ast.Attribute) and f.attr == name
    )


def test_version_update_log_writes_dedicated_file_only(tmp_path, monkeypatch):
    """_version_update_log lands in daemon-version-update.log and never creates daemon.log."""
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path))
    _clear()
    try:
        daemon._version_update_log("x-marker")
        assert "x-marker" in (tmp_path / "daemon-version-update.log").read_text(encoding="utf-8")
        assert not (tmp_path / "daemon.log").exists()
    finally:
        _clear()


def test_exactly_one_daemon_log_pointer_call():
    """task_version_update keeps exactly one state.log_line('daemon', ...) call: the pointer."""
    calls = [
        n
        for n in ast.walk(_task_node())
        if _is_call_to(n, "log_line")
        and isinstance(n, ast.Call)
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == "daemon"
    ]
    assert len(calls) == 1
    msg = calls[0].args[1]
    if isinstance(msg, ast.JoinedStr):
        msg = msg.values[0]
    assert isinstance(msg, ast.Constant) and str(msg.value).startswith("version-update:")


def test_terminal_line_is_written_in_finally():
    """The terminal _version_update_log(_version_update_terminal(...)) call sits in a finally block."""
    found = False
    for node in ast.walk(_task_node()):
        if isinstance(node, ast.Try):
            for stmt in node.finalbody:
                for n in ast.walk(stmt):
                    if _is_call_to(n, "_version_update_log") and isinstance(n, ast.Call):
                        found |= any(_is_call_to(a, "_version_update_terminal") for a in n.args)
    assert found


def test_terminal_format_for_unresolved_values():
    """_version_update_terminal renders empty values as unknown/unresolved and updated=False."""
    line = daemon._version_update_terminal("ok", "", "", False)
    assert "installed=unknown" in line
    assert "published=unresolved" in line
    assert "updated=False" in line
    assert "outcome=ok" in line

def test_disabled_run_logs_outcome_in_both_logs(tmp_path, monkeypatch):
    """A run with auto-update disabled records outcome=disabled in the dedicated log and the pointer."""
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE", "false")
    _clear()
    try:
        daemon.task_version_update()
        dedicated = (tmp_path / "daemon-version-update.log").read_text(encoding="utf-8")
        assert "outcome=disabled" in dedicated
        pointer = (tmp_path / "daemon.log").read_text(encoding="utf-8")
        assert "version-update: called outcome=disabled" in pointer
    finally:
        _clear()


def test_sweep_exempts_attribution_logs(tmp_path):
    """The age sweep keeps version-update.log(.1) but still removes other old logs."""
    old = time.time() - 40 * 86400
    for name in ("version-update.log", "version-update.log.1", "other.log"):
        f = tmp_path / name
        f.write_text("x", encoding="utf-8")
        os.utime(f, (old, old))
    dispatch._sweep_old_files(
        tmp_path, (".log", ".log.1"), time.time() - 30 * 86400, dispatch._ATTRIBUTION_LOG_STEMS
    )
    assert (tmp_path / "version-update.log").exists()
    assert (tmp_path / "version-update.log.1").exists()
    assert not (tmp_path / "other.log").exists()
