"""design-tracked — a PROJECT design/ must never be gitignored (TRDD-58Q791FL).

Real temp git repos, the real detector in a subprocess; the global state dir is isolated by
conftest. The incident behind it: a `/design/` line in `.git/info/exclude` hid 467 cards.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "design-tracked.py"
_REPORTS = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "reports-gitignore.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path, with_design: bool = True) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    if with_design:
        (repo / "design" / "tasks").mkdir(parents=True)
        (repo / "design" / "tasks" / "card.md").write_text("x\n")
    return repo


def _run(script: Path, repo: Path) -> list[str]:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]


def _ignored(repo: Path, rel: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--no-index", rel],
                          capture_output=True).returncode == 0


def test_info_exclude_line_is_removed_and_other_lines_stay_byte_identical(tmp_path: Path) -> None:
    """The ios-app-authoring incident: only the `/design/` line goes; the rest is byte-exact."""
    repo = _repo(tmp_path)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_bytes(b"# keep\r\n*.log\n/design/\nno-newline-at-end")
    lines = _run(_DETECTOR, repo)
    assert _ignored(repo, "design/tasks/x.md") is False
    assert exclude.read_bytes() == b"# keep\r\n*.log\nno-newline-at-end"
    assert len(lines) == 1 and "info/exclude" in lines[0] and "/design/" in lines[0]


def test_root_gitignore_hiding_design_gets_negations_appended(tmp_path: Path) -> None:
    """A root .gitignore rule is overridden by appended negations, and the probe is clean."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("design/\n")
    lines = _run(_DETECTOR, repo)
    text = (repo / ".gitignore").read_text()
    assert text.startswith("design/\n") and "!/design/\n" in text and "!/design/**\n" in text
    assert not _ignored(repo, "design/proposals/x.md") and not _ignored(repo, "design/x.md")
    assert len(lines) == 1 and "fixed" in lines[0]
    before = text
    _run(_DETECTOR, repo)
    assert (repo / ".gitignore").read_text() == before



def test_later_root_rule_hiding_design_gets_negations_reappended_once(tmp_path: Path) -> None:
    """The negations already sit ABOVE a later `design/` rule, so "both present" appended nothing
    and design/ stayed hidden; the fix re-appends them at the end, once, and a second run is a no-op."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("!/design/\n!/design/**\ndesign/\n")
    lines = _run(_DETECTOR, repo)
    text = (repo / ".gitignore").read_text()
    assert text == "!/design/\n!/design/**\ndesign/\n!/design/\n!/design/**\n"
    assert not _ignored(repo, "design/x.md") and not _ignored(repo, "design/tasks/x.md")
    assert len(lines) == 1 and "fixed" in lines[0]
    assert _run(_DETECTOR, repo) == []
    assert (repo / ".gitignore").read_text() == text


def test_nested_design_gitignore_is_reported_still_hidden_and_never_edited(tmp_path: Path) -> None:
    """A nested ignore beats the root negations, so it is warned about and left alone."""
    repo = _repo(tmp_path)
    nested = repo / "design" / ".gitignore"
    nested.write_text("*\n")
    lines = _run(_DETECTOR, repo)
    assert nested.read_text() == "*\n"
    assert not (repo / ".gitignore").exists()
    assert len(lines) == 1 and "STILL HIDDEN" in lines[0] and "never be gitignored" in lines[0]


def test_autofix_off_only_warns(tmp_path: Path) -> None:
    """With /janitor-autofix-off nothing is edited, the hiding line is just named."""
    repo = _repo(tmp_path)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text("/design/\n")
    (repo / ".janitor" / "state").mkdir(parents=True)
    (repo / ".janitor" / "state" / "autofix-mode.txt").write_text("off\n")
    lines = _run(_DETECTOR, repo)
    assert exclude.read_text() == "/design/\n"
    assert len(lines) == 1 and "STILL HIDDEN" in lines[0]


def test_untracked_old_card_is_reported_once_per_day(tmp_path: Path) -> None:
    """A card untracked for over 24 h gets one line; the second run the same day is silent."""
    repo = _repo(tmp_path)
    card = repo / "design" / "tasks" / "card.md"
    old = time.time() - 3 * 86400
    os.utime(card, (old, old))
    (repo / "design" / "tasks" / ".DS_Store").write_text("")
    first = _run(_DETECTOR, repo)
    assert len(first) == 1 and "1 design card(s) untracked" in first[0] and "card.md" in first[0]
    assert _run(_DETECTOR, repo) == []


def test_fresh_untracked_card_is_not_reported(tmp_path: Path) -> None:
    """Under 24 h old is a card in progress, not a forgotten one."""
    assert _run(_DETECTOR, _repo(tmp_path)) == []


def test_no_design_dir_is_silent(tmp_path: Path) -> None:
    """A project with no design/ and nothing tracked there is none of this detector's business."""
    assert _run(_DETECTOR, _repo(tmp_path, with_design=False)) == []


def test_reports_dirs_not_ignored_get_their_lines_appended(tmp_path: Path) -> None:
    """The existing reports-gitignore detector already enforces reports/ and reports_dev/."""
    repo = _repo(tmp_path)
    lines = _run(_REPORTS, repo)
    text = (repo / ".gitignore").read_text()
    assert "/reports/\n" in text and "/reports_dev/\n" in text
    assert _ignored(repo, "reports/x.md") and _ignored(repo, "reports_dev/x.md")
    assert len(lines) == 1
