"""Tests for the "SAID OUT LOUD" floor-line rider (TRDD-A70YJLXN box 3).

`version_update_lib.should_emit_floor_line` is the detector's PURE decision point for
whether to announce that a self-update is riding the 4 h unconditional cadence floor
(the ai-maestro server owns the `version-update` chore) instead of the <=15 min
release-triggered flag path. Real function, real boolean inputs — no mocking of the
code under test, matching the pattern in test_ci_status_detector.py.

The last two tests drive the detector's own `main()` (Branch A2 wiring: the `line is
None` guard, the `harness_backend` composition, the dedupe key, the printed text) —
loaded via `importlib.util.spec_from_file_location` since the filename is hyphenated,
same pattern as `test_ci_status_detector.py::_load`. Only COLLABORATORS are
monkeypatched (`vu.list_installed_versions`, `vu.resolve_latest_published`,
`vu._SEMVER_RE` to accept the fake running-dir name, `harness_backend.server_runs_chores`
/ `.claimed_chores`) — the Branch A2 decision code itself runs for real.
"""

from __future__ import annotations

import importlib.util as _u
import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import version_update_lib as vu  # noqa: E402


def test_floor_line_emitted_when_server_owned_and_newer_and_no_flag() -> None:
    """Server claims the chore, a newer release is out, and nothing raised the flag
    yet -> the 4 h floor is the only thing that will pick it up, so say so."""
    assert vu.should_emit_floor_line(
        server_owns_chore=True, newer_available=True, flag_present=False,
    ) is True


def test_floor_line_not_emitted_when_flag_present() -> None:
    """A flag IS raised -> the <=15 min fast path is engaged; nothing new to say."""
    assert vu.should_emit_floor_line(
        server_owns_chore=True, newer_available=True, flag_present=True,
    ) is False


def test_floor_line_not_emitted_when_janitor_owns_the_chore() -> None:
    """The janitor's own daemon still owns `version-update` (server hasn't claimed
    it) -> no floor degradation exists to announce."""
    assert vu.should_emit_floor_line(
        server_owns_chore=False, newer_available=True, flag_present=False,
    ) is False


def test_floor_line_not_emitted_when_no_newer_version() -> None:
    """Cache is already current -> there is no update in flight to be riding
    anything, floor or otherwise."""
    assert vu.should_emit_floor_line(
        server_owns_chore=True, newer_available=False, flag_present=False,
    ) is False


# ---------- main() wiring (Branch A2) --------------------------------------

_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "version-update.py"


def _load_detector():
    """Import the hyphen-named detector module by path (not a valid import name)."""
    spec = _u.spec_from_file_location("janitor_version_update_under_test", str(_DETECTOR))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated project/global-state/control dirs; fresh library modules per test —
    mirrors tests/test_version_update_daemon.py::env."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    for mod_name in ("state", "global_state", "harness_backend", "version_update_lib", "dedupe"):
        sys.modules.pop(mod_name, None)
    return tmp_path


def _rig_detector(mod, monkeypatch: pytest.MonkeyPatch, *, installed: str, published: str) -> None:
    """Fake the marketplace/installed versions + the server-ownership probe — the only
    collaborators, never the Branch A2 decision code itself."""
    monkeypatch.setattr(mod.vu, "_SEMVER_RE", re.compile(r".*"))  # accept the real repo dirname as "installed"
    monkeypatch.setattr(mod.vu, "list_installed_versions", lambda *_a, **_kw: [installed])
    monkeypatch.setattr(mod.vu, "resolve_latest_published", lambda *_a, **_kw: published)
    monkeypatch.setattr(mod.harness_backend, "server_runs_chores", lambda *_a, **_kw: True)
    monkeypatch.setattr(
        mod.harness_backend, "claimed_chores", lambda *_a, **_kw: frozenset({"version-update"}),
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE", "true")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER", "false")  # disable the flag-raise branch


def test_main_prints_floor_line_when_server_owned_newer_and_no_flag(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Server owns the chore, a newer release is out, the flag-raise branch is off
    (opted out) -> `main()` prints the floor line exactly once, with the real text."""
    mod = _load_detector()
    _rig_detector(mod, monkeypatch, installed="0.5.0", published="0.6.0")

    rc = mod.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("rides the 4 h cadence floor") == 1
    assert "0.5.0 -> 0.6.0 detected" in out
    assert "not the <=15 min flag path" in out


def test_main_suppresses_floor_line_when_flag_already_present(
    env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Same server-owned + newer setup, but the fast-path flag is ALREADY raised ->
    the <=15 min path is engaged, so `main()` prints nothing about the floor."""
    mod = _load_detector()
    _rig_detector(mod, monkeypatch, installed="0.5.0", published="0.6.0")
    mod.gs.request_version_update("pre-existing request")

    rc = mod.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert "rides the 4 h cadence floor" not in out
