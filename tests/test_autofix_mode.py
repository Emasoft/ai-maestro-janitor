"""Tests for the autofix-mode toggle (state.autofix_mode + dispatch reminder).

The two slash commands `/janitor-autofix-on` and `/janitor-autofix-off`
write `.janitor/state/autofix-mode.txt` and the dispatcher surfaces a
once-per-day `[autofix-off]` reminder while the OFF sentinel is set.
These tests exercise the state helpers directly + the dispatch phase
through its in-process entry point.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def project_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CLAUDE_PROJECT_DIR at tmp_path; reload state + dispatch modules."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for mod in ("state", "dispatch", "dedupe"):
        if mod in sys.modules:
            del sys.modules[mod]
    return tmp_path


def _import_state():
    import state  # type: ignore[import-not-found]
    return state


def _import_dispatch():
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "janitor_dispatch_under_test", str(_PROJECT_ROOT / "scripts" / "dispatch.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture_stdout(fn) -> str:
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


# ---------- state.autofix_mode / _enabled / _disabled ---------------------

def test_autofix_mode_defaults_to_on_when_sentinel_absent(project_env: Path) -> None:
    s = _import_state()
    s.init_state()
    assert s.autofix_mode() == "on"
    assert s.autofix_enabled() is True
    assert s.autofix_disabled() is False


def test_autofix_mode_off_when_sentinel_contains_off(project_env: Path) -> None:
    s = _import_state()
    s.init_state()
    (s.state_dir() / "autofix-mode.txt").write_text("off", encoding="utf-8")
    assert s.autofix_mode() == "off"
    assert s.autofix_enabled() is False
    assert s.autofix_disabled() is True


def test_autofix_mode_off_is_case_insensitive_with_whitespace(project_env: Path) -> None:
    """`/janitor-autofix-off` writes the value, but a human-edited file
    might have stray case / whitespace. Accept those forms too."""
    s = _import_state()
    s.init_state()
    for raw in ("off\n", "OFF", " off ", "Off\n  "):
        (s.state_dir() / "autofix-mode.txt").write_text(raw, encoding="utf-8")
        assert s.autofix_mode() == "off", f"failed on {raw!r}"


def test_autofix_mode_on_when_sentinel_contains_anything_else(project_env: Path) -> None:
    """Garbage / typos in the sentinel default to ON (safer fallback)."""
    s = _import_state()
    s.init_state()
    for raw in ("on", "ON", "1", "true", "yes", "", "garbage", "0"):
        (s.state_dir() / "autofix-mode.txt").write_text(raw, encoding="utf-8")
        assert s.autofix_mode() == "on", f"failed on {raw!r}"


# ---------- dispatch phase: autofix-off daily reminder --------------------

def test_phase_silent_when_autofix_on(project_env: Path) -> None:
    """No sentinel / sentinel says "on" → no marker emitted."""
    s = _import_state()
    s.init_state()
    dispatch = _import_dispatch()
    out = _capture_stdout(dispatch._phase_autofix_mode_reminder)
    assert out == "", f"phase must be silent when autofix is ON, got {out!r}"


def test_phase_emits_line_when_autofix_off(project_env: Path) -> None:
    """OFF sentinel → exactly one [autofix-off] drift line on first fire."""
    s = _import_state()
    s.init_state()
    (s.state_dir() / "autofix-mode.txt").write_text("off", encoding="utf-8")
    dispatch = _import_dispatch()
    out = _capture_stdout(dispatch._phase_autofix_mode_reminder)
    assert out.startswith("[autofix-off]"), \
        f"phase must emit a single [autofix-off] line, got {out!r}"
    assert "/janitor-autofix-on" in out


def test_phase_deduplicates_within_same_day(project_env: Path) -> None:
    """Repeated heartbeats inside the same date bucket emit at most once."""
    s = _import_state()
    s.init_state()
    (s.state_dir() / "autofix-mode.txt").write_text("off", encoding="utf-8")
    dispatch = _import_dispatch()
    first = _capture_stdout(dispatch._phase_autofix_mode_reminder)
    second = _capture_stdout(dispatch._phase_autofix_mode_reminder)
    third = _capture_stdout(dispatch._phase_autofix_mode_reminder)
    assert first.startswith("[autofix-off]")
    assert second == ""
    assert third == ""
