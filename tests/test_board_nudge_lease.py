"""LH84WTL5: only ONE session of a project root receives the zero-agent board nudge per change.

Two sessions sharing a root share the board, so both told "finish a card means pulling the next"
would work the same card in one tree. The nudge holds a per-project lease; it must expire when
its holder stops renewing it (session died or went stale), or the board would never wake anyone.
Real dispatch phase, real tmp project and state dir; no mocks.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

from test_dispatch_phases import (  # type: ignore[import-not-found]  # noqa: E402,F401
    _capture_stdout,
    _import_dispatch,
    _make_user_idle,
    _write_trdd,
    env_isolation,
)

_LEASE = "keep-going-board-nudge-lease.json"


def _fire(dispatch, monkeypatch, session: str | None) -> str:
    """One heartbeat of `session`: the zero-agent keep-going phase, stdout captured."""
    if session is None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    return _capture_stdout(dispatch._phase_keep_going_nudge)


def _setup(env_isolation: dict):  # noqa: F811 -- the imported fixture
    dispatch = _import_dispatch()
    import state

    state.init_state()
    _make_user_idle(state, ago_s=3700)
    _write_trdd(env_isolation["project"], "LEASE001", "dev")
    return dispatch, state


def test_second_session_is_quiet_while_the_first_holds_the_lease(
    env_isolation: dict, monkeypatch  # noqa: F811 -- the imported fixture
) -> None:
    """B's pane has a newer prompt epoch (re-arms the stamp), yet B is not nudged while A holds the lease."""
    dispatch, state = _setup(env_isolation)
    assert _fire(dispatch, monkeypatch, "sess-A").startswith("[janitor-resume]")
    _make_user_idle(state, ago_s=3000)  # B's pane typed more recently than A's: stamp would re-arm
    assert _fire(dispatch, monkeypatch, "sess-B") == ""


def test_holder_keeps_being_nudged_when_the_board_changes(
    env_isolation: dict, monkeypatch  # noqa: F811 -- the imported fixture
) -> None:
    """The lease holder is not locked out by its own lease: a card move re-nudges it."""
    dispatch, _ = _setup(env_isolation)
    assert _fire(dispatch, monkeypatch, "sess-A").startswith("[janitor-resume]")
    _write_trdd(env_isolation["project"], "LEASE002", "todo")
    assert _fire(dispatch, monkeypatch, "sess-A").startswith("[janitor-resume]")


def test_lease_expires_when_the_holder_stops_renewing_it(
    env_isolation: dict, monkeypatch  # noqa: F811 -- the imported fixture
) -> None:
    """A dead or stale holder cannot silence the board forever: past the TTL another session is nudged."""
    dispatch, state = _setup(env_isolation)
    assert _fire(dispatch, monkeypatch, "sess-A").startswith("[janitor-resume]")
    lease = state.state_dir() / _LEASE
    held = json.loads(lease.read_text(encoding="utf-8"))
    assert held["holder"] == "sess-A"
    held["epoch"] = int(time.time()) - dispatch._BOARD_NUDGE_LEASE_TTL_S - 1
    lease.write_text(json.dumps(held), encoding="utf-8")
    _make_user_idle(state, ago_s=3000)
    assert _fire(dispatch, monkeypatch, "sess-B").startswith("[janitor-resume]")
    assert json.loads(lease.read_text(encoding="utf-8"))["holder"] == "sess-B"


def test_unreadable_lease_fails_open_toward_nudging(
    env_isolation: dict, monkeypatch  # noqa: F811 -- the imported fixture
) -> None:
    """A corrupt lease file must never silence the pulse."""
    dispatch, state = _setup(env_isolation)
    (state.state_dir() / _LEASE).write_text("{not json", encoding="utf-8")
    assert _fire(dispatch, monkeypatch, "sess-A").startswith("[janitor-resume]")


def test_session_without_an_id_is_still_nudged(
    env_isolation: dict, monkeypatch  # noqa: F811 -- the imported fixture
) -> None:
    """No CLAUDE_CODE_SESSION_ID means no identity to lease against: fail open, nudge."""
    dispatch, _ = _setup(env_isolation)
    assert _fire(dispatch, monkeypatch, None).startswith("[janitor-resume]")
