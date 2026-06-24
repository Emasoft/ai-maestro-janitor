"""Tests for the OAuth REAUTH helper scripts ported into the plugin (TRDD-3T4DZWXA).

The `/refresh-claude-logins` wrapper + its `open-login.sh` / `check-login.sh` /
`lifetime-status.sh` helpers were standalone USER-SCOPE artifacts that escaped the
2026-05-31 rotator fold (TRDD-f892e109, which migrated only the engine). They are now
shipped BY the plugin (the `janitor-refresh-claude-logins` command + the 3 helpers beside
`rotator.py`). These tests pin the port's invariants: the scripts exist, parse, resolve
the IN-PLUGIN sibling `rotator.py` (never the cache glob the pre-fold form used), and the
command is present and drives the helpers.
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


def test_lifetime_status_points_at_janitor_skill() -> None:
    """lifetime-status.sh's action prompt points at the renamed /janitor-refresh-claude-logins
    (the old un-prefixed name is gone — note /janitor-... does not contain the '/refresh-' stem)."""
    text = (OAUTH_DIR / "lifetime-status.sh").read_text()
    assert "/janitor-refresh-claude-logins" in text
    assert "/refresh-claude-logins" not in text


def test_refresh_logins_command_shipped() -> None:
    """The janitor-refresh-claude-logins COMMAND exists and drives the IN-PLUGIN helpers. It is a
    command (not a skill) because CPV's skill-name reserved-word check forbids 'claude'; commands
    carry no such rule, so this keeps the user's exact requested name (TRDD-3T4DZWXA)."""
    cmd = REPO / "commands" / "janitor-refresh-claude-logins.md"
    assert cmd.is_file(), "janitor-refresh-claude-logins command was not created"
    body = cmd.read_text()
    assert body.startswith("---") and "description:" in body[:500], "command needs frontmatter with a description"
    assert "$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator" in body, "command must drive the in-plugin helpers"
