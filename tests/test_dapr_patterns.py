"""Tests for scripts/lib/dapr_patterns.py.

Wave-37 distillation round 23 — Dapr sidecar / Distributed Application
Runtime misconfiguration. Covers Dapr's own access-control default,
app-channel TLS, secret-store path, pubsub scope, tracing sampling,
API-token, input-binding sender restriction, and actor-placement
binding address.

Every rule gets at least one positive test (realistic vulnerable Dapr
YAML that MUST match) and at least one negative test (a safe shape that
MUST NOT match). Two-pass rules (app-channel TLS, input binding) get a
dedicated negative proving the mitigating field suppresses the finding.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import dapr_patterns as dpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[dpp.Finding]:
    return [f for f in dpp.scan_text(text) if f.rule_id == rule_id]


# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES is a tuple containing every advertised Dapr rule id."""
    assert isinstance(dpp.RULES, tuple)
    rule_ids = {r.id for r in dpp.RULES}
    expected = {
        "dapr-access-control-default-allow",
        "dapr-app-channel-no-tls",
        "dapr-secrets-file-baked-path",
        "dapr-pubsub-subscription-no-scope",
        "dapr-tracing-full-sampling",
        "dapr-api-token-static",
        "dapr-input-binding-no-sender-restriction",
        "dapr-placement-non-loopback",
    }
    assert expected == rule_ids
    assert len(expected) == 8


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a valid severity."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in dpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the sibling pattern-module Finding shape."""
    f = dpp.Finding(
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
    assert dpp.scan_text("") == []


def test_descriptions_nonempty() -> None:
    """Every rule has a non-empty name and description."""
    for r in dpp.RULES:
        assert r.name.strip()
        assert r.description.strip()


# ---------- Rule 1: accessControl defaultAction: allow -------------------


def test_default_action_allow_high() -> None:
    """accessControl defaultAction: allow is HIGH (default-deny flipped)."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Configuration\n"
        "metadata: {name: appconfig}\n"
        "spec:\n"
        "  accessControl:\n"
        "    defaultAction: allow\n"
        "    policies: []\n"
    )
    hits = _hits("dapr-access-control-default-allow", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_default_action_deny_safe() -> None:
    """accessControl defaultAction: deny is the safe baseline."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Configuration\n"
        "metadata: {name: appconfig}\n"
        "spec:\n"
        "  accessControl:\n"
        "    defaultAction: deny\n"
    )
    assert not _hits("dapr-access-control-default-allow", src)


# ---------- Rule 2: appPort without app-channel TLS ----------------------


def test_app_port_no_tls_medium() -> None:
    """appPort without appProtocol https/grpcs is MEDIUM (plaintext channel)."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Configuration\n"
        "metadata: {name: appconfig}\n"
        "spec:\n"
        "  appPort: 3000\n"
    )
    hits = _hits("dapr-app-channel-no-tls", src)
    assert hits
    assert any(f.severity == "MEDIUM" for f in hits)


def test_app_port_with_https_safe() -> None:
    """appPort paired with appProtocol https does NOT fire rule 2."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Configuration\n"
        "metadata: {name: appconfig}\n"
        "spec:\n"
        "  appPort: 3000\n"
        "  appProtocol: https\n"
    )
    assert not _hits("dapr-app-channel-no-tls", src)


# ---------- Rule 3: secretsFile baked path -------------------------------


def test_secrets_file_path_medium() -> None:
    """A direct secretsFile path is MEDIUM (secrets baked into image)."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Component\n"
        "metadata: {name: localsecretstore}\n"
        "spec:\n"
        "  type: secretstores.local.file\n"
        "  version: v1\n"
        "  secretsFile: /app/secrets.json\n"
    )
    assert _hits("dapr-secrets-file-baked-path", src)


def test_no_secrets_file_safe() -> None:
    """A component with no secretsFile key does NOT fire rule 3."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Component\n"
        "metadata: {name: vault}\n"
        "spec:\n"
        "  type: secretstores.hashicorp.vault\n"
        "  version: v1\n"
        "  metadata:\n"
        "    - name: vaultAddr\n"
        "      value: https://vault:8200\n"
    )
    assert not _hits("dapr-secrets-file-baked-path", src)


# ---------- Rule 4: pubsub subscription without scope --------------------


def test_subscription_no_scope_medium() -> None:
    """A Subscription topic without subscriptionScopes is MEDIUM."""
    src = (
        "apiVersion: dapr.io/v2alpha1\n"
        "kind: Subscription\n"
        "metadata: {name: order-sub}\n"
        "spec:\n"
        "  pubsubname: pubsub\n"
        "  topic: orders\n"
        "  routes: {default: /orders}\n"
    )
    assert _hits("dapr-pubsub-subscription-no-scope", src)


def test_subscription_with_scope_safe() -> None:
    """A Subscription declaring subscriptionScopes does NOT fire rule 4."""
    src = (
        "apiVersion: dapr.io/v2alpha1\n"
        "kind: Subscription\n"
        "metadata: {name: order-sub}\n"
        "spec:\n"
        "  pubsubname: pubsub\n"
        "  topic: orders\n"
        "  subscriptionScopes:\n"
        "    - orderprocessor\n"
    )
    assert not _hits("dapr-pubsub-subscription-no-scope", src)


# ---------- Rule 5: full trace sampling ----------------------------------


def test_full_sampling_low() -> None:
    """samplingRate '1' (100%) is LOW (PII/token capture)."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Configuration\n"
        "metadata: {name: tracing}\n"
        "spec:\n"
        "  tracing:\n"
        '    samplingRate: "1"\n'
    )
    hits = _hits("dapr-tracing-full-sampling", src)
    assert hits
    assert any(f.severity == "LOW" for f in hits)


def test_partial_sampling_safe() -> None:
    """A fractional samplingRate does NOT fire rule 5."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Configuration\n"
        "metadata: {name: tracing}\n"
        "spec:\n"
        "  tracing:\n"
        '    samplingRate: "0.1"\n'
    )
    assert not _hits("dapr-tracing-full-sampling", src)


# ---------- Rule 6: static API token -------------------------------------


def test_api_token_env_high() -> None:
    """DAPR_API_TOKEN in an env block is HIGH (long-lived bearer cred)."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: app}\n"
        "spec:\n"
        "  containers:\n"
        "    - name: app\n"
        "      env:\n"
        "        - name: DAPR_API_TOKEN\n"
        "          value: s3cr3t-token\n"
    )
    hits = _hits("dapr-api-token-static", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_api_token_annotation_high() -> None:
    """The dapr.io/api-token-secret annotation also fires rule 6."""
    src = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata: {name: app}\n"
        "spec:\n"
        "  template:\n"
        "    metadata:\n"
        "      annotations:\n"
        "        dapr.io/enabled: \"true\"\n"
        "        dapr.io/api-token-secret: dapr-api-token\n"
    )
    assert _hits("dapr-api-token-static", src)


def test_no_api_token_safe() -> None:
    """A pod without a Dapr API token does NOT fire rule 6."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: app}\n"
        "spec:\n"
        "  containers:\n"
        "    - name: app\n"
        "      env:\n"
        "        - name: LOG_LEVEL\n"
        "          value: info\n"
    )
    assert not _hits("dapr-api-token-static", src)


# ---------- Rule 7: input binding without sender restriction -------------


def test_input_binding_no_restriction_high() -> None:
    """A direction: input binding with no sender restriction is HIGH."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Component\n"
        "metadata: {name: cron}\n"
        "spec:\n"
        "  type: bindings.cron\n"
        "  version: v1\n"
        "  direction: input\n"
        "  metadata:\n"
        "    - name: schedule\n"
        '      value: "@every 1m"\n'
    )
    hits = _hits("dapr-input-binding-no-sender-restriction", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_input_binding_with_allowed_origins_safe() -> None:
    """An input binding with allowedOrigins does NOT fire rule 7."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Component\n"
        "metadata: {name: http-in}\n"
        "spec:\n"
        "  type: bindings.http\n"
        "  direction: input\n"
        "  metadata:\n"
        "    - name: allowedOrigins\n"
        '      value: "https://trusted.example.com"\n'
    )
    assert not _hits("dapr-input-binding-no-sender-restriction", src)


def test_output_binding_safe() -> None:
    """A direction: output binding does NOT fire rule 7."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Component\n"
        "metadata: {name: queue-out}\n"
        "spec:\n"
        "  type: bindings.azure.storagequeues\n"
        "  direction: output\n"
        "  metadata:\n"
        "    - name: queueName\n"
        "      value: jobs\n"
    )
    assert not _hits("dapr-input-binding-no-sender-restriction", src)


# ---------- Rule 8: placement on non-loopback ----------------------------


def test_placement_non_loopback_high() -> None:
    """placementHostAddress on a routable host is HIGH (ring poisoning)."""
    src = (
        "spec:\n"
        "  placementHostAddress: dapr-placement.dapr-system.svc:50005\n"
    )
    hits = _hits("dapr-placement-non-loopback", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_placement_loopback_safe() -> None:
    """placementHostAddress on 127.0.0.1 does NOT fire rule 8."""
    src = (
        "spec:\n"
        "  placementHostAddress: 127.0.0.1:50005\n"
    )
    assert not _hits("dapr-placement-non-loopback", src)


def test_placement_localhost_safe() -> None:
    """placementHostAddress on localhost does NOT fire rule 8."""
    src = (
        "spec:\n"
        "  placementHostAddress: localhost:50005\n"
    )
    assert not _hits("dapr-placement-non-loopback", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_findings_sorted_and_deduped() -> None:
    """Findings come out sorted by (line, column, rule_id) and deduped."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Configuration\n"
        "metadata: {name: c}\n"
        "spec:\n"
        "  accessControl:\n"
        "    defaultAction: allow\n"
        "  tracing:\n"
        '    samplingRate: "1"\n'
    )
    findings = dpp.scan_text(src)
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line,
            curr.column,
            curr.rule_id,
        )
    keys = [(f.rule_id, f.line, f.column, f.matched_text) for f in findings]
    assert len(keys) == len(set(keys))


def test_input_binding_multidoc_scoped() -> None:
    """A restriction in a neighbouring doc must not mask an open binding."""
    src = (
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Component\n"
        "metadata: {name: safe-in}\n"
        "spec:\n"
        "  type: bindings.http\n"
        "  direction: input\n"
        "  metadata:\n"
        "    - name: allowedOrigins\n"
        '      value: "https://ok.example.com"\n'
        "---\n"
        "apiVersion: dapr.io/v1alpha1\n"
        "kind: Component\n"
        "metadata: {name: open-in}\n"
        "spec:\n"
        "  type: bindings.cron\n"
        "  direction: input\n"
        "  metadata:\n"
        "    - name: schedule\n"
        '      value: "@every 30s"\n'
    )
    hits = _hits("dapr-input-binding-no-sender-restriction", src)
    assert len(hits) == 1
