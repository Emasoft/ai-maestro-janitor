"""SessionStart disarmed-state reminder — the rich reminder that makes a forgotten
temporary /janitor-global-disarm impossible to miss on the NEXT session start.

Background: a temporary global-disarm (for a token-burn fix) was never re-armed and
went unnoticed for ~33 h because the old reminder was a bare "the janitor is stopped"
line carrying neither the DURATION nor the REASON. These tests pin the two pure helpers
that build the enriched reminder. Real global-state I/O in an isolated JANITOR_GLOBAL_STATE_DIR
(never touches the live daemon state).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
# Both roots, flat-import style (the janitor test convention): scripts/lib so
# global_state's own `import state` resolves, scripts so `from lib import ...` also works.
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))


def _load_hook():
    """Import the hyphenated hook script as a module (its main() is NOT run on import)."""
    spec = importlib.util.spec_from_file_location(
        "on_session_start_hook", _ROOT / "scripts" / "hooks" / "on-session-start.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_active_global_stop_reads_disarm_flag(monkeypatch, tmp_path) -> None:
    """A set kill-switch.flag is reported as (DISARMED, its reason, its mtime)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — isolate it too, or every test in this
    # file would share the real process's $HOME/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    gs = importlib.import_module("global_state")
    gs.set_kill_switch("token burn test")
    hook = _load_hook()
    result = hook._active_global_stop(gs)
    assert result is not None
    kind, reason, since = result
    assert kind == "DISARMED"
    assert reason == "token burn test"
    assert since > 0


def test_active_global_stop_none_when_running(monkeypatch, tmp_path) -> None:
    """No stop flag → None (the running state; the reminder is not shown)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — isolate it too, or every test in this
    # file would share the real process's $HOME/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    gs = importlib.import_module("global_state")
    hook = _load_hook()
    assert hook._active_global_stop(gs) is None


def test_active_global_stop_ignores_a_stale_pause_flag(monkeypatch, tmp_path) -> None:
    """A stale retired pause flag must not be reported as an active stop; only the kill-switch is."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — isolate it too, or every test in this
    # file would share the real process's $HOME/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    gs = importlib.import_module("global_state")
    cd = gs.control_dir()
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "global-pause.flag").write_text('{"reason": "pause reason"}', encoding="utf-8")
    gs.set_kill_switch("disarm reason")
    hook = _load_hook()
    result = hook._active_global_stop(gs)
    assert result is not None
    kind, reason, _ = result
    assert kind == "DISARMED"
    assert reason == "disarm reason"


def test_format_reminder_includes_duration_and_reason() -> None:
    """The reminder names the duration (days+hours) AND the reason — the two facts the
    old bare line lacked, which is why a stop could be forgotten for 33 h."""
    hook = _load_hook()
    now = 1_000_000_000
    since = now - (2 * 86400 + 3 * 3600)  # 2 days 3 hours ago
    msg = hook._format_stop_reminder("DISARMED", "token burn", since, now)
    assert "DISARMED" in msg
    assert "2d 3h ago" in msg
    assert 'reason: "token burn"' in msg
    assert "/janitor-global-arm" in msg


def test_format_reminder_hours_only_and_empty_reason_omitted() -> None:
    """Under a day shows hours-only (no 'Nd'); an empty reason is omitted cleanly."""
    hook = _load_hook()
    now = 1_000_000_000
    since = now - (5 * 3600)  # 5 hours ago
    msg = hook._format_stop_reminder("PAUSED", "", since, now)
    assert "(5h ago)" in msg
    assert "0d" not in msg
    assert "reason:" not in msg
    assert "PAUSED" in msg


def test_format_reminder_no_timestamp_when_since_zero() -> None:
    """A missing/zero mtime degrades gracefully — no 'since' clause, still actionable."""
    hook = _load_hook()
    msg = hook._format_stop_reminder("DISARMED", "why", 0, 1_000_000_000)
    assert "since" not in msg
    assert 'reason: "why"' in msg
    assert "/janitor-global-arm" in msg
