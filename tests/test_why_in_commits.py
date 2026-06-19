"""Tests for the why-in-commits detector (scripts/detectors/why-in-commits.py).

Real fixtures, no mocks. The detector is invoked AS A SUBPROCESS — exactly how the
heartbeat runs it — so each case is hermetic (fresh process). Fixtures are real: a
real ``git init`` repo with real commits (subject-only vs subject+body, backdated
via GIT_*_DATE for the window test). The ai-maestro gate is forced via
JANITOR_FORCE_AI_MAESTRO so the tmp repo needs no plugin manifest.

Covers TRDD-87935f21 priority #6 (WHY-in-commits enforcement):
- FIRES on ≥3 subject-only feat/fix/refactor commits.
- SILENT below threshold, when commits carry a body, for non-substantive types
  (docs/chore/test), outside the ai-maestro gate, and for commits older than the
  3-day window.
- DEDUPE: a second run on the same deficient set is silent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "detectors" / "why-in-commits.py"
)

_OPT_VARS = ("CLAUDE_PLUGIN_OPTION_WHY_IN_COMMITS_MIN",)


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = dict(os.environ)
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True, env=env)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _commit(repo: Path, rel: str, subject: str,
            body: str | None = None, *, date: str | None = None) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{subject}\n{rel}\n", encoding="utf-8")
    _git(repo, "add", rel)
    args = ["commit", "-q", "-m", subject]
    if body is not None:
        args += ["-m", body]
    _git(repo, *args, date=date)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def _run(repo: Path, home: Path, *, ai_maestro: bool = True, **opts: str) -> str:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["CLAUDE_SESSION_ID"] = "test-session-fixed"
    env["JANITOR_FORCE_AI_MAESTRO"] = "1" if ai_maestro else "0"
    for v in _OPT_VARS:
        env.pop(v, None)
    for k, val in opts.items():
        env[f"CLAUDE_PLUGIN_OPTION_WHY_IN_COMMITS_{k.upper()}"] = val
    proc = subprocess.run(
        [sys.executable, str(_DETECTOR)],
        cwd=str(repo if repo.is_dir() else repo.parent),
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_fires_on_subject_only_substantive_commits(tmp_path, home):
    """≥3 subject-only feat/fix/refactor commits → one nudge line."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "a.py", "feat: alpha")
    _commit(repo, "b.py", "fix: beta")
    _commit(repo, "c.py", "refactor: gamma")
    out = _run(repo, home)
    assert "[why-in-commits]" in out
    assert "3 recent" in out


def test_silent_below_threshold(tmp_path, home):
    """Only 2 deficient commits (default threshold 3) → silent."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "a.py", "feat: alpha")
    _commit(repo, "b.py", "fix: beta")
    assert _run(repo, home) == ""


def test_commits_with_body_are_compliant(tmp_path, home):
    """feat/fix commits that carry a body (a WHY) are never flagged."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(4):
        _commit(repo, f"f{i}.py", f"feat: thing {i}", body="because the WHY is here")
    assert _run(repo, home) == ""


def test_non_substantive_types_excluded(tmp_path, home):
    """Subject-only docs/chore/test commits are NOT candidates (legitimately terse)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "a.md", "docs: alpha")
    _commit(repo, "b.txt", "chore: beta")
    _commit(repo, "c_test.py", "test: gamma")
    assert _run(repo, home) == ""


def test_silent_outside_ai_maestro_gate(tmp_path, home):
    """Not an ai-maestro project → silent even with deficient commits."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(3):
        _commit(repo, f"f{i}.py", f"feat: thing {i}")
    assert _run(repo, home, ai_maestro=False) == ""


def test_old_commits_outside_window_excluded(tmp_path, home):
    """Deficient commits older than the 3-day window are not counted.

    A fixed absolute past date (git's GIT_COMMITTER_DATE rejects relative forms);
    the detector's `--since=3 days ago` is computed at runtime so 2020 is excluded.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(3):
        _commit(repo, f"f{i}.py", f"feat: thing {i}", date="2020-01-01T00:00:00")
    assert _run(repo, home) == ""


def test_dedupe_second_run_same_set_silent(tmp_path, home):
    """Two runs on the same deficient set → exactly one nudge (no re-nag of
    un-amendable history)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "a.py", "feat: alpha")
    _commit(repo, "b.py", "fix: beta")
    _commit(repo, "c.py", "refactor: gamma")
    assert "[why-in-commits]" in _run(repo, home)
    assert _run(repo, home) == ""
