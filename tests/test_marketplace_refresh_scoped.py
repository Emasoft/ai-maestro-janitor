"""Tests for the per-session scoped marketplace refresh.

The refactored detector lives at scripts/detectors/marketplace-refresh.py.
It actively refreshes ONLY the marketplaces hosting plugins enabled in this
project's .claude/settings.json (project scope) and .claude/settings.local.json
(local scope). Global / user-scope marketplaces are owned by the daemon.

These tests use a fake `claude` CLI on PATH to verify the per-session
detector enumerates the right marketplaces and spawns the worker with
the right arguments — no real Claude Code state is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "marketplace-refresh.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"

# Fake claude CLI: logs each invocation to $CLAUDE_LOG and exits 0.
_CLAUDE_STUB = '''#!/usr/bin/env python3
import os, sys
log = os.environ.get("CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(sys.argv[1:]) + "\\n")
raise SystemExit(0)
'''

sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _make_uv_bin(parent: Path) -> Path:
    """Build a bin dir with `uv` + a fake `claude`. Used as the test PATH."""
    binp = parent / "_bin"
    binp.mkdir(exist_ok=True)
    real_uv = shutil.which("uv")
    assert real_uv is not None, "uv must be on PATH for these tests"
    (binp / "uv").symlink_to(real_uv)
    claude = binp / "claude"
    claude.write_text(_CLAUDE_STUB, encoding="utf-8")
    claude.chmod(0o755)
    return binp


def _make_settings(
    project_root: Path,
    *,
    project_enabled: dict[str, bool] | None = None,
    local_enabled: dict[str, bool] | None = None,
) -> None:
    cdir = project_root / ".claude"
    cdir.mkdir(parents=True, exist_ok=True)
    if project_enabled is not None:
        (cdir / "settings.json").write_text(
            json.dumps({"enabledPlugins": project_enabled}), encoding="utf-8",
        )
    if local_enabled is not None:
        (cdir / "settings.local.json").write_text(
            json.dumps({"enabledPlugins": local_enabled}), encoding="utf-8",
        )


@pytest.fixture
def env_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Per-test project + global-state + claude-call log."""
    project = tmp_path / "project"
    project.mkdir()
    binp = _make_uv_bin(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    # Disable the global daemon: its own marketplace refresh would
    # pollute the claude-call log and make assertions noisy.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED", "false")
    log_file = tmp_path / "claude-calls.log"
    monkeypatch.setenv("CLAUDE_LOG", str(log_file))
    # Reload modules so the fixture's env vars apply
    for mod in ("state", "global_state", "dedupe"):
        if mod in sys.modules:
            del sys.modules[mod]
    return {
        "project": project,
        "binp": binp,
        "claude_log": log_file,
        "global": tmp_path / "global",
    }


def _run_detector(env_paths: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(env_paths["project"])
    env["JANITOR_GLOBAL_STATE_DIR"] = str(env_paths["global"])
    env["CLAUDE_LOG"] = str(env_paths["claude_log"])
    env["PATH"] = f"{env_paths['binp']}{os.pathsep}{env['PATH']}"
    env["CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED"] = "false"
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=30,
    )


def _wait_for_worker(env_paths: dict[str, Path], deadline: float = 20.0) -> Path:
    """Block until the detached worker finishes writing the claude log.

    The worker is a DETACHED double-fork that acquires the marketplace flock
    before exec'ing the stub `claude`, so its first log write can lag the
    detector's own return. Under full-suite CPU contention that startup
    occasionally exceeded the old 5s deadline (flaked ~1/11000 in the full run
    while passing in isolation), yielding an empty log and a false failure. The
    deadline is therefore generous; the happy path still returns in <1s, the
    moment the log stabilizes, so the longer ceiling costs nothing when the
    worker is prompt."""
    log = env_paths["claude_log"]
    start = time.time()
    while time.time() - start < deadline:
        if log.is_file() and log.read_text(encoding="utf-8").strip():
            # Worker may write more lines — wait a moment for stability.
            prev = log.read_text(encoding="utf-8")
            time.sleep(0.2)
            if log.read_text(encoding="utf-8") == prev:
                return log
        time.sleep(0.1)
    return log


# ---------- _enabled_plugins / _marketplaces_from_plugin_ids (in-process) -

def test_enabled_plugins_returns_only_true_entries(env_setup: dict[str, Path]) -> None:
    """In-process: enabledPlugins entries with flag=False are skipped."""
    import importlib.util as _u
    spec = _u.spec_from_file_location("janitor_mrt", str(_DETECTOR))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)

    settings = env_setup["project"] / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"enabledPlugins": {
        "a@m1": True,
        "b@m2": False,
        "c@m1": True,
        "":      True,
        "d":     True,
        "e@m3":  "yes",
    }}), encoding="utf-8")
    out = mod._enabled_plugins(settings, "settings.json")
    assert set(out) == {"a@m1", "c@m1", "d"}


def test_marketplaces_from_plugin_ids_dedups_and_skips_unmarketed(
    env_setup: dict[str, Path],
) -> None:
    _ = env_setup
    import importlib.util as _u
    spec = _u.spec_from_file_location("janitor_mrt2", str(_DETECTOR))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    markets = mod._marketplaces_from_plugin_ids(
        ["a@m1", "b@m2", "c@m1", "d@m1", "no-at", "e@m3", "  @  ", "f@m2"],
    )
    assert markets == ["m1", "m2", "m3"]


def test_scoped_marketplaces_unions_local_and_project(
    env_setup: dict[str, Path],
) -> None:
    """Plugins enabled in either settings.json OR settings.local.json → union of
    their marketplaces, deduped."""
    import importlib.util as _u
    spec = _u.spec_from_file_location("janitor_mrt3", str(_DETECTOR))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _make_settings(
        env_setup["project"],
        project_enabled={"a@m1": True, "b@m2": True},
        local_enabled={"c@m1": True, "d@m3": True},
    )
    markets = mod._scoped_marketplaces(env_setup["project"])
    assert set(markets) == {"m1", "m2", "m3"}


# ---------- end-to-end: detector spawns worker, worker calls claude --------

def test_no_enabled_plugins_means_no_claude_calls(env_setup: dict[str, Path]) -> None:
    """No settings files → detector bails fast without spawning the worker."""
    r = _run_detector(env_setup)
    assert r.returncode == 0, r.stderr
    # Give any (incorrectly-spawned) worker a chance to write — it shouldn't.
    time.sleep(0.5)
    assert not env_setup["claude_log"].is_file() or \
        env_setup["claude_log"].read_text(encoding="utf-8") == ""


def test_per_session_refreshes_each_unique_marketplace(
    env_setup: dict[str, Path],
) -> None:
    """Enabled local+project plugins → detector spawns worker → worker calls
    `claude plugin marketplace update <name>` once per unique marketplace."""
    _make_settings(
        env_setup["project"],
        project_enabled={"plug-a@market-1": True},
        local_enabled={
            "plug-b@market-1": True,  # duplicate market — should dedupe
            "plug-c@market-2": True,
        },
    )
    r = _run_detector(env_setup)
    assert r.returncode == 0, r.stderr
    log = _wait_for_worker(env_setup)
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert any("plugin marketplace update market-1" in ln for ln in lines), text
    assert any("plugin marketplace update market-2" in ln for ln in lines), text
    market1_lines = [ln for ln in lines if "market-1" in ln]
    assert len(market1_lines) == 1, f"market-1 should be deduped, got {market1_lines!r}"


def test_disabled_plugins_are_skipped(env_setup: dict[str, Path]) -> None:
    """enabledPlugins entries with flag=False contribute nothing to the
    refresh — disabled plugins don't drag their marketplace in."""
    _make_settings(
        env_setup["project"],
        project_enabled={"a@m1": True, "b@m2": False},
    )
    r = _run_detector(env_setup)
    assert r.returncode == 0, r.stderr
    log = _wait_for_worker(env_setup)
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "market" in text.lower() or "m1" in text, f"expected at least m1, got: {text!r}"
    assert "m2" not in text, f"m2 should be skipped (disabled), got: {text!r}"
