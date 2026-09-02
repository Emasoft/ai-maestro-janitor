"""Tests for the personal-address lint (TRDD-QW7K3M2V): `_added_lines_since` and
`_personal_email_hits` in scripts/publish.py — the gate that blocks a push from
introducing a new raw personal e-mail address into this public repo.

Real git repositories in tmp_path, real `git diff` — no mocks, because the whole
behaviour under test is how `git diff --unified=0` shapes hunk headers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402

# The flaggable addresses are ASSEMBLED at runtime, never written as literals:
# this file is itself tracked in the public repo, and the gate under test scans
# every added line of every tracked file — a literal gmail address here would
# block the very publish that ships the gate (measured 2026-09-02: six hits in
# this file, then one more from a comment that spelled one out). Splitting the
# `@` keeps the regex from ever matching the source.
_AT = "@"


def _gmail(local: str) -> str:
    return f"{local}{_AT}gmail.com"


JOHN = _gmail("john.doe")
OLD = _gmail("old")
NEW = _gmail("new")


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True, timeout=30,
    )
    return r.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real git repo with a `base` branch and a `work` branch one commit ahead."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "notes.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    _git(r, "add", "notes.txt")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "branch", "base")
    _git(r, "checkout", "-q", "-b", "work")
    return r


def _hits(repo: Path, base_ref: str = "base") -> list[tuple[str, int, str]]:
    def known_for(path: str) -> frozenset[str]:
        return frozenset(publish._base_ref_email_addresses(repo, base_ref, path))

    return publish._personal_email_hits(publish._added_lines_since(repo, base_ref), known_for)


def test_new_personal_address_is_flagged_and_masked(repo: Path) -> None:
    """An added line with a raw gmail address yields one masked hit."""
    (repo / "notes.txt").write_text(f"line1\nline2\nline3\ncontact: {JOHN}\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "add contact")
    assert _hits(repo) == [("notes.txt", 4, "j***" + _AT + "gmail.com")]


def test_allow_listed_placeholder_addresses_are_not_flagged(repo: Path) -> None:
    """noreply / example / .local addresses added on top of base yield zero hits."""
    (repo / "notes.txt").write_text(
        "line1\nline2\nline3\n"
        "713559+Emasoft@users.noreply.github.com\n"
        "alice@example.com\n"
        "bob@host.local\n",
        encoding="utf-8",
    )
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "add placeholders")
    assert _hits(repo) == []


def test_preexisting_address_untouched_by_new_commits_is_ignored(repo: Path) -> None:
    """An address already on the base ref, never touched since, is out of scope."""
    _git(repo, "checkout", "-q", "base")
    (repo / "notes.txt").write_text(f"line1\nline2\nline3\n{OLD}\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "old address on base")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "-q", "base")
    (repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-q", "-m", "unrelated change")
    assert _hits(repo) == []


def test_modified_line_only_flags_when_it_adds_a_new_address(repo: Path) -> None:
    """A modified line keeping an old address is clean; adding a second address is a hit."""
    _git(repo, "checkout", "-q", "base")
    (repo / "notes.txt").write_text(f"line1\nline2\nline3\n{OLD}\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "old address on base")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "-q", "base")

    # Reformat the line but keep the same single address -> no new hit.
    (repo / "notes.txt").write_text(f"line1\nline2\nline3\ncontact ({OLD})\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "reformat, same address")
    assert _hits(repo) == []

    # Now add a second, new address on the same line -> one hit.
    (repo / "notes.txt").write_text(
        f"line1\nline2\nline3\ncontact ({OLD}, {NEW})\n", encoding="utf-8"
    )
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "add a second address")
    assert _hits(repo) == [("notes.txt", 4, "n***" + _AT + "gmail.com")]


def test_address_known_only_in_another_file_is_still_new_for_a_new_file(repo: Path) -> None:
    """An address that lives in file A on the base ref is a NEW disclosure when pasted into file B."""
    _git(repo, "checkout", "-q", "base")
    (repo / "notes.txt").write_text(f"line1\nline2\nline3\n{OLD}\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "old address on base, in notes.txt only")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "-q", "base")
    (repo / "copy.txt").write_text(f"see {OLD}\n", encoding="utf-8")
    _git(repo, "add", "copy.txt")
    _git(repo, "commit", "-q", "-m", "paste the address into a new file")
    assert _hits(repo) == [("copy.txt", 1, "o***" + _AT + "gmail.com")]


def test_added_lines_since_reports_correct_new_line_numbers(repo: Path) -> None:
    """`_added_lines_since` reports the right new-file line numbers for an insertion hunk."""
    (repo / "notes.txt").write_text("line1\nline2\ninserted-a\ninserted-b\nline3\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "insert two lines after line 2")
    added = publish._added_lines_since(repo, "base")
    assert added == [
        ("notes.txt", 3, "inserted-a"),
        ("notes.txt", 4, "inserted-b"),
    ]
