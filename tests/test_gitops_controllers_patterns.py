"""Tests for scripts/lib/gitops_controllers_patterns.py.

Pattern-coverage tests for the Wave-28 distill-round-14 gitops-controllers
catalogue (12 GitOps anti-patterns covering FluxCD, ArgoCD and Tekton).
Each rule has at least 2 tests: one positive (canary triggers) and one
negative (safe/carve-out does NOT trigger).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import gitops_controllers_patterns as gcp  # type: ignore[import-not-found]  # noqa: E402

sys.path.insert(0, str(_PROJECT_ROOT / "tests"))
from _fake_secrets import secret  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 12 documented rule IDs."""
    assert isinstance(gcp.RULES, tuple)
    rule_ids = {r.id for r in gcp.RULES}
    expected = {
        "gitops-argocd-admin-password-plaintext",
        "gitops-argocd-repo-url-http-not-https",
        "gitops-argocd-insecure-flag-enabled",
        "gitops-argocd-app-sync-allow-privileged",
        "gitops-flux-git-secret-plaintext",
        "gitops-flux-insecure-skip-tls-verify",
        "gitops-flux-source-oci-no-verify",
        "gitops-tekton-param-injection-script",
        "gitops-tekton-privileged-step-container",
        "gitops-tekton-serviceaccount-default",
        "gitops-gitops-webhook-secret-missing",
        "gitops-argocd-project-clusterresourcewhitelist-all",
    }
    assert expected == rule_ids
    assert len(gcp.RULES) == 12


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in gcp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = gcp.Finding(
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
    assert gcp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "repoURL: http://git.example.com/repo\n"
        "admin.password: plainpassword123\n"
        "repoURL: http://git.example.com/repo2\n"
    )
    result = gcp.scan_text(src)
    lines = [f.line for f in result]
    assert lines == sorted(lines)


# ---------- G01 : argocd-admin-password-plaintext ------------------------


def test_g01_positive_admin_password_literal() -> None:
    """admin.password with a plaintext literal should trigger G01."""
    src = "admin.password: MyS3cretPa55word\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-admin-password-plaintext" in ids


def test_g01_negative_admin_password_empty() -> None:
    """admin.password left empty (placeholder) should NOT trigger G01."""
    src = "admin.password: \n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-admin-password-plaintext" not in ids


# ---------- G02 : argocd-repo-url-http-not-https -------------------------


def test_g02_positive_repo_url_http() -> None:
    """repoURL with http:// should trigger G02."""
    src = "  repoURL: http://github.com/myorg/myrepo.git\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-repo-url-http-not-https" in ids


def test_g02_negative_repo_url_https() -> None:
    """repoURL with https:// must NOT trigger G02."""
    src = "  repoURL: https://github.com/myorg/myrepo.git\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-repo-url-http-not-https" not in ids


# ---------- G03 : argocd-insecure-flag-enabled ---------------------------


def test_g03_positive_insecure_key_true() -> None:
    """insecure: true in a YAML manifest should trigger G03."""
    src = "spec:\n  insecure: true\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-insecure-flag-enabled" in ids


def test_g03_positive_insecure_cli_flag() -> None:
    """argocd-server --insecure in a command spec should trigger G03."""
    src = "command: [argocd-server, --insecure]\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-insecure-flag-enabled" in ids


def test_g03_negative_insecure_false() -> None:
    """insecure: false must NOT trigger G03."""
    src = "spec:\n  insecure: false\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-insecure-flag-enabled" not in ids


# ---------- G04 : argocd-app-sync-allow-privileged -----------------------


def test_g04_positive_allow_privilege_escalation() -> None:
    """allowPrivilegeEscalation: true should trigger G04."""
    src = "securityContext:\n  allowPrivilegeEscalation: true\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-app-sync-allow-privileged" in ids


def test_g04_negative_allow_privilege_escalation_false() -> None:
    """allowPrivilegeEscalation: false must NOT trigger G04."""
    src = "securityContext:\n  allowPrivilegeEscalation: false\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-app-sync-allow-privileged" not in ids


# ---------- G05 : flux-git-secret-plaintext ------------------------------


def test_g05_positive_password_literal() -> None:
    """password: with a plaintext literal value should trigger G05."""
    src = "  password: supersecretpassword1234\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-git-secret-plaintext" in ids


def test_g05_positive_bearer_token_literal() -> None:
    """bearerToken: with a literal value should trigger G05."""
    src = f"  bearerToken: {secret('ghp' + '_', 'gcp-g05-bearer-token', 32)}\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-git-secret-plaintext" in ids


def test_g05_negative_password_env_ref() -> None:
    """password referencing an env var expression should NOT trigger G05."""
    src = "  password: $(SECRET_VALUE)\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-git-secret-plaintext" not in ids


# ---------- G06 : flux-insecure-skip-tls-verify --------------------------


def test_g06_positive_insecure_skip_tls_verify_yaml() -> None:
    """insecureSkipTLSVerify: true should trigger G06."""
    src = "spec:\n  insecureSkipTLSVerify: true\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-insecure-skip-tls-verify" in ids


def test_g06_positive_tls_skip_verify_flag() -> None:
    """--tls-skip-verify CLI flag should trigger G06."""
    src = "args: [--tls-skip-verify, --namespace, flux-system]\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-insecure-skip-tls-verify" in ids


def test_g06_negative_tls_verify_enabled() -> None:
    """insecureSkipTLSVerify: false must NOT trigger G06."""
    src = "spec:\n  insecureSkipTLSVerify: false\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-insecure-skip-tls-verify" not in ids


# ---------- G07 : flux-source-oci-no-verify ------------------------------


def test_g07_positive_oci_repo_no_verify_block() -> None:
    """OCIRepository without verify: block should trigger G07."""
    src = (
        "apiVersion: source.toolkit.fluxcd.io/v1beta2\n"
        "kind: OCIRepository\n"
        "metadata:\n"
        "  name: podinfo\n"
        "spec:\n"
        "  interval: 5m\n"
        "  url: oci://ghcr.io/stefanprodan/podinfo\n"
        "  ref:\n"
        "    tag: latest\n"
    )
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-source-oci-no-verify" in ids


def test_g07_negative_oci_repo_with_verify_block() -> None:
    """OCIRepository with verify: block must NOT trigger G07."""
    src = (
        "kind: OCIRepository\n"
        "spec:\n"
        "  interval: 5m\n"
        "  url: oci://ghcr.io/stefanprodan/podinfo\n"
        "  verify:\n"
        "    provider: cosign\n"
        "    secretRef:\n"
        "      name: cosign-pub-key\n"
    )
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-flux-source-oci-no-verify" not in ids


# ---------- G08 : tekton-param-injection-script --------------------------


def test_g08_positive_param_in_curl_command() -> None:
    """$(params.url) interpolated into curl should trigger G08."""
    src = "  script: |\n    curl $(params.targetUrl) | sh\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-param-injection-script" in ids


def test_g08_positive_param_in_eval() -> None:
    """$(params.cmd) interpolated into eval should trigger G08."""
    src = "  - name: run\n    script: eval $(params.cmd)\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-param-injection-script" in ids


def test_g08_negative_param_safe_variable_expansion() -> None:
    """$(params.version) used only in a value assignment is not injected."""
    src = "  - name: set-ver\n    env:\n      - name: VERSION\n        value: $(params.version)\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-param-injection-script" not in ids


# ---------- G09 : tekton-privileged-step-container -----------------------


def test_g09_positive_privileged_true() -> None:
    """privileged: true in a step securityContext should trigger G09."""
    src = "  securityContext:\n    privileged: true\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-privileged-step-container" in ids


def test_g09_positive_run_as_user_zero() -> None:
    """runAsUser: 0 in a step securityContext should trigger G09."""
    src = "  securityContext:\n    runAsUser: 0\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-privileged-step-container" in ids


def test_g09_negative_privileged_false() -> None:
    """privileged: false must NOT trigger G09."""
    src = "  securityContext:\n    privileged: false\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-privileged-step-container" not in ids


def test_g09_negative_run_as_user_nonzero() -> None:
    """runAsUser: 1000 (non-root) must NOT trigger G09."""
    src = "  securityContext:\n    runAsUser: 1000\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-privileged-step-container" not in ids


# ---------- G10 : tekton-serviceaccount-default --------------------------


def test_g10_positive_service_account_default() -> None:
    """serviceAccountName: default should trigger G10."""
    src = "spec:\n  serviceAccountName: default\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-serviceaccount-default" in ids


def test_g10_negative_service_account_named() -> None:
    """serviceAccountName: pipeline-runner must NOT trigger G10."""
    src = "spec:\n  serviceAccountName: pipeline-runner\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-tekton-serviceaccount-default" not in ids


# ---------- G11 : gitops-webhook-secret-missing --------------------------


def test_g11_positive_receiver_no_secret_ref() -> None:
    """Receiver kind without secretRef should trigger G11."""
    src = (
        "apiVersion: notification.toolkit.fluxcd.io/v1\n"
        "kind: Receiver\n"
        "metadata:\n"
        "  name: github-receiver\n"
        "spec:\n"
        "  type: github\n"
        "  events:\n"
        "    - ping\n"
        "    - push\n"
        "  resources:\n"
        "    - apiVersion: source.toolkit.fluxcd.io/v1\n"
        "      kind: GitRepository\n"
        "      name: webapp\n"
    )
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-gitops-webhook-secret-missing" in ids


def test_g11_negative_receiver_with_secret_ref() -> None:
    """Receiver kind with secretRef must NOT trigger G11."""
    src = (
        "kind: Receiver\n"
        "spec:\n"
        "  type: github\n"
        "  secretRef:\n"
        "    name: webhook-token\n"
        "  resources:\n"
        "    - kind: GitRepository\n"
        "      name: webapp\n"
    )
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-gitops-webhook-secret-missing" not in ids


# ---------- G12 : argocd-project-clusterresourcewhitelist-all ------------


def test_g12_positive_wildcard_group() -> None:
    """clusterResourceWhitelist with group: '*' should trigger G12."""
    src = (
        "spec:\n"
        "  clusterResourceWhitelist:\n"
        "  - group: '*'\n"
        "    kind: '*'\n"
    )
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-project-clusterresourcewhitelist-all" in ids


def test_g12_positive_wildcard_kind_inline() -> None:
    """clusterResourceWhitelist with kind: * on one line should trigger G12."""
    src = "clusterResourceWhitelist: [{group: 'apps', kind: '*'}]\n"
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-project-clusterresourcewhitelist-all" in ids


def test_g12_negative_scoped_resource_whitelist() -> None:
    """clusterResourceWhitelist with specific group/kind must NOT trigger G12."""
    src = (
        "spec:\n"
        "  clusterResourceWhitelist:\n"
        "  - group: 'apps'\n"
        "    kind: Deployment\n"
    )
    findings = gcp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "gitops-argocd-project-clusterresourcewhitelist-all" not in ids


# ---------- Integration: multi-rule single document ----------------------


def test_multiple_issues_in_one_manifest() -> None:
    """A manifest with several anti-patterns must surface all relevant rules."""
    src = (
        "# ArgoCD bootstrap application\n"
        "admin.password: BootstrapPass99\n"
        "spec:\n"
        "  repoURL: http://git.internal/myapp.git\n"
        "  insecure: true\n"
        "  allowPrivilegeEscalation: true\n"
    )
    findings = gcp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "gitops-argocd-admin-password-plaintext" in ids
    assert "gitops-argocd-repo-url-http-not-https" in ids
    assert "gitops-argocd-insecure-flag-enabled" in ids
    assert "gitops-argocd-app-sync-allow-privileged" in ids


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text must always return a list, never None."""
    assert isinstance(gcp.scan_text(""), list)
    assert isinstance(gcp.scan_text("no issues here"), list)
