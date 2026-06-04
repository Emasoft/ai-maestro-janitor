"""Tests for scripts/lib/crossplane_patterns.py.

Pattern-coverage tests for the Wave-37 distill-round-23 Crossplane
composition + provider-trust catalogue (10 attack classes: untrusted
compositeTypeRef group / unpinned package, plain ProviderConfig secretRef,
floating Configuration tag, Function Deployment with an admin SA, unguarded
FromCompositeFieldPath patch, XRD with no schema, provider SA bound to
cluster-admin, status.atProvider credential leak, :latest image with
automatic revision activation, and privileged Function securityContext).

The source proposal uses negative lookahead/lookbehind for several signals;
this module rewrites those as RE2-safe candidate + absence checks. Each
attack class has at least one positive test (a realistic vulnerable snippet
that MUST match) and at least one negative test (a safe snippet that MUST NOT
match), proving no false-positive.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import crossplane_patterns as xpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented attack-class rule IDs."""
    assert isinstance(xpp.RULES, tuple)
    rule_ids = {r.id for r in xpp.RULES}
    expected = {
        "xplane-compositetyperef-untrusted-group",
        "xplane-providerconfig-plain-secretref",
        "xplane-configuration-floating-tag",
        "xplane-function-deployment-admin-sa",
        "xplane-patch-fromcomposite-no-guardrail",
        "xplane-xrd-no-schema-validation",
        "xplane-provider-sa-cluster-admin",
        "xplane-status-atprovider-credential-leak",
        "xplane-package-latest-image-auto-activation",
        "xplane-function-privileged-securitycontext",
    }
    assert expected == rule_ids


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in xpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors argocd_fluxcd_patterns.Finding shape."""
    f = xpp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="CRITICAL", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert xpp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, column, rule_id)."""
    src = (
        "image: crossplane/function-patch-and-transform:latest\n"
        "revisionActivationPolicy: Automatic\n"
    )
    findings = xpp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[xpp.Finding]:
    return [f for f in xpp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : xplane-compositetyperef-untrusted-group -----------------


def test_r1_compositetyperef_public_group_flags() -> None:
    """compositeTypeRef with a public-TLD group triggers HIGH finding."""
    src = (
        "spec:\n"
        "  compositeTypeRef:\n"
        "    apiVersion: vendor.cloud/v1alpha1\n"
        "    group: vendor.cloud\n"
        "    kind: XDatabase\n"
    )
    hits = _hits("xplane-compositetyperef-untrusted-group", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r1_unpinned_upbound_package_flags() -> None:
    """An Upbound package with no @sha256: digest triggers HIGH finding."""
    src = "spec:\n  package: xpkg.upbound.io/crossplane-contrib/provider-aws:v0.40.0\n"
    hits = _hits("xplane-compositetyperef-untrusted-group", src)
    assert hits


def test_r1_internal_group_no_flag() -> None:
    """compositeTypeRef pointing at an internal/corp group does not flag."""
    src = (
        "spec:\n"
        "  compositeTypeRef:\n"
        "    group: platform.internal.example\n"
        "    kind: XDatabase\n"
    )
    hits = _hits("xplane-compositetyperef-untrusted-group", src)
    assert not hits


def test_r1_digest_pinned_package_no_flag() -> None:
    """An Upbound package pinned by @sha256: digest does not flag."""
    src = (
        "spec:\n"
        "  package: xpkg.upbound.io/crossplane-contrib/provider-aws@sha256:"
        + ("a" * 64)
        + "\n"
    )
    hits = _hits("xplane-compositetyperef-untrusted-group", src)
    assert not hits


# ---------- R2 : xplane-providerconfig-plain-secretref -------------------


def test_r2_providerconfig_plain_secretref_flags() -> None:
    """ProviderConfig with a bare secretRef triggers HIGH finding."""
    src = (
        "apiVersion: aws.upbound.io/v1beta1\n"
        "kind: ProviderConfig\n"
        "metadata:\n"
        "  name: default\n"
        "spec:\n"
        "  credentials:\n"
        "    source: Secret\n"
        "    secretRef:\n"
        "      name: aws-creds\n"
        "      namespace: crossplane-system\n"
        "      key: creds\n"
    )
    hits = _hits("xplane-providerconfig-plain-secretref", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_providerconfig_irsa_no_secretref_no_flag() -> None:
    """ProviderConfig using IRSA/web-identity (no secretRef) does not flag."""
    src = (
        "kind: ProviderConfig\n"
        "metadata:\n"
        "  name: default\n"
        "spec:\n"
        "  credentials:\n"
        "    source: WebIdentity\n"
        "    webIdentity:\n"
        "      roleARN: arn:aws:iam::111122223333:role/crossplane\n"
    )
    hits = _hits("xplane-providerconfig-plain-secretref", src)
    assert not hits


# ---------- R3 : xplane-configuration-floating-tag -----------------------


def test_r3_configuration_latest_tag_flags() -> None:
    """A Configuration package with :latest triggers HIGH finding."""
    src = (
        "apiVersion: pkg.crossplane.io/v1\n"
        "kind: Configuration\n"
        "spec:\n"
        "  package: registry.upbound.io/acme/platform:latest\n"
    )
    hits = _hits("xplane-configuration-floating-tag", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_ghcr_package_no_digest_flags() -> None:
    """A ghcr.io package with no @sha256: digest triggers HIGH finding."""
    src = "spec:\n  package: ghcr.io/acme/configuration-platform:v1.2.3\n"
    hits = _hits("xplane-configuration-floating-tag", src)
    assert hits


def test_r3_digest_pinned_configuration_no_flag() -> None:
    """A Configuration package pinned to a digest does not flag."""
    src = (
        "kind: Configuration\n"
        "spec:\n"
        "  package: registry.upbound.io/acme/platform@sha256:" + ("b" * 64) + "\n"
    )
    hits = _hits("xplane-configuration-floating-tag", src)
    assert not hits


# ---------- R4 : xplane-function-deployment-admin-sa ---------------------


def test_r4_function_admin_sa_flags() -> None:
    """A DeploymentRuntimeConfig with serviceAccountName: default triggers CRITICAL."""
    src = (
        "apiVersion: pkg.crossplane.io/v1beta1\n"
        "kind: DeploymentRuntimeConfig\n"
        "metadata:\n"
        "  name: privileged-fn\n"
        "spec:\n"
        "  serviceAccountTemplate:\n"
        "    metadata:\n"
        "      name: default\n"
        "  deploymentTemplate:\n"
        "    spec:\n"
        "      template:\n"
        "        spec:\n"
        "          serviceAccountName: cluster-admin\n"
    )
    hits = _hits("xplane-function-deployment-admin-sa", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r4_drc_no_automount_disable_flags() -> None:
    """A DeploymentRuntimeConfig containers spec without automount=false flags."""
    src = (
        "kind: DeploymentRuntimeConfig\n"
        "spec:\n"
        "  deploymentTemplate:\n"
        "    spec:\n"
        "      template:\n"
        "        spec:\n"
        "          serviceAccountName: fn-runner\n"
        "          containers:\n"
        "            - name: package-runtime\n"
    )
    hits = _hits("xplane-function-deployment-admin-sa", src)
    assert hits


def test_r4_named_sa_with_automount_false_no_flag() -> None:
    """A non-default SA plus automountServiceAccountToken: false does not flag."""
    src = (
        "kind: DeploymentRuntimeConfig\n"
        "spec:\n"
        "  deploymentTemplate:\n"
        "    spec:\n"
        "      template:\n"
        "        spec:\n"
        "          serviceAccountName: fn-runner\n"
        "          automountServiceAccountToken: false\n"
        "          containers:\n"
        "            - name: package-runtime\n"
    )
    hits = _hits("xplane-function-deployment-admin-sa", src)
    assert not hits


# ---------- R5 : xplane-patch-fromcomposite-no-guardrail -----------------


def test_r5_fromcomposite_no_guardrail_flags() -> None:
    """A FromCompositeFieldPath patch with no transforms/policy triggers MEDIUM."""
    src = (
        "patches:\n"
        "  - type: FromCompositeFieldPath\n"
        "    fromFieldPath: spec.parameters.roleArn\n"
        "    toFieldPath: spec.forProvider.roleArn\n"
    )
    hits = _hits("xplane-patch-fromcomposite-no-guardrail", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r5_fromcomposite_with_policy_no_flag() -> None:
    """A FromCompositeFieldPath patch with a policy guardrail does not flag."""
    src = (
        "patches:\n"
        "  - type: FromCompositeFieldPath\n"
        "    fromFieldPath: spec.parameters.roleArn\n"
        "    toFieldPath: spec.forProvider.roleArn\n"
        "    policy:\n"
        "      fromFieldPath: Required\n"
    )
    hits = _hits("xplane-patch-fromcomposite-no-guardrail", src)
    assert not hits


# ---------- R6 : xplane-xrd-no-schema-validation -------------------------


def test_r6_xrd_version_no_schema_flags() -> None:
    """A served XRD version with no schema subkey triggers HIGH finding."""
    src = (
        "spec:\n"
        "  versions:\n"
        "    - name: v1alpha1\n"
        "      served: true\n"
        "      referenceable: true\n"
    )
    hits = _hits("xplane-xrd-no-schema-validation", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r6_xrd_version_with_schema_no_flag() -> None:
    """A served XRD version that declares an openAPIV3Schema does not flag."""
    src = (
        "spec:\n"
        "  versions:\n"
        "    - name: v1alpha1\n"
        "      served: true\n"
        "      referenceable: true\n"
        "      schema:\n"
        "        openAPIV3Schema:\n"
        "          type: object\n"
    )
    hits = _hits("xplane-xrd-no-schema-validation", src)
    assert not hits


# ---------- R7 : xplane-provider-sa-cluster-admin ------------------------


def test_r7_provider_sa_cluster_admin_flags() -> None:
    """A ClusterRoleBinding giving a provider SA cluster-admin triggers CRITICAL."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata:\n"
        "  name: provider-aws-admin\n"
        "roleRef:\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "  kind: ClusterRole\n"
        "  name: cluster-admin\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: provider-aws-1234\n"
        "    namespace: crossplane-system\n"
    )
    hits = _hits("xplane-provider-sa-cluster-admin", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r7_provider_sa_scoped_role_no_flag() -> None:
    """A provider SA bound to a scoped ClusterRole (not cluster-admin) does not flag."""
    src = (
        "kind: ClusterRoleBinding\n"
        "roleRef:\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "  kind: ClusterRole\n"
        "  name: crossplane-provider-aws-edit\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: provider-aws-1234\n"
        "    namespace: crossplane-system\n"
    )
    hits = _hits("xplane-provider-sa-cluster-admin", src)
    assert not hits


# ---------- R8 : xplane-status-atprovider-credential-leak ----------------


def test_r8_status_atprovider_patch_flags() -> None:
    """A ToCompositeFieldPath patch sourcing status.atProvider triggers HIGH."""
    src = (
        "patches:\n"
        "  - type: ToCompositeFieldPath\n"
        "    fromFieldPath: status.atProvider.accessKey\n"
        "    toFieldPath: status.dbAccessKey\n"
    )
    hits = _hits("xplane-status-atprovider-credential-leak", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r8_tocomposite_safe_field_no_flag() -> None:
    """A ToCompositeFieldPath patch sourcing a non-secret status field does not flag."""
    src = (
        "patches:\n"
        "  - type: ToCompositeFieldPath\n"
        "    fromFieldPath: status.conditions[0].status\n"
        "    toFieldPath: status.ready\n"
    )
    hits = _hits("xplane-status-atprovider-credential-leak", src)
    assert not hits


# ---------- R9 : xplane-package-latest-image-auto-activation -------------


def test_r9_latest_image_flags() -> None:
    """A Function/Provider image with :latest triggers HIGH finding."""
    src = "spec:\n  image: crossplane/function-patch-and-transform:latest\n"
    hits = _hits("xplane-package-latest-image-auto-activation", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r9_revision_automatic_flags() -> None:
    """revisionActivationPolicy: Automatic triggers HIGH finding."""
    src = "spec:\n  revisionActivationPolicy: Automatic\n"
    hits = _hits("xplane-package-latest-image-auto-activation", src)
    assert hits


def test_r9_pinned_image_manual_activation_no_flag() -> None:
    """A pinned image tag with Manual revision activation does not flag."""
    src = (
        "spec:\n"
        "  image: crossplane/function-patch-and-transform:v0.7.0\n"
        "  revisionActivationPolicy: Manual\n"
    )
    hits = _hits("xplane-package-latest-image-auto-activation", src)
    assert not hits


# ---------- R10 : xplane-function-privileged-securitycontext -------------


def test_r10_privileged_true_flags() -> None:
    """privileged: true in a securityContext triggers CRITICAL finding."""
    src = (
        "securityContext:\n"
        "  privileged: true\n"
    )
    hits = _hits("xplane-function-privileged-securitycontext", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r10_allow_privilege_escalation_flags() -> None:
    """allowPrivilegeEscalation: true triggers CRITICAL finding."""
    src = (
        "securityContext:\n"
        "  allowPrivilegeEscalation: true\n"
    )
    hits = _hits("xplane-function-privileged-securitycontext", src)
    assert hits


def test_r10_drc_no_runasnonroot_flags() -> None:
    """A DeploymentRuntimeConfig containers spec without runAsNonRoot: true flags."""
    src = (
        "kind: DeploymentRuntimeConfig\n"
        "spec:\n"
        "  deploymentTemplate:\n"
        "    spec:\n"
        "      template:\n"
        "        spec:\n"
        "          containers:\n"
        "            - name: package-runtime\n"
    )
    hits = _hits("xplane-function-privileged-securitycontext", src)
    assert hits


def test_r10_hardened_securitycontext_no_flag() -> None:
    """A hardened DeploymentRuntimeConfig (runAsNonRoot true, no privileged) does not flag."""
    src = (
        "kind: DeploymentRuntimeConfig\n"
        "spec:\n"
        "  deploymentTemplate:\n"
        "    spec:\n"
        "      template:\n"
        "        spec:\n"
        "          securityContext:\n"
        "            runAsNonRoot: true\n"
        "          containers:\n"
        "            - name: package-runtime\n"
        "              securityContext:\n"
        "                allowPrivilegeEscalation: false\n"
        "                privileged: false\n"
    )
    hits = _hits("xplane-function-privileged-securitycontext", src)
    assert not hits
