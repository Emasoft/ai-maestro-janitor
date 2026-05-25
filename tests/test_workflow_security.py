"""Tests for the workflow-security detector.

The detector lives at scripts/detectors/workflow-security.py. Tests run it
as a subprocess (the real invocation surface — matches how dispatch.py
spawns it), with CLAUDE_PROJECT_DIR pointed at a tmp_path so state.py's
lru_cache and per-project .janitor/state stay isolated per test.

The detector runs the janitor's native Sentinel scanner and surfaces ONLY
CRITICAL/HIGH findings; MAJOR/MINOR are left to the on-demand doctor
skill. The fixtures below are grounded in the scanner's real output:
  * VULN_WF trips shell-injection-expr (CRITICAL).
  * SAFE_WF is the hardened reference workflow — zero findings.
  * LOWSEV_WF trips only MAJOR/MINOR rules (missing-permissions etc.),
    so the detector must stay silent on it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "workflow-security.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


# A CRITICAL finding: attacker-controlled PR title interpolated into a run
# block (shell-injection-expr).
VULN_WF = """\
on:
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Building PR ${{ github.event.pull_request.title }}"
"""

# The hardened reference — fires zero rules across every tier.
SAFE_WF = """\
name: CI
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - run: npm ci
"""

# Only MAJOR/MINOR findings (missing-permissions=MAJOR, missing-timeouts,
# overly-broad-triggers=MINOR, missing-frozen-lockfile=MAJOR). No CRITICAL/HIGH.
LOWSEV_WF = """\
on:
  push:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: npm install
"""


def _write_wf(project_dir: Path, name: str, content: str) -> Path:
    wf = project_dir / ".github" / "workflows" / name
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(content, encoding="utf-8")
    return wf


def _run(project_dir: Path, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_WORKFLOW_SECURITY_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    # Generous timeout: the first invocation may resolve uv deps (re2, pyyaml);
    # later invocations reuse the uv cache and finish in well under a second.
    return subprocess.run([str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=120)


def test_fires_on_critical_injection(tmp_path: Path) -> None:
    """A CRITICAL template-injection workflow surfaces a drift line."""
    _write_wf(tmp_path, "vuln.yml", VULN_WF)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "[workflow-security]" in r.stdout
    assert "CRITICAL" in r.stdout
    assert "shell-injection-expr" in r.stdout


def test_silent_on_hardened(tmp_path: Path) -> None:
    """A fully-hardened workflow produces no output."""
    _write_wf(tmp_path, "ci.yml", SAFE_WF)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_on_low_severity_only(tmp_path: Path) -> None:
    """A workflow with only MAJOR/MINOR findings is silent (only CRITICAL/HIGH ride)."""
    _write_wf(tmp_path, "lowsev.yml", LOWSEV_WF)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_no_workflows_dir_silent(tmp_path: Path) -> None:
    """A project with no .github/workflows/ is silent (not a CI repo)."""
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_empty_workflows_dir_silent(tmp_path: Path) -> None:
    """An existing-but-empty .github/workflows/ is silent."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_cache_short_circuit(tmp_path: Path) -> None:
    """An unchanged workflow set re-emits nothing on the second pass."""
    _write_wf(tmp_path, "vuln.yml", VULN_WF)
    first = _run(tmp_path)
    assert "[workflow-security]" in first.stdout, first.stderr

    second = _run(tmp_path)
    assert second.returncode == 0, second.stderr
    assert second.stdout == ""  # content-hash short-circuit

    stamp = tmp_path / ".janitor" / "state" / "workflow-security-last-hash.ts"
    assert stamp.is_file()


def test_reedit_rescans_and_realerts(tmp_path: Path) -> None:
    """Fixing then reverting a workflow re-alerts (hash transition)."""
    wf = _write_wf(tmp_path, "vuln.yml", VULN_WF)
    assert "[workflow-security]" in _run(tmp_path).stdout

    wf.write_text(SAFE_WF, encoding="utf-8")  # fix it
    assert _run(tmp_path).stdout == ""

    wf.write_text(VULN_WF, encoding="utf-8")  # revert to vulnerable
    assert "[workflow-security]" in _run(tmp_path).stdout


def test_disabled_env_silent(tmp_path: Path) -> None:
    """Setting WORKFLOW_SECURITY_ENABLED=0 silences even a vulnerable workflow."""
    _write_wf(tmp_path, "vuln.yml", VULN_WF)
    r = _run(tmp_path, {"CLAUDE_PLUGIN_OPTION_WORKFLOW_SECURITY_ENABLED": "0"})
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_yaml_extension_is_scanned(tmp_path: Path) -> None:
    """A .yaml (not .yml) workflow is scanned — no blind spot for that suffix."""
    _write_wf(tmp_path, "vuln.yaml", VULN_WF)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "shell-injection-expr" in r.stdout
