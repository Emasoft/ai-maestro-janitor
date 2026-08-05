"""The presence gate DEFERS to a busy pane; it does not abandon the send (owner report 2026-08-05).

Before this, `send_self_command` returned USER_PRESENT on the FIRST refusal, which stranded the
continuity chain — the human was told to type `/clear` + `/janitor-arm` themselves. The janitor's
primary guarantee is that an agent never STOPS, so the gate must WAIT for the pane to go quiet
(the presence window is only 10 s wide) and give up only after a real budget elapses.

Every test stubs the post-gate channel, so a regression can never type into the developer's own
pane while the suite runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terminal_trigger as tt  # noqa: E402

_SENT = "FIRED:stub-channel"


@pytest.fixture(autouse=True)
def _stub_channel(monkeypatch):
    """Neutralise everything AFTER the gate.

    The gate is the unit under test; the channel is not. Stubbing it keeps the assertions about
    deferral alone AND makes it impossible for a broken gate to drive real keystrokes into
    whatever terminal is running the suite.
    """
    monkeypatch.setattr(tt.state, "in_ai_maestro_agent_env", lambda *a, **k: False)
    monkeypatch.setattr(tt.state, "terminal_kind", lambda *a, **k: "stub")
    monkeypatch.setattr(tt, "_try_linux_gui_send", lambda *a, **k: _SENT)


class _Gate:
    """`injection_allowed` that refuses `refusals` times, then allows. Records every call."""

    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.calls = 0

    def __call__(self, _cmds, **_kw):
        self.calls += 1
        if self.calls <= self.refusals:
            return False, "user is present and did not ask"
        return True, "user is away"


def _fake_sleeper():
    """A sleeper that records durations instead of spending them, so the test is instant."""
    slept: list[float] = []
    return slept, slept.append


def test_busy_then_idle_sends_after_waiting(monkeypatch):
    """The pane is busy for three polls, then goes quiet -> the command IS sent."""
    gate = _Gate(refusals=3)
    monkeypatch.setattr(tt.user_intent, "injection_allowed", gate)
    slept, sleeper = _fake_sleeper()

    result = tt.send_self_command("/janitor-arm", env={}, sleeper=sleeper)

    assert result == _SENT, "a pane that went quiet must receive the command, not a refusal"
    assert gate.calls == 4, "the gate must be re-asked each poll, not consulted once"
    assert len(slept) == 3, "one wait per refusal"
    assert all(d == tt._PRESENCE_POLL_S for d in slept)


def test_busy_throughout_gives_up_only_after_the_budget(monkeypatch):
    """A pane that never goes quiet still yields USER_PRESENT — but only after waiting."""
    gate = _Gate(refusals=10**6)
    monkeypatch.setattr(tt.user_intent, "injection_allowed", gate)
    slept, sleeper = _fake_sleeper()

    # A real monotonic clock with a zero-cost sleeper would spin the full budget in wall-clock
    # time, so the budget is passed explicitly and kept small.
    result = tt.send_self_command(
        "/janitor-arm", env={}, sleeper=sleeper, presence_wait_s=0.05
    )

    assert result == tt.USER_PRESENT
    assert gate.calls >= 2, "give-up must follow at least one RETRY, never the first refusal"
    assert slept, "the gate must have actually waited before giving up"


def test_zero_budget_restores_fail_fast(monkeypatch):
    """`presence_wait_s=0` is the documented escape hatch for a caller that cannot block."""
    gate = _Gate(refusals=10**6)
    monkeypatch.setattr(tt.user_intent, "injection_allowed", gate)
    slept, sleeper = _fake_sleeper()

    result = tt.send_self_command("/janitor-arm", env={}, sleeper=sleeper, presence_wait_s=0)

    assert result == tt.USER_PRESENT
    assert gate.calls == 1 and not slept, "a zero budget must not sleep at all"


def test_away_user_never_waits(monkeypatch):
    """The common path is untouched: an absent user sends immediately, with no delay."""
    gate = _Gate(refusals=0)
    monkeypatch.setattr(tt.user_intent, "injection_allowed", gate)
    slept, sleeper = _fake_sleeper()

    assert tt.send_self_command("/janitor-arm", env={}, sleeper=sleeper) == _SENT
    assert gate.calls == 1 and not slept


def test_dry_run_bypasses_the_gate_entirely(monkeypatch):
    """A dry run sends nothing, so it must neither consult the gate nor wait on it."""
    gate = _Gate(refusals=10**6)
    monkeypatch.setattr(tt.user_intent, "injection_allowed", gate)
    slept, sleeper = _fake_sleeper()

    tt.send_self_command("/janitor-arm", env={}, dry_run=True, sleeper=sleeper)

    assert gate.calls == 0 and not slept


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", tt._PRESENCE_WAIT_DEFAULT_S),
        ("45", 45.0),
        ("0", 0.0),
        ("  90  ", 90.0),
        # A malformed or negative knob must NOT silently become fail-fast — that would turn the
        # stranding bug back on through a typo, which is exactly what this fix removed.
        ("banana", tt._PRESENCE_WAIT_DEFAULT_S),
        ("-1", tt._PRESENCE_WAIT_DEFAULT_S),
    ],
)
def test_budget_knob_parsing(raw, expected):
    assert tt._presence_wait_budget_s({"CLAUDE_PLUGIN_OPTION_PRESENCE_WAIT_S": raw}) == expected
