"""A /clear that lands late must not strand phase B (TRDD-AIT2KNBU F2; issues #355, #356).

THE BUG. `/clear` typed into a busy pane is QUEUED by Claude Code and runs at the next turn
boundary -- 19 minutes later in #355, 261 s and 672 s later in the 2026-11-14/15 incidents. The
chain's post-Enter gate gave up at 180 s ("no fresh session within 180s"), so phase B
(`/janitor-arm`, `/goal`) was never typed. F2: after the base gate the chain keeps waiting while the
pane is busy (or compacting, or shows our `/clear` queued) and gives up only when the pane is idle
with nothing queued, confirmed by TWO consecutive probes with the stamp still not newer.

WHAT THESE TESTS DRIVE. The tmux tests run the REAL `clear_trigger._run_chain_payload` ->
`run_chained_inject` -> `_await_fresh_session` -> the production probe, typing through REAL
`tmux send-keys` into a REAL tmux pane and reading it back through REAL `tmux capture-pane`. The
pane does NOT run Claude Code: it runs a tiny script that PRINTS A CAPTURED FRAME from
`tests/fixtures/pane_frames/`, so it is a simulated TUI, not a live Claude Code. Two of those
frames are SYNTHETIC (hand-written, never captured from a real session):
`synthetic-compacting-native.txt` and `synthetic-queued-slash-command.txt`. A true end-to-end still
needs the owner to run a live session with `/goal`. The gate's timing knobs are shortened through
the functions' own keyword defaults so the tests run in seconds; the stamp-race and cap tests use a
fake clock and sleeper (the only fakes) because they assert tick-exact decision order.

Run only before a push (owner rule: no tests during development).
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FRAMES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import external_clear  # noqa: E402
import terminal_trigger  # noqa: E402
import user_intent  # noqa: E402
from test_clear_trigger_busy_gate import _BUSY_FRAME, _IDLE_FRAME, _import_clear_trigger, _Pane  # noqa: E402


@pytest.fixture
def pane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    p = _Pane(tmp_path, monkeypatch)
    # Fast cadence for the injector (production: 8 s quiet window, 5 s retry) and no HID probe.
    inject_defaults = terminal_trigger.inject_until_sent.__kwdefaults__
    assert inject_defaults is not None
    monkeypatch.setitem(inject_defaults, "quiet_s", 0.5)
    monkeypatch.setitem(inject_defaults, "retry_s", 0.5)
    # Base gate 180 s -> 1 s; probe cadence 15 s / recheck 5 s -> 1 s / 0.5 s.
    chain_defaults = terminal_trigger.run_chained_inject.__kwdefaults__
    assert chain_defaults is not None
    monkeypatch.setitem(chain_defaults, "gate_timeout_s", 1.0)
    await_defaults = terminal_trigger._await_fresh_session.__kwdefaults__
    assert await_defaults is not None
    monkeypatch.setitem(await_defaults, "extend_probe_every_s", 1.0)
    monkeypatch.setitem(await_defaults, "extend_recheck_s", 0.5)
    monkeypatch.setattr(user_intent, "typing_now", lambda *a, **kw: False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("JANITOR_TRANSCRIPT_PATH", raising=False)
    p.show(_IDLE_FRAME)  # the turn-busy gate would never type /clear into the busy frame
    yield p
    p.close()


def _payload(tmp_path: Path, terminal: dict, then: list[str]) -> str:
    payload = {
        "delay": 0.0,
        "terminal": terminal,
        "first": "/clear",
        "then": then,
        "state_dir": str(tmp_path / ".janitor" / "state"),
        "gate_baseline": 0,
        "directive": "resume",
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _start_chain(mod, pane: _Pane, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, then: list[str]):
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    result: dict[str, int] = {}
    thread = threading.Thread(
        target=lambda: result.update(rc=mod._run_chain_payload(_payload(tmp_path, pane.terminal, then)))
    )
    thread.start()
    return thread, result, logs


def _gate_stamp(tmp_path: Path) -> Path:
    return tmp_path / ".janitor" / "state" / "clear-observed.ts"


def _submitted_clear_at(pane: _Pane, thread: threading.Thread, limit_s: float = 30.0) -> float:
    """Block until the pane has submitted `/clear`; return the monotonic time that was seen."""
    deadline = time.monotonic() + limit_s
    while thread.is_alive() and time.monotonic() < deadline:
        if pane.submitted():
            return time.monotonic()
        time.sleep(0.05)
    raise AssertionError("the chain never submitted /clear")


class _FakeTime:
    """A clock and sleeper that advance together, so the gate's tick order is deterministic."""

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleeper(self, seconds: float) -> None:
        self.now += seconds


# --- T3 against a real tmux pane ------------------------------------------------------------


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
@pytest.mark.real_subprocess("tmux")
def test_a_late_landing_clear_still_gets_phase_b(pane: _Pane, tmp_path: Path, monkeypatch) -> None:
    """A real tmux pane (simulated TUI, not a live Claude Code): busy after the /clear, stamp 3 s later, then phase B is typed."""
    mod = _import_clear_trigger()
    thread, result, logs = _start_chain(mod, pane, tmp_path, monkeypatch, ["/janitor-arm"])

    submitted_at = _submitted_clear_at(pane, thread)
    pane.show(_BUSY_FRAME)  # the harness queued our /clear behind a running turn
    while time.monotonic() - submitted_at < 3.0:
        assert thread.is_alive(), f"the chain gave up while the pane was busy: {logs}"
        time.sleep(0.1)
    assert pane.submitted() == ["/clear"], "phase B was typed before the fresh session appeared"
    pane.show(_IDLE_FRAME)  # the turn ended, the queued /clear landed ...
    stamp = _gate_stamp(tmp_path)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(str(int(time.time()) + 5), encoding="utf-8")  # ... and its SessionStart stamped it
    thread.join(timeout=30)

    assert not thread.is_alive(), "chain did not finish"
    assert result["rc"] == 0, logs
    assert pane.submitted() == ["/clear", "/janitor-arm"]
    assert any("still waiting for the fresh session" in line for line in logs), logs
    assert not any("FAILED" in line for line in logs), logs


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
@pytest.mark.real_subprocess("tmux")
def test_an_idle_empty_pane_with_no_stamp_gives_up_after_two_false_probes(
    pane: _Pane, tmp_path: Path, monkeypatch
) -> None:
    """A real tmux pane (simulated TUI) idle with an empty field and no stamp: the old give-up, now after exactly two False probes."""
    mod = _import_clear_trigger()
    answers: list[tuple[bool, str]] = []
    real_decision = mod.gate_extend_decision

    def _recording(frame):
        answer = real_decision(frame)
        answers.append(answer)
        return answer

    monkeypatch.setattr(mod, "gate_extend_decision", _recording)
    thread, result, logs = _start_chain(mod, pane, tmp_path, monkeypatch, ["/janitor-arm"])
    thread.join(timeout=60)

    assert not thread.is_alive(), "chain did not finish"
    assert result["rc"] == 1, logs
    assert [extend for extend, _why in answers] == [False, False], answers
    assert pane.submitted() == ["/clear"], "phase B must NOT be typed into a session that never cleared"
    failed = [line for line in logs if "chain: FAILED" in line]
    assert failed, logs
    match = re.search(r"no fresh session after (\d+)s", failed[0])
    assert match is not None, failed[0]
    assert int(match.group(1)) >= 1, "the failure text must report real elapsed seconds, not the 180 s default"
    assert "180" not in failed[0], failed[0]


# --- the gate itself, fake clock ------------------------------------------------------------


def test_a_stamp_landing_between_the_two_probes_wins(tmp_path: Path) -> None:
    """A fresh session looks idle+empty before its hook stamps: a stamp that lands right after the first False probe returns True."""
    stamp = tmp_path / "clear-observed.ts"
    stamp.write_text("100", encoding="utf-8")
    fake = _FakeTime()
    calls: list[float] = []

    def _extend() -> bool:
        calls.append(fake.now)
        stamp.write_text("101", encoding="utf-8")  # the hook stamps while the pane already looks idle
        return False

    assert terminal_trigger._await_fresh_session(
        stamp, 100, timeout_s=2, sleeper=fake.sleeper, clock=fake.clock,
        gate_extend=_extend, gate_cap_s=100,
    ) is True
    assert len(calls) == 1, "the stamp must be re-read BEFORE the second probe is asked"


def test_two_consecutive_false_probes_with_no_stamp_give_up(tmp_path: Path) -> None:
    """Idle+empty twice in a row, 5 s apart, stamp never newer: False, after exactly two probes."""
    stamp = tmp_path / "clear-observed.ts"
    stamp.write_text("100", encoding="utf-8")
    fake = _FakeTime()
    calls: list[float] = []

    def _extend() -> bool:
        calls.append(fake.now)
        return False

    assert terminal_trigger._await_fresh_session(
        stamp, 100, timeout_s=2, sleeper=fake.sleeper, clock=fake.clock,
        gate_extend=_extend, gate_cap_s=1000,
    ) is False
    assert calls == [2.0, 7.0], calls


def test_a_busy_answer_resets_the_false_count_and_the_cap_still_ends_the_wait(tmp_path: Path) -> None:
    """True answers keep the wait going every 15 s, but never past gate_cap_s from entry."""
    stamp = tmp_path / "clear-observed.ts"
    fake = _FakeTime()
    calls: list[float] = []

    def _extend() -> bool:
        calls.append(fake.now)
        return True

    assert terminal_trigger._await_fresh_session(
        stamp, 0, timeout_s=2, sleeper=fake.sleeper, clock=fake.clock,
        gate_extend=_extend, gate_cap_s=100,
    ) is False
    assert calls == [2.0, 17.0, 32.0, 47.0, 62.0, 77.0, 92.0], calls
    assert fake.now >= 100


def test_gate_extend_without_a_cap_is_refused(tmp_path: Path) -> None:
    """No implicit cap: an extension with no gate_cap_s raises instead of waiting forever."""
    with pytest.raises(ValueError, match="gate_cap_s"):
        terminal_trigger._await_fresh_session(
            tmp_path / "s.ts", 0, timeout_s=1, sleeper=lambda _s: None, gate_extend=lambda: True,
        )


# --- the production probe on frames ---------------------------------------------------------


@pytest.mark.parametrize(
    ("frame_name", "expected"),
    [
        ("real-calm-working.txt", True),  # captured: main turn busy
        ("synthetic-compacting-native.txt", True),  # SYNTHETIC: native compaction, empty field
        ("synthetic-compacting-with-queued.txt", True),  # SYNTHETIC: compacting with queued rows
        ("synthetic-queued-slash-command.txt", True),  # SYNTHETIC: idle status, /clear queued
        ("synthetic-garbage-empty.txt", True),  # unrecognised frame counts as busy
        ("synthetic-idle-empty-field.txt", False),  # idle, empty field: the clear went nowhere
        ("synthetic-done-row-idle.txt", False),
    ],
)
def test_the_probe_extends_for_busy_compacting_queued_and_unreadable_panes(frame_name: str, expected: bool) -> None:
    """The production probe on captured/synthetic frames: only an idle pane with nothing queued ends the wait."""
    mod = _import_clear_trigger()
    extend, why = mod.gate_extend_decision((_FRAMES / frame_name).read_text(encoding="utf-8"))
    assert extend is expected, (frame_name, why)


def test_an_unreadable_pane_extends() -> None:
    """None from read_pane_text counts as busy; the cap bounds it."""
    extend, _why = _import_clear_trigger().gate_extend_decision(None)
    assert extend is True


# --- drift -----------------------------------------------------------------------------------


def test_the_chain_caps_the_wait_with_the_arming_window_constant(tmp_path: Path, monkeypatch) -> None:
    """Drift guard: the chain passes gate_cap_s == external_clear._UNARMED_CLEAR_FLAG_MAX_AGE_S (F3's late-landing window), not _CLEAR_CHAIN_GIVEUP_S."""
    mod = _import_clear_trigger()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    captured: dict = {}

    def _capture(_terminal, **kwargs):
        captured.update(kwargs)
        return True, "chain complete"

    monkeypatch.setattr(mod.terminal_trigger, "run_chained_inject", _capture)
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: None)
    assert mod._run_chain_payload(_payload(tmp_path, {"kind": "tmux", "pane": "%1"}, [])) == 0

    assert captured["gate_cap_s"] == float(external_clear._UNARMED_CLEAR_FLAG_MAX_AGE_S)
    assert callable(captured["gate_extend"])
    assert mod.gate_extend_cap_s() == captured["gate_cap_s"]
