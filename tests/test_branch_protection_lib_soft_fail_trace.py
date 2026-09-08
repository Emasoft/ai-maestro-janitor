"""Tests that the three `gh`-reader soft-fail paths in branch_protection_lib print a stderr
trace line naming the cause (TRDD-PJD6XV66) — the silence that hid 7NSRD8OV's failures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

# Controlled via env: GH_RC (exit code), GH_STDOUT, GH_STDERR, GH_SLEEP (seconds).
_GH_STUB = '''#!/usr/bin/env python3
import os, sys, time
time.sleep(float(os.environ.get("GH_SLEEP", "0")))
out = os.environ.get("GH_STDOUT", "")
err = os.environ.get("GH_STDERR", "")
if out:
    sys.stdout.write(out)
if err:
    sys.stderr.write(err)
raise SystemExit(int(os.environ.get("GH_RC", "0")))
'''


@pytest.fixture
def bpl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh `branch_protection_lib` import with a controllable `gh` stub on PATH."""
    binp = tmp_path / "_bin"
    binp.mkdir()
    gh = binp / "gh"
    gh.write_text(_GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binp}{__import__('os').pathsep}{__import__('os').environ['PATH']}")
    for mod in ("state", "branch_protection_lib"):
        if mod in sys.modules:
            del sys.modules[mod]
    import branch_protection_lib as _bpl  # type: ignore[import-not-found]
    return _bpl


def test_nonzero_exit_prints_rc_and_stderr(bpl, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A non-zero `gh` exit traces `rc=<n> stderr=<text>` on stderr."""
    monkeypatch.setenv("GH_RC", "3")
    monkeypatch.setenv("GH_STDERR", "boom")
    result = bpl.detect_default_branch("o/r")
    assert result is None
    line = capsys.readouterr().err
    assert "detect_default_branch rc=3 stderr=boom" in line


def test_empty_stdout_prints_empty_stdout_reason(bpl, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A clean exit with no output traces `empty-stdout`."""
    monkeypatch.setenv("GH_RC", "0")
    monkeypatch.setenv("GH_STDOUT", "")
    result = bpl.detect_default_branch("o/r")
    assert result is None
    assert "detect_default_branch empty-stdout" in capsys.readouterr().err


@pytest.mark.no_timeout_scale
def test_timeout_prints_timeout_reason(bpl, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A `gh` call that outlives the scaled ceiling traces `timeout after <N>s`.

    Marked `no_timeout_scale`: conftest's `_relax_subprocess_timeouts` seam multiplies every
    timeout by 10x for the suite, which would turn the 0.3s ceiling here into 3s — exactly as
    long as the stub sleeps — and the timeout would never actually expire.
    """
    monkeypatch.setenv("GH_SLEEP", "3")
    monkeypatch.setattr(bpl, "_t", lambda seconds: 0.3)
    result = bpl.detect_default_branch("o/r")
    assert result is None
    assert "detect_default_branch timeout after 0.3s" in capsys.readouterr().err


def test_success_path_prints_nothing(bpl, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A clean, non-empty result prints no stderr trace at all."""
    monkeypatch.setenv("GH_RC", "0")
    monkeypatch.setenv("GH_STDOUT", "main")
    result = bpl.detect_default_branch("o/r")
    assert result == "main"
    assert capsys.readouterr().err == ""


def test_gh_not_on_path_prints_gh_not_on_path_reason(
    bpl, monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path
) -> None:
    """No `gh` binary anywhere on PATH traces `gh-not-on-path` and returns None."""
    empty_bin = tmp_path / "_empty_bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    result = bpl.detect_default_branch("o/r")
    assert result is None
    assert "detect_default_branch gh-not-on-path" in capsys.readouterr().err
