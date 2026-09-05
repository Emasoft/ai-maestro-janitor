"""Yielded-host floor statement (TRDD-A70YJLXN, box 3 scope note).

When the server owns `version-update` and no janitor session has raised
`version-update-requested.flag` within one absorbed beat (4 h — the peer's own
absorbed-chore cadence), the daemon must SAY OUT LOUD that a newer release lands on
the peer's 4 h absorbed beat instead — the detector-side line (version-update.py
Branch A2) only fires inside an armed session, so a host where nobody has raised the
flag recently had no statement at all.

Predicate history (each corrected by review before landing):
1. Keying on the flag's mere presence false-positives every hour on a healthy armed
   host — the peer's consumer clears the flag within one poll, so "flag absent while
   yielded" is the NORMAL steady state between raises.
2. Keying on a fleet armed-instance count is a proxy too — `gather_fleet` enumerates
   only iTerm/tmux/ai-maestro panes, missing Terminal.app / headless `-p` / Claude
   Desktop sessions that can still raise the flag. Replaced with the never-consumed
   `version-update-last-raised.ts` stamp (`global_state.version_update_last_raised`),
   whose age survives the flag's own clear-within-one-poll lifecycle.
3. A plain "≥1 h since last logged" timer re-prints the SAME silence hourly forever
   on a permanently server-owned host — a metronome, exactly the noise the heartbeat
   contract forbids. Replaced with memory KEYED ON THE RAISE STAMP itself.
4. That memory was first a module variable — erased by a daemon restart, and the
   corpus records a crash-loop mode where the daemon restarts every heartbeat.
   Replaced with a PERSISTED sibling stamp `version-update-floor-logged-for.ts`
   (`global_state.version_update_floor_logged_for` /
   `set_version_update_floor_logged_for`) so a restart cannot repeat the line.

Real global-state I/O in an isolated tmp dir (isolated_env fixture pattern shared
with test_daemon_foreground_budget.py / test_chore_coordination.py). No mocking of
the code under test.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Iterator

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))
daemon = importlib.import_module("daemon")
state = importlib.import_module("state")
gs = importlib.import_module("global_state")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolated global state + log dir (same pattern as the sibling daemon tests)."""
    gsd = tmp_path / "global-state"
    gsd.mkdir()
    proj = tmp_path / "proj"
    (proj / ".janitor").mkdir(parents=True)
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()
    yield gsd
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()


def _log_text() -> str:
    log_path = state.log_dir() / "daemon.log"
    return log_path.read_text() if log_path.exists() else ""


# --- pure helper: _floor_statement_due ------------------------------------------

def test_floor_statement_due_never_raised_never_logged() -> None:
    """last_raised=None, no persisted stamp at all (logged_exists=False) -> due."""
    assert daemon._floor_statement_due(
        now=100.0, server_owns_chore=True, last_raised=None, logged_exists=False, logged_value=None
    )


def test_floor_statement_not_due_never_raised_already_logged_for_none() -> None:
    """last_raised=None, persisted stamp says "logged for none" -> not due (no repeat)."""
    assert not daemon._floor_statement_due(
        now=100.0, server_owns_chore=True, last_raised=None, logged_exists=True, logged_value=None
    )


def test_floor_statement_due_raised_five_hours_ago_never_logged_for_it() -> None:
    """Raised 5 h ago (stale, past the 4 h absorbed beat), persisted stamp is for a
    DIFFERENT (older) raise -> due."""
    now = 100000.0
    last_raised = int(now - 5 * 3600)
    assert daemon._floor_statement_due(
        now=now, server_owns_chore=True, last_raised=last_raised, logged_exists=True, logged_value=1
    )


def test_floor_statement_not_due_raised_five_hours_ago_already_logged_for_it() -> None:
    """Same stale raise, but the persisted stamp is for exactly that raise -> not due."""
    now = 100000.0
    last_raised = int(now - 5 * 3600)
    assert not daemon._floor_statement_due(
        now=now, server_owns_chore=True, last_raised=last_raised, logged_exists=True, logged_value=last_raised
    )


def test_floor_statement_not_due_raised_one_hour_ago() -> None:
    """Raised within the 4 h absorbed beat — still someone's watch, regardless of memory."""
    now = 100000.0
    assert not daemon._floor_statement_due(
        now=now, server_owns_chore=True, last_raised=int(now - 3600), logged_exists=False, logged_value=None
    )


def test_floor_statement_not_due_when_not_server_owned() -> None:
    """version-update isn't yielded to the server — this daemon runs it itself, nothing to say."""
    assert not daemon._floor_statement_due(
        now=100.0, server_owns_chore=False, last_raised=None, logged_exists=False, logged_value=None
    )


# --- global_state stamp writer/reader round-trips ---------------------------------

def test_version_update_last_raised_round_trips_through_request() -> None:
    assert gs.version_update_last_raised() is None
    before = int(time.time())
    gs.request_version_update("test")
    after = int(time.time())
    stamped = gs.version_update_last_raised()
    assert stamped is not None
    assert before <= stamped <= after


def test_version_update_floor_logged_for_round_trips() -> None:
    assert gs.version_update_floor_logged_for() == (False, None)
    gs.set_version_update_floor_logged_for(None)
    assert gs.version_update_floor_logged_for() == (True, None)
    gs.set_version_update_floor_logged_for(12345)
    assert gs.version_update_floor_logged_for() == (True, 12345)


def test_request_version_update_stamps_before_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stamp write failure must skip the flag write too — a flag with no stamp behind it
    is exactly the ambiguity the stamp exists to resolve."""

    def _boom(path: Path, value: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(state, "atomic_write", _boom)
    gs.request_version_update("test")
    assert gs.version_update_requested_present() is False


# --- loop-side wrapper: real global-state + log I/O -----------------------------

def test_maybe_log_floor_statement_writes_once_across_two_gate_evaluations() -> None:
    """The real loop-side function, called twice back-to-back (as two loop iterations
    would, with the flag never raised), logs exactly once — the second evaluation is
    suppressed by the persisted "logged for this exact silence" memory, not a timer."""
    assert daemon._maybe_log_version_update_floor_statement(server_owns_chore=True, now=100.0) is True
    assert daemon._maybe_log_version_update_floor_statement(server_owns_chore=True, now=100.5) is False
    text = _log_text()
    assert text.count("TRDD-A70YJLXN") == 1
    assert "no janitor session has raised version-update-requested.flag in the last 4 h" in text


def test_maybe_log_floor_statement_silent_when_recently_raised() -> None:
    """A flag raised within the last absorbed beat means someone is watching — silent."""
    gs.request_version_update("test")
    assert daemon._maybe_log_version_update_floor_statement(server_owns_chore=True, now=time.time()) is False
    assert _log_text() == ""
