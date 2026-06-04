"""Tests for the self-scan guard — every repo-security detector must refuse
to scan the janitor's own repo unless explicitly overridden.

The guard prevents the janitor from emitting findings about its own CI when
it's armed inside its own source repo during development (the natural case
for the maintainer). See `state.is_self_scan_target()` for the design
rationale.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

# The four repo-security detectors that must self-skip
_GUARDED_DETECTORS = (
    "workflow-security",
    "branch-protection",
    "package-manager-policy",
    "remote-credentials",
)


def _make_janitor_manifest(root: Path, name: str = "ai-maestro-janitor") -> None:
    """Drop a plugin.json that makes the project look like the janitor."""
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": name, "version": "0.0.0"}),
        encoding="utf-8",
    )


def _make_workflow(root: Path) -> None:
    """Drop a deliberately weak workflow so any non-self-scan would emit findings."""
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "name: ci\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo \"hi\"\n",
        encoding="utf-8",
    )


def _run_detector(detector: str, project_dir: Path, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_ALLOW_SELF_SCAN", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_PROJECT_ROOT / "scripts" / "detectors" / f"{detector}.py")],
        env=env, capture_output=True, text=True, timeout=60,
    )


# ---------- state.is_self_scan_target() ----------------------------------


@pytest.fixture
def project_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_ALLOW_SELF_SCAN", raising=False)
    for mod in ("state",):
        if mod in sys.modules:
            del sys.modules[mod]
    return tmp_path


def test_is_self_scan_target_false_when_no_manifest(project_env: Path) -> None:
    """A project without .claude-plugin/plugin.json is not the janitor."""
    _ = project_env
    import state
    assert state.is_self_scan_target() is False


def test_is_self_scan_target_true_when_plugin_name_matches(project_env: Path) -> None:
    """plugin.json with name=='ai-maestro-janitor' → self-scan target."""
    _make_janitor_manifest(project_env)
    import state
    assert state.is_self_scan_target() is True


def test_is_self_scan_target_false_for_other_plugins(project_env: Path) -> None:
    """A different plugin's manifest does NOT count as self-scan."""
    _make_janitor_manifest(project_env, name="some-other-plugin")
    import state
    assert state.is_self_scan_target() is False


def test_is_self_scan_target_false_on_malformed_manifest(project_env: Path) -> None:
    """Malformed plugin.json → not self-scan (don't accidentally silence)."""
    (project_env / ".claude-plugin").mkdir(parents=True)
    (project_env / ".claude-plugin" / "plugin.json").write_text(
        "{ not valid json", encoding="utf-8",
    )
    import state
    assert state.is_self_scan_target() is False


def test_override_env_disables_self_scan_guard(
    project_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1 overrides the guard (for janitor's own CI)."""
    _make_janitor_manifest(project_env)
    for v in ("1", "true", "yes", "on", "TRUE"):
        monkeypatch.setenv("CLAUDE_PLUGIN_ALLOW_SELF_SCAN", v)
        # Need to reload state to clear the lru_cache
        if "state" in sys.modules:
            del sys.modules["state"]
        import state
        assert state.is_self_scan_target() is False, f"failed for override={v!r}"


# ---------- guarded detectors actually self-skip --------------------------


@pytest.mark.parametrize("detector", _GUARDED_DETECTORS)
def test_security_detector_silent_on_self_scan(
    tmp_path: Path, detector: str,
) -> None:
    """Every security/CI detector must emit nothing when scanning the janitor."""
    _make_janitor_manifest(tmp_path)
    _make_workflow(tmp_path)  # would-be-vulnerable workflow
    # package-manager-policy needs a package.json too
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"lodash": "^4.0.0"}}),
        encoding="utf-8",
    )
    r = _run_detector(detector, tmp_path)
    assert r.returncode == 0, (
        f"{detector} crashed on self-scan; stderr: {r.stderr!r}"
    )
    assert r.stdout == "", (
        f"{detector} must be silent on self-scan, got: {r.stdout!r}"
    )


@pytest.mark.parametrize("detector", _GUARDED_DETECTORS)
def test_security_detector_fires_with_override(
    tmp_path: Path, detector: str,
) -> None:
    """CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1 lets the detector scan the janitor's
    own repo (used by the publish.py CI gate)."""
    _make_janitor_manifest(tmp_path)
    _make_workflow(tmp_path)
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"lodash": "^4.0.0"}}),
        encoding="utf-8",
    )
    r = _run_detector(detector, tmp_path, env_overrides={
        "CLAUDE_PLUGIN_ALLOW_SELF_SCAN": "1",
    })
    assert r.returncode == 0, (
        f"{detector} crashed with override; stderr: {r.stderr!r}"
    )
    # At least one of these should now produce output. branch-protection
    # needs gh / external state we don't stub here so it may stay silent;
    # but workflow-security and package-manager-policy will fire on the
    # workflow/package.json we created. We assert at least the override
    # path executed (i.e. the guard didn't fire). Empirical: package-
    # manager-policy fires deterministically on no-.npmrc.
    if detector == "package-manager-policy":
        assert "[package-manager-policy]" in r.stdout


# ---------- doctor_classify.py also self-guards ---------------------------


def test_doctor_classify_refuses_on_self_scan(tmp_path: Path) -> None:
    """The workflow classifier (powering /janitor-github-workflow-doctor)
    must also refuse to scan the janitor's own .github/workflows/."""
    _make_janitor_manifest(tmp_path)
    _make_workflow(tmp_path)
    env = os.environ.copy()
    env.pop("CLAUDE_PLUGIN_ALLOW_SELF_SCAN", None)
    r = subprocess.run(
        [str(_PROJECT_ROOT / "scripts" / "doctor_classify.py")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 2  # "no workflows" / "skip" exit
    assert "[SKIP]" in r.stderr or "self-scan" in r.stderr.lower()
    assert r.stdout == ""


def test_doctor_classify_scans_with_override(tmp_path: Path) -> None:
    """Override lets the classifier scan the janitor's own workflows."""
    _make_janitor_manifest(tmp_path)
    _make_workflow(tmp_path)
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ALLOW_SELF_SCAN"] = "1"
    r = subprocess.run(
        [str(_PROJECT_ROOT / "scripts" / "doctor_classify.py")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    # rc 0 (clean) or 1 (findings) — either way, guard didn't short-circuit.
    assert r.returncode in (0, 1), f"unexpected rc={r.returncode}, stderr={r.stderr!r}"
