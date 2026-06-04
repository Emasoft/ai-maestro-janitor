"""Tests for the historical-cache-scan detector.

Spins up a tmp HOME with fake npm cacache + pnpm store + global
node_modules, seeds it with known-malicious package@version, and
verifies the detector surfaces a drift line. Also checks the
silent-on-no-incident-list and self-scan guard paths.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "historical-cache-scan.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    project_dir: Path, home_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["HOME"] = str(home_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_HISTORICAL_CACHE_SCAN_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


def _seed_incident_list(project_dir: Path, entries: list[str]) -> None:
    incidents = project_dir / ".janitor"
    incidents.mkdir(exist_ok=True)
    (incidents / "incidents.txt").write_text(
        "# known-malicious versions\n" + "\n".join(entries) + "\n",
        encoding="utf-8",
    )


def _seed_npm_cacache_ledger(home: Path, name: str, version: str) -> None:
    """Drop a fake cacache index file under ~/.npm/_cacache/index-v5/."""
    idx_dir = home / ".npm" / "_cacache" / "index-v5" / "00"
    idx_dir.mkdir(parents=True, exist_ok=True)
    ledger = idx_dir / "fake-ledger"
    # Mirror the real cacache line shape: <sha>\t<json-body>
    body = json.dumps({"name": name, "version": version, "integrity": "sha512-..."})
    ledger.write_text(f"deadbeef\t{body}\n", encoding="utf-8")


def _seed_pnpm_store_pkg(home: Path, name: str, version: str) -> None:
    pkg = home / ".local" / "share" / "pnpm" / "store" / "v3" / "files" / "abc"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": name, "version": version}),
        encoding="utf-8",
    )


def _seed_global_node_modules_pkg(home: Path, name: str, version: str) -> None:
    """nvm-style global node_modules with one fake package."""
    nm = home / ".nvm" / "versions" / "node" / "v20.0.0" / "lib" / "node_modules" / name
    nm.mkdir(parents=True, exist_ok=True)
    (nm / "package.json").write_text(
        json.dumps({"name": name, "version": version}),
        encoding="utf-8",
    )


# ---------- Silent paths ------------------------------------------------


def test_silent_when_no_incident_list(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_when_incident_list_empty(tmp_path: Path) -> None:
    """Empty or comment-only file → no entries to scan against."""
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".janitor").mkdir()
    (tmp_path / ".janitor" / "incidents.txt").write_text(
        "# nothing here\n", encoding="utf-8",
    )
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_when_caches_clean(tmp_path: Path) -> None:
    """Incidents exist but no cache contains them → silent."""
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["evil-pkg@1.0.0"])
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Detection in npm cacache -----------------------------------


def test_fires_on_npm_cacache_hit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["evil-pkg@1.0.0"])
    _seed_npm_cacache_ledger(home, "evil-pkg", "1.0.0")
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert "[historical-cache-scan]" in r.stdout
    assert "evil-pkg@1.0.0" in r.stdout


def test_npm_cacache_clean_version_not_flagged(tmp_path: Path) -> None:
    """A DIFFERENT version of the same package present in cache is fine."""
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["evil-pkg@1.0.0"])  # malicious version
    _seed_npm_cacache_ledger(home, "evil-pkg", "1.0.1")  # clean version
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Detection in pnpm store ------------------------------------


def test_fires_on_pnpm_store_hit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["bad-pkg@2.3.4"])
    _seed_pnpm_store_pkg(home, "bad-pkg", "2.3.4")
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert "[historical-cache-scan]" in r.stdout
    assert "bad-pkg@2.3.4" in r.stdout


# ---------- Detection in global node_modules ---------------------------


def test_fires_on_global_node_modules_hit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["compromised@9.9.9"])
    _seed_global_node_modules_pkg(home, "compromised", "9.9.9")
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert "[historical-cache-scan]" in r.stdout
    assert "compromised@9.9.9" in r.stdout


# ---------- Scoped packages --------------------------------------------


def test_fires_on_scoped_package(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["@evil/stealer@0.0.1"])
    _seed_npm_cacache_ledger(home, "@evil/stealer", "0.0.1")
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert "[historical-cache-scan]" in r.stdout


# ---------- Self-scan guard ---------------------------------------------


def test_self_scan_guard_silences(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.1"}),
        encoding="utf-8",
    )
    _seed_incident_list(tmp_path, ["evil-pkg@1.0.0"])
    _seed_npm_cacache_ledger(home, "evil-pkg", "1.0.0")
    r = _run(tmp_path, home)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Feature flag ------------------------------------------------


def test_disabled_by_env_flag(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["evil-pkg@1.0.0"])
    _seed_npm_cacache_ledger(home, "evil-pkg", "1.0.0")
    r = _run(
        tmp_path, home,
        env_overrides={"CLAUDE_PLUGIN_OPTION_HISTORICAL_CACHE_SCAN_ENABLED": "0"},
    )
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Dedupe ------------------------------------------------------


def test_silent_on_second_run_when_nothing_changed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_incident_list(tmp_path, ["evil-pkg@1.0.0"])
    _seed_npm_cacache_ledger(home, "evil-pkg", "1.0.0")
    first = _run(tmp_path, home)
    assert "[historical-cache-scan]" in first.stdout
    second = _run(tmp_path, home)
    assert second.returncode == 0
    assert second.stdout == ""
