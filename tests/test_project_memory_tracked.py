"""Tests for the PROJECT-memory gitignore-exception enforcer (TRDD-3f7b6807, P2).

Real fixtures, no mocks. Every case builds an actual `git init` repo in tmp_path,
writes a real `.gitignore`, and exercises `project_memory_tracked.ensure_tracked`
against it — the same way the heartbeat detector does. The CONTRACT under test:

- An ignored `.claude/project/memory/` gets a `.gitignore` EXCEPTION appended so
  it becomes trackable; the result is verified with a real `git check-ignore`.
- An already-compliant repo is a byte-for-byte no-op on `.gitignore`.
- A missing memory dir is "absent" (nothing to do).
- A directory-pruning ignore (bare `.claude/`) is "needs-manual" — git can't
  descend, so an exception can't help, and the enforcer NEVER rewrites the line.
- Running twice never duplicates an exception line (idempotent).
- The enforcer NEVER force-stages: after it runs, the memory file is NOT in the
  staging area (`git diff --cached --name-only`).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import project_memory_tracked  # noqa: E402

_PROBE = ".claude/project/memory/MEMORY.md"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _make_memory_dir(repo: Path) -> Path:
    """Create `.claude/project/memory/MEMORY.md` (the probe file). Returns it."""
    mem = repo / ".claude" / "project" / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    probe = mem / "MEMORY.md"
    probe.write_text("- [seed](seed.md) — hook\n", encoding="utf-8")
    return probe


def _is_ignored(repo: Path) -> bool:
    """True iff git reports the probe path as ignored (check-ignore exit 0)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", _PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


# --- (a) ignored `.claude/**` + memory dir → exception-added -----------------

def test_claude_glob_ignored_gets_exception_added(tmp_path):
    """A `.claude/**`-ignored memory dir → 'exception-added', then NOT ignored."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".gitignore").write_text(".claude/**\n", encoding="utf-8")
    _make_memory_dir(repo)

    assert _is_ignored(repo) is True  # precondition: scope starts ignored

    action, _detail = project_memory_tracked.ensure_tracked(repo)
    assert action == "exception-added"

    # The exception took effect — git no longer ignores the scope.
    assert _is_ignored(repo) is False
    # And all three canonical exception lines are present in .gitignore.
    text = (repo / ".gitignore").read_text(encoding="utf-8")
    for exc in ("!.claude/project/", "!.claude/project/memory/", "!.claude/project/memory/**"):
        assert exc in text.splitlines()


# --- (b) full triplet already present → already-tracked, .gitignore unchanged -

def test_full_triplet_already_present_is_no_op(tmp_path):
    """With the full exception triplet already present → 'already-tracked' and the
    .gitignore is byte-for-byte unchanged."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    original = (
        ".claude/**\n"
        "!.claude/project/\n"
        "!.claude/project/memory/\n"
        "!.claude/project/memory/**\n"
    )
    gi = repo / ".gitignore"
    gi.write_text(original, encoding="utf-8")
    _make_memory_dir(repo)

    assert _is_ignored(repo) is False  # precondition: exceptions already work

    before = gi.read_bytes()
    action, _detail = project_memory_tracked.ensure_tracked(repo)
    after = gi.read_bytes()

    assert action == "already-tracked"
    assert before == after  # not one byte touched


# --- (c) no memory dir → absent ---------------------------------------------

def test_no_memory_dir_is_absent(tmp_path):
    """When `.claude/project/memory/` does not exist → 'absent' (no .gitignore edit)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    gi = repo / ".gitignore"
    gi.write_text(".claude/**\n", encoding="utf-8")

    before = gi.read_bytes()
    action, _detail = project_memory_tracked.ensure_tracked(repo)
    after = gi.read_bytes()

    assert action == "absent"
    assert before == after  # absent → never touches .gitignore


# --- (d) bare `.claude/` directory-prune → needs-manual ----------------------

def test_bare_claude_prune_is_needs_manual(tmp_path):
    """A bare `.claude/` ignore prunes the directory so an exception can't apply →
    'needs-manual', and the enforcer does NOT rewrite the existing ignore line."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    gi = repo / ".gitignore"
    gi.write_text(".claude/\n", encoding="utf-8")
    _make_memory_dir(repo)

    assert _is_ignored(repo) is True  # precondition: scope ignored by the prune

    action, detail = project_memory_tracked.ensure_tracked(repo)
    assert action == "needs-manual"
    assert ".claude/**" in detail  # the remediation hint is surfaced

    # The original directory-pruning line is preserved (NEVER rewritten); the
    # scope remains ignored because git won't descend into a pruned directory.
    assert ".claude/" in gi.read_text(encoding="utf-8").splitlines()
    assert _is_ignored(repo) is True

    # janitor#180: the trial-appended negations are provably INERT under the
    # prune, so they must be ROLLED BACK — the file is byte-identical to before
    # (no dirty tree, no silent reversal of a documented removal).
    assert gi.read_text(encoding="utf-8") == ".claude/\n"


def test_bare_claude_prune_re_run_stays_clean(tmp_path):
    """janitor#180 regression shape: the consuming repo's owner had REMOVED the
    inert negations (with a forbidding comment) and the next enforcer run
    re-appended them. With the rollback, any number of runs leaves the file
    byte-identical and keeps reporting needs-manual."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    gi = repo / ".gitignore"
    original = "# Do NOT re-add the memory negations — inert under the prune.\n.claude/\n"
    gi.write_text(original, encoding="utf-8")
    _make_memory_dir(repo)

    for _ in range(3):
        action, _detail = project_memory_tracked.ensure_tracked(repo)
        assert action == "needs-manual"
        assert gi.read_text(encoding="utf-8") == original


# --- (e) idempotent: two runs, no duplicate lines ---------------------------

def test_idempotent_no_duplicate_lines(tmp_path):
    """Running ensure_tracked twice adds the exception once: no duplicate lines on
    the second run, which reports 'already-tracked'."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".gitignore").write_text(".claude/**\n", encoding="utf-8")
    _make_memory_dir(repo)

    a1, _ = project_memory_tracked.ensure_tracked(repo)
    assert a1 == "exception-added"
    a2, _ = project_memory_tracked.ensure_tracked(repo)
    # Second run: already un-ignored, so it's a no-op.
    assert a2 == "already-tracked"

    lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    for exc in ("!.claude/project/", "!.claude/project/memory/", "!.claude/project/memory/**"):
        assert lines.count(exc) == 1  # exactly one occurrence each, no dupes


# --- (f) NEVER force-add: memory file is not staged --------------------------

def test_never_force_adds_to_staging(tmp_path):
    """After ensure_tracked, the memory file is NOT in the staging area — the
    enforcer only edits .gitignore, it never `git add`/`git add -f`."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / ".gitignore").write_text(".claude/**\n", encoding="utf-8")
    _make_memory_dir(repo)

    action, _detail = project_memory_tracked.ensure_tracked(repo)
    assert action == "exception-added"

    staged = _git(repo, "diff", "--cached", "--name-only").stdout
    staged_files = staged.split()
    # The memory probe must NOT have been force-staged by the enforcer.
    assert _PROBE not in staged_files
    assert not any(f.startswith(".claude/project/memory/") for f in staged_files)
