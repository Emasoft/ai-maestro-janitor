"""TRDD-D2DD5GO8 — a blinded typing probe must DEFER an injection, never license it.

The 2026-08-19 incident, replayed as tests: under host load `ioreg` hangs, so
`hid_idle_seconds()` returns None and the old presence ladder fell through to the
SUBMIT-stamped breadcrumb — stale by construction while a user is mid-sentence — and
returned a confident-looking "not typing". The injector then typed over the user's
fingers. The fix has two halves, each pinned here:

  * `user_intent.typing_now` un-launders the blindness: hid readable answers BOTH ways;
    hid blinded ON darwin yields None (unless a fresh breadcrumb proves True); off darwin
    it collapses to a bool so no headless runner can block.
  * `terminal_trigger`'s default probes treat None as "typing" (defer, bounded by the
    loop's own loud give-up) and log once at the streak threshold.

Fault injection is real (monkeypatched probe functions on the real module objects); the
code under test is never mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import pytest  # noqa: E402
import terminal_trigger as tt  # noqa: E402
import user_intent  # noqa: E402

NBSP = " "


def _pane(field: str) -> str:
    """A capture shaped like the real one (see test_terminal_trigger_readback)."""
    return "out\n" + "─" * 40 + f"\n❯{NBSP}{field}\n" + "─" * 40 + "\n"


TERM = {"kind": "iterm", "session_id": "ABCDEF12-3456-7890-ABCD-EF1234567890"}


# ---------------------------------------------------------------- typing_now semantics

def test_typing_now_answers_both_ways_when_hid_is_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A working HID probe alone decides: recent keystroke ⇒ True, idle keyboard ⇒ False —
    breadcrumbs are not consulted, because HID is machine-wide and moves on every key."""
    monkeypatch.setattr(user_intent, "hid_idle_seconds", lambda **_kw: 2.0)
    assert user_intent.typing_now(idle_s=8) is True
    monkeypatch.setattr(user_intent, "hid_idle_seconds", lambda **_kw: 500.0)
    assert user_intent.typing_now(idle_s=8) is False


@pytest.mark.skipif(sys.platform != "darwin", reason="darwin blindness semantics")
def test_typing_now_blinded_on_darwin_is_UNKNOWN_not_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE incident pin: hid unreadable + stale/absent breadcrumb must be None — the old
    ladder's confident False here is what typed over the user on 2026-08-19."""
    monkeypatch.setattr(user_intent, "hid_idle_seconds", lambda **_kw: None)
    monkeypatch.setattr(user_intent, "user_presence", lambda **_kw: False)
    assert user_intent.typing_now(idle_s=8) is None
    monkeypatch.setattr(user_intent, "user_presence", lambda **_kw: None)
    assert user_intent.typing_now(idle_s=8) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="darwin blindness semantics")
def test_typing_now_blinded_still_honours_a_fresh_breadcrumb(monkeypatch: pytest.MonkeyPatch) -> None:
    """A submit IS typing: presence True survives the blindness as True."""
    monkeypatch.setattr(user_intent, "hid_idle_seconds", lambda **_kw: None)
    monkeypatch.setattr(user_intent, "user_presence", lambda **_kw: True)
    assert user_intent.typing_now(idle_s=8) is True


def test_typing_now_off_darwin_collapses_to_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-HID platforms must never yield None — a permanent defer there would resurrect the
    22-minute headless-CI hang class (31844013197) as a permanent give-up."""
    monkeypatch.setattr(user_intent.sys, "platform", "linux")
    monkeypatch.setattr(user_intent, "hid_idle_seconds", lambda **_kw: None)
    for presence, expect in ((True, True), (False, False), (None, False)):
        monkeypatch.setattr(user_intent, "user_presence", lambda _p=presence, **_kw: _p)
        assert user_intent.typing_now(idle_s=8) is expect


# ------------------------------------------------- inject_until_sent under a blind probe

def _run_inject(monkeypatch: pytest.MonkeyPatch, verdicts: list[bool | None]) -> tuple[bool, str, int]:
    """Drive the REAL inject_until_sent with its DEFAULT probe, faking only typing_now
    (the fault being injected) and the pane reader. Returns (sent, why, type_calls)."""
    seq = iter(verdicts)
    last: dict[str, bool | None] = {"v": verdicts[-1]}

    def fake_typing_now(**_kw: object) -> bool | None:
        try:
            last["v"] = next(seq)
        except StopIteration:
            pass
        return last["v"]

    monkeypatch.setattr(user_intent, "typing_now", fake_typing_now)
    typed: list[str] = []
    sent, why = tt.inject_until_sent(
        TERM,
        "/reload-plugins",
        type_fn=lambda: typed.append("typed"),
        submit_fn=lambda: typed.append("submitted"),
        quiet_s=0.01,
        retry_s=0.01,
        giveup_s=0.5,
        reader=lambda _t: _pane("/reload-plugins" if typed else ""),
        sleeper=lambda _s: None,
    )
    return sent, why, len([t for t in typed if t == "typed"])


def test_sustained_blindness_never_types_and_gives_up_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """The acceptance pin: with the probe blinded throughout, type_fn is NEVER called and
    the loop exits through the loud bounded give-up — defer, not cancel, not inject."""
    sent, why, type_calls = _run_inject(monkeypatch, [None])
    assert sent is False
    assert "gave up" in why
    assert type_calls == 0


def test_first_read_blind_then_recovered_idle_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient blip costs ONE deferral, never the command: blind once, then the probe
    recovers and proves the keyboard idle — the injection completes."""
    sent, _why, type_calls = _run_inject(monkeypatch, [None, False])
    assert sent is True
    assert type_calls == 1


def test_a_real_typing_verdict_still_defers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: True (actually typing) defers to the same loud give-up."""
    sent, why, type_calls = _run_inject(monkeypatch, [True])
    assert sent is False
    assert "gave up" in why
    assert type_calls == 0


def test_streak_log_fires_once_at_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagnostic names the blind probe exactly once per streak, at the threshold."""
    lines: list[str] = []
    monkeypatch.setattr(tt.state, "log_line", lambda _c, msg: lines.append(msg))
    _run_inject(monkeypatch, [None])
    blinded = [ln for ln in lines if "blinded" in ln]
    assert len(blinded) == 1
    assert f"{tt._BLIND_PROBE_STREAK}x" in blinded[0]


# ------------------------------------------------- wait_until_pane_free under blindness

def test_pane_free_wait_holds_busy_under_sustained_blindness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_intent, "typing_now", lambda **_kw: None)
    free, why = tt.wait_until_pane_free(
        TERM, quiet_s=0.01, giveup_s=0.3,
        reader=lambda _t: _pane(""), sleeper=lambda _s: None,
    )
    assert free is False
    assert "typing" in why or "iteration cap" in why


def test_pane_free_wait_frees_when_probe_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    verdicts = iter([None, False])
    monkeypatch.setattr(
        user_intent, "typing_now",
        lambda **_kw: next(verdicts, False),
    )
    free, why = tt.wait_until_pane_free(
        TERM, quiet_s=0.01, giveup_s=0.5,
        reader=lambda _t: _pane(""), sleeper=lambda _s: None,
    )
    assert free is True
    assert why == "pane free"
