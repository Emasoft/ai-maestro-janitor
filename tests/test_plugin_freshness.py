"""Tests for the plugin-freshness helper (issue #69, TRDD-YF4NDYYE).

Real fixtures, no mocks of the unit under test: fake plugin trees + a fake
installed_plugins.json under the isolated HOME; only the NETWORK probe
(version_update_lib.resolve_latest_published) is stubbed — offline behavior is the
point of half these tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import plugin_freshness as pf  # noqa: E402

_NOW = 1_700_000_000


def _mk_plugin(root: Path, name: str, version: str) -> Path:
    d = root / ".claude-plugin"
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps({"name": name, "version": version, "repository": f"github.com/x/{name}"}),
        encoding="utf-8",
    )
    return root


def _cache_tree(base: Path, marketplace: str, name: str, version: str) -> Path:
    """A plugin dir at the REAL cache shape .../cache/<marketplace>/<name>/<version>."""
    root = base / "cache" / marketplace / name / version
    return _mk_plugin(root, name, version)


def _write_pin(home: Path, name: str, marketplace: str, version: str) -> None:
    p = home / ".claude" / "plugins" / "installed_plugins.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    # The legacy installed_plugins.json shape keys the version dir as `path`; the current one
    # uses `installPath` + an explicit `version`. cache_prune.pinned_versions_for reads both.
    p.write_text(
        json.dumps(
            {"plugins": {f"{name}@{marketplace}": [{"path": f"cache/{marketplace}/{name}/{version}"}]}}
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    """Default every test to OFFLINE; tests that want a 'published' answer re-patch."""
    monkeypatch.setattr(pf.version_update_lib, "resolve_latest_published", lambda _root: None)


def test_stale_when_cache_diverges_from_pin(tmp_path, monkeypatch):
    """cache 1.0.0 vs pin 1.2.0 → is_stale, and the header carries the STALE banner."""
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    root = _cache_tree(home, "mkt", "demo-plugin", "1.0.0")
    _write_pin(home, "demo-plugin", "mkt", "1.2.0")
    f = pf.freshness(root, now=_NOW)
    assert f["cached_version"] == "1.0.0"
    assert f["installed_pins"] == ["1.2.0"]
    assert f["is_stale"] is True
    assert "STALE" in pf.header(root, now=_NOW)


def test_fresh_when_cache_matches_pin_offline(tmp_path, monkeypatch):
    """cache == pin, latest unknown (offline) → NOT stale; header says latest unknown."""
    monkeypatch.setenv("HOME", str(tmp_path))
    root = _cache_tree(tmp_path, "mkt", "demo-plugin", "1.2.0")
    _write_pin(tmp_path, "demo-plugin", "mkt", "1.2.0")
    f = pf.freshness(root, now=_NOW)
    assert f["is_stale"] is False
    h = pf.header(root, now=_NOW)
    assert "audited demo-plugin@1.2.0" in h and "latest unknown" in h and "STALE" not in h


def test_offline_and_pinless_never_marks_stale(tmp_path, monkeypatch):
    """No pin file + no network → every comparator unknown → fail-open NOT stale."""
    monkeypatch.setenv("HOME", str(tmp_path))
    root = _mk_plugin(tmp_path / "somewhere" / "repo", "loose-plugin", "0.9.0")
    f = pf.freshness(root, now=_NOW)
    assert f == {
        "plugin": "loose-plugin",
        "cached_version": "0.9.0",
        "installed_pins": [],
        "latest_published": None,
        "is_stale": False,
    }


def test_a_cache_matching_ANY_record_is_not_stale(tmp_path, monkeypatch):
    """Multi-record host: the audited tree matches one of several pins → NOT stale (#137).

    The scalar predecessor compared against whichever record was listed first, so on a host
    spanning two versions this both false-alarmed and false-cleared depending on list order.
    The audited code is live if ANY record loads it.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    root = _cache_tree(tmp_path, "mkt", "demo-plugin", "0.64.1")
    p = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "plugins": {
                    "demo-plugin@mkt": [
                        {"installPath": "/c/demo-plugin/0.60.1", "version": "0.60.1"},
                        {"installPath": "/c/demo-plugin/0.64.1", "version": "0.64.1"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    f = pf.freshness(root, now=_NOW)

    assert f["installed_pins"] == ["0.60.1", "0.64.1"]   # sorted, both reported
    assert f["is_stale"] is False                        # 0.64.1 IS in use
    assert "pin 0.60.1, 0.64.1" in pf.header(root, now=_NOW)


def test_stale_when_newer_release_published(tmp_path, monkeypatch):
    """cache == pin but a NEWER release exists → stale (audit would miss live fixes)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    root = _cache_tree(tmp_path, "mkt", "demo-plugin", "1.2.0")
    _write_pin(tmp_path, "demo-plugin", "mkt", "1.2.0")
    monkeypatch.setattr(pf.version_update_lib, "resolve_latest_published", lambda _root: "1.3.0")
    f = pf.freshness(root, now=_NOW)
    assert f["latest_published"] == "1.3.0"
    assert f["is_stale"] is True


def test_latest_release_probe_is_ttl_cached(tmp_path, monkeypatch):
    """The network probe fires ONCE inside the TTL window — the second call answers
    from the global-state cache file (cadence-limited by design, issue #69)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    root = _cache_tree(tmp_path, "mkt", "demo-plugin", "1.2.0")
    calls: list[int] = []

    def probe(_root):
        calls.append(1)
        return "1.3.0"

    monkeypatch.setattr(pf.version_update_lib, "resolve_latest_published", probe)
    assert pf.latest_published(root, now=_NOW) == "1.3.0"
    assert pf.latest_published(root, now=_NOW + 60) == "1.3.0"  # within TTL → cached
    assert len(calls) == 1
    assert pf.latest_published(root, now=_NOW + pf._DEFAULT_TTL_S + 1) == "1.3.0"  # expired → re-probe
    assert len(calls) == 2


def test_ttl_zero_disables_network_probe(tmp_path, monkeypatch):
    """CLAUDE_PLUGIN_OPTION_FRESHNESS_TTL_S=0 → no network at all, latest=None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FRESHNESS_TTL_S", "0")
    root = _cache_tree(tmp_path, "mkt", "demo-plugin", "1.2.0")

    def boom(_root):  # the probe must never be reached
        raise AssertionError("network probe called with TTL 0")

    monkeypatch.setattr(pf.version_update_lib, "resolve_latest_published", boom)
    assert pf.latest_published(root, now=_NOW) is None


def test_missing_plugin_json_is_graceful(tmp_path, monkeypatch):
    """A root with no plugin.json yields unknowns, never a crash."""
    monkeypatch.setenv("HOME", str(tmp_path))
    f = pf.freshness(tmp_path / "empty", now=_NOW)
    assert f["cached_version"] is None and f["is_stale"] is False
