"""Tests for the memorize-nudge detector (scripts/detectors/memorize-nudge.py).

Real fixtures, no mocks. The detector is invoked AS A SUBPROCESS — exactly how the
heartbeat runs it — so each case is hermetic (a fresh process, no lru-cached
project-root / no shared in-memory state) and the test mirrors production. The
fixtures are real: a real ``git init`` repo with real commits, real memory note
files whose mtimes are set with ``os.utime`` to control the "last memorized"
clock, and HOME/CLAUDE_PROJECT_DIR redirected to tmp so the live tree is untouched.

Covers the acceptance for TRDD-87935f21 priority #6:
- FIRES on ≥ threshold substantive commits since the last note (adoption present).
- SILENT below threshold, when the wiki is empty (adoption gate), when every
  commit is bookkeeping, when a note is newer than the commits (gap closed), and
  when not inside a git repo.
- AGGRESSIVE mode (require_adoption=false) nudges an empty wiki.
- DEDUPE: a second run in the same interval/session is silent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "detectors" / "memorize-nudge.py"
)

# Option vars the test must NOT inherit from the surrounding session, so the
# detector's documented defaults (threshold 3, interval 4h, adoption required)
# apply unless a test sets them explicitly.
_OPT_VARS = (
    "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_MIN_COMMITS",
    "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_INTERVAL",
    "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_REQUIRE_ADOPTION",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _commit(repo: Path, rel: str, content: str, msg: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", msg)


def _write_note(repo: Path, name: str, *, age_s: float) -> Path:
    """Write a PROJECT-scope memory note whose mtime is `age_s` seconds in the
    past (negative age_s → in the future, i.e. 'memorized after the commits')."""
    mem = repo / ".claude" / "project" / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    note = mem / name
    note.write_text("---\nname: x\n---\nbody\n", encoding="utf-8")
    t = time.time() - age_s
    os.utime(note, (t, t))
    return note


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def _run(repo: Path, home: Path, **opts: str) -> str:
    """Run the detector as a fresh subprocess (the heartbeat's contract).

    `opts` set CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_* vars; any not given are
    REMOVED from the env so the detector defaults apply.
    """
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["CLAUDE_SESSION_ID"] = "test-session-fixed"
    for v in _OPT_VARS:
        env.pop(v, None)
    for k, val in opts.items():
        env[f"CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_{k.upper()}"] = val
    proc = subprocess.run(
        [sys.executable, str(_DETECTOR)],
        cwd=str(repo if repo.is_dir() else repo.parent),
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_fires_on_substantive_commits_after_last_note(tmp_path, home):
    """≥3 substantive commits after the last memory note → one nudge line."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)  # memorized 2h ago
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x = {i}\n", f"feat: thing {i}")
    out = _run(repo, home)
    assert "[memorize-nudge]" in out
    assert "3 substantive commit(s)" in out


def test_silent_below_threshold(tmp_path, home):
    """Only 2 substantive commits (default threshold 3) → silent."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)
    for i in range(2):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    assert _run(repo, home) == ""


def test_silent_when_no_notes_adoption_gate(tmp_path, home):
    """No memory note anywhere → adoption gate keeps it silent (never nag a
    project that does not use the wiki)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(5):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    assert _run(repo, home) == ""


def test_aggressive_mode_nudges_empty_wiki(tmp_path, home):
    """require_adoption=false nudges even an empty wiki (the fleet's choice)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    out = _run(repo, home, require_adoption="false")
    assert "[memorize-nudge]" in out


def test_bookkeeping_commits_do_not_count(tmp_path, home):
    """Memory writes, TRDD/design edits, and release commits are NOT substantive."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)
    _commit(repo, ".claude/project/memory/n1.md", "a\n", "docs(memory): note")
    _commit(repo, "design/tasks/TRDD-x.md", "b\n", "docs(trdd): plan")
    _commit(repo, "CHANGELOG.md", "c\n", "chore(release): v1.2.3")
    assert _run(repo, home) == ""


def test_silent_when_note_is_newer_than_commits(tmp_path, home):
    """A note written AFTER the commits (gap closed) → window collapses → silent.

    The note mtime is set 5 min in the future so it is unambiguously newer than
    the just-made commits — the deterministic stand-in for 'already memorized'.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(4):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    _write_note(repo, "fresh.md", age_s=-300)  # mtime = now + 5 min
    assert _run(repo, home) == ""


def test_silent_outside_git_repo(tmp_path, home):
    """Not a git work tree → silent (nothing to nudge about)."""
    bare = tmp_path / "plain"
    bare.mkdir()
    (bare / ".claude" / "project" / "memory").mkdir(parents=True)
    (bare / ".claude" / "project" / "memory" / "n.md").write_text("x\n")
    assert _run(bare, home) == ""


def test_dedupe_second_run_in_same_interval_silent(tmp_path, home):
    """Two runs in the same interval/session → exactly one nudge (no per-commit spam)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    assert "[memorize-nudge]" in _run(repo, home)
    assert _run(repo, home) == ""
