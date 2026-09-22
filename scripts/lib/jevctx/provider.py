"""Which Jev backend to use (TRDD-541CBN36 card 2 — not upstream, added here).

One switch, one env var, no inference. The spec is explicit that provider choice must
NOT be guessed from which API keys happen to be set (a host with both
``OPENROUTER_API_KEY`` and ``TYPESAFE_API_KEY`` exported would make "infer from
presence" ambiguous, and a host with neither would make it silently do nothing instead
of erroring) — so the one env var is authoritative, and a missing key for whichever
provider it names is an error, not a fallback to the other one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from jevctx.jev import HttpJevClient
from jevctx.openrouter import API_KEY_ENV as OPENROUTER_API_KEY_ENV
from jevctx.openrouter import OpenRouterJevClient
from jevctx.types import JevAuthError, JevClient

__all__ = ["PROVIDER_ENV", "PROVIDERS", "make_client"]

PROVIDER_ENV = "CLAUDE_PLUGIN_OPTION_JEV_PROVIDER"
DEFAULT_PROVIDER = "openrouter"
PROVIDERS = ("openrouter", "typesafe")
TYPESAFE_API_KEY_ENV = "TYPESAFE_API_KEY"


def make_client(env: Mapping[str, str] | None = None) -> JevClient:
    """Build the configured ``JevClient``, or raise.

    ``env`` is injectable so a test can drive provider selection without mutating
    ``os.environ`` (the same seam ``HttpJevClient``/``OpenRouterJevClient`` already use
    for ``sleep=``/``rng=``/``transport=``).
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    provider = (environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        raise JevAuthError(f"unknown {PROVIDER_ENV}={provider!r}, must be one of {PROVIDERS}")

    if provider == "openrouter":
        key = environ.get(OPENROUTER_API_KEY_ENV)
        if not key:
            raise JevAuthError(f"{PROVIDER_ENV}=openrouter but {OPENROUTER_API_KEY_ENV} is not set")
        return OpenRouterJevClient(api_key=key)

    key = environ.get(TYPESAFE_API_KEY_ENV)
    if not key:
        raise JevAuthError(f"{PROVIDER_ENV}=typesafe but {TYPESAFE_API_KEY_ENV} is not set")
    return HttpJevClient(api_key=key)
