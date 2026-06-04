"""Istio mTLS / PeerAuthentication bypass patterns.

Wave-37 distillation round 23 — k8s/service-mesh group.

Orthogonal to `scripts/lib/service_mesh_patterns.py`. That module already
covers the *top-level* PeerAuthentication `mode: PERMISSIVE`, the broad
AuthorizationPolicy allow-all (no `rules:`), the Sidecar
OutboundTrafficPolicy `ALLOW_ANY`, and RequestAuthentication with no
`audiences:` key. This module focuses on the *deeper* mTLS-stripping
surface that module does NOT touch:

  * port-level mTLS `DISABLE` (a single port punched through an
    otherwise-STRICT PeerAuthentication),
  * DestinationRule `trafficPolicy.tls.mode: DISABLE` (east-west mTLS
    stripped on the client side),
  * Gateway `tls.mode: SIMPLE` (server-only TLS, no client cert,
    downgrade-able),
  * VirtualService CORS `allowOrigins` wildcard (browser CSRF on
    internal APIs),
  * EnvoyFilter inserting an `envoy.filters.http.lua` filter (runtime
    code injection in every sidecar),
  * WorkloadEntry without a `serviceAccount` (no verifiable SPIFFE id),
  * Sidecar egress `hosts: ["*/*"]` (namespace-isolation bypass),
  * AuthorizationPolicy `action: ALLOW` with no `from:` clause
    (universal access — narrower than the service_mesh allow-all rule),
  * RequestAuthentication with an EMPTY `audiences: []` array (distinct
    from the missing-key case service_mesh already flags).

All rule ids are `istio-mtls-*` prefixed — zero overlap with the
`mesh-istio-*` ids in `service_mesh_patterns.py`.

Reference proposal: `reports/distill-round-23/istio-mtls.md`.

Rule inventory (9 rules):

  1.  istio-mtls-portlevel-disable                 (HIGH)
  2.  istio-mtls-destinationrule-tls-disable       (HIGH)
  3.  istio-mtls-gateway-tls-simple                (HIGH)
  4.  istio-mtls-virtualservice-cors-wildcard      (MEDIUM)
  5.  istio-mtls-envoyfilter-lua                    (CRITICAL)
  6.  istio-mtls-workloadentry-no-serviceaccount    (MEDIUM)
  7.  istio-mtls-sidecar-egress-wildcard            (MEDIUM)
  8.  istio-mtls-authzpolicy-allow-no-from          (CRITICAL)
  9.  istio-mtls-requestauth-empty-audiences        (HIGH)

Public surface mirrors sibling modules:

  * Finding / Rule NamedTuples, RULES tuple,
    scan_text(text, *, file_kind="auto", file_path="") -> list[Finding],
    scan_k8s(text, *, file_path="") -> list[Finding].

OWASP ASI mapping:
  ASI-05 — Supply-chain / cross-tenant pivot (EnvoyFilter Lua injection,
                                              egress wildcard).
  ASI-07 — Authority / authorisation gaps    (mTLS strip, allow-no-from,
                                              empty audiences, SIMPLE
                                              gateway, CORS wildcard,
                                              WorkloadEntry no SA).
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as the sibling pattern modules."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """Static rule metadata."""

    id: str
    name: str
    severity: str
    description: str
    owasp_asi: str


def _re(pattern: str) -> re.Pattern[str]:
    """Compile a pattern with IGNORECASE.

    RE2-safe: bounded quantifiers, no backreferences, no lookaround.
    `(?s)` dot-all is applied inline per multi-line pattern.
    """
    return re.compile(pattern, re.IGNORECASE)


# ---- Rule metadata ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="istio-mtls-portlevel-disable",
        name="PeerAuthentication portLevelMtls mode: DISABLE",
        severity="HIGH",
        description=(
            "A port-level override disables mTLS on a single port while "
            "the top-level policy still looks STRICT. Traffic to that "
            "port is plain-text with no peer-certificate requirement."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="istio-mtls-destinationrule-tls-disable",
        name="DestinationRule trafficPolicy.tls.mode: DISABLE",
        severity="HIGH",
        description=(
            "A DestinationRule with tls.mode: DISABLE tells the sidecar "
            "to send plain-text to the upstream even if it has a valid "
            "cert — silently stripping mTLS on the east-west path."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="istio-mtls-gateway-tls-simple",
        name="Gateway tls.mode: SIMPLE",
        severity="HIGH",
        description=(
            "tls.mode: SIMPLE configures server-side TLS only (no mutual "
            "TLS). Any client can connect without a certificate; combined "
            "with no minProtocolVersion a downgrade to TLS 1.0/1.1 is "
            "possible."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="istio-mtls-virtualservice-cors-wildcard",
        name="VirtualService CORS allowOrigins wildcard",
        severity="MEDIUM",
        description=(
            "A wildcard CORS origin on an internal VirtualService allows "
            "an attacker-controlled page to make cross-origin requests to "
            "internal APIs, bypassing browser same-origin protection."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="istio-mtls-envoyfilter-lua",
        name="EnvoyFilter inserting an HTTP Lua filter",
        severity="CRITICAL",
        description=(
            "An EnvoyFilter adding envoy.filters.http.lua injects "
            "arbitrary Lua into every sidecar — runtime code injection "
            "across the mesh, especially when it references an external "
            "URL or dofile/loadfile/io.open."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="istio-mtls-workloadentry-no-serviceaccount",
        name="WorkloadEntry without serviceAccount",
        severity="MEDIUM",
        description=(
            "A WorkloadEntry with no serviceAccount registers a VM or "
            "external endpoint with no verifiable SPIFFE identity — "
            "AuthorizationPolicy principals do not scope correctly and "
            "audit trails are blind to it."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="istio-mtls-sidecar-egress-wildcard",
        name="Sidecar egress hosts: [\"*/*\"]",
        severity="MEDIUM",
        description=(
            "A Sidecar egress hosts: [\"*/*\"] lets the workload reach "
            "any service in any namespace, defeating namespace isolation "
            "and enabling a compromised pod to enumerate internal "
            "services."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="istio-mtls-authzpolicy-allow-no-from",
        name="AuthorizationPolicy action: ALLOW with no from:",
        severity="CRITICAL",
        description=(
            "An AuthorizationPolicy with action: ALLOW and no from: "
            "clause matches all traffic from all sources — effectively a "
            "no-op that grants universal access."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="istio-mtls-requestauth-empty-audiences",
        name="RequestAuthentication empty audiences: []",
        severity="HIGH",
        description=(
            "An empty audiences: [] array accepts the issuer's tokens "
            "regardless of the audience claim — any valid token minted "
            "for a different service satisfies the check."
        ),
        owasp_asi="ASI-07",
    ),
)


# ---- Regex constants (RE2-safe, bounded — N <= 600 per proposal) --------


# Rule 1 — portLevelMtls block containing mode: DISABLE.
_PORTLEVEL_DISABLE = _re(
    r"(?s)portLevelMtls:\s*.{0,200}?mode:\s*DISABLE\b"
)

# Rule 2 — DestinationRule (or nested trafficPolicy) tls mode: DISABLE.
_DESTRULE_TLS_DISABLE = _re(
    r"(?s)kind:\s*DestinationRule\b.{0,500}?tls:\s*[\r\n\s]{0,40}mode:\s*DISABLE\b"
)
_TRAFFICPOLICY_TLS_DISABLE = _re(
    r"(?s)trafficPolicy:\s*.{0,200}?tls:\s*[\r\n\s]{0,40}mode:\s*DISABLE\b"
)

# Rule 3 — Gateway with tls.mode: SIMPLE.
_GATEWAY_TLS_SIMPLE = _re(
    r"(?s)kind:\s*Gateway\b.{0,400}?mode:\s*SIMPLE\b"
)

# Rule 4 — VirtualService CORS allowOrigins wildcard.
_VS_CORS_WILDCARD = _re(
    r"(?s)kind:\s*VirtualService\b.{0,600}?"
    r"allowOrigins:\s*.{0,100}?-\s*(?:exact|prefix|regex):\s*[\"']\*[\"']"
)
# Inline / non-VS-anchored exact-wildcard fallback.
_CORS_EXACT_WILDCARD = _re(
    r"allowOrigins:\s*[\r\n\s]{0,40}-\s*exact:\s*[\"']\*[\"']"
)

# Rule 5 — EnvoyFilter adding a Lua HTTP filter (any source) + risky-source.
_ENVOYFILTER_LUA = _re(
    r"(?s)kind:\s*EnvoyFilter\b.{0,600}?envoy\.filters\.http\.lua"
)

# Rule 7 — Sidecar egress hosts: ["*/*"] (block or inline array).
_SIDECAR_EGRESS_WILDCARD = _re(
    r"(?s)kind:\s*Sidecar\b.{0,400}?hosts:\s*[\r\n\s]{0,20}-\s*[\"']\*/\*[\"']"
)
_HOSTS_INLINE_WILDCARD = _re(
    r"hosts:\s*\[[^\]]{0,200}[\"']\*/\*[\"'][^\]]{0,200}\]"
)

# Rule 9 — RequestAuthentication with an empty audiences: [] array.
_EMPTY_AUDIENCES = _re(
    r"audiences:\s*\[\s*\]"
)

# Anchors used by two-pass rules.
_AUTHZPOLICY_ALLOW = _re(
    r"(?s)kind:\s*AuthorizationPolicy\b.{0,500}?action:\s*ALLOW\b"
)
_WORKLOADENTRY = _re(
    r"(?s)kind:\s*WorkloadEntry\b"
)

_DOC_SPLIT = re.compile(r"^---\s*$", re.MULTILINE)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert string offset → (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _trunc(s: str, n: int = 200) -> str:
    """Truncate matched_text for reporting."""
    return s if len(s) <= n else s[:n] + "…"


def _rule(rule_id: str) -> Rule:
    """Lookup a Rule by id. Raises KeyError if missing (programmer error)."""
    for r in RULES:
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def _emit(
    rule_id: str,
    text: str,
    match: re.Match[str],
    findings: list[Finding],
    *,
    severity: str | None = None,
) -> None:
    """Append a Finding for `match` using `rule_id`'s metadata."""
    rule = _rule(rule_id)
    line, col = _line_col(text, match.start())
    findings.append(
        Finding(
            rule_id=rule_id,
            line=line,
            column=col,
            matched_text=_trunc(match.group(0)),
            severity=severity or rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )
    )


def _docs_with_offsets(text: str) -> list[tuple[int, str]]:
    """Split a multi-doc YAML stream into (absolute_offset, doc_text).

    The two-pass absence rules (ALLOW-no-from, WorkloadEntry-no-SA) must
    scope the absence check to the SINGLE document the anchor lives in —
    otherwise a `from:` in a neighbouring doc would mask a real finding.
    """
    docs: list[tuple[int, str]] = []
    last = 0
    for m in _DOC_SPLIT.finditer(text):
        docs.append((last, text[last : m.start()]))
        last = m.end()
    docs.append((last, text[last:]))
    return docs


# ---- Scanners -----------------------------------------------------------


def _scan_simple(
    text: str,
    findings: list[Finding],
    rule_id: str,
    pattern: re.Pattern[str],
) -> None:
    """Emit one Finding per non-overlapping match of `pattern`."""
    for m in pattern.finditer(text):
        _emit(rule_id, text, m, findings)


def _scan_portlevel_disable(text: str, findings: list[Finding]) -> None:
    """Rule 1 — portLevelMtls mode: DISABLE."""
    _scan_simple(text, findings, "istio-mtls-portlevel-disable", _PORTLEVEL_DISABLE)


def _scan_destrule_tls_disable(text: str, findings: list[Finding]) -> None:
    """Rule 2 — DestinationRule / trafficPolicy tls mode: DISABLE."""
    m = _DESTRULE_TLS_DISABLE.search(text)
    if m is not None:
        _emit("istio-mtls-destinationrule-tls-disable", text, m, findings)
        return
    m2 = _TRAFFICPOLICY_TLS_DISABLE.search(text)
    if m2 is not None and re.search(r"(?i)kind:\s*DestinationRule\b", text):
        _emit("istio-mtls-destinationrule-tls-disable", text, m2, findings)


def _scan_gateway_tls_simple(text: str, findings: list[Finding]) -> None:
    """Rule 3 — Gateway tls.mode: SIMPLE."""
    _scan_simple(text, findings, "istio-mtls-gateway-tls-simple", _GATEWAY_TLS_SIMPLE)


def _scan_cors_wildcard(text: str, findings: list[Finding]) -> None:
    """Rule 4 — VirtualService CORS allowOrigins wildcard."""
    m = _VS_CORS_WILDCARD.search(text)
    if m is not None:
        _emit("istio-mtls-virtualservice-cors-wildcard", text, m, findings)
        return
    if re.search(r"(?i)kind:\s*VirtualService\b", text):
        m2 = _CORS_EXACT_WILDCARD.search(text)
        if m2 is not None:
            _emit("istio-mtls-virtualservice-cors-wildcard", text, m2, findings)


def _scan_envoyfilter_lua(text: str, findings: list[Finding]) -> None:
    """Rule 5 — EnvoyFilter inserting a Lua HTTP filter."""
    _scan_simple(text, findings, "istio-mtls-envoyfilter-lua", _ENVOYFILTER_LUA)


def _scan_workloadentry_no_sa(text: str, findings: list[Finding]) -> None:
    """Rule 6 — WorkloadEntry without serviceAccount (per-doc absence)."""
    for offset, doc in _docs_with_offsets(text):
        m = _WORKLOADENTRY.search(doc)
        if m is None:
            continue
        if re.search(r"(?i)^\s*serviceAccount:\s*\S", doc, re.MULTILINE):
            continue
        # Re-anchor the match offset into the full-text coordinate space.
        abs_match = _WORKLOADENTRY.search(text, offset)
        anchor = abs_match if abs_match is not None else m
        _emit("istio-mtls-workloadentry-no-serviceaccount", text, anchor, findings)


def _scan_sidecar_egress_wildcard(text: str, findings: list[Finding]) -> None:
    """Rule 7 — Sidecar egress hosts: [\"*/*\"]."""
    m = _SIDECAR_EGRESS_WILDCARD.search(text)
    if m is not None:
        _emit("istio-mtls-sidecar-egress-wildcard", text, m, findings)
        return
    if re.search(r"(?i)kind:\s*Sidecar\b", text):
        m2 = _HOSTS_INLINE_WILDCARD.search(text)
        if m2 is not None:
            _emit("istio-mtls-sidecar-egress-wildcard", text, m2, findings)


def _scan_authzpolicy_allow_no_from(text: str, findings: list[Finding]) -> None:
    """Rule 8 — AuthorizationPolicy ALLOW with no from: (per-doc absence)."""
    for offset, doc in _docs_with_offsets(text):
        m = _AUTHZPOLICY_ALLOW.search(doc)
        if m is None:
            continue
        # Two-pass: the doc must NOT contain a `from:` clause anywhere.
        if re.search(r"(?im)^\s*-?\s*from:", doc):
            continue
        abs_match = _AUTHZPOLICY_ALLOW.search(text, offset)
        anchor = abs_match if abs_match is not None else m
        _emit("istio-mtls-authzpolicy-allow-no-from", text, anchor, findings)


def _scan_empty_audiences(text: str, findings: list[Finding]) -> None:
    """Rule 9 — RequestAuthentication empty audiences: []."""
    if not re.search(r"(?i)kind:\s*RequestAuthentication\b", text):
        return
    _scan_simple(text, findings, "istio-mtls-requestauth-empty-audiences", _EMPTY_AUDIENCES)


_SCANNERS: tuple[Callable[[str, list[Finding]], None], ...] = (
    _scan_portlevel_disable,
    _scan_destrule_tls_disable,
    _scan_gateway_tls_simple,
    _scan_cors_wildcard,
    _scan_envoyfilter_lua,
    _scan_workloadentry_no_sa,
    _scan_sidecar_egress_wildcard,
    _scan_authzpolicy_allow_no_from,
    _scan_empty_audiences,
)


def scan_k8s(text: str, *, file_path: str = "") -> list[Finding]:
    """Apply every Istio-mTLS rule to a K8s/Istio YAML manifest."""
    _ = file_path
    findings: list[Finding] = []
    for scan in _SCANNERS:
        scan(text, findings)
    return findings


def scan_text(
    text: str,
    *,
    file_kind: str = "auto",
    file_path: str = "",
) -> list[Finding]:
    """Top-level dispatcher.

    file_kind: "auto" or "k8s" (the only meaningful kind). Findings come
    out sorted by (line, column, rule_id) and deduped on
    (rule_id, line, column, matched_text).
    """
    if not text:
        return []
    _ = file_kind
    findings = scan_k8s(text, file_path=file_path)

    seen: set[tuple[str, int, int, str]] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = (f.rule_id, f.line, f.column, f.matched_text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    deduped.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return deduped
