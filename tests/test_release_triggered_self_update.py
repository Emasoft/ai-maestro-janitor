"""Release-triggered janitor self-update (TRDD-Y9KM5RCJ) — the three pieces, real, no mocks.

A new janitor release used to sit in the plugin cache for up to 6 h (the daemon's
`version-update` beat) even though the per-session detector notices it ~5 min after the
release lands — the exact "v0.41.0 sat at 0.39.0 for hours" symptom. The fix keeps the
single-writer invariant (issue #7 / PRRD S2.1 — only the daemon runs `claude plugin
update`): the detector RAISES a global request flag; the daemon CONSUMES it on its next
loop (<= ~60 s) and runs the version-update task NOW.

Three units under test, all pure/deterministic:
  * `global_state.{request,version_update_requested_present,clear}_version_update...`
    — the request-flag trio, isolated via JANITOR_GLOBAL_STATE_DIR.
  * `version_update_lib.should_request_prompt_update` — the detector's pure decision.
  * `daemon._consume_version_update_request` — the daemon's clear-before-run consume,
    driven with REAL `daemon.Task` spy objects (no subprocess / network) exactly as
    `_build_tasks()` would hand it in production, mirroring
    tests/test_daemon_maintenance_keepalive.py.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")
vu = importlib.import_module("version_update_lib")


@pytest.fixture(autouse=True)
def _isolate_janitor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every janitor global-state / DATA / HOME path to a per-test tmp tree so no
    test reads or writes the real ~/.claude/janitor-global-state/ or the plugin DATA dir.
    JANITOR_GLOBAL_STATE_DIR is where the request flag AND the Task cadence stamps live."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


# ---------- the request-flag trio (global_state) --------------------------

def test_request_present_clear_roundtrip() -> None:
    """request() sets the flag, present() sees it, clear() removes it."""
    assert gs.version_update_requested_present() is False
    gs.request_version_update("0.39.0->0.41.0")
    assert gs.version_update_requested_present() is True
    gs.clear_version_update_request()
    assert gs.version_update_requested_present() is False


def test_request_is_idempotent() -> None:
    """Re-requesting is harmless; present() stays True; a single clear() clears it."""
    gs.request_version_update("a")
    gs.request_version_update("b")
    gs.request_version_update("c")
    assert gs.version_update_requested_present() is True
    gs.clear_version_update_request()
    assert gs.version_update_requested_present() is False


def test_clear_when_absent_is_a_safe_noop() -> None:
    """clear() on a missing flag never raises and leaves present() False."""
    gs.clear_version_update_request()  # nothing set yet
    assert gs.version_update_requested_present() is False


# ---------- the pure decision predicate (version_update_lib) ---------------

def test_predicate_true_when_behind_and_both_enabled() -> None:
    """Cache behind + auto + trigger both on => raise the request."""
    assert vu.should_request_prompt_update("0.39.0", "0.41.0", True, True) is True


def test_predicate_false_when_current() -> None:
    """Equal installed/published versions => no request (already up to date)."""
    assert vu.should_request_prompt_update("0.41.0", "0.41.0", True, True) is False


def test_predicate_false_when_installed_ahead() -> None:
    """Installed strictly ahead of published => no request (never downgrade-trigger)."""
    assert vu.should_request_prompt_update("0.42.0", "0.41.0", True, True) is False


def test_predicate_false_when_auto_update_off() -> None:
    """auto_update_on_new_release off => no request even when behind."""
    assert vu.should_request_prompt_update("0.39.0", "0.41.0", False, True) is False


def test_predicate_false_when_release_trigger_off() -> None:
    """The release-trigger opt-in off => no request (falls back to the 6 h beat)."""
    assert vu.should_request_prompt_update("0.39.0", "0.41.0", True, False) is False


def test_predicate_false_when_a_version_is_missing() -> None:
    """Empty installed or published (transient gh/cache failure) => no request."""
    assert vu.should_request_prompt_update("", "0.41.0", True, True) is False
    assert vu.should_request_prompt_update("0.39.0", "", True, True) is False


# ---------- the daemon consume-helper (daemon) ----------------------------

def test_consume_runs_version_update_once_and_clears_flag() -> None:
    """Flag set => the version-update Task runs exactly once, flag cleared, returns True."""
    calls: list[str] = []
    task = daemon.Task("version-update", 21600, lambda: calls.append("ran"))
    gs.request_version_update("0.39.0->0.41.0")

    consumed = daemon._consume_version_update_request([task])

    assert consumed is True
    assert calls == ["ran"], "the version-update task must run exactly once"
    assert gs.version_update_requested_present() is False, "the flag must be cleared on consume"


def test_consume_is_a_noop_when_no_request() -> None:
    """No flag => returns False and runs nothing (no wasted self-update)."""
    calls: list[str] = []
    task = daemon.Task("version-update", 21600, lambda: calls.append("ran"))

    consumed = daemon._consume_version_update_request([task])

    assert consumed is False
    assert calls == []


def test_consume_clears_the_flag_BEFORE_running_the_task() -> None:
    """Clear-before-run: the flag is already gone when the task fn executes, so a crash
    mid-run cannot strand the request (the detector re-signals on its next fire)."""
    observed: list[bool] = []

    def _spy() -> None:
        # At the moment the task runs, the request flag must ALREADY be cleared.
        observed.append(gs.version_update_requested_present())

    task = daemon.Task("version-update", 21600, _spy)
    gs.request_version_update("x")

    daemon._consume_version_update_request([task])

    assert observed == [False], "the flag must be cleared BEFORE the task runs, not after"


def test_consume_runs_only_version_update_not_other_tasks() -> None:
    """With a full task list, only 'version-update' runs — never the sibling chores."""
    ran: list[str] = []
    tasks = [
        daemon.Task("marketplace-refresh", 1200, lambda: ran.append("marketplace-refresh")),
        daemon.Task("version-update", 21600, lambda: ran.append("version-update")),
        daemon.Task("user-plugins-update", 3600, lambda: ran.append("user-plugins-update")),
    ]
    gs.request_version_update("0.39.0->0.41.0")

    daemon._consume_version_update_request(tasks)

    assert ran == ["version-update"], "only the version-update task may run on consume"


def test_consume_clears_flag_even_when_no_version_update_task() -> None:
    """A task list lacking 'version-update' still clears the flag + returns True — the
    request is consumed (never left to re-fire forever) even if the task is absent."""
    ran: list[str] = []
    tasks = [daemon.Task("marketplace-refresh", 1200, lambda: ran.append("ran"))]
    gs.request_version_update("x")

    consumed = daemon._consume_version_update_request(tasks)

    assert consumed is True
    assert ran == []
    assert gs.version_update_requested_present() is False
