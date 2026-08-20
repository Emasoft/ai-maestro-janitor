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


def _run_session_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, flag: str | None, source: str | None = None
) -> str:
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
    elif flag == "stale-pause":
        # The RETIRED global-pause flag, written raw: no setter exists any more.
        cd = gs.control_dir()
        cd.mkdir(parents=True, exist_ok=True)
        (cd / "global-pause.flag").write_text('{"reason": "test"}', encoding="utf-8")
    elif flag == "armed":
        gs.record_armed("arm")

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
    if source is None:
        sys.stdin = StringIO("")  # non-tty, empty → source defaults to "startup"
    else:
        sys.stdin = StringIO(f'{{"source": "{source}"}}')
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
    assert "[janitor] armed (persistent)" not in out, "must NOT re-plumb silently while globally disarmed"


def test_session_start_ignores_a_stale_pause_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A STALE retired pause flag must NOT suppress the arm nudge.

    Pause is gone (owner directive 2026-07-31). A host that was paused under an older janitor
    still has the flag on disk, and if SessionStart kept honoring it that machine would never be
    nudged to arm again — silently unarmed forever, which is the failure this whole change is
    about.
    """
    out = _run_session_start(monkeypatch, tmp_path, flag="stale-pause")
    assert "globally PAUSED" not in out, f"the retired flag was still reported as a stop: {out!r}"
    assert "run /janitor-arm to arm it" in out, f"the arm nudge must still fire: {out!r}"


def test_session_start_nudges_rearm_when_not_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No stop flag, never armed → "absent" → the normal 'run /janitor-arm' nudge (unchanged)."""
    out = _run_session_start(monkeypatch, tmp_path, flag=None)
    assert "run /janitor-arm to arm it" in out, f"expected the arm nudge, got {out!r}"
    assert "globally DISARMED" not in out, "the disarmed reminder must not appear when armed"
    assert "globally PAUSED" not in out, "the paused reminder must not appear when armed"


def test_session_start_replumbs_silently_when_persistently_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TRDD-TUIBWHT7: once `armed.flag` is recorded, SessionStart re-plumbs the session's cron
    with a terse machine line instead of the old user-facing nag banner."""
    out = _run_session_start(monkeypatch, tmp_path, flag="armed")
    assert "run /janitor-arm to arm it" not in out, f"the nag banner must not appear once armed, got {out!r}"
    assert "[janitor] armed (persistent)" in out, f"expected the silent re-plumb line, got {out!r}"
    assert "globally DISARMED" not in out
    assert "globally PAUSED" not in out


def test_session_start_replumbs_on_startup_when_armed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """source="startup" + armed → the re-plumb nudge fires (a genuinely fresh process)."""
    out = _run_session_start(monkeypatch, tmp_path, flag="armed", source="startup")
    assert "re-plumbing" in out, f"expected the re-plumb nudge on startup, got {out!r}"


def test_session_start_replumbs_on_resume_when_armed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """source="resume" + armed → the re-plumb nudge fires (a genuinely fresh process)."""
    out = _run_session_start(monkeypatch, tmp_path, flag="armed", source="resume")
    assert "re-plumbing" in out, f"expected the re-plumb nudge on resume, got {out!r}"


def test_session_start_skips_replumb_on_compact_when_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """source="compact" + armed → NO re-plumb nudge (same process, live cron survives)."""
    out = _run_session_start(monkeypatch, tmp_path, flag="armed", source="compact")
    assert "re-plumbing" not in out, f"must not re-plumb mid-session on compact, got {out!r}"


def test_session_start_skips_replumb_on_clear_when_armed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """source="clear" + armed → NO re-plumb nudge (same process, live cron survives)."""
    out = _run_session_start(monkeypatch, tmp_path, flag="armed", source="clear")
    assert "re-plumbing" not in out, f"must not re-plumb mid-session on clear, got {out!r}"


def test_replumb_line_never_reads_as_a_user_chore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The re-plumb line is rendered to the USER, so it must say no action is required and must
    NOT carry a slash-command imperative the user's eye reads as an instruction to type."""
    out = _run_session_start(monkeypatch, tmp_path, flag="armed", source="startup")
    assert "NO USER ACTION REQUIRED" in out, f"the user must be told nothing is asked of them, got {out!r}"
    assert "/janitor-arm" not in out, f"a slash command in a user-visible line reads as a chore, got {out!r}"
