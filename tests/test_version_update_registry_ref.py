"""TRDD-ADFIO49Q: the update check compares GitHub against the USER-scope registry version,
not the highest plugin-cache dir. A publish smoke install put 3.9.5 in the cache while the
user-scope install stayed on 3.9.4, so the cache-only check read "current" and never updated.

The registry is a real `installed_plugins.json` under a tmp HOME (registry_path() reads
Path.home()). Stubbed: resolve_latest_published (GitHub),
attempt_auto_update (`claude plugin update`), and for the detector tests the cache listing, the
ai-maestro server probe, and _SEMVER_RE widened so the repo checkout counts as a cache install."""

from __future__ import annotations

import importlib.util as _u
import json
import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _vu():
    import version_update_lib  # type: ignore[import-not-found]
    return version_update_lib


def _write_registry(home: Path, records: object) -> None:
    """Write a real installed_plugins.json holding `records` for this plugin."""
    vu = _vu()
    path = home / ".claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    key = f"{vu.PLUGIN_NAME}@{vu.MARKETPLACE_NAME}"
    path.write_text(json.dumps({"version": 2, "plugins": {key: records}}), encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp HOME so registry_path() resolves a registry this test owns."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_registered_user_version_reads_user_record(home: Path) -> None:
    """The user-scope record's version is returned even when a local record comes first."""
    _write_registry(home, [
        {"scope": "local", "version": "3.9.5", "projectPath": "/x"},
        {"scope": "user", "version": "3.9.4"},
    ])
    vu = _vu()
    assert vu.registered_user_version(vu.registry_install_records()) == "3.9.4"


def test_registered_user_version_ignores_local_only(home: Path) -> None:
    """With only local-scope records there is no user install, so the result is empty."""
    _write_registry(home, [{"scope": "local", "version": "3.9.5", "projectPath": "/x"}])
    vu = _vu()
    assert vu.registered_user_version(vu.registry_install_records()) == ""


def test_registered_user_version_rejects_non_semver(home: Path) -> None:
    """A non-semver user version maps to empty, not to a value that reads as behind forever."""
    _write_registry(home, [{"scope": "user", "version": "latest"}])
    vu = _vu()
    assert vu.registered_user_version(vu.registry_install_records()) == ""


def test_registered_user_version_rejects_non_string_version(home: Path) -> None:
    """A user record whose version is not a string maps to empty."""
    _write_registry(home, [{"scope": "user", "version": 394}])
    vu = _vu()
    assert vu.registered_user_version(vu.registry_install_records()) == ""


def test_registered_user_version_unreadable_json(home: Path) -> None:
    """Corrupt registry JSON gives no records, hence an empty user version."""
    path = home / ".claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    vu = _vu()
    assert vu.registry_install_records() == []
    assert vu.registered_user_version(vu.registry_install_records()) == ""


def test_registered_user_version_missing_file(home: Path) -> None:
    """No registry file gives no records, hence an empty user version."""
    vu = _vu()
    assert not vu.registry_path().exists()
    assert vu.registry_install_records() == []
    assert vu.registered_user_version(vu.registry_install_records()) == ""


def test_update_reference_prefers_registered_user() -> None:
    """A known user-scope version wins over the cache's highest version."""
    assert _vu().update_reference("3.9.5", "3.9.4") == "3.9.4"


def test_update_reference_falls_back_to_cache() -> None:
    """With no user-scope version the cache's highest version is the reference."""
    assert _vu().update_reference("3.9.5", "") == "3.9.5"


def test_update_succeeded_bug_case_user_advanced_cache_unchanged() -> None:
    """THE BUG CASE: cache already at 3.9.5 before and after, user 3.9.4 -> 3.9.5 is success."""
    assert _vu().update_succeeded(
        user_before="3.9.4", user_after="3.9.5", cache_before="3.9.5", cache_after="3.9.5",
    ) is True


def test_update_succeeded_user_unchanged_cache_unchanged() -> None:
    """Nothing moved anywhere: failure."""
    assert _vu().update_succeeded(
        user_before="3.9.4", user_after="3.9.4", cache_before="3.9.5", cache_after="3.9.5",
    ) is False


def test_update_succeeded_user_unchanged_cache_advanced() -> None:
    """With a user record the cache advancing alone proves nothing: failure."""
    assert _vu().update_succeeded(
        user_before="3.9.4", user_after="3.9.4", cache_before="3.9.4", cache_after="3.9.5",
    ) is False


def test_update_succeeded_user_record_vanished() -> None:
    """A user record that disappears after the update is not an advance: failure."""
    assert _vu().update_succeeded(
        user_before="3.9.4", user_after="", cache_before="3.9.4", cache_after="3.9.5",
    ) is False


def test_update_succeeded_no_user_record_cache_advanced() -> None:
    """No user record: the cache advancing is the only signal (the old rule): success."""
    assert _vu().update_succeeded(
        user_before="", user_after="", cache_before="3.9.4", cache_after="3.9.5",
    ) is True


def test_update_succeeded_no_user_record_cache_unchanged() -> None:
    """No user record and the cache did not move: failure."""
    assert _vu().update_succeeded(
        user_before="", user_after="", cache_before="3.9.4", cache_after="3.9.4",
    ) is False



def _make_cache(parent: Path, versions: list[str]) -> Path:
    """Real `<plugin>/<version>/` dirs; returns the newest version dir."""
    for v in versions:
        (parent / v / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    return parent / versions[-1]


def test_do_auto_update_runs_when_cache_ahead_of_user_scope(
    home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE BUG END TO END: cache 3.9.5, user scope 3.9.4, published 3.9.5 -> update runs and succeeds."""
    vu = _vu()
    vdir = _make_cache(home / "cache", ["3.9.4", "3.9.5"])
    _write_registry(home, [{"scope": "user", "version": "3.9.4"}])
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root, **_kw: "3.9.5")
    attempts: list[int] = []

    def fake_update(_log, _path=None) -> bool:
        """Stand-in for the `claude` CLI: advances the real registry record, as the CLI does."""
        attempts.append(1)
        _write_registry(home, [{"scope": "user", "version": "3.9.5"}])
        return True

    monkeypatch.setattr(vu, "attempt_auto_update", fake_update)
    updated, latest, published = vu.do_auto_update_if_needed(vdir, lambda _m: None)
    assert attempts == [1], "the old cache-only check would have skipped the update"
    assert updated is True
    assert latest == "3.9.5"
    assert published == "3.9.5"


def test_do_auto_update_fails_when_user_scope_does_not_advance(
    home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CLI that reports success but leaves the user record behind is treated as failure."""
    vu = _vu()
    vdir = _make_cache(home / "cache", ["3.9.4", "3.9.5"])
    _write_registry(home, [{"scope": "user", "version": "3.9.4"}])
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root, **_kw: "3.9.5")
    monkeypatch.setattr(vu, "attempt_auto_update", lambda _log, _path=None: True)
    logs: list[str] = []
    updated, _, _ = vu.do_auto_update_if_needed(vdir, logs.append)
    assert updated is False
    assert any("did not advance" in line for line in logs)


def test_do_auto_update_silent_when_user_scope_current(
    home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User scope already at the published version: no update attempt."""
    vu = _vu()
    vdir = _make_cache(home / "cache", ["3.9.5"])
    _write_registry(home, [{"scope": "user", "version": "3.9.5"}])
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root, **_kw: "3.9.5")

    def must_not_run(_log, _path=None) -> bool:
        """Fails the test if the update is attempted."""
        raise AssertionError("update attempted although user scope is current")

    monkeypatch.setattr(vu, "attempt_auto_update", must_not_run)
    updated, _, _ = vu.do_auto_update_if_needed(vdir, lambda _m: None)
    assert updated is False



# ---------- detector main() wiring (Branch A on the registry reference) ----------

_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "version-update.py"


def _load_detector():
    """Import the hyphen-named detector module by path (not a valid import name)."""
    spec = _u.spec_from_file_location("janitor_version_update_registry_ref", str(_DETECTOR))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def detector_env(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated project/global-state/control dirs and fresh library modules for main()."""
    (home / "project").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(home / "project"))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(home / "global"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(home / "control"))
    for mod_name in ("state", "global_state", "harness_backend", "version_update_lib", "dedupe"):
        sys.modules.pop(mod_name, None)
    return home


def _rig_detector(mod, monkeypatch: pytest.MonkeyPatch, *, cache_latest: str, published: str) -> None:
    """Fake only the network/cache/server collaborators; the registry is the real file."""
    monkeypatch.setattr(mod.vu, "_SEMVER_RE", re.compile(r".*"))  # accept the repo dirname as the running version
    monkeypatch.setattr(mod.vu, "list_installed_versions", lambda *_a, **_kw: [cache_latest])
    monkeypatch.setattr(mod.vu, "resolve_latest_published", lambda *_a, **_kw: published)
    monkeypatch.setattr(mod.harness_backend, "server_runs_chores", lambda *_a, **_kw: False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE", "true")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER", "true")


def test_detector_requests_update_when_cache_ahead_of_user_scope(
    detector_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache 3.9.5, user scope 3.9.4, published 3.9.5: main() raises the request as 3.9.4->3.9.5."""
    mod = _load_detector()
    _write_registry(detector_env, [{"scope": "user", "version": "3.9.4"}])
    _rig_detector(mod, monkeypatch, cache_latest="3.9.5", published="3.9.5")
    assert mod.main() == 0
    assert mod.gs.version_update_requested_present() is True
    flag = mod.gs._version_update_request_path()
    assert "3.9.4->3.9.5" in flag.read_text(encoding="utf-8")  # the request label uses the registry version


def test_detector_silent_when_user_scope_current(
    detector_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User scope already at the published version: main() raises no request."""
    mod = _load_detector()
    _write_registry(detector_env, [{"scope": "user", "version": "3.9.5"}])
    _rig_detector(mod, monkeypatch, cache_latest="3.9.5", published="3.9.5")
    assert mod.main() == 0
    assert mod.gs.version_update_requested_present() is False


def test_detector_without_user_record_falls_back_to_cache(
    detector_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No registry at all: the cache is the reference, so cache 3.9.4 vs published 3.9.5 requests."""
    mod = _load_detector()
    _rig_detector(mod, monkeypatch, cache_latest="3.9.4", published="3.9.5")
    assert mod.main() == 0
    assert mod.gs.version_update_requested_present() is True
