"""Tests for the doctor_classify --sarif emitter.

Verify the JSON shape matches the SARIF 2.1.0 contract that GitHub
Code Scanning's upload-sarif action ingests.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOCTOR = _PROJECT_ROOT / "scripts" / "doctor_classify.py"

assert _DOCTOR.is_file(), f"doctor_classify not found at {_DOCTOR}"


def _run(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CLAUDE_PLUGIN_ALLOW_SELF_SCAN", None)
    return subprocess.run(
        ["uv", "run", "--quiet", str(_DOCTOR), *args],
        cwd=str(project_dir), env=env,
        capture_output=True, text=True, timeout=120,
    )


VULN_WF = """\
on: pull_request
permissions: write-all
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "${{ github.event.pull_request.title }}"
"""


def _setup(project_dir: Path) -> None:
    workflows = project_dir / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "vuln.yml").write_text(VULN_WF, encoding="utf-8")


def test_sarif_output_is_valid_json(tmp_path: Path) -> None:
    _setup(tmp_path)
    r = _run(tmp_path, "--sarif")
    assert r.returncode == 1, r.stderr  # findings present → exit 1
    # stdout MUST be parseable JSON (no JSON-lines noise mixed in)
    data = json.loads(r.stdout)
    assert isinstance(data, dict)


def test_sarif_schema_2_1_0(tmp_path: Path) -> None:
    _setup(tmp_path)
    r = _run(tmp_path, "--sarif")
    data = json.loads(r.stdout)
    assert data["version"] == "2.1.0"
    assert "$schema" in data
    assert "sarif-schema-2.1.0" in data["$schema"]


def test_sarif_has_tool_driver(tmp_path: Path) -> None:
    _setup(tmp_path)
    r = _run(tmp_path, "--sarif")
    data = json.loads(r.stdout)
    runs = data["runs"]
    assert len(runs) == 1
    driver = runs[0]["tool"]["driver"]
    assert driver["name"] == "ai-maestro-janitor-doctor"
    assert isinstance(driver["rules"], list)
    assert len(driver["rules"]) >= 1


def test_sarif_results_have_locations_and_levels(tmp_path: Path) -> None:
    _setup(tmp_path)
    r = _run(tmp_path, "--sarif")
    data = json.loads(r.stdout)
    results = data["runs"][0]["results"]
    assert len(results) >= 1
    for result in results:
        # Every result MUST carry rule + level + location for upload-sarif
        # to display it correctly in the GitHub UI.
        assert "ruleId" in result
        assert result["level"] in ("error", "warning", "note", "none")
        assert "locations" in result
        loc = result["locations"][0]["physicalLocation"]
        assert "artifactLocation" in loc
        assert "region" in loc
        assert loc["region"]["startLine"] >= 1


def test_sarif_severity_mapping(tmp_path: Path) -> None:
    """CRITICAL/HIGH map to 'error', MAJOR to 'warning', MINOR to 'note'."""
    _setup(tmp_path)
    r = _run(tmp_path, "--sarif")
    data = json.loads(r.stdout)
    levels = {result["level"] for result in data["runs"][0]["results"]}
    # The vuln workflow above contains CRITICAL (shell-injection-expr)
    # so we must see at least one 'error' level result.
    assert "error" in levels


def test_jsonlines_mode_default(tmp_path: Path) -> None:
    """Without --sarif, output is one JSON object per line, no envelope."""
    _setup(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    # Parse each non-empty line as its own JSON object.
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert lines, "expected at least one finding line"
    for line in lines:
        obj = json.loads(line)
        assert "rule_id" in obj
        assert "file" in obj


def test_yaml_extension_is_classified(tmp_path: Path) -> None:
    """A workflow written as .yaml (not .yml) MUST be scanned — GitHub treats
    the two identically, so ignoring .yaml would be a security blind spot."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "vuln.yaml").write_text(VULN_WF, encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stderr  # findings present → scanned, exit 1
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert lines, "expected the .yaml workflow to produce findings"
    # The finding's `file` field must point at the .yaml file we created.
    assert any(json.loads(ln)["file"].endswith("vuln.yaml") for ln in lines)


def test_yaml_extension_in_sarif(tmp_path: Path) -> None:
    """The SARIF emitter must also include the .yaml workflow's findings."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "vuln.yaml").write_text(VULN_WF, encoding="utf-8")
    r = _run(tmp_path, "--sarif")
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    results = data["runs"][0]["results"]
    assert len(results) >= 1


def test_yaml_only_dir_does_not_falsely_report_empty(tmp_path: Path) -> None:
    """A workflows dir containing only .yaml files must NOT exit 2 with
    'no .yml/.yaml files' — the pre-fix bug falsely told the user there was
    nothing to scan."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "vuln.yaml").write_text(VULN_WF, encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode != 2, r.stderr
    assert "no .yml" not in r.stderr
