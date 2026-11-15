"""One name test for "this variable holds a secret", shared by the Bash guard, the live-value matcher
and the environment helper (janitor issue #354).

SECRET_NAME, NOT_SECRET_NAME and STRONG_NAME are copies of the three expressions of the same names in
hooks/secret-shield/patterns.ts. tests/test_secret_names.py compares their source text with that file, so
the two cannot drift apart without a red test. ENV_EXTRA_NAME is the one addition: the shield's list has no
`pat`, `cookie`, `oauth`, `bearer` or bare `key`, and an environment holds names such as GH_PAT,
SESSION_COOKIE and CLAUDE_CODE_OAUTH_TOKEN. Moving those words into patterns.ts is a follow-up that belongs to
the card that owns that file (TRDD-Q6LPJTPO); until then this module is the only place that has the gap.
"""
from __future__ import annotations

import re

SECRET_NAME = re.compile(
    r"(^|[_.-])(secrets?|token|password|passwd|passphrase|pwd|pass|api_?key|apikey|private_?key|access_?key"
    r"|access_?token|auth_?key|auth_?token|client_?secret|secret_?key|credentials?|signing_?key|encryption_?key"
    r"|session_?key|master_?key)([_.-]|$)"
)
NOT_SECRET_NAME = re.compile(
    r"[_.-](url|uri|endpoint|path|file|dir|name|type|expiry|expires|expires_at|ttl|length|header|id|count|limit"
    r"|size|prefix|env|var|mode|enabled|required|policy|hint|prompt|label|placeholder|field|format)$"
)
STRONG_NAME = re.compile(r"(^|_)(storage|account)_?key(_|$)")
ENV_EXTRA_NAME = re.compile(r"(^|[_.-])(pat|cookies?|oauth|bearer|key)([_.-]|$)")


def snake_name(name: str) -> str:
    """The form a name is matched on: `apiKey`, `api-key` and `API_KEY` all read `api_key` (as in the shield)."""
    return re.sub(r"[-.]", "_", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower())


def is_secret_env_name(name: str) -> bool:
    """True when the NAME of an environment variable says its value is a secret."""
    if name == "PWD":  # the working directory; the copied shield expression reads `pwd` as a password abbreviation, so `printenv PWD` was denied
        return False
    snake = snake_name(name)
    named = SECRET_NAME.search(snake) or STRONG_NAME.search(snake) or ENV_EXTRA_NAME.search(snake)
    return bool(named) and not NOT_SECRET_NAME.search(snake)
