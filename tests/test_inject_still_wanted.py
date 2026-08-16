"""`still_wanted` — the condition, not the clock, terminates a deferred injection.

WHY (owner directive 2026-08-16). The /clear chain's injection used to give up on a 30 s
wall clock while the pane was busy — measured that day: three abandoned injections
(`inject gave up after 30s: field not empty ('the user is typing')`) left a session
un-shrunk for 4+ hours, the exact cost the external clear exists to prevent. The directive:
keep retrying at the 8 s cadence, but re-ask agentlensPro each round whether the cache is
still expired, and CANCEL the moment it is not — the user's own turn rebuilt the cache, so
the /clear would destroy a live context for nothing.

These tests pin the `inject_until_sent` half (the generic cancel hook) and the
`run_chained_inject` half (first-command-only wiring). The probe itself is
`external_clear.cache_certainly_expired`, already covered by its own tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import terminal_trigger as tt  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_project_log(monkeypatch, tmp_path):
    """The cancel path calls `state.log_line`, which resolves the PROJECT `.janitor/logs`
    from CLAUDE_PROJECT_DIR — conftest's autouse isolation covers HOME and the global-state
    dirs, not this one. Without the redirect these tests append their fixture strings to the
    REAL log: measured 2026-08-16, "inject cancelled: cache went warm" landed in the live
    `.janitor/logs/terminal_trigger.log` three times and read there as production evidence."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

NBSP = " "


def _pane(field: str) -> str:
    """A capture shaped like the real one (same fixture as test_terminal_trigger_readback):
    box rule, marker + NBSP + field, box rule. The shape is load-bearing — an invented pane
    format parses as 'busy', adds a silent extra loop iteration, and the reader sequences
    exhaust with StopIteration (how the first draft of this file failed)."""
    return "some earlier output\n" + "─" * 40 + f"\n❯{NBSP}{field}\n" + "─" * 40 + "\n"


def _seq(*items):
    it = iter(items)
    return lambda _t=None: next(it)


def test_still_wanted_False_cancels_instead_of_waiting_out_the_clock() -> None:
    """The cancel arrives as its own loud verdict, not as a timeout."""
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/clear",
        type_fn=lambda: None, submit_fn=lambda: None,
        reader=_seq(_pane("busy")),
        is_typing=lambda _t: False,
        still_wanted=lambda: (False, "cache is WARM again"),
        sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok is False
    assert why == "cancelled — cache is WARM again"


def test_still_wanted_is_asked_BEFORE_the_typing_probe() -> None:
    """A no-longer-wanted command must cancel even while the user types.

    Order is the point: if the typing deferral ran first, a continuously-typing user would
    keep the probe from ever being consulted, and the injection would wait out its whole
    ceiling for a command whose purpose evaporated on the first keystroke's turn.
    """
    probes: list[str] = []

    def _typing(_t) -> bool:
        probes.append("typing")
        return True

    def _wanted() -> tuple[bool, str]:
        probes.append("wanted")
        return (len(probes) < 3, "cache went warm")

    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/clear",
        type_fn=lambda: None, submit_fn=lambda: None,
        reader=_seq(_pane("busy")),
        is_typing=_typing,
        still_wanted=_wanted,
        sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok is False and "cancelled" in why
    assert probes[0] == "wanted", "the cancel condition must be consulted before the typing probe"


def test_still_wanted_True_keeps_the_8s_defer_cadence() -> None:
    """While the condition holds, behaviour is exactly the pre-existing 8 s deferral —
    the hook adds a terminator, it must not change the cadence the owner specified."""
    typing = iter([True, True, False])
    slept: list[float] = []
    sent: list[str] = []
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/clear",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        reader=_seq(_pane(""), _pane("/clear")),
        is_typing=lambda _t: next(typing),
        still_wanted=lambda: (True, "cache still expired"),
        sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok, why
    assert sent == ["Enter"]
    assert slept[:2] == [8.0, 8.0]


def test_absent_still_wanted_changes_nothing() -> None:
    """The default (None) is the historical contract — no probe, clock-bounded only."""
    sent: list[str] = []
    ok, _ = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/clear",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        reader=_seq(_pane(""), _pane("/clear")),
        is_typing=lambda _t: False,
        sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok and sent == ["Enter"]


def test_run_chained_inject_gates_ONLY_the_first_command(monkeypatch) -> None:
    """Once /clear is submitted, the bootstrap must run regardless of the condition.

    Cancelling mid-chain strands a cleared session unarmed and unresumable — the exact
    outcome the chain exists to prevent — so the probe is wired to the first inject only.
    Asserted by spying which inject calls receive the hook, not by simulating a full chain.
    """
    seen: list[object] = []
    real = tt.inject_until_sent

    def _spy(terminal, command, **kw):
        seen.append((command, kw.get("still_wanted")))
        return False, "stop after the first call"

    monkeypatch.setattr(tt, "inject_until_sent", _spy)
    marker = lambda: (True, "x")  # noqa: E731
    ok, _why = tt.run_chained_inject(
        {"kind": "tmux", "pane": "%1"},
        first="/clear", then=["/janitor-arm"],
        gate_stamp=Path("/nonexistent/gate"), gate_baseline=0,
        still_wanted=marker,
    )
    assert ok is False
    assert seen == [("/clear", marker)], (
        "the first command must carry the hook (and the chain stops when it fails)"
    )
    assert tt.inject_until_sent is not real or True  # monkeypatch restores on teardown
