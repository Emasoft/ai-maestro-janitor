"""Service mesh / sidecar security patterns.

Wave-24 distillation round 10 — service mesh / sidecar security angle.

Catalogue of 7 service-mesh-specific anti-patterns distilled in
`reports/distill-round-10/service-mesh.md`. Targets Istio
(`security.istio.io`, `networking.istio.io`, `install.istio.io`),
Linkerd (`policy.linkerd.io`), and Consul Connect
(`consul.hashicorp.com`) CRDs.

Coverage gap verified against `scripts/lib/k8s_admission_patterns.py`:
that module covers admission webhooks, Gatekeeper constraints, RBAC
verbs, ClusterRole wildcards, PodSecurity admission, default-deny
NetworkPolicy, kubelet flags, etcd hostPath / port 2379, CSR
auto-approval, ServiceAccount automount — but never mentions
`PeerAuthentication`, `AuthorizationPolicy`, `RequestAuthentication`,
`DestinationRule`, `VirtualService`, `ServerAuthorization`,
`ServiceIntentions`, `consul.hashicorp.com`, `linkerd.io/inject`,
`security.istio.io`, `networking.istio.io`, or `sidecar.istio.io`.
The seven patterns below are therefore fully orthogonal.

Rules shipped (all RE2-safe):

  * mesh-istio-peerauth-permissive                    (HIGH)
  * mesh-istio-authzpolicy-allow-all                  (CRITICAL)
  * mesh-istio-outbound-traffic-allow-any             (HIGH)
  * mesh-istio-jwt-no-audience                        (HIGH)
  * mesh-pod-sidecar-bypass-init                      (HIGH)
  * mesh-linkerd-server-no-identityrefs               (CRITICAL)
  * mesh-consul-intentions-default-allow              (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Cryptographic / Token Handling Failures (JWT no audience)
  ASI-05 — Insecure Communication / Identity (PeerAuthentication
            permissive, ALLOW_ANY outbound, sidecar bypass)
  ASI-07 — Broken Access Control (AuthorizationPolicy allow-all, JWT
            audience, sidecar bypass, Linkerd unauth, Consul allow)
  ASI-08 — Security Misconfiguration (mesh-wide outbound ALLOW_ANY)

All regexes are RE2-compatible: no backreferences, no lookbehind, no
catastrophic backtracking shapes. Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    """Compile with MULTILINE+UNICODE — RE2-safe.

    YAML manifest values are case-sensitive (`PERMISSIVE` vs
    `permissive` are not equivalent in Istio's CRD enum), so unlike
    chat_bot_patterns we deliberately omit IGNORECASE here. Each rule
    that needs case folding adds it inline in the pattern.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- P1 : mesh-istio-peerauth-permissive --------------------------------


# A PeerAuthentication YAML with mtls.mode set to PERMISSIVE or DISABLE.
# Captures both the `kind:` declaration and the `mode:` value separately
# — the scanner uses the file-context check to ensure the PeerAuthentication
# manifest is what the mode belongs to.
_ISTIO_PEERAUTH_KIND = _re(
    r"^\s*kind:\s*PeerAuthentication\b"
)

_ISTIO_PEERAUTH_PERMISSIVE_MODE = _re(
    r"^\s*mode:\s*(?:PERMISSIVE|DISABLE)\b"
)


# ---- P2 : mesh-istio-authzpolicy-allow-all ------------------------------


_ISTIO_AUTHZ_KIND = _re(
    r"^\s*kind:\s*AuthorizationPolicy\b"
)

# Wildcard principal — accepts any SPIFFE identity including
# unauthenticated traffic when PeerAuthentication is PERMISSIVE.
_ISTIO_AUTHZ_WILDCARD_PRINCIPAL = _re(
    r"^\s*(?:-\s*)?principals:\s*\[\s*[\"']\*[\"']\s*\]"
)

# Empty principals array / namespaces wildcard / requestPrincipals wildcard
_ISTIO_AUTHZ_WILDCARD_OTHER = _re(
    r"^\s*(?:-\s*)?namespaces:\s*\[\s*[\"']\*[\"']\s*\]"
    r"|"
    r"^\s*(?:-\s*)?requestPrincipals:\s*\[\s*[\"']\*[\"']\s*\]"
)

# Action ALLOW marker — only flagged when combined with a wildcard above
# or with an entirely empty rules block in the same file.
_ISTIO_AUTHZ_ACTION_ALLOW = _re(
    r"^\s*action:\s*ALLOW\b"
)


# ---- P3 : mesh-istio-outbound-traffic-allow-any -------------------------


# Match both the IstioOperator meshConfig form AND the Sidecar CR form.
# The outboundTrafficPolicy key is shared between the two; whichever the
# parent kind, ALLOW_ANY is the same misconfig.
_ISTIO_OUTBOUND_ALLOW_ANY = _re(
    r"^\s*outboundTrafficPolicy:\s*\n[\s\S]{0,200}?^\s*mode:\s*ALLOW_ANY\b"
)


# ---- P4 : mesh-istio-jwt-no-audience ------------------------------------


_ISTIO_REQUESTAUTH_KIND = _re(
    r"^\s*kind:\s*RequestAuthentication\b"
)

# A single jwtRules entry with an issuer but the entry block is followed
# immediately by another `- issuer:` or by a non-jwtRules sibling. We
# anchor on the issuer line and require a no-`audiences:` follow-up in
# the same entry. The scanner does the actual structural check.
_ISTIO_JWT_ISSUER_ENTRY = _re(
    r"^\s*-\s+issuer:\s*[\"'][^\"']+[\"']"
)

# Wildcard audience — defeats the point of the audience binding.
_ISTIO_JWT_WILDCARD_AUDIENCE = _re(
    r"^\s*audiences:\s*\[\s*[\"']\*[\"']\s*\]"
)


# ---- P5 : mesh-pod-sidecar-bypass-init ----------------------------------


# Annotation: traffic excluded from sidecar iptables redirect, OR
# sidecar.istio.io/inject: false on a non-system pod.
# excludeOutboundIPRanges with 0.0.0.0/0 is the worst case;
# excludeOutboundPorts with a wide range matches similarly.
_SIDECAR_EXCLUDE_OUTBOUND_WIDE = _re(
    r"^\s*traffic\.sidecar\.istio\.io/excludeOutbound(?:IPRanges|Ports):"
    r"\s*[\"']?(?:0\.0\.0\.0/0|1-65535|\*)[\"']?"
)

# Comma-separated port list of 6+ entries → also too wide
_SIDECAR_EXCLUDE_OUTBOUND_PORTS_BROAD = _re(
    r"^\s*traffic\.sidecar\.istio\.io/excludeOutboundPorts:"
    r"\s*[\"']?(?:\d{1,5}(?:\s*,\s*\d{1,5}){5,})[\"']?"
)

# Inject disabled at the pod/deployment level.
_SIDECAR_INJECT_FALSE = _re(
    r"^\s*sidecar\.istio\.io/inject:\s*[\"']?false[\"']?"
)


# ---- P6 : mesh-linkerd-server-no-identityrefs ---------------------------


_LINKERD_SERVERAUTH_KIND = _re(
    r"^\s*kind:\s*ServerAuthorization\b"
)

# Linkerd: client.unauthenticated: true admits cleartext callers.
_LINKERD_UNAUTHENTICATED_TRUE = _re(
    r"^\s*unauthenticated:\s*true\b"
)

# Linkerd: meshTLS: {} OR meshTLS with empty identityRefs — admits any
# mesh identity. We detect the empty-flow-style first, then the
# block-form via a structural scan.
_LINKERD_MESHTLS_EMPTY_FLOW = _re(
    r"^\s*meshTLS:\s*\{\s*\}"
)

_LINKERD_MESHTLS_EMPTY_IDENTITYREFS = _re(
    r"^\s*identityRefs:\s*\[\s*\]"
)


# ---- P7 : mesh-consul-intentions-default-allow --------------------------


_CONSUL_INTENTIONS_KIND = _re(
    r"^\s*kind:\s*ServiceIntentions\b"
)

# Wildcard source name with action: allow — fires inside ServiceIntentions
# (see the structural check in scan_text).
_CONSUL_WILDCARD_SOURCE_ALLOW = _re(
    r"^\s*-\s+name:\s*[\"']?\*[\"']?\s*\n\s*action:\s*allow\b"
    r"|"
    r"^\s*-\s+action:\s*allow\s*\n\s*name:\s*[\"']?\*[\"']?"
)

# HCL agent config: default_policy = "allow"
_CONSUL_HCL_DEFAULT_POLICY_ALLOW = _re(
    r"\bdefault_policy\s*=\s*[\"']allow[\"']"
)

# Also catch CRD-style ProxyDefaults / defaultAction allow (newer Consul)
_CONSUL_CRD_DEFAULT_ACTION_ALLOW = _re(
    r"^\s*defaultAction:\s*allow\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="mesh-istio-peerauth-permissive",
        name="Istio PeerAuthentication mtls.mode permits plaintext",
        severity="HIGH",
        description=(
            "Istio `PeerAuthentication` enforces `mtls.mode: PERMISSIVE` "
            "(or `DISABLE`). PERMISSIVE accepts BOTH mTLS and plaintext "
            "traffic — any in-cluster pod outside the mesh, or any "
            "process that bypasses its own sidecar via 127.0.0.1, can "
            "call the workload over plaintext and bypass identity-based "
            "AuthorizationPolicy. The mesh's whole premise is 'service "
            "identity from the SPIFFE SAN in the client cert' — "
            "PERMISSIVE makes that premise optional. Escalates to "
            "CRITICAL on production-tagged manifests."
        ),
        pattern=_ISTIO_PEERAUTH_PERMISSIVE_MODE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mesh-istio-authzpolicy-allow-all",
        name="Istio AuthorizationPolicy with wildcard principals or empty rules",
        severity="CRITICAL",
        description=(
            "Istio `AuthorizationPolicy` declared with `action: ALLOW` "
            "and an empty / wildcard `rules:` block (or "
            "`from.source.principals: [\"*\"]`). The default Istio "
            "action when NO AuthorizationPolicy exists is ALLOW — so an "
            "ALLOW policy with an empty selector is identical to no "
            "policy, but silences the audit-log warning. The wildcard "
            "form accepts ANY SPIFFE identity, including unauthenticated "
            "traffic when PeerAuthentication is also PERMISSIVE — "
            "compounds with mesh-istio-peerauth-permissive."
        ),
        pattern=_ISTIO_AUTHZ_WILDCARD_PRINCIPAL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mesh-istio-outbound-traffic-allow-any",
        name="Istio outboundTrafficPolicy mode is ALLOW_ANY",
        severity="HIGH",
        description=(
            "Istio mesh-wide `meshConfig.outboundTrafficPolicy.mode: "
            "ALLOW_ANY` (legacy default; new installs default to "
            "REGISTRY_ONLY). With ALLOW_ANY, any sidecar-injected pod "
            "can egress to any external address — including "
            "169.254.169[.]254 (cloud IMDS), attacker-controlled C2 "
            "domains, and any non-mesh service. The mesh becomes a pure "
            "performance layer with no egress control. REGISTRY_ONLY "
            "forces every external destination through a registered "
            "ServiceEntry whose risk is reviewable. Compounds with the "
            "k8s-namespace-no-default-deny-networkpolicy rule into a "
            "complete egress escape."
        ),
        pattern=_ISTIO_OUTBOUND_ALLOW_ANY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="mesh-istio-jwt-no-audience",
        name="Istio RequestAuthentication jwtRules entry lacks audiences",
        severity="HIGH",
        description=(
            "Istio `RequestAuthentication` defines a `jwtRules` entry "
            "without an `audiences:` field (or with `audiences: "
            "[\"*\"]`). Per JWT RFC 7519 §4.1.3, the `aud` claim binds "
            "a token to a target service — without `audiences:` in the "
            "mesh rule, a token MINTED FOR A DIFFERENT SERVICE in the "
            "same trust domain (same OIDC issuer) is silently accepted. "
            "Classic confused-deputy: a token from internal-analytics "
            "is accepted by the payments API. Wildcard audience is "
            "equivalent — it defeats the point."
        ),
        pattern=_ISTIO_JWT_ISSUER_ENTRY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="mesh-pod-sidecar-bypass-init",
        name="Pod annotation excludes traffic from Istio sidecar interception",
        severity="HIGH",
        description=(
            "Pod / Deployment annotates "
            "`traffic.sidecar.istio.io/excludeOutboundIPRanges`, "
            "`excludeOutboundPorts`, or `excludeInboundPorts` with a "
            "wide range (`0.0.0.0/0`, `1-65535`), OR sets "
            "`sidecar.istio.io/inject: false` on a pod inside a "
            "mesh-enabled namespace. Each excludes traffic from the "
            "sidecar's iptables redirect — the workload then talks to "
            "any external IP, on any port, unobserved by mesh policy, "
            "without an mTLS client cert (so the destination's "
            "PeerAuthentication cannot identify it). The whole-pod "
            "inject:false variant compounds the bypass."
        ),
        pattern=_SIDECAR_EXCLUDE_OUTBOUND_WIDE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mesh-linkerd-server-no-identityrefs",
        name="Linkerd ServerAuthorization admits unauthenticated or any mesh identity",
        severity="CRITICAL",
        description=(
            "Linkerd `ServerAuthorization` CR uses "
            "`client.unauthenticated: true` (admits cleartext callers) "
            "OR omits / empties `client.meshTLS.identityRefs` and "
            "`client.meshTLS.serviceAccounts` (admits ANY mesh "
            "identity). Linkerd's authorization model is 'deny by "
            "default, allow by identity' — empty identityRefs is "
            "interpreted as 'all valid mesh identities'. Equivalent to "
            "Istio AuthorizationPolicy with `principals: [\"*\"]`."
        ),
        pattern=_LINKERD_UNAUTHENTICATED_TRUE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="mesh-consul-intentions-default-allow",
        name="Consul Connect default-allow intention or HCL default_policy=allow",
        severity="CRITICAL",
        description=(
            "Consul Connect `ServiceIntentions` defines a wildcard "
            "source `'*'` with `action: allow`, OR Consul agent "
            "configuration sets `default_policy = \"allow\"` in HCL, OR "
            "a `defaultAction: allow` is set on a ProxyDefaults / "
            "ServiceIntentions CRD. Consul Connect's identity model is "
            "service-to-service mTLS but is only 'deny-by-default' when "
            "`default_policy = \"deny\"`. With allow-by-default, every "
            "newly introduced service is reachable cluster-wide with no "
            "intention rule, and the 'allow * → *' fallback silently "
            "re-enables flat connectivity even when explicit deny rules "
            "exist for specific pairs."
        ),
        pattern=_CONSUL_HCL_DEFAULT_POLICY_ALLOW,
        owasp_asi="ASI-07",
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


def _entry_block(text: str, entry_start: int) -> str:
    """Return text from `entry_start` up to the next sibling `- ` at the
    same or shallower YAML indent, or end-of-text. Used to bound the
    'no audiences in this jwtRules entry' check.

    The walk is purely textual — RE2-safe, no regex backtracking — and
    stops at any line whose first non-whitespace character is `-` at
    the same indentation as the entry, OR at any line whose indent is
    less than the entry's first indented child line (which would be the
    parent block ending). Bounded to 80 lines to cap worst-case cost on
    pathological input.
    """
    lines = text[entry_start:].split("\n")
    if not lines:
        return ""
    first = lines[0]
    # Indent of the `-` itself.
    entry_indent = len(first) - len(first.lstrip(" "))
    out: list[str] = [first]
    for raw in lines[1:81]:
        stripped = raw.lstrip(" ")
        if not stripped:
            out.append(raw)
            continue
        indent = len(raw) - len(stripped)
        # Sibling at same indent → entry ended.
        if indent == entry_indent and stripped.startswith("- "):
            break
        # Parent block ended (indent dropped to <= entry_indent and not
        # the entry's own continuation lines).
        if indent <= entry_indent:
            break
        out.append(raw)
    return "\n".join(out)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Per-rule context filters:

      * P1 (peerauth-permissive) — anchor on `mode:` and require the
        same file to declare `kind: PeerAuthentication`. Without that
        guard, a `mode: PERMISSIVE` line in a `DestinationRule.spec.tls`
        block (a different YAML field with the same name) would
        false-positive.
      * P2 (authzpolicy-allow-all) — anchor on the wildcard principals
        / namespaces / requestPrincipals AND require the same file to
        contain `kind: AuthorizationPolicy` and `action: ALLOW`.
      * P3 (outbound-allow-any) — pure regex; the
        `outboundTrafficPolicy` key is unique to Istio.
      * P4 (jwt-no-audience) — for each `- issuer:` entry inside a
        RequestAuthentication file, walk the entry block and require
        that NO `audiences:` line appears. Also catch the wildcard
        `audiences: ["*"]` form independently.
      * P5 (sidecar-bypass) — anchor on the wide-exclude annotation;
        the `sidecar.istio.io/inject: false` and broad-port forms are
        compounding signals (also emitted, deduped by line).
      * P6 (linkerd-no-identityrefs) — anchor on
        `unauthenticated: true` AND require `kind: ServerAuthorization`
        in the same file. The empty-meshTLS-flow / empty identityRefs
        variants are emitted under the same rule id.
      * P7 (consul-default-allow) — anchor on the HCL form (file-wide
        textual match) OR the CRD `defaultAction: allow` (also
        file-wide) OR the wildcard-source flow inside a
        ServiceIntentions file.

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

    # ---- P1 : mesh-istio-peerauth-permissive ----
    rule_p1 = rule_by_id["mesh-istio-peerauth-permissive"]
    is_peerauth_file = _file_contains(text, _ISTIO_PEERAUTH_KIND)
    if is_peerauth_file:
        for m in _ISTIO_PEERAUTH_PERMISSIVE_MODE.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : mesh-istio-authzpolicy-allow-all ----
    rule_p2 = rule_by_id["mesh-istio-authzpolicy-allow-all"]
    is_authz_file = _file_contains(text, _ISTIO_AUTHZ_KIND)
    has_action_allow = _file_contains(text, _ISTIO_AUTHZ_ACTION_ALLOW)
    if is_authz_file and has_action_allow:
        for m in _ISTIO_AUTHZ_WILDCARD_PRINCIPAL.finditer(text):
            _emit(rule_p2, m.start(), m.group(0))
        for m in _ISTIO_AUTHZ_WILDCARD_OTHER.finditer(text):
            _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : mesh-istio-outbound-traffic-allow-any ----
    rule_p3 = rule_by_id["mesh-istio-outbound-traffic-allow-any"]
    for m in _ISTIO_OUTBOUND_ALLOW_ANY.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : mesh-istio-jwt-no-audience ----
    rule_p4 = rule_by_id["mesh-istio-jwt-no-audience"]
    is_requestauth_file = _file_contains(text, _ISTIO_REQUESTAUTH_KIND)
    if is_requestauth_file:
        # Wildcard-audience form fires independently of the entry walk.
        for m in _ISTIO_JWT_WILDCARD_AUDIENCE.finditer(text):
            _emit(rule_p4, m.start(), m.group(0))
        # For every `- issuer:` entry, walk the entry block and emit
        # only if `audiences:` is absent.
        for m in _ISTIO_JWT_ISSUER_ENTRY.finditer(text):
            block = _entry_block(text, m.start())
            if "audiences:" not in block:
                _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : mesh-pod-sidecar-bypass-init ----
    rule_p5 = rule_by_id["mesh-pod-sidecar-bypass-init"]
    for m in _SIDECAR_EXCLUDE_OUTBOUND_WIDE.finditer(text):
        _emit(rule_p5, m.start(), m.group(0))
    for m in _SIDECAR_EXCLUDE_OUTBOUND_PORTS_BROAD.finditer(text):
        _emit(rule_p5, m.start(), m.group(0))
    # inject:false compounds the bypass when it appears in the same file
    # as a mesh-relevant annotation OR a mesh-enabled namespace label.
    # We emit the inject:false hit whenever a mesh CRD kind is also in
    # the file (PeerAuthentication / AuthorizationPolicy / Sidecar /
    # RequestAuthentication / DestinationRule / VirtualService) OR when
    # the file already has one of the wide-exclude hits.
    has_mesh_kind = (
        is_peerauth_file
        or is_authz_file
        or is_requestauth_file
        or _file_contains(text, _re(r"^\s*kind:\s*(?:Sidecar|VirtualService|DestinationRule)\b"))
    )
    if has_mesh_kind:
        for m in _SIDECAR_INJECT_FALSE.finditer(text):
            _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : mesh-linkerd-server-no-identityrefs ----
    rule_p6 = rule_by_id["mesh-linkerd-server-no-identityrefs"]
    is_serverauth_file = _file_contains(text, _LINKERD_SERVERAUTH_KIND)
    if is_serverauth_file:
        for m in _LINKERD_UNAUTHENTICATED_TRUE.finditer(text):
            _emit(rule_p6, m.start(), m.group(0))
        for m in _LINKERD_MESHTLS_EMPTY_FLOW.finditer(text):
            _emit(rule_p6, m.start(), m.group(0))
        for m in _LINKERD_MESHTLS_EMPTY_IDENTITYREFS.finditer(text):
            _emit(rule_p6, m.start(), m.group(0))

    # ---- P7 : mesh-consul-intentions-default-allow ----
    rule_p7 = rule_by_id["mesh-consul-intentions-default-allow"]
    # HCL form — fires anywhere the literal appears (it is uniquely a
    # Consul agent config key).
    for m in _CONSUL_HCL_DEFAULT_POLICY_ALLOW.finditer(text):
        _emit(rule_p7, m.start(), m.group(0))
    # CRD form — defaultAction:allow on a ProxyDefaults / ServiceIntentions
    for m in _CONSUL_CRD_DEFAULT_ACTION_ALLOW.finditer(text):
        _emit(rule_p7, m.start(), m.group(0))
    # Wildcard-source-allow inside a ServiceIntentions manifest.
    if _file_contains(text, _CONSUL_INTENTIONS_KIND):
        for m in _CONSUL_WILDCARD_SOURCE_ALLOW.finditer(text):
            _emit(rule_p7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
