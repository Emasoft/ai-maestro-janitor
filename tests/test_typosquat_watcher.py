"""Tests for the typosquat-watcher heartbeat detector.

The detector lives at scripts/detectors/typosquat-watcher.py and audits
every supported lockfile in the project for dependency names within
Levenshtein distance ≤ 1 of a curated popular package — the documented
shape of typosquat campaigns.

Lockfile formats covered: package-lock.json (v7+ + v6), yarn.lock,
pnpm-lock.yaml, requirements.txt, uv.lock, poetry.lock.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "typosquat-watcher.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    project_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_TYPOSQUAT_WATCHER_ENABLED", None)
    env.pop("CLAUDE_PLUGIN_OPTION_TYPOSQUAT_MAX_DISTANCE", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


# ---------- Silent on clean projects ------------------------------------


def test_silent_on_empty_project(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_when_lockfile_uses_real_popular_names(tmp_path: Path) -> None:
    """Real popular packages don't trip the detector."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "name": "x", "version": "1.0.0", "lockfileVersion": 3,
            "packages": {
                "": {"name": "x"},
                "node_modules/react": {"version": "18.0.0"},
                "node_modules/lodash": {"version": "4.17.21"},
                "node_modules/typescript": {"version": "5.0.0"},
            },
        }), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- npm typosquat detection -------------------------------------


def test_fires_on_npm_typosquat_reactt(tmp_path: Path) -> None:
    """`reactt` is one edit from `react` → caught."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "node_modules/reactt": {"version": "1.0.0"},
            },
        }), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[typosquat-watcher]" in r.stdout
    assert "npm:reactt" in r.stdout
    assert "'react'" in r.stdout


def test_fires_on_npm_typosquat_ethersr(tmp_path: Path) -> None:
    """`ethersr` is one edit from `ethers` → caught."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "node_modules/ethersr": {"version": "1.0.0"},
            },
        }), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[typosquat-watcher]" in r.stdout
    assert "npm:ethersr" in r.stdout


# ---------- yarn.lock parsing -------------------------------------------


def test_fires_on_yarn_lock_typosquat(tmp_path: Path) -> None:
    """yarn.lock entry shape: `"reactt@^1.0.0":`."""
    (tmp_path / "yarn.lock").write_text(
        '# yarn lockfile v1\n'
        '\n'
        '"reactt@^1.0.0":\n'
        '  version "1.0.0"\n'
        '  resolved "https://registry.yarnpkg.com/reactt/-/reactt-1.0.0.tgz"\n',
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[typosquat-watcher]" in r.stdout
    assert "npm:reactt" in r.stdout


# ---------- pnpm-lock.yaml parsing --------------------------------------


def test_fires_on_pnpm_typosquat(tmp_path: Path) -> None:
    """pnpm-lock.yaml entry shape: `/reactt@1.0.0:`."""
    (tmp_path / "pnpm-lock.yaml").write_text(
        'lockfileVersion: "6.0"\n'
        '\n'
        'packages:\n'
        '\n'
        '  /reactt@1.0.0:\n'
        '    resolution: {integrity: sha512-...}\n'
        '    dev: false\n',
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[typosquat-watcher]" in r.stdout
    assert "npm:reactt" in r.stdout


# ---------- Python (requirements.txt + uv.lock + poetry.lock) ----------


def test_fires_on_pypi_typosquat_in_requirements(tmp_path: Path) -> None:
    """`requestz` (1 edit from `requests`) is caught."""
    (tmp_path / "requirements.txt").write_text(
        "# project deps\n"
        "requestz==2.31.0\n"
        "numpy==1.26.0\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[typosquat-watcher]" in r.stdout
    assert "py:requestz" in r.stdout


def test_fires_on_pypi_typosquat_in_uv_lock(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(
        'version = 1\n'
        '\n'
        '[[package]]\n'
        'name = "requestz"\n'
        'version = "2.31.0"\n',
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[typosquat-watcher]" in r.stdout
    assert "py:requestz" in r.stdout


# ---------- Vendored-dir exclusion --------------------------------------


def test_skips_lockfile_inside_node_modules(tmp_path: Path) -> None:
    """A package-lock.json under node_modules/ is vendored, not the
    project's own lockfile — must not be scanned."""
    inner = tmp_path / "node_modules" / "some-dep"
    inner.mkdir(parents=True)
    (inner / "package-lock.json").write_text(
        json.dumps({
            "lockfileVersion": 3,
            "packages": {"node_modules/reactt": {"version": "1.0.0"}},
        }), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Distance-2 tunable -----------------------------------------


def test_distance_2_finds_lodahs(tmp_path: Path) -> None:
    """`lodahs` is distance 2 from `lodash` — fires only with max_distance=2."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "lockfileVersion": 3,
            "packages": {"node_modules/lodahs": {"version": "1.0.0"}},
        }), encoding="utf-8",
    )
    r1 = _run(tmp_path)
    assert r1.returncode == 0
    assert r1.stdout == ""  # default distance=1 misses it
    # Reset the dedupe hash for the second run.
    (tmp_path / ".janitor" / "state" / "typosquat-watcher-last-hash.ts").unlink(
        missing_ok=True,
    )
    r2 = _run(tmp_path, env_overrides={"CLAUDE_PLUGIN_OPTION_TYPOSQUAT_MAX_DISTANCE": "2"})
    assert r2.returncode == 0
    assert "[typosquat-watcher]" in r2.stdout
    assert "npm:lodahs" in r2.stdout
    assert "'lodash'" in r2.stdout


# ---------- Dedupe + heartbeat hygiene ---------------------------------


def test_silent_on_second_run_when_nothing_changed(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "lockfileVersion": 3,
            "packages": {"node_modules/reactt": {"version": "1.0.0"}},
        }), encoding="utf-8",
    )
    first = _run(tmp_path)
    assert "[typosquat-watcher]" in first.stdout
    second = _run(tmp_path)
    assert second.returncode == 0
    assert second.stdout == ""


# ---------- Self-scan + feature flag -----------------------------------


def test_self_scan_guard_silences_detector(tmp_path: Path) -> None:
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.1"}),
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "lockfileVersion": 3,
            "packages": {"node_modules/reactt": {"version": "1.0.0"}},
        }), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_disabled_by_env_flag(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text(
        json.dumps({
            "lockfileVersion": 3,
            "packages": {"node_modules/reactt": {"version": "1.0.0"}},
        }), encoding="utf-8",
    )
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_TYPOSQUAT_WATCHER_ENABLED": "0"},
    )
    assert r.returncode == 0
    assert r.stdout == ""
