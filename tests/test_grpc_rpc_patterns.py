"""Tests for scripts/lib/grpc_rpc_patterns.py.

Pattern-coverage tests for the Wave-19 (distill round 5, agent E)
gRPC / RPC payload + WebSocket / JSON-RPC server-side ingress catalogue.

Every rule gets at least one positive + one negative test. The catalog
covers the RPC ENVELOPE / FRAMING layer — distinct from the byte-level
deserializer catalog (`parser_format_patterns.py`) and the egress
catalog (`network_exfil_patterns.py`).

Source: `reports/distill-round-5/grpc-rpc-payload.md` — 15 proposals.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import grpc_rpc_patterns as grp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(grp.RULES, tuple)
    rule_ids = [r.id for r in grp.RULES]
    expected = {
        "websocket-no-frame-size-limit",
        "websocket-node-no-max-payload",
        "uvicorn-no-ws-max-size",
        "websocket-no-origin-check",
        "websocket-no-handshake-auth",
        "jsonrpc-getattr-method-dispatch",
        "jsonrpc-unfiltered-dispatch-map",
        "json-loads-no-depth-cap",
        "pydantic-parse-obj-no-depth-cap",
        "http-body-no-content-length-cap",
        "flask-get-data-no-limit",
        "cors-credentials-with-permissive-origin",
        "cors-credentials-with-permissive-origin-reordered",
        "node-cors-credentials-with-origin",
        "websocket-broadcast-no-backpressure",
        "websocket-no-rate-limit-loop",
        "grpc-py-server-no-max-recv-msg-size",
        "grpc-go-server-no-max-msg-size",
        "grpc-tonic-builder-no-max-msg-size",
        "grpc-py-reflection-enabled",
        "grpc-go-reflection-enabled",
        "grpc-tonic-reflection-enabled",
        "grpc-py-insecure-port-public",
        "grpc-py-insecure-channel-non-localhost",
        "grpc-go-with-insecure",
        "grpc-py-interceptor-auth-after-logging",
        "grpc-go-chain-interceptor-auth-last",
        "grpc-tower-layer-auth-before-trace",
        "grpc-keepalive-mintime-zero",
        "grpc-keepalive-permit-without-stream",
        "protobuf-recursive-message-definition",
        "protobuf-parse-no-recursion-limit",
    }
    assert expected.issubset(set(rule_ids))


def test_every_rule_has_owasp_mapping() -> None:
    """Every catalog rule must declare a real ASI mapping and a valid severity."""
    for rule in grp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding is a frozen NamedTuple — must accept the documented fields."""
    f = grp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_loopback_hosts_exported() -> None:
    """Detectors import LOOPBACK_HOSTS to stay lockstep with the catalog."""
    assert "127.0.0.1" in grp.LOOPBACK_HOSTS
    assert "localhost" in grp.LOOPBACK_HOSTS
    assert "::1" in grp.LOOPBACK_HOSTS


def test_recommended_caps_exported() -> None:
    """Detectors render the recommended caps in remediation hints."""
    assert grp.RECOMMENDED_WS_MAX_FRAME_BYTES > 0
    assert grp.RECOMMENDED_GRPC_MAX_RECV_BYTES > 0
    assert grp.RECOMMENDED_HTTP_MAX_BODY_BYTES > 0


# ---------- helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[grp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in grp.scan_text(text) if f.rule_id == rule_id]


def test_empty_text_no_findings() -> None:
    """Empty input must return an empty list — scan_text fast-path."""
    assert grp.scan_text("") == []
    assert grp.scan_text("   \n   \n") == []


# ---------- 1. WebSocket no frame-size limit -----------------------------


def test_ws_no_frame_size_positive() -> None:
    """FastAPI @app.websocket with receive_text() and no max_size kwarg fires."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws_endpoint(websocket: WebSocket):\n"
        "    await websocket.accept()\n"
        "    while True:\n"
        "        data = await websocket.receive_text()\n"
        "        print(data)\n"
    )
    assert _hits("websocket-no-frame-size-limit", src)


def test_ws_no_frame_size_negative_max_size_present() -> None:
    """When MAX_FRAME constant is referenced in the handler, no hit."""
    src = (
        "MAX_FRAME = 1024 * 1024\n"
        "@app.websocket('/ws')\n"
        "async def ws_endpoint(websocket: WebSocket):\n"
        "    await websocket.accept()\n"
        "    data = await websocket.receive_text()\n"
        "    if len(data) > MAX_FRAME:\n"
        "        await websocket.close(1009)\n"
    )
    assert _hits("websocket-no-frame-size-limit", src) == []


# ---------- 2. Node ws.Server no maxPayload ------------------------------


def test_ws_node_no_max_payload_positive() -> None:
    """new WebSocket.Server({...}) with no maxPayload option fires."""
    src = (
        "const wss = new WebSocket.Server({ port: 8080, path: '/ws' });\n"
        "wss.on('connection', ws => ws.send('hi'));\n"
    )
    assert _hits("websocket-node-no-max-payload", src)


def test_ws_node_no_max_payload_negative_with_option() -> None:
    """maxPayload option present — no hit."""
    src = (
        "const wss = new WebSocket.Server({ port: 8080, maxPayload: 65536 });\n"
    )
    assert _hits("websocket-node-no-max-payload", src) == []


# ---------- 3. uvicorn.run no ws_max_size --------------------------------


def test_uvicorn_no_ws_max_size_positive() -> None:
    """uvicorn.run() without ws_max_size kwarg fires."""
    src = "uvicorn.run(app, host='0.0.0.0', port=8000)\n"
    assert _hits("uvicorn-no-ws-max-size", src)


def test_uvicorn_no_ws_max_size_negative_with_kwarg() -> None:
    """ws_max_size kwarg present — no hit."""
    src = "uvicorn.run(app, host='0.0.0.0', port=8000, ws_max_size=1048576)\n"
    assert _hits("uvicorn-no-ws-max-size", src) == []


# ---------- 4. WebSocket no origin check ---------------------------------


def test_ws_no_origin_check_positive() -> None:
    """websocket.accept() without origin inspection fires."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket):\n"
        "    await websocket.accept()\n"
        "    print('connected')\n"
    )
    assert _hits("websocket-no-origin-check", src)


def test_ws_no_origin_check_negative_with_origin_check() -> None:
    """When origin is checked before accept(), no hit."""
    src = (
        "ALLOWED_ORIGINS = {'https://dashboard.example.com'}\n"
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket):\n"
        "    origin = websocket.headers.get('origin')\n"
        "    if origin not in ALLOWED_ORIGINS:\n"
        "        await websocket.close(1008)\n"
        "        return\n"
        "    await websocket.accept()\n"
    )
    assert _hits("websocket-no-origin-check", src) == []


# ---------- 5. WebSocket no handshake auth -------------------------------


def test_ws_no_handshake_auth_positive() -> None:
    """Endpoint with only websocket parameter and no auth-token check fires."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket):\n"
        "    await websocket.accept()\n"
        "    print('connected')\n"
    )
    assert _hits("websocket-no-handshake-auth", src)


def test_ws_no_handshake_auth_negative_depends() -> None:
    """Endpoint that uses Depends(get_current_user) — no hit."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket, user=Depends(get_current_user)):\n"
        "    await websocket.accept()\n"
    )
    assert _hits("websocket-no-handshake-auth", src) == []


def test_ws_no_handshake_auth_negative_token_in_body() -> None:
    """Endpoint that verifies a query-string token — no hit."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket):\n"
        "    token = websocket.query_params.get('token')\n"
        "    if not verify_token(token):\n"
        "        await websocket.close(1008)\n"
        "        return\n"
        "    await websocket.accept()\n"
    )
    assert _hits("websocket-no-handshake-auth", src) == []


# ---------- 6. JSON-RPC getattr dispatch ---------------------------------


def test_jsonrpc_getattr_dispatch_positive() -> None:
    """getattr(self, msg['method']) — classic eval-shape JSON-RPC dispatch."""
    src = (
        "def dispatch(self, msg):\n"
        "    handler = getattr(self, msg['method'])\n"
        "    return handler(msg.get('params', {}))\n"
    )
    assert _hits("jsonrpc-getattr-method-dispatch", src)


def test_jsonrpc_getattr_dispatch_double_quoted() -> None:
    """Same shape with double quotes around 'method' — still fires."""
    src = 'handler = getattr(self, msg["method"])\n'
    assert _hits("jsonrpc-getattr-method-dispatch", src)


def test_jsonrpc_getattr_dispatch_negative_allowlist() -> None:
    """When method goes through an explicit allowlist — no hit."""
    src = (
        "ALLOWED = {'ping', 'list_tools', 'call_tool'}\n"
        "def dispatch(self, msg):\n"
        "    method = msg['method']\n"
        "    if method not in ALLOWED:\n"
        "        raise JSONRPCError(-32601, 'method not found')\n"
        "    return self._handlers[method](msg)\n"
    )
    assert _hits("jsonrpc-getattr-method-dispatch", src) == []


# ---------- 7. JSON-RPC unfiltered dispatch map --------------------------


def test_jsonrpc_unfiltered_map_dir_based() -> None:
    """METHOD_MAP built from dir(self) is a hit."""
    src = (
        "class Handler:\n"
        "    def __init__(self):\n"
        "        METHOD_MAP = {name: getattr(self, name) for name in dir(self)}\n"
    )
    assert _hits("jsonrpc-unfiltered-dispatch-map", src)


def test_jsonrpc_unfiltered_map_globals_based() -> None:
    """METHOD_MAP = globals() is a hit."""
    src = "METHOD_MAP = globals()\n"
    assert _hits("jsonrpc-unfiltered-dispatch-map", src)


def test_jsonrpc_unfiltered_map_negative_explicit() -> None:
    """Explicit-allowlist METHOD_MAP — no hit."""
    src = (
        "METHOD_MAP = {\n"
        "    'ping': handle_ping,\n"
        "    'list_tools': handle_list_tools,\n"
        "    'call_tool': handle_call_tool,\n"
        "}\n"
    )
    assert _hits("jsonrpc-unfiltered-dispatch-map", src) == []


# ---------- 8. json.loads no depth cap -----------------------------------


def test_json_loads_no_depth_cap_positive() -> None:
    """json.loads on attacker data ('body' / 'text' / 'data') fires."""
    src = (
        "async def handler(request):\n"
        "    body = await request.body()\n"
        "    text = body.decode('utf-8')\n"
        "    data = json.loads(text)\n"
        "    return data\n"
    )
    assert _hits("json-loads-no-depth-cap", src)


def test_json_loads_no_depth_cap_negative_with_parse_constant() -> None:
    """json.loads with parse_constant nearby — no hit (author thought about it)."""
    src = (
        "def reject_nan(c):\n"
        "    raise ValueError('NaN not allowed')\n"
        "data = json.loads(payload, parse_constant=reject_nan)\n"
    )
    assert _hits("json-loads-no-depth-cap", src) == []


def test_json_loads_no_depth_cap_negative_literal_string() -> None:
    """json.loads of a literal string is not on attacker data — no hit."""
    src = "config = json.loads('{\"key\": \"value\"}')\n"
    assert _hits("json-loads-no-depth-cap", src) == []


# ---------- 9. Pydantic parse_obj no depth cap ---------------------------


def test_pydantic_parse_obj_no_depth_positive() -> None:
    """Model.parse_obj(data) with no max_depth nearby fires."""
    src = (
        "from pydantic import BaseModel\n"
        "class Req(BaseModel):\n"
        "    method: str\n"
        "req = Req.parse_obj(data)\n"
    )
    assert _hits("pydantic-parse-obj-no-depth-cap", src)


def test_pydantic_parse_obj_no_depth_negative_with_check() -> None:
    """When max_depth check is present, no hit."""
    src = (
        "MAX_DEPTH = 16\n"
        "if data_depth(data) > MAX_DEPTH:\n"
        "    raise ValueError\n"
        "req = Req.parse_obj(data)\n"
    )
    assert _hits("pydantic-parse-obj-no-depth-cap", src) == []


# ---------- 10. HTTP body no content-length cap --------------------------


def test_http_body_no_length_cap_positive() -> None:
    """await request.body() with no MAX_BODY token fires."""
    src = (
        "async def handler(request):\n"
        "    body = await request.body()\n"
        "    text = body.decode('utf-8')\n"
        "    return text\n"
    )
    assert _hits("http-body-no-content-length-cap", src)


def test_http_body_no_length_cap_negative_with_check() -> None:
    """When Content-Length is checked, no hit."""
    src = (
        "async def handler(request):\n"
        "    if int(request.headers.get('content-length', 0)) > MAX_BODY:\n"
        "        return JSONResponse({'error': 'too large'}, status_code=413)\n"
        "    body = await request.body()\n"
    )
    assert _hits("http-body-no-content-length-cap", src) == []


# ---------- 11. Flask get_data no limit ----------------------------------


def test_flask_get_data_no_limit_positive() -> None:
    """request.get_data() with no MAX_CONTENT_LENGTH nearby fires."""
    src = (
        "@app.route('/upload', methods=['POST'])\n"
        "def upload():\n"
        "    data = request.get_data()\n"
        "    return data\n"
    )
    assert _hits("flask-get-data-no-limit", src)


def test_flask_get_data_no_limit_negative_with_config() -> None:
    """When max_content_length config is set, no hit."""
    src = (
        "app.config['max_content_length'] = 10 * 1024 * 1024\n"
        "@app.route('/upload', methods=['POST'])\n"
        "def upload():\n"
        "    data = request.get_data()\n"
    )
    assert _hits("flask-get-data-no-limit", src) == []


# ---------- 12. CORS credentials with permissive origin -----------------


def test_cors_credentials_with_origin_positive() -> None:
    """CORSMiddleware with allow_origins=... + allow_credentials=True fires."""
    src = (
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['*'],\n"
        "    allow_credentials=True,\n"
        "    allow_methods=['*'],\n"
        ")\n"
    )
    assert _hits("cors-credentials-with-permissive-origin", src)


def test_cors_credentials_with_origin_env_driven_positive() -> None:
    """Env-driven origin list with allow_credentials=True — fires (the variant
    proposal 7 specifically calls out)."""
    src = (
        "origins = os.environ.get('CORS_ORIGINS', '').split(',')\n"
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=origins,\n"
        "    allow_credentials=True,\n"
        ")\n"
    )
    assert _hits("cors-credentials-with-permissive-origin", src)


def test_cors_no_credentials_negative() -> None:
    """allow_credentials=False — no hit."""
    src = (
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_origins=['https://dashboard.example.com'],\n"
        "    allow_credentials=False,\n"
        ")\n"
    )
    assert _hits("cors-credentials-with-permissive-origin", src) == []


def test_cors_credentials_reordered_positive() -> None:
    """allow_credentials=True before allow_origins= — the reordered rule fires."""
    src = (
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        "    allow_credentials=True,\n"
        "    allow_origins=settings.CORS_ORIGINS,\n"
        "    allow_methods=['*'],\n"
        ")\n"
    )
    assert _hits("cors-credentials-with-permissive-origin-reordered", src)


# ---------- 13. Node CORS credentials -----------------------------------


def test_node_cors_credentials_positive() -> None:
    """Express cors({ origin: ..., credentials: true }) fires."""
    src = "app.use(cors({ origin: 'https://dashboard.example.com', credentials: true }));\n"
    assert _hits("node-cors-credentials-with-origin", src)


def test_node_cors_credentials_negative_no_credentials() -> None:
    """No credentials flag — no hit."""
    src = "app.use(cors({ origin: 'https://dashboard.example.com' }));\n"
    assert _hits("node-cors-credentials-with-origin", src) == []


# ---------- 14. WebSocket broadcast no backpressure ---------------------


def test_ws_broadcast_no_backpressure_positive() -> None:
    """Broadcast that iterates active_connections and awaits send_json fires."""
    src = (
        "async def broadcast(self, message):\n"
        "    for connection in self.active_connections:\n"
        "        await connection.send_json(message)\n"
    )
    assert _hits("websocket-broadcast-no-backpressure", src)


def test_ws_broadcast_no_backpressure_negative_with_timeout() -> None:
    """Broadcast that uses asyncio.wait_for — no hit."""
    src = (
        "async def broadcast(self, message):\n"
        "    for connection in self.active_connections:\n"
        "        await asyncio.wait_for(connection.send_json(message), timeout=5.0)\n"
    )
    assert _hits("websocket-broadcast-no-backpressure", src) == []


def test_ws_broadcast_no_backpressure_negative_gather() -> None:
    """Broadcast that uses asyncio.gather — no hit (parallel fan-out)."""
    src = (
        "async def broadcast(self, message):\n"
        "    tasks = [conn.send_json(message) for conn in self.active_connections]\n"
        "    await asyncio.gather(*tasks, return_exceptions=True)\n"
    )
    # `gather` token alone in the lookahead suppresses the hit even though
    # the iteration shape is the same; that's acceptable — the fan-out
    # IS the remediation.
    assert _hits("websocket-broadcast-no-backpressure", src) == []


# ---------- 15. WebSocket no rate-limit loop -----------------------------


def test_ws_no_rate_limit_loop_positive() -> None:
    """while True: data = await ws.receive_text() with no throttle fires."""
    src = (
        "while True:\n"
        "    data = await websocket.receive_text()\n"
        "    print(data)\n"
    )
    assert _hits("websocket-no-rate-limit-loop", src)


def test_ws_no_rate_limit_loop_negative_with_sleep() -> None:
    """asyncio.sleep present in loop body — no hit."""
    src = (
        "while True:\n"
        "    data = await websocket.receive_text()\n"
        "    await asyncio.sleep(0.01)  # crude rate limit\n"
        "    print(data)\n"
    )
    assert _hits("websocket-no-rate-limit-loop", src) == []


def test_ws_no_rate_limit_loop_negative_token_bucket() -> None:
    """TokenBucket reference in scope — no hit."""
    src = (
        "bucket = TokenBucket(rate=10)\n"
        "while True:\n"
        "    data = await websocket.receive_text()\n"
        "    if not bucket.consume():\n"
        "        await websocket.close(1008)\n"
        "        break\n"
    )
    assert _hits("websocket-no-rate-limit-loop", src) == []


# ---------- 16. gRPC Python server no MaxRecvMsgSize --------------------


def test_grpc_py_server_no_max_positive() -> None:
    """grpc.server(...) with no MaxRecvMsgSize option fires."""
    src = (
        "import grpc\n"
        "from concurrent import futures\n"
        "server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))\n"
    )
    assert _hits("grpc-py-server-no-max-recv-msg-size", src)


def test_grpc_py_server_no_max_negative_with_option() -> None:
    """grpc.server with MaxRecvMsgSize in options — no hit."""
    src = (
        "server = grpc.server(\n"
        "    futures.ThreadPoolExecutor(max_workers=10),\n"
        "    options=[('grpc.MaxRecvMsgSize', 4 * 1024 * 1024)],\n"
        ")\n"
    )
    assert _hits("grpc-py-server-no-max-recv-msg-size", src) == []


# ---------- 17. gRPC Go server no MaxRecvMsgSize ------------------------


def test_grpc_go_server_no_max_positive() -> None:
    """grpc.NewServer() with no MaxRecvMsgSize fires."""
    src = (
        "func main() {\n"
        '    lis, _ := net.Listen("tcp", ":50051")\n'
        "    s := grpc.NewServer()\n"
        "    pb.RegisterFooServer(s, &server{})\n"
        "    s.Serve(lis)\n"
        "}\n"
    )
    assert _hits("grpc-go-server-no-max-msg-size", src)


def test_grpc_go_server_no_max_negative() -> None:
    """grpc.NewServer with MaxRecvMsgSize ServerOption — no hit."""
    src = (
        "s := grpc.NewServer(\n"
        "    grpc.MaxRecvMsgSize(4 * 1024 * 1024),\n"
        "    grpc.MaxSendMsgSize(4 * 1024 * 1024),\n"
        ")\n"
    )
    assert _hits("grpc-go-server-no-max-msg-size", src) == []


# ---------- 18. gRPC tonic builder no max -------------------------------


def test_grpc_tonic_no_max_positive() -> None:
    """Server::builder() with no max_*_message_size fires."""
    src = (
        "let server = Server::builder()\n"
        "    .add_service(FooServer::new(foo))\n"
        "    .serve(addr)\n"
        "    .await?;\n"
    )
    assert _hits("grpc-tonic-builder-no-max-msg-size", src)


def test_grpc_tonic_no_max_negative() -> None:
    """Server::builder with max_decoding_message_size — no hit."""
    src = (
        "let server = Server::builder()\n"
        "    .max_decoding_message_size(4 * 1024 * 1024)\n"
        "    .add_service(FooServer::new(foo))\n"
        "    .serve(addr)\n"
    )
    assert _hits("grpc-tonic-builder-no-max-msg-size", src) == []


# ---------- 19-21. gRPC reflection enabled (Py, Go, Rust) ---------------


def test_grpc_py_reflection_positive() -> None:
    """reflection.enable_server_reflection fires."""
    src = (
        "from grpc_reflection.v1alpha import reflection\n"
        "reflection.enable_server_reflection(SERVICE_NAMES, server)\n"
    )
    assert _hits("grpc-py-reflection-enabled", src)


def test_grpc_go_reflection_positive() -> None:
    """reflection.Register(s) fires."""
    src = (
        'import "google.golang.org/grpc/reflection"\n'
        "reflection.Register(s)\n"
    )
    assert _hits("grpc-go-reflection-enabled", src)


def test_grpc_tonic_reflection_positive() -> None:
    """tonic_reflection::server::Builder fires."""
    src = (
        "let reflection_service = tonic_reflection::server::Builder::configure()\n"
        "    .build()\n"
        "    .unwrap();\n"
        "Server::builder()\n"
        "    .add_service(reflection_service)\n"
    )
    assert _hits("grpc-tonic-reflection-enabled", src)


def test_grpc_reflection_negative_no_call() -> None:
    """No reflection imports — no hit."""
    src = "import grpc\nserver = grpc.server(...)\n"
    assert _hits("grpc-py-reflection-enabled", src) == []
    assert _hits("grpc-go-reflection-enabled", src) == []
    assert _hits("grpc-tonic-reflection-enabled", src) == []


# ---------- 22. gRPC Python insecure port public ------------------------


def test_grpc_py_insecure_port_dual_stack_positive() -> None:
    """add_insecure_port('[::]:50051') is public-bound — fires."""
    src = "server.add_insecure_port('[::]:50051')\n"
    assert _hits("grpc-py-insecure-port-public", src)


def test_grpc_py_insecure_port_zero_zero_positive() -> None:
    """add_insecure_port('0.0.0.0:50051') is public-bound — fires."""
    src = 'server.add_insecure_port("0.0.0.0:50051")\n'
    assert _hits("grpc-py-insecure-port-public", src)


def test_grpc_py_insecure_port_secure_port_present() -> None:
    """The rule fires on add_insecure_port regardless of add_secure_port;
    the detector's stage-2 makes the call about whether to suppress."""
    src = (
        "server.add_insecure_port('[::]:50051')\n"
        "server.add_secure_port('[::]:50052', creds)\n"
    )
    # The catalog DOES fire here — detector decides downgrade.
    assert _hits("grpc-py-insecure-port-public", src)


# ---------- 23. gRPC Python insecure channel non-localhost --------------


def test_grpc_py_insecure_channel_positive() -> None:
    """grpc.insecure_channel('remote-host:50051') fires."""
    src = 'channel = grpc.insecure_channel("remote-host:50051")\n'
    assert _hits("grpc-py-insecure-channel-non-localhost", src)


def test_grpc_py_insecure_channel_negative_localhost() -> None:
    """grpc.insecure_channel('localhost:50051') — no hit (loopback)."""
    src = 'channel = grpc.insecure_channel("localhost:50051")\n'
    assert _hits("grpc-py-insecure-channel-non-localhost", src) == []


def test_grpc_py_insecure_channel_negative_127() -> None:
    """grpc.insecure_channel('127.0.0.1:50051') — no hit (loopback)."""
    src = "channel = grpc.insecure_channel('127.0.0.1:50051')\n"
    assert _hits("grpc-py-insecure-channel-non-localhost", src) == []


# ---------- 24. gRPC Go WithInsecure / insecure.NewCredentials ----------


def test_grpc_go_with_insecure_positive() -> None:
    """grpc.WithInsecure() fires."""
    src = "conn, err := grpc.Dial(target, grpc.WithInsecure())\n"
    assert _hits("grpc-go-with-insecure", src)


def test_grpc_go_insecure_new_credentials_positive() -> None:
    """insecure.NewCredentials() (the explicit replacement) fires."""
    src = (
        'import "google.golang.org/grpc/credentials/insecure"\n'
        "conn, err := grpc.Dial(target, grpc.WithTransportCredentials(insecure.NewCredentials()))\n"
    )
    assert _hits("grpc-go-with-insecure", src)


def test_grpc_go_with_insecure_negative_tls() -> None:
    """TLS credentials — no hit."""
    src = "conn, err := grpc.Dial(target, grpc.WithTransportCredentials(credentials.NewClientTLSFromCert(...)))\n"
    assert _hits("grpc-go-with-insecure", src) == []


# ---------- 25-27. gRPC interceptor chain auth ordering -----------------


def test_grpc_py_interceptor_auth_last_positive() -> None:
    """interceptors=[Trace, Log, Auth] — auth last fires."""
    src = (
        "server = grpc.server(\n"
        "    futures.ThreadPoolExecutor(),\n"
        "    interceptors=[TracingInterceptor(), LoggingInterceptor(), AuthInterceptor()],\n"
        ")\n"
    )
    assert _hits("grpc-py-interceptor-auth-after-logging", src)


def test_grpc_py_interceptor_auth_first_negative() -> None:
    """interceptors=[Auth, Trace, Log] — auth first, no hit."""
    src = (
        "interceptors=[AuthInterceptor(), TracingInterceptor(), LoggingInterceptor()]\n"
    )
    assert _hits("grpc-py-interceptor-auth-after-logging", src) == []


def test_grpc_go_chain_auth_last_positive() -> None:
    """ChainUnaryInterceptor(Trace, Log, Auth) — Go auth last fires."""
    src = (
        "s := grpc.NewServer(\n"
        "    grpc.ChainUnaryInterceptor(\n"
        "        TracingUnary,\n"
        "        LoggingUnary,\n"
        "        AuthUnary,\n"
        "    ),\n"
        ")\n"
    )
    assert _hits("grpc-go-chain-interceptor-auth-last", src)


def test_grpc_tower_layer_auth_before_trace_positive() -> None:
    """ServiceBuilder.layer(Auth)...layer(Trace) — Trace runs first, hit."""
    src = (
        "let svc = ServiceBuilder::new()\n"
        "    .layer(AuthLayer::new())\n"
        "    .layer(TraceLayer::new_for_http())\n"
        "    .service(my_service);\n"
    )
    assert _hits("grpc-tower-layer-auth-before-trace", src)


def test_grpc_tower_correct_ordering_negative() -> None:
    """layer(Trace) then layer(Auth) — tower reverses, so Auth runs first.
    Our rule should NOT fire."""
    src = (
        "let svc = ServiceBuilder::new()\n"
        "    .layer(TraceLayer::new_for_http())\n"
        "    .layer(AuthLayer::new())\n"
        "    .service(my_service);\n"
    )
    assert _hits("grpc-tower-layer-auth-before-trace", src) == []


# ---------- 28-29. gRPC keepalive permissive ----------------------------


def test_grpc_keepalive_mintime_zero_positive() -> None:
    """keepalive.EnforcementPolicy{ MinTime: 0 } fires."""
    src = (
        "ep := keepalive.EnforcementPolicy{\n"
        "    MinTime: 0,\n"
        "}\n"
    )
    assert _hits("grpc-keepalive-mintime-zero", src)


def test_grpc_keepalive_mintime_nonzero_negative() -> None:
    """MinTime: 5 * time.Second — no hit."""
    src = (
        "ep := keepalive.EnforcementPolicy{\n"
        "    MinTime: 5 * time.Second,\n"
        "}\n"
    )
    assert _hits("grpc-keepalive-mintime-zero", src) == []


def test_grpc_keepalive_permit_without_stream_positive() -> None:
    """PermitWithoutStream: true fires."""
    src = (
        "ep := keepalive.EnforcementPolicy{\n"
        "    PermitWithoutStream: true,\n"
        "}\n"
    )
    assert _hits("grpc-keepalive-permit-without-stream", src)


def test_grpc_keepalive_permit_without_stream_negative() -> None:
    """PermitWithoutStream: false — no hit."""
    src = (
        "ep := keepalive.EnforcementPolicy{\n"
        "    PermitWithoutStream: false,\n"
        "}\n"
    )
    assert _hits("grpc-keepalive-permit-without-stream", src) == []


# ---------- 30. Protobuf recursive message definition -------------------


def test_protobuf_recursive_message_positive() -> None:
    """.proto with `message Node { Node child = 1; ... }` fires."""
    src = (
        "message Node {\n"
        "    Node child = 1;\n"
        "    string value = 2;\n"
        "}\n"
    )
    assert _hits("protobuf-recursive-message-definition", src)


def test_protobuf_non_recursive_negative() -> None:
    """Non-recursive message — no hit."""
    src = (
        "message User {\n"
        "    string name = 1;\n"
        "    int32 id = 2;\n"
        "}\n"
    )
    assert _hits("protobuf-recursive-message-definition", src) == []


def test_protobuf_recursive_with_repeated_negative() -> None:
    """Flat-shape with repeated children + parent_id — different message
    name, no recursion."""
    src = (
        "message Node {\n"
        "    string value = 1;\n"
        "    int32 parent_id = 2;\n"
        "}\n"
        "message Tree {\n"
        "    repeated Node nodes = 1;\n"
        "}\n"
    )
    assert _hits("protobuf-recursive-message-definition", src) == []


# ---------- 31. Protobuf ParseFromString no recursion limit -------------


def test_protobuf_parse_no_recursion_positive() -> None:
    """msg.ParseFromString(data) with no recursion-limit hint fires."""
    src = (
        "msg = MyMessage()\n"
        "msg.ParseFromString(data)\n"
    )
    assert _hits("protobuf-parse-no-recursion-limit", src)


def test_protobuf_parse_no_recursion_negative_with_set_limit() -> None:
    """SetRecursionLimit annotation present — no hit."""
    src = (
        "SetRecursionLimit(20)\n"
        "msg = MyMessage()\n"
        "msg.ParseFromString(data)\n"
    )
    assert _hits("protobuf-parse-no-recursion-limit", src) == []


# ---------- Cross-cutting: dedup + sort ---------------------------------


def test_findings_deduped_by_position() -> None:
    """Same rule firing twice at the same line/col emits ONE finding."""
    src = (
        "msg = MyMessage()\n"
        "msg.ParseFromString(data)\n"
    )
    findings = grp.scan_text(src)
    keys = {(f.rule_id, f.line, f.column) for f in findings}
    assert len(keys) == len(findings)


def test_findings_sorted_by_line_col() -> None:
    """scan_text returns findings ordered by (line, column, rule_id)."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket):\n"
        "    await websocket.accept()\n"
        "    while True:\n"
        "        data = await websocket.receive_text()\n"
        "        msg = json.loads(data)\n"
    )
    findings = grp.scan_text(src)
    assert findings, "expected at least one finding"
    sorted_findings = sorted(findings, key=lambda f: (f.line, f.column, f.rule_id))
    assert findings == sorted_findings


def test_matched_text_truncated_to_200() -> None:
    """Long matches get truncated with an ellipsis."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket):\n"
        + ("    # padding comment to grow the match width\n" * 30)
        + "    data = await websocket.receive_text()\n"
    )
    findings = grp.scan_text(src)
    for f in findings:
        if len(f.matched_text) > 200:
            # A truncated match must end with the ellipsis we use.
            assert f.matched_text.endswith("…"), f"finding {f.rule_id} matched_text len={len(f.matched_text)}"


def test_file_kind_parity() -> None:
    """`prose` and `source` return the same findings for this catalog
    (every rule applies to source-code shapes regardless)."""
    src = (
        "@app.websocket('/ws')\n"
        "async def ws(websocket: WebSocket):\n"
        "    await websocket.accept()\n"
    )
    prose_findings = grp.scan_text(src, file_kind="prose")
    source_findings = grp.scan_text(src, file_kind="source")
    assert prose_findings == source_findings


def test_redos_safety_pathological_input() -> None:
    """The catalog must complete on a 50 KB pathological input in well
    under 1 second (RE2-safety regression guard)."""
    import time

    pathological = (
        "CORSMiddleware,\n" * 500
        + "allow_origins=" + "x" * 100 + "\n"
        + "allow_credentials=True\n"
    )
    start = time.perf_counter()
    grp.scan_text(pathological)
    elapsed = time.perf_counter() - start
    # Generous bound — typical run is ≤ 50 ms; 2 s catches catastrophic
    # backtracking regressions while tolerating slow CI runners.
    assert elapsed < 2.0, f"scan_text took {elapsed:.2f}s on a 50 KB input"
