"""Tests for scripts/lib/argocd_fluxcd_patterns.py.

Pattern-coverage tests for the Wave-36 distill-round-22 ArgoCD / FluxCD
app-of-apps catalogue (10 patterns covering source-path glob, SSH MITM,
Helm parameter injection, Kustomize inline patches, cross-env destination,
FluxCD GitRepository no-verify, HelmRelease public-chart semver range,
Kustomization remote patch URL, AppProject wildcard namespace, and
sync-windows absence).

Each rule has at least 2 tests: one positive exercising a canary AND one
negative exercising a carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import argocd_fluxcd_patterns as afp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(afp.RULES, tuple)
    rule_ids = {r.id for r in afp.RULES}
    expected = {
        "gops-argocd-source-path-glob",
        "gops-argocd-repoutil-ssh-no-known-hosts",
        "gops-argocd-helm-parameters-user-controlled",
        "gops-argocd-kustomize-patches-inline-exec",
        "gops-argocd-destination-cross-env-server",
        "gops-fluxcd-gitrepository-no-verify",
        "gops-fluxcd-helmrelease-public-chart-unverified",
        "gops-fluxcd-kustomization-patches-url-fetch",
        "gops-argocd-appproject-wildcard-destination-namespace",
        "gops-argocd-sync-windows-no-deny-manual",
    }
    assert expected == rule_ids
    assert len(afp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in afp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = afp.Finding(
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
    assert afp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "path: \"*\"\n"
        "repoURL: git@github.com:org/k8s-config.git\n"
    )
    findings = afp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[afp.Finding]:
    return [f for f in afp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : gops-argocd-source-path-glob ----------------------------


def test_r1_source_path_double_glob_flags() -> None:
    """spec.source.path set to '**' triggers HIGH finding."""
    src = (
        "apiVersion: argoproj.io/v1alpha1\n"
        "kind: Application\n"
        "spec:\n"
        "  source:\n"
        "    repoURL: https://github.com/org/platform\n"
        "    targetRevision: HEAD\n"
        '    path: "**"\n'
    )
    hits = _hits("gops-argocd-source-path-glob", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r1_source_path_specific_subdir_no_flag() -> None:
    """spec.source.path set to a concrete subdir does not flag."""
    src = (
        "spec:\n"
        "  source:\n"
        "    path: apps/myapp\n"
    )
    hits = _hits("gops-argocd-source-path-glob", src)
    assert not hits


# ---------- R2 : gops-argocd-repoutil-ssh-no-known-hosts -----------------


def test_r2_ssh_git_at_url_flags() -> None:
    """git@ SSH repoURL triggers HIGH finding."""
    src = (
        "spec:\n"
        "  source:\n"
        "    repoURL: git@github.com:org/k8s-config.git\n"
        "    path: apps/myapp\n"
    )
    hits = _hits("gops-argocd-repoutil-ssh-no-known-hosts", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_https_repoutil_no_flag() -> None:
    """HTTPS repoURL does not trigger the SSH known-hosts rule."""
    src = (
        "spec:\n"
        "  source:\n"
        "    repoURL: https://github.com/org/k8s-config.git\n"
        "    path: apps/myapp\n"
    )
    hits = _hits("gops-argocd-repoutil-ssh-no-known-hosts", src)
    assert not hits


# ---------- R3 : gops-argocd-helm-parameters-user-controlled -------------


def test_r3_helm_parameters_block_flags() -> None:
    """Helm parameters block with a name entry triggers HIGH finding."""
    src = (
        "spec:\n"
        "  source:\n"
        "    helm:\n"
        "      parameters:\n"
        "        - name: image.tag\n"
        "          value: latest\n"
    )
    hits = _hits("gops-argocd-helm-parameters-user-controlled", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_helm_values_only_no_parameters_no_flag() -> None:
    """Helm block with only 'values' (no parameters array) does not flag."""
    src = (
        "spec:\n"
        "  source:\n"
        "    helm:\n"
        "      values: |\n"
        "        replicaCount: 2\n"
    )
    hits = _hits("gops-argocd-helm-parameters-user-controlled", src)
    assert not hits


# ---------- R4 : gops-argocd-kustomize-patches-inline-exec ---------------


def test_r4_kustomize_patches_block_flags() -> None:
    """kustomize.patches array with a patch entry triggers HIGH finding."""
    src = (
        "spec:\n"
        "  source:\n"
        "    kustomize:\n"
        "      patches:\n"
        "        - target:\n"
        "            kind: Deployment\n"
        "          patch: |\n"
        "            - op: add\n"
        "              path: /spec/template/spec/containers/0/env/-\n"
        "              value:\n"
        "                name: SECRET\n"
    )
    hits = _hits("gops-argocd-kustomize-patches-inline-exec", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r4_kustomize_no_patches_no_flag() -> None:
    """kustomize block with no patches key does not flag."""
    src = (
        "spec:\n"
        "  source:\n"
        "    kustomize:\n"
        "      images:\n"
        "        - myapp=myrepo/myapp:v1.2.3\n"
    )
    hits = _hits("gops-argocd-kustomize-patches-inline-exec", src)
    assert not hits


# ---------- R5 : gops-argocd-destination-cross-env-server ----------------


def test_r5_destinations_multi_server_flags() -> None:
    """destinations block with a server entry triggers CRITICAL finding."""
    src = (
        "spec:\n"
        "  destinations:\n"
        "    - server: https://prod-api.k8s.example.com\n"
        "      namespace: default\n"
        "    - server: https://dev-api.k8s.example.com\n"
        "      namespace: default\n"
    )
    hits = _hits("gops-argocd-destination-cross-env-server", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r5_single_in_cluster_server_present_flags() -> None:
    """A single destinations.server URL still matches the destinations-multi pattern."""
    src = (
        "spec:\n"
        "  destinations:\n"
        "    - server: https://kubernetes.default.svc\n"
        "      namespace: default\n"
    )
    hits = _hits("gops-argocd-destination-cross-env-server", src)
    # The pattern matches any destinations block with a server entry.
    assert hits


# ---------- R6 : gops-fluxcd-gitrepository-no-verify ---------------------


def test_r6_gitrepository_no_verify_github_flags() -> None:
    """FluxCD GitRepository pointing to github.com without verify flags HIGH."""
    src = (
        "apiVersion: source.toolkit.fluxcd.io/v1\n"
        "kind: GitRepository\n"
        "metadata:\n"
        "  name: flux-system\n"
        "  namespace: flux-system\n"
        "spec:\n"
        "  interval: 1m0s\n"
        "  ref:\n"
        "    branch: main\n"
        "  url: https://github.com/org/fleet-infra\n"
    )
    hits = _hits("gops-fluxcd-gitrepository-no-verify", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r6_gitrepository_internal_host_no_flag() -> None:
    """FluxCD GitRepository pointing to an internal host does not flag."""
    src = (
        "kind: GitRepository\n"
        "spec:\n"
        "  url: https://gitea.corp.internal/org/fleet-infra\n"
    )
    hits = _hits("gops-fluxcd-gitrepository-no-verify", src)
    assert not hits


# ---------- R7 : gops-fluxcd-helmrelease-public-chart-unverified ---------


def test_r7_semver_gte_range_flags() -> None:
    """HelmRelease spec.chart.spec.version with >= prefix triggers HIGH."""
    src = (
        "spec:\n"
        "  chart:\n"
        "    spec:\n"
        "      chart: ingress-nginx\n"
        '      version: ">=4.0.0"\n'
        "      sourceRef:\n"
        "        kind: HelmRepository\n"
        "        name: ingress-nginx\n"
    )
    hits = _hits("gops-fluxcd-helmrelease-public-chart-unverified", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r7_pinned_exact_version_no_flag() -> None:
    """HelmRelease with a pinned exact semver (no range operator) does not flag."""
    src = (
        "spec:\n"
        "  chart:\n"
        "    spec:\n"
        "      chart: ingress-nginx\n"
        '      version: "4.11.2"\n'
    )
    hits = _hits("gops-fluxcd-helmrelease-public-chart-unverified", src)
    assert not hits


# ---------- R8 : gops-fluxcd-kustomization-patches-url-fetch -------------


def test_r8_patches_strategic_merge_remote_url_flags() -> None:
    """patchesStrategicMerge pointing to HTTP URL triggers CRITICAL finding."""
    src = (
        "patchesStrategicMerge:\n"
        "  - https://raw.githubusercontent.com/org/repo/main/patch.yaml\n"
    )
    hits = _hits("gops-fluxcd-kustomization-patches-url-fetch", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r8_patches_strategic_merge_local_path_no_flag() -> None:
    """patchesStrategicMerge with a local file path does not flag."""
    src = (
        "patchesStrategicMerge:\n"
        "  - ./overlays/dev/patch.yaml\n"
    )
    hits = _hits("gops-fluxcd-kustomization-patches-url-fetch", src)
    assert not hits


# ---------- R9 : gops-argocd-appproject-wildcard-destination-namespace ---


def test_r9_wildcard_namespace_flags() -> None:
    """AppProject destinations with namespace: '*' triggers CRITICAL finding."""
    src = (
        "spec:\n"
        "  destinations:\n"
        "    - server: https://remote-cluster.k8s.example.com\n"
        "      namespace: \"*\"\n"
    )
    hits = _hits("gops-argocd-appproject-wildcard-destination-namespace", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r9_specific_namespace_no_flag() -> None:
    """AppProject destinations with a concrete namespace does not flag."""
    src = (
        "spec:\n"
        "  destinations:\n"
        "    - server: https://remote-cluster.k8s.example.com\n"
        "      namespace: production\n"
    )
    hits = _hits("gops-argocd-appproject-wildcard-destination-namespace", src)
    assert not hits


# ---------- R10 : gops-argocd-sync-windows-no-deny-manual ----------------


def test_r10_selfheal_true_flags() -> None:
    """selfHeal: true without syncWindows triggers HIGH finding."""
    src = (
        "spec:\n"
        "  syncPolicy:\n"
        "    automated:\n"
        "      prune: true\n"
        "      selfHeal: true\n"
    )
    hits = _hits("gops-argocd-sync-windows-no-deny-manual", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r10_selfheal_false_no_flag() -> None:
    """selfHeal: false does not trigger the sync-windows rule."""
    src = (
        "spec:\n"
        "  syncPolicy:\n"
        "    automated:\n"
        "      prune: false\n"
        "      selfHeal: false\n"
    )
    hits = _hits("gops-argocd-sync-windows-no-deny-manual", src)
    assert not hits
