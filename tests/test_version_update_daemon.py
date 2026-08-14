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
    updated, latest, published = vu.do_auto_update_if_needed(vdir, logs.append)
    assert updated is False
    assert latest == "0.5.0"
    assert published == "0.5.0"
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
    updated, _, _ = vu.do_auto_update_if_needed(vdir, logs.append)
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

    updated, latest, published = vu.do_auto_update_if_needed(vdir, lambda _m: None)
    assert updated is True
    assert latest == "0.5.1"
    assert published == "0.5.1"


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
    updated, _, _ = vu.do_auto_update_if_needed(vdir, logs.append)
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
    updated, latest, published = vu.do_auto_update_if_needed(vdir, lambda _m: None)
    assert updated is False
    assert latest == "0.5.0"
    assert published == "0.5.1"


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


# ---------- certify_newest_if_clean (TRDD-ZM5LZ24Y periodic re-pin) -------
#
# `pin_good_version`'s only prior caller lived inside `daemon.py`'s
# `if updated:` branch, so a version installed by any OTHER route (a human
# running `claude plugin update ... --scope user`) was never certified and
# C3 went permanently "no opinion". `certify_newest_if_clean` is the
# periodic-path fix: it re-derives the newest CACHED version itself and
# pins it only when its shipped manifest verifies byte-for-byte clean
# (the same C2 check the janitor-self-integrity detector runs) — so C2 is
# never weakened, and every uncertainty is a silent no-op (fail-open).


def _clean_manifest_json() -> str:
    """A manifest asserting NO tracked files exist — matches a version dir
    that ships none of `DEFAULT_MANIFEST_GLOBS` (README.md, CLAUDE.md,
    skills/**/SKILL.md, ...), so `verify_manifest` reports it clean."""
    return json.dumps({"version": 1, "files": {}})


def _dirty_manifest_json() -> str:
    """A manifest that claims `CLAUDE.md` exists with a known hash, while no
    such file is written on disk — `verify_manifest` reports it as
    `missing`, so the version must NOT be certified."""
    return json.dumps({"version": 1, "files": {"CLAUDE.md": "deadbeef"}})


def _make_manifest(version_dir: Path, *, clean: bool) -> None:
    integrity_dir = version_dir / ".integrity"
    integrity_dir.mkdir(parents=True, exist_ok=True)
    blob = _clean_manifest_json() if clean else _dirty_manifest_json()
    (integrity_dir / "manifest-sha256.json").write_text(blob, encoding="utf-8")
    # certify_newest_if_clean now requires scripts/dispatch.py to exist before
    # a version is even eligible — it mirrors the stub's own predicate (the
    # stub can never exec a version lacking this entry point). Every fixture
    # that models a certifiable version must create it, or the fixture is
    # modelling a version the stub could never actually run.
    _make_runnable(version_dir)


def _make_runnable(version_dir: Path) -> None:
    """Create the `scripts/dispatch.py` entry point the stub requires to exec
    a version — without it `certify_newest_if_clean` must skip the version
    outright, regardless of how clean its manifest is."""
    scripts_dir = version_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "dispatch.py").write_text("", encoding="utf-8")


def test_certify_newest_if_clean_pins_a_clean_uncertified_newest(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core fix: a version installed OUTSIDE the daemon's own self-update
    branch (no prior pin at all) still gets certified once its manifest
    verifies clean — this is the periodic path `daemon.py` must call on
    every fire, not only inside `if updated:`. Passes `published="2.0.0"`
    (F1's provenance gate) so this test isolates the C2/runnable/quarantine
    logic from the gate — see the dedicated F1 tests below for the gate
    itself."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "2.0.0", clean=True)

    vu = _vu()
    pinned = vu.certify_newest_if_clean(cache_parent, "2.0.0")

    assert pinned == "2.0.0"
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "2.0.0"


def test_certify_newest_if_clean_never_pins_a_dirty_manifest(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A version whose manifest does NOT verify clean (C2 catches a
    mismatch) must never be pinned — C3 must never certify what C2 itself
    would reject."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "3.0.0", clean=False)

    vu = _vu()
    pinned = vu.certify_newest_if_clean(cache_parent)

    assert pinned is None
    assert vu.read_last_good() is None


def test_certify_newest_if_clean_is_a_noop_when_already_current(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steady-state fire: the newest cached version is already pinned, so
    the function must do nothing (no re-write, no wasted work) — every
    heartbeat calls this unconditionally, so the no-op path must be cheap
    and side-effect-free."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "4.0.0", clean=True)

    vu = _vu()
    first = vu.certify_newest_if_clean(cache_parent, "4.0.0")
    assert first == "4.0.0"

    # The already-pinned short-circuit needs no tag at all (it costs nothing
    # and confirms nothing new) — omitting `published` here proves that.
    second = vu.certify_newest_if_clean(cache_parent)
    assert second is None
    # Bind before subscripting: read_last_good() is `dict | None`, so indexing it
    # directly raises TypeError on a regression instead of failing the assertion —
    # which reports "unsubscriptable NoneType" rather than "the pin went missing".
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "4.0.0"


def test_certify_newest_if_clean_noop_with_no_cached_versions(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No cache dir at all (fresh machine, nothing installed yet) is
    uncertainty, not a signal — fail-open, never a crash."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    vu = _vu()
    assert vu.certify_newest_if_clean(tmp_path / "no-such-cache") is None
    assert vu.read_last_good() is None


def test_certify_newest_if_clean_noop_when_manifest_missing(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cached version with no shipped `.integrity/manifest-sha256.json`
    (an older release) is unpinnable — same fail-open C2 already has for a
    missing manifest, never a crash and never a false pin."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    (cache_parent / "5.0.0").mkdir(parents=True)

    vu = _vu()
    assert vu.certify_newest_if_clean(cache_parent) is None
    assert vu.read_last_good() is None


def test_certify_newest_if_clean_walks_past_a_quarantined_newest(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect this closes: a QUARANTINED newest version must never be
    pinned even though it is clean+runnable — certifying it would overwrite
    the anchor of the OLDER version the stub actually execs (the stub skips
    quarantined versions), permanently recreating the stale-pin bug. The
    older, clean, non-quarantined version must be pinned instead."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "6.0.0", clean=True)
    _make_manifest(cache_parent / "6.1.0", clean=True)

    vu = _vu()
    assert vu.add_quarantine("6.1.0", reason="proven bad in this test")

    pinned = vu.certify_newest_if_clean(cache_parent, "6.0.0")

    assert pinned == "6.0.0"
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "6.0.0"


def test_certify_newest_if_clean_skips_a_newest_with_no_dispatch_entrypoint(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newest version that verifies C2-clean but ships no
    `scripts/dispatch.py` can never be the version the stub execs, so it
    must never be certified — the older, fully-runnable version is pinned
    instead."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "7.0.0", clean=True)

    # 7.1.0: manifest verifies clean, but no scripts/dispatch.py — built by
    # hand (not via _make_manifest/_make_runnable) so it deliberately lacks
    # the entry point.
    newest_dir = cache_parent / "7.1.0"
    integrity_dir = newest_dir / ".integrity"
    integrity_dir.mkdir(parents=True, exist_ok=True)
    (integrity_dir / "manifest-sha256.json").write_text(
        _clean_manifest_json(), encoding="utf-8",
    )

    vu = _vu()
    pinned = vu.certify_newest_if_clean(cache_parent, "7.0.0")

    assert pinned == "7.0.0"
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "7.0.0"


def test_certify_newest_if_clean_walks_down_past_a_dirty_newest(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newest version whose manifest does NOT verify clean must be skipped
    (never pinned, per C2), and the walk must continue to an older, clean
    version rather than giving up — this is the walk-down behaviour that
    previously returned None and pinned nothing."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "8.0.0", clean=True)
    _make_manifest(cache_parent / "8.1.0", clean=False)

    vu = _vu()
    pinned = vu.certify_newest_if_clean(cache_parent, "8.0.0")

    assert pinned == "8.0.0"
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "8.0.0"


def test_certify_newest_if_clean_noop_when_every_version_is_quarantined_or_unrunnable(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When every cached version is either quarantined or missing the
    dispatch entry point, there is nothing the stub could ever exec — the
    function must return None and must NOT touch the anchor (no pin written,
    no existing pin overwritten)."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"

    # 9.0.0: clean manifest, runnable, but quarantined.
    _make_manifest(cache_parent / "9.0.0", clean=True)
    # 9.1.0: clean manifest, but NOT runnable (no scripts/dispatch.py).
    unrunnable_dir = cache_parent / "9.1.0"
    integrity_dir = unrunnable_dir / ".integrity"
    integrity_dir.mkdir(parents=True, exist_ok=True)
    (integrity_dir / "manifest-sha256.json").write_text(
        _clean_manifest_json(), encoding="utf-8",
    )

    vu = _vu()
    assert vu.add_quarantine("9.0.0", reason="proven bad in this test")

    pinned = vu.certify_newest_if_clean(cache_parent)

    assert pinned is None
    assert vu.read_last_good() is None


# ---------- F1 provenance gate (TRDD-ZM5LZ24Y, owner-directed 2026-08-14) --
#
# Certifying "whatever is newest on disk" (Option A alone) means first trust
# is established by mere cache-write access. F1 requires the candidate to
# also equal the GitHub `releases/latest` tag the daemon ALREADY resolved
# this fire (via `do_auto_update_if_needed`'s third return value — no second
# `gh api` call). Unresolvable/mismatched tag ⇒ fail CLOSED: skip pinning,
# leave the prior pin exactly as it was.


def test_certify_newest_if_clean_certifies_when_newest_equals_published_tag(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate's open path: the release channel agrees with the candidate."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "10.0.0", clean=True)

    vu = _vu()
    pinned = vu.certify_newest_if_clean(cache_parent, "10.0.0")

    assert pinned == "10.0.0"
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "10.0.0"


def test_certify_newest_if_clean_skips_when_newest_differs_from_published_tag(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate that is otherwise clean+runnable+non-quarantined must NOT
    be certified when the release channel names a DIFFERENT tag — e.g. a
    locally-built or mutated cache entry that never actually shipped."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "11.0.0", clean=True)

    vu = _vu()
    pinned = vu.certify_newest_if_clean(cache_parent, "11.5.0")

    assert pinned is None
    assert vu.read_last_good() is None


def test_certify_newest_if_clean_fails_closed_when_tag_unresolvable_and_leaves_prior_pin(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline / no `gh` / no releases yet ⇒ `published` is None (or empty).
    The gate must fail CLOSED: skip certifying a NEW candidate, and — the
    part that matters most — leave an EXISTING pin completely untouched
    rather than rejecting or clearing it. Fail-closed means "don't advance",
    never "tear down what's already anchored"."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "12.0.0", clean=True)

    vu = _vu()
    # Establish a prior pin the way the gate's open path would.
    first = vu.certify_newest_if_clean(cache_parent, "12.0.0")
    assert first == "12.0.0"

    # A newer version lands on disk, but this fire cannot resolve the tag
    # (published=None — the unresolvable case, e.g. offline or no `gh`).
    _make_manifest(cache_parent / "12.1.0", clean=True)
    pinned = vu.certify_newest_if_clean(cache_parent, None)

    assert pinned is None
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "12.0.0"  # unchanged — never torn down


def test_certify_newest_if_clean_fails_closed_on_empty_string_tag_too(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`do_auto_update_if_needed` returns `""` (not `None`) for an
    unresolvable tag — the gate must treat the empty string identically to
    `None`, since that is the exact value the daemon threads through."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    cache_parent = tmp_path / "cache"
    _make_manifest(cache_parent / "13.0.0", clean=True)

    vu = _vu()
    pinned = vu.certify_newest_if_clean(cache_parent, "")

    assert pinned is None
    assert vu.read_last_good() is None
