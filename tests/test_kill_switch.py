"""Tests for the machine-wide janitor STOP (TRDD-56d24c02 follow-up).

The kill-switch flag is what /janitor-stop sets and /janitor-arm clears; the daemon
and ensure_daemon_running both already honor it (verified elsewhere), so these tests
cover the write/clear primitives + the backing CLI against an isolated state dir —
no real daemon, no real ~/.claude.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import global_state as gs  # type: ignore[import-not-found]  # noqa: E402
import kill_switch_cli  # type: ignore[import-not-found]  # noqa: E402


def test_set_and_clear_kill_switch(tmp_path, monkeypatch) -> None:
    """set creates the flag (with the reason), clear removes it, and clear is
    idempotent — the STOP/revive primitives the daemon already obeys."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    assert gs.kill_switch_present() is False
    gs.set_kill_switch("stopped via test")
    assert gs.kill_switch_present() is True
    assert (tmp_path / "kill-switch.flag").read_text(encoding="utf-8") == "stopped via test"
    gs.clear_kill_switch()
    assert gs.kill_switch_present() is False
    gs.clear_kill_switch()                       # idempotent — no flag is fine


def test_set_kill_switch_default_reason(tmp_path, monkeypatch) -> None:
    """An empty reason still writes a non-empty marker so the flag file is never blank."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    gs.set_kill_switch()
    assert (tmp_path / "kill-switch.flag").read_text(encoding="utf-8") == "stopped"


def test_cli_set_status_clear_roundtrip(tmp_path, monkeypatch, capsys) -> None:
    """The backing CLI drives the same primitives: set → STOPPED, clear → RUNNING."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))

    monkeypatch.setattr(kill_switch_cli.sys, "argv", ["x", "set", "because reasons"])
    assert kill_switch_cli.main() == 0
    assert gs.kill_switch_present() is True

    monkeypatch.setattr(kill_switch_cli.sys, "argv", ["x", "status"])
    assert kill_switch_cli.main() == 0
    assert "STOPPED" in capsys.readouterr().out

    monkeypatch.setattr(kill_switch_cli.sys, "argv", ["x", "clear"])
    assert kill_switch_cli.main() == 0
    assert gs.kill_switch_present() is False

    monkeypatch.setattr(kill_switch_cli.sys, "argv", ["x", "status"])
    kill_switch_cli.main()
    assert "RUNNING" in capsys.readouterr().out


def test_cli_default_command_is_status(tmp_path, monkeypatch, capsys) -> None:
    """No argument → status (a safe read-only default, never an accidental stop)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(kill_switch_cli.sys, "argv", ["x"])
    assert kill_switch_cli.main() == 0
    assert "RUNNING" in capsys.readouterr().out
    assert gs.kill_switch_present() is False      # status never wrote anything
