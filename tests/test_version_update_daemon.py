"""Tests for the daemon-owned janitor self-update path (TRDD-be2efa56 §9).

The auto-update branch moved from scripts/detectors/version-update.py into
scripts/daemon.py::task_version_update. These tests cover:

* `version_update_lib.do_auto_update_if_needed` — the wrapper the daemon
  calls. Tests stub out `attempt_auto_update` + cache listing so no real
  `claude` / `gh` subprocess fires.
* The detector now emits the manual-nudge line ONLY when
  `auto_update_on_new_release` is OFF; when ON (the default) it stays
  silent because the daemon is the writer.

The daemon-process integration (spawn → flock → run task) lives in
test_daemon.py — those tests would need a richer `claude` stub to
exercise this new task end-to-end without network. Here we stay
in-process for precision.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test tmp dirs for project + global state; reload modules."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    for mod in ("state", "global_state", "version_update_lib"):
        if mod in sys.modules:
            del sys.modules[mod]
    return tmp_path


def _vu():
    import version_update_lib  # type: ignore[import-not-found]
    return version_update_lib


def _make_cache(parent: Path, versions: list[str]) -> None:
    """Build a fake `<plugin>/<version>/` cache layout under `parent`."""
    for v in versions:
        (parent / v).mkdir(parents=True, exist_ok=True)


def _make_plugin_root(parent: Path, version: str, repo_url: str | None = None) -> Path:
    """Create a plugin.json under the version dir; return the version dir."""
    vdir = parent / version
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / ".claude-plugin").mkdir(exist_ok=True)
    payload: dict[str, str] = {"name": "ai-maestro-janitor", "version": version}
    if repo_url:
        payload["repository"] = repo_url
    import json
    (vdir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )
    return vdir


# ---------- version_update_lib helpers -----------------------------------

def test_semver_tuple_orders_correctly(env: Path) -> None:
    vu = _vu()
    assert vu._semver_tuple("0.5.0") < vu._semver_tuple("0.5.1")
    assert vu._semver_tuple("0.5.0") < vu._semver_tuple("1.0.0")
    assert vu._semver_tuple("not-a-version") == (-1,)


def test_list_installed_versions_filters_and_sorts(env: Path) -> None:
    vu = _vu()
    cache_parent = env / "cache"
    _make_cache(cache_parent, ["0.4.13", "0.5.0", "0.4.0", "garbage", "0.10.0"])
    versions = vu.list_installed_versions(cache_parent)
    assert versions == ["0.4.0", "0.4.13", "0.5.0", "0.10.0"]


def test_list_installed_versions_empty_when_dir_missing(env: Path) -> None:
    vu = _vu()
    assert vu.list_installed_versions(env / "nonexistent") == []


def test_resolve_latest_published_returns_none_when_no_manifest(env: Path) -> None:
    vu = _vu()
    cache_parent = env / "cache"
    vdir = cache_parent / "0.5.0"
    vdir.mkdir(parents=True)
    # No .claude-plugin/plugin.json
    assert vu.resolve_latest_published(vdir) is None


def test_resolve_latest_published_returns_none_when_no_repo_url(env: Path) -> None:
    vu = _vu()
    vdir = _make_plugin_root(env / "cache", "0.5.0")  # no repository field
    assert vu.resolve_latest_published(vdir) is None


# ---------- do_auto_update_if_needed --------------------------------------

def test_do_auto_update_silent_when_cache_matches_github(
    env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vu = _vu()
    vdir = _make_plugin_root(
        env / "cache", "0.5.0", "https://github.com/Emasoft/ai-maestro-janitor",
    )
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root: "0.5.0")
    logs: list[str] = []
    updated, latest = vu.do_auto_update_if_needed(vdir, logs.append)
    assert updated is False
    assert latest == "0.5.0"
    # No attempt_auto_update was invoked → no auto-update log line.
    assert not any("auto-update:" in line for line in logs)


def test_do_auto_update_silent_when_cache_ahead_of_github(
    env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-release cache (built locally) must NOT downgrade."""
    vu = _vu()
    vdir = _make_plugin_root(
        env / "cache", "0.6.0-dev", "https://github.com/Emasoft/ai-maestro-janitor",
    )
    # Make the cache parent show only valid semver dirs:
    (env / "cache" / "0.6.0").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root: "0.5.0")
    logs: list[str] = []
    updated, _ = vu.do_auto_update_if_needed(vdir, logs.append)
    assert updated is False


def test_do_auto_update_runs_when_cache_behind_github(
    env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cache < GitHub, attempt_auto_update IS called; cache advance
    is detected via re-listing the parent."""
    vu = _vu()
    cache_parent = env / "cache"
    vdir = _make_plugin_root(cache_parent, "0.5.0", "https://github.com/Emasoft/ai-maestro-janitor")
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root: "0.5.1")

    # Simulate the auto-update creating the new version dir.
    def _fake_attempt(_log: object, _path: object = None) -> bool:
        (cache_parent / "0.5.1").mkdir(parents=True, exist_ok=True)
        return True
    monkeypatch.setattr(vu, "attempt_auto_update", _fake_attempt)

    updated, latest = vu.do_auto_update_if_needed(vdir, lambda _m: None)
    assert updated is True
    assert latest == "0.5.1"


def test_do_auto_update_treats_no_cache_advance_as_failure(
    env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI may exit 0 without downloading the new version — treat as failure."""
    vu = _vu()
    cache_parent = env / "cache"
    vdir = _make_plugin_root(cache_parent, "0.5.0", "https://github.com/Emasoft/ai-maestro-janitor")
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root: "0.5.1")
    monkeypatch.setattr(vu, "attempt_auto_update", lambda _log, _path=None: True)  # but no new dir
    logs: list[str] = []
    updated, _ = vu.do_auto_update_if_needed(vdir, logs.append)
    assert updated is False
    assert any("did not advance" in line for line in logs)


def test_do_auto_update_silent_when_attempt_returns_false(
    env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vu = _vu()
    cache_parent = env / "cache"
    vdir = _make_plugin_root(cache_parent, "0.5.0", "https://github.com/Emasoft/ai-maestro-janitor")
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root: "0.5.1")
    monkeypatch.setattr(vu, "attempt_auto_update", lambda _log, _path=None: False)
    updated, latest = vu.do_auto_update_if_needed(vdir, lambda _m: None)
    assert updated is False
    assert latest == "0.5.0"


class _Proc:
    def __init__(self, rc: int, out: str = "") -> None:
        self.returncode = rc
        self.stdout = out


def test_auto_update_skips_when_no_scope_detected(
    env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scope invariant: when no install scope is detected, the self-update is
    SKIPPED (returns False) and NO scope-less `claude plugin update` is run — the
    marketplace refresh is the only subprocess."""
    vu = _vu()
    calls: list[list[str]] = []
    monkeypatch.setattr(vu.shutil, "which", lambda _x: "/usr/bin/claude")
    monkeypatch.setattr(vu.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _Proc(0))[1])
    monkeypatch.setattr(vu, "detect_install_scopes", lambda: [])
    logs: list[str] = []

    result = vu.attempt_auto_update(logs.append)

    assert result is False
    update_calls = [c for c in calls if c[:3] == ["claude", "plugin", "update"]]
    assert update_calls == [], f"a scope-less plugin update was attempted: {update_calls}"
    assert any("SKIPPING self-update" in m for m in logs)


def test_auto_update_passes_exact_scope_per_detected_scope(
    env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One `claude plugin update … --scope <s>` per detected scope, never scope-less."""
    vu = _vu()
    calls: list[list[str]] = []
    monkeypatch.setattr(vu.shutil, "which", lambda _x: "/usr/bin/claude")
    monkeypatch.setattr(
        vu.subprocess, "run",
        lambda cmd, **kw: (calls.append(cmd), _Proc(0, "updated from 0.1.0 to 0.2.0"))[1],
    )
    monkeypatch.setattr(vu, "detect_install_scopes", lambda: ["user", "local"])

    result = vu.attempt_auto_update(lambda _m: None)

    assert result is True
    update_calls = [c for c in calls if c[:3] == ["claude", "plugin", "update"]]
    assert len(update_calls) == 2
    assert update_calls[0][-2:] == ["--scope", "user"]
    assert update_calls[1][-2:] == ["--scope", "local"]
    assert all("--scope" in c for c in update_calls)


# ── install scope comes from the REGISTRY, not from settings.json ─────────────
#
# THE INCIDENT (janitor#147). `detect_install_scopes` substring-matched
# `~/.claude/settings.json` and reported `user` on a host whose four installs
# were all `local`, so every self-update ran `--scope user`, died with "not
# installed at scope user", and logged it at debug level. Six releases shipped
# while the machine stayed on 0.60.1. `enabledPlugins` records ENABLEMENT;
# `installed_plugins.json` records INSTALLATION, and only the latter governs
# `claude plugin update`.


def _registry(home: Path, records: list[dict]) -> None:
    vu = _vu()
    p = home / ".claude" / "plugins" / "installed_plugins.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "version": 1,
        "plugins": {f"{vu.PLUGIN_NAME}@{vu.MARKETPLACE_NAME}": records},
    }), encoding="utf-8")


def _enabled_at_user(home: Path) -> None:
    """The settings shape that misled the old heuristic: enabled, NOT installed."""
    vu = _vu()
    p = home / ".claude" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "enabledPlugins": {f"{vu.PLUGIN_NAME}@{vu.MARKETPLACE_NAME}": True},
    }), encoding="utf-8")


def test_registry_wins_over_an_enabled_but_not_installed_user_entry(env, tmp_path, monkeypatch):
    """Enabled at user + installed only at local → `local`, never `user`.

    This is the exact live configuration that broke self-update: updating the
    scope where the plugin is merely ENABLED fails, because nothing is installed
    there to update.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _enabled_at_user(tmp_path)
    _registry(tmp_path, [
        {"scope": "local", "version": "0.60.1", "projectPath": "/w/a"},
        {"scope": "local", "version": "0.64.1", "projectPath": "/w/b"},
    ])
    assert _vu().detect_install_scopes() == ["local"]


def test_registry_scopes_are_deduped_and_broadest_first(env, tmp_path, monkeypatch):
    """Several installs per scope collapse to one entry each, user → local → project."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _registry(tmp_path, [
        {"scope": "project"}, {"scope": "local"}, {"scope": "local"}, {"scope": "user"},
    ])
    assert _vu().detect_install_scopes() == ["user", "local", "project"]


def test_unknown_scope_name_is_kept_not_silently_dropped(env, tmp_path, monkeypatch):
    """A scope we do not recognise is still a real install we must not skip."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _registry(tmp_path, [{"scope": "user"}, {"scope": "enterprise"}])
    assert _vu().detect_install_scopes() == ["user", "enterprise"]


def test_falls_back_to_settings_when_the_registry_is_missing(env, tmp_path, monkeypatch):
    """No registry → the old heuristic, because a weak answer beats no self-update."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    _enabled_at_user(tmp_path)
    assert _vu().detect_install_scopes() == ["user"]


def test_malformed_registry_degrades_and_never_raises(env, tmp_path, monkeypatch):
    """A corrupt registry must not break the daemon's update beat."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    p = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    assert _vu().registry_install_records() == []
    assert _vu().detect_install_scopes() == []
