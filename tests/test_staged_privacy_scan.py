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


# ---- Machine-generated-line suppression (issues #316/#314) ----------------


def test_cargo_lock_checksum_does_not_block(repo: Path) -> None:
    """Issue #316 main body: a Cargo.lock `checksum = "…"` hex line reads as
    an SSN (the regex's separators are optional) — machine-generated lines
    must not block a dependency bump. The EXACT repro from the issue."""
    _stage(repo, "Cargo.lock", (
        '[[package]]\nname = "libc"\n'
        'version = "0.2.169"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        'checksum = "cb4cb245038516f5f85277875cdaa4f7d2c9a0fa0468de06ed190163b1581fcf"\n'
    ))
    assert sps.scan_staged(repo) == []
    # The suppression is disclosed, never silent.
    assert sps._LAST_SUPPRESSED == 5


def test_checksum_key_assignment_in_other_file_suppressed(repo: Path) -> None:
    """The line-shape fallback is KEY-NAME-GATED: outside a lockfile, only
    exact generated-manifest keys (checksum/integrity/resolved) suppress."""
    _stage(repo, "notes.md", (
        'integrity = "sha512-cb4cb245038516f5f85277875cdaa4f7d2c9a0fa0468de06ed190163b1581fcf=="\n'
    ))
    assert sps.scan_staged(repo) == []


def test_bare_hex_run_outside_lockfile_still_blocks(repo: Path) -> None:
    """A hand-pasted hex-looking token in an ordinary file is NOT suppressed
    by the bare-hex shape (only named lockfiles get that) — it still reads
    as an SSN shape and blocks."""
    _stage(repo, "handwritten.md", "token cb4cb245038516f5f85277875cdaa4f7d2c9a0fa0468de06ed190163b1581fcf end\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "pii-us_ssn"]
    assert len(hits) == 1


def test_trdd_governance_author_token_does_not_block(repo: Path) -> None:
    """Issue #314: trddgrep's `<role>@<project-id>` governance author token
    matches the ssh user-at-host shape but names no machine — must not block
    every new TRDD card."""
    _stage(repo, "TRDD-card.md", (
        "---\ntrdd-id: ABCD1234\ncurrent-owner: main-agent@ai-maestro-janitor\n---\n"
    ))
    assert [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"] == []


def test_chief_of_staff_token_suppressed(repo: Path) -> None:
    """Other vocabulary roles from the closed set are suppressed too."""
    _stage(repo, "card2.md", "assignee: chief-of-staff@my-project-x\n")
    assert [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"] == []


def test_role_agent_suffix_token_suppressed(repo: Path) -> None:
    """`<anything>-agent@<dotless-host>` — the `agent` suffix convention —
    is suppressed."""
    _stage(repo, "card3.md", "owner: reviewer-agent@some-project\n")
    assert [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"] == []


def test_real_ssh_target_still_blocks(repo: Path) -> None:
    """Negative control: a real ssh-shaped target is NOT suppressed by the
    governance allow (dotless host, non-role user) — fail toward blocking."""
    _stage(repo, "deploy.md", "ssh deploy@web-1\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"]
    assert len(hits) == 1


def test_real_lowercase_user_dotless_host_still_blocks(repo: Path) -> None:
    """Negative control: `dev-alice@web-1` is a lowercase-hyphenated PERSON,
    not a role token — never swallowed by a general regex."""
    _stage(repo, "deploy2.md", "ssh dev-alice@web-1\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"]
    assert len(hits) == 1


def test_agent_suffix_with_digit_host_still_blocks(repo: Path) -> None:
    """Negative control: `deploy-agent@web-1` is a REAL service-account ssh
    convention (review round on the suppress layer): the *-agent suffix only
    suppresses when the host is digit-free (project-id shape); a numbered
    hostname is a machine."""
    _stage(repo, "deploy3.md", "ssh deploy-agent@web-1\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"]
    assert len(hits) == 1


def test_real_ssn_still_blocks(repo: Path) -> None:
    """Negative control: a real-looking SSN outside a checksum line blocks."""
    _stage(repo, "form.txt", "SSN: 123-45-6789\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "pii-us_ssn"]
    assert len(hits) == 1


def test_personal_home_and_email_still_block(repo: Path) -> None:
    """Negative control: tilde home, dotted ssh host, personal e-mail all
    still fire (only the governance shape is suppressed)."""
    _stage(repo, "mixed.md", (
        f"home {_mac_home('someone_else')}\n"
        "ssh alice@some-real-host.local\n"
        f"mail {LEAK}\n"
    ))
    rules = {h.rule for h in sps.scan_staged(repo)}
    assert "private-path.macos-user-home" in rules
    assert "private-path.ssh-user-host" in rules
    assert "personal-email" in rules


def test_tilde_typesafe_still_suppressed(repo: Path) -> None:
    """The already-committed tilde fix (d0f3d53e): `~typesafe/jev-latest` is
    a model id, not a home — still suppressed."""
    _stage(repo, "model.md", "route to ~typesafe/jev-latest for prose\n")
    assert [h for h in sps.scan_staged(repo) if h.rule == "private-path.tilde-user-home"] == []


def test_host_identity_token_still_checked_on_generated_lines(repo: Path) -> None:
    """A machine-generated file is not human-written, but a human COULD have
    typed a secret/username into one — the host-identity token check is a
    real-token check, not a shape guess, so it STAYS ON for suppressed
    lines. (The token is the host's real username, assembled at runtime.)"""
    import getpass
    user = getpass.getuser()
    if not user or user in ("root", "runner", "user"):  # generic/CI — no signal
        pytest.skip("generic host username carries no identity signal")
    _stage(repo, "Cargo.lock", f'checksum = "cb4cb245038516f5f85277875cdaa4f7d2c9a0fa0468de06ed190163b1581fcf" owner={user}\n')
    hits = [h for h in sps.scan_staged(repo) if h.rule == "host-identity"]
    assert len(hits) == 1
