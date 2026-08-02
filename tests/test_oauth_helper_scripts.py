"""Tests for the OAuth REAUTH helper scripts ported into the plugin (TRDD-3T4DZWXA).

The `/refresh-claude-logins` wrapper + its `open-login.sh` / `check-login.sh` /
`lifetime-status.sh` helpers were standalone USER-SCOPE artifacts that escaped the
2026-05-31 rotator fold (TRDD-f892e109, which migrated only the engine). They are now
shipped BY the plugin (the `janitor-refresh-cc-logins` skill + the 3 helpers beside
`rotator.py`). These tests pin the port's invariants: the scripts exist, parse, resolve
the IN-PLUGIN sibling `rotator.py` (never the cache glob the pre-fold form used), and the
skill is present and drives the helpers.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OAUTH_DIR = REPO / "scripts" / "oauth_rotator"
HELPERS = ["open-login.sh", "check-login.sh", "lifetime-status.sh"]

# The exact cache-glob the pre-fold (user-scope) scripts used to resolve the engine.
# A ported helper that still contains this is resolving the NEWEST cached version
# instead of its own sibling — the bug this port removes.
CACHE_GLOB = "plugins/cache/ai-maestro-plugins/ai-maestro-janitor/*/scripts"


@pytest.mark.parametrize("name", HELPERS)
def test_helper_exists_and_executable(name: str) -> None:
    """Each ported helper is present in scripts/oauth_rotator/ and executable."""
    p = OAUTH_DIR / name
    assert p.is_file(), f"{name} was not ported into the plugin"
    assert p.stat().st_mode & 0o111, f"{name} is not executable"


@pytest.mark.parametrize("name", HELPERS)
def test_helper_parses(name: str) -> None:
    """Each helper passes `bash -n` (no syntax error)."""
    bash = shutil.which("bash")
    assert bash, "bash not found on PATH"
    r = subprocess.run([bash, "-n", str(OAUTH_DIR / name)], capture_output=True, text=True)
    assert r.returncode == 0, f"{name} bash -n failed: {r.stderr}"


@pytest.mark.parametrize("name", HELPERS)
def test_helper_resolves_sibling_not_cache_glob(name: str) -> None:
    """The ported helper resolves rotator.py as its IN-PLUGIN SIBLING, never by globbing
    the plugin cache — so the helper and the engine are always the same version
    (TRDD-3T4DZWXA). This is the load-bearing invariant of the fold-completion."""
    text = (OAUTH_DIR / name).read_text()
    assert 'dirname "$0"' in text, f"{name} must resolve rotator.py via its own dir (sibling)"
    assert CACHE_GLOB not in text, f"{name} still globs the plugin cache — must use the sibling rotator.py"


@pytest.mark.parametrize("name", HELPERS)
def test_helper_no_legacy_home_default(name: str) -> None:
    """No ported helper defaults to the legacy user-scope home `~/.claude/account-rotator/...`;
    fallbacks resolve via the engine (print-profiles-root) or the canonical DATA dir."""
    text = (OAUTH_DIR / name).read_text()
    assert ".claude/account-rotator" not in text, (
        f"{name} still falls back to the legacy user-scope home — must use the canonical DATA dir"
    )


def test_lifetime_status_points_at_janitor_command() -> None:
    """lifetime-status.sh's action prompt points at /janitor-refresh-cc-logins — the current
    skill name. Neither the old un-prefixed /refresh-claude-logins nor the pre-rename
    /janitor-refresh-claude-logins may remain (the name may not contain the reserved 'claude')."""
    text = (OAUTH_DIR / "lifetime-status.sh").read_text()
    assert "/janitor-refresh-cc-logins" in text
    assert "/refresh-claude-logins" not in text
    assert "/janitor-refresh-claude-logins" not in text


def test_refresh_logins_skill_shipped() -> None:
    """The janitor-refresh-cc-logins SKILL exists and drives the IN-PLUGIN helpers. It is a SKILL
    (agent descriptions are surfaced to context; commands are not), and it is named `cc`-logins
    NOT `claude`-logins because a skill name may not contain the reserved word 'claude' (CPV RC-59
    / Claude Code) — the user-chosen rename that lets it ship as a discoverable skill (TRDD-EBVZJ6GU,
    superseding the command-form of TRDD-3T4DZWXA)."""
    skill = REPO / "skills" / "janitor-refresh-cc-logins" / "SKILL.md"
    assert skill.is_file(), "janitor-refresh-cc-logins skill was not created"
    body = skill.read_text()
    assert body.startswith("---") and "description:" in body[:600], "skill needs frontmatter with a description"
    assert "name: janitor-refresh-cc-logins" in body[:600], "skill name field must be janitor-refresh-cc-logins"
    assert "claude" not in _skill_name_field(body), "skill NAME must not contain the reserved word 'claude'"
    assert "$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator" in body, "skill must drive the in-plugin helpers"
    # The pre-rename command form must be gone (one source of truth).
    assert not (REPO / "commands" / "janitor-refresh-claude-logins.md").is_file(), (
        "the pre-rename command must not coexist with the skill"
    )


def _skill_name_field(body: str) -> str:
    """The value of the frontmatter `name:` line (lowercased), for the reserved-word assertion."""
    for line in body.splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().lower()
    return ""


def test_check_login_never_asserts_identity() -> None:
    """janitor#179: check-login.sh proves a session is SAVED in the profile filed under
    <email>, never WHOSE it is (cookie values are encrypted; only the capture's /roles
    probe resolves the owner). The confident '<email>: logged in' ✓ line over a profile
    signed into another account inverted the operator's advice exactly when a re-login
    was needed — so that phrasing must never return."""
    text = (OAUTH_DIR / "check-login.sh").read_text()
    # The exact f-string shape of the old confident claim (the guard comment in the
    # script spells it "<email>" precisely so it does not collide with this assertion).
    assert "✓ {email}: logged in" not in text, (
        "check-login.sh must not claim '<email>: logged in' — identity is unverifiable offline"
    )
    assert "janitor#179" in text, "the ✓ lines must carry the owner-unverified caveat"


def test_lifetime_status_clean_exit_carries_identity_caveat() -> None:
    """janitor#179: lifetime-status.sh's clean exits must not read as a verified-identity
    all-clear — 'nothing to do' over a wrong-account profile hid a dead slot behind
    another account's cookies. Every healthy verdict/banner carries the caveat."""
    text = (OAUTH_DIR / "lifetime-status.sh").read_text()
    assert "nothing to do" not in text, (
        "the bare 'nothing to do' all-clear must not survive — it asserted identity it never checked"
    )
    assert "janitor#179" in text, "clean exits must carry the owner-unverified caveat"
    assert "IDENTITY_CAVEAT" in text, "both clean-exit paths must print the shared caveat"
