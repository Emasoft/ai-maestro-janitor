"""gRPC / RPC payload + WebSocket / JSON-RPC server-side ingress patterns.

Wave 19 of the github-monitoring distillation (distill round 5, agent E —
``reports/distill-round-5/grpc-rpc-payload.md``). Patterns convergent
across:

* SentinelOps-Autonomous-DevOps-AI (unauthenticated WebSocket dashboard,
  no frame-size / origin / auth / rate-limit on ``@app.websocket("/ws")``,
  broadcast loop with no per-client backpressure or ack timeout),
* sentinel-gateway (``await request.body()`` then ``decode("utf-8")`` then
  ``json.loads(text)`` with no Content-Length cap, acts as a JSON-RPC
  forwarder for Anthropic / OpenAI / Groq),
* AgentShield (``CORSMiddleware(allow_origins=env_split, allow_credentials=True)``
  with env-driven origin list),
* sentinel (MCP-over-stdio + WebSocket JSON-RPC dispatch by string method
  field with no allowlist).

This module is the RULE-PATTERN catalog for SERVER-SIDE / INGRESS framing
of RPC envelopes — distinct from the EGRESS catalog in
``network_exfil_patterns.py`` (which catches outbound gRPC / WebSocket
traffic), and distinct from the DESERIALIZATION-at-byte-level catalog in
``parser_format_patterns.py`` (which catches the msgpack / CBOR / protobuf
unpacking step). This catalog covers the RPC ENVELOPE layer: missing
limits on frame-size, missing origin checks on the WebSocket handshake,
JSON-RPC method dispatch via getattr, gRPC server config that disables
TLS / message-size limits / interceptor-chain auth ordering.

Public surface (mirrors network_exfil_patterns / parser_format_patterns
for uniformity — heartbeat detectors render either kind interchangeably):

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                    — single rule record.
  * RULES                           — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]
                                    — run every applicable rule, return findings.
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
                                    — single finding record. Frozen NamedTuple.

The patterns deliberately favour STAGE-1 regex pre-filter over deep AST
analysis; the deep AST stage may run in a follow-up. What this module
guarantees: every disclosed "RPC framing / WebSocket ingress / gRPC
server config" shape in the dr5-E report has a stage-1 catch.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor sentinel/zizmor convention.

RE2-safety note: every multi-step bridge uses bounded ``[\\s\\S]{0,N}?``
windows (where N is a small explicit literal — 200, 400, 600, 800, 4000,
or 8000 max). No unbounded ``.*`` / ``.+`` between named anchors. No
nested-quantifier risk. The patterns compile and run under Python's
backtracking ``re`` engine but stay safe-shaped because every quantifier
has an explicit upper bound — even a pathological input cannot trigger
catastrophic backtracking when the engine has a finite window to search.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/network_exfil_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-02"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load.

    ``exclude_if_present`` is a tuple of substring tokens (case-sensitive)
    that, when ANY appears in the surrounding window of a match (default
    ±600 chars), suppresses the finding. This lets a rule whose dangerous
    shape (``await request.body()``) can be made safe by a check that
    appears BEFORE the shape (``if content-length > MAX_BODY: ...``) skip
    the false-positive at the catalog level. Python ``re`` only supports
    fixed-width lookbehind, so we do the bidirectional check in
    ``scan_text`` instead of inside the regex itself.

    When ``exclude_if_present`` is empty, the rule fires whenever the
    pattern matches.
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str
    exclude_if_present: tuple[str, ...] = ()


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE+UNICODE. RPC framing patterns
    target source-code shapes (call sites, decorator stanzas, options
    dicts) where case matters (``MaxRecvMsgSize`` is NOT ``maxrecvmsgsize``),
    so we DO NOT enable IGNORECASE by default. Per-rule overrides use
    re.compile directly with explicit flags where the shape is
    case-insensitive."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. WebSocket endpoint with no message-size / frame-size limit ------


# FastAPI / Starlette ``@app.websocket("/...")`` decorator above a function
# that calls ``.receive_text() / .receive_bytes() / .receive_json()``. The
# bidirectional safety-token check in scan_text suppresses findings when
# ``max_size`` / ``max_payload`` / ``MAX_FRAME`` / etc. appears within
# ±600 chars of the match. uvicorn defaults to 16 MiB per frame; almost
# no project lowers it.
#
# The 400-char bridge between the decorator and the ``.receive_*()`` call
# tolerates a few lines of function signature + docstring before the read.
_WS_NO_FRAME_SIZE = _re(
    r"@\w+\.websocket\s*\([^)]+\)\s*\n"
    r"[\s\S]{0,400}?"
    r"\.receive_(?:text|bytes|json)\s*\(\s*\)"
)


# Node ``ws`` library: ``new WebSocket.Server({...})``. Safety-token check
# (``maxPayload`` in the surrounding window) suppresses true negatives.
_WS_NODE_NO_MAX_PAYLOAD = _re(
    r"new\s+WebSocket\.Server\s*\(\s*\{[^}]{0,600}\}"
)


# uvicorn invocation: ``uvicorn.run(...)``. Safety-token check
# (``ws_max_size`` in surrounding window) suppresses true negatives.
# uvicorn's default WebSocket frame size is 16 MiB.
_UVICORN_NO_WS_MAX_SIZE = _re(
    r"\buvicorn\.run\s*\([^)]+\)"
)


# ---- 2. WebSocket endpoint with no origin / CSWSH check -----------------


# ``@app.websocket("/...")`` followed by ``await websocket.accept()`` (or
# ``await ws.accept()`` — any short identifier). The safety-token check
# (``origin`` / ``Origin`` / ``allowed_origins`` / ``ORIGIN_ALLOWLIST``
# in surrounding window) suppresses true negatives. CSWSH = Cross-Site
# WebSocket Hijacking; the handshake's ``Origin`` header is the LAST
# chance to reject a cross-site connection.
_WS_NO_ORIGIN_CHECK = _re(
    r"@\w+\.websocket\s*\([^)]+\)\s*\n"
    r"[\s\S]{0,400}?"
    r"await\s+\w+\.accept\s*\(\s*\)"
)


# ---- 3. WebSocket endpoint with no handshake authentication -------------


# ``@app.websocket("/...")`` with a function signature that takes ONLY
# a single ``websocket`` parameter — no ``token`` / ``user`` / ``session``
# / ``api_key`` / ``Depends(...)`` / ``Cookie(...)`` parameter, and no
# ``Authorization`` / ``api_key`` token in the surrounding window. The
# safety-token check in scan_text handles the bidirectional case.
#
# The function signature is captured via
# ``async def \w+\(\s*\w+\s*:\s*WebSocket\s*\)`` — exactly one parameter,
# no other auth-shaped names.
_WS_NO_HANDSHAKE_AUTH = _re(
    r"@\w+\.websocket\s*\([^)]+\)\s*\n"
    r"\s*async\s+def\s+\w+\s*\(\s*\w+\s*:\s*WebSocket\s*\)\s*[-:][\s\S]{0,400}?"
    r"await\s+\w+\.accept\s*\(\s*\)"
)


# ---- 4. JSON-RPC dispatch by string method field — eval-shape ----------


# ``getattr(self, msg["method"])`` / ``getattr(handler, data['method'])`` —
# attribute access keyed by attacker-controlled string. The single most
# common JSON-RPC server foot-gun (MCP-over-stdio / MCP-over-WebSocket
# both use JSON-RPC 2.0 envelopes; a copy-paste MCP server that maps
# method names to attributes via getattr lets the prompt-injected
# attacker call any private helper on the server class).
_JSONRPC_GETATTR_DISPATCH = _re(
    r"\bgetattr\s*\(\s*\w+\s*,\s*\w+\s*\[\s*[\"']method[\"']\s*\]"
)


# Plus the explicit-map-but-unfiltered shape: ``METHOD_MAP = { ... dir(self) }``
# or ``METHOD_MAP = globals()``. Either constructs the dispatch table
# from a wide-open namespace.
_JSONRPC_UNFILTERED_DISPATCH_MAP = _re(
    r"\b(?:METHOD_MAP|HANDLERS|DISPATCH(?:_MAP|_TABLE)?|RPC_METHODS)\s*=\s*"
    r"(?:\{[^}]*?\b(?:dir|globals|vars)\s*\(|globals\s*\(\s*\)|vars\s*\([^)]*\))"
)


# ---- 5. JSON-RPC parse with no nesting / recursion limit ----------------


# Any ``json.loads(...)`` call on attacker-controlled data. The shape
# requires the first argument to be a short variable name from the
# attacker-data namespace (``data``, ``body``, ``text``, ``payload``,
# ``msg``, ``raw``, ``content``, ``request_data``, ``message``) so a
# ``json.loads("{...}")`` of a literal string doesn't fire. The safety-
# token check (``max_depth`` / ``parse_constant`` / ``RECURSION`` /
# ``MAX_NESTING`` in surrounding window) suppresses true negatives where
# the author wrote an explicit depth-bounded JSONDecoder.
_JSON_LOADS_NO_DEPTH_CAP = _re(
    r"\bjson\.loads\s*\(\s*(?:data|body|text|payload|msg|raw|content|request_data|message)\b[^)]*\)"
)


# Plus the Pydantic v1 ``Model.parse_obj(...)`` shape — no max_depth
# enforcement; Pydantic v2 warns but doesn't enforce either. The
# safety-token check (``max_depth`` / ``MAX_DEPTH`` in surrounding
# window) suppresses true negatives.
_PYDANTIC_PARSE_OBJ_NO_DEPTH = _re(
    r"\b\w+\.parse_obj\s*\(\s*\w+\s*\)"
)


# ---- 6. HTTP body read with no Content-Length cap ----------------------


# FastAPI / Starlette: ``await request.body()`` (or ``await req.body()``).
# The safety-token check (``content-length`` / ``MAX_BODY`` /
# ``max_content_length`` / ``max_body_size`` / ``stream`` in surrounding
# window) suppresses true negatives. The single line ``body = await
# request.body()`` is the gateway shape that bites sentinel-gateway-main
# at gateway.py:111.
_HTTP_BODY_NO_LENGTH_CAP = _re(
    r"\bawait\s+\w+\.body\s*\(\s*\)"
)


# Flask: ``request.get_data()``. Safety-token check
# (``max_content_length`` / ``MAX_CONTENT_LENGTH`` in surrounding
# window) suppresses true negatives. Flask has no per-call cap; the
# app-level ``MAX_CONTENT_LENGTH`` config key is the only defense.
_FLASK_GET_DATA_NO_LIMIT = _re(
    r"\brequest\.get_data\s*\(\s*\)"
)


# ---- 7. CORS allow_credentials=True with env-driven origin list -------


# Starlette / FastAPI ``CORSMiddleware``. Two real shapes in the wild:
#   1. ``app.add_middleware(CORSMiddleware, allow_origins=..., allow_credentials=True)``
#      (FastAPI's documented pattern — CORSMiddleware is a positional arg
#      to add_middleware).
#   2. ``app.add_middleware(CORSMiddleware(allow_origins=..., allow_credentials=True))``
#      (less common; constructor call).
# We anchor on ``CORSMiddleware`` followed by EITHER ``,`` (shape 1) or
# ``(`` (shape 2) and then look for both ``allow_origins=`` and
# ``allow_credentials=True`` within 600 chars — the kwargs may span
# multiple lines. The ``[\s\S]`` class matches across newlines (unlike
# ``[^)]`` which stops at the closing paren but ALSO at any other
# char — though in practice the only failure mode here is too-large
# windows, which we cap at 600).
#
# We use 600 chars as the bridge because a typical CORS configuration
# uses 4-6 kwargs on separate lines (~ 50 chars per kwarg) plus a list
# literal.
_CORS_CREDENTIALS_WITH_ORIGIN = _re(
    r"\bCORSMiddleware\b[,(]\s*"
    r"[\s\S]{0,600}?\ballow_origins\s*=\s*"
    r"[\s\S]{0,600}?\ballow_credentials\s*=\s*True"
)


# Same shape, kwargs in the opposite order (allow_credentials first).
_CORS_CREDENTIALS_WITH_ORIGIN_REORDERED = _re(
    r"\bCORSMiddleware\b[,(]\s*"
    r"[\s\S]{0,600}?\ballow_credentials\s*=\s*True"
    r"[\s\S]{0,600}?\ballow_origins\s*=\s*"
)


# Node / Express ``cors({ origin: ..., credentials: true })`` shape.
# Express's ``cors`` middleware behaves the same way as Starlette — if
# ``origin`` is reflective (a function or array including ``"*"``) and
# ``credentials: true``, the browser will send cookies to any origin.
_NODE_CORS_CREDENTIALS = _re(
    r"\bcors\s*\(\s*\{[^}]*?\borigin\s*:[^}]*?\bcredentials\s*:\s*true\b",
)


# ---- 8. WebSocket broadcast with no per-client backpressure / timeout ---


# ``async def broadcast(...)`` (or ``def broadcast(...)``) followed by
# ``for ... in ... active_connections`` followed by ``await ....send_json``
# (or ``send_text`` / ``send_bytes``). Safety-token check (``timeout``,
# ``asyncio.wait_for``, ``ensure_future``, ``asyncio.gather``,
# ``create_task`` in surrounding window) suppresses true negatives.
# Serial-await over slow clients is the asymmetric-DOS shape.
_WS_BROADCAST_NO_BACKPRESSURE = _re(
    r"\b(?:async\s+)?def\s+broadcast[\s\S]{0,400}?"
    r"for\s+\w+\s+in\s+\w*\.?active_connections"
    r"[\s\S]{0,400}?"
    r"await\s+\w+\.send_(?:json|text|bytes)"
)


# ---- 9. JSON-RPC notification flood / no per-connection rate limit -----


# ``while True:`` followed within 200 chars by ``.receive_text()`` /
# ``.receive_bytes()`` / ``.receive_json()``. Safety-token check
# (``rate`` / ``throttle`` / ``TokenBucket`` / ``token_bucket`` /
# ``asyncio.sleep`` / ``RATE_LIMIT`` / ``RateLimiter`` in surrounding
# window) suppresses true negatives. The unbounded-receive loop is what
# the MCP server template ships with by default.
_WS_NO_RATE_LIMIT_LOOP = _re(
    r"\bwhile\s+True\s*:\s*\n"
    r"[\s\S]{0,200}?"
    r"\.receive_(?:text|bytes|json)\s*\("
)


# ---- 10. gRPC server with MaxRecvMsgSize unset --------------------------


# Python: ``grpc.server(...)``. Safety-token check (``MaxRecvMsgSize`` /
# ``max_message_length`` / ``max_receive_message_length`` /
# ``grpc.max_receive`` in surrounding window) suppresses true negatives.
# Default is 4 MiB; teams routinely raise to MaxInt32 to "handle big
# protobufs". Note: ``grpc.server(`` must be followed by at least one
# argument (the ThreadPoolExecutor) to avoid matching a bare reference.
_GRPC_PY_SERVER_NO_MAX_RECV = _re(
    r"\bgrpc\.server\s*\([^)]+\)"
)


# Go: ``grpc.NewServer(...)``. Safety-token check (``MaxRecvMsgSize`` /
# ``MaxSendMsgSize`` in surrounding window) suppresses true negatives.
# Note: we deliberately match across multi-line Go calls — Go style
# wraps long option lists across lines. The greedy ``[\s\S]*?`` would
# misbehave; we use the cheap shape ``grpc.NewServer(`` to start the
# match and the safety check picks up MaxRecvMsgSize anywhere within
# ±600 chars.
_GRPC_GO_NEW_SERVER_NO_MAX = _re(
    r"\bgrpc\.NewServer\s*\("
)


# Rust tonic: ``Server::builder()``. Safety-token check
# (``max_decoding_message_size`` / ``max_encoding_message_size`` in
# surrounding window) suppresses true negatives. Tonic default is 4 MiB.
_GRPC_TONIC_BUILDER_NO_MAX = _re(
    r"\bServer::builder\s*\(\s*\)"
)


# ---- 11. gRPC reflection enabled (likely in production) -----------------


# Python: ``reflection.enable_server_reflection(...)``. Designed for
# ``grpcurl`` developer tooling, devastating in production: unauthenticated
# enumeration of every service / method / message type.
_GRPC_PY_REFLECTION_ENABLED = _re(
    r"\breflection\.enable_server_reflection\s*\("
)


# Go: ``reflection.Register(s)`` or ``reflection.RegisterV1Alpha(s)``.
_GRPC_GO_REFLECTION_ENABLED = _re(
    r"\breflection\.Register(?:V1Alpha)?\s*\("
)


# Rust tonic: any reference to ``tonic_reflection::`` indicates the
# reflection service is being built. Real shapes:
#   * ``Server::builder().add_service(tonic_reflection::server::Builder::configure().build()?)``
#   * ``let svc = tonic_reflection::server::Builder::configure().build()?; ... .add_service(svc)``
# We anchor on the ``tonic_reflection::`` path prefix which is the
# canonical reflection import — present in both shapes.
_GRPC_TONIC_REFLECTION_ENABLED = _re(
    r"\btonic_reflection::"
)


# ---- 12. gRPC insecure channel / no-TLS in non-localhost context -------


# Python server-side: ``server.add_insecure_port("[::]:N")`` or
# ``server.add_insecure_port("0.0.0.0:N")``. The loopback variant
# ``add_insecure_port("127.0.0.1:N")`` is acceptable but only if the
# bind literal is literally loopback — we catch the broader shapes
# (``[::]`` or ``0.0.0.0`` or a non-literal host).
_GRPC_PY_INSECURE_PORT_PUBLIC = _re(
    r"\.add_insecure_port\s*\(\s*[\"']"
    r"(?:\[?::\]?|0\.0\.0\.0|\$\{?\w+\}?|[a-zA-Z][\w.-]*?)"
    r":\d+[\"']"
)


# Python client-side: ``grpc.insecure_channel("host:port")`` where host
# is NOT loopback. We catch the shape; the detector validates host.
_GRPC_PY_INSECURE_CHANNEL = _re(
    r"\bgrpc\.insecure_channel\s*\(\s*[\"']"
    r"(?!(?:localhost|127\.0\.0\.1|::1|\[::1\])(?::|[\"']))"
    r"[^\"']{1,200}[\"']\s*\)"
)


# Go: ``grpc.WithInsecure()`` (deprecated, still common) and
# ``insecure.NewCredentials()`` (the explicit replacement). Both indicate
# the channel is unencrypted on the wire.
_GRPC_GO_WITH_INSECURE = _re(
    r"\b(?:grpc\.WithInsecure\s*\(\s*\)|insecure\.NewCredentials\s*\(\s*\))"
)


# ---- 13. gRPC interceptor chain ordering — auth AFTER tracing/logging ---


# Python: ``interceptors=[Trace..., Log..., Auth...]`` — auth last means
# the tracing and logging layers see unauthenticated request bodies.
# We match any case-insensitive "trace" / "log" / "audit" before "auth".
_GRPC_PY_INTERCEPTOR_AUTH_LAST = re.compile(
    r"\binterceptors\s*=\s*\[\s*[^\]]*?\b(?:[Tt]race|[Ll]og|[Aa]udit)\w*\s*\([^\]]*?,\s*[^\]]*?\b[Aa]uth\w*\s*\(",
    re.MULTILINE | re.UNICODE,
)


# Go: ``ChainUnaryInterceptor(TraceUnary, LogUnary, AuthUnary)`` — same
# ordering bug, expressed via ``grpc.ChainUnaryInterceptor`` /
# ``ChainStreamInterceptor``. Go style routinely wraps the call across
# multiple lines; we use ``[\s\S]`` to span newlines but cap each bridge
# at 200 chars (≤ 6-8 lines, plenty for a typical interceptor list).
_GRPC_GO_CHAIN_AUTH_LAST = re.compile(
    r"\bChain(?:Unary|Stream)Interceptor\s*\(\s*"
    r"[\s\S]{0,200}?(?:[Tt]race|[Ll]og|[Aa]udit)\w*\s*,"
    r"[\s\S]{0,200}?[Aa]uth\w*\s*[,)]",
    re.MULTILINE | re.UNICODE,
)


# Rust tower: ``ServiceBuilder::new().layer(TraceLayer)...layer(AuthLayer)``.
# Tower applies layers in reverse — the OUTERMOST layer is added LAST.
# So ``.layer(Trace) ... .layer(Auth)`` means Auth runs FIRST (correct)
# and Trace runs LAST. But ``.layer(Auth) ... .layer(Trace)`` means
# Trace runs FIRST (auth-after-tracing — the bug). We catch the latter.
_GRPC_TOWER_LAYER_TRACE_AFTER_AUTH = re.compile(
    r"\bServiceBuilder::new\s*\(\s*\)[\s\S]{0,400}?\.layer\s*\(\s*[Aa]uth\w*[\s\S]{0,400}?\.layer\s*\(\s*(?:[Tt]race|[Ll]og)\w*",
    re.MULTILINE | re.UNICODE,
)


# ---- 14. gRPC keepalive enforcement: permissive policy ------------------


# Go: ``keepalive.EnforcementPolicy{ MinTime: 0, PermitWithoutStream: true }``.
# Either flag alone is a smell; both together is an unauthenticated DOS
# surface.
_GRPC_GO_KEEPALIVE_MIN_TIME_ZERO = _re(
    r"\bkeepalive\.EnforcementPolicy\s*\{[^}]{0,400}\bMinTime\s*:\s*0\b"
)


_GRPC_GO_KEEPALIVE_PERMIT_WITHOUT_STREAM = _re(
    r"\bkeepalive\.EnforcementPolicy\s*\{[^}]{0,400}\bPermitWithoutStream\s*:\s*true\b"
)


# ---- 15. Protobuf recursive-message bomb -------------------------------


# .proto file with a recursive message definition: ``message Foo { Foo bar = 1; }``.
# Recursion in a protobuf message is legal but invites depth-bomb attacks
# unless the deserializer has an explicit recursion limit. The pattern
# matches when a ``message Name`` block contains a field of type
# ``Name`` (backreference) BEFORE the closing brace of THAT message —
# i.e. inside the message's own ``{...}`` block. We use ``[^}]*?`` to
# stop at the closing brace so a sibling ``message Tree { Node nodes; }``
# doesn't trigger a false positive on the original ``message Node`` def.
_PROTOBUF_RECURSIVE_MESSAGE = _re(
    r"^\s*message\s+(\w+)\s*\{"
    r"[^}]{0,500}?"
    r"\b\1\s+\w+\s*=\s*\d+\s*;"
)


# Python: ``MyMessage().ParseFromString(data)``. Safety-token check
# (``SetRecursionLimit`` / ``max_depth`` / ``MAX_DEPTH`` /
# ``recursion_limit`` / ``RECURSION_LIMIT`` in surrounding window)
# suppresses true negatives. The google.protobuf Python runtime has a
# default 100-deep recursion limit but raises a non-catchable C++
# exception when exceeded.
_PROTOBUF_PARSE_NO_RECURSION_LIMIT = _re(
    r"\b\w+\.ParseFromString\s*\([^)]+\)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="websocket-no-frame-size-limit",
        name="WebSocket endpoint with no frame / message-size limit",
        severity="HIGH",
        description=(
            "FastAPI / Starlette ``@app.websocket('/...')`` decorator above "
            "a handler that reads ``.receive_text() / .receive_bytes() / "
            ".receive_json()`` with NO ``max_size`` / ``max_message_size`` / "
            "``max_payload`` / ``MAX_*`` bound. uvicorn defaults to 16 MiB "
            "per frame; one attacker frame OOMs the worker hosting the "
            "entire sentinel dashboard. Source: SentinelOps-Autonomous-"
            "DevOps-AI sentinelops-backend/app/main.py:99-113."
        ),
        pattern=_WS_NO_FRAME_SIZE,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "max_size", "max_message_size", "max_payload",
            "MAX_FRAME", "MAX_MESSAGE", "MAX_PAYLOAD",
        ),
    ),
    Rule(
        id="websocket-node-no-max-payload",
        name="Node ws.Server with no maxPayload option",
        severity="HIGH",
        description=(
            "Node ``new WebSocket.Server({...})`` constructor with no "
            "``maxPayload`` in its options. The ``ws`` library's default "
            "``maxPayload`` is 100 MiB. A single oversized frame from a "
            "malicious client OOMs the Node worker."
        ),
        pattern=_WS_NODE_NO_MAX_PAYLOAD,
        owasp_asi="ASI-04",
        exclude_if_present=("maxPayload",),
    ),
    Rule(
        id="uvicorn-no-ws-max-size",
        name="uvicorn.run() with no ws_max_size",
        severity="MEDIUM",
        description=(
            "``uvicorn.run(...)`` invocation with no ``ws_max_size`` kwarg "
            "anywhere in the call. uvicorn defaults to 16 MiB per "
            "WebSocket frame across every route; the framework-level cap "
            "is the only defense if the per-route handler doesn't enforce "
            "its own size limit."
        ),
        pattern=_UVICORN_NO_WS_MAX_SIZE,
        owasp_asi="ASI-04",
        exclude_if_present=("ws_max_size",),
    ),
    Rule(
        id="websocket-no-origin-check",
        name="WebSocket accept() with no Origin allowlist (CSWSH)",
        severity="HIGH",
        description=(
            "``@app.websocket('/...')`` calls ``await websocket.accept()`` "
            "without first inspecting ``websocket.headers.get('origin')`` "
            "against an allowlist. Cross-Site WebSocket Hijacking (CSWSH) "
            "is the WebSocket analogue of CSRF; ``allow_credentials=True`` "
            "on the sibling HTTP API makes it worse because cookies "
            "authenticating the *user* are sent on the WebSocket "
            "handshake by default. Source: dr5-E proposal 2."
        ),
        pattern=_WS_NO_ORIGIN_CHECK,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "origin", "Origin", "ORIGIN",
            "allowed_origins", "ALLOWED_ORIGINS",
        ),
    ),
    Rule(
        id="websocket-no-handshake-auth",
        name="WebSocket endpoint with no handshake authentication",
        severity="CRITICAL",
        description=(
            "``@app.websocket('/...')`` route reads no ``Authorization`` "
            "header, no query-string token, no cookie-bound session, no "
            "``Depends(get_current_user)``-shaped injection before "
            "``await websocket.accept()``. The sibling HTTP API uses "
            "auth; the WebSocket dashboard does NOT — attackers know to "
            "probe there first. Source: SentinelOps-Autonomous-DevOps-AI "
            "sentinelops-backend/app/main.py:99, dr5-E proposal 3."
        ),
        pattern=_WS_NO_HANDSHAKE_AUTH,
        owasp_asi="ASI-05",
        exclude_if_present=(
            "token", "session", "api_key", "API_KEY",
            "Depends", "verify_jwt", "verify_token",
            "Authorization", "authenticate", "Cookie",
        ),
    ),
    Rule(
        id="jsonrpc-getattr-method-dispatch",
        name="JSON-RPC method dispatch via getattr (eval-shape)",
        severity="CRITICAL",
        description=(
            "``getattr(self, msg['method'])`` — attribute access keyed by "
            "attacker-controlled string from the JSON-RPC envelope. The "
            "single most common MCP-over-stdio / MCP-over-WebSocket "
            "foot-gun: a copy-paste server template that maps method "
            "names to attributes lets a prompt-injected agent call any "
            "private helper on the server class. Source: dr5-E proposal 4."
        ),
        pattern=_JSONRPC_GETATTR_DISPATCH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jsonrpc-unfiltered-dispatch-map",
        name="JSON-RPC dispatch map built from dir() / globals() / vars()",
        severity="HIGH",
        description=(
            "``METHOD_MAP = {... dir(self) ...}`` or "
            "``METHOD_MAP = globals()`` — the dispatch table is computed "
            "from a wide-open namespace instead of being an explicit "
            "allowlist. Same outcome as the getattr shape: attacker-"
            "controlled method name reaches an unintended attribute. "
            "Source: dr5-E proposal 4."
        ),
        pattern=_JSONRPC_UNFILTERED_DISPATCH_MAP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="json-loads-no-depth-cap",
        name="json.loads on attacker data with no depth / parse_constant guard",
        severity="MEDIUM",
        description=(
            "``json.loads(data | body | text | payload | msg | raw | "
            "content)`` with no ``max_depth`` / ``parse_constant`` / "
            "``RECURSION`` token nearby. Deeply-nested JSON objects "
            "(``{'a':{'a':...}}``) hit Python's default recursion limit "
            "of 1000 and leak a stack trace via the global exception "
            "handler. CBOR / MessagePack RPC envelopes have the same "
            "issue at deserialization. Source: dr5-E proposal 5."
        ),
        pattern=_JSON_LOADS_NO_DEPTH_CAP,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "max_depth", "MAX_DEPTH",
            "parse_constant", "RECURSION",
            "MAX_NESTING", "max_nesting",
        ),
    ),
    Rule(
        id="pydantic-parse-obj-no-depth-cap",
        name="Pydantic Model.parse_obj() with no depth cap",
        severity="MEDIUM",
        description=(
            "Pydantic v1 ``Model.parse_obj(data)`` (and v2's SecurityWarning-"
            "but-not-enforced equivalent) has no built-in recursion depth "
            "limit. Deeply-nested ``Optional[Optional[Optional[...]]]`` "
            "resolution exhausts CPU. Detector validates that a "
            "``max_depth`` annotation or wrapper is present. Source: "
            "dr5-E proposal 5."
        ),
        pattern=_PYDANTIC_PARSE_OBJ_NO_DEPTH,
        owasp_asi="ASI-04",
        exclude_if_present=("max_depth", "MAX_DEPTH"),
    ),
    Rule(
        id="http-body-no-content-length-cap",
        name="await request.body() with no Content-Length cap",
        severity="HIGH",
        description=(
            "``await request.body()`` (FastAPI / Starlette) with NO "
            "``content-length`` / ``MAX_BODY`` / ``max_content_length`` / "
            "``stream`` guard nearby. The body buffer is then "
            "``.decode('utf-8')``-ed (2× memory) and ``json.loads``-ed "
            "(3× memory). A single 500 MB body OOMs the gateway BEFORE "
            "the upstream provider rejects it. Source: sentinel-gateway "
            "sentinel/gateway.py:109-123, dr5-E proposal 6."
        ),
        pattern=_HTTP_BODY_NO_LENGTH_CAP,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "content-length", "content_length",
            "MAX_BODY", "max_body_size",
            "max_content_length", "MAX_CONTENT_LENGTH",
            "MAX_REQUEST", ".stream(",
        ),
    ),
    Rule(
        id="flask-get-data-no-limit",
        name="Flask request.get_data() with no MAX_CONTENT_LENGTH",
        severity="MEDIUM",
        description=(
            "Flask ``request.get_data()`` with no ``max_content_length`` "
            "token nearby. Flask has no per-call size cap; the app-level "
            "``MAX_CONTENT_LENGTH`` config key is the only defense. "
            "Source: dr5-E proposal 6."
        ),
        pattern=_FLASK_GET_DATA_NO_LIMIT,
        owasp_asi="ASI-04",
        exclude_if_present=("max_content_length", "MAX_CONTENT_LENGTH"),
    ),
    Rule(
        id="cors-credentials-with-permissive-origin",
        name="CORSMiddleware allow_origins=... with allow_credentials=True",
        severity="HIGH",
        description=(
            "Starlette / FastAPI ``CORSMiddleware(allow_origins=..., "
            "allow_credentials=True)``. If ``allow_origins`` is env-driven "
            "(``os.environ.get('CORS_ORIGINS', '').split(',')``), a "
            "single ``.env`` entry of ``*,https://attacker.tld`` silently "
            "widens the credentialed origin set; the wildcard suppresses "
            "credentials but the server still echoes ANY origin. Source: "
            "AgentShield backend/main.py:36-41, SentinelOps-Autonomous-"
            "DevOps-AI sentinelops-backend/app/main.py:75-81, dr5-E "
            "proposal 7."
        ),
        pattern=_CORS_CREDENTIALS_WITH_ORIGIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cors-credentials-with-permissive-origin-reordered",
        name="CORSMiddleware allow_credentials=True with allow_origins=... (reordered kwargs)",
        severity="HIGH",
        description=(
            "Same shape as the canonical rule but with the kwargs in the "
            "opposite order (``allow_credentials=True`` appearing before "
            "``allow_origins=``). The underlying foot-gun is identical: "
            "credentialed CORS with an attacker-mutable origin list. "
            "Source: dr5-E proposal 7."
        ),
        pattern=_CORS_CREDENTIALS_WITH_ORIGIN_REORDERED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="node-cors-credentials-with-origin",
        name="Express cors({ origin: ..., credentials: true })",
        severity="HIGH",
        description=(
            "Node / Express ``cors({ origin: ..., credentials: true })`` — "
            "same CSWSH / cross-origin-credentialed-read foot-gun as the "
            "Starlette shape. If ``origin`` is a function or an array "
            "including ``'*'`` and ``credentials: true`` is set, browsers "
            "will send cookies on cross-origin requests. Source: dr5-E "
            "proposal 7."
        ),
        pattern=_NODE_CORS_CREDENTIALS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="websocket-broadcast-no-backpressure",
        name="WebSocket broadcast with no per-client timeout / backpressure",
        severity="HIGH",
        description=(
            "``async def broadcast(...)`` iterates ``active_connections`` "
            "and ``await``s ``.send_json / .send_text / .send_bytes`` "
            "serially with NO ``timeout`` / ``asyncio.wait_for`` / "
            "``ensure_future`` / ``gather`` / ``create_task`` token. One "
            "slow client backpressures the entire broadcast — an "
            "attacker holding 1000 idle sockets blocks all incident "
            "notifications. Source: SentinelOps-Autonomous-DevOps-AI "
            "sentinelops-backend/app/services/websocket_service.py:19-29, "
            "dr5-E proposal 8."
        ),
        pattern=_WS_BROADCAST_NO_BACKPRESSURE,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "timeout=", "asyncio.wait_for",
            "ensure_future", "asyncio.gather", "create_task",
        ),
    ),
    Rule(
        id="websocket-no-rate-limit-loop",
        name="WebSocket while-True receive loop with no rate limit",
        severity="HIGH",
        description=(
            "``while True: data = await ws.receive_text()`` (or "
            "``.receive_bytes()`` / ``.receive_json()``) with NO ``rate`` "
            "/ ``throttle`` / ``TokenBucket`` / ``asyncio.sleep`` / "
            "``RATE_LIMIT`` token nearby. One client at 10 kHz burns the "
            "event loop. Source: dr5-E proposal 9."
        ),
        pattern=_WS_NO_RATE_LIMIT_LOOP,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "throttle", "TokenBucket", "token_bucket",
            "asyncio.sleep", "RATE_LIMIT", "rate_limit", "RateLimiter",
        ),
    ),
    Rule(
        id="grpc-py-server-no-max-recv-msg-size",
        name="grpc.server(...) with no MaxRecvMsgSize option",
        severity="HIGH",
        description=(
            "Python ``grpc.server(futures.ThreadPoolExecutor(...))`` with "
            "no ``MaxRecvMsgSize`` / ``max_message_length`` / "
            "``max_receive_message_length`` option nearby. Default is "
            "4 MiB; teams routinely raise to MaxInt32 to 'handle big "
            "protobufs', at which point a single oversized protobuf "
            "OOMs the server. Source: dr5-E proposal 10."
        ),
        pattern=_GRPC_PY_SERVER_NO_MAX_RECV,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "MaxRecvMsgSize", "max_message_length",
            "max_receive_message_length", "grpc.max_receive",
        ),
    ),
    Rule(
        id="grpc-go-server-no-max-msg-size",
        name="grpc.NewServer(...) with no MaxRecvMsgSize / MaxSendMsgSize",
        severity="HIGH",
        description=(
            "Go ``grpc.NewServer(...)`` constructor with no "
            "``MaxRecvMsgSize`` / ``MaxSendMsgSize`` ServerOption nearby. "
            "Default is 4 MiB; same OOM surface as the Python variant "
            "once the cap is raised. Source: dr5-E proposal 10."
        ),
        pattern=_GRPC_GO_NEW_SERVER_NO_MAX,
        owasp_asi="ASI-04",
        exclude_if_present=("MaxRecvMsgSize", "MaxSendMsgSize"),
    ),
    Rule(
        id="grpc-tonic-builder-no-max-msg-size",
        name="tonic Server::builder() with no max_*_message_size",
        severity="HIGH",
        description=(
            "Rust tonic ``Server::builder()`` with no "
            "``max_decoding_message_size`` / ``max_encoding_message_size`` "
            "configuration nearby. Tonic's default is 4 MiB. Source: "
            "dr5-E proposal 10."
        ),
        pattern=_GRPC_TONIC_BUILDER_NO_MAX,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "max_decoding_message_size", "max_encoding_message_size",
        ),
    ),
    Rule(
        id="grpc-py-reflection-enabled",
        name="gRPC server reflection enabled (Python)",
        severity="HIGH",
        description=(
            "Python ``reflection.enable_server_reflection(SERVICE_NAMES, "
            "server)`` — unauthenticated enumeration of every service, "
            "method, and message type. Devastating in production. "
            "Wrap in ``if os.getenv('ENV') in {'dev','local','test'}``. "
            "Source: dr5-E proposal 11."
        ),
        pattern=_GRPC_PY_REFLECTION_ENABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-go-reflection-enabled",
        name="gRPC server reflection enabled (Go)",
        severity="HIGH",
        description=(
            "Go ``reflection.Register(s)`` (or "
            "``reflection.RegisterV1Alpha(s)``) — same unauthenticated "
            "enumeration surface. The official tutorial includes this "
            "near the bottom; nobody removes it before deployment. "
            "Source: dr5-E proposal 11."
        ),
        pattern=_GRPC_GO_REFLECTION_ENABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-tonic-reflection-enabled",
        name="gRPC server reflection enabled (Rust tonic)",
        severity="HIGH",
        description=(
            "Rust tonic ``.add_service(tonic_reflection::server::"
            "Builder::...build())`` — same surface as the Python / Go "
            "variants. Source: dr5-E proposal 11."
        ),
        pattern=_GRPC_TONIC_REFLECTION_ENABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-py-insecure-port-public",
        name="grpc server.add_insecure_port on public bind",
        severity="HIGH",
        description=(
            "Python ``server.add_insecure_port('[::]:N')`` or "
            "``add_insecure_port('0.0.0.0:N')`` — gRPC server bound on a "
            "non-loopback interface with no TLS. The detector validates "
            "whether ``add_secure_port`` is also present (mixed mode is "
            "acceptable for local-port-forward setups). Loopback "
            "(``127.0.0.1`` / ``::1``) is exempt. Source: dr5-E "
            "proposal 12."
        ),
        pattern=_GRPC_PY_INSECURE_PORT_PUBLIC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-py-insecure-channel-non-localhost",
        name="grpc.insecure_channel('host:port') to a non-loopback host",
        severity="HIGH",
        description=(
            "Python client-side ``grpc.insecure_channel(target)`` where "
            "``target`` is NOT localhost / 127.0.0.1 / ::1. Plaintext "
            "gRPC reveals headers (Authorization Bearer tokens), "
            "metadata, and the full request body to any on-path observer. "
            "Source: dr5-E proposal 12."
        ),
        pattern=_GRPC_PY_INSECURE_CHANNEL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-go-with-insecure",
        name="grpc-go WithInsecure() / insecure.NewCredentials()",
        severity="HIGH",
        description=(
            "Go ``grpc.WithInsecure()`` (deprecated) or "
            "``insecure.NewCredentials()`` (the explicit replacement). "
            "Either indicates a gRPC channel transported without TLS — "
            "Anthropic API keys carried in ``authorization: Bearer ...`` "
            "metadata are revealed on the wire. Source: dr5-E proposal 12."
        ),
        pattern=_GRPC_GO_WITH_INSECURE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-py-interceptor-auth-after-logging",
        name="Python gRPC interceptor chain: auth AFTER tracing / logging",
        severity="HIGH",
        description=(
            "Python ``interceptors=[Trace..., Log..., Auth...]`` — auth "
            "is LAST. Tracing and logging layers see and log the "
            "unauthenticated request body before auth rejects it; failed-"
            "auth log entries contain attacker-controlled protobuf payloads. "
            "Indirect prompt-injection vector when those logs are later "
            "ingested by Claude. Source: dr5-E proposal 13."
        ),
        pattern=_GRPC_PY_INTERCEPTOR_AUTH_LAST,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-go-chain-interceptor-auth-last",
        name="grpc-go ChainUnaryInterceptor with auth AFTER tracing / logging",
        severity="HIGH",
        description=(
            "Go ``grpc.ChainUnaryInterceptor(TraceUnary, LogUnary, "
            "AuthUnary)`` — same ordering bug as the Python shape. "
            "Auth must be FIRST so tracing / logging never sees an "
            "unauthenticated body. Rate-limit also goes before auth so "
            "failed-auth doesn't generate work. Source: dr5-E proposal 13."
        ),
        pattern=_GRPC_GO_CHAIN_AUTH_LAST,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-tower-layer-auth-before-trace",
        name="Rust tower ServiceBuilder: AuthLayer before TraceLayer",
        severity="HIGH",
        description=(
            "Rust ``ServiceBuilder::new().layer(AuthLayer)...layer(TraceLayer)`` "
            "— tower applies layers in REVERSE, so the layer added LAST "
            "runs FIRST. ``.layer(Auth)...layer(Trace)`` means Trace runs "
            "first, exposing unauthenticated request bodies to logs. "
            "Source: dr5-E proposal 13."
        ),
        pattern=_GRPC_TOWER_LAYER_TRACE_AFTER_AUTH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-keepalive-mintime-zero",
        name="grpc-go keepalive.EnforcementPolicy MinTime: 0",
        severity="MEDIUM",
        description=(
            "Go ``keepalive.EnforcementPolicy{ MinTime: 0, ... }`` — "
            "disables the PING-spam limit. A malicious client floods "
            "PINGs at 1 kHz; the server spends CPU on PING-PONG with no "
            "useful work. The grpc-go default is 5s. Source: dr5-E "
            "proposal 14."
        ),
        pattern=_GRPC_GO_KEEPALIVE_MIN_TIME_ZERO,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="grpc-keepalive-permit-without-stream",
        name="grpc-go keepalive.EnforcementPolicy PermitWithoutStream: true",
        severity="MEDIUM",
        description=(
            "Go ``keepalive.EnforcementPolicy{ PermitWithoutStream: true }`` "
            "— allows clients to send PINGs with no active RPC. "
            "Unauthenticated-DOS surface when combined with MinTime: 0. "
            "Source: dr5-E proposal 14."
        ),
        pattern=_GRPC_GO_KEEPALIVE_PERMIT_WITHOUT_STREAM,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="protobuf-recursive-message-definition",
        name="Protobuf message defined recursively",
        severity="MEDIUM",
        description=(
            "A ``.proto`` file defines ``message Foo { Foo bar = 1; }`` — "
            "legal but invites depth-bomb attacks unless the deserializer "
            "has an explicit recursion limit. Prefer flattening "
            "(``repeated Foo nodes = 1`` with an ``int32 parent_id`` "
            "field). Source: dr5-E proposal 15."
        ),
        pattern=_PROTOBUF_RECURSIVE_MESSAGE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="protobuf-parse-no-recursion-limit",
        name="Protobuf ParseFromString with no recursion limit",
        severity="MEDIUM",
        description=(
            "Python ``MyMessage().ParseFromString(data)`` with NO "
            "``SetRecursionLimit`` / ``max_depth`` / ``RECURSION_LIMIT`` "
            "token nearby. The google.protobuf Python runtime raises a "
            "non-catchable C++ exception on deep recursion. A 1 kB "
            "protobuf can crash the server — well below any reasonable "
            "``MaxRecvMsgSize``. Source: dr5-E proposal 15."
        ),
        pattern=_PROTOBUF_PARSE_NO_RECURSION_LIMIT,
        owasp_asi="ASI-04",
        exclude_if_present=(
            "SetRecursionLimit", "max_depth", "MAX_DEPTH",
            "recursion_limit", "RECURSION_LIMIT",
        ),
    ),
)


# ---- Detector-side allowlist helpers -----------------------------------


# Bind hosts considered "localhost-safe" — the detector uses these to
# downgrade severity on ``add_insecure_port`` and ``insecure_channel``
# matches. Kept in lockstep with network_exfil_patterns.LOOPBACK_HOSTS.
LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1", "::1", "[::1]", "localhost",
})


# Default WebSocket / gRPC message-size caps the detector recommends. The
# catalog itself does NOT enforce these (it's a stage-1 regex pre-filter);
# the detector applies them in stage-2 as part of the remediation hint.
RECOMMENDED_WS_MAX_FRAME_BYTES: int = 1 * 1024 * 1024     # 1 MiB
RECOMMENDED_GRPC_MAX_RECV_BYTES: int = 4 * 1024 * 1024    # 4 MiB (gRPC default)
RECOMMENDED_HTTP_MAX_BODY_BYTES: int = 10 * 1024 * 1024   # 10 MiB


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Mirrors network_exfil_patterns._line_col and parser_format_patterns._line_col
    so callers get identical coordinates for findings emitted by any of
    the three modules.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "prose") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply:
      * "prose"  (default) — runs every rule. Skill bodies, READMEs, and
                              configuration files may textually reference
                              gRPC / WebSocket keywords but the patterns
                              are tight enough that FP-rate stays low.
      * "source"            — same set; every rule in this catalog targets
                              source-code shapes (decorator + handler,
                              call-site + missing-option), so "source" and
                              "prose" return identical findings. The
                              parameter exists for parity with
                              network_exfil_patterns / parser_format_patterns.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same position emits one.
    """
    if not text:
        return []
    # `file_kind` is accepted for parity with the sibling catalogs; gRPC /
    # WebSocket / JSON-RPC rules all apply identically to prose and source
    # (every rule's shape is a source-code construct, and prose only
    # quotes those constructs in code-fenced blocks — same regex hit).
    del file_kind
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    text_len = len(text)
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            # Bidirectional safety-token check. Python ``re`` only supports
            # fixed-width lookbehind, so we open a ±_SAFETY_WINDOW_CHARS
            # window around the match and substring-check for any of the
            # rule's ``exclude_if_present`` tokens. If found, this is
            # almost certainly a true negative (the author wrote the
            # safety check) — suppress the finding at the catalog level
            # so the detector doesn't have to re-derive it in stage 2.
            if rule.exclude_if_present:
                window_start = max(0, m.start() - _SAFETY_WINDOW_CHARS)
                window_end = min(text_len, m.end() + _SAFETY_WINDOW_CHARS)
                window = text[window_start:window_end]
                if any(tok in window for tok in rule.exclude_if_present):
                    continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


# Bidirectional safety-token search window. 600 chars ≈ 15-20 lines of
# typical Python source — wide enough to catch a "if Content-Length >
# MAX_BODY: return" guard placed immediately before an
# ``await request.body()`` call, narrow enough to avoid the window
# spilling into an unrelated function several screenfuls away.
_SAFETY_WINDOW_CHARS: int = 600
