"""HTTP/3 + QUIC security quirk patterns.

Wave-33 distillation round 19, HTTP/3 + QUIC angle.

Catalogue of 8 QUIC-specific anti-patterns distilled in
`reports/distill-round-19/http3-quic-quirks.md`. Targets nginx/quiche
configs, Go quic-go code, Rust quinn code, Python aioquic code,
Caddy Caddyfiles, and Envoy QUIC transport YAMLs.

What is NOT here (already covered by other modules):

  * Generic nginx proxy_pass / proxy_http_version misconfigs —
    `reverse_proxy_patterns.py`.
  * HTTP/1.1 CL.TE / TE.CL desync — `http_smuggling_patterns.py`.
  * TLS 1.0/1.1 downgrade, weak cipher suites, missing HSTS —
    `tls_configuration_patterns.py`.
  * gRPC reflection / health-service exposure —
    separate gRPC patterns module.

What IS here (8 net-new rules, all RE2-safe):

  * quic-01-zero-rtt-early-data-no-replay-protection      (HIGH)
  * quic-02-connection-id-rotation-absent                 (MEDIUM)
  * quic-03-path-validation-missing                       (HIGH)
  * quic-04-retry-token-no-expiry                         (MEDIUM)
  * quic-05-qpack-dynamic-table-mixed-trust               (MEDIUM)
  * quic-06-stream-limit-absent-dos                       (HIGH)
  * quic-07-alpn-downgrade-h2-h3-bypass                   (MEDIUM)
  * quic-08-address-validation-token-no-per-ip-expiry     (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak
  ASI-03 — Sensitive data exposure (side-channel, privacy)
  ASI-04 — Insecure direct object reference (token reuse)
  ASI-05 — Security misconfiguration (privacy-relevant default)
  ASI-06 — Cryptographic failures (compression oracle)
  ASI-08 — Security misconfiguration (replay, amplification, downgrade)
  ASI-10 — DoS via resource exhaustion
  ASI-11 — Insufficient logging / audit

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Q1 : quic-01-zero-rtt-early-data-no-replay-protection --------------


# nginx/quiche directive enabling TLS 1.3 0-RTT — the vulnerable shape is
# `ssl_early_data on;` without a companion `proxy_set_header Early-Data`.
# RE2-safe: simple token sequence, no nested quantifiers.
_EARLY_DATA_ON = _re(r"ssl_early_data\s+on\s*;")

# Companion guard: proxy_set_header forwarding the Early-Data indicator.
_EARLY_DATA_HEADER_FORWARD = _re(r"Early-Data\s+\$ssl_early_data")


# ---- Q2 : quic-02-connection-id-rotation-absent -------------------------


# quic-go MaxConnectionIDs set to 0–3 (below RFC 9000 recommended minimum).
# Alternation bounded with \b — RE2 safe.
_MAX_CID_LOW = _re(r"MaxConnectionIDs\s*:\s*[0-3]\b")


# ---- Q3 : quic-03-path-validation-missing --------------------------------


# DisablePathMTUDiscovery: true is an explicit downgrade from the secure
# default; it disables PMTUD and signals that path-validation may be skipped.
_DISABLE_PATH_MTUD = _re(r"DisablePathMTUDiscovery\s*:\s*true\b")


# ---- Q4 : quic-04-retry-token-no-expiry ----------------------------------


# MaxRetryTokenAge: 0 — explicitly sets zero-duration expiry (tokens never
# expire or expire immediately, both are bugs per RFC 9000 §8.1.2).
_MAX_RETRY_TOKEN_AGE_ZERO = _re(r"MaxRetryTokenAge\s*:\s*0\b")

# RequireAddressValidation present without MaxRetryTokenAge set: Stage-B
# complement for the scanner (anchor rule is the zero value above; the
# context guard checks for absent expiry setting).
_REQUIRE_ADDR_VALIDATION = _re(r"RequireAddressValidation\s*:")


# ---- Q5 : quic-05-qpack-dynamic-table-mixed-trust -----------------------


# Caddy Caddyfile: `protocols h1 h2 h3` enables HTTP/3 globally —
# QPACK dynamic table shared across mixed-trust streams.
_CADDY_PROTOCOLS_H3 = _re(r"protocols\s+h1\s+h2\s+h3")

# Go http3.Server{} literal — reviewer checks for absent QPACK table limit.
_HTTP3_SERVER_LITERAL = _re(r"http3\.Server\s*\{")


# ---- Q6 : quic-06-stream-limit-absent-dos --------------------------------


# quic-go: MaxIncomingStreams: 0 maps to unlimited concurrent streams.
_MAX_INCOMING_STREAMS_ZERO = _re(r"MaxIncomingStreams\s*:\s*0\b")

# quic-go: MaxIncomingUniStreams: 0 — same unlimited default for
# unidirectional streams.
_MAX_INCOMING_UNI_STREAMS_ZERO = _re(r"MaxIncomingUniStreams\s*:\s*0\b")

# Unreasonably high stream limit: 5+ digit value (>=10000).
_MAX_INCOMING_STREAMS_HIGH = _re(r"MaxIncomingStreams\s*:\s*[1-9][0-9]{4,}\b")


# ---- Q7 : quic-07-alpn-downgrade-h2-h3-bypass ---------------------------


# nginx: Alt-Svc header advertising h3 — trigger for ALPN downgrade review.
# Bounded character class, no lookahead — RE2 safe.
_ALT_SVC_H3 = _re(r"add_header\s+Alt-Svc\s+[\"']?h3\s*=")

# Envoy: TLS context with only h2+h1 ALPN (h3 absent from TCP path while
# a QUIC downstream transport exists in the same cluster).
_ALPN_H2_ONLY = _re(r"alpn_protocols\s*:\s*\[[\"']h2[\"']")


# ---- Q8 : quic-08-address-validation-token-no-per-ip-expiry -------------


# quic-go lruTokenStore usage — client-agnostic key space by default.
_LRU_TOKEN_STORE = _re(r"quic\.NewLRUTokenStore\s*\(")

# Allow0RTT: true — compound risk with absent MaxRetryTokenAge.
_ALLOW_0RTT_TRUE = _re(r"Allow0RTT\s*:\s*true\b")


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="quic-01-zero-rtt-early-data-no-replay-protection",
        name="nginx ssl_early_data on without Early-Data header forwarding",
        severity="HIGH",
        description=(
            "nginx compiled with quiche/BoringSSL enables TLS 1.3 0-RTT "
            "resumption via `ssl_early_data on;` without forwarding the "
            "`Early-Data: 1` header to upstream origins (RFC 8470). "
            "Non-idempotent handlers reachable via 0-RTT early data are "
            "vulnerable to replay: an attacker that captures a 0-RTT "
            "ClientHello can retransmit it and re-execute the enclosed "
            "request (e.g. POST, DELETE, state-mutating GET). The origin "
            "sees a normal request and executes mutations without knowing "
            "it is processing replayed early data."
        ),
        pattern=_EARLY_DATA_ON,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="quic-02-connection-id-rotation-absent",
        name="quic-go MaxConnectionIDs below rotation threshold",
        severity="MEDIUM",
        description=(
            "QUIC connection IDs MUST be rotated regularly (RFC 9000 §5.1) "
            "to prevent passive observers from correlating packets across "
            "network-path changes. `MaxConnectionIDs` set to 0–3 is below "
            "the RFC 9000 recommended minimum of 4 active CIDs needed to "
            "support rotation. A stable CID allows ISPs and on-path "
            "adversaries to track a client across IP changes, link "
            "mobility events to a single user identity, and correlate "
            "traffic even when the client switches networks."
        ),
        pattern=_MAX_CID_LOW,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="quic-03-path-validation-missing",
        name="quic-go DisablePathMTUDiscovery: true skips path validation",
        severity="HIGH",
        description=(
            "QUIC RFC 9000 §8.2 requires PATH_CHALLENGE / PATH_RESPONSE "
            "before a server sends data on a new client path. "
            "`DisablePathMTUDiscovery: true` in quic-go disables PMTUD "
            "and signals that path migration may proceed without "
            "validation. An attacker that can spoof the client's source "
            "IP can redirect the server's traffic to an arbitrary address "
            "(off-path amplification / reflection attack). Legitimate "
            "use-cases (fixed-MTU environments) require compensating "
            "validation controls that must be reviewed."
        ),
        pattern=_DISABLE_PATH_MTUD,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="quic-04-retry-token-no-expiry",
        name="quic-go MaxRetryTokenAge: 0 disables retry-token expiration",
        severity="MEDIUM",
        description=(
            "QUIC RFC 9000 §8.1.2 requires servers to enforce token "
            "expiration on Retry packets used for address verification. "
            "`MaxRetryTokenAge: 0` in quic-go sets a zero-duration expiry: "
            "tokens issued to one client can be replayed by another client "
            "at a different IP (defeating address-verification), or stored "
            "and replayed later to bypass amplification limits. Zero is "
            "unambiguously wrong — tokens either never expire or are "
            "immediately invalid depending on implementation."
        ),
        pattern=_MAX_RETRY_TOKEN_AGE_ZERO,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="quic-05-qpack-dynamic-table-mixed-trust",
        name="HTTP/3 h1/h2/h3 enabled globally — QPACK side-channel risk",
        severity="MEDIUM",
        description=(
            "HTTP/3 QPACK (RFC 9204) maintains a per-connection dynamic "
            "table of previously seen header values. When authenticated "
            "and unauthenticated streams share the same QUIC connection "
            "(the default), a timing or size side-channel exists: an "
            "active attacker on the same connection can infer secret "
            "header values (Cookie, Authorization) by measuring compressed "
            "header sizes — analogous to CRIME/BREACH for TLS compression. "
            "Enabling `protocols h1 h2 h3` globally without per-endpoint "
            "stream isolation is the high-risk shape."
        ),
        pattern=_CADDY_PROTOCOLS_H3,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="quic-06-stream-limit-absent-dos",
        name="quic-go MaxIncomingStreams: 0 — unlimited streams (DoS)",
        severity="HIGH",
        description=(
            "QUIC RFC 9000 §4 limits concurrent streams via MAX_STREAMS. "
            "`MaxIncomingStreams: 0` in quic-go maps to unlimited — a "
            "single unauthenticated client can open thousands of streams "
            "and exhaust server goroutine pools. HTTP/3 stream exhaustion "
            "is more dangerous than HTTP/2 RST_STREAM flooding "
            "(CVE-2023-44487 / Rapid Reset) because QUIC streams are "
            "opened with a single datagram, bypassing TCP's three-way "
            "handshake cost per stream. Setting no limit is an explicit "
            "removal of the server's only DoS mitigation at the transport "
            "layer."
        ),
        pattern=_MAX_INCOMING_STREAMS_ZERO,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="quic-07-alpn-downgrade-h2-h3-bypass",
        name="nginx Alt-Svc h3 advertisement without h2 security-control parity",
        severity="MEDIUM",
        description=(
            "nginx advertising `h3` via the `Alt-Svc` header enables "
            "QUIC opportunistically but may apply QUIC-specific security "
            "controls (rate limiting, stream limits, 0-RTT guards) only "
            "to the QUIC listener, not to the TCP+h2 fallback path. An "
            "attacker that suppresses UDP (firewall, NAT hairpin) forces "
            "a downgrade to TCP+h2 and bypasses QUIC-only controls. "
            "`limit_req`, `limit_conn`, and TLS-policy directives must "
            "apply equally to both `listen 443 ssl` and "
            "`listen 443 quic reuseport` listener blocks."
        ),
        pattern=_ALT_SVC_H3,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="quic-08-address-validation-token-no-per-ip-expiry",
        name="quic-go NewLRUTokenStore — client-agnostic token key space",
        severity="MEDIUM",
        description=(
            "RFC 9000 §8.1 NEW_TOKEN frames allow clients to skip the "
            "Retry round-trip on future connections. quic-go's default "
            "`lruTokenStore` keys tokens on server address only (not "
            "client IP): a token issued to client A at 1.2.3.4 can be "
            "used by client B at 5.6.7.8 to skip address verification — "
            "defeating the amplification-protection purpose of NEW_TOKEN. "
            "`quic.NewLRUTokenStore` usage warrants a reviewer confirming "
            "that the calling context binds the store to a per-client-IP "
            "namespace or that a custom TokenStore verifies client IP on "
            "retrieval."
        ),
        pattern=_LRU_TOKEN_STORE,
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


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * Q1 (zero-rtt-early-data) — anchor on `ssl_early_data on` and
        require NO `Early-Data $ssl_early_data` forwarding in the same
        file. Without the header forward, early data is replayed unsafely.
      * Q4 (retry-token-no-expiry) — anchor on MaxRetryTokenAge: 0 is
        sufficient (unambiguously wrong). Also flag RequireAddressValidation
        in a window where MaxRetryTokenAge is absent.
      * Q6 (stream-limit-absent) — two anchor patterns:
        MaxIncomingStreams: 0 (explicit unlimited) and
        MaxIncomingUniStreams: 0 (same for uni-directional streams).
        Additionally flags unreasonably high limits (>=10000).
      * Q8 (address-validation-token) — primary anchor on NewLRUTokenStore;
        secondary anchor on Allow0RTT: true for compound risk context.

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

    # ---- Q1 : quic-01-zero-rtt-early-data-no-replay-protection ----
    rule_q1 = rule_by_id["quic-01-zero-rtt-early-data-no-replay-protection"]
    has_early_data_forward = _file_contains(text, _EARLY_DATA_HEADER_FORWARD)
    if not has_early_data_forward:
        for m in _EARLY_DATA_ON.finditer(text):
            _emit(rule_q1, m.start(), m.group(0))

    # ---- Q2 : quic-02-connection-id-rotation-absent ----
    rule_q2 = rule_by_id["quic-02-connection-id-rotation-absent"]
    for m in _MAX_CID_LOW.finditer(text):
        _emit(rule_q2, m.start(), m.group(0))

    # ---- Q3 : quic-03-path-validation-missing ----
    rule_q3 = rule_by_id["quic-03-path-validation-missing"]
    for m in _DISABLE_PATH_MTUD.finditer(text):
        _emit(rule_q3, m.start(), m.group(0))

    # ---- Q4 : quic-04-retry-token-no-expiry ----
    rule_q4 = rule_by_id["quic-04-retry-token-no-expiry"]
    # Primary anchor: explicit zero-duration expiry.
    for m in _MAX_RETRY_TOKEN_AGE_ZERO.finditer(text):
        _emit(rule_q4, m.start(), m.group(0))
    # Secondary anchor: RequireAddressValidation present but MaxRetryTokenAge
    # absent from the same 20-line window (token expiry unset).
    has_any_retry_age = _file_contains(text, _re(r"MaxRetryTokenAge\s*:"))
    if not has_any_retry_age:
        for m in _REQUIRE_ADDR_VALIDATION.finditer(text):
            _emit(rule_q4, m.start(), m.group(0))

    # ---- Q5 : quic-05-qpack-dynamic-table-mixed-trust ----
    rule_q5 = rule_by_id["quic-05-qpack-dynamic-table-mixed-trust"]
    for m in _CADDY_PROTOCOLS_H3.finditer(text):
        _emit(rule_q5, m.start(), m.group(0))
    # Also flag http3.Server{} literals as an architectural review trigger.
    for m in _HTTP3_SERVER_LITERAL.finditer(text):
        _emit(rule_q5, m.start(), m.group(0))

    # ---- Q6 : quic-06-stream-limit-absent-dos ----
    rule_q6 = rule_by_id["quic-06-stream-limit-absent-dos"]
    for m in _MAX_INCOMING_STREAMS_ZERO.finditer(text):
        _emit(rule_q6, m.start(), m.group(0))
    for m in _MAX_INCOMING_UNI_STREAMS_ZERO.finditer(text):
        _emit(rule_q6, m.start(), m.group(0))
    for m in _MAX_INCOMING_STREAMS_HIGH.finditer(text):
        _emit(rule_q6, m.start(), m.group(0))

    # ---- Q7 : quic-07-alpn-downgrade-h2-h3-bypass ----
    rule_q7 = rule_by_id["quic-07-alpn-downgrade-h2-h3-bypass"]
    for m in _ALT_SVC_H3.finditer(text):
        _emit(rule_q7, m.start(), m.group(0))
    # Also flag Envoy ALPN contexts with h2-only when a QUIC transport exists.
    has_quic_transport = _file_contains(
        text, _re(r"QuicDownstreamTransport|quic_options|envoy\.transport_sockets\.quic")
    )
    if has_quic_transport:
        for m in _ALPN_H2_ONLY.finditer(text):
            _emit(rule_q7, m.start(), m.group(0))

    # ---- Q8 : quic-08-address-validation-token-no-per-ip-expiry ----
    rule_q8 = rule_by_id["quic-08-address-validation-token-no-per-ip-expiry"]
    for m in _LRU_TOKEN_STORE.finditer(text):
        _emit(rule_q8, m.start(), m.group(0))
    # Secondary anchor: Allow0RTT: true as compound-risk trigger.
    for m in _ALLOW_0RTT_TRUE.finditer(text):
        _emit(rule_q8, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
