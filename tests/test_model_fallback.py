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

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import model_fallback as mf  # noqa: E402

NOW = 1_800_000_000
_VERDICT = {"model": "Fable", "scoped_label": "7d/Fable", "scoped_util": 98.0,
            "account_max_util": 60.0, "resets_at_epoch": NOW + 1000}


def _plan(**over):
    kw = dict(
        verdict=_VERDICT, current_model="Fable 5", target="opus",
        last_switch_ts=0, now=NOW, is_enabled=True,
    )
    kw.update(over)
    return mf.plan_model_fallback(**kw)


def test_the_measured_case_switches() -> None:
    """Scoped window spent, session still on that model, no cooldown → type the switch."""
    p = _plan()
    assert p["act"] is True and p["command"] == "/model opus" and p["reason"] == "switch"


def test_ships_dark() -> None:
    """DEFAULT OFF, and the planner refuses regardless of how compelling the case is: the
    failure mode of a wrong switch is a session parked on an unanswered dialog, which is
    worse than the exhausted window it was fixing."""
    assert mf.enabled() is False, "the flag must default OFF"
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


def test_detector_exits_silently_while_the_flag_is_unset(tmp_path: Path) -> None:
    """SHIPS DARK, proven by running the real thing: with the flag unset it must print
    NOTHING and touch no pane. This is the test the ai-maestro side pins on their side too —
    the failure mode of a wrong switch is a session parked on an unanswered dialog."""
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"),
    }
    env.pop("CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED", None)
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "detectors" / "model-fallback.py")],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"dark detector must be silent, got: {proc.stdout!r}"
