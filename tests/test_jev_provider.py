"""Tests for scripts/lib/jevctx/provider.py::make_client (TRDD-541CBN36 card 2).

Provider selection must be driven by ONE env var, never inferred from which keys happen
to exist — these tests pin exactly that: default is openrouter, an explicit override
wins, an unknown value is an error, and a missing key for the SELECTED provider errors
even when the other provider's key is present (proving there is no silent fallback).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pytest  # noqa: E402
from jevctx.jev import HttpJevClient  # noqa: E402
from jevctx.openrouter import OpenRouterJevClient  # noqa: E402
from jevctx.provider import PROVIDER_ENV, make_client  # noqa: E402
from jevctx.types import JevAuthError  # noqa: E402


def test_default_provider_is_openrouter() -> None:
    client = make_client(env={"OPENROUTER_API_KEY": "or-key"})
    assert isinstance(client, OpenRouterJevClient)
    client.close()


def test_explicit_openrouter_override() -> None:
    client = make_client(env={PROVIDER_ENV: "openrouter", "OPENROUTER_API_KEY": "or-key"})
    assert isinstance(client, OpenRouterJevClient)
    client.close()


def test_explicit_typesafe_override() -> None:
    client = make_client(env={PROVIDER_ENV: "typesafe", "TYPESAFE_API_KEY": "ts-key"})
    assert isinstance(client, HttpJevClient)
    client.close()


def test_unknown_provider_is_an_error() -> None:
    with pytest.raises(JevAuthError, match=PROVIDER_ENV):
        make_client(env={PROVIDER_ENV: "made-up", "OPENROUTER_API_KEY": "or-key"})


def test_missing_key_for_default_provider_names_the_env_var() -> None:
    # No OPENROUTER_API_KEY at all — and a TYPESAFE_API_KEY present must NOT be used as a
    # fallback, since inference from "which key exists" is explicitly forbidden.
    with pytest.raises(JevAuthError, match="OPENROUTER_API_KEY"):
        make_client(env={"TYPESAFE_API_KEY": "ts-key"})


def test_missing_key_for_explicit_typesafe_names_the_env_var() -> None:
    with pytest.raises(JevAuthError, match="TYPESAFE_API_KEY"):
        make_client(env={PROVIDER_ENV: "typesafe", "OPENROUTER_API_KEY": "or-key"})


def test_built_client_uses_the_passed_env_key_not_the_real_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A white-box check that the key `make_client` threads through actually reaches the
    HTTP client's Authorization header — not `os.environ`. This matters because
    `OpenRouterJevClient.__init__` itself has an `os.environ.get(API_KEY_ENV)` fallback (for
    callers that build it directly, not through `make_client`); if `make_client` ever
    accidentally passed `api_key=None` instead of the resolved key, this fallback would
    silently paper over the bug by reading the REAL host's exported OPENROUTER_API_KEY (the
    study's own facts note this host has one exported) — a test that only checks
    `isinstance(...)` would still pass while `make_client`'s "use exactly the env dict I was
    given" contract quietly broke.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "real-process-env-key-must-not-be-used")
    client = make_client(env={"OPENROUTER_API_KEY": "explicit-test-key"})
    assert isinstance(client, OpenRouterJevClient)
    try:
        assert client._client.headers["authorization"] == "Bearer explicit-test-key"
    finally:
        client.close()
