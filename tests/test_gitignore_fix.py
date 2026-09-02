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
    assert "+.env\n" in proposed.stdout
    # The diff is what the user confirms on: every header on its own line, the unchanged
    # line as context, the new pattern as its own "+" line — not glued together.
    assert "--- .gitignore\n+++ .gitignore (proposed)\n@@ " in proposed.stdout, proposed.stdout
    assert "\n *.log\n+.env\n" in proposed.stdout, proposed.stdout
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
    """Criterion 3: --apply only appends; existing bytes (CRLF, `!` lines, no final newline) stay byte-identical."""
    repo = tmp_path / "seed"
    _seed(repo)
    # Deliberately hostile to a split-and-rejoin implementation: a CRLF line, a negation, and
    # NO trailing newline. Byte-identical means these survive exactly as written.
    original = b"*.log\r\n/.trashcan/*\n!/.trashcan/.gitkeep"
    (repo / ".gitignore").write_bytes(original)

    _run(repo, "--apply")

    after = (repo / ".gitignore").read_bytes()
    assert after.startswith(original + b"\n"), after
    appended = after[len(original) + 1 :].decode()
    assert appended and all(line for line in appended.rstrip("\n").split("\n")), appended
    assert b".env" in after  # something real was appended after the preserved prefix


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


def test_a_git_failure_exits_nonzero_and_writes_nothing(tmp_path: Path) -> None:
    """Fail fast: when git cannot answer (not a repo), --apply exits non-zero and never touches .gitignore."""
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    (not_a_repo / ".gitignore").write_text("*.log\n")

    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo", str(not_a_repo), "--apply"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0, proc.stdout
    assert "git ls-files failed" in proc.stderr, proc.stderr
    assert (not_a_repo / ".gitignore").read_text() == "*.log\n"  # an unknown answer writes nothing
