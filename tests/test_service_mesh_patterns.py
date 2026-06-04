"""Tests for scripts/lib/service_mesh_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 service-mesh
catalogue (7 patterns covering Istio / Linkerd / Consul Connect).
Each rule has two tests: one positive (canary fires) and one negative
(carve-out / context filter suppresses).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import service_mesh_patterns as smp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(smp.RULES, tuple)
    rule_ids = {r.id for r in smp.RULES}
    expected = {
        "mesh-istio-peerauth-permissive",
        "mesh-istio-authzpolicy-allow-all",
        "mesh-istio-outbound-traffic-allow-any",
        "mesh-istio-jwt-no-audience",
        "mesh-pod-sidecar-bypass-init",
        "mesh-linkerd-server-no-identityrefs",
        "mesh-consul-intentions-default-allow",
    }
    assert expected == rule_ids
    assert len(smp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in smp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = smp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
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
    assert smp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "apiVersion: security.istio.io/v1beta1\n"
        "kind: PeerAuthentication\n"
        "metadata:\n"
        "  name: default\n"
        "  namespace: production\n"
        "spec:\n"
        "  mtls:\n"
        "    mode: PERMISSIVE\n"
        "---\n"
        "default_policy = \"allow\"\n"
    )
    findings = smp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[smp.Finding]:
    return [f for f in smp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : mesh-istio-peerauth-permissive --------------------------


def test_p1_peerauth_permissive_flags() -> None:
    """PeerAuthentication with mtls.mode: PERMISSIVE → HIGH hit."""
    src = (
        "apiVersion: security.istio.io/v1beta1\n"
        "kind: PeerAuthentication\n"
        "metadata:\n"
        "  name: default\n"
        "  namespace: production\n"
        "spec:\n"
        "  mtls:\n"
        "    mode: PERMISSIVE\n"
    )
    hits = _hits("mesh-istio-peerauth-permissive", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert "PERMISSIVE" in hits[0].matched_text


def test_p1_peerauth_disable_flags() -> None:
    """PeerAuthentication with mtls.mode: DISABLE → also flagged."""
    src = (
        "kind: PeerAuthentication\n"
        "spec:\n"
        "  mtls:\n"
        "    mode: DISABLE\n"
    )
    assert _hits("mesh-istio-peerauth-permissive", src)


def test_p1_peerauth_strict_silent() -> None:
    """PeerAuthentication with mtls.mode: STRICT → no hit."""
    src = (
        "kind: PeerAuthentication\n"
        "spec:\n"
        "  mtls:\n"
        "    mode: STRICT\n"
    )
    assert not _hits("mesh-istio-peerauth-permissive", src)


def test_p1_mode_outside_peerauth_silent() -> None:
    """A `mode: PERMISSIVE` line in a file that is NOT a PeerAuthentication
    (no `kind: PeerAuthentication`) must not fire — same word, different CRD."""
    src = (
        "apiVersion: networking.istio.io/v1beta1\n"
        "kind: DestinationRule\n"
        "spec:\n"
        "  trafficPolicy:\n"
        "    tls:\n"
        "      mode: PERMISSIVE\n"  # legal in DestinationRule tls
    )
    assert not _hits("mesh-istio-peerauth-permissive", src)


# ---------- P2 : mesh-istio-authzpolicy-allow-all ------------------------


def test_p2_authzpolicy_wildcard_principal_flags() -> None:
    """AuthorizationPolicy ALLOW + principals: ['*'] → CRITICAL hit."""
    src = (
        "apiVersion: security.istio.io/v1beta1\n"
        "kind: AuthorizationPolicy\n"
        "metadata:\n"
        "  name: allow-everything\n"
        "  namespace: payments\n"
        "spec:\n"
        "  action: ALLOW\n"
        "  rules:\n"
        "  - from:\n"
        "    - source:\n"
        "        principals: [\"*\"]\n"
    )
    hits = _hits("mesh-istio-authzpolicy-allow-all", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p2_authzpolicy_wildcard_namespace_flags() -> None:
    """AuthorizationPolicy ALLOW + namespaces wildcard → CRITICAL hit."""
    src = (
        "kind: AuthorizationPolicy\n"
        "spec:\n"
        "  action: ALLOW\n"
        "  rules:\n"
        "  - from:\n"
        "    - source:\n"
        "        namespaces: [\"*\"]\n"
    )
    assert _hits("mesh-istio-authzpolicy-allow-all", src)


def test_p2_authzpolicy_specific_principal_silent() -> None:
    """AuthorizationPolicy with a specific SPIFFE principal → no hit."""
    src = (
        "kind: AuthorizationPolicy\n"
        "spec:\n"
        "  action: ALLOW\n"
        "  rules:\n"
        "  - from:\n"
        "    - source:\n"
        "        principals: [\"cluster.local/ns/payments/sa/api\"]\n"
    )
    assert not _hits("mesh-istio-authzpolicy-allow-all", src)


def test_p2_wildcard_outside_authz_file_silent() -> None:
    """A wildcard principals line in a non-AuthorizationPolicy file → no hit."""
    src = (
        "kind: ServiceAccount\n"
        "spec:\n"
        "  principals: [\"*\"]\n"  # nonsense for SA, but proves context-gating
    )
    assert not _hits("mesh-istio-authzpolicy-allow-all", src)


# ---------- P3 : mesh-istio-outbound-traffic-allow-any -------------------


def test_p3_istio_operator_allow_any_flags() -> None:
    """IstioOperator meshConfig.outboundTrafficPolicy.mode: ALLOW_ANY → HIGH."""
    src = (
        "apiVersion: install.istio.io/v1alpha1\n"
        "kind: IstioOperator\n"
        "spec:\n"
        "  meshConfig:\n"
        "    outboundTrafficPolicy:\n"
        "      mode: ALLOW_ANY\n"
    )
    hits = _hits("mesh-istio-outbound-traffic-allow-any", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p3_sidecar_cr_allow_any_flags() -> None:
    """Sidecar CR outboundTrafficPolicy.mode: ALLOW_ANY → also flagged."""
    src = (
        "apiVersion: networking.istio.io/v1beta1\n"
        "kind: Sidecar\n"
        "metadata:\n"
        "  namespace: production\n"
        "spec:\n"
        "  outboundTrafficPolicy:\n"
        "    mode: ALLOW_ANY\n"
    )
    assert _hits("mesh-istio-outbound-traffic-allow-any", src)


def test_p3_registry_only_silent() -> None:
    """outboundTrafficPolicy.mode: REGISTRY_ONLY → no hit."""
    src = (
        "kind: IstioOperator\n"
        "spec:\n"
        "  meshConfig:\n"
        "    outboundTrafficPolicy:\n"
        "      mode: REGISTRY_ONLY\n"
    )
    assert not _hits("mesh-istio-outbound-traffic-allow-any", src)


# ---------- P4 : mesh-istio-jwt-no-audience ------------------------------


def test_p4_jwt_no_audiences_flags() -> None:
    """jwtRules entry with issuer but NO audiences → HIGH hit."""
    src = (
        "apiVersion: security.istio.io/v1beta1\n"
        "kind: RequestAuthentication\n"
        "metadata:\n"
        "  name: jwt-auth\n"
        "  namespace: payments\n"
        "spec:\n"
        "  selector:\n"
        "    matchLabels:\n"
        "      app: payments-api\n"
        "  jwtRules:\n"
        "  - issuer: \"https://login.example.com\"\n"
        "    jwksUri: \"https://login.example.com/.well-known/jwks.json\"\n"
    )
    hits = _hits("mesh-istio-jwt-no-audience", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p4_jwt_wildcard_audience_flags() -> None:
    """jwtRules entry with `audiences: ['*']` → flagged (defeats binding)."""
    src = (
        "kind: RequestAuthentication\n"
        "spec:\n"
        "  jwtRules:\n"
        "  - issuer: \"https://login.example.com\"\n"
        "    audiences: [\"*\"]\n"
    )
    assert _hits("mesh-istio-jwt-no-audience", src)


def test_p4_jwt_with_audiences_silent() -> None:
    """jwtRules entry with a specific audiences list → no hit."""
    src = (
        "kind: RequestAuthentication\n"
        "spec:\n"
        "  jwtRules:\n"
        "  - issuer: \"https://login.example.com\"\n"
        "    jwksUri: \"https://login.example.com/.well-known/jwks.json\"\n"
        "    audiences:\n"
        "    - \"payments-api\"\n"
    )
    assert not _hits("mesh-istio-jwt-no-audience", src)


# ---------- P5 : mesh-pod-sidecar-bypass-init ----------------------------


def test_p5_sidecar_exclude_outbound_zero_flags() -> None:
    """excludeOutboundIPRanges: 0.0.0.0/0 → HIGH hit."""
    src = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: data-exporter\n"
        "spec:\n"
        "  template:\n"
        "    metadata:\n"
        "      annotations:\n"
        "        traffic.sidecar.istio.io/excludeOutboundIPRanges: \"0.0.0.0/0\"\n"
    )
    hits = _hits("mesh-pod-sidecar-bypass-init", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p5_sidecar_full_port_range_flags() -> None:
    """excludeOutboundPorts: 1-65535 → flagged."""
    src = (
        "kind: Deployment\n"
        "spec:\n"
        "  template:\n"
        "    metadata:\n"
        "      annotations:\n"
        "        traffic.sidecar.istio.io/excludeOutboundPorts: \"1-65535\"\n"
    )
    assert _hits("mesh-pod-sidecar-bypass-init", src)


def test_p5_sidecar_inject_false_with_mesh_kind_flags() -> None:
    """sidecar.istio.io/inject: false in a file with a mesh kind → flagged
    (the inject-false is the bypass; the mesh kind is the gating signal)."""
    src = (
        "kind: PeerAuthentication\n"
        "spec:\n"
        "  mtls:\n"
        "    mode: STRICT\n"
        "---\n"
        "kind: Deployment\n"
        "spec:\n"
        "  template:\n"
        "    metadata:\n"
        "      annotations:\n"
        "        sidecar.istio.io/inject: \"false\"\n"
    )
    assert _hits("mesh-pod-sidecar-bypass-init", src)


def test_p5_narrow_port_exclude_silent() -> None:
    """excludeOutboundPorts with a single narrow port → no hit."""
    src = (
        "kind: Deployment\n"
        "spec:\n"
        "  template:\n"
        "    metadata:\n"
        "      annotations:\n"
        "        traffic.sidecar.istio.io/excludeOutboundPorts: \"5432\"\n"
    )
    assert not _hits("mesh-pod-sidecar-bypass-init", src)


# ---------- P6 : mesh-linkerd-server-no-identityrefs ---------------------


def test_p6_linkerd_unauthenticated_flags() -> None:
    """ServerAuthorization with client.unauthenticated: true → CRITICAL hit."""
    src = (
        "apiVersion: policy.linkerd.io/v1beta1\n"
        "kind: ServerAuthorization\n"
        "metadata:\n"
        "  name: api-allow-all\n"
        "  namespace: production\n"
        "spec:\n"
        "  server:\n"
        "    name: api-server\n"
        "  client:\n"
        "    unauthenticated: true\n"
    )
    hits = _hits("mesh-linkerd-server-no-identityrefs", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p6_linkerd_empty_meshtls_flags() -> None:
    """ServerAuthorization with empty meshTLS: {} → flagged."""
    src = (
        "kind: ServerAuthorization\n"
        "spec:\n"
        "  client:\n"
        "    meshTLS: {}\n"
    )
    assert _hits("mesh-linkerd-server-no-identityrefs", src)


def test_p6_linkerd_identityrefs_empty_array_flags() -> None:
    """ServerAuthorization with `identityRefs: []` → flagged."""
    src = (
        "kind: ServerAuthorization\n"
        "spec:\n"
        "  client:\n"
        "    meshTLS:\n"
        "      identityRefs: []\n"
    )
    assert _hits("mesh-linkerd-server-no-identityrefs", src)


def test_p6_linkerd_specific_identity_silent() -> None:
    """ServerAuthorization with a real meshTLS identityRef → no hit."""
    src = (
        "kind: ServerAuthorization\n"
        "spec:\n"
        "  client:\n"
        "    meshTLS:\n"
        "      identityRefs:\n"
        "      - kind: ServiceAccount\n"
        "        name: payments-client\n"
        "        namespace: payments\n"
    )
    assert not _hits("mesh-linkerd-server-no-identityrefs", src)


def test_p6_unauthenticated_outside_serverauth_silent() -> None:
    """`unauthenticated: true` outside a ServerAuthorization file → no hit
    (some other CRD may have a same-named field with a different semantic)."""
    src = (
        "kind: SomeOtherCRD\n"
        "spec:\n"
        "  unauthenticated: true\n"
    )
    assert not _hits("mesh-linkerd-server-no-identityrefs", src)


# ---------- P7 : mesh-consul-intentions-default-allow --------------------


def test_p7_consul_hcl_default_allow_flags() -> None:
    """HCL agent config with default_policy = \"allow\" → CRITICAL hit."""
    src = (
        "acl {\n"
        "  enabled        = true\n"
        "  default_policy = \"allow\"\n"
        "}\n"
    )
    hits = _hits("mesh-consul-intentions-default-allow", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p7_consul_crd_default_action_allow_flags() -> None:
    """CRD defaultAction: allow → flagged."""
    src = (
        "apiVersion: consul.hashicorp.com/v1alpha1\n"
        "kind: ServiceIntentions\n"
        "metadata:\n"
        "  name: defaults\n"
        "spec:\n"
        "  destination:\n"
        "    name: payments\n"
        "  defaultAction: allow\n"
    )
    assert _hits("mesh-consul-intentions-default-allow", src)


def test_p7_consul_wildcard_source_allow_flags() -> None:
    """ServiceIntentions with wildcard source name + action: allow → flagged."""
    src = (
        "apiVersion: consul.hashicorp.com/v1alpha1\n"
        "kind: ServiceIntentions\n"
        "metadata:\n"
        "  name: payments\n"
        "spec:\n"
        "  destination:\n"
        "    name: payments\n"
        "  sources:\n"
        "  - name: '*'\n"
        "    action: allow\n"
    )
    assert _hits("mesh-consul-intentions-default-allow", src)


def test_p7_consul_default_deny_silent() -> None:
    """HCL with `default_policy = \"deny\"` and a specific source → no hit."""
    src = (
        "acl {\n"
        "  enabled        = true\n"
        "  default_policy = \"deny\"\n"
        "}\n"
        "---\n"
        "kind: ServiceIntentions\n"
        "spec:\n"
        "  sources:\n"
        "  - name: 'web'\n"
        "    action: allow\n"
    )
    assert not _hits("mesh-consul-intentions-default-allow", src)


# ---------- Cross-rule sanity --------------------------------------------


def test_multiple_rules_can_fire_on_same_file() -> None:
    """A compound misconfig file fires multiple rule IDs."""
    src = (
        "kind: PeerAuthentication\n"
        "spec:\n"
        "  mtls:\n"
        "    mode: PERMISSIVE\n"
        "---\n"
        "default_policy = \"allow\"\n"
    )
    findings = smp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "mesh-istio-peerauth-permissive" in rule_ids
    assert "mesh-consul-intentions-default-allow" in rule_ids


def test_no_findings_on_benign_text() -> None:
    """Benign English prose → 0 findings."""
    src = (
        "This document describes service mesh integration. It does not\n"
        "contain any actual manifests. The mesh is discussed only in\n"
        "prose, with no Istio, Linkerd, or Consul YAML present.\n"
    )
    assert smp.scan_text(src) == []


def test_dedup_prevents_double_emission() -> None:
    """Same line / column / rule_id is only emitted once per scan."""
    src = (
        "kind: PeerAuthentication\n"
        "spec:\n"
        "  mtls:\n"
        "    mode: PERMISSIVE\n"
    )
    findings = smp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
