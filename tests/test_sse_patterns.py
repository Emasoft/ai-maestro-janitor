"""Tests for scripts/lib/sse_patterns.py.

Pattern-coverage tests for the Wave-28 distill-round-14 Server-Sent
Events (SSE) catalogue (6 anti-patterns). Each rule has at least two
tests: one positive (canary that must fire) and one negative (carve-out
or suppressor that must NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import sse_patterns as sp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(sp.RULES, tuple)
    rule_ids = {r.id for r in sp.RULES}
    expected = {
        "sse-eventsource-no-auth-header",
        "sse-wildcard-cors-eventsource-response",
        "sse-weak-stream-id-idor",
        "sse-missing-no-store-cache-control",
        "sse-middleware-only-auth-no-handler-check",
        "sse-no-heartbeat-zombie-connection",
    }
    assert expected == rule_ids
    assert len(sp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    for rule in sp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = sp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert sp.scan_text("") == []


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text always returns a list (never raises on valid input)."""
    result = sp.scan_text("no SSE code here")
    assert isinstance(result, list)


def _hits(rule_id: str, text: str) -> list[sp.Finding]:
    return [f for f in sp.scan_text(text) if f.rule_id == rule_id]


# ---------- S1 : sse-eventsource-no-auth-header --------------------------


def test_s1_bare_eventsource_construct_flags() -> None:
    """Bare new EventSource(url) without fetch-stream alternative → HIGH hit."""
    src = (
        "class ArmorClient {\n"
        "  constructor(options) {\n"
        "    this.headers = { Authorization: `Bearer ${options.apiKey}` };\n"
        "  }\n"
        "  eventStream() {\n"
        "    return new EventSource(this.buildUrl('/v1/events/stream'));\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("sse-eventsource-no-auth-header", src)
    assert hits, "Expected S1 hit for bare EventSource"
    assert hits[0].severity == "HIGH"


def test_s1_eventsource_with_fetch_nearby_suppressed() -> None:
    """EventSource followed within 20 lines by fetch streaming → no S1 hit."""
    src = (
        "// deprecated helper\n"
        "function legacyStream(url) {\n"
        "  return new EventSource(url);\n"
        "}\n"
        "// preferred approach\n"
        "async function fetchStream(url, headers) {\n"
        "  const resp = await fetch(url, { headers });\n"
        "  const reader = resp.body.getReader();\n"
        "  return reader;\n"
        "}\n"
    )
    hits = _hits("sse-eventsource-no-auth-header", src)
    assert not hits, "fetch nearby should suppress S1"


# ---------- S2 : sse-wildcard-cors-eventsource-response ------------------


def test_s2_wildcard_cors_with_sse_response_flags() -> None:
    """allow_origins=[\"*\"] + EventSourceResponse in same file → HIGH hit."""
    src = (
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "from sse_starlette.sse import EventSourceResponse\n"
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['*'],\n"
        "    allow_methods=['*'],\n"
        ")\n"
        "@app.get('/stream')\n"
        "async def stream() -> EventSourceResponse:\n"
        "    async def gen():\n"
        "        yield {'data': 'hello'}\n"
        "    return EventSourceResponse(gen())\n"
    )
    hits = _hits("sse-wildcard-cors-eventsource-response", src)
    assert hits, "Expected S2 hit for wildcard CORS + SSE"
    assert hits[0].severity == "HIGH"


def test_s2_wildcard_cors_without_sse_not_flagged() -> None:
    """allow_origins=[\"*\"] on a regular REST API (no SSE) → no S2 hit."""
    src = (
        "from fastapi.middleware.cors import CORSMiddleware\n"
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['*'],\n"
        ")\n"
        "@app.get('/hello')\n"
        "async def hello() -> dict:\n"
        "    return {'msg': 'world'}\n"
    )
    hits = _hits("sse-wildcard-cors-eventsource-response", src)
    assert not hits, "Wildcard CORS without SSE should not trigger S2"


# ---------- S3 : sse-weak-stream-id-idor ---------------------------------


def test_s3_short_uuid_hex_with_sse_no_auth_flags() -> None:
    """uuid.uuid4().hex[:8] as stream ID with SSE endpoint and no auth → HIGH hit."""
    src = (
        "import uuid\n"
        "from sse_starlette.sse import EventSourceResponse\n"
        "@app.post('/review')\n"
        "async def start_review():\n"
        "    review_id = uuid.uuid4().hex[:8]\n"
        "    reviews[review_id] = {'status': 'running'}\n"
        "    return {'review_id': review_id}\n"
        "@app.get('/review/{review_id}/stream')\n"
        "async def stream_review(review_id: str) -> EventSourceResponse:\n"
        "    async def gen():\n"
        "        yield {'data': 'event'}\n"
        "    return EventSourceResponse(gen())\n"
    )
    hits = _hits("sse-weak-stream-id-idor", src)
    assert hits, "Expected S3 hit for weak UUID + SSE + no auth"
    assert hits[0].severity == "HIGH"


def test_s3_weak_id_with_auth_guard_suppressed() -> None:
    """uuid.uuid4().hex[:8] but Depends(get_current_user) present → no S3 hit."""
    src = (
        "import uuid\n"
        "from sse_starlette.sse import EventSourceResponse\n"
        "@app.get('/review/{review_id}/stream')\n"
        "async def stream_review(\n"
        "    review_id: str,\n"
        "    current_user: User = Depends(get_current_user),\n"
        ") -> EventSourceResponse:\n"
        "    review_id = uuid.uuid4().hex[:8]\n"
        "    async def gen():\n"
        "        yield {'data': 'event'}\n"
        "    return EventSourceResponse(gen())\n"
    )
    hits = _hits("sse-weak-stream-id-idor", src)
    assert not hits, "Depends(get_current_user) should suppress S3"


# ---------- S4 : sse-missing-no-store-cache-control ----------------------


def test_s4_eventsource_response_no_headers_flags() -> None:
    """EventSourceResponse() with no headers kwarg → MEDIUM hit."""
    src = (
        "from sse_starlette.sse import EventSourceResponse\n"
        "@app.get('/stream')\n"
        "async def stream_review(review_id: str) -> EventSourceResponse:\n"
        "    async def gen():\n"
        "        yield {'data': 'sensitive'}\n"
        "    return EventSourceResponse(gen())\n"
    )
    hits = _hits("sse-missing-no-store-cache-control", src)
    assert hits, "Expected S4 hit for EventSourceResponse without no-store"
    assert hits[0].severity == "MEDIUM"


def test_s4_eventsource_response_with_no_store_suppressed() -> None:
    """EventSourceResponse with no-store in headers → no S4 hit."""
    src = (
        "from sse_starlette.sse import EventSourceResponse\n"
        "@app.get('/stream')\n"
        "async def stream() -> EventSourceResponse:\n"
        "    async def gen():\n"
        "        yield {'data': 'ok'}\n"
        "    return EventSourceResponse(\n"
        "        gen(),\n"
        "        headers={'Cache-Control': 'no-store, no-cache, private'},\n"
        "    )\n"
    )
    hits = _hits("sse-missing-no-store-cache-control", src)
    assert not hits, "no-store in headers should suppress S4"


# ---------- S5 : sse-middleware-only-auth-no-handler-check ---------------


def test_s5_express_stream_handler_no_auth_check_flags() -> None:
    """Express SSE stream route with no in-handler auth token check → HIGH hit."""
    src = (
        "const express = require('express');\n"
        "const router = express.Router();\n"
        "\n"
        "router.get('/stream/:incidentId', (req, res) => {\n"
        "  const { incidentId } = req.params;\n"
        "  res.set({\n"
        "    'Content-Type': 'text/event-stream',\n"
        "    'Cache-Control': 'no-cache',\n"
        "    'Connection': 'keep-alive',\n"
        "  });\n"
        "  reasoningEmitter.on(`incident:${incidentId}`, (step) => {\n"
        "    res.write(`data: ${JSON.stringify(step)}\\n\\n`);\n"
        "  });\n"
        "});\n"
    )
    hits = _hits("sse-middleware-only-auth-no-handler-check", src)
    assert hits, "Expected S5 hit for Express SSE handler with no in-handler auth"
    assert hits[0].severity == "HIGH"


def test_s5_express_stream_handler_with_jwt_verify_suppressed() -> None:
    """Express SSE handler that calls jwt.verify inside → no S5 hit."""
    src = (
        "router.get('/stream/:incidentId', async (req, res) => {\n"
        "  const authHeader = req.headers.authorization;\n"
        "  const token = authHeader?.split(' ')[1];\n"
        "  let userId;\n"
        "  try {\n"
        "    userId = jwt.verify(token, process.env.JWT_SECRET).sub;\n"
        "  } catch (err) {\n"
        "    return res.status(401).json({ error: 'Unauthorized' });\n"
        "  }\n"
        "  res.set({ 'Content-Type': 'text/event-stream' });\n"
        "  // stream incident data for userId\n"
        "});\n"
    )
    hits = _hits("sse-middleware-only-auth-no-handler-check", src)
    assert not hits, "jwt.verify inside handler should suppress S5"


# ---------- S6 : sse-no-heartbeat-zombie-connection ----------------------


def test_s6_eventsource_response_no_heartbeat_flags() -> None:
    """EventSourceResponse with no heartbeat anywhere in file → MEDIUM hit."""
    src = (
        "from sse_starlette.sse import EventSourceResponse\n"
        "@app.get('/review/{review_id}/stream')\n"
        "async def stream_review(review_id: str) -> EventSourceResponse:\n"
        "    async def event_generator():\n"
        "        sent = 0\n"
        "        while True:\n"
        "            review = reviews[review_id]\n"
        "            while sent < len(review['events']):\n"
        "                yield {'data': review['events'][sent]}\n"
        "                sent += 1\n"
        "            if review['status'] == 'complete':\n"
        "                return\n"
        "            await asyncio.sleep(0.4)\n"
        "    return EventSourceResponse(event_generator())\n"
    )
    hits = _hits("sse-no-heartbeat-zombie-connection", src)
    assert hits, "Expected S6 hit for SSE without heartbeat"
    assert hits[0].severity == "MEDIUM"


def test_s6_express_sse_with_keep_alive_interval_suppressed() -> None:
    """Express SSE with setInterval keep-alive heartbeat → no S6 hit."""
    src = (
        "router.get('/stream/:id', (req, res) => {\n"
        "  res.set({\n"
        "    'Content-Type': 'text/event-stream',\n"
        "    'Cache-Control': 'no-store, no-cache',\n"
        "    'Connection': 'keep-alive',\n"
        "  });\n"
        "  const keepAlive = setInterval(() => {\n"
        "    res.write(': keep-alive\\n\\n');\n"
        "  }, 30000);\n"
        "  req.on('close', () => {\n"
        "    clearInterval(keepAlive);\n"
        "    res.end();\n"
        "  });\n"
        "});\n"
    )
    hits = _hits("sse-no-heartbeat-zombie-connection", src)
    assert not hits, "setInterval keep-alive should suppress S6"
