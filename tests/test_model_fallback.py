"""The model-scoped fallback PLANNER's truth table (TRDD-QE390SJA, janitor#222).

Every branch is a decision that types (or refuses to type) into the user's own pane, so each
one is pinned here with the reason it exists — a planner whose refusals are untested is a
planner that will act on the day its gate is wrong.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import model_fallback as mf  # noqa: E402

NOW = 1_800_000_000
_VERDICT = {"model": "Fable", "scoped_label": "7d/Fable", "scoped_util": 98.0,
            "account_max_util": 60.0, "resets_at_epoch": NOW + 1000}


class _PlanKwargs(TypedDict):
    """Shape of `plan_model_fallback`'s kwargs (TypedDict, PEP 692) — a bare `dict(...)`
    mixing dict/str/int/bool values infers one union value type, so `**kw` would broadcast
    that union against every keyword parameter."""

    verdict: dict[str, Any] | None
    current_model: str | None
    target: str
    last_switch_ts: int
    now: int
    is_enabled: bool


def _plan(**over: Any) -> dict:
    kw: _PlanKwargs = {
        "verdict": _VERDICT, "current_model": "Fable 5", "target": "opus",
        "last_switch_ts": 0, "now": NOW, "is_enabled": True,
    }
    kw.update(over)  # type: ignore[typeddict-item]  # `over` is a caller-supplied partial override
    return mf.plan_model_fallback(**kw)


def test_the_measured_case_switches() -> None:
    """Scoped window spent, session still on that model, no cooldown → type the switch."""
    p = _plan()
    assert p["act"] is True and p["command"] == "/model opus" and p["reason"] == "switch"


def test_default_is_enabled_with_the_env_var_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFAULT ON: a spent model window otherwise stalls the session until the window resets,
    and an idle session cannot self-heal any other way — so with nothing set, the switch is
    live by default."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED", raising=False)
    assert mf.enabled() is True, "the flag must default ON"


@pytest.mark.parametrize("spelling", ["false", "0", "no", "off", "False", "OFF"])
def test_explicit_false_spellings_still_disable_it(
    monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    """The opt-out escape hatch: any of the usual false spellings turns it back off, and the
    planner refuses regardless of how compelling the case is — the failure mode of a wrong
    switch is a session parked on an unanswered dialog, which is worse than the exhausted
    window it was fixing."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED", spelling)
    assert mf.enabled() is False, f"{spelling!r} must disable the flag"
    p = _plan(is_enabled=False)
    assert p["act"] is False and p["reason"] == mf.SKIP_DISABLED


def test_no_verdict_does_nothing() -> None:
    """No gate verdict (window fine, stale snapshot, unproven headroom) → no action."""
    assert _plan(verdict=None)["reason"] == mf.SKIP_NO_VERDICT


def test_already_off_the_exhausted_model_is_a_named_skip() -> None:
    """The single-session form of 'the candidate list drains itself' — including the case
    that actually happened: the owner switched by hand before the automation ran."""
    p = _plan(current_model="Opus 5")
    assert p["act"] is False and p["reason"] == mf.SKIP_ALREADY_OFF


def test_an_unknown_current_model_does_NOT_act() -> None:
    """No badge in the capture is UNKNOWN, never 'probably still on the spent model'.
    Typing blind could switch a session that already moved; unproven state does not
    actuate — the same rule as unproven freshness and unproven headroom."""
    p = _plan(current_model=None)
    assert p["act"] is False and p["reason"] == mf.SKIP_UNKNOWN_MODEL


def test_never_switches_TO_the_exhausted_model() -> None:
    """Would accomplish nothing and burn a cooldown. Family-compared, so 'Fable 5' and
    'fable' are the same target."""
    for target in ("fable", "Fable 5"):
        p = _plan(target=target)
        assert p["act"] is False and p["reason"] == mf.SKIP_TARGET_EXHAUSTED


def test_cooldown_suppresses_a_second_switch_inside_the_interval() -> None:
    """Enforced HERE rather than by trusting the beat: the heartbeat cadence is dynamic
    (it re-tiers between */5 and */15 on its own), so a faster beat would otherwise fire a
    burst of switches — the exact rate-limit ban the interval exists to avoid."""
    assert _plan(last_switch_ts=NOW - 10)["reason"] == mf.SKIP_COOLDOWN
    assert _plan(last_switch_ts=NOW - mf.FALLBACK_INTERVAL_S - 1)["act"] is True


def test_cooldown_is_checked_LAST_so_the_reported_reason_is_the_useful_one() -> None:
    """A session already off the exhausted model reports THAT, not a cooldown that is
    irrelevant to it — the reason is what a human reads when asking why nothing happened."""
    p = _plan(current_model="Opus 5", last_switch_ts=NOW - 5)
    assert p["reason"] == mf.SKIP_ALREADY_OFF


def test_a_never_switched_session_is_not_in_cooldown() -> None:
    """last_switch_ts == 0 means 'never', not 'the epoch' — a fresh install must not be
    treated as having just switched."""
    assert _plan(last_switch_ts=0)["act"] is True


@pytest.mark.parametrize("target_env,expected", [("", "opus"), ("sonnet", "sonnet")])
def test_target_is_configurable_with_a_sane_default(
    monkeypatch: pytest.MonkeyPatch, target_env: str, expected: str
) -> None:
    """A future model tier should not need a code change."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_TARGET", target_env)
    assert mf.fallback_target() == expected


# --- the detector: roster wiring + the dark default (TRDD-QE390SJA) ------------------------


def test_detector_is_on_the_roster_and_denied_to_harness_agents() -> None:
    """A detector that is not on the roster NEVER RUNS — that exact omission kept
    token-usage-anomaly dark for weeks (TRDD-E9LMBNPE). And it must be denied inside a
    harness agent: its data source is the OAuth rotator (off in there) and it TYPES INTO A
    PANE, which is the server's to drive for harness agents (janitor#100)."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    import dispatch  # noqa: PLC0415

    names = [name for name, _, _ in dispatch._DETECTORS]
    assert "model-fallback" in names
    assert "model-fallback" in dispatch._NON_HARNESS_DETECTORS


def test_detector_file_exists_and_is_executable() -> None:
    """The roster names a FILE; a typo there is a silent no-op."""
    det = _ROOT / "scripts" / "detectors" / "model-fallback.py"
    assert det.is_file(), f"roster names a detector that does not exist: {det}"
    assert os.access(det, os.X_OK), "detector must be executable (the roster runs it directly)"


def test_detector_exits_silently_when_explicitly_disabled(tmp_path: Path) -> None:
    """Proven by running the real thing: with the flag explicitly turned off it must print
    NOTHING and touch no pane. This is the test the ai-maestro side pins on their side too —
    the failure mode of a wrong switch is a session parked on an unanswered dialog. (The flag
    now defaults ON when unset — see `test_default_is_enabled_with_the_env_var_unset` above —
    so this test pins the explicit opt-out rather than the old dark default; it stays
    hermetic in `tmp_path` by forcing the disabled path instead of depending on whatever
    rotator state happens to be configured on the machine running the suite.)"""
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"),
        "CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED": "false",
    }
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "detectors" / "model-fallback.py")],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"disabled detector must be silent, got: {proc.stdout!r}"


def _load_detector():
    """In-process load of the hyphen-named detector so its routing can be spied on."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "mf_det_routing", _ROOT / "scripts" / "detectors" / "model-fallback.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wire_acting_detector(det, monkeypatch, pane_text: str) -> dict[str, list]:
    """Fake every gate up to the injection so main() reaches the sequence choice with
    `pane_text` on the pane, and spy on BOTH injection entry points."""
    called: dict[str, list] = {"true_error": [], "verified": []}
    monkeypatch.setattr(det.state, "init_state", lambda: None)
    monkeypatch.setattr(det.state, "log_line", lambda *a, **k: None)
    monkeypatch.setattr(det.state, "rotate_log_if_big", lambda *a, **k: None)
    monkeypatch.setattr(det.mfb, "enabled", lambda: True)
    monkeypatch.setattr(det, "_live_account", lambda: {"usage": {}, "sample_age_s": 0, "is_live": True})
    monkeypatch.setattr(
        det.token_burn, "model_fallback_verdict",
        lambda *a, **k: {"model": "Fable", "scoped_label": "7d/Fable", "scoped_util": 98.0,
                         "account_max_util": 40.0, "resets_at_epoch": None},
    )
    monkeypatch.setattr(det, "_this_terminal", lambda: {"kind": "tmux", "pane": "%1"})
    monkeypatch.setattr(det.terminal_trigger, "read_pane_text", lambda _t: pane_text)
    monkeypatch.setattr(det.mfb, "fallback_target", lambda: "opus")
    monkeypatch.setattr(
        det.mfb, "plan_model_fallback",
        lambda **k: {"act": True, "command": "/model opus", "reason": "test"},
    )
    monkeypatch.setattr(
        det.terminal_trigger, "send_model_switch_true_error",
        lambda t, c, **k: (called["true_error"].append(c), (True, "sent; ask-user menu confirmed"))[1],
    )
    monkeypatch.setattr(
        det.terminal_trigger, "send_verified",
        lambda t, c, **k: (called["verified"].append(c), (True, "sent"))[1],
    )
    monkeypatch.setattr(det.terminal_trigger, "confirm_model_switch", lambda *a: True)
    monkeypatch.setattr(det, "_stamp_switch", lambda _n: None)
    monkeypatch.setattr(det, "_last_switch_ts", lambda: 0)
    monkeypatch.setattr(det.findings_ledger, "record", lambda **k: None)
    return called


def test_a_true_error_pane_routes_to_the_owner_ratified_sequence(monkeypatch, capsys) -> None:
    """Owner spec 2026-08-15: a pane showing CC's live retry signature must get the
    command+Enter → ESC → wait-for-menu → Enter sequence, NOT the idle ESC-first one."""
    det = _load_detector()
    called = _wire_acting_detector(
        det, monkeypatch, "⏳ Rate limited · Retrying in 3s · attempt 12/300\n"
    )
    assert det.main() == 0
    assert called["true_error"] == ["/model opus"], "the true-error sequence must be chosen"
    assert called["verified"] == [], "the idle ESC-first path must NOT fire on an erroring pane"


def test_an_idle_pane_keeps_the_esc_first_sequence(monkeypatch, capsys) -> None:
    """CONTROL for the routing: no retry signature on the pane ⇒ the original ESC-first
    verified injection stands — proving the router keys on the pane state, not on the
    verdict alone."""
    det = _load_detector()
    called = _wire_acting_detector(det, monkeypatch, "just an idle prompt, nothing retrying\n")
    assert det.main() == 0
    assert called["verified"] == ["/model opus"], "idle pane must keep the ESC-first path"
    assert called["true_error"] == [], "the true-error sequence must not fire on an idle pane"
