"""Tests for the machine-wide janitor control flags (TRDD-a3fa4d5d).

Two distinct global flags, each with its own semantics:
  * the kill-switch (DISARM) — daemon exits AND every heartbeat goes silent. The
    daemon + ensure_daemon_running + dispatch.py Phase 0 all honor it (TRDD-NJ22HNC3).
    The `disarm` CLI raises the kill-switch AND the pause flag (so already-cached
    heartbeats silence immediately); `arm` clears both.
  * the global-pause flag (PAUSE) — daemon idles but stays alive, heartbeats silent;
    set ALONE by /janitor-global-pause, cleared by /janitor-global-unpause.

These cover the global_state primitives + the global_control_cli surface against an
isolated state dir (no real daemon, no real ~/.claude). The daemon-idle and
dispatch-no-op WIRING is covered by test_daemon.py / the dispatch tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import global_control_cli as cli  # type: ignore[import-not-found]  # noqa: E402
import global_state as gs  # type: ignore[import-not-found]  # noqa: E402

# ---------- DISARM (kill-switch) ----------

def test_disarm_set_and_clear(tmp_path, monkeypatch) -> None:
    """set creates the kill-switch (with the reason), clear removes it, clear is
    idempotent — the DISARM/revive primitives the daemon already obeys."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    assert gs.kill_switch_present() is False
    gs.set_kill_switch("disarmed via test")
    assert gs.kill_switch_present() is True
    assert (tmp_path / "kill-switch.flag").read_text(encoding="utf-8") == "disarmed via test"
    gs.clear_kill_switch()
    assert gs.kill_switch_present() is False
    gs.clear_kill_switch()                       # idempotent


def test_set_kill_switch_default_reason(tmp_path, monkeypatch) -> None:
    """An empty reason still writes a non-empty marker so the flag file is never blank."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    gs.set_kill_switch()
    assert (tmp_path / "kill-switch.flag").read_text(encoding="utf-8") == "stopped"


# ---------- PAUSE (global-pause flag) ----------

def test_global_pause_set_and_clear(tmp_path, monkeypatch) -> None:
    """set creates the global-pause flag, clear removes it, clear is idempotent — and
    it is a DIFFERENT file from the kill-switch (disarm ≠ pause)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    assert gs.global_pause_present() is False
    gs.set_global_pause("paused via test")
    assert gs.global_pause_present() is True
    assert (tmp_path / "global-pause.flag").read_text(encoding="utf-8") == "paused via test"
    assert gs.kill_switch_present() is False     # pause does NOT set the disarm flag
    gs.clear_global_pause()
    assert gs.global_pause_present() is False
    gs.clear_global_pause()                       # idempotent


def test_disarm_and_pause_are_independent(tmp_path, monkeypatch) -> None:
    """The two flags are orthogonal — clearing one never clears the other."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    gs.set_kill_switch()
    gs.set_global_pause()
    assert gs.kill_switch_present() and gs.global_pause_present()
    gs.clear_global_pause()
    assert gs.kill_switch_present() is True and gs.global_pause_present() is False


# ---------- the global_control_cli surface ----------

def test_cli_disarm_arm_roundtrip(tmp_path, monkeypatch, capsys) -> None:
    """DISARM is the TRUE STOP: it raises BOTH the kill-switch AND the global-pause flag
    so per-session heartbeats go silent IMMEDIATELY — even one running a pre-fix cached
    dispatch.py that honors only global-pause (TRDD-NJ22HNC3). ARM clears BOTH (full
    revive)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x", "disarm", "because"])
    assert cli.main() == 0
    assert gs.kill_switch_present() is True
    assert gs.global_pause_present() is True, \
        "disarm must ALSO raise the pause flag so already-cached heartbeats go silent now"
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "DISARMED" in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, "argv", ["x", "arm"])
    assert cli.main() == 0
    assert gs.kill_switch_present() is False
    assert gs.global_pause_present() is False, "arm must clear BOTH flags (full revive)"


def test_cli_pause_does_not_disarm(tmp_path, monkeypatch) -> None:
    """PAUSE stays pause-only — it raises ONLY the global-pause flag, never the
    kill-switch. (Disarm is the superset that raises both; pause is the soft idle.)"""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x", "pause", "soft idle"])
    assert cli.main() == 0
    assert gs.global_pause_present() is True
    assert gs.kill_switch_present() is False, "pause must NOT set the kill-switch"


def test_cli_reload_skills_stamps_only_its_own_flag(tmp_path, monkeypatch, capsys) -> None:
    """`reload-skills` stamps ONLY the standalone-skills reload generation — NOT the
    kill-switch, NOT the pause flag. Status stays RUNNING (it is a one-time reload
    request, not a stop-state)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    assert gs.skills_reload_flag_present() is False
    monkeypatch.setattr(cli.sys, "argv", ["x", "reload-skills", "installed skill-x"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "reload-skills requested" in out
    assert gs.skills_reload_flag_present() is True
    body = (tmp_path / "skills-reload-needed.flag").read_text(encoding="utf-8")
    assert body.partition("\t")[2] == "installed skill-x"
    # It is NOT a stop: neither the kill-switch nor the pause flag is raised.
    assert gs.kill_switch_present() is False and gs.global_pause_present() is False
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "RUNNING" in capsys.readouterr().out


def test_cli_pause_unpause_roundtrip(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x", "pause"])
    assert cli.main() == 0
    assert gs.global_pause_present() is True
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "PAUSED" in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, "argv", ["x", "unpause"])
    assert cli.main() == 0
    assert gs.global_pause_present() is False


def test_cli_status_precedence_disarm_over_pause(tmp_path, monkeypatch, capsys) -> None:
    """When BOTH flags are set, status reports DISARMED (the stronger state) — a
    disarmed daemon is stopped, so 'paused' would be misleading."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    gs.set_kill_switch()
    gs.set_global_pause()
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "DISARMED" in capsys.readouterr().out


def test_cli_default_command_is_status(tmp_path, monkeypatch, capsys) -> None:
    """No argument → status (a safe read-only default, never an accidental disarm/pause)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x"])
    assert cli.main() == 0
    assert "RUNNING" in capsys.readouterr().out
    assert gs.kill_switch_present() is False and gs.global_pause_present() is False
