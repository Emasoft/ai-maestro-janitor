"""Tests for the package-manager-policy detector.

The detector lives at scripts/detectors/package-manager-policy.py and is the
detection complement to the pre-tool-pkg-guard PreToolUse hook: the hook
PREVENTS weakening, this detector REPORTS pre-existing gaps. Tests run it
as a subprocess (the dispatch.py invocation surface) with CLAUDE_PROJECT_DIR
pointed at tmp_path so per-project state stays isolated. The install-time
firewall PATH check is steered by prepending a tmp bin dir with stub `sfw`
when we want "firewall installed" coverage.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "package-manager-policy.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(project_dir: Path, env_overrides: dict[str, str] | None = None,
         with_firewall: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_POLICY_ENABLED", None)
    env.pop("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES", None)
    if with_firewall:
        # Drop a tmp bin dir with stub `sfw` on PATH so the firewall check passes.
        binp = project_dir / "_bin"
        binp.mkdir(exist_ok=True)
        sfw = binp / "sfw"
        sfw.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        sfw.chmod(0o755)
        env["PATH"] = f"{binp}{os.pathsep}{env['PATH']}"
    else:
        # Empty bin dir prefix to ensure no system-installed sfw/safe-chain
        # leaks into the assertion. We DON'T put sfw/safe-chain on PATH.
        emptyp = project_dir / "_empty_bin"
        emptyp.mkdir(exist_ok=True)
        # Replace PATH to only contain essentials (uv + system) AND not the
        # real sfw location. Keep python tooling reachable.
        keep = []
        for d in env.get("PATH", "").split(os.pathsep):
            if d and "homebrew/bin" not in d:
                keep.append(d)
        env["PATH"] = os.pathsep.join([str(emptyp), *keep])
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


def test_silent_on_non_node_project(tmp_path: Path) -> None:
    """A project with no package.json + no JS lockfiles is silent."""
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_fires_on_node_project_with_no_npmrc(tmp_path: Path) -> None:
    """A node project missing .npmrc is flagged."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0"}), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout
    assert "no .npmrc" in r.stdout


def test_silent_on_hardened_node_project(tmp_path: Path) -> None:
    """A fully-hardened project with sfw on PATH produces zero output."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "pnpm": {"minimumReleaseAge": 7200, "trustPolicy": "no-downgrade",
                 "blockExoticSubdeps": True},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    r = _run(tmp_path, with_firewall=True)
    assert r.returncode == 0
    assert r.stdout == ""


def test_flags_weak_npmrc(tmp_path: Path) -> None:
    """A .npmrc with weak values flags each issue."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=60\ntrust-policy=allow\naudit-level=info\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "minimum-release-age=60" in r.stdout
    assert "trust-policy" in r.stdout
    assert "audit-level" in r.stdout


def test_flags_missing_firewall(tmp_path: Path) -> None:
    """A node project with no sfw/safe-chain on PATH is flagged."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)  # with_firewall=False
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout
    assert "install-time malware firewall" in r.stdout


def test_content_hash_short_circuits(tmp_path: Path) -> None:
    """Second run with unchanged config produces no output (cache hit)."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    first = _run(tmp_path)
    assert "[package-manager-policy]" in first.stdout
    second = _run(tmp_path)
    assert second.returncode == 0
    assert second.stdout == ""


def test_edit_invalidates_cache(tmp_path: Path) -> None:
    """Editing a config file changes the hash → re-emits the current findings."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    assert "[package-manager-policy]" in _run(tmp_path).stdout
    # Editing the file (any byte change) re-fires.
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0"}), encoding="utf-8",
    )
    second = _run(tmp_path)
    assert "[package-manager-policy]" in second.stdout


def test_disabled_env_silent(tmp_path: Path) -> None:
    """ENABLED=false silences the detector entirely."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    r = _run(tmp_path, env_overrides={"CLAUDE_PLUGIN_OPTION_PKG_MANAGER_POLICY_ENABLED": "0"})
    assert r.returncode == 0
    assert r.stdout == ""


def test_threshold_override_relaxes_block(tmp_path: Path) -> None:
    """Lowering the threshold knob lets a lower minimum-release-age pass."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=60\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES": "30"},
        with_firewall=True,
    )
    assert r.returncode == 0
    assert r.stdout == ""  # 60 > 30 → passes


def test_yarnrc_enable_scripts_true_flagged(tmp_path: Path) -> None:
    """.yarnrc.yml enableScripts: true is flagged."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    (tmp_path / ".yarnrc.yml").write_text("enableScripts: true\n", encoding="utf-8")
    r = _run(tmp_path, with_firewall=True)
    assert r.returncode == 0
    assert "enableScripts" in r.stdout


def test_bunfig_verify_false_flagged(tmp_path: Path) -> None:
    """bunfig.toml [install].verify=false is flagged."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    (tmp_path / "bunfig.toml").write_text("[install]\nverify = false\n", encoding="utf-8")
    r = _run(tmp_path, with_firewall=True)
    assert r.returncode == 0
    assert "verify=false" in r.stdout
