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

A reader who finds these tests green could still conclude the flake is solved. It is not —
but NOT for the reason this docstring gave until 2026-08-21. It claimed the 73 files calling
`subprocess.run` DIRECTLY were a second, uncovered family. They are not uncovered:
`run` forwards its timeout to `Popen.communicate`, which is the layer conftest patches, so
those ceilings scale too. `test_a_DIRECT_subprocess_run_gets_the_scaled_ceiling_too` and its
seam-off twin measure exactly that.

That correction REMOVES an explanation rather than adding one. The residual empty-stdout
failures observed after this shipped are therefore not attributable to a direct-`run` family
being missed, and their mechanism is undetermined — do not edit 73 call sites on the strength
of the old claim. What these tests pin is that the seam's scale reaches both call shapes and
stays production-inert.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import conftest
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
    assert state.timeout_scale() == 1.0


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
    assert state.timeout_scale() == 1.0


def test_a_valid_scale_is_honoured_and_read_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read per call, not bound at import — otherwise a fixture setting it later is ignored.

    That is not hypothetical: `conftest._relax_subprocess_timeouts` sets the knob well after
    `state` is imported, so an import-time constant would make the whole fix a no-op.
    """
    monkeypatch.setenv(_KNOB, "10")
    assert state.timeout_scale() == 10.0
    monkeypatch.setenv(_KNOB, "2.5")
    assert state.timeout_scale() == 2.5


def test_the_scale_actually_reaches_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavioural: the multiplied value is what `subprocess.run` receives.

    Asserting on `timeout_scale()` alone would pass even if nobody multiplied by it — the
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


# ---------------------------------------------------------------------------
# The OTHER half: the ceilings the TESTS own, scaled by conftest's seam.
# ---------------------------------------------------------------------------


def test_seam_multiplies_an_explicit_timeout_kwarg() -> None:
    """`scale_timeout_kwarg` multiplies an explicit numeric `timeout=` by the suite scale."""
    seen: dict[str, object] = {}

    def _spy(**kwargs: object) -> str:
        seen.update(kwargs)
        return "ran"

    assert conftest.scale_timeout_kwarg(_spy)(timeout=3) == "ran"
    assert seen["timeout"] == 3 * conftest.SUBPROCESS_TIMEOUT_SCALE


def test_seam_leaves_absent_and_none_timeouts_alone() -> None:
    """No timeout, or `timeout=None`, passes through untouched — `None * 10` would TypeError.

    Both shapes are routine: `Popen.wait()` inside `communicate`'s own cleanup passes neither,
    and `subprocess.run` forwards `timeout=None` verbatim when the caller gave none. A seam
    that multiplied blindly would turn every un-timed call in the suite into a crash.
    """
    seen: dict[str, object] = {}

    def _spy(**kwargs: object) -> None:
        seen.clear()
        seen.update(kwargs)

    scaled = conftest.scale_timeout_kwarg(_spy)
    scaled()
    assert "timeout" not in seen
    scaled(timeout=None)
    assert seen["timeout"] is None


def test_seam_is_installed_on_the_popen_layer() -> None:
    """The wiring: the autouse fixture patched `Popen.communicate`/`wait`, not `run`.

    Patching `subprocess.run` as well would DOUBLE-scale, because `run` forwards its own
    timeout down to `communicate`. Asserting the factory works (above) would pass even if the
    fixture never installed it anywhere, so this pins where it landed.
    """
    assert getattr(subprocess.Popen.communicate, "__wrapped__", None) is not None
    assert getattr(subprocess.Popen.wait, "__wrapped__", None) is not None
    assert getattr(subprocess.run, "__wrapped__", None) is None


def test_a_DIRECT_subprocess_run_gets_the_scaled_ceiling_too() -> None:
    """The second family IS covered: a bare `subprocess.run(timeout=)` inherits the scale.

    This is the box the card got wrong. `run_subprocess` is one seam; 73 files call
    `subprocess.run` directly with their own ceilings and were written off as "scaling the
    seam does nothing for those". They funnel through `Popen.communicate`, which IS the
    patched layer — so they are covered, and no 73-file edit is owed.

    Measured, not reasoned: a 1.5 s child under a 0.5 s ceiling. Unscaled that is a
    `TimeoutExpired`; at 10x the ceiling is 5 s and the child completes. Its twin below runs
    the identical call with the seam off and asserts the raise, so a passing result here
    cannot be a sleep that merely finished early.
    """
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(1.5)"],
        timeout=0.5,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0


@pytest.mark.no_timeout_scale
def test_a_DIRECT_subprocess_run_expires_when_the_seam_is_off() -> None:
    """The control for the test above — same call, seam removed, must raise.

    Without this, that test would pass just as happily if the child had exited instantly,
    proving nothing about the ceiling.
    """
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", "import time; time.sleep(1.5)"],
            timeout=0.5,
            capture_output=True,
            check=False,
        )


@pytest.mark.no_timeout_scale
def test_the_no_timeout_scale_marker_removes_the_seam() -> None:
    """The opt-out a timeout-subject test relies on actually opts out.

    `test_fetch_agents_timeout_is_reported` and `test_real_producer_...` DRIVE a timeout to
    completion; if the marker silently did nothing, their ceilings would stretch 10x and they
    would prove nothing while still passing.
    """
    assert getattr(subprocess.Popen.communicate, "__wrapped__", None) is None
