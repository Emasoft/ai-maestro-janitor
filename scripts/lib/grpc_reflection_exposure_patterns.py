"""gRPC server-reflection and health-check exposure patterns.

Wave-32 distillation round 18, angle grpc-reflection-exposure.

Catalogue of 10 gRPC-reflection and health-check anti-patterns distilled in
`reports/distill-round-18/grpc-reflection-exposure.md`. Targets Python,
Go, Java, Node.js, Envoy YAML, and Spring Boot gRPC surfaces that the
existing `grpc_rpc_patterns.py` module (Wave-19 / dr5-E) does NOT cover.

What is NOT here (already shipped in grpc_rpc_patterns.py — DO NOT duplicate):

  * `grpc-py-reflection-enabled` — Python reflection.enable_server_reflection(...)
  * `grpc-go-reflection-enabled` — Go reflection.Register(s)
  * `grpc-tonic-reflection-enabled` — Rust tonic_reflection::
  * `grpc-py-insecure-port-public` — Python server.add_insecure_port("[::]:N")
  * `grpc-py-insecure-channel-non-localhost` — Python grpc.insecure_channel(...)
  * `grpc-go-with-insecure` — Go grpc.WithInsecure() / insecure.NewCredentials()
  * `grpc-py-server-no-max-recv-msg-size` / `grpc-go-server-no-max-msg-size`
  * Protobuf recursive message / parse recursion limit

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * grpc-refl-py-health-service-no-auth            (HIGH)
  * grpc-refl-go-health-service-no-auth            (HIGH)
  * grpc-refl-java-insecure-channel-credentials    (HIGH)
  * grpc-refl-java-managed-channel-plaintext       (HIGH)
  * grpc-refl-node-create-insecure-credentials     (HIGH)
  * grpc-refl-envoy-yaml-reflection-filter         (CRITICAL)
  * grpc-refl-spring-grpc-web-filter               (HIGH)
  * grpc-refl-py-streaming-no-deadline             (MEDIUM)
  * grpc-refl-client-proto-reflection-db           (MEDIUM)
  * grpc-refl-client-go-reflection-stub            (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Unrestricted Resource Consumption (streaming no-deadline)
  ASI-05 — Broken Authentication / credential failures
  ASI-08 — Security Misconfiguration (health/reflection exposure)
  ASI-09 — Cryptographic Failures (plaintext channels)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : grpc-refl-py-health-service-no-auth ---------------------------


# Python grpcio-health-checking: add_HealthServicer_to_server registers the
# gRPC health service. Any registration on a non-loopback port without an
# auth interceptor exposes service topology to unauthenticated callers.
_PY_HEALTH_SERVICER_REGISTER = _re(
    r"add_HealthServicer_to_server\s*\("
)


# ---- R2 : grpc-refl-go-health-service-no-auth ---------------------------


# Go google.golang.org/grpc/health/grpc_health_v1: RegisterHealthServer
# registers the health service on a gRPC server. Same topology-leakage
# risk as the Python variant — liveness probe service names reveal the
# internal API surface without requiring reflection.
_GO_HEALTH_SERVER_REGISTER = _re(
    r"grpc_health_v1\.RegisterHealthServer\s*\("
)


# ---- R3 : grpc-refl-java-insecure-channel-credentials ------------------


# Java grpc-java 1.45+: InsecureChannelCredentials.create() is the new
# credential factory that transmits all RPC metadata in plaintext. This
# includes Authorization headers — leaking tokens on the wire.
_JAVA_INSECURE_CHANNEL_CREDENTIALS = _re(
    r"InsecureChannelCredentials\.create\s*\(\s*\)"
)


# ---- R4 : grpc-refl-java-managed-channel-plaintext ----------------------


# Java grpc-java legacy: ManagedChannelBuilder.usePlaintext() forces
# plaintext transport on any channel, including those targeting non-localhost
# addresses. Deprecated in grpc-java 1.45+ but still widespread.
_JAVA_MANAGED_CHANNEL_PLAINTEXT = _re(
    r"ManagedChannelBuilder\b[^;]{0,200}\.usePlaintext\s*\(\s*\)"
)


# ---- R5 : grpc-refl-node-create-insecure-credentials -------------------


# Node.js @grpc/grpc-js: grpc.credentials.createInsecure() creates a
# plaintext channel. Equivalent to Go insecure.NewCredentials() and Python
# grpc.insecure_channel(). Transmits all RPC metadata including Authorization
# headers in cleartext.
_NODE_CREATE_INSECURE_CREDENTIALS = _re(
    r"grpc\.credentials\.createInsecure\s*\(\s*\)"
)


# ---- R6 : grpc-refl-envoy-yaml-reflection-filter -----------------------


# Envoy proxy 1.29+: the grpc_server_reflection HTTP filter wires the gRPC
# Server Reflection service into an Envoy listener. On a public listener
# without a preceding RBAC or JWT authn filter, any caller can fetch the
# complete protobuf FileDescriptorProto set — reconstructing the full
# internal API topology.
_ENVOY_GRPC_REFLECTION_FILTER = _re(
    r"envoy\.filters\.http\.grpc_server_reflection"
)


# ---- R7 : grpc-refl-spring-grpc-web-filter ------------------------------


# Spring Boot grpc-server-spring-boot-starter: GrpcWebFilter enables
# gRPC-Web (browser gRPC over HTTP/1.1). Without a SecurityWebFilterChain
# covering /grpc/**, all gRPC-Web RPCs including ServerReflection and
# Health/Check are reachable from browser JS without authentication.
_SPRING_GRPC_WEB_FILTER = _re(
    r"new\s+GrpcWebFilter\s*\(\s*\)"
)


# ---- R8 : grpc-refl-py-streaming-no-deadline ----------------------------


# Python gRPC server-streaming servicer: a method that accepts (self,
# request, context) and uses yield to stream responses without checking
# context.is_active() or context.time_remaining() will continue producing
# output after client disconnection — exhausting CPU and memory.
# Match: method signature with capital-letter name typical of RPC servicers.
_PY_STREAMING_SERVICER_METHOD = _re(
    r"def\s+[A-Z][A-Za-z0-9_]*\s*\(\s*self\s*,\s*request\s*,\s*context\s*\)\s*:"
)

# Deadline-check guard: presence of context.is_active or time_remaining
# in the same method body suppresses the finding.
_PY_DEADLINE_CHECK_GUARD = _re(
    r"context\.(?:is_active|time_remaining)\s*\("
)


# ---- R9 : grpc-refl-client-proto-reflection-db -------------------------


# Python grpc_reflection client: ProtoReflectionDescriptorDatabase connects
# to a reflection-enabled gRPC server and downloads all FileDescriptorProto
# objects. Its presence in non-test app code confirms reflection is enabled
# on the target server AND introduces descriptor-confusion risk.
_PY_PROTO_REFLECTION_DB = _re(
    r"ProtoReflectionDescriptorDatabase\s*\("
)


# ---- R10 : grpc-refl-client-go-reflection-stub -------------------------


# Go grpc_reflection_v1alpha: NewServerReflectionClient creates a reflection
# client that can enumerate all services and fetch FileDescriptorProto objects
# from a reflection-enabled server. In non-test production code this confirms
# the target server has reflection enabled.
_GO_REFLECTION_CLIENT_STUB = _re(
    r"grpc_reflection_v1alpha\.NewServerReflectionClient\s*\("
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="grpc-refl-py-health-service-no-auth",
        name="Python gRPC Health service registered without auth gate",
        severity="HIGH",
        description=(
            "add_HealthServicer_to_server(...) registers the grpc.health.v1.Health "
            "service on the gRPC server. When registered on the same public listener "
            "as business RPCs with no auth interceptor, any unauthenticated caller can "
            "determine service readiness and enumerate the exact fully-qualified service "
            "names passed to HealthServicer.set() — leaking internal API topology without "
            "requiring reflection. Review the port binding and interceptor chain to confirm "
            "an auth gate precedes this listener."
        ),
        pattern=_PY_HEALTH_SERVICER_REGISTER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="grpc-refl-go-health-service-no-auth",
        name="Go gRPC Health service registered without auth gate",
        severity="HIGH",
        description=(
            "grpc_health_v1.RegisterHealthServer(...) registers the gRPC health service "
            "on the server. The service names set via hs.SetServingStatus() are "
            "protobuf fully-qualified service names — leaking the internal API topology "
            "to any unauthenticated grpc-health-probe caller. Review the gRPC server "
            "interceptor chain to confirm an auth gate is present."
        ),
        pattern=_GO_HEALTH_SERVER_REGISTER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="grpc-refl-java-insecure-channel-credentials",
        name="Java gRPC client uses InsecureChannelCredentials.create()",
        severity="HIGH",
        description=(
            "InsecureChannelCredentials.create() produces a credential that transmits "
            "all RPC metadata — including Authorization: Bearer <token> headers — in "
            "plaintext. This is the grpc-java 1.45+ equivalent of Go insecure.NewCredentials(). "
            "Common in service-mesh 'trust the sidecar' patterns but dangerous when "
            "used without a properly configured mTLS sidecar — all tokens are on the wire."
        ),
        pattern=_JAVA_INSECURE_CHANNEL_CREDENTIALS,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="grpc-refl-java-managed-channel-plaintext",
        name="Java gRPC ManagedChannelBuilder.usePlaintext() forces cleartext transport",
        severity="HIGH",
        description=(
            "ManagedChannelBuilder.usePlaintext() forces plaintext transport on any "
            "channel regardless of the target address. This deprecated method predates "
            "InsecureChannelCredentials and is still widespread in Java service code. "
            "Tokens transmitted via this channel — including Authorization headers — "
            "are exposed in cleartext. Suppress when the forAddress target is localhost "
            "or 127.0.0.1 (integration test usage)."
        ),
        pattern=_JAVA_MANAGED_CHANNEL_PLAINTEXT,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="grpc-refl-node-create-insecure-credentials",
        name="Node.js gRPC client uses grpc.credentials.createInsecure()",
        severity="HIGH",
        description=(
            "grpc.credentials.createInsecure() creates a plaintext @grpc/grpc-js channel. "
            "This is the Node.js equivalent of Go insecure.NewCredentials() and Python "
            "grpc.insecure_channel(). Any Authorization headers sent via this channel — "
            "including bearer tokens — are transmitted in cleartext. The @grpc/grpc-js "
            "library does not restrict target hosts, so a localhost test client promoted "
            "to production silently exposes all tokens."
        ),
        pattern=_NODE_CREATE_INSECURE_CREDENTIALS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-refl-envoy-yaml-reflection-filter",
        name="Envoy YAML: grpc_server_reflection filter on listener (no auth filter before it)",
        severity="CRITICAL",
        description=(
            "The envoy.filters.http.grpc_server_reflection filter wires the gRPC Server "
            "Reflection service into an Envoy listener. On a listener bound to 0.0.0.0 "
            "or a non-loopback address without a preceding RBAC or JWT authn filter, any "
            "network caller can issue ServerReflectionInfo RPCs via grpcdebug or "
            "grpcurl --reflect and receive the complete set of FileDescriptorProto objects "
            "— reconstructing the full internal protobuf schema, all service and method names, "
            "and all message field names. Review that an RBAC or jwt_authn filter appears "
            "before this filter in the http_filters list."
        ),
        pattern=_ENVOY_GRPC_REFLECTION_FILTER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="grpc-refl-spring-grpc-web-filter",
        name="Spring Boot GrpcWebFilter registered without auth filter chain",
        severity="HIGH",
        description=(
            "new GrpcWebFilter() enables gRPC-Web (browser gRPC over HTTP/1.1) in a "
            "Spring Boot application. Without a SecurityWebFilterChain that enforces JWT "
            "or Basic auth on the /grpc/** path prefix, all gRPC-Web RPCs — including "
            "ServerReflection and Health/Check — are reachable from browser JavaScript "
            "without authentication. The grpc-web content-type bypasses many WAF rules "
            "that only inspect REST traffic. Review the SecurityWebFilterChain ordering."
        ),
        pattern=_SPRING_GRPC_WEB_FILTER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="grpc-refl-py-streaming-no-deadline",
        name="Python gRPC server-streaming servicer without context deadline check",
        severity="MEDIUM",
        description=(
            "A Python gRPC server-streaming servicer method (capital-letter name matching "
            "the RPC method convention, accepting self/request/context) uses yield to "
            "stream responses without checking context.is_active() or "
            "context.time_remaining(). The server continues generating output after client "
            "disconnection — exhausting CPU and memory proportional to the data set size. "
            "Attackers can open many concurrent streaming RPCs with zero-byte reads to "
            "amplify server resource consumption. Add context.is_active() or "
            "context.time_remaining() > 0 checks at the top of each yield iteration."
        ),
        pattern=_PY_STREAMING_SERVICER_METHOD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="grpc-refl-client-proto-reflection-db",
        name="App code uses ProtoReflectionDescriptorDatabase (confirms server reflection enabled)",
        severity="MEDIUM",
        description=(
            "ProtoReflectionDescriptorDatabase(...) connects to a gRPC server and downloads "
            "all FileDescriptorProto objects via the reflection API. Its presence in "
            "non-test application code confirms the target server has reflection enabled "
            "AND introduces descriptor-confusion risk if the fetched descriptors are used "
            "for dynamic dispatch. Suppress when the file path contains _test, test_, "
            "spec_, conftest, cmd/debug, tools/, or scripts/."
        ),
        pattern=_PY_PROTO_REFLECTION_DB,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="grpc-refl-client-go-reflection-stub",
        name="App code uses grpc_reflection_v1alpha.NewServerReflectionClient (confirms reflection enabled)",
        severity="MEDIUM",
        description=(
            "grpc_reflection_v1alpha.NewServerReflectionClient(...) creates a Go gRPC "
            "reflection client that can enumerate all services and fetch FileDescriptorProto "
            "objects from a reflection-enabled server. Its presence in production app code "
            "confirms reflection is queryable on the target server. Suppress when the file "
            "path contains _test.go, cmd/debug, tools/, or scripts/."
        ),
        pattern=_GO_REFLECTION_CLIENT_STUB,
        owasp_asi="ASI-08",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])



# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * R8 (grpc-refl-py-streaming-no-deadline) — anchor on the streaming
        servicer method signature (capital-letter method name with
        self/request/context) and require NO context.is_active() or
        context.time_remaining() in a 40-line forward window. Without this
        gate the rule would flag every streaming servicer regardless of
        whether it has a deadline check later in the body.

    All other rules fire on direct regex match (single-stage).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- R1 : grpc-refl-py-health-service-no-auth ----
    rule_r1 = rule_by_id["grpc-refl-py-health-service-no-auth"]
    for m in _PY_HEALTH_SERVICER_REGISTER.finditer(text):
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : grpc-refl-go-health-service-no-auth ----
    rule_r2 = rule_by_id["grpc-refl-go-health-service-no-auth"]
    for m in _GO_HEALTH_SERVER_REGISTER.finditer(text):
        _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : grpc-refl-java-insecure-channel-credentials ----
    rule_r3 = rule_by_id["grpc-refl-java-insecure-channel-credentials"]
    for m in _JAVA_INSECURE_CHANNEL_CREDENTIALS.finditer(text):
        _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : grpc-refl-java-managed-channel-plaintext ----
    rule_r4 = rule_by_id["grpc-refl-java-managed-channel-plaintext"]
    for m in _JAVA_MANAGED_CHANNEL_PLAINTEXT.finditer(text):
        _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : grpc-refl-node-create-insecure-credentials ----
    rule_r5 = rule_by_id["grpc-refl-node-create-insecure-credentials"]
    for m in _NODE_CREATE_INSECURE_CREDENTIALS.finditer(text):
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : grpc-refl-envoy-yaml-reflection-filter ----
    rule_r6 = rule_by_id["grpc-refl-envoy-yaml-reflection-filter"]
    for m in _ENVOY_GRPC_REFLECTION_FILTER.finditer(text):
        _emit(rule_r6, m.start(), m.group(0))

    # ---- R7 : grpc-refl-spring-grpc-web-filter ----
    rule_r7 = rule_by_id["grpc-refl-spring-grpc-web-filter"]
    for m in _SPRING_GRPC_WEB_FILTER.finditer(text):
        _emit(rule_r7, m.start(), m.group(0))

    # ---- R8 : grpc-refl-py-streaming-no-deadline ----
    # Stage-B: only flag if no deadline check appears in the 40-line
    # forward window of the servicer method body.
    rule_r8 = rule_by_id["grpc-refl-py-streaming-no-deadline"]
    for m in _PY_STREAMING_SERVICER_METHOD.finditer(text):
        line, _ = _line_col(text, m.start())
        # Look at the method body (40 lines forward covers large methods).
        window = _slice_forward(text, line, 40)
        # Only emit if there is a yield in the window (server-streaming)
        # and no deadline check.
        if "yield" not in window:
            continue
        if _PY_DEADLINE_CHECK_GUARD.search(window) is not None:
            continue
        _emit(rule_r8, m.start(), m.group(0))

    # ---- R9 : grpc-refl-client-proto-reflection-db ----
    rule_r9 = rule_by_id["grpc-refl-client-proto-reflection-db"]
    for m in _PY_PROTO_REFLECTION_DB.finditer(text):
        _emit(rule_r9, m.start(), m.group(0))

    # ---- R10 : grpc-refl-client-go-reflection-stub ----
    rule_r10 = rule_by_id["grpc-refl-client-go-reflection-stub"]
    for m in _GO_REFLECTION_CLIENT_STUB.finditer(text):
        _emit(rule_r10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
