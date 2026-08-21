"""`run_subprocess`'s timeout scale — TRDD-7NSRD8OV.

The scale exists so the TEST SUITE can survive its own load, not so anyone can loosen a
production timeout. These tests pin that distinction: the default is 1.0, a malformed or
non-positive knob falls back to 1.0, and the knob is read PER CALL so a fixture that sets it
after import is honoured.

Why the seam exists at all: detectors pass short timeouts (`git rev-parse --git-dir`,
`timeout=5`) and `run_subprocess` fails OPEN on expiry — returning None so a hung child never
parks the 5-minute heartbeat. Under full-suite load that expiry fires, the caller's
`if x is None: return 0` runs, and the detector exits 0 with EMPTY stdout; the test then fails
asserting on `''` with nothing naming a timeout. 52 call sites share the seam, so which test
fails is decided by scheduling — that is why the fix is here and not in any one test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import state  # noqa: E402

_KNOB = "CLAUDE_PLUGIN_OPTION_SUBPROCESS_TIMEOUT_SCALE"


def test_production_default_is_exactly_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNSET ⇒ 1.0. This is the whole safety property: production behaviour is byte-identical.

    If this ever fails, the flake fix has become a silent production change — the exact trade
    TRDD-7NSRD8OV forbids ("do not loosen a real guarantee to make a test pass").
    """
    monkeypatch.delenv(_KNOB, raising=False)
    assert state._timeout_scale() == 1.0


@pytest.mark.parametrize("raw", ["", "abc", "0", "-3", "nan-ish", "1e", "None"])
def test_malformed_or_non_positive_falls_back_to_one(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A bad knob must never SHORTEN a timeout.

    Falling back to 1.0 rather than raising is deliberate: this runs inside the heartbeat's
    hot path, where a config typo must not take out the detector that reads it. `0` and
    negatives are rejected for the same reason — `timeout=0` would make every subprocess
    expire instantly, converting a mistyped knob into a total, silent outage of every
    detector that shells out.
    """
    monkeypatch.setenv(_KNOB, raw)
    assert state._timeout_scale() == 1.0


def test_a_valid_scale_is_honoured_and_read_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read per call, not bound at import — otherwise a fixture setting it later is ignored.

    That is not hypothetical: `conftest._relax_subprocess_timeouts` sets the knob well after
    `state` is imported, so an import-time constant would make the whole fix a no-op.
    """
    monkeypatch.setenv(_KNOB, "10")
    assert state._timeout_scale() == 10.0
    monkeypatch.setenv(_KNOB, "2.5")
    assert state._timeout_scale() == 2.5


def test_the_scale_actually_reaches_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavioural: the multiplied value is what `subprocess.run` receives.

    Asserting on `_timeout_scale()` alone would pass even if nobody multiplied by it — the
    helper could be dead code. This pins the wiring.
    """
    seen: dict[str, float] = {}

    def _fake_run(*_a, **kw):
        seen["timeout"] = kw["timeout"]
        raise KeyboardInterrupt  # unwind without really spawning anything

    monkeypatch.setattr(state.subprocess, "run", _fake_run)
    monkeypatch.setenv(_KNOB, "4")
    with pytest.raises(KeyboardInterrupt):
        state.run_subprocess(["true"], timeout=5)
    assert seen["timeout"] == 20.0
