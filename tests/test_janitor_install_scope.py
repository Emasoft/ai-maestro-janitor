"""Tests for the janitor-install-scope detector (TRDD-db169d9e R5).

The janitor MUST be a USER-scope install. This detector warns when it is enabled
at project/local scope, and its `--check` mode (used by /janitor-arm) exits
non-zero on a violation. Run as subprocesses with a temp CLAUDE_PROJECT_DIR.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_DET = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "janitor-install-scope.py"


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(
        [sys.executable, str(_DET), *args], capture_output=True, text=True, env=env, timeout=30
    )


def _write_settings(project: Path, rel: str, data: dict) -> None:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_silent_when_not_project_enabled(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    assert _run(proj).stdout.strip() == ""


def test_check_ok_when_user_scope(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    r = _run(proj, "--check")
    assert r.returncode == 0 and "OK user-scope" in r.stdout


def test_warns_when_project_enabled(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    _write_settings(proj, ".claude/settings.json", {"enabledPlugins": ["ai-maestro-janitor@ai-maestro-plugins"]})
    out = _run(proj).stdout
    assert "[janitor-install-scope]" in out and "project" in out


def test_check_nonzero_when_project_enabled(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    _write_settings(proj, ".claude/settings.json", {"enabledPlugins": ["ai-maestro-janitor@mp"]})
    r = _run(proj, "--check")
    assert r.returncode == 1 and "[janitor-install-scope]" in r.stdout


def test_warns_when_local_enabled(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    _write_settings(proj, ".claude/settings.local.json", {"enabledPlugins": ["ai-maestro-janitor@mp"]})
    assert "local" in _run(proj).stdout


def test_silent_when_only_disabled(tmp_path):
    # A disabledPlugins mention is NOT an active install — must stay silent.
    proj = tmp_path / "p"
    proj.mkdir()
    _write_settings(
        proj, ".claude/settings.json",
        {"enabledPlugins": [], "disabledPlugins": ["ai-maestro-janitor@mp"]},
    )
    assert _run(proj).stdout.strip() == ""
    assert _run(proj, "--check").returncode == 0
