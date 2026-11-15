"""Tests for scripts/lib/secret_names.py (janitor issue #354): one name test shared by the Bash guard,
the live-value matcher and the environment helper, kept in step with the secret shield's own."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import secret_names  # noqa: E402

_PATTERNS_TS = _ROOT / "hooks" / "secret-shield" / "patterns.ts"


def _shield_source(constant: str) -> str:
    """The text between the slashes of `const <constant> = /.../` in the shield's patterns.ts."""
    match = re.search(rf"^const {constant} = /(.*)/$", _PATTERNS_TS.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None, f"{constant} not found in {_PATTERNS_TS}"
    return match.group(1)


@pytest.mark.parametrize("constant", ["SECRET_NAME", "NOT_SECRET_NAME", "STRONG_NAME"])
def test_the_three_expressions_are_the_shields_own(constant: str) -> None:
    """The Python copy and hooks/secret-shield/patterns.ts hold the same expression: they cannot drift apart."""
    assert getattr(secret_names, constant).pattern == _shield_source(constant)


def test_names_that_say_secret_are_secret() -> None:
    """The shield's words and the extension (pat, cookie, oauth, bearer, key) all mark a name as secret."""
    for name in ("GITHUB_TOKEN", "MY_API_KEY", "DB_PASSWORD", "AWS_SECRET_ACCESS_KEY", "GH_PAT", "SESSION_COOKIE",
                 "CLAUDE_CODE_OAUTH_TOKEN", "BEARER_VALUE", "STRIPE_KEY", "AZURE_STORAGE_KEY", "apiKey", "x-api-key"):
        assert secret_names.is_secret_env_name(name), name


def test_names_about_a_secret_or_unrelated_are_not_secret() -> None:
    """A variable that names a file, id, url or count of a secret, or has nothing to do with one, is not secret."""
    for name in ("PATH", "HOME", "SESSION_ID", "TOKEN_FILE", "API_KEY_PATH", "GH_PAT_FILE", "OAUTH_URL", "TOKENIZERS_PARALLELISM",
                 "MAX_TOKENS", "KEYBOARD_LAYOUT", "SHELL"):
        assert not secret_names.is_secret_env_name(name), name
