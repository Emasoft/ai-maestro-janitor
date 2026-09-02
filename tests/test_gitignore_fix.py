"""gitignore-fix — the remedy command for gitignore-coverage findings. TRDD-VMXAF9IY."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "gitignore_fix.py"


def _seed(repo: Path) -> None:
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")


def _run(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo", str(repo), *extra],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def test_missing_dotenv_is_proposed_and_only_written_after_apply(tmp_path: Path) -> None:
    """Criterion 1: a repo missing `.env` coverage proposes exactly `.env`, unwritten until --apply."""
    repo = tmp_path / "seed"
    _seed(repo)
    (repo / ".gitignore").write_text("*.log\n")

    proposed = _run(repo)
    assert "+.env" in proposed.stdout
    assert (repo / ".gitignore").read_text() == "*.log\n"  # untouched by propose mode

    _run(repo, "--apply")
    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines[0] == "*.log"  # the original line stays first — only appended after
    assert ".env" in lines[1:]


def test_a_tracked_dotenv_prints_git_rm_cached_but_never_runs_it(tmp_path: Path) -> None:
    """Criterion 2: a tracked `.env` gets a printed `git rm --cached .env`, and stays tracked."""
    repo = tmp_path / "seed"
    _seed(repo)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    (repo / ".env").write_text("x=1\n")
    git("add", ".env")
    git("commit", "-qm", "seed")

    proposed = _run(repo)
    assert "git rm --cached .env" in proposed.stdout

    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert ".env" in tracked


def test_apply_preserves_existing_lines_order_and_negations_byte_identical(tmp_path: Path) -> None:
    """Criterion 3: --apply only appends; existing lines, order, and `!` lines stay byte-identical."""
    repo = tmp_path / "seed"
    _seed(repo)
    original = "*.log\n/.trashcan/*\n!/.trashcan/.gitkeep\n"
    (repo / ".gitignore").write_text(original)

    _run(repo, "--apply")

    after = (repo / ".gitignore").read_text()
    assert after.startswith(original)
    prefix_lines = original.splitlines()
    after_lines = after.splitlines()
    assert after_lines[: len(prefix_lines)] == prefix_lines


def test_protected_prefixes_never_appear_in_either_direction(tmp_path: Path) -> None:
    """Criterion 4: design/** and .claude/project/memory/** are never proposed to ignore or untrack."""
    repo = tmp_path / "seed"
    _seed(repo)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    (repo / "design" / "tasks").mkdir(parents=True)
    (repo / "design" / "tasks" / "x.md").write_text("x\n")
    (repo / ".claude" / "project" / "memory").mkdir(parents=True)
    (repo / ".claude" / "project" / "memory" / "p.md").write_text("p\n")
    git("add", "design", ".claude")
    git("commit", "-qm", "seed")

    proposed = _run(repo)
    assert "design" not in proposed.stdout
    assert "memory" not in proposed.stdout
    assert "git rm --cached" not in proposed.stdout
