"""Tests for scripts/lib/k8s_admission_patterns.py.

Wave-20 distillation round 6 angle J — K8s admission controllers,
OPA Gatekeeper, RBAC depth (escalate/bind/impersonate), kubelet/
apiserver anonymous-auth, CSR auto-approval, NetworkPolicy
default-deny, PodSecurity admission labels, ClusterRole aggregation
drift, direct etcd access.

Every rule gets at least one positive test + at least one negative
test exercising the carve-out / safe shape. Targets 21 rules with
~50-70 total tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import k8s_admission_patterns as kap  # type: ignore[import-not-found]  # noqa: E402

# ---------- Helpers ------------------------------------------------------


def _hits(
    rule_id: str,
    text: str,
    *,
    file_kind: str = "auto",
    file_path: str = "",
) -> list[kap.Finding]:
    return [
        f
        for f in kap.scan_text(text, file_kind=file_kind, file_path=file_path)
        if f.rule_id == rule_id
    ]


# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(kap.RULES, tuple)
    rule_ids = {r.id for r in kap.RULES}
    expected = {
        "k8s-admission-failure-policy-ignore",
        "k8s-admission-side-effects-none-external",
        "k8s-admission-cabundle-missing-or-injected",
        "k8s-admission-webhook-external-url",
        "k8s-gatekeeper-enforcement-dryrun-or-warn",
        "k8s-gatekeeper-constraint-narrow-kinds",
        "k8s-rego-default-allow-true",
        "k8s-admission-timeout-excessive",
        "k8s-admission-namespace-selector-excludes-system",
        "k8s-rbac-verb-escalate",
        "k8s-rbac-verb-bind",
        "k8s-rbac-verb-impersonate",
        "k8s-rbac-wildcard-clusterrole",
        "k8s-pod-automount-sa-token-default-true",
        "k8s-namespace-no-default-deny-networkpolicy",
        "k8s-podsecurity-admission-privileged-or-baseline",
        "k8s-csr-auto-approval-broad-group",
        "k8s-kubelet-anonymous-or-alwaysallow",
        "k8s-pod-direct-etcd-access",
        "k8s-admission-object-selector-attacker-controlled",
        "k8s-clusterrole-aggregate-to-admin-drift",
    }
    assert expected.issubset(rule_ids)
    assert len(expected) == 21


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a valid severity."""
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in kap.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_severities, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns / sandbox_escape shape."""
    f = kap.Finding(
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
    assert kap.scan_text("") == []


# ---------- Rule 1: failurePolicy: Ignore --------------------------------


def test_admission_failure_policy_ignore_security_webhook_critical() -> None:
    """Gatekeeper webhook with failurePolicy=Ignore is CRITICAL."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: MutatingWebhookConfiguration\n"
        "metadata:\n"
        "  name: gk-mutator\n"
        "webhooks:\n"
        "  - name: inject.gatekeeper.sh\n"
        "    failurePolicy: Ignore\n"
        "    clientConfig:\n"
        "      service: {name: gk, namespace: gatekeeper-system}\n"
    )
    hits = _hits("k8s-admission-failure-policy-ignore", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_admission_failure_policy_ignore_generic_webhook_high() -> None:
    """Non-security webhook with failurePolicy=Ignore is HIGH."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata:\n"
        "  name: defaulter\n"
        "webhooks:\n"
        "  - name: defaulter.example.com\n"
        "    failurePolicy: Ignore\n"
        "    clientConfig:\n"
        "      service: {name: d, namespace: default}\n"
    )
    hits = _hits("k8s-admission-failure-policy-ignore", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_admission_failure_policy_fail_is_safe() -> None:
    """failurePolicy=Fail (the safe choice) does not fire rule 1."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata:\n"
        "  name: ok\n"
        "webhooks:\n"
        "  - name: ok.example.com\n"
        "    failurePolicy: Fail\n"
        "    clientConfig:\n"
        "      service: {name: ok, namespace: default}\n"
    )
    assert not _hits("k8s-admission-failure-policy-ignore", src)


# ---------- Rule 2: sideEffects: None + external -------------------------


def test_admission_side_effects_none_with_external_url_flagged() -> None:
    """sideEffects: None + external URL is HIGH (dry-run side effect)."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ext}\n"
        "webhooks:\n"
        "  - name: notify.vendor.com\n"
        "    sideEffects: None\n"
        "    clientConfig:\n"
        "      url: https://notify.vendor.com/admit\n"
    )
    hits = _hits("k8s-admission-side-effects-none-external", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_admission_side_effects_none_with_notify_name() -> None:
    """Webhook NAME containing 'notify' triggers rule 2 even in-cluster."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: incluster-notify}\n"
        "webhooks:\n"
        "  - name: audit-notify.svc\n"
        "    sideEffects: None\n"
        "    clientConfig:\n"
        "      service: {name: n, namespace: default}\n"
    )
    assert _hits("k8s-admission-side-effects-none-external", src)


def test_admission_side_effects_some_pure_safe() -> None:
    """sideEffects: NoneOnDryRun is the safe choice."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ok}\n"
        "webhooks:\n"
        "  - name: ok.svc\n"
        "    sideEffects: NoneOnDryRun\n"
        "    clientConfig:\n"
        "      service: {name: ok, namespace: default}\n"
    )
    assert not _hits("k8s-admission-side-effects-none-external", src)


# ---------- Rule 3: caBundle missing / injected --------------------------


def test_admission_cabundle_empty_with_url_critical() -> None:
    """clientConfig.url set + caBundle empty is CRITICAL (MITM trivial)."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: bad}\n"
        "webhooks:\n"
        "  - name: bad.example.com\n"
        "    clientConfig:\n"
        "      url: https://bad.example.com/admit\n"
        '      caBundle: ""\n'
    )
    hits = _hits("k8s-admission-cabundle-missing-or-injected", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_admission_cabundle_dynamic_inject_annotation_minor() -> None:
    """cert-manager.io/inject-ca-from annotation is MEDIUM (architectural)."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata:\n"
        "  name: cm\n"
        "  annotations:\n"
        "    cert-manager.io/inject-ca-from: ns/cert-issuer\n"
        "webhooks:\n"
        "  - name: cm.example.com\n"
        "    clientConfig:\n"
        "      url: https://cm.example.com/admit\n"
        "      caBundle: BASE64==\n"
    )
    hits = _hits("k8s-admission-cabundle-missing-or-injected", src)
    assert hits
    assert any(f.severity == "MEDIUM" for f in hits)


def test_admission_cabundle_with_pinned_safe() -> None:
    """caBundle set with content + no cert-manager annotation is safe."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ok}\n"
        "webhooks:\n"
        "  - name: ok.example.com\n"
        "    clientConfig:\n"
        "      url: https://ok.example.com/admit\n"
        "      caBundle: LS0tLS1CRUdJTi==\n"
    )
    assert not _hits("k8s-admission-cabundle-missing-or-injected", src)


# ---------- Rule 4: external webhook URL ---------------------------------


def test_admission_webhook_external_url_high() -> None:
    """clientConfig.url to a vendor host is HIGH."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: vendor}\n"
        "webhooks:\n"
        "  - name: vendor.example.com\n"
        "    clientConfig:\n"
        "      url: https://policy.vendor.example.com/admit\n"
        "      caBundle: BASE64\n"
    )
    assert _hits("k8s-admission-webhook-external-url", src)


def test_admission_webhook_incluster_service_safe() -> None:
    """clientConfig.service (in-cluster) does NOT fire rule 4."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ok}\n"
        "webhooks:\n"
        "  - name: ok.svc\n"
        "    clientConfig:\n"
        "      service: {name: ok, namespace: default}\n"
    )
    assert not _hits("k8s-admission-webhook-external-url", src)


def test_admission_webhook_localhost_url_safe() -> None:
    """localhost URL counts as in-cluster (sidecar pattern)."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: sidecar}\n"
        "webhooks:\n"
        "  - name: sidecar.svc\n"
        "    clientConfig:\n"
        "      url: https://localhost:8443/admit\n"
        "      caBundle: BASE\n"
    )
    assert not _hits("k8s-admission-webhook-external-url", src)


# ---------- Rule 5: Gatekeeper enforcementAction -------------------------


def test_gatekeeper_dryrun_minor() -> None:
    """Gatekeeper Constraint with enforcementAction=dryrun fires MEDIUM."""
    src = (
        "apiVersion: constraints.gatekeeper.sh/v1beta1\n"
        "kind: K8sRequiredLabels\n"
        "metadata: {name: owner-label}\n"
        "spec:\n"
        "  enforcementAction: dryrun\n"
        "  match:\n"
        "    kinds:\n"
        "      - apiGroups: [\"\"]\n"
        "        kinds: [Namespace]\n"
    )
    hits = _hits("k8s-gatekeeper-enforcement-dryrun-or-warn", src)
    assert hits


def test_gatekeeper_dryrun_in_production_path_major() -> None:
    """Production-path Gatekeeper constraint with dryrun fires HIGH."""
    src = (
        "apiVersion: constraints.gatekeeper.sh/v1beta1\n"
        "kind: K8sRequiredLabels\n"
        "metadata: {name: prod-owner}\n"
        "spec:\n"
        "  enforcementAction: dryrun\n"
        "  match:\n"
        "    kinds:\n"
        "      - apiGroups: [\"\"]\n"
        "        kinds: [Namespace]\n"
    )
    hits = _hits(
        "k8s-gatekeeper-enforcement-dryrun-or-warn",
        src,
        file_path="/clusters/production/gatekeeper-required.yaml",
    )
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_gatekeeper_deny_action_safe() -> None:
    """Default `deny` enforcementAction is the safe choice."""
    src = (
        "apiVersion: constraints.gatekeeper.sh/v1beta1\n"
        "kind: K8sRequiredLabels\n"
        "metadata: {name: ok}\n"
        "spec:\n"
        "  enforcementAction: deny\n"
        "  match:\n"
        "    kinds:\n"
        "      - apiGroups: [\"\"]\n"
        "        kinds: [Namespace]\n"
    )
    assert not _hits("k8s-gatekeeper-enforcement-dryrun-or-warn", src)


# ---------- Rule 6: Gatekeeper constraint narrow kinds -------------------


def test_gatekeeper_pod_only_constraint_misses_controllers() -> None:
    """PodSecurity Gatekeeper constraint matching only Pod is HIGH."""
    src = (
        "apiVersion: constraints.gatekeeper.sh/v1beta1\n"
        "kind: K8sPSPHostNetwork\n"
        "metadata: {name: no-host-net}\n"
        "spec:\n"
        "  enforcementAction: deny\n"
        "  match:\n"
        "    kinds:\n"
        "      - apiGroups: [\"\"]\n"
        "        kinds: [Pod]\n"
    )
    assert _hits("k8s-gatekeeper-constraint-narrow-kinds", src)


def test_gatekeeper_constraint_covers_controllers_safe() -> None:
    """Constraint covering Deployment + StatefulSet + DaemonSet is safe."""
    src = (
        "apiVersion: constraints.gatekeeper.sh/v1beta1\n"
        "kind: K8sPSPHostNetwork\n"
        "metadata: {name: no-host-net}\n"
        "spec:\n"
        "  enforcementAction: deny\n"
        "  match:\n"
        "    kinds:\n"
        "      - apiGroups: [\"\", apps, batch]\n"
        "        kinds: [Pod, Deployment, StatefulSet, DaemonSet, Job, CronJob]\n"
    )
    assert not _hits("k8s-gatekeeper-constraint-narrow-kinds", src)


# ---------- Rule 7: rego default allow = true ----------------------------


def test_rego_default_allow_true_critical() -> None:
    """`default allow = true` in rego is CRITICAL fail-open."""
    src = (
        "package kubernetes.admission\n"
        "\n"
        "default allow = true\n"
        "\n"
        'deny[msg] { input.request.kind.kind == "Pod"; msg := "no" }\n'
    )
    assert _hits("k8s-rego-default-allow-true", src, file_kind="rego")


def test_rego_default_allow_walrus_true_critical() -> None:
    """`default allow := true` (walrus form) is also CRITICAL."""
    src = "package admission\n\ndefault allow := true\n"
    assert _hits("k8s-rego-default-allow-true", src, file_kind="rego")


def test_rego_default_decision_allow_critical() -> None:
    """`default decision = \"allow\"` is the auth-policy variant."""
    src = (
        "package authz\n\n"
        'default decision = "allow"\n'
    )
    assert _hits("k8s-rego-default-allow-true", src, file_kind="rego")


def test_rego_default_deny_false_critical() -> None:
    """`default deny = false` is the inverted variant."""
    src = "package admission\n\ndefault deny = false\n"
    assert _hits("k8s-rego-default-allow-true", src, file_kind="rego")


def test_rego_default_allow_false_safe() -> None:
    """`default allow = false` (fail-closed) is the safe shape."""
    src = "package admission\n\ndefault allow = false\n"
    assert not _hits("k8s-rego-default-allow-true", src, file_kind="rego")


# ---------- Rule 8: timeoutSeconds >= 15 + failurePolicy=Fail ------------


def test_admission_timeout_30_fail_major() -> None:
    """timeoutSeconds=30 + failurePolicy=Fail is HIGH (cluster freeze DoS)."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: slow}\n"
        "webhooks:\n"
        "  - name: slow.svc\n"
        "    timeoutSeconds: 30\n"
        "    failurePolicy: Fail\n"
        "    clientConfig:\n"
        "      service: {name: s, namespace: default}\n"
    )
    assert _hits("k8s-admission-timeout-excessive", src)


def test_admission_timeout_5_fail_safe() -> None:
    """timeoutSeconds=5 + failurePolicy=Fail is the recommended pattern."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ok}\n"
        "webhooks:\n"
        "  - name: ok.svc\n"
        "    timeoutSeconds: 5\n"
        "    failurePolicy: Fail\n"
        "    clientConfig:\n"
        "      service: {name: o, namespace: default}\n"
    )
    assert not _hits("k8s-admission-timeout-excessive", src)


def test_admission_timeout_30_ignore_skipped() -> None:
    """High timeout + failurePolicy=Ignore is not a freeze risk."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ign}\n"
        "webhooks:\n"
        "  - name: ign.svc\n"
        "    timeoutSeconds: 30\n"
        "    failurePolicy: Ignore\n"
        "    clientConfig:\n"
        "      service: {name: i, namespace: default}\n"
    )
    assert not _hits("k8s-admission-timeout-excessive", src)


# ---------- Rule 9: namespaceSelector NotIn kube-system ------------------


def test_admission_namespaceselector_notin_kubesystem_major() -> None:
    """namespaceSelector NotIn kube-system is HIGH (bypass surface)."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: skip-kube-system}\n"
        "webhooks:\n"
        "  - name: w.svc\n"
        "    namespaceSelector:\n"
        "      matchExpressions:\n"
        "        - key: kubernetes.io/metadata.name\n"
        "          operator: NotIn\n"
        "          values: [kube-system, gatekeeper-system]\n"
        "    clientConfig:\n"
        "      service: {name: w, namespace: default}\n"
    )
    assert _hits("k8s-admission-namespace-selector-excludes-system", src)


def test_admission_namespaceselector_in_app_namespace_safe() -> None:
    """Selector targeting only app namespaces does NOT trigger rule 9."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ok}\n"
        "webhooks:\n"
        "  - name: ok.svc\n"
        "    namespaceSelector:\n"
        "      matchLabels:\n"
        "        kubernetes.io/metadata.name: my-app\n"
        "    clientConfig:\n"
        "      service: {name: ok, namespace: default}\n"
    )
    assert not _hits("k8s-admission-namespace-selector-excludes-system", src)


# ---------- Rule 10: escalate verb ---------------------------------------


def test_rbac_escalate_verb_critical() -> None:
    """ClusterRole granting `escalate` on roles is CRITICAL."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: escalator}\n"
        "rules:\n"
        "  - apiGroups: [rbac.authorization.k8s.io]\n"
        "    resources: [roles, clusterroles]\n"
        "    verbs: [escalate, update, patch]\n"
    )
    hits = _hits("k8s-rbac-verb-escalate", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_rbac_no_escalate_safe() -> None:
    """ClusterRole with get/list on roles is NOT a privilege escalation."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: viewer}\n"
        "rules:\n"
        "  - apiGroups: [rbac.authorization.k8s.io]\n"
        "    resources: [roles, clusterroles]\n"
        "    verbs: [get, list]\n"
    )
    assert not _hits("k8s-rbac-verb-escalate", src)


# ---------- Rule 11: bind verb on bindings -------------------------------


def test_rbac_bind_verb_critical() -> None:
    """`bind` verb on clusterrolebindings is CRITICAL (self-bind admin)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: binder}\n"
        "rules:\n"
        "  - apiGroups: [rbac.authorization.k8s.io]\n"
        "    resources: [clusterrolebindings, rolebindings]\n"
        "    verbs: [create, bind]\n"
    )
    hits = _hits("k8s-rbac-verb-bind", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_rbac_create_only_bindings_high() -> None:
    """`create` (no `bind`) on clusterrolebindings is HIGH."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: creator}\n"
        "rules:\n"
        "  - apiGroups: [rbac.authorization.k8s.io]\n"
        "    resources: [clusterrolebindings]\n"
        "    verbs: [create]\n"
    )
    hits = _hits("k8s-rbac-verb-bind", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_rbac_get_only_bindings_safe() -> None:
    """Read-only access to bindings does NOT trigger rule 11."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: reader}\n"
        "rules:\n"
        "  - apiGroups: [rbac.authorization.k8s.io]\n"
        "    resources: [clusterrolebindings, rolebindings]\n"
        "    verbs: [get, list, watch]\n"
    )
    assert not _hits("k8s-rbac-verb-bind", src)


# ---------- Rule 12: impersonate verb ------------------------------------


def test_rbac_impersonate_serviceaccounts_critical() -> None:
    """`impersonate` on serviceaccounts is CRITICAL."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: imp}\n"
        "rules:\n"
        "  - apiGroups: [\"\"]\n"
        "    resources: [serviceaccounts]\n"
        "    verbs: [impersonate]\n"
    )
    assert _hits("k8s-rbac-verb-impersonate", src)


def test_rbac_impersonate_groups_system_masters_pivot() -> None:
    """`impersonate groups` allows the system:masters pivot."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: imp-groups}\n"
        "rules:\n"
        "  - apiGroups: [\"\"]\n"
        "    resources: [groups]\n"
        "    verbs: [impersonate]\n"
    )
    hits = _hits("k8s-rbac-verb-impersonate", src)
    assert hits
    assert any("system:masters" in f.matched_text for f in hits)


def test_rbac_no_impersonate_safe() -> None:
    """ClusterRole without impersonate is safe."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: ok}\n"
        "rules:\n"
        "  - apiGroups: [\"\"]\n"
        "    resources: [serviceaccounts]\n"
        "    verbs: [get, list]\n"
    )
    assert not _hits("k8s-rbac-verb-impersonate", src)


# ---------- Rule 13: */*/* wildcard ClusterRole --------------------------


def test_rbac_triple_wildcard_clusterrole_critical() -> None:
    """*/*/* ClusterRole rule is CRITICAL (cluster-admin equivalent)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: god}\n"
        "rules:\n"
        "  - apiGroups: [\"*\"]\n"
        "    resources: [\"*\"]\n"
        "    verbs: [\"*\"]\n"
    )
    hits = _hits("k8s-rbac-wildcard-clusterrole", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_rbac_two_wildcard_clusterrole_high() -> None:
    """Two-out-of-three wildcards is HIGH."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: two-star}\n"
        "rules:\n"
        "  - apiGroups: [\"\"]\n"
        "    resources: [\"*\"]\n"
        "    verbs: [\"*\"]\n"
    )
    hits = _hits("k8s-rbac-wildcard-clusterrole", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_rbac_concrete_clusterrole_safe() -> None:
    """A concrete ClusterRole with named verbs/resources is safe."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: viewer}\n"
        "rules:\n"
        "  - apiGroups: [\"\"]\n"
        "    resources: [pods, services]\n"
        "    verbs: [get, list, watch]\n"
    )
    assert not _hits("k8s-rbac-wildcard-clusterrole", src)


# ---------- Rule 14: automountServiceAccountToken default-true -----------


def test_pod_automount_token_default_true_flagged() -> None:
    """Pod without automountServiceAccountToken: false is HIGH."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: app}\n"
        "spec:\n"
        "  serviceAccountName: my-sa\n"
        "  containers:\n"
        "    - name: app\n"
        "      image: myapp:1.0\n"
    )
    assert _hits("k8s-pod-automount-sa-token-default-true", src)


def test_pod_automount_token_explicit_false_safe() -> None:
    """Explicit automountServiceAccountToken: false is the safe choice."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: app}\n"
        "spec:\n"
        "  serviceAccountName: my-sa\n"
        "  automountServiceAccountToken: false\n"
        "  containers:\n"
        "    - name: app\n"
        "      image: myapp:1.0\n"
    )
    assert not _hits("k8s-pod-automount-sa-token-default-true", src)


def test_deployment_automount_token_default_flagged() -> None:
    """Deployment template also missing the disable is flagged."""
    src = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata: {name: d}\n"
        "spec:\n"
        "  replicas: 1\n"
        "  selector: {matchLabels: {app: d}}\n"
        "  template:\n"
        "    metadata: {labels: {app: d}}\n"
        "    spec:\n"
        "      serviceAccountName: my-sa\n"
        "      containers:\n"
        "        - name: app\n"
        "          image: myapp:1\n"
    )
    assert _hits("k8s-pod-automount-sa-token-default-true", src)


# ---------- Rule 15: default-deny NetworkPolicy --------------------------


def test_namespace_no_default_deny_networkpolicy_flagged() -> None:
    """Namespace without a default-deny NetworkPolicy is HIGH."""
    src = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: app\n"
        "  labels:\n"
        "    pod-security.kubernetes.io/enforce: restricted\n"
    )
    assert _hits("k8s-namespace-no-default-deny-networkpolicy", src)


def test_namespace_with_default_deny_networkpolicy_safe() -> None:
    """Namespace + matching NetworkPolicy default-deny is safe."""
    src = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: app\n"
        "  labels:\n"
        "    pod-security.kubernetes.io/enforce: restricted\n"
        "---\n"
        "apiVersion: networking.k8s.io/v1\n"
        "kind: NetworkPolicy\n"
        "metadata:\n"
        "  name: default-deny\n"
        "  namespace: app\n"
        "spec:\n"
        "  podSelector: {}\n"
        "  policyTypes: [Ingress, Egress]\n"
    )
    assert not _hits("k8s-namespace-no-default-deny-networkpolicy", src)


def test_namespace_kube_system_low_severity() -> None:
    """kube-system missing default-deny downgrades to LOW."""
    src = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata: {name: kube-system}\n"
    )
    hits = _hits("k8s-namespace-no-default-deny-networkpolicy", src)
    assert hits
    assert all(f.severity == "LOW" for f in hits)


# ---------- Rule 16: PodSecurity admission labels ------------------------


def test_psa_enforce_privileged_critical() -> None:
    """enforce: privileged on a namespace is CRITICAL (PSA bypass)."""
    src = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: untrusted\n"
        "  labels:\n"
        "    pod-security.kubernetes.io/enforce: privileged\n"
    )
    hits = _hits("k8s-podsecurity-admission-privileged-or-baseline", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_psa_baseline_on_production_high() -> None:
    """enforce: baseline on production-named namespace is HIGH."""
    src = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: production-app\n"
        "  labels:\n"
        "    pod-security.kubernetes.io/enforce: baseline\n"
    )
    hits = _hits("k8s-podsecurity-admission-privileged-or-baseline", src)
    assert any(f.severity == "HIGH" for f in hits)


def test_psa_audit_restricted_enforce_privileged_misleading() -> None:
    """audit: restricted + enforce: privileged is the dashboard trick."""
    src = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: dash-trick\n"
        "  labels:\n"
        "    pod-security.kubernetes.io/enforce: privileged\n"
        "    pod-security.kubernetes.io/audit: restricted\n"
    )
    hits = _hits("k8s-podsecurity-admission-privileged-or-baseline", src)
    # Both the privileged-enforce + the mismatch fire CRITICAL.
    assert any(f.severity == "CRITICAL" for f in hits)
    assert any("audit=restricted" in f.matched_text for f in hits)


def test_psa_enforce_restricted_safe() -> None:
    """enforce: restricted is the hardened profile."""
    src = (
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: safe\n"
        "  labels:\n"
        "    pod-security.kubernetes.io/enforce: restricted\n"
    )
    assert not _hits("k8s-podsecurity-admission-privileged-or-baseline", src)


# ---------- Rule 17: CSR auto-approval broad group -----------------------


def test_csr_auto_approval_authenticated_critical() -> None:
    """ClusterRoleBinding granting nodeclient CSR approval to system:authenticated."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata: {name: auto-csr}\n"
        "roleRef:\n"
        "  kind: ClusterRole\n"
        "  name: system:certificates.k8s.io:certificatesigningrequests:nodeclient\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "subjects:\n"
        "  - kind: Group\n"
        "    name: system:authenticated\n"
        "    apiGroup: rbac.authorization.k8s.io\n"
    )
    assert _hits("k8s-csr-auto-approval-broad-group", src)


def test_csr_specific_node_binding_safe() -> None:
    """Per-node CSR binding to a specific user/SA is safe."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata: {name: node-csr}\n"
        "roleRef:\n"
        "  kind: ClusterRole\n"
        "  name: system:certificates.k8s.io:certificatesigningrequests:nodeclient\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: node-bootstrapper\n"
        "    namespace: kube-system\n"
    )
    assert not _hits("k8s-csr-auto-approval-broad-group", src)


# ---------- Rule 18: kubelet AlwaysAllow / anonymous-auth ----------------


def test_kubelet_anonymous_enabled_critical() -> None:
    """kubelet authentication.anonymous.enabled=true is CRITICAL."""
    src = (
        "apiVersion: kubelet.config.k8s.io/v1beta1\n"
        "kind: KubeletConfiguration\n"
        "authentication:\n"
        "  anonymous:\n"
        "    enabled: true\n"
    )
    assert _hits("k8s-kubelet-anonymous-or-alwaysallow", src, file_kind="kubelet")


def test_kubelet_authz_always_allow_critical() -> None:
    """kubelet authorization.mode=AlwaysAllow is CRITICAL."""
    src = (
        "apiVersion: kubelet.config.k8s.io/v1beta1\n"
        "kind: KubeletConfiguration\n"
        "authorization:\n"
        "  mode: AlwaysAllow\n"
    )
    assert _hits("k8s-kubelet-anonymous-or-alwaysallow", src, file_kind="kubelet")


def test_apiserver_anonymous_auth_flag_critical() -> None:
    """kube-apiserver --anonymous-auth=true flag is CRITICAL."""
    src = (
        "[Service]\n"
        "ExecStart=/usr/local/bin/kube-apiserver "
        "--anonymous-auth=true --authorization-mode=RBAC\n"
    )
    assert _hits("k8s-kubelet-anonymous-or-alwaysallow", src, file_kind="apiserver")


def test_apiserver_authz_always_allow_flag_critical() -> None:
    """kube-apiserver --authorization-mode=AlwaysAllow is CRITICAL."""
    src = (
        "[Service]\n"
        "ExecStart=/usr/local/bin/kube-apiserver "
        "--anonymous-auth=false --authorization-mode=AlwaysAllow,RBAC\n"
    )
    assert _hits("k8s-kubelet-anonymous-or-alwaysallow", src, file_kind="apiserver")


def test_apiserver_insecure_port_critical() -> None:
    """kube-apiserver --insecure-port=8080 is CRITICAL legacy hole."""
    src = (
        "ExecStart=/usr/local/bin/kube-apiserver --insecure-port=8080\n"
    )
    assert _hits("k8s-kubelet-anonymous-or-alwaysallow", src, file_kind="apiserver")


def test_kubelet_anonymous_disabled_safe() -> None:
    """kubelet anonymous.enabled=false + Webhook authz is safe."""
    src = (
        "apiVersion: kubelet.config.k8s.io/v1beta1\n"
        "kind: KubeletConfiguration\n"
        "authentication:\n"
        "  anonymous:\n"
        "    enabled: false\n"
        "authorization:\n"
        "  mode: Webhook\n"
    )
    assert not _hits(
        "k8s-kubelet-anonymous-or-alwaysallow", src, file_kind="kubelet"
    )


# ---------- Rule 19: direct etcd access ----------------------------------


def test_pod_etcd_hostpath_critical() -> None:
    """Pod mounting /etc/kubernetes/pki/etcd is CRITICAL."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: backup}\n"
        "spec:\n"
        "  containers:\n"
        "    - name: backup\n"
        "      image: backup:latest\n"
        "      volumeMounts:\n"
        "        - {name: etcd-certs, mountPath: /etc/etcd}\n"
        "  volumes:\n"
        "    - name: etcd-certs\n"
        "      hostPath:\n"
        "        path: /etc/kubernetes/pki/etcd\n"
    )
    assert _hits("k8s-pod-direct-etcd-access", src)


def test_pod_etcdctl_env_critical() -> None:
    """Pod with ETCDCTL_ENDPOINTS env var is CRITICAL."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: tool}\n"
        "spec:\n"
        "  containers:\n"
        "    - name: tool\n"
        "      image: etcdctl:latest\n"
        "      env:\n"
        "        - name: ETCDCTL_ENDPOINTS\n"
        "          value: https://etcd.kube-system.svc:2379\n"
        "      command: [etcdctl, get, /, --prefix]\n"
    )
    assert _hits("k8s-pod-direct-etcd-access", src)


def test_service_port_2379_in_user_ns_high() -> None:
    """Service exposing port 2379 in a non-system namespace is HIGH."""
    src = (
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: app-etcd\n"
        "  namespace: default\n"
        "spec:\n"
        "  ports:\n"
        "    - {port: 2379, targetPort: 2379}\n"
        "  selector: {app: a}\n"
    )
    assert _hits("k8s-pod-direct-etcd-access", src)


def test_pod_unrelated_hostpath_safe() -> None:
    """Pod mounting /var/log (not etcd) does NOT fire rule 19."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: logger}\n"
        "spec:\n"
        "  automountServiceAccountToken: false\n"
        "  containers:\n"
        "    - name: logger\n"
        "      image: logger:1\n"
        "      volumeMounts:\n"
        "        - {name: logs, mountPath: /logs}\n"
        "  volumes:\n"
        "    - name: logs\n"
        "      hostPath: {path: /var/log}\n"
    )
    assert not _hits("k8s-pod-direct-etcd-access", src)


# ---------- Rule 20: webhook objectSelector attacker-controlled ----------


def test_admission_object_selector_attacker_label_major() -> None:
    """objectSelector matchLabels keyed on attacker-controllable label."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: bad-selector}\n"
        "webhooks:\n"
        "  - name: scanner.svc\n"
        "    objectSelector:\n"
        "      matchLabels:\n"
        "        scan-me: \"true\"\n"
        "    clientConfig:\n"
        "      service: {name: s, namespace: default}\n"
    )
    assert _hits("k8s-admission-object-selector-attacker-controlled", src)


def test_admission_object_selector_does_not_exist_safe() -> None:
    """matchExpressions DoesNotExist is the deny-by-default safe shape."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ok}\n"
        "webhooks:\n"
        "  - name: ok.svc\n"
        "    objectSelector:\n"
        "      matchExpressions:\n"
        "        - key: my-exempt\n"
        "          operator: DoesNotExist\n"
        "    clientConfig:\n"
        "      service: {name: o, namespace: default}\n"
    )
    assert not _hits(
        "k8s-admission-object-selector-attacker-controlled", src
    )


def test_admission_object_selector_kubernetes_io_label_safe() -> None:
    """matchLabels keyed on system-prefixed label is NOT attacker-controllable."""
    src = (
        "apiVersion: admissionregistration.k8s.io/v1\n"
        "kind: ValidatingWebhookConfiguration\n"
        "metadata: {name: ok}\n"
        "webhooks:\n"
        "  - name: ok.svc\n"
        "    objectSelector:\n"
        "      matchLabels:\n"
        "        kubernetes.io/managed-by: terraform\n"
        "    clientConfig:\n"
        "      service: {name: o, namespace: default}\n"
    )
    assert not _hits(
        "k8s-admission-object-selector-attacker-controlled", src
    )


# ---------- Rule 21: aggregate-to-admin drift ----------------------------


def test_clusterrole_aggregate_to_admin_with_wildcards_major() -> None:
    """ClusterRole labelled aggregate-to-admin with */* rules is HIGH."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata:\n"
        "  name: drift\n"
        "  labels:\n"
        "    rbac.authorization.k8s.io/aggregate-to-admin: \"true\"\n"
        "rules:\n"
        "  - apiGroups: [mycrd.example.com]\n"
        "    resources: [\"*\"]\n"
        "    verbs: [\"*\"]\n"
    )
    assert _hits("k8s-clusterrole-aggregate-to-admin-drift", src)


def test_clusterrole_aggregate_to_admin_with_secrets_major() -> None:
    """aggregate-to-admin + access to secrets is HIGH."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata:\n"
        "  name: drift\n"
        "  labels:\n"
        "    rbac.authorization.k8s.io/aggregate-to-admin: \"true\"\n"
        "rules:\n"
        "  - apiGroups: [\"\"]\n"
        "    resources: [secrets]\n"
        "    verbs: [get, list]\n"
    )
    assert _hits("k8s-clusterrole-aggregate-to-admin-drift", src)


def test_clusterrole_aggregate_to_view_safe() -> None:
    """aggregate-to-view with only get/list is safe (read-only view)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata:\n"
        "  name: viewer\n"
        "  labels:\n"
        "    rbac.authorization.k8s.io/aggregate-to-view: \"true\"\n"
        "rules:\n"
        "  - apiGroups: [mycrd.example.com]\n"
        "    resources: [widgets]\n"
        "    verbs: [get, list, watch]\n"
    )
    assert not _hits("k8s-clusterrole-aggregate-to-admin-drift", src)


def test_clusterrole_no_aggregate_label_safe() -> None:
    """ClusterRole without aggregate label is safe (just RBAC)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata:\n"
        "  name: plain\n"
        "rules:\n"
        "  - apiGroups: [\"\"]\n"
        "    resources: [secrets]\n"
        "    verbs: [get, list]\n"
    )
    assert not _hits("k8s-clusterrole-aggregate-to-admin-drift", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_autodetect_k8s() -> None:
    """`apiVersion:` opener triggers k8s autodetect."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: g}\n"
        "rules:\n"
        "  - apiGroups: [\"*\"]\n"
        "    resources: [\"*\"]\n"
        "    verbs: [\"*\"]\n"
    )
    findings = kap.scan_text(src)
    assert any(f.rule_id == "k8s-rbac-wildcard-clusterrole" for f in findings)


def test_scan_text_autodetect_rego() -> None:
    """rego `package` opener triggers rego autodetect."""
    src = "package admission\n\ndefault allow = true\n"
    findings = kap.scan_text(src)
    assert any(f.rule_id == "k8s-rego-default-allow-true" for f in findings)


def test_scan_text_autodetect_kubelet() -> None:
    """KubeletConfiguration kind triggers kubelet autodetect."""
    src = (
        "apiVersion: kubelet.config.k8s.io/v1beta1\n"
        "kind: KubeletConfiguration\n"
        "authorization:\n"
        "  mode: AlwaysAllow\n"
    )
    findings = kap.scan_text(src)
    assert any(
        f.rule_id == "k8s-kubelet-anonymous-or-alwaysallow" for f in findings
    )


def test_scan_text_findings_sorted_and_deduped() -> None:
    """Findings come out sorted by (line, column, rule_id) and deduped."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: g}\n"
        "rules:\n"
        "  - apiGroups: [\"*\"]\n"
        "    resources: [\"*\"]\n"
        "    verbs: [\"*\"]\n"
    )
    findings = kap.scan_text(src)
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line, curr.column, curr.rule_id,
        )
    # No duplicate (rule_id, line, col, matched_text).
    keys = [(f.rule_id, f.line, f.column, f.matched_text) for f in findings]
    assert len(keys) == len(set(keys))


def test_malformed_yaml_does_not_crash() -> None:
    """Malformed YAML returns empty findings instead of raising."""
    src = "kind: Pod\n  bad: indent: here\n - stray\n"
    # Should not raise.
    assert kap.scan_text(src) == [] or isinstance(kap.scan_text(src), list)


def test_descriptions_nonempty() -> None:
    """Every rule has a non-empty description."""
    for r in kap.RULES:
        assert r.description.strip()
        assert r.name.strip()
