"""GitLab credential coverage, and the dead path-branch it uncovered (CC 2.1.232).

CC 2.1.232 added redaction for the GitLab token families and gave the `glab` CLI config
store "the same sandbox and credential-path protection as `gh`". The janitor detected NONE
of the GitLab families and protected `~/.config/gh` but not `~/.config/glab` — a guard that
covers one of two interchangeable CLIs just tells an attacker which one to read.

Chasing that turned up a worse defect: the PATH branch of `exfil_verify._SECRET_REFERENCE`
had never matched anything. Its leading `\\b` could not hold, because every alternative
starts with a non-word char (`~`, `$`, `/`) and the preceding char is normally a space —
non-word to non-word is not a word boundary. It LOOKED alive only because the obvious probe,
`~/.config/gh/hosts.yml`, matched the separate `hosts.yml` alternative. That is why these
tests assert each path form on its own, with no filename that another branch could catch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import exfil_verify as ev  # noqa: E402
import secret_rotation_patterns as srp  # noqa: E402

# --- the dead branch ------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "cat ~/.aws/",
        "cat ~/.ssh/",
        "cat ~/.netrc",
        "cat $HOME/.aws/",
        "cat /Users/someone/.aws/",
        "cat /home/someone/.ssh/",
    ],
)
def test_credential_path_branch_actually_fires(path: str) -> None:
    """Each credential-path form is flagged as a secret reference.

    NONE of these carry a filename (`credentials`, `id_rsa`, `hosts.yml`) that a different
    alternative could match, so a pass here proves the PATH branch itself works — which it
    did not before 2026-08-14."""
    assert ev._SECRET_REFERENCE.search(path), f"path branch failed to match: {path}"


@pytest.mark.parametrize("path", ["cat ~/.config/gh/", "cat ~/.config/glab/"])
def test_both_forge_cli_config_stores_are_covered(path: str) -> None:
    """`gh` AND `glab` config stores are both sensitive sources. Covering only one is
    equivalent to covering neither, since either CLI can read the same repositories."""
    assert ev._SECRET_REFERENCE.search(path), f"forge CLI config store not covered: {path}"


@pytest.mark.parametrize(
    "benign",
    ["cat ~/notes.txt", "echo hello world", "read the ~/.config directory", "ls ~/Documents"],
)
def test_benign_paths_are_not_flagged(benign: str) -> None:
    """Reviving the branch must not flag ordinary paths — note `~/.config` alone stays
    clean, since it is only sensitive with a credential subdirectory."""
    assert not ev._SECRET_REFERENCE.search(benign), f"false positive: {benign}"


# --- the GitLab token families ---------------------------------------------------------

_GITLAB_PREFIXES = (
    "glpat-", "gldt-",  # routable — CC redacts these in full
    "glrt-", "gloas-", "glptt-", "glagent-", "glimt-", "glsoat-", "glcbt-", "glft-", "glffct-",
)


@pytest.mark.parametrize("prefix", _GITLAB_PREFIXES)
def test_gitlab_token_families_are_detected(prefix: str) -> None:
    """Every GitLab token family CC 2.1.232 redacts is detected as a literal PAT.

    They use a HYPHEN after the prefix where the GitHub families use an underscore, which
    is why an alternation whose trailing class was `[A-Za-z0-9_]` missed all of them even
    once the prefixes were listed."""
    token = f"{prefix}ABCdef1234567890abcdEFGH"
    assert srp._LITERAL_PAT_TOKEN.search(token), f"undetected GitLab token family: {prefix}"


@pytest.mark.parametrize("token", ["ghp_ABCdef1234567890abcdEF", "github_pat_ABCdef1234567890abcd"])
def test_github_families_still_detected(token: str) -> None:
    """The control: adding GitLab must not regress GitHub detection."""
    assert srp._LITERAL_PAT_TOKEN.search(token)


def test_ordinary_gl_prefixed_words_are_not_tokens() -> None:
    """`gl`-prefixed English must not read as a credential — the prefixes end in `-` and
    require a long alphanumeric tail, so prose stays clean."""
    assert not srp._LITERAL_PAT_TOKEN.search("glaciers are melting slowly in the north")
