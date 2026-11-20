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
from exe_path import exe  # noqa: E402

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
        [exe("git"), *args], cwd=str(repo), capture_output=True, text=True, check=True, timeout=30,
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


def test_bare_hex_run_is_not_an_ssn(repo: Path) -> None:
    """FLIPPED by the hex-boundary fix: a hand-pasted 64-hex token in an ordinary
    file no longer reads as an SSN (a digit run inside a hex token is not an SSN;
    pasted-secret detection belongs to secret-shield/trufflehog), while a real
    SSN on the next line still blocks."""
    _stage(repo, "handwritten.md", (
        "token cb4cb245038516f5f85277875cdaa4f7d2c9a0fa0468de06ed190163b1581fcf end\n"
        "SSN: 123-45-6789\n"
    ))
    hits = [h for h in sps.scan_staged(repo) if h.rule == "pii-us_ssn"]
    assert [h.line for h in hits] == [2]


# An integrity-manifest-shaped entry line whose KEY carries a real SSN shape: it
# is flagged when scanned and suppressed only on the exact manifest path, so it
# discriminates the path gate (a bare 64-hex digest no longer reads as an SSN).
_SSN = "123" + "-" + "45" + "-" + "6789"
_MANIFEST_LINE = (
    "    \"" + _SSN + "\": \"cb4cb245038516f5f85277875cdaa4f7d2c9a0fa0468de06ed190163b1581fcf\",\n"
)


def _ssn_hits(repo: Path) -> list:
    return [h for h in sps.scan_staged(repo) if h.rule == "pii-us_ssn"]


def test_integrity_manifest_entry_line_suppressed(repo: Path) -> None:
    """A digest entry line in the exact integrity-manifest path is suppressed and counted."""
    (repo / ".integrity").mkdir()
    _stage(repo, ".integrity/manifest-sha256.json", "{\n" + _MANIFEST_LINE + "}\n")
    assert _ssn_hits(repo) == []
    assert sps._LAST_SUPPRESSED > 0


def test_manifest_entry_line_in_ordinary_file_still_blocks(repo: Path) -> None:
    """REWRITTEN after the hex-boundary fix (a bare digest no longer hits the SSN
    rule): an entry line carrying a real SSN shape in an ordinary file is still scanned."""
    (repo / "data").mkdir()
    _stage(repo, "data/other.json", _MANIFEST_LINE)
    assert len(_ssn_hits(repo)) == 1
    assert sps._LAST_SUPPRESSED == 0


def test_manifest_basename_in_other_directory_still_blocks(repo: Path) -> None:
    """REWRITTEN after the hex-boundary fix (a bare digest no longer hits the SSN
    rule): the same SSN-keyed entry line in a same-named file elsewhere is still
    scanned (basename is not enough)."""
    (repo / "vendor").mkdir()
    _stage(repo, "vendor/manifest-sha256.json", _MANIFEST_LINE)
    assert len(_ssn_hits(repo)) == 1
    assert sps._LAST_SUPPRESSED == 0


def test_non_entry_line_in_integrity_manifest_still_blocks(repo: Path) -> None:
    """A non-entry line carrying an SSN shape inside the manifest is still scanned."""
    (repo / ".integrity").mkdir()
    ssn = "123" + "-" + "45" + "-" + "6789"
    _stage(repo, ".integrity/manifest-sha256.json", '    "note": "' + ssn + '",\n')
    assert len(_ssn_hits(repo)) == 1


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


def test_own_plugin_spec_does_not_block(repo: Path) -> None:
    """TRDD-ELVVBENI: this repo's own `<plugin>@<marketplace>` spec in an
    install/update command has the ssh user@host shape but names no machine."""
    _stage(repo, "install.md", "claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope user\n")
    assert [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"] == []


@pytest.mark.parametrize("spec", [
    "ai-maestro-janitor@example-host",
    "deploy@ai-maestro-plugins",
    "someone@ai-maestro-plugins.local",
    "ai-maestro-janitor@ai-maestro-plugins-2",
    "other-plugin@ai-maestro-plugins",
])
def test_non_own_plugin_spec_still_blocks(repo: Path, spec: str) -> None:
    """TRDD-ELVVBENI negative control: only the exact own plugin spec is exempt;
    a different host, a different user, a `.local` host or another plugin in
    the same marketplace is still a user@host finding."""
    _stage(repo, "ssh.md", f"ssh {spec}\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"]
    assert len(hits) == 1


def test_own_plugin_spec_blocks_when_manifest_unreadable(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TRDD-ELVVBENI fail-closed path: with plugin.json unreadable the exemption
    is off and the plugin spec flags like any user@host."""
    monkeypatch.setattr(sps, "_PLUGIN_MANIFEST", repo / "missing" / "plugin.json")
    assert sps._own_plugin_spec() is None
    _stage(repo, "install2.md", "claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope user\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "private-path.ssh-user-host"]
    assert len(hits) == 1


def test_own_plugin_spec_blocks_when_marketplace_import_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """TRDD-ELVVBENI fail-closed path: a failing import of version_update_lib turns
    the exemption off (spec flags, scan does not crash) and names the cause on stderr."""
    monkeypatch.setitem(sys.modules, "version_update_lib", None)  # makes `from version_update_lib import ...` raise ImportError
    _stage(repo, "install3.md", "claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope user\n" + LEAK + "\n")
    found = sps.scan_staged(repo)
    assert len([h for h in found if h.rule == "private-path.ssh-user-host"]) == 1
    # The rest of the scan still completes: an unrelated finding in the same file is still reported.
    assert [h for h in found if h.rule == "personal-email"]
    assert "cannot import version_update_lib" in capsys.readouterr().err


def test_own_plugin_spec_blocks_when_marketplace_import_raises_non_import_error(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """TRDD-ELVVBENI: version_update_lib runs Path.home() at import time, which can raise
    RuntimeError (not ImportError) in a bare-HOME CI. The exemption must still just turn
    off (spec flags, rest of the scan completes), never crash the gate; stderr names only
    the exception class."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "version_update_lib.py").write_text("raise RuntimeError(\"simulated import-time failure\")\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "version_update_lib", raising=False)
    monkeypatch.syspath_prepend(str(stub_dir))
    _stage(repo, "install4.md", "claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope user\n" + LEAK + "\n")
    found = sps.scan_staged(repo)
    assert len([h for h in found if h.rule == "private-path.ssh-user-host"]) == 1
    assert [h for h in found if h.rule == "personal-email"]
    err = capsys.readouterr().err
    assert "(RuntimeError)" in err
    assert "simulated import-time failure" not in err


def test_real_ssn_still_blocks(repo: Path) -> None:
    """Negative control: a real-looking SSN outside a checksum line blocks."""
    _stage(repo, "form.txt", "SSN: 123-45-6789\n")
    hits = [h for h in sps.scan_staged(repo) if h.rule == "pii-us_ssn"]
    assert len(hits) == 1



def test_commit_sha_and_32hex_id_in_reports_do_not_block(repo: Path) -> None:
    """A reports/ file citing a 12-hex commit sha and a 32-hex id is not an SSN
    (the 2026-11-14 blocker: hex ids matched the optional-separator SSN shape)."""
    (repo / "reports").mkdir()
    _stage(repo, "reports/x.md", (
        "commit a268903483c2 landed\n"
        "id 633457257a6c4a5882f1ed46b06af84a\n"
    ))
    assert _ssn_hits(repo) == []


def test_real_ssn_in_reports_md_still_blocks(repo: Path) -> None:
    """Negative control: a real dashed SSN in reports/x.md still blocks."""
    (repo / "reports").mkdir()
    _stage(repo, "reports/x.md", "SSN: 123-45-6789\n")
    assert len(_ssn_hits(repo)) == 1


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
