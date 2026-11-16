"""TRDD-7KPG2PCO increment 2: every PROJECT-domain detector runs main through exit_on_git_root_error.

A failing `git worktree list` raises GitRootError out of issue_catalog.raise_issue / clear_issue /
reconcile (via ticket_proposal -> trdd_common.trdd_files). Without the entry wrap the detector dies in
a multi-line traceback on the agent-visible stderr; with it the failure is one line and exit 1.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DETECTORS_DIR = _ROOT / "scripts" / "detectors"
_ISSUE_CALLS = frozenset({"raise_issue", "clear_issue", "reconcile"})

# Exempt from the entry wrap (TRDD-7KPG2PCO research): these three raise HARNESS-domain issues only,
# which return before ticket_proposal and never reach git. trdd-state-reconciliation is NOT exempt:
# it calls its own `reconcile`, not issue_catalog's, and already wraps its entry (TRDD-56FOY1U1), so
# the structural check covers it.
_EXEMPT = frozenset(
    {
        "janitor-self-integrity",
        "wikimem-syntax",
        "memgrep-index-health",
    }
)


def _called_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _issue_calling_detectors() -> list[str]:
    found = []
    for path in sorted(_DETECTORS_DIR.glob("*.py")):
        if _called_names(ast.parse(path.read_text(encoding="utf-8"))) & _ISSUE_CALLS:
            found.append(path.stem)
    return found


def _main_block_calls_wrap(tree: ast.Module) -> bool:
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            return "exit_on_git_root_error" in _called_names(node)
    return False


_CALLERS = _issue_calling_detectors()


def test_exemptions_are_real_issue_callers() -> None:
    """A stale exemption (renamed or no longer calling issue_catalog) must fail, not hide a detector."""
    assert _EXEMPT <= set(_CALLERS)


@pytest.mark.parametrize("name", [n for n in _CALLERS if n not in _EXEMPT])
def test_detector_entry_wraps_git_root_error(name: str) -> None:
    """A detector that calls raise_issue/clear_issue/reconcile runs main through exit_on_git_root_error."""
    tree = ast.parse((_DETECTORS_DIR / f"{name}.py").read_text(encoding="utf-8"))
    assert _main_block_calls_wrap(tree), f"{name}: __main__ block does not call exit_on_git_root_error"


_VULN_WF = """\
on:
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Building PR ${{ github.event.pull_request.title }}"
"""


def test_workflow_security_failing_git_is_one_stderr_line_and_exit_1(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """A vulnerable workflow reaches raise_issue; a failing `git worktree list` is one stderr line + exit 1."""
    uv = shutil.which("uv")  # resolved BEFORE the PATH override below
    assert uv is not None, "uv must be installed to run this test"
    project = tmp_path / "proj"
    workflow = project / ".github" / "workflows" / "vuln.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(_VULN_WF, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["PATH"] = failing_worktree_list_git_path
    env.pop("CLAUDE_PLUGIN_OPTION_WORKFLOW_SECURITY_ENABLED", None)
    proc = subprocess.run(
        [uv, "run", "--script", "--quiet", str(_DETECTORS_DIR / "workflow-security.py")],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 1, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, proc.stderr
    assert lines[0].startswith("workflow-security:"), proc.stderr
    assert "git failed resolving the design root" in lines[0], proc.stderr
    assert str(tmp_path) not in proc.stderr, proc.stderr
