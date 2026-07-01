"""Tests for the SessionStart re-arm guard (TRDD-RQ9FIFX6).

When a MACHINE-WIDE stop flag (/janitor-global-disarm kill-switch or /janitor-global-pause)
is set, the SessionStart hook must NOT nudge /janitor-arm — re-arming would re-create the very
heartbeat the user globally stopped (and each fire re-reads ~618k cached tokens). It prints an
enriched "globally DISARMED/PAUSED since <date> — reason: …" reminder instead (naming the duration
and reason so a forgotten temporary stop can't silently persist — TRDD-3MEUT9VW). With no flag set,
the normal arm nudge appears.

Isolation: $CLAUDE_PROJECT_DIR + $JANITOR_GLOBAL_STATE_DIR + $HOME all point at tmp dirs so no
real state is touched, and the two filesystem-writing best-effort steps (rules install + lean-ctx
allowlist self-heal) are neutralized so the test only exercises the guard.
"""

from __future__ import annotations

import importlib.util as _u
import sys
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


def _run_session_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, flag: str | None) -> str:
    """Run the SessionStart hook's main() under full isolation; return captured stdout."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))

    for mod in ("global_state", "state"):
        sys.modules.pop(mod, None)
    import global_state as gs

    gs.init_global_state()
    if flag == "disarm":
        gs.set_kill_switch("test")
    elif flag == "pause":
        gs.set_global_pause("test")

    # Neutralize the heavy best-effort filesystem side effects so the test only exercises the
    # guard (and never runs the real lean-ctx binary or copies real rule files).
    monkeypatch.setattr("lib.rules_installer.install_rules", lambda _root: [])
    monkeypatch.setattr("lib.leanctx_allowlist.ensure_janitor_allowed", lambda: [])

    spec = _u.spec_from_file_location(
        "janitor_on_session_start_under_test",
        str(_PROJECT_ROOT / "scripts" / "hooks" / "on-session-start.py"),
    )
    assert spec is not None and spec.loader is not None
    hook = _u.module_from_spec(spec)
    spec.loader.exec_module(hook)

    buf = StringIO()
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin = StringIO("")  # non-tty, empty → source defaults to "startup"
    sys.stdout = buf
    try:
        hook.main()
    finally:
        sys.stdin, sys.stdout = old_in, old_out
    return buf.getvalue()


def test_session_start_skips_rearm_when_globally_disarmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kill-switch set → NO /janitor-arm nudge; print the enriched globally-DISARMED reminder instead.

    The pre-RQ9FIFX6 bug: this hook nudged /janitor-arm unconditionally, so a disarmed machine
    re-armed a fresh ~618k-token-per-fire heartbeat on every new/resumed session. TRDD-3MEUT9VW then
    enriched the reminder to name the duration + reason so a forgotten stop can't silently persist.
    """
    out = _run_session_start(monkeypatch, tmp_path, flag="disarm")
    assert "globally DISARMED" in out, f"expected the enriched disarmed reminder, got {out!r}"
    assert 'reason: "test"' in out, "the reminder must name the reason so a forgotten stop can't persist"
    assert "/janitor-global-arm" in out, "the reminder must name the revive command"
    assert "run /janitor-arm to arm it" not in out, "must NOT nudge re-arm while globally disarmed"


def test_session_start_skips_rearm_when_globally_paused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """global-pause set → same: no arm nudge (keep the daemon, stop the project heartbeats)."""
    out = _run_session_start(monkeypatch, tmp_path, flag="pause")
    assert "globally PAUSED" in out, f"expected the enriched paused reminder, got {out!r}"
    assert "run /janitor-arm to arm it" not in out, "must NOT nudge re-arm while globally paused"


def test_session_start_nudges_rearm_when_not_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No stop flag → the normal 'run /janitor-arm' nudge IS printed (unchanged behavior)."""
    out = _run_session_start(monkeypatch, tmp_path, flag=None)
    assert "run /janitor-arm to arm it" in out, f"expected the arm nudge, got {out!r}"
    assert "globally DISARMED" not in out, "the disarmed reminder must not appear when armed"
    assert "globally PAUSED" not in out, "the paused reminder must not appear when armed"
