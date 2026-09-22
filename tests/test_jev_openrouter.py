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
from jevctx.types import JevAuthError, Noul  # noqa: E402

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
    captured: dict = {}
    client = OpenRouterJevClient(api_key="or-key", transport=_fixed_response_transport(captured))
    try:
        answers = client.ask(STATE, QUESTIONS)
    finally:
        pass
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
