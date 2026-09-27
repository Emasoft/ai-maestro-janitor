"""Tests for the staged-diff privacy-leak scanner (TRDD-FWDZDB7W step 1):
scripts/lib/staged_privacy_scan.py — the pre-commit gate that blocks a commit
introducing a personal e-mail, a home path or machine-identity leak into this
public repo. Real git repos in tmp_path, real `git add`, real `git diff
--cached` — no mocks, because the behaviour under test is the staged-diff
pipeline itself (same discipline as test_publish_personal_address_gate.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import staged_privacy_scan as sps  # noqa: E402

# Private values are ASSEMBLED at runtime, never written as literals: this
# test file is itself tracked in the public repo and the very gate under test
# scans every added line of every staged file — a literal gmail address or
# home path here would block the commit that ships it (the same reason
# test_publish_personal_address_gate.py splits the `@`).
_AT = "@"

LEAK = "jane.doe" + _AT + "gmail.com"
NOREPLY = "owner" + _AT + "users.noreply.github.com"


def _mac_home(user: str) -> str:
    return "/Users/" + user + "/notes/2026/report.txt"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True, timeout=30,
    )
    return r.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real git repo with one clean base commit."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "notes.txt").write_text("line1\nline2\n", encoding="utf-8")
    _git(r, "add", "notes.txt")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _stage(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)


def test_personal_email_in_staged_diff_is_flagged_and_masked(repo: Path) -> None:
    """An added line with a raw personal e-mail yields one MASKED hit."""
    _stage(repo, "leak.md", f"contact me: {LEAK}\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "personal-email"]
    assert len(hits) == 1
    hit = hits[0]
    assert hit.path == "leak.md"
    assert hit.line == 1
    # The gate's output must never echo the full address (it lands in logs).
    assert "jane.doe" not in hit.masked
    assert hit.masked.endswith(_AT + "gmail.com")


def test_noreply_github_address_passes(repo: Path) -> None:
    """An @users.noreply.github.com address is allow-listed — no e-mail hit."""
    _stage(repo, "ok.md", f"author: {NOREPLY}\n")
    assert [h for h in sps.scan_staged(repo) if h.rule == "personal-email"] == []


def test_clean_diff_passes(repo: Path) -> None:
    """A staged diff with no privacy content produces zero findings."""
    _stage(repo, "clean.py", "x = 1 + 1\nprint(x)\n")
    assert sps.scan_staged(repo) == []


def test_home_path_in_staged_diff_is_flagged(repo: Path) -> None:
    """A macOS home path with a personal user segment is caught (K0PMVRN6 class)."""
    _stage(repo, "path.md", f"lives under {_mac_home('someperson')}\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "private-path.macos-user-home"]
    assert len(hits) == 1
    assert "someperson" not in hits[0].masked


def test_address_already_at_head_is_not_re_flagged(repo: Path) -> None:
    """An address the file already holds at HEAD is not a NEW disclosure —
    editing that file must not block (G1b per-file grandfathering)."""
    (repo / "grand.md").write_text(f"contact: {LEAK}\n", encoding="utf-8")
    _git(repo, "add", "grand.md")
    _git(repo, "commit", "-q", "-m", "grandfather")
    (repo / "grand.md").write_text(f"contact: {LEAK}\nmore text\n", encoding="utf-8")
    _git(repo, "add", "grand.md")
    assert [h for h in sps.scan_staged(repo) if h.rule == "personal-email"] == []


def test_cli_blocks_with_masked_output(repo: Path) -> None:
    """The CLI the hook calls exits 1 on a leak and MASKS the value."""
    _stage(repo, "leak.md", f"mail: {LEAK}\n")
    r = subprocess.run(
        [sys.executable, str(Path(sps.__file__))],
        cwd=str(repo), capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 1
    assert "BLOCKED" in r.stdout
    assert "jane.doe" not in r.stdout
    assert "personal-email" in r.stdout


def test_cli_clean_exits_zero(repo: Path) -> None:
    """The CLI exits 0 on a clean staged diff (hook proceeds)."""
    _stage(repo, "clean.py", "x = 1\n")
    r = subprocess.run(
        [sys.executable, str(Path(sps.__file__))],
        cwd=str(repo), capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0
