"""settings.json → os.environ mirror for the launchd daemon lane (TRDD-XCJFCJUX).

launchd starts the daemon with launchd's own environment, so none of the session
harness's settings.json ``env`` block reaches it. These tests exercise the loader
against real tmp_path settings files only — never the machine's real
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
    """Each test starts with no injected keys and no remembered mtime."""
    state._SETTINGS_INJECTED.clear()
    state._SETTINGS_MTIME_NS = None
    yield
    state._SETTINGS_INJECTED.clear()
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
    assert os.environ["CLAUDE_PLUGIN_OPTION_FOO"] == "yes"
    assert "SOME_OTHER_VAR" not in os.environ


def test_real_env_value_is_not_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A key already set by the real environment wins over the settings file value."""
    settings = tmp_path / "settings.json"
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "from-file"})
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FOO", "from-real-env")

    count = state.load_plugin_options_from_settings(settings)

    assert count == 0
    assert os.environ["CLAUDE_PLUGIN_OPTION_FOO"] == "from-real-env"


def test_changed_file_value_updates_an_injected_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-loading after the file changes updates a key the loader itself injected."""
    settings = tmp_path / "settings.json"
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "v1"})
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FOO", raising=False)
    state.load_plugin_options_from_settings(settings)
    assert os.environ["CLAUDE_PLUGIN_OPTION_FOO"] == "v1"

    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "v2"})
    state.load_plugin_options_from_settings(settings)

    assert os.environ["CLAUDE_PLUGIN_OPTION_FOO"] == "v2"


def test_key_removed_from_file_is_dropped_but_real_env_key_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key the loader injected disappears from os.environ once the file drops it."""
    settings = tmp_path / "settings.json"
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FOO", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REAL", "kept")
    _write_settings(
        settings,
        {"CLAUDE_PLUGIN_OPTION_FOO": "v1", "CLAUDE_PLUGIN_OPTION_REAL": "ignored-by-loader"},
    )
    state.load_plugin_options_from_settings(settings)
    assert os.environ["CLAUDE_PLUGIN_OPTION_FOO"] == "v1"
    assert os.environ["CLAUDE_PLUGIN_OPTION_REAL"] == "kept"

    _write_settings(settings, {})
    state.load_plugin_options_from_settings(settings)

    assert "CLAUDE_PLUGIN_OPTION_FOO" not in os.environ
    assert os.environ["CLAUDE_PLUGIN_OPTION_REAL"] == "kept"


def test_missing_file_and_malformed_json_return_zero_and_leave_environ_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing or malformed settings file is a no-op, never a crash."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FOO", raising=False)
    missing = tmp_path / "does-not-exist.json"

    assert state.load_plugin_options_from_settings(missing) == 0
    assert "CLAUDE_PLUGIN_OPTION_FOO" not in os.environ

    malformed = tmp_path / "settings.json"
    malformed.write_text("{not json", encoding="utf-8")

    assert state.load_plugin_options_from_settings(malformed) == 0
    assert "CLAUDE_PLUGIN_OPTION_FOO" not in os.environ


def test_refresh_only_reloads_when_mtime_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """refresh_plugin_options_if_changed() is True on first call and after an mtime bump only."""
    settings = tmp_path / "settings.json"
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FOO", raising=False)
    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "v1"})

    assert state.refresh_plugin_options_if_changed(settings) is True
    assert os.environ["CLAUDE_PLUGIN_OPTION_FOO"] == "v1"
    assert state.refresh_plugin_options_if_changed(settings) is False

    _write_settings(settings, {"CLAUDE_PLUGIN_OPTION_FOO": "v2"})
    stat = settings.stat()
    os.utime(settings, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))

    assert state.refresh_plugin_options_if_changed(settings) is True
    assert os.environ["CLAUDE_PLUGIN_OPTION_FOO"] == "v2"
