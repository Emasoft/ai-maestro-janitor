"""`run_subprocess` records WHY it failed open — unconditionally (TRDD-7NSRD8OV).

THE PROBLEM THIS CLOSES. `run_subprocess` returns None on timeout / missing binary / OSError
so a hung child can never park the 5-minute heartbeat. Callers then do
`if x is None: return 0` — and the detector exits 0 with EMPTY stdout. The test asserting on
that output fails with `assert 'something' in ''`, and nothing anywhere names a timeout, so it
reads as a logic bug in code that is correct.

The log line existed already, but it was gated on the OPTIONAL `detector_name` argument, so
every caller that omitted one failed open in total silence. TRDD-7NSRD8OV was misdiagnosed
four separate times against exactly that shape — each diagnosis a GUESS at a mechanism no
artifact had recorded. A soak at 595 s produced 26 failures of which essentially all were the
empty-stdout shape and not one could be classified from the logs.

So the gate is gone: an unattributed failure lands in a shared `subprocess.log` instead of
nowhere. The timestamp, the reason and the argv are what the diagnosis needs; the component
name is a nicety.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import state  # noqa: E402


def _log_text(name: str) -> str:
    path = state.log_dir() / f"{name}.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# Drives a real timeout to completion, so it owns its own scale — the suite-wide seam would
# stretch 0.1 s well past the child's lifetime and nothing would expire.
@pytest.mark.no_timeout_scale
def test_a_timeout_is_logged_even_with_no_detector_name(tmp_path: Path, monkeypatch) -> None:
    """An unattributed timeout still leaves a breadcrumb — in `subprocess.log`."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    state.init_state()

    assert state.run_subprocess([sys.executable, "-c", "import time; time.sleep(5)"],
                                timeout=0.1) is None

    logged = _log_text("subprocess")
    assert "timed out" in logged, f"a silent fail-open is the bug this closes; got {logged!r}"
    assert sys.executable in logged, "the argv must be there — the reason alone names no call"


@pytest.mark.no_timeout_scale
def test_a_named_caller_still_logs_to_its_own_file(tmp_path: Path, monkeypatch) -> None:
    """Passing `detector_name` keeps the old per-detector routing — no caller regressed."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    state.init_state()

    state.run_subprocess([sys.executable, "-c", "import time; time.sleep(5)"],
                         timeout=0.1, detector_name="some-detector")

    assert "timed out" in _log_text("some-detector")
    assert _log_text("subprocess") == "", "a named failure must not ALSO hit the shared log"


def test_a_missing_binary_is_logged(tmp_path: Path, monkeypatch) -> None:
    """FileNotFoundError is the other silent None — it names the binary, not just 'failed'."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    state.init_state()

    assert state.run_subprocess(["definitely-not-a-real-binary-xyzzy"]) is None
    assert "not in PATH" in _log_text("subprocess")


def test_an_unwritable_log_never_breaks_the_fail_open_contract(tmp_path: Path, monkeypatch) -> None:
    """The diagnostic must not become the thing that raises.

    `run_subprocess` documents that it NEVER propagates; a host whose log dir is unwritable
    would otherwise turn every fail-open into an exception in the heartbeat hot path. That is
    why `_log_fail_open` carries an `except OSError` against this repo's fail-fast default.
    """
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    state.init_state()

    def _boom(*_a: object, **_k: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(state, "log_line", _boom)
    assert state.run_subprocess(["definitely-not-a-real-binary-xyzzy"]) is None


def test_the_seam_and_the_knob_both_apply_in_tests_and_that_is_intended() -> None:
    """In-process production code is scaled TWICE, and that is a documented consequence.

    `run_subprocess` multiplies by `timeout_scale()` itself, then conftest's seam multiplies
    what reaches `Popen.communicate` again — so a 5 s production ceiling is 500 s under the
    suite, not 50 s. Harmless for a fail-open path (more slack is the point) and irrelevant for
    a child process (a detector gets the env knob only). It matters for a test that DRIVES a
    timeout, and those carry `no_timeout_scale`, which disables both halves.

    Pinned here so nobody 'fixes' the double-scale by removing one half and silently re-opens
    the flake this card is about.
    """
    assert state.timeout_scale() == 10.0
    assert getattr(subprocess.Popen.communicate, "__wrapped__", None) is not None
