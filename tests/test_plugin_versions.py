"""Tests for scripts/lib/plugin_versions.py — the `[janitor-reload]` relevance-gate snapshot.

Real tmp_path filesystem trees throughout — never the real ~/.claude cache or settings.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import plugin_versions  # noqa: E402


def _cache_with(cache_root: Path, plugin_key: str, *versions: str) -> None:
    name, _, marketplace = plugin_key.partition("@")
    for v in versions:
        (cache_root / marketplace / name / v).mkdir(parents=True, exist_ok=True)


def _settings_with(path: Path, enabled: dict[str, bool]) -> None:
    path.write_text(json.dumps({"enabledPlugins": enabled}))


def test_newest_cached_version_picks_highest_numeric_including_double_digits(tmp_path: Path) -> None:
    """3.4.10 must sort ABOVE 3.4.9 — plain string sort would get this backwards."""
    _cache_with(tmp_path, "foo@mp", "3.4.9", "3.4.10", "3.4.2")
    assert plugin_versions.newest_cached_version(tmp_path, "foo@mp") == "3.4.10"


def test_newest_cached_version_none_when_uncached(tmp_path: Path) -> None:
    """No cache dir for the plugin at all → None, not a raise."""
    assert plugin_versions.newest_cached_version(tmp_path, "foo@mp") is None


def test_newest_cached_version_none_on_malformed_key(tmp_path: Path) -> None:
    """A plugin key missing the `@marketplace` suffix is malformed input, not a crash."""
    assert plugin_versions.newest_cached_version(tmp_path, "foo-no-at-sign") is None


def test_snapshot_enabled_maps_only_true_plugins_with_a_cache_hit(tmp_path: Path) -> None:
    """Only `True`-enabled plugins with a real cache dir make it into the snapshot."""
    cache = tmp_path / "cache"
    settings = tmp_path / "settings.json"
    _cache_with(cache, "foo@mp", "1.0.0")
    _settings_with(settings, {"foo@mp": True, "bar@mp": False, "baz@mp": True})
    # baz@mp has no cache dir — must be omitted, not raise.
    snap = plugin_versions.snapshot_enabled(settings, cache)
    assert snap == {"foo@mp": "1.0.0"}


def test_write_then_read_snapshot_roundtrips(tmp_path: Path) -> None:
    path = tmp_path / "plugins-at-start.json"
    plugin_versions.write_snapshot(path, {"foo@mp": "1.0.0"})
    assert plugin_versions.read_snapshot(path) == {"foo@mp": "1.0.0"}


def test_read_snapshot_none_on_absent_file(tmp_path: Path) -> None:
    assert plugin_versions.read_snapshot(tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    "content",
    ["not json at all", json.dumps({"epoch": 1}), json.dumps({"versions": "not-a-dict"}), json.dumps({"versions": {"foo@mp": 1}}), json.dumps([1, 2, 3])],
)
def test_read_snapshot_none_on_malformed_content(tmp_path: Path, content: str) -> None:
    """Malformed/missing `versions`, a non-dict `versions`, or a non-string value all
    read as None — a snapshot fault must fall back to legacy behaviour, never raise."""
    path = tmp_path / "snap.json"
    path.write_text(content)
    assert plugin_versions.read_snapshot(path) is None


def test_changed_since_empty_when_nothing_moved(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    settings = tmp_path / "settings.json"
    _cache_with(cache, "foo@mp", "1.0.0")
    _settings_with(settings, {"foo@mp": True})
    snapshot = {"foo@mp": "1.0.0"}
    assert plugin_versions.changed_since(snapshot, settings, cache) == {}


def test_changed_since_reports_a_real_version_delta(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    settings = tmp_path / "settings.json"
    _cache_with(cache, "foo@mp", "1.0.0", "1.1.0")
    _settings_with(settings, {"foo@mp": True})
    snapshot = {"foo@mp": "1.0.0"}
    assert plugin_versions.changed_since(snapshot, settings, cache) == {"foo@mp": ("1.0.0", "1.1.0")}


def test_changed_since_treats_a_newly_enabled_plugin_as_changed(tmp_path: Path) -> None:
    """A plugin enabled AFTER the snapshot was taken — absent from `snapshot` — counts as
    changed, with old reported as the sentinel "?" (it was not tracked at session start)."""
    cache = tmp_path / "cache"
    settings = tmp_path / "settings.json"
    _cache_with(cache, "new@mp", "2.0.0")
    _settings_with(settings, {"new@mp": True})
    assert plugin_versions.changed_since({}, settings, cache) == {"new@mp": ("?", "2.0.0")}
