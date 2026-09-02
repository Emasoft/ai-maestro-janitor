"""settings.json → in-memory options mirror for the launchd daemon lane (TRDD-XCJFCJUX).

launchd starts the daemon with launchd's own environment, so none of the session
harness's settings.json ``env`` block reaches it. `plugin_option()`/`plugin_options_env()`
read a module-level dict mirror — never os.environ — because CPV's security gate blocks
any dynamic `os.environ[key] = value` write (ENV_INJECTION, MAJOR). These tests exercise
the loader against real tmp_path settings files only — never the machine's real
~/.claude/settings.json.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import state  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_loader_state() -> Iterator[None]:
    """Each test starts with an empty mirror and no remembered mtime."""
    state._SETTINGS_OPTIONS.clear()
    state._SETTINGS_MTIME_NS = None
    yield
    state._SETTINGS_OPTIONS.clear()
    state._SETTINGS_MTIME_NS = None


def _write_settings(path: Path, env: dict) -> None:
    path.write_text(json.dumps({"env": env}), encoding="utf-8")


def test_only_plugin_option_keys_land(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-CLAUDE_PLUGIN_OPTION_ key in the settings env block is never mirrored."""
    settings = tmp_path / "settings.json"
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "yes", "SOME_OTHER_VAR": "nope"})
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FOO", raising=False)
    monkeypatch.delenv("SOME_OTHER_VAR", raising=False)

    count = state.load_plugin_options_from_settings(settings)

    assert count == 1
    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_FOO") == "yes"
    assert "CLAUDE_PLUGIN_OPTION_FOO" not in os.environ
    assert "SOME_OTHER_VAR" not in os.environ


def test_real_env_value_wins_over_mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A key already set by the real environment wins over the settings file value."""
    settings = tmp_path / "settings.json"
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "from-file"})
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FOO", "from-real-env")

    state.load_plugin_options_from_settings(settings)

    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_FOO") == "from-real-env"


def test_real_env_wins_even_when_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An EMPTY real env value still wins over a non-empty mirror value — presence, not truthiness."""
    settings = tmp_path / "settings.json"
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "from-file"})
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FOO", "")

    state.load_plugin_options_from_settings(settings)

    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_FOO") == ""


def test_plugin_options_env_omits_real_env_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child-env merge must not re-add a mirror entry already real in this process's env."""
    settings = tmp_path / "settings.json"
    _write_settings(
        settings,
        {"CLAUDE_PLUGIN_OPTION_FOO": "from-file", "CLAUDE_PLUGIN_OPTION_BAR": "from-file-bar"},
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FOO", "from-real-env")
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_BAR", raising=False)

    state.load_plugin_options_from_settings(settings)
    child_env = state.plugin_options_env()

    assert "CLAUDE_PLUGIN_OPTION_FOO" not in child_env
    assert child_env["CLAUDE_PLUGIN_OPTION_BAR"] == "from-file-bar"


def test_reload_updates_and_drops_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A changed file value shows through plugin_option() after reload; a removed key disappears."""
    settings = tmp_path / "settings.json"
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FOO", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_BAR", raising=False)
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "1", "CLAUDE_PLUGIN_OPTION_BAR": "2"})
    state.load_plugin_options_from_settings(settings)
    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_FOO") == "1"
    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_BAR") == "2"

    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "9"})
    state.load_plugin_options_from_settings(settings)

    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_FOO") == "9"
    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_BAR") is None


def test_missing_file_returns_zero_and_leaves_mirror_untouched(tmp_path: Path) -> None:
    """A missing settings file returns 0 and never wipes what was already loaded."""
    settings = tmp_path / "settings.json"
    real = tmp_path / "real.json"
    _write_settings(real, {"CLAUDE_PLUGIN_OPTION_FOO": "kept"})
    state.load_plugin_options_from_settings(real)

    count = state.load_plugin_options_from_settings(settings)

    assert count == 0
    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_FOO") == "kept"


def test_malformed_json_returns_zero_and_leaves_mirror_untouched(tmp_path: Path) -> None:
    """A malformed JSON settings file returns 0 and never wipes what was already loaded."""
    real = tmp_path / "real.json"
    _write_settings(real, {"CLAUDE_PLUGIN_OPTION_FOO": "kept"})
    state.load_plugin_options_from_settings(real)

    broken = tmp_path / "broken.json"
    broken.write_text("{not valid json", encoding="utf-8")

    count = state.load_plugin_options_from_settings(broken)

    assert count == 0
    assert state.plugin_option("CLAUDE_PLUGIN_OPTION_FOO") == "kept"


def test_refresh_detects_mtime_change(tmp_path: Path) -> None:
    """refresh_plugin_options_if_changed is True on first call and after an mtime bump, else False."""
    settings = tmp_path / "settings.json"
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "1"})

    assert state.refresh_plugin_options_if_changed(settings) is True
    assert state.refresh_plugin_options_if_changed(settings) is False

    stat = settings.stat()
    os.utime(settings, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert state.refresh_plugin_options_if_changed(settings) is True


def test_is_truthy_env_honours_mirror_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """is_truthy_env falls back to the mirror when the real env lacks the key."""
    settings = tmp_path / "settings.json"
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FLAG": "false"})
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FLAG", raising=False)

    state.load_plugin_options_from_settings(settings)

    assert state.is_truthy_env("CLAUDE_PLUGIN_OPTION_FLAG", True) is False
