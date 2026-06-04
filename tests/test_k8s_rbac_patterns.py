"""Tests for scripts/lib/k8s_rbac_patterns.py.

Wave-37 distillation round 23 — Kubernetes RBAC drift + ServiceAccount
over-privilege. Orthogonal to k8s_admission_patterns: focuses on RBAC
grant scope (wildcard ClusterRole, cross-namespace secret read, pods/exec,
escalate/bind, cluster-admin binding, system:authenticated binding,
aggregation-label injection) and the automount-token red flag.

Every rule gets at least one positive test (realistic vulnerable YAML
that MUST match) and at least one negative test (a safe shape that MUST
NOT match).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import k8s_rbac_patterns as krp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[krp.Finding]:
    return [f for f in krp.scan_text(text) if f.rule_id == rule_id]


# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES is a tuple containing every advertised RBAC rule id."""
    assert isinstance(krp.RULES, tuple)
    rule_ids = {r.id for r in krp.RULES}
    expected = {
        "k8s-rbac-wildcard-clusterrole-grant",
        "k8s-rbac-bind-system-authenticated",
        "k8s-rbac-pods-exec-grant",
        "k8s-rbac-cluster-secret-read",
        "k8s-rbac-automount-token-true",
        "k8s-rbac-aggregationrule-broad-selector",
        "k8s-rbac-escalate-or-bind-verb",
        "k8s-rbac-clusteradmin-binding",
    }
    assert expected == rule_ids
    assert len(expected) == 8


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a valid severity."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in krp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the sibling pattern-module Finding shape."""
    f = krp.Finding(
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
    assert f.matched_text == "m"
    assert f.severity == "HIGH"


def test_scan_text_empty_returns_empty() -> None:
    """An empty input yields no findings."""
    assert krp.scan_text("") == []


def test_descriptions_nonempty() -> None:
    """Every rule has a non-empty name and description."""
    for r in krp.RULES:
        assert r.name.strip()
        assert r.description.strip()


# ---------- Rule 1: wildcard ClusterRole ---------------------------------


def test_wildcard_clusterrole_grant_high() -> None:
    """ClusterRole with resources:* AND verbs:* is HIGH (cluster-admin)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: god}\n"
        "rules:\n"
        '  - apiGroups: ["*"]\n'
        '    resources: ["*"]\n'
        '    verbs: ["*"]\n'
    )
    hits = _hits("k8s-rbac-wildcard-clusterrole-grant", src)
    assert hits
    assert any(f.severity == "HIGH" for f in hits)


def test_wildcard_concrete_clusterrole_safe() -> None:
    """A concrete ClusterRole with named verbs/resources does NOT fire."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: viewer}\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [pods, services]\n"
        "    verbs: [get, list, watch]\n"
    )
    assert not _hits("k8s-rbac-wildcard-clusterrole-grant", src)


# ---------- Rule 2: system:authenticated binding -------------------------


def test_bind_system_authenticated_high() -> None:
    """ClusterRoleBinding to system:authenticated is HIGH (public grant)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata: {name: open}\n"
        "roleRef: {kind: ClusterRole, name: edit, apiGroup: rbac.authorization.k8s.io}\n"
        "subjects:\n"
        "  - kind: Group\n"
        "    name: system:authenticated\n"
        "    apiGroup: rbac.authorization.k8s.io\n"
    )
    assert _hits("k8s-rbac-bind-system-authenticated", src)


def test_bind_named_serviceaccount_safe() -> None:
    """A binding to a specific ServiceAccount does NOT fire rule 2."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata: {name: scoped}\n"
        "roleRef: {kind: ClusterRole, name: view, apiGroup: rbac.authorization.k8s.io}\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: app-sa\n"
        "    namespace: default\n"
    )
    assert not _hits("k8s-rbac-bind-system-authenticated", src)


# ---------- Rule 3: pods/exec --------------------------------------------


def test_pods_exec_grant_high() -> None:
    """A Role granting pods/exec is HIGH (arbitrary code execution)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: Role\n"
        "metadata: {name: dev, namespace: app}\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [pods/exec]\n"
        "    verbs: [create]\n"
    )
    assert _hits("k8s-rbac-pods-exec-grant", src)


def test_pods_get_only_safe() -> None:
    """A Role granting only pods get/list (no exec) does NOT fire rule 3."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: Role\n"
        "metadata: {name: viewer, namespace: app}\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [pods]\n"
        "    verbs: [get, list, watch]\n"
    )
    assert not _hits("k8s-rbac-pods-exec-grant", src)


# ---------- Rule 4: cross-namespace secret read --------------------------


def test_cluster_secret_read_high() -> None:
    """ClusterRole get/list on secrets is HIGH (cross-namespace exfil)."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: secret-reader}\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [secrets]\n"
        "    verbs: [get, list, watch]\n"
    )
    assert _hits("k8s-rbac-cluster-secret-read", src)


def test_system_clusterrole_secret_read_safe() -> None:
    """A system: ClusterRole reading secrets is a built-in, not drift."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata:\n"
        "  name: system:controller:persistent-volume-binder\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [secrets]\n"
        "    verbs: [get, list, watch]\n"
    )
    assert not _hits("k8s-rbac-cluster-secret-read", src)


def test_namespaced_role_secret_read_safe() -> None:
    """A namespaced Role (not ClusterRole) on secrets does NOT fire rule 4."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: Role\n"
        "metadata: {name: local-secret, namespace: app}\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [secrets]\n"
        "    verbs: [get]\n"
    )
    assert not _hits("k8s-rbac-cluster-secret-read", src)


# ---------- Rule 5: automountServiceAccountToken: true --------------------


def test_automount_token_true_medium() -> None:
    """automountServiceAccountToken: true is MEDIUM (SA-token exposure)."""
    src = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata: {name: d}\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      automountServiceAccountToken: true\n"
        "      containers:\n"
        "        - {name: app, image: app:1}\n"
    )
    hits = _hits("k8s-rbac-automount-token-true", src)
    assert hits
    assert any(f.severity == "MEDIUM" for f in hits)


def test_automount_token_false_safe() -> None:
    """automountServiceAccountToken: false is the safe choice."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata: {name: p}\n"
        "spec:\n"
        "  automountServiceAccountToken: false\n"
        "  containers:\n"
        "    - {name: app, image: app:1}\n"
    )
    assert not _hits("k8s-rbac-automount-token-true", src)


# ---------- Rule 6: aggregationRule broad selector -----------------------


def test_aggregationrule_selector_medium() -> None:
    """A ClusterRole aggregationRule.clusterRoleSelectors fires MEDIUM."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: monitoring}\n"
        "aggregationRule:\n"
        "  clusterRoleSelectors:\n"
        "    - matchLabels:\n"
        "        app: monitoring\n"
        "rules: []\n"
    )
    assert _hits("k8s-rbac-aggregationrule-broad-selector", src)


def test_no_aggregationrule_safe() -> None:
    """A plain ClusterRole without an aggregationRule does NOT fire rule 6."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: plain}\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [configmaps]\n"
        "    verbs: [get]\n"
    )
    assert not _hits("k8s-rbac-aggregationrule-broad-selector", src)


# ---------- Rule 7: escalate / bind verb ---------------------------------


def test_escalate_verb_critical() -> None:
    """The escalate verb (list-item form) is CRITICAL."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: escalator}\n"
        "rules:\n"
        "  - apiGroups: [rbac.authorization.k8s.io]\n"
        "    resources: [roles]\n"
        "    verbs:\n"
        "      - escalate\n"
        "      - update\n"
    )
    hits = _hits("k8s-rbac-escalate-or-bind-verb", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_bind_verb_inline_array_critical() -> None:
    """The bind verb (inline array form) is CRITICAL."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: binder}\n"
        "rules:\n"
        "  - apiGroups: [rbac.authorization.k8s.io]\n"
        "    resources: [clusterrolebindings]\n"
        '    verbs: ["create", "bind"]\n'
    )
    assert _hits("k8s-rbac-escalate-or-bind-verb", src)


def test_no_escalate_bind_safe() -> None:
    """Ordinary verbs (get/list/create) do NOT fire rule 7."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: ok}\n"
        "rules:\n"
        '  - apiGroups: [""]\n'
        "    resources: [pods]\n"
        "    verbs: [get, list, create]\n"
    )
    assert not _hits("k8s-rbac-escalate-or-bind-verb", src)


# ---------- Rule 8: cluster-admin binding --------------------------------


def test_clusteradmin_binding_serviceaccount_critical() -> None:
    """ClusterRoleBinding cluster-admin to a workload SA is CRITICAL."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata: {name: oops}\n"
        "roleRef:\n"
        "  kind: ClusterRole\n"
        "  name: cluster-admin\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: ci-runner\n"
        "    namespace: ci\n"
    )
    hits = _hits("k8s-rbac-clusteradmin-binding", src)
    assert hits
    assert any(f.severity == "CRITICAL" for f in hits)


def test_clusteradmin_binding_to_system_subject_safe() -> None:
    """cluster-admin bound to a system: subject is the built-in wiring."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata: {name: cluster-admin}\n"
        "roleRef:\n"
        "  kind: ClusterRole\n"
        "  name: cluster-admin\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "subjects:\n"
        "  - kind: Group\n"
        "    name: system:masters\n"
        "    apiGroup: rbac.authorization.k8s.io\n"
    )
    assert not _hits("k8s-rbac-clusteradmin-binding", src)


def test_non_clusteradmin_binding_safe() -> None:
    """A binding to a non-admin ClusterRole does NOT fire rule 8."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata: {name: viewers}\n"
        "roleRef:\n"
        "  kind: ClusterRole\n"
        "  name: view\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: app\n"
        "    namespace: default\n"
    )
    assert not _hits("k8s-rbac-clusteradmin-binding", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_findings_sorted_and_deduped() -> None:
    """Findings come out sorted by (line, column, rule_id) and deduped."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata: {name: god}\n"
        "rules:\n"
        '  - apiGroups: ["*"]\n'
        '    resources: ["*"]\n'
        '    verbs: ["*"]\n'
    )
    findings = krp.scan_text(src)
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line,
            curr.column,
            curr.rule_id,
        )
    keys = [(f.rule_id, f.line, f.column, f.matched_text) for f in findings]
    assert len(keys) == len(set(keys))
