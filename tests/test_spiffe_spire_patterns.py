"""Tests for scripts/lib/spiffe_spire_patterns.py.

Wave-37 distillation round 23 — SPIFFE / SPIRE workload-identity misuse:
JWT-SVID wildcard audience, excessive X.509-SVID TTL, world-writable
Agent socket, public-DNS trust domain, unpinned federation bundle
endpoint, long-lived join-token, unix attestor without sha256, disk
UpstreamAuthority cleartext CA, deep parent_id delegation chains, OIDC
discovery-provider block.

Every rule gets at least one positive test (a realistic vulnerable
snippet that MUST match) and at least one negative test (a safe snippet
that MUST NOT match).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import spiffe_spire_patterns as ssp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[ssp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in ssp.scan_text(text) if f.rule_id == rule_id]


# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES is a tuple and contains every advertised rule id."""
    assert isinstance(ssp.RULES, tuple)
    rule_ids = {r.id for r in ssp.RULES}
    expected = {
        "spiffe-jwt-svid-wildcard-audience",
        "spiffe-x509-svid-ttl-excessive",
        "spiffe-agent-socket-world-readable",
        "spiffe-trust-domain-public-dns",
        "spiffe-federation-bundle-endpoint-unpinned",
        "spiffe-node-attestor-join-token-long-ttl",
        "spiffe-unix-attestor-no-sha256",
        "spiffe-upstream-authority-disk-cleartext",
        "spiffe-parent-id-chain-too-deep",
        "spiffe-oidc-discovery-provider-block",
    }
    assert expected.issubset(rule_ids)
    assert len(expected) == 10


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a valid severity."""
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in ssp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_severities, rule.id


def test_descriptions_and_names_nonempty() -> None:
    """Every rule has a non-empty name and description."""
    for r in ssp.RULES:
        assert r.name.strip(), r.id
        assert r.description.strip(), r.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the cloud_credential_patterns shape."""
    f = ssp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1 and f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"


def test_scan_text_empty_returns_empty() -> None:
    """Empty input yields no findings."""
    assert ssp.scan_text("") == []


# ---------- Rule 1: JWT-SVID wildcard audience ---------------------------


def test_jwt_wildcard_audience_fires() -> None:
    """audience = [\"*\"] is flagged CRITICAL."""
    src = 'jwt_svid {\n    audience = [ "*" ]\n}\n'
    hits = _hits("spiffe-jwt-svid-wildcard-audience", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_jwt_explicit_audience_safe() -> None:
    """An explicit audience list does NOT fire rule 1."""
    src = 'jwt_svid {\n    audience = ["spiffe://acme/api"]\n}\n'
    assert not _hits("spiffe-jwt-svid-wildcard-audience", src)


# ---------- Rule 2: X.509-SVID TTL excessive -----------------------------


def test_x509_ttl_48h_fires() -> None:
    """x509_svid_ttl = \"48h\" exceeds 24h and is flagged."""
    src = 'entry {\n    x509_svid_ttl = "48h"\n}\n'
    assert _hits("spiffe-x509-svid-ttl-excessive", src)


def test_x509_ttl_168h_fires() -> None:
    """A 3-digit hour TTL (168h = 1 week) is flagged."""
    src = 'entry {\n    x509_svid_ttl = "168h"\n}\n'
    assert _hits("spiffe-x509-svid-ttl-excessive", src)


def test_x509_ttl_1h_safe() -> None:
    """x509_svid_ttl = \"1h\" (recommended) does NOT fire."""
    src = 'entry {\n    x509_svid_ttl = "1h"\n}\n'
    assert not _hits("spiffe-x509-svid-ttl-excessive", src)


# ---------- Rule 3: Agent socket world-readable --------------------------


def test_agent_socket_tmp_fires() -> None:
    """socket_path under /tmp is flagged HIGH."""
    src = 'agent {\n    socket_path = "/tmp/spire-agent/public/api.sock"\n}\n'
    hits = _hits("spiffe-agent-socket-world-readable", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_agent_socket_run_path_safe() -> None:
    """socket_path under /run (restricted) does NOT fire rule 3."""
    src = 'agent {\n    socket_path = "/run/spire/agent/api.sock"\n}\n'
    assert not _hits("spiffe-agent-socket-world-readable", src)


# ---------- Rule 4: trust_domain public DNS ------------------------------


def test_trust_domain_public_dns_fires() -> None:
    """A public multi-label trust_domain is flagged for review."""
    src = 'server {\n    trust_domain = "mesh.example.com"\n}\n'
    assert _hits("spiffe-trust-domain-public-dns", src)


def test_trust_domain_cluster_local_safe() -> None:
    """An internal .cluster.local trust_domain does NOT fire."""
    src = 'server {\n    trust_domain = "spire.cluster.local"\n}\n'
    assert not _hits("spiffe-trust-domain-public-dns", src)


# ---------- Rule 5: federation bundle endpoint unpinned ------------------


def test_federation_bundle_endpoint_fires() -> None:
    """A federation bundle_endpoint_url is surfaced for pinning review."""
    src = (
        "federation {\n"
        "    federates_with \"other.org\" {\n"
        '        bundle_endpoint_url = "https://other.org/bundle"\n'
        "    }\n"
        "}\n"
    )
    assert _hits("spiffe-federation-bundle-endpoint-unpinned", src)


def test_no_federation_block_safe() -> None:
    """A config with no bundle_endpoint_url does NOT fire rule 5."""
    src = 'server {\n    trust_domain = "spire.cluster.local"\n}\n'
    assert not _hits("spiffe-federation-bundle-endpoint-unpinned", src)


# ---------- Rule 6: node attestor join_token long TTL --------------------


def test_join_token_long_ttl_days_fires() -> None:
    """A join_token ttl in days is flagged HIGH."""
    src = 'NodeAttestor "join_token" {\n    plugin_data {\n        ttl = "7d"\n    }\n}\n'
    assert _hits("spiffe-node-attestor-join-token-long-ttl", src)


def test_join_token_large_seconds_fires() -> None:
    """A four-digit-second ttl (3600s) is flagged HIGH."""
    src = 'plugin_data {\n    ttl = "3600s"\n}\n'
    assert _hits("spiffe-node-attestor-join-token-long-ttl", src)


def test_join_token_short_ttl_safe() -> None:
    """A short ttl = \"60s\" (single-use bootstrap) does NOT fire."""
    src = 'plugin_data {\n    ttl = "60s"\n}\n'
    assert not _hits("spiffe-node-attestor-join-token-long-ttl", src)


# ---------- Rule 7: unix attestor without sha256 -------------------------


def test_unix_attestor_fires() -> None:
    """A unix WorkloadAttestor plugin is surfaced for sha256 review."""
    src = 'WorkloadAttestor "unix" {\n    plugin_data {}\n}\n'
    assert _hits("spiffe-unix-attestor-no-sha256", src)


def test_docker_attestor_safe() -> None:
    """A docker attestor (not unix) does NOT fire rule 7."""
    src = 'WorkloadAttestor "docker" {\n    plugin_data {}\n}\n'
    assert not _hits("spiffe-unix-attestor-no-sha256", src)


# ---------- Rule 8: UpstreamAuthority disk cleartext ---------------------


def test_upstream_authority_disk_fires() -> None:
    """UpstreamAuthority \"disk\" is flagged CRITICAL."""
    src = (
        'UpstreamAuthority "disk" {\n'
        '    plugin_data {\n'
        '        key_file_path = "/etc/spire/ca.key"\n'
        "    }\n"
        "}\n"
    )
    hits = _hits("spiffe-upstream-authority-disk-cleartext", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_upstream_authority_awssecret_safe() -> None:
    """UpstreamAuthority \"aws_secret\" (KMS-backed) does NOT fire rule 8."""
    src = 'UpstreamAuthority "aws_secret" {\n    plugin_data {}\n}\n'
    assert not _hits("spiffe-upstream-authority-disk-cleartext", src)


# ---------- Rule 9: parent_id chain too deep -----------------------------


def test_parent_id_deep_chain_fires() -> None:
    """A parent_id with 4+ path segments is flagged."""
    src = 'entry {\n    parent_id = "spiffe://acme/spire/agent/k8s/node/pool/a"\n}\n'
    assert _hits("spiffe-parent-id-chain-too-deep", src)


def test_parent_id_shallow_chain_safe() -> None:
    """A shallow parent_id (2 segments) does NOT fire rule 9."""
    src = 'entry {\n    parent_id = "spiffe://acme/spire/agent"\n}\n'
    assert not _hits("spiffe-parent-id-chain-too-deep", src)


# ---------- Rule 10: OIDC discovery provider block -----------------------


def test_oidc_provider_block_fires() -> None:
    """An OIDCProvider stanza is surfaced for issuer/JWKS review."""
    src = 'OIDCProvider {\n    issuer = "https://oidc.acme/"\n}\n'
    assert _hits("spiffe-oidc-discovery-provider-block", src)


def test_no_oidc_block_safe() -> None:
    """A config without an OIDCProvider block does NOT fire rule 10."""
    src = 'server {\n    trust_domain = "spire.cluster.local"\n}\n'
    assert not _hits("spiffe-oidc-discovery-provider-block", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_findings_sorted_and_deduped() -> None:
    """Findings come out sorted by (line, column, rule_id) and deduped."""
    src = (
        'server {\n'
        '    trust_domain = "mesh.example.com"\n'
        '}\n'
        'UpstreamAuthority "disk" {\n'
        '    key_file_path = "/etc/spire/ca.key"\n'
        '}\n'
        'jwt_svid {\n'
        '    audience = [ "*" ]\n'
        '}\n'
    )
    findings = ssp.scan_text(src)
    assert findings
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line,
            curr.column,
            curr.rule_id,
        )
    keys = [(f.rule_id, f.line, f.column, f.matched_text) for f in findings]
    assert len(keys) == len(set(keys))
