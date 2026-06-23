"""Tests for scripts/lib/private_path_patterns.py.

The private-path pattern library is the LOCAL-only material detector used by
the `memory-scope-leak` detector: it flags machine/user-private tokens —
absolute home paths with a username, Windows user paths, ssh `user@host`
forms, hostname-looking tokens (`box.local`, `box.lan`), and `$HOME` /
`%USERPROFILE%` leaks that carry a username — so such material is caught
before a PROJECT-scope (git-pushed) memory page can carry it.

Every rule gets at least one positive test AND a no-false-positive test:
generic/shared paths (`/Users/Shared/`, `/home/runner/` on CI), example
hostnames (`example.com`, `localhost`), and ordinary prose must NOT fire.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import private_path_patterns as ppp  # type: ignore[import-not-found]  # noqa: E402


def _ids(findings) -> set[str]:
    return {f.rule_id for f in findings}


# ---------- Data-model sanity --------------------------------------------


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors privacy_patterns.Finding (line/column/matched_text/...)."""
    f = ppp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", kind="local-path",
    )
    assert (f.rule_id, f.line, f.column, f.matched_text) == ("r", 1, 2, "m")
    assert f.severity == "HIGH"
    assert f.kind == "local-path"


def test_rules_tuple_is_frozen_and_ids_unique() -> None:
    """RULES is an immutable tuple with unique rule ids and valid severities."""
    assert isinstance(ppp.RULES, tuple)
    ids = [r.id for r in ppp.RULES]
    assert len(ids) == len(set(ids)), "duplicate rule ids"
    valid = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW"}
    for r in ppp.RULES:
        assert r.severity in valid, (r.id, r.severity)
        assert r.kind, r.id


def test_empty_text_is_no_findings() -> None:
    """scan_text('') returns an empty list (defensive)."""
    assert ppp.scan_text("") == []


# ---------- macOS /Users/<name>/ -----------------------------------------


def test_macos_user_home_path_flagged() -> None:
    """A concrete macOS home path with a username is flagged as a local path."""
    findings = ppp.scan_text("the rotator lives at /Users/emanuele/Code/secret/run.sh")
    assert "private-path.macos-user-home" in _ids(findings)


def test_macos_users_shared_not_flagged() -> None:
    """/Users/Shared/ is a generic multi-user location — must NOT fire."""
    findings = ppp.scan_text("put the cache under /Users/Shared/cache for everyone")
    assert "private-path.macos-user-home" not in _ids(findings)


# ---------- Linux /home/<name>/ ------------------------------------------


def test_linux_user_home_path_flagged() -> None:
    """A concrete Linux home path with a username is flagged."""
    findings = ppp.scan_text("config at /home/alice/.config/app/settings.toml")
    assert "private-path.linux-user-home" in _ids(findings)


def test_linux_ci_runner_home_not_flagged() -> None:
    """/home/runner/ (GitHub Actions) and other generic CI homes must NOT fire."""
    for ci in ("/home/runner/work/repo", "/home/ubuntu/build", "/home/ec2-user/x"):
        findings = ppp.scan_text(f"CI builds in {ci} and that is fine")
        assert "private-path.linux-user-home" not in _ids(findings), ci


# ---------- Windows C:\Users\<name>\ -------------------------------------


def test_windows_user_home_path_flagged() -> None:
    r"""A Windows C:\Users\<name>\ path is flagged."""
    findings = ppp.scan_text(r"the file is C:\Users\Emanuele\Documents\creds.txt today")
    assert "private-path.windows-user-home" in _ids(findings)


def test_windows_public_not_flagged() -> None:
    r"""C:\Users\Public\ is the shared Windows location — must NOT fire."""
    findings = ppp.scan_text(r"shared assets in C:\Users\Public\Downloads here")
    assert "private-path.windows-user-home" not in _ids(findings)


# ---------- ~-expanded home with a username ------------------------------


def test_tilde_user_home_flagged() -> None:
    """A ~username/ form (another user's home) is flagged."""
    findings = ppp.scan_text("see ~emanuele/.ssh/id_rsa for the key")
    assert "private-path.tilde-user-home" in _ids(findings)


def test_plain_tilde_not_flagged() -> None:
    """A bare ~/ (the running user's own home, no username) must NOT fire —
    it is portable and carries no identity."""
    findings = ppp.scan_text("install into ~/bin and add ~/.config too")
    assert "private-path.tilde-user-home" not in _ids(findings)


# ---------- $HOME / %USERPROFILE% leaks with a username ------------------


def test_env_home_with_username_flagged() -> None:
    """A $HOME-expanded string that still embeds /Users/<name> is flagged
    (the macOS rule catches it — the expansion leaked the identity)."""
    findings = ppp.scan_text("export DATA=/Users/bob/data  # was $HOME/data")
    assert "private-path.macos-user-home" in _ids(findings)


def test_bare_env_var_reference_not_flagged() -> None:
    """A symbolic $HOME / %USERPROFILE% reference (NOT expanded) is portable —
    it carries no username and must NOT fire."""
    findings = ppp.scan_text("write to $HOME/.cache and %USERPROFILE%\\AppData")
    assert _ids(findings) == set()


# ---------- ssh user@host ------------------------------------------------


def test_ssh_user_at_host_flagged() -> None:
    """An ssh `user@host` form (real host, not an email) is flagged."""
    findings = ppp.scan_text("ssh into emanuele@macbook.local to restart it")
    assert "private-path.ssh-user-host" in _ids(findings)


def test_email_not_flagged_as_ssh() -> None:
    """An email address must NOT be misread as ssh user@host (email is PII,
    handled by privacy_patterns; this lib must not double-fire on it)."""
    findings = ppp.scan_text("contact me at someone@example.com for access")
    assert "private-path.ssh-user-host" not in _ids(findings)


def test_github_action_sha_pin_not_flagged_as_ssh() -> None:
    """Issue #53: a GitHub Action SHA-pin (`owner/action@<40-hex>`) is a public
    action reference, NOT a machine host — documenting it in a shareable note
    must not trip the machine-host classifier."""
    findings = ppp.scan_text(
        "pin it: astral-sh/setup-uv@abcdef0123456789abcdef0123456789abcdef01  # v3.1.0"
    )
    assert "private-path.ssh-user-host" not in _ids(findings)


def test_real_ssh_host_still_flagged_after_sha_exclusion() -> None:
    """Regression for #53: excluding hex SHA-pins must NOT weaken detection of a
    genuine ssh `user@host` (a real LAN host still fires)."""
    findings = ppp.scan_text("ssh into emanuele@macbook.local to restart it")
    assert "private-path.ssh-user-host" in _ids(findings)


def test_github_action_sha_pin_short_and_comment_variants_not_flagged() -> None:
    """Issue #53 (variants): a SHA-pin abbreviated to a short (7-39 hex) commit
    AND the standard `# vX.Y.Z` trailing-comment form are still public action
    refs, not machine hosts — every common pin spelling must stay portable so
    documenting a pin decision in a PROJECT page never reads as machine-private."""
    for note in (
        "peter-evans/repository-dispatch@28959ce8",  # abbreviated 8-hex pin
        "actions/checkout@8ade135",  # abbreviated 7-hex pin (git default width)
        "shivammathur/setup-php@fcafdd6392932010c2bd5094439b8e33be2a8a09 # v2.37.0",
    ):
        assert "private-path.ssh-user-host" not in _ids(ppp.scan_text(note)), note


def test_genuine_machine_host_still_classified_after_sha_exclusion() -> None:
    """Regression guard for #53: the SHA-pin exclusion must not over-broaden —
    genuine `user@<bare-host>` ssh targets and `<host>.local` LAN names must
    still surface as the `machine-host` leak class (the kind the PROJECT scope
    forbids), proving the fix narrowed only the action-pin shape."""
    for note in ("run ssh deploy@buildbox to kick the job", "alice@macbook.local"):
        kinds = {f.kind for f in ppp.scan_text(note)}
        assert "machine-host" in kinds, note


# ---------- hostnames (.local / .lan) ------------------------------------


def test_local_hostname_flagged() -> None:
    """A `<host>.local` mDNS hostname is flagged as a machine identifier."""
    findings = ppp.scan_text("the box is reachable at emanueles-mbp.local on the lan")
    assert "private-path.local-hostname" in _ids(findings)


def test_lan_hostname_flagged() -> None:
    """A `<host>.lan` hostname is flagged."""
    findings = ppp.scan_text("nas.lan exports the share")
    assert "private-path.local-hostname" in _ids(findings)


def test_generic_hostnames_not_flagged() -> None:
    """Well-known generic hostnames (localhost, example.com, *.test) must NOT
    fire — they are documentation/loopback names, not a real machine."""
    text = "use localhost or example.com or foo.example or my.test for docs"
    findings = ppp.scan_text(text)
    assert "private-path.local-hostname" not in _ids(findings)
    assert "private-path.ssh-user-host" not in _ids(findings)


def test_localhost_local_not_flagged() -> None:
    """`localhost.local` / `localhost` style loopback names must NOT fire."""
    findings = ppp.scan_text("bind to localhost.localdomain for the test")
    assert "private-path.local-hostname" not in _ids(findings)


# ---------- composition / ordering ---------------------------------------


def test_findings_sorted_by_position() -> None:
    """Findings come back sorted by (line, column) for stable rendering."""
    text = (
        "line one /home/alice/x\n"
        "line two /Users/bob/y\n"
    )
    findings = ppp.scan_text(text)
    positions = [(f.line, f.column) for f in findings]
    assert positions == sorted(positions)


def test_clean_prose_yields_nothing() -> None:
    """Ordinary memory-note prose with no private tokens yields no findings."""
    text = (
        "The widget retries 3 times then fails. Tune via the max_retries key. "
        "See the docs at https://example.com/widget for the full table."
    )
    assert ppp.scan_text(text) == []


# ---------- extended coverage (built on the leftover contract) -----------


def test_finding_kind_labels_are_classed() -> None:
    """Every finding carries a `kind` of either local-path or machine-host."""
    text = "/Users/alice/x and box.local and ~bob/c and dave@nas.lan"
    kinds = {f.kind for f in ppp.scan_text(text)}
    assert kinds, "expected findings"
    assert kinds <= {"local-path", "machine-host"}, kinds


def test_system_account_homes_not_flagged() -> None:
    """Home paths owned by system/CI service accounts (root, www-data, jenkins)
    name no person and are portable — must NOT fire."""
    for seg in ("root", "www-data", "jenkins", "vagrant", "docker"):
        findings = ppp.scan_text(f"the service writes to /home/{seg}/data here")
        assert "private-path.linux-user-home" not in _ids(findings), seg


def test_windows_all_users_not_flagged() -> None:
    r"""`C:\Users\Default\` (the template profile) is a system location — no fire."""
    findings = ppp.scan_text(r"profile template at C:\Users\Default\NTUSER.DAT here")
    assert "private-path.windows-user-home" not in _ids(findings)


def test_macos_and_linux_homes_both_fire_on_one_line() -> None:
    """Two distinct private paths on the same line yield two findings (one per
    rule), both with the username-bearing class flagged."""
    findings = ppp.scan_text("synced /Users/alice/a to /home/bob/b just now")
    ids = _ids(findings)
    assert "private-path.macos-user-home" in ids
    assert "private-path.linux-user-home" in ids


def test_documentation_host_suffixes_not_flagged() -> None:
    """RFC-2606/6761 reserved suffixes (.test, .invalid, foo.example) are docs,
    not a real machine — neither the hostname nor ssh rule fires."""
    text = "ssh user@build.test and ping api.invalid and see db.example for docs"
    ids = _ids(ppp.scan_text(text))
    assert "private-path.local-hostname" not in ids
    assert "private-path.ssh-user-host" not in ids


def test_bare_ssh_host_without_dot_flagged() -> None:
    """An ssh `user@host` to a bare (dot-less) machine name is a real target —
    it is NOT an email (no domain) and must fire."""
    findings = ppp.scan_text("run ssh deploy@buildbox to kick the job")
    assert "private-path.ssh-user-host" in _ids(findings)


def test_severities_match_class() -> None:
    """Absolute home paths are HIGH (most identifying); hostnames/ssh/tilde are
    MEDIUM — sanity-check the rule catalogue's risk ranking."""
    by_id = {r.id: r for r in ppp.RULES}
    assert by_id["private-path.macos-user-home"].severity == "HIGH"
    assert by_id["private-path.linux-user-home"].severity == "HIGH"
    assert by_id["private-path.windows-user-home"].severity == "HIGH"
    assert by_id["private-path.local-hostname"].severity == "MEDIUM"
    assert by_id["private-path.ssh-user-host"].severity == "MEDIUM"
