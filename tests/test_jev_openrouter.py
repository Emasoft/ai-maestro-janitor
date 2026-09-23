"""Tests for scripts/lib/jevctx/openrouter.py::OpenRouterJevClient (TRDD-541CBN36 card 2).

The response fixture below is the EXACT body captured by the live probe recorded in
reports/compaction-replacement/20260922_210008+0200-jev-proposal-measurements.md §M1
(POST https://openrouter.ai/api/alpha/decisions, HTTP 200, ~0.41s) — used here as a
static `httpx.MockTransport` fixture rather than a live network call, per the card's own
test policy ("no mocks of the network unless nothing else is possible... a static
fixture" is the sanctioned exception, spec card 2 test bullet).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from jevctx.openrouter import API_KEY_ENV, DEFAULT_MODEL, OpenRouterJevClient  # noqa: E402
from jevctx.types import JevAuthError, JevUnavailableError, Noul  # noqa: E402

# Byte-identical to the §M1 live-probe response.
M1_RESPONSE_BODY = {
    "model": "typesafe/jev-1.13-20260917",
    "answers": {"a": {"type": "noul", "noul": 0.19}},
    "usage": {"input_tokens": 373, "output_tokens": 20, "cost": 0.000015666},
    "id": "gen-dec-1790103521-I7rlaGC821WphRWOJkrF",
    "provider": "TypeSafe",
}

STATE = {"task": "probe", "items": [{"ref": "a", "text": "npm http fetch GET 200 https://registry.npmjs.org/x 12ms"}]}
QUESTIONS = {
    "a": Noul(
        instructions="Considering item a only: will this item still be needed later in the task?",
        true="needed later",
        false="progress noise",
    )
}


def _fixed_response_transport(captured: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=M1_RESPONSE_BODY)

    return httpx.MockTransport(handler)


def test_request_body_shape_matches_the_openrouter_contract() -> None:
    captured: dict = {}
    client = OpenRouterJevClient(api_key="or-key", transport=_fixed_response_transport(captured))
    try:
        client.ask(STATE, QUESTIONS)
    finally:
        client.close()

    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["auth"] == "Bearer or-key"
    body = captured["body"]
    assert body["model"] == DEFAULT_MODEL == "~typesafe/jev-latest"
    assert "state" in body and body["state"] == STATE
    assert "questions" in body and set(body["questions"]) == {"a"}
    assert body["questions"]["a"] == {
        "type": "noul",
        "instructions": QUESTIONS["a"].instructions,
        "criteria": {"true": "needed later", "false": "progress noise"},
    }


def test_response_with_cost_and_extra_fields_parses() -> None:
    from jevctx.types import NoulAnswer

    captured: dict = {}
    client = OpenRouterJevClient(api_key="or-key", transport=_fixed_response_transport(captured))
    try:
        answers = client.ask(STATE, QUESTIONS)
    finally:
        pass
    assert isinstance(answers["a"], NoulAnswer)
    assert answers["a"].noul == pytest.approx(0.19)
    # `model`/`id`/`provider` (the extra fields §M1's live probe carries) are simply never
    # read — proving "tolerate the extra fields" needs no special-casing.
    assert client.usage.input_tokens == 373
    assert client.usage.output_tokens == 20
    assert client.usage.cost == pytest.approx(0.000015666)
    client.close()


def test_missing_key_raises_jev_auth_error_naming_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real dev host has OPENROUTER_API_KEY exported (per the study's facts) — delete it
    # for this one test, or the "missing key" path would never actually be exercised here.
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with pytest.raises(JevAuthError, match=API_KEY_ENV):
        OpenRouterJevClient(api_key=None, transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def test_retries_exhausted_on_5xx_carries_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429/5xx response IS a response -- `.status` must be the HTTP code, which
    `jev_compact.py::_stamp_kind_for_error` reads to classify the probe stamp
    `kind="unavailable"` (a real, machine-wide Jev outage -- see VENDORED.md's
    `JevUnavailableError` attribute note, commit 40cc06d1 follow-up)."""
    monkeypatch.setenv(API_KEY_ENV, "or-key")
    client = OpenRouterJevClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        max_retries=1,
        sleep=lambda s: None,
    )
    with pytest.raises(JevUnavailableError) as excinfo:
        client.ask(STATE, QUESTIONS)
    client.close()
    assert getattr(excinfo.value, "status") == 503
    assert "503" in getattr(excinfo.value, "cause")


def test_retries_exhausted_on_429_carries_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 with a `Retry-After` header must surface that value on the exception's
    `.retry_after` -- `jev_compact.py::_retry_after_for_stamp` reads it to give the probe
    stamp's `kind="rate_limited"` decline gate a short, server-informed TTL (commit
    40cc06d1 follow-up)."""
    monkeypatch.setenv(API_KEY_ENV, "or-key")
    client = OpenRouterJevClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, headers={"retry-after": "9"})
        ),
        max_retries=1,
        sleep=lambda s: None,
    )
    with pytest.raises(JevUnavailableError) as excinfo:
        client.ask(STATE, QUESTIONS)
    client.close()
    assert getattr(excinfo.value, "status") == 429
    assert getattr(excinfo.value, "retry_after") == pytest.approx(9.0)


def test_retries_exhausted_on_transport_error_carries_no_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """No response ever came back -- `.status` must be `None` so `jev_compact.py`
    classifies this `kind="unreachable"` instead of `"unavailable"`: a transport error
    (connect/DNS/TLS/timeout) can be local to this one machine or lane (e.g. the
    daemon's Python missing a CA bundle, TRDD-X6I04SAO), not evidence Jev itself is
    down, so it must not black out every other shell's compaction."""
    monkeypatch.setenv(API_KEY_ENV, "or-key")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = OpenRouterJevClient(
        transport=httpx.MockTransport(handler), max_retries=1, sleep=lambda s: None
    )
    with pytest.raises(JevUnavailableError) as excinfo:
        client.ask(STATE, QUESTIONS)
    client.close()
    assert getattr(excinfo.value, "status") is None
    assert "ConnectError" in getattr(excinfo.value, "cause")
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)



@pytest.mark.parametrize("status_code", [402, 403])
def test_402_403_raise_jev_auth_error_not_validation_error(monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
    """402 (insufficient credits) / 403 (forbidden -- bad key permissions, a guardrail
    block, or a moderation flag) are non-retryable account/request states -- must raise
    JevAuthError (not the catch-all JevValidationError) with no retry, so jev_compact.py
    stamps kind="auth" instead of misreporting a Jev outage (TRDD-541CBN36)."""
    monkeypatch.setenv(API_KEY_ENV, "or-key")
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(status_code)

    client = OpenRouterJevClient(
        transport=httpx.MockTransport(handler), max_retries=1, sleep=lambda s: None
    )
    with pytest.raises(JevAuthError, match=str(status_code)):
        client.ask(STATE, QUESTIONS)
    client.close()
    assert call_count["n"] == 1
