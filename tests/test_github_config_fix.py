"""Tests for scripts/github_config_fix.py — the remote-workflow context staging
(TRDD-157OH2D7 follow-up).

The gap this covers: `_project_root_for` used to hand every FOREIGN repo a nonexistent
path, so `detect_required_status_checks` returned [] and a fleet repo's
NO_REQUIRED_CHECKS finding could never be fixed remotely — only ever from that repo's own
checkout. The fix stages the remote workflow files (fetched via gh) into a temp
`.github/workflows/` and feeds the SAME parser. These tests monkeypatch the fetcher — the
network layer stays out; what is proven is the staging + the parser reading it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import branch_protection_lib as bpl  # noqa: E402
import github_config_fix as gcf  # noqa: E402
import pytest  # noqa: E402

_PR_WORKFLOW = """\
name: CI
on:
  push:
  pull_request:
jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  tests:
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
"""

_PUSH_ONLY_WORKFLOW = """\
name: Release
on:
  push:
    tags: ["v*"]
jobs:
  release:
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
"""


def test_local_repo_still_uses_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The current checkout keeps the original behavior — no fetch, cwd as root."""
    monkeypatch.chdir(tmp_path)
    called = []
    monkeypatch.setattr(gcf, "_fetch_remote_workflows", lambda slug: called.append(slug))
    assert gcf._project_root_for("o/r", "o/r") == tmp_path
    assert called == [], "a local repo must never trigger a remote fetch"


def test_foreign_repo_stages_workflows_and_parser_finds_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A foreign slug's fetched workflows land under <tmp>/.github/workflows and the ONE
    shared parser discovers the PR-triggered jobs' contexts from them — push-only
    workflows stay excluded exactly as for a local repo (janitor#14 parity)."""
    monkeypatch.setattr(
        gcf, "_fetch_remote_workflows",
        lambda slug: {"ci.yml": _PR_WORKFLOW, "release.yml": _PUSH_ONLY_WORKFLOW},
    )
    root = gcf._project_root_for("Emasoft/some-fleet-repo", "o/other")
    assert (root / ".github" / "workflows" / "ci.yml").is_file()
    contexts = [c["context"] for c in bpl.detect_required_status_checks(root)]
    assert contexts == ["Lint", "tests"]
    assert "release" not in contexts, "push-only jobs must not become required checks"


def test_foreign_repo_empty_fetch_degrades_to_no_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    """No workflows / no net / no auth → the pre-fetch behavior: a root with no
    workflows dir, i.e. zero contexts and the checks rule omitted (never a 422-ing
    empty contexts array)."""
    monkeypatch.setattr(gcf, "_fetch_remote_workflows", lambda slug: {})
    root = gcf._project_root_for("Emasoft/some-fleet-repo", None)
    assert not (root / ".github" / "workflows").is_dir()
    assert bpl.detect_required_status_checks(root) == []


def test_fetch_survives_gh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fetcher never raises: a gh binary that fails (simulated via a broken PATH)
    yields {} rather than an exception — the fix must degrade, not crash, on an offline
    or unauthenticated host."""
    monkeypatch.setenv("PATH", "/nonexistent-bin-dir")
    assert gcf._fetch_remote_workflows("o/r") == {}
