"""Tests for scripts/lib/istio_mtls_patterns.py.

Wave-37 distillation round 23 — Istio mTLS / PeerAuthentication bypass.
Orthogonal to service_mesh_patterns (which covers top-level PERMISSIVE,
allow-all AuthorizationPolicy, OutboundTrafficPolicy ALLOW_ANY, and
missing-audience RequestAuthentication). This module covers the deeper
mTLS-strip surface: port-level DISABLE, DestinationRule tls DISABLE,
Gateway SIMPLE, CORS wildcard, EnvoyFilter Lua, WorkloadEntry without
serviceAccount, Sidecar egress wildcard, ALLOW-without-from, and the
EMPTY audiences-array variant.

Every rule gets at least one positive test (realistic vulnerable Istio
YAML that MUST match) and at least one negative test (a safe shape that
MUST NOT match).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import istio_mtls_patterns as imp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[imp.Finding]:
    return [f for f in imp.scan_text(text) if f.rule_id == rule_id]


# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES is a tuple containing every advertised Istio-mTLS rule id."""
    assert isinstance(imp.RULES, tuple)
    rule_ids = {r.id for r in imp.RULES}
    expected = {
        "istio-mtls-portlevel-disable",
        "istio-mtls-destinationrule-tls-disable",
        "istio-mtls-gateway-tls-simple",
        "istio-mtls-virtualservice-cors-wildcard",
        "istio-mtls-envoyfilter-lua",
        "istio-mtls-workloadentry-no-serviceaccount",
        "istio-mtls-sidecar-egress-wildcard",
        "istio-mtls-authzpolicy-allow-no-from",
        "istio-mtls-requestauth-empty-audiences",
    }
    assert expected == rule_ids
    assert len(expected) == 9


def test_no_overlap_with_service_mesh_ids() -> None:
    """All ids are istio-mtls-* prefixed — no mesh-istio-* collisions."""
    for rule in imp.RULES:
        assert rule.id.startswith("istio-mtls-"), rule.id
        assert not rule.id.startswith("mesh-"), rule.id


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a valid severity."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in imp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the sibling pattern-module Finding shape."""
    f = imp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1 and f.column == 2
    assert f.severity == "HIGH"


def test_scan_text_empty_returns_empty() -> None:
    """An empty input yields no findings."""
    assert imp.scan_text("") == []


def test_descriptions_nonempty() -> None:
    """Every rule has a non-empty name and description."""
    for r in imp.RULES:
        assert r.name.strip()
        assert r.description.strip()


# ---------- Rule 1: portLevelMtls DISABLE --------------------------------


def test_portlevel_mtls_disable_high() -> None:
    """portLevelMtls mode: DISABLE on a STRICT policy is HIGH."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: PeerAuthentication\n"
        "metadata: {name: app, namespace: prod}\n"
        "spec:\n"
        "  mtls: {mode: STRICT}\n"
        "  portLevelMtls:\n"
        "    8080:\n"
        "      mode: DISABLE\n"
    )
    hits = _hits("istio-mtls-portlevel-disable", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_portlevel_mtls_strict_safe() -> None:
    """portLevelMtls mode: STRICT does NOT fire rule 1."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: PeerAuthentication\n"
        "metadata: {name: app, namespace: prod}\n"
        "spec:\n"
        "  mtls: {mode: STRICT}\n"
        "  portLevelMtls:\n"
        "    8080:\n"
        "      mode: STRICT\n"
    )
    assert not _hits("istio-mtls-portlevel-disable", src)


# ---------- Rule 2: DestinationRule tls DISABLE --------------------------


def test_destinationrule_tls_disable_high() -> None:
    """DestinationRule trafficPolicy.tls.mode: DISABLE is HIGH."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: DestinationRule\n"
        "metadata: {name: backend}\n"
        "spec:\n"
        "  host: backend.prod.svc.cluster.local\n"
        "  trafficPolicy:\n"
        "    tls:\n"
        "      mode: DISABLE\n"
    )
    assert _hits("istio-mtls-destinationrule-tls-disable", src)


def test_destinationrule_tls_istio_mutual_safe() -> None:
    """DestinationRule tls.mode: ISTIO_MUTUAL does NOT fire rule 2."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: DestinationRule\n"
        "metadata: {name: backend}\n"
        "spec:\n"
        "  host: backend\n"
        "  trafficPolicy:\n"
        "    tls:\n"
        "      mode: ISTIO_MUTUAL\n"
    )
    assert not _hits("istio-mtls-destinationrule-tls-disable", src)


# ---------- Rule 3: Gateway tls SIMPLE -----------------------------------


def test_gateway_tls_simple_high() -> None:
    """Gateway tls.mode: SIMPLE (server-only TLS) is HIGH."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: Gateway\n"
        "metadata: {name: ingress}\n"
        "spec:\n"
        "  servers:\n"
        "    - port: {number: 443, name: https, protocol: HTTPS}\n"
        "      tls:\n"
        "        mode: SIMPLE\n"
    )
    assert _hits("istio-mtls-gateway-tls-simple", src)


def test_gateway_tls_mutual_safe() -> None:
    """Gateway tls.mode: MUTUAL (client cert required) does NOT fire rule 3."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: Gateway\n"
        "metadata: {name: ingress}\n"
        "spec:\n"
        "  servers:\n"
        "    - port: {number: 443, name: https, protocol: HTTPS}\n"
        "      tls:\n"
        "        mode: MUTUAL\n"
    )
    assert not _hits("istio-mtls-gateway-tls-simple", src)


# ---------- Rule 4: VirtualService CORS wildcard -------------------------


def test_virtualservice_cors_wildcard_medium() -> None:
    """VirtualService CORS allowOrigins exact: '*' is MEDIUM."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: VirtualService\n"
        "metadata: {name: api}\n"
        "spec:\n"
        "  hosts: [api.internal]\n"
        "  http:\n"
        "    - corsPolicy:\n"
        "        allowOrigins:\n"
        '          - exact: "*"\n'
    )
    assert _hits("istio-mtls-virtualservice-cors-wildcard", src)


def test_virtualservice_cors_scoped_origin_safe() -> None:
    """A scoped CORS origin (exact host) does NOT fire rule 4."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: VirtualService\n"
        "metadata: {name: api}\n"
        "spec:\n"
        "  hosts: [api.internal]\n"
        "  http:\n"
        "    - corsPolicy:\n"
        "        allowOrigins:\n"
        '          - exact: "https://app.example.com"\n'
    )
    assert not _hits("istio-mtls-virtualservice-cors-wildcard", src)


# ---------- Rule 5: EnvoyFilter Lua --------------------------------------


def test_envoyfilter_lua_critical() -> None:
    """EnvoyFilter adding envoy.filters.http.lua is CRITICAL."""
    src = (
        "apiVersion: networking.istio.io/v1alpha3\n"
        "kind: EnvoyFilter\n"
        "metadata: {name: lua-inject}\n"
        "spec:\n"
        "  configPatches:\n"
        "    - applyTo: HTTP_FILTER\n"
        "      patch:\n"
        "        operation: INSERT_BEFORE\n"
        "        value:\n"
        "          name: envoy.filters.http.lua\n"
        "          typed_config:\n"
        '            inlineCode: "function envoy_on_request(h) end"\n'
    )
    hits = _hits("istio-mtls-envoyfilter-lua", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_envoyfilter_no_lua_safe() -> None:
    """An EnvoyFilter that adds a non-Lua filter does NOT fire rule 5."""
    src = (
        "apiVersion: networking.istio.io/v1alpha3\n"
        "kind: EnvoyFilter\n"
        "metadata: {name: cors}\n"
        "spec:\n"
        "  configPatches:\n"
        "    - applyTo: HTTP_FILTER\n"
        "      patch:\n"
        "        value:\n"
        "          name: envoy.filters.http.cors\n"
    )
    assert not _hits("istio-mtls-envoyfilter-lua", src)


# ---------- Rule 6: WorkloadEntry without serviceAccount -----------------


def test_workloadentry_no_serviceaccount_medium() -> None:
    """A WorkloadEntry without serviceAccount is MEDIUM (no SPIFFE id)."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: WorkloadEntry\n"
        "metadata: {name: vm1, namespace: prod}\n"
        "spec:\n"
        "  address: 10.0.0.5\n"
        "  labels: {app: legacy}\n"
    )
    assert _hits("istio-mtls-workloadentry-no-serviceaccount", src)


def test_workloadentry_with_serviceaccount_safe() -> None:
    """A WorkloadEntry with a serviceAccount does NOT fire rule 6."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: WorkloadEntry\n"
        "metadata: {name: vm1, namespace: prod}\n"
        "spec:\n"
        "  address: 10.0.0.5\n"
        "  serviceAccount: vm-identity\n"
    )
    assert not _hits("istio-mtls-workloadentry-no-serviceaccount", src)


# ---------- Rule 7: Sidecar egress wildcard ------------------------------


def test_sidecar_egress_wildcard_medium() -> None:
    """Sidecar egress hosts: ['*/*'] is MEDIUM (namespace-isolation bypass)."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: Sidecar\n"
        "metadata: {name: default, namespace: app}\n"
        "spec:\n"
        "  egress:\n"
        "    - hosts:\n"
        '        - "*/*"\n'
    )
    assert _hits("istio-mtls-sidecar-egress-wildcard", src)


def test_sidecar_egress_scoped_safe() -> None:
    """A Sidecar egress scoped to one namespace does NOT fire rule 7."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: Sidecar\n"
        "metadata: {name: default, namespace: app}\n"
        "spec:\n"
        "  egress:\n"
        "    - hosts:\n"
        '        - "app/*"\n'
        '        - "istio-system/*"\n'
    )
    assert not _hits("istio-mtls-sidecar-egress-wildcard", src)


# ---------- Rule 8: AuthorizationPolicy ALLOW without from ----------------


def test_authzpolicy_allow_no_from_critical() -> None:
    """An ALLOW AuthorizationPolicy with no from: clause is CRITICAL."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: AuthorizationPolicy\n"
        "metadata: {name: allow-anything, namespace: prod}\n"
        "spec:\n"
        "  action: ALLOW\n"
        "  rules:\n"
        "    - to:\n"
        '        - operation: {methods: ["GET", "POST"]}\n'
    )
    hits = _hits("istio-mtls-authzpolicy-allow-no-from", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_authzpolicy_allow_with_from_safe() -> None:
    """An ALLOW policy WITH a from: source clause does NOT fire rule 8."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: AuthorizationPolicy\n"
        "metadata: {name: scoped, namespace: prod}\n"
        "spec:\n"
        "  action: ALLOW\n"
        "  rules:\n"
        "    - from:\n"
        "        - source:\n"
        '            principals: ["cluster.local/ns/prod/sa/frontend"]\n'
    )
    assert not _hits("istio-mtls-authzpolicy-allow-no-from", src)


def test_authzpolicy_deny_action_safe() -> None:
    """A DENY AuthorizationPolicy (no ALLOW) does NOT fire rule 8."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: AuthorizationPolicy\n"
        "metadata: {name: deny-bad, namespace: prod}\n"
        "spec:\n"
        "  action: DENY\n"
        "  rules:\n"
        "    - to:\n"
        '        - operation: {paths: ["/admin"]}\n'
    )
    assert not _hits("istio-mtls-authzpolicy-allow-no-from", src)


# ---------- Rule 9: RequestAuthentication empty audiences ----------------


def test_requestauth_empty_audiences_high() -> None:
    """RequestAuthentication with audiences: [] is HIGH (token reuse)."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: RequestAuthentication\n"
        "metadata: {name: jwt, namespace: prod}\n"
        "spec:\n"
        "  jwtRules:\n"
        '    - issuer: "https://accounts.example.com"\n'
        "      audiences: []\n"
    )
    assert _hits("istio-mtls-requestauth-empty-audiences", src)


def test_requestauth_with_audience_safe() -> None:
    """A populated audiences list does NOT fire rule 9."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: RequestAuthentication\n"
        "metadata: {name: jwt, namespace: prod}\n"
        "spec:\n"
        "  jwtRules:\n"
        '    - issuer: "https://accounts.example.com"\n'
        "      audiences:\n"
        '        - "my-service"\n'
    )
    assert not _hits("istio-mtls-requestauth-empty-audiences", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_findings_sorted_and_deduped() -> None:
    """Findings come out sorted by (line, column, rule_id) and deduped."""
    src = (
        "apiVersion: networking.istio.io/v1\n"
        "kind: DestinationRule\n"
        "metadata: {name: backend}\n"
        "spec:\n"
        "  host: backend\n"
        "  trafficPolicy:\n"
        "    tls:\n"
        "      mode: DISABLE\n"
    )
    findings = imp.scan_text(src)
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line,
            curr.column,
            curr.rule_id,
        )
    keys = [(f.rule_id, f.line, f.column, f.matched_text) for f in findings]
    assert len(keys) == len(set(keys))


def test_multidoc_allow_no_from_scoped_per_document() -> None:
    """A from: in a neighbouring doc must not mask an ALLOW-no-from doc."""
    src = (
        "apiVersion: security.istio.io/v1\n"
        "kind: AuthorizationPolicy\n"
        "metadata: {name: scoped}\n"
        "spec:\n"
        "  action: ALLOW\n"
        "  rules:\n"
        "    - from:\n"
        '        - source: {principals: ["cluster.local/ns/a/sa/b"]}\n'
        "---\n"
        "apiVersion: security.istio.io/v1\n"
        "kind: AuthorizationPolicy\n"
        "metadata: {name: open}\n"
        "spec:\n"
        "  action: ALLOW\n"
        "  rules:\n"
        "    - to:\n"
        '        - operation: {methods: ["GET"]}\n'
    )
    # Exactly the second (open) document must fire.
    hits = _hits("istio-mtls-authzpolicy-allow-no-from", src)
    assert len(hits) == 1
