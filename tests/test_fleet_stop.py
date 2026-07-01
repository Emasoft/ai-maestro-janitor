"""Unit tests for the daemon-driven fleet disarm/pause POLICY (TRDD-ME8V2YJF).

Every decision in scripts/lib/fleet_stop.py is pure, so these run with no I/O, no
mocks, no processes — plain fixtures in, plans out. They pin the safety invariants:
default-off, never the guardian, never the user's live pane, dedupe per (pid, flag).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))
fleet_stop = importlib.import_module("fleet_stop")


def _sess(pid: int, command: str = "claude", terminal: dict | None = None) -> dict:
    return {"pid": pid, "command": command, "terminal": terminal or {"tmux_pane": "%1"}}


def test_enabled_default_off(monkeypatch) -> None:
    """fleet_stop_enabled is False unless the opt-in env var is a true spelling."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED", raising=False)
    assert fleet_stop.fleet_stop_enabled() is False


def test_enabled_true_spellings(monkeypatch) -> None:
    """fleet_stop_enabled accepts 1/true/yes/on and rejects other values."""
    for v in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED", v)
        assert fleet_stop.fleet_stop_enabled() is True
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED", v)
        assert fleet_stop.fleet_stop_enabled() is False


def test_stop_command_mapping() -> None:
    """stop_command_for maps disarm/pause to the local slash commands, else None."""
    assert fleet_stop.stop_command_for("disarm") == "/janitor-disarm"
    assert fleet_stop.stop_command_for("pause") == "/janitor-pause"
    assert fleet_stop.stop_command_for("bogus") is None
    assert fleet_stop.stop_command_for(None) is None
    assert fleet_stop.stop_command_for("") is None


def test_injection_stamp_key_stable() -> None:
    """injection_stamp_key is the stable 'pid:flag' dedupe key."""
    assert fleet_stop.injection_stamp_key(4321, "disarm") == "4321:disarm"
    assert fleet_stop.injection_stamp_key(4321, "pause") == "4321:pause"


def test_is_injectable_accepts_clean_other_session() -> None:
    """A real claude pid that is not self/daemon/user-active is injectable."""
    assert fleet_stop.is_injectable(
        pid=555, command="claude --dangerously", self_pid=1, daemon_pid=2, is_user_active=False
    )


def test_is_injectable_rejects_self_daemon_bad_pid() -> None:
    """Never inject into this process, the daemon, or a non-positive pid."""
    assert not fleet_stop.is_injectable(pid=1, command="claude", self_pid=1, daemon_pid=2, is_user_active=False)
    assert not fleet_stop.is_injectable(pid=2, command="claude", self_pid=1, daemon_pid=2, is_user_active=False)
    assert not fleet_stop.is_injectable(pid=0, command="claude", self_pid=1, daemon_pid=2, is_user_active=False)


def test_is_injectable_rejects_non_claude() -> None:
    """A pid whose command is not a claude process is never a target."""
    assert not fleet_stop.is_injectable(
        pid=999, command="python worker.py", self_pid=1, daemon_pid=2, is_user_active=False
    )


def test_is_injectable_rejects_user_active() -> None:
    """Never inject into the user's live interactive session (STATE invariant)."""
    assert not fleet_stop.is_injectable(
        pid=777, command="claude", self_pid=1, daemon_pid=2, is_user_active=True
    )


def test_select_targets_disarm_all_others() -> None:
    """select_stop_targets emits /janitor-disarm for every clean other session."""
    sessions = [_sess(10), _sess(11), _sess(12)]
    plans = fleet_stop.select_stop_targets(
        sessions, flag_state="disarm", self_pid=1, daemon_pid=2,
        already_injected=set(), user_active_pids=set(),
    )
    assert {p["pid"] for p in plans} == {10, 11, 12}
    assert all(p["command"] == "/janitor-disarm" for p in plans)
    assert all(p["dedupe_key"] == f"{p['pid']}:disarm" for p in plans)


def test_select_targets_pause_command() -> None:
    """A pause flag injects /janitor-pause, not /janitor-disarm."""
    plans = fleet_stop.select_stop_targets(
        [_sess(20)], flag_state="pause", self_pid=1, daemon_pid=2,
        already_injected=set(), user_active_pids=set(),
    )
    assert plans and plans[0]["command"] == "/janitor-pause"


def test_select_targets_dedupes_already_injected() -> None:
    """An already-stamped (pid, flag) is skipped so a held flag does not re-inject."""
    sessions = [_sess(30), _sess(31)]
    plans = fleet_stop.select_stop_targets(
        sessions, flag_state="disarm", self_pid=1, daemon_pid=2,
        already_injected={"30:disarm"}, user_active_pids=set(),
    )
    assert {p["pid"] for p in plans} == {31}


def test_select_targets_skips_user_and_guardian() -> None:
    """The user's active pane, this process, and the daemon are never targeted."""
    sessions = [_sess(1), _sess(2), _sess(40), _sess(41)]  # 1=self, 2=daemon
    plans = fleet_stop.select_stop_targets(
        sessions, flag_state="disarm", self_pid=1, daemon_pid=2,
        already_injected=set(), user_active_pids={40},
    )
    assert {p["pid"] for p in plans} == {41}


def test_select_targets_unknown_flag_is_empty() -> None:
    """An unknown/None flag state yields no injection plans."""
    sessions = [_sess(50)]
    assert fleet_stop.select_stop_targets(
        sessions, flag_state=None, self_pid=1, daemon_pid=2,
        already_injected=set(), user_active_pids=set(),
    ) == []
    assert fleet_stop.select_stop_targets(
        sessions, flag_state="bogus", self_pid=1, daemon_pid=2,
        already_injected=set(), user_active_pids=set(),
    ) == []
