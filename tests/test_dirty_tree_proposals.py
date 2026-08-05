"""dirty-tree must not nag about the janitor's OWN proposal files.

The janitor is a GUEST in the user's repo: on a PROJECT-domain finding it may only PROPOSE, which
means writing a TRDD into `design/proposals/` — and it is forbidden to commit that file, because
running the approval command IS the approval. So the janitor authored a file it could not clear,
and `dirty-tree` counted it as the user's uncommitted work and nagged every window, forever.

Observed on a real host (reported by the Claude developing AgentlensPro): the same single item
nagged from 443 to 487 minutes, unclearable, while the ticket channel reported the SAME object as
"2 janitor proposal(s) await YOUR approval". One item, two unrelated-looking alarms, neither
actionable by the reader — *"a self-sustaining loop, not two problems"*.

Real git repos in temp dirs; no mocks.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "dirty-tree.py"


def _load():
    spec = importlib.util.spec_from_file_location("dirty_tree_detector", DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dirty_tree_detector"] = mod
    spec.loader.exec_module(mod)
    return mod


dt = _load()


# --------------------------------------------------------------------------- #
# the pure decision — which `git status --porcelain` lines are the janitor's own
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "line",
    [
        "?? design/proposals/TRDD-20260730_120000+0200-ABC12345-a-finding.md",
        " M design/proposals/TRDD-ABC12345-x.md",
        'A  "design/proposals/TRDD-ABC12345-quoted path.md"',
        "R  design/proposals/TRDD-OLD.md -> design/proposals/TRDD-ABC12345-new.md",
    ],
)
def test_a_janitor_proposal_is_not_the_users_dirty_work(line: str) -> None:
    """Every porcelain spelling of "a proposal TRDD" is excluded, including a rename's NEW path."""
    assert dt._is_janitor_proposal(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "?? src/main.py",                                   # ordinary untracked work
        "?? design/tasks/TRDD-ABC12345-approved.md",        # APPROVED — a real tracked artifact
        "?? design/proposals/README.md",                    # a human's file, not a proposal TRDD
        "?? design/proposals/sub/TRDD-ABC12345-x.md",       # nested — not what propose() writes
        "?? design/proposals/TRDD-ABC12345-x.txt",          # not a markdown TRDD
        "?? notes.md",
    ],
)
def test_everything_else_is_still_counted(line: str) -> None:
    """The exclusion is narrow on purpose — it must not silence the user's real dirty work.

    `design/tasks/` especially: once approved, a TRDD IS committable, so an uncommitted one there
    is genuine dirty work the nag should keep reporting.
    """
    assert dt._is_janitor_proposal(line) is False


# --------------------------------------------------------------------------- #
# end to end, against a real git repo
# --------------------------------------------------------------------------- #

def _repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return tmp_path


def _run(project: Path, home: Path) -> str:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_PLUGIN_OPTION_DIRTY_TREE_THRESHOLD"] = "0"  # nag immediately if it would nag
    res = subprocess.run(
        [sys.executable, str(DETECTOR)], capture_output=True, text=True, env=env, timeout=60
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


def test_a_tree_dirty_ONLY_with_janitor_proposals_is_silent(tmp_path: Path) -> None:
    """THE regression: the janitor must not report a mess consisting solely of its own output."""
    project = _repo(tmp_path / "proj")
    (project / "design" / "proposals").mkdir(parents=True)
    (project / "design" / "proposals" / "TRDD-20260730_120000+0200-ABC12345-finding.md").write_text(
        "---\ntrdd-id: ABC12345\n---\n", encoding="utf-8"
    )

    assert _run(project, tmp_path / "home") == ""


def test_real_dirty_work_alongside_a_proposal_still_nags(tmp_path: Path) -> None:
    """The exclusion narrows the count; it must never zero out the user's own uncommitted work."""
    project = _repo(tmp_path / "proj2")
    (project / "design" / "proposals").mkdir(parents=True)
    (project / "design" / "proposals" / "TRDD-ABC12345-finding.md").write_text("x", encoding="utf-8")
    (project / "real_work.py").write_text("print(1)\n", encoding="utf-8")

    out = _run(project, tmp_path / "home2")

    assert "dirty-tree" in out
    assert "1 uncommitted" in out, f"only the user's own file should be counted, got: {out!r}"


def test_the_nudge_never_recommends_a_bare_git_stash(tmp_path: Path) -> None:
    """#188: the nudge fires on a dirty tree — exactly when uncommitted work exists to be
    destroyed — and on a concurrent-agent host a bare `git stash` swallows every OTHER agent's
    in-flight edits silently (the near-miss is recorded in the issue: an agent stashed while two
    others were mid-edit, and only quiet-tree timing made the pop clean). Every recommended move
    must be per-file or additive; the only stash form permitted is the path-scoped
    `git stash push -- <paths>`."""
    project = _repo(tmp_path / "proj3")
    (project / "real_work.py").write_text("print(1)\n", encoding="utf-8")

    out = _run(project, tmp_path / "home3")

    assert "dirty-tree" in out
    assert "'git stash' to park work" not in out, "the whole-tree stash recommendation is back"
    assert "git stash push -- " in out, "the path-scoped escape hatch must be named"
    assert "Never bare 'git stash'" in out
