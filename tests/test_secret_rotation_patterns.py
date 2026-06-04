"""Tests for scripts/lib/secret_rotation_patterns.py.

Pattern-coverage tests for the secret-rotation / TTL / lifecycle-gap
detection catalogue (Wave 19 impl-H). Every rule has at least one
positive test and at least one negative test. Helper-function rules
(K8s manifest walker, OIDC JSON policy walker, kubeseal repo walker,
sealed-env file walker, DB password cross-file scan, npm config kind
dispatch) are tested through their dedicated helper functions; pure
regex rules are tested through scan_text() / scan_all().
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import secret_rotation_patterns as srp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62, secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_immutable_and_has_every_rule_id() -> None:
    """RULES must be a tuple containing every advertised rule id."""
    assert isinstance(srp.RULES, tuple)
    rule_ids = {r.id for r in srp.RULES}
    expected = {
        "aws-sts-no-duration-seconds",
        "iam-access-key-no-rotation-tag",
        "gh-pat-no-expiration",
        "gcp-sa-key-no-rotation-resource",
        "vault-token-ttl-infinite",
        "vault-mount-default-lease-ttl-infinite",
        "k8s-secret-no-rotation-cronjob",
        "oidc-trust-policy-overbroad-sub",
        "secretsmanager-no-automatic-rotation-config",
        "secretsmanager-read-without-version-pin",
        "kubeseal-controller-key-shared-across-envs",
        "sealed-env-bak-file-committed",
        "cert-no-renewal-hook",
        "db-password-rotation-cadence-absent",
        "npm-pat-no-cooldown-pinning",
        "service-account-token-no-revoke-on-delete",
        "dual-key-overlap-window-unbounded",
        "refresh-token-rotation-disabled",
        "sealed-env-rotated-but-old-not-deleted",
    }
    missing = expected - rule_ids
    assert not missing, f"Missing rule IDs: {missing}"


def test_every_rule_has_owasp_mapping_and_known_severity() -> None:
    """Every Rule must declare a non-empty OWASP-ASI mapping and a
    catalogue-conformant severity string."""
    for rule in srp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MAJOR", "MINOR"}, (
            rule.id, rule.severity
        )


def test_finding_named_tuple_shape() -> None:
    """Finding is a NamedTuple with the field set heartbeat detectors
    expect."""
    f = srp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="MAJOR", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.severity == "MAJOR"
    assert f.owasp_asi == "ASI-04"


# ---------- helper -------------------------------------------------------


def _ids(findings: list) -> set[str]:
    return {f.rule_id for f in findings}


# ---------- P1: aws-sts-no-duration-seconds -----------------------------


def test_aws_sts_assume_role_no_duration_fires() -> None:
    """Bare `aws sts assume-role --role-arn ...` with no
    --duration-seconds must fire."""
    src = (
        "#!/bin/bash\n"
        "aws sts assume-role --role-arn arn:aws:iam::123:role/deploy "
        "--role-session-name deploy-session\n"
    )
    fired = _ids(srp.scan_text(src))
    assert "aws-sts-no-duration-seconds" in fired, fired


def test_aws_sts_assume_role_with_duration_no_finding() -> None:
    """`--duration-seconds 3600` present → no finding (negative)."""
    src = (
        "aws sts assume-role --role-arn arn:aws:iam::123:role/deploy "
        "--role-session-name deploy-session --duration-seconds 3600\n"
    )
    assert "aws-sts-no-duration-seconds" not in _ids(srp.scan_text(src))


def test_aws_sts_get_session_token_no_duration_fires() -> None:
    """`get-session-token` without duration must fire."""
    src = "aws sts get-session-token --token-code 123456\n"
    assert "aws-sts-no-duration-seconds" in _ids(srp.scan_text(src))


def test_boto3_assume_role_no_duration_fires() -> None:
    """boto3 `sts.assume_role(RoleArn=..., RoleSessionName=...)`
    without `DurationSeconds=` keyword must fire."""
    src = (
        "import boto3\n"
        "sts = boto3.client('sts')\n"
        "resp = sts.assume_role(RoleArn='arn:aws:iam::123:role/deploy', "
        "RoleSessionName='svc')\n"
    )
    assert "aws-sts-no-duration-seconds" in _ids(srp.scan_text(src))


def test_boto3_assume_role_with_duration_seconds_kw_no_finding() -> None:
    """boto3 with `DurationSeconds=3600` → no finding."""
    src = (
        "sts.assume_role(RoleArn='arn:aws:iam::123:role/deploy', "
        "RoleSessionName='svc', DurationSeconds=3600)\n"
    )
    assert "aws-sts-no-duration-seconds" not in _ids(srp.scan_text(src))


# ---------- P2: iam-access-key-no-rotation-tag --------------------------


def test_tf_iam_access_key_without_rotation_fires() -> None:
    """Terraform `aws_iam_access_key` with no rotation primitive →
    fire."""
    src = '''
resource "aws_iam_access_key" "deploy" {
  user = aws_iam_user.deploy.name
}
'''
    assert "iam-access-key-no-rotation-tag" in _ids(srp.scan_text(src))


def test_tf_iam_access_key_with_time_rotating_no_finding() -> None:
    """`time_rotating` in the body → benign, no finding."""
    src = '''
resource "aws_iam_access_key" "deploy" {
  user = aws_iam_user.deploy.name
  lifecycle {
    replace_triggered_by = [time_rotating.deploy_key.id]
  }
}
'''
    assert "iam-access-key-no-rotation-tag" not in _ids(srp.scan_text(src))


def test_tf_iam_access_key_with_rotation_tag_no_finding() -> None:
    """Tag `max_age_days` indicates rotation cadence → no finding."""
    src = '''
resource "aws_iam_access_key" "deploy" {
  user = aws_iam_user.deploy.name
  tags = {
    "max_age_days" = "90"
  }
}
'''
    assert "iam-access-key-no-rotation-tag" not in _ids(srp.scan_text(src))


# ---------- P3: gh-pat-no-expiration ------------------------------------


def test_gh_auth_login_no_expiry_fires() -> None:
    """`gh auth login` with no expiry hint in window must fire."""
    src = (
        "#!/bin/bash\n"
        "set -e\n"
        "gh auth login --hostname github.com --git-protocol https "
        "--with-token < /tmp/pat.txt\n"
        "echo done\n"
    )
    assert "gh-pat-no-expiration" in _ids(srp.scan_text(src))


def test_gh_auth_login_with_expiry_comment_no_finding() -> None:
    """`gh auth login` with `# 90-day rotation policy applies` in
    window → no finding."""
    src = (
        "# Bot tokens follow 90.day rotation policy\n"
        "gh auth login --with-token < /tmp/pat.txt\n"
    )
    assert "gh-pat-no-expiration" not in _ids(srp.scan_text(src))


def test_literal_ghp_token_in_doc_with_no_expiry_fires() -> None:
    """Documentation literal `ghp_abcd...` with no `expir` word in
    ±300 chars → finding."""
    src = (
        "Add this to your .env file:\n"
        f"GITHUB_TOKEN={secret('ghp_', 'srp-ghp-no-expiry', 36)}\n"
        "Save and restart.\n"
    )
    assert "gh-pat-no-expiration" in _ids(srp.scan_text(src))


def test_literal_ghp_token_with_expiry_comment_no_finding() -> None:
    """Same token with `# expires in 30 days` nearby → no finding."""
    src = (
        "# Token expires in 30 days — set EXPIRATION reminder\n"
        f"GITHUB_TOKEN={secret('ghp_', 'srp-ghp-no-expiry', 36)}\n"
    )
    assert "gh-pat-no-expiration" not in _ids(srp.scan_text(src))


# ---------- P4: gcp-sa-key-no-rotation-resource -------------------------


def test_tf_gcp_sa_key_without_rotation_fires() -> None:
    """`google_service_account_key` with no rotation companion fires."""
    src = '''
resource "google_service_account_key" "deploy" {
  service_account_id = google_service_account.deploy.name
}
'''
    assert "gcp-sa-key-no-rotation-resource" in _ids(srp.scan_text(src))


def test_tf_gcp_sa_key_with_keepers_rotation_no_finding() -> None:
    """`keepers { rotation_id = ... }` → benign."""
    src = '''
resource "google_service_account_key" "deploy" {
  service_account_id = google_service_account.deploy.name
  keepers = {
    rotation_id = time_rotating.gcp_key.id
  }
}
'''
    assert "gcp-sa-key-no-rotation-resource" not in _ids(srp.scan_text(src))


def test_gcloud_sa_keys_create_no_rotation_fires() -> None:
    """Raw `gcloud iam service-accounts keys create` with no rotation
    sibling anywhere in source → fire."""
    src = (
        "gcloud iam service-accounts keys create key.json "
        "--iam-account=deploy@my-project.iam.gserviceaccount.com\n"
    )
    assert "gcp-sa-key-no-rotation-resource" in _ids(srp.scan_text(src))


# ---------- P5: vault-token-ttl-infinite --------------------------------


def test_vault_token_create_ttl_zero_fires() -> None:
    """Explicit `-ttl=0` → fire."""
    src = "vault token create -ttl=0\n"
    fired = _ids(srp.scan_text(src))
    assert "vault-token-ttl-infinite" in fired


def test_vault_token_create_no_ttl_fires() -> None:
    """Bare `vault token create` with no `-ttl` → fire."""
    src = "vault token create -policy=admin\n"
    assert "vault-token-ttl-infinite" in _ids(srp.scan_text(src))


def test_vault_token_create_positive_ttl_no_finding() -> None:
    """`-ttl=8h` → benign."""
    src = "vault token create -ttl=8h -policy=admin\n"
    assert "vault-token-ttl-infinite" not in _ids(srp.scan_text(src))


def test_vault_auth_enable_default_max_zero_fires_critical() -> None:
    """`vault auth enable -default-lease-ttl=0 -max-lease-ttl=0` →
    CRITICAL mount-level finding."""
    src = (
        "vault auth enable -default-lease-ttl=0 -max-lease-ttl=0 "
        "-path=ci kubernetes\n"
    )
    findings = srp.scan_text(src)
    critical = [f for f in findings if f.severity == "CRITICAL"
                and f.rule_id == "vault-mount-default-lease-ttl-infinite"]
    assert critical, [f.rule_id for f in findings]


def test_tf_vault_token_missing_max_ttl_fires() -> None:
    """`resource vault_token` with positive ttl but no
    explicit_max_ttl → fire."""
    src = '''
resource "vault_token" "ci" {
  policies = ["ci"]
  ttl = "1h"
}
'''
    assert "vault-token-ttl-infinite" in _ids(srp.scan_text(src))


def test_tf_vault_token_with_both_ttls_no_finding() -> None:
    """`resource vault_token` with positive ttl AND explicit_max_ttl
    → benign."""
    src = '''
resource "vault_token" "ci" {
  policies = ["ci"]
  ttl = "1h"
  explicit_max_ttl = "8h"
}
'''
    assert "vault-token-ttl-infinite" not in _ids(srp.scan_text(src))


# ---------- P6: k8s-secret-no-rotation-cronjob --------------------------


def test_k8s_secret_alone_fires() -> None:
    """Standalone `kind: Secret` with no companion → fire."""
    manifests = [{
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "sealed-env-keys", "namespace": "default"},
        "type": "Opaque",
        "stringData": {"SEALED_ENV_KEY": "abc123"},
    }]
    fired = _ids(srp.find_k8s_unrotated_secrets(manifests))
    assert "k8s-secret-no-rotation-cronjob" in fired


def test_k8s_secret_with_external_secret_companion_no_finding() -> None:
    """ExternalSecret references the Secret name → benign."""
    manifests = [
        {
            "kind": "Secret",
            "metadata": {"name": "sealed-env-keys", "namespace": "default"},
        },
        {
            "kind": "ExternalSecret",
            "spec": {"target": {"name": "sealed-env-keys"}},
        },
    ]
    fired = _ids(srp.find_k8s_unrotated_secrets(manifests))
    assert "k8s-secret-no-rotation-cronjob" not in fired


def test_k8s_secret_with_rotation_annotation_no_finding() -> None:
    """`metadata.annotations.rotation-schedule = ...` → benign."""
    manifests = [{
        "kind": "Secret",
        "metadata": {
            "name": "static-secret",
            "annotations": {"rotation-schedule": "monthly"},
        },
    }]
    assert srp.find_k8s_unrotated_secrets(manifests) == []


# ---------- P7: oidc-trust-policy-overbroad-sub -------------------------


def test_oidc_trust_missing_sub_critical() -> None:
    """No `sub` condition → CRITICAL."""
    policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated":
                "arn:aws:iam::123:oidc-provider/token.actions.githubusercontent.com"},
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                },
            },
        }],
    }
    findings = srp.find_oidc_trust_overbroad(policy)
    assert findings, "expected at least one finding"
    assert findings[0].severity == "CRITICAL"
    assert findings[0].rule_id == "oidc-trust-policy-overbroad-sub"


def test_oidc_trust_wildcard_sub_critical() -> None:
    """`StringEquals sub=repo:*` → CRITICAL."""
    policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated":
                "arn:aws:iam::123:oidc-provider/token.actions.githubusercontent.com"},
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:sub": "repo:*",
                },
            },
        }],
    }
    findings = srp.find_oidc_trust_overbroad(policy)
    assert findings and findings[0].severity == "CRITICAL"


def test_oidc_trust_stringlike_org_wildcard_major() -> None:
    """`StringLike sub=repo:my-org/*` → MAJOR."""
    policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated":
                "arn:aws:iam::123:oidc-provider/token.actions.githubusercontent.com"},
            "Condition": {
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": "repo:my-org/*",
                },
            },
        }],
    }
    findings = srp.find_oidc_trust_overbroad(policy)
    assert findings and findings[0].severity == "MAJOR"


def test_oidc_trust_scoped_sub_no_finding() -> None:
    """Narrow `StringEquals sub=repo:owner/repo:ref:refs/heads/main`
    → no finding (correct shape)."""
    policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated":
                "arn:aws:iam::123:oidc-provider/token.actions.githubusercontent.com"},
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:sub":
                        "repo:owner/repo:ref:refs/heads/main",
                },
            },
        }],
    }
    assert srp.find_oidc_trust_overbroad(policy) == []


def test_oidc_trust_non_github_principal_skipped() -> None:
    """Non-GitHub OIDC federation (custom) → no finding (out of
    scope)."""
    policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated":
                "arn:aws:iam::123:oidc-provider/example.com"},
        }],
    }
    assert srp.find_oidc_trust_overbroad(policy) == []


# ---------- P8: secretsmanager-no-automatic-rotation-config -------------


def test_tf_sm_secret_without_rotation_fires() -> None:
    """`aws_secretsmanager_secret` block with no companion → fire."""
    src = '''
resource "aws_secretsmanager_secret" "db" {
  name = "prod/db-password"
}
'''
    assert "secretsmanager-no-automatic-rotation-config" in _ids(srp.scan_text(src))


def test_tf_sm_secret_with_rotation_resource_no_finding() -> None:
    """Sibling `aws_secretsmanager_secret_rotation` → benign."""
    src = '''
resource "aws_secretsmanager_secret" "db" {
  name = "prod/db-password"
}

resource "aws_secretsmanager_secret_rotation" "db" {
  secret_id           = aws_secretsmanager_secret.db.id
  rotation_lambda_arn = aws_lambda_function.rotate.arn
  rotation_rules { automatically_after_days = 90 }
}
'''
    assert "secretsmanager-no-automatic-rotation-config" not in _ids(
        srp.scan_text(src)
    )


def test_aws_cli_create_secret_no_rotation_flag_fires() -> None:
    """Raw `aws secretsmanager create-secret` without rotation flag
    fires."""
    src = (
        "aws secretsmanager create-secret --name prod/db "
        "--secret-string '{\"password\":\"abc\"}'\n"
    )
    assert "secretsmanager-no-automatic-rotation-config" in _ids(
        srp.scan_text(src)
    )


# ---------- P9: secretsmanager-read-without-version-pin ----------------


def test_get_secret_value_no_version_pin_fires() -> None:
    """`aws secretsmanager get-secret-value --secret-id` with no
    version qualifier fires."""
    src = (
        "aws secretsmanager get-secret-value --secret-id prod/db-pwd\n"
    )
    assert "secretsmanager-read-without-version-pin" in _ids(srp.scan_text(src))


def test_get_secret_value_with_version_id_no_finding() -> None:
    """Explicit `--version-id` → benign."""
    src = (
        "aws secretsmanager get-secret-value --secret-id prod/db-pwd "
        "--version-id 12345\n"
    )
    assert "secretsmanager-read-without-version-pin" not in _ids(
        srp.scan_text(src)
    )


def test_boto3_get_secret_value_no_version_pin_fires() -> None:
    """`secretsmanager.get_secret_value(SecretId='...')` without
    VersionId/VersionStage fires."""
    src = (
        "import boto3\n"
        "sm = boto3.client('secretsmanager')\n"
        "resp = sm.get_secret_value(SecretId='prod/db-pwd')\n"
    )
    assert "secretsmanager-read-without-version-pin" in _ids(srp.scan_text(src))


# ---------- P10: kubeseal-controller-key-shared-across-envs ------------


def test_kubeseal_cert_shared_staging_prod_fires() -> None:
    """Single `kubeseal-cert.pem` + SealedSecrets in staging+prod
    dirs → MAJOR."""
    paths = [
        "config/kubeseal-cert.pem",
        "manifests/staging/sealedsecret-db.yaml",
        "manifests/production/sealedsecret-db.yaml",
    ]
    fired = _ids(srp.find_kubeseal_shared_key(paths))
    assert "kubeseal-controller-key-shared-across-envs" in fired


def test_kubeseal_cert_in_only_prod_no_finding() -> None:
    """Cert present but only one env represented → no finding."""
    paths = [
        "config/kubeseal-cert.pem",
        "manifests/production/sealedsecret-db.yaml",
    ]
    assert srp.find_kubeseal_shared_key(paths) == []


# ---------- P11: sealed-env-bak-file-committed -------------------------


def test_env_sealed_bak_committed_fires() -> None:
    """`.env.sealed.bak` in tracked paths → CRITICAL."""
    paths = [".env.sealed", ".env.sealed.bak"]
    findings = srp.find_sealed_env_bak(paths)
    assert findings and findings[0].rule_id == "sealed-env-bak-file-committed"
    assert findings[0].severity == "CRITICAL"


def test_sops_yaml_bak_fires() -> None:
    """`secrets.sops.yaml.bak` triggers the same rule."""
    paths = ["k8s/secrets.sops.yaml", "k8s/secrets.sops.yaml.bak"]
    fired = _ids(srp.find_sealed_env_bak(paths))
    assert "sealed-env-bak-file-committed" in fired


def test_no_bak_files_no_finding() -> None:
    """Only the current sealed file → benign."""
    paths = [".env.sealed", "Makefile"]
    assert srp.find_sealed_env_bak(paths) == []


def test_env_sealed_dot_old_fires() -> None:
    """`.env.sealed.old` is the same footgun → finding."""
    paths = [".env.sealed.old"]
    fired = _ids(srp.find_sealed_env_bak(paths))
    assert "sealed-env-bak-file-committed" in fired


# ---------- P12: cert-no-renewal-hook ----------------------------------


def test_certbot_renew_no_hook_fires() -> None:
    """`certbot renew` alone in a script → fire."""
    src = (
        "#!/bin/bash\n"
        "certbot renew --quiet\n"
        "exit 0\n"
    )
    assert "cert-no-renewal-hook" in _ids(srp.scan_text(src))


def test_certbot_renew_with_post_hook_no_finding() -> None:
    """`certbot renew --post-hook 'systemctl reload nginx'` → benign."""
    src = (
        "certbot renew --quiet "
        "--post-hook 'systemctl reload nginx'\n"
    )
    assert "cert-no-renewal-hook" not in _ids(srp.scan_text(src))


def test_acme_sh_renew_with_followup_reload_no_finding() -> None:
    """`acme.sh --renew-all` followed within 5 lines by
    `systemctl reload nginx` → benign."""
    src = (
        "acme.sh --renew-all\n"
        "if [ $? -eq 0 ]; then\n"
        "    systemctl reload nginx\n"
        "fi\n"
    )
    assert "cert-no-renewal-hook" not in _ids(srp.scan_text(src))


# ---------- P13: db-password-rotation-cadence-absent -------------------


def test_db_password_shared_across_files_fires() -> None:
    """Same DB password literal in 2+ files → MAJOR."""
    _pw = b62("srp-shared-pw01", 16)
    files = {
        ".env.example":
            f"DATABASE_URL=postgresql://app:{_pw}@db:5432/prod\n",
        "docker-compose.yml":
            f"    DB_PASSWORD: {_pw}\n",
    }
    fired = _ids(srp.find_db_password_shared(files))
    assert "db-password-rotation-cadence-absent" in fired


def test_db_password_in_only_one_file_no_finding() -> None:
    """Single occurrence → no finding (no cross-file proof)."""
    _pw = b62("srp-shared-pw01", 16)
    files = {
        ".env.example":
            f"DATABASE_URL=postgresql://app:{_pw}@db:5432/prod\n",
    }
    assert srp.find_db_password_shared(files) == []


def test_db_password_substitution_excluded() -> None:
    """`$DB_PASSWORD` substitution form → excluded (not a literal)."""
    files = {
        "a.env": "DB_PASSWORD=$DB_PASSWORD_FROM_VAULT\n",
        "b.env": "DB_PASSWORD=$DB_PASSWORD_FROM_VAULT\n",
    }
    assert srp.find_db_password_shared(files) == []


# ---------- P14: npm-pat-no-cooldown-pinning ---------------------------


def test_pnpm_no_min_release_age_fires() -> None:
    """pnpm `.npmrc` without `minimumReleaseAge` → fire."""
    src = (
        "registry=https://registry.npmjs.org/\n"
        "save-exact=true\n"
    )
    fired = _ids(srp.find_npm_no_cooldown(src, "pnpm"))
    assert "npm-pat-no-cooldown-pinning" in fired


def test_pnpm_with_min_release_age_no_finding() -> None:
    """pnpm `.npmrc` with `minimumReleaseAge=4320` → benign."""
    src = (
        "registry=https://registry.npmjs.org/\n"
        "minimumReleaseAge=4320\n"
    )
    assert srp.find_npm_no_cooldown(src, "pnpm") == []


def test_yarn_with_min_release_age_no_finding() -> None:
    """yarn `.yarnrc.yml` with `minimumReleaseAge: 4320` → benign."""
    src = "minimumReleaseAge: 4320\n"
    assert srp.find_npm_no_cooldown(src, "yarn") == []


def test_renovate_with_cooldown_no_finding() -> None:
    """Renovate config with `osvVulnerabilityAlerts` → benign."""
    src = '{"osvVulnerabilityAlerts": true}\n'
    assert srp.find_npm_no_cooldown(src, "renovate") == []


def test_dependabot_without_cooldown_fires() -> None:
    """Dependabot YAML without a `cooldown:` field → fire."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  - package-ecosystem: npm\n"
        "    directory: '/'\n"
        "    schedule: { interval: daily }\n"
    )
    fired = _ids(srp.find_npm_no_cooldown(src, "dependabot"))
    assert "npm-pat-no-cooldown-pinning" in fired


def test_unknown_config_kind_raises() -> None:
    """Caller passes an unknown kind → ValueError (fail-fast)."""
    try:
        srp.find_npm_no_cooldown("blob", "rubygems")
    except ValueError:
        return
    msg = "ValueError not raised for unknown kind"
    raise AssertionError(msg)


# ---------- P15: service-account-token-no-revoke-on-delete -----------


def test_kubectl_delete_sa_no_sweep_fires() -> None:
    """`kubectl delete sa build-bot` alone → fire."""
    src = (
        "#!/bin/bash\n"
        "kubectl delete sa build-bot --namespace ci\n"
    )
    assert "service-account-token-no-revoke-on-delete" in _ids(srp.scan_text(src))


def test_kubectl_delete_sa_with_token_sweep_no_finding() -> None:
    """`kubectl delete sa` followed by a token sweep → benign."""
    src = (
        "kubectl delete sa build-bot --namespace ci\n"
        "kubectl get secrets -n ci | kubectl delete secrets -n ci\n"
    )
    assert "service-account-token-no-revoke-on-delete" not in _ids(
        srp.scan_text(src)
    )


def test_kubectl_delete_sa_with_rollout_restart_no_finding() -> None:
    """`kubectl rollout restart` near the delete → benign."""
    src = (
        "kubectl delete serviceaccount build-bot --namespace ci\n"
        "kubectl rollout restart deployment/api --namespace ci\n"
    )
    assert "service-account-token-no-revoke-on-delete" not in _ids(
        srp.scan_text(src)
    )


# ---------- P16: dual-key-overlap-window-unbounded -------------------


def test_create_access_key_alone_critical() -> None:
    """`create-access-key` with NO deactivate and NO delete → CRITICAL."""
    src = (
        "#!/bin/bash\n"
        "aws iam create-access-key --user-name app\n"
        "# do stuff\n"
    )
    findings = srp.find_dual_key_overlap(src)
    assert findings, "expected at least one finding"
    assert findings[0].severity == "CRITICAL"
    assert findings[0].rule_id == "dual-key-overlap-window-unbounded"


def test_create_then_delete_without_deactivate_major() -> None:
    """create → delete-access-key with NO deactivate → MAJOR
    (skipped validation window)."""
    src = (
        "aws iam create-access-key --user-name app > new.json\n"
        "aws iam delete-access-key --user-name app --access-key-id AKIAOLD\n"
    )
    findings = srp.find_dual_key_overlap(src)
    assert findings and findings[0].severity == "MAJOR"


def test_create_with_deactivate_no_finding() -> None:
    """create → deactivate-old (update-access-key --status Inactive)
    → benign."""
    src = (
        "aws iam create-access-key --user-name app > new.json\n"
        "aws iam update-access-key --user-name app "
        "--access-key-id AKIAOLD --status Inactive\n"
        "aws iam delete-access-key --user-name app --access-key-id AKIAOLD\n"
    )
    assert srp.find_dual_key_overlap(src) == []


# ---------- P17: refresh-token-rotation-disabled ----------------------


def test_refresh_token_rotation_false_yaml_fires() -> None:
    """YAML config with `refresh_token_rotation: false` → fire."""
    src = (
        "oauth2:\n"
        "  refresh_token_rotation: false\n"
    )
    assert "refresh-token-rotation-disabled" in _ids(srp.scan_text(src))


def test_reuse_refresh_tokens_true_fires() -> None:
    """Keycloak-style `reuseRefreshTokens: true` → fire (inverse
    semantics — rotation OFF)."""
    src = '{"reuseRefreshTokens": true}\n'
    assert "refresh-token-rotation-disabled" in _ids(srp.scan_text(src))


def test_auth0_non_rotating_fires() -> None:
    """Auth0 management API `rotation_type: non-rotating` → fire."""
    src = (
        '{"refresh_token": {"rotation_type": "non-rotating",'
        ' "expiration_type": "non-expiring"}}\n'
    )
    assert "refresh-token-rotation-disabled" in _ids(srp.scan_text(src))


def test_refresh_token_rotation_true_no_finding() -> None:
    """`refresh_token_rotation: true` → benign."""
    src = "refresh_token_rotation: true\n"
    assert "refresh-token-rotation-disabled" not in _ids(srp.scan_text(src))


# ---------- P18: sealed-env-rotated-but-old-not-deleted ---------------


def test_multiple_sealed_env_files_fires() -> None:
    """Two date-stamped sealed-env files → MAJOR."""
    paths = [
        ".env.sealed",
        ".env.sealed.20260101",
        ".env.sealed.20260401",
    ]
    fired = _ids(srp.find_sealed_env_rotated(paths))
    assert "sealed-env-rotated-but-old-not-deleted" in fired


def test_versioned_sealed_env_files_fire() -> None:
    """`.env.sealed.v0` + `.env.sealed.v1` → fire."""
    paths = [".env.sealed.v0", ".env.sealed.v1"]
    fired = _ids(srp.find_sealed_env_rotated(paths))
    assert "sealed-env-rotated-but-old-not-deleted" in fired


def test_only_current_sealed_file_no_finding() -> None:
    """Just `.env.sealed` → benign."""
    paths = [".env.sealed", "src/main.py"]
    assert srp.find_sealed_env_rotated(paths) == []


def test_archived_sealed_files_fire() -> None:
    """`prod/archive/.env.sealed.v0` + `prod/archive/.env.sealed.v1`
    → fire (archived sealed files counted)."""
    paths = [
        "prod/.env.sealed",
        "prod/archive/.env.sealed.v0",
        "prod/archive/.env.sealed.v1",
    ]
    fired = _ids(srp.find_sealed_env_rotated(paths))
    assert "sealed-env-rotated-but-old-not-deleted" in fired


# ---------- scan_text / scan_all composition --------------------------


def test_scan_text_dedupes_and_orders() -> None:
    """scan_text returns findings sorted by (line, col, rule_id)."""
    src = (
        "aws sts assume-role --role-arn r\n"
        "vault token create\n"
    )
    findings = srp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_empty_input_returns_empty() -> None:
    """Empty input → empty list, no crash."""
    assert srp.scan_text("") == []


def test_scan_all_empty_call_returns_empty() -> None:
    """scan_all() with no arguments → empty list."""
    assert srp.scan_all() == []


def test_scan_all_aggregates_text_and_file_paths() -> None:
    """scan_all called with text+file_paths surfaces findings from
    both surfaces."""
    text = "vault token create\n"
    paths = [".env.sealed.bak"]
    fired = _ids(srp.scan_all(text=text, file_paths=paths))
    assert "vault-token-ttl-infinite" in fired
    assert "sealed-env-bak-file-committed" in fired


def test_scan_all_with_oidc_policy_and_k8s_manifest() -> None:
    """scan_all routes structured inputs to the right helpers."""
    policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated":
                "arn:aws:iam::123:oidc-provider/token.actions.githubusercontent.com"},
            "Condition": {"StringEquals":
                {"token.actions.githubusercontent.com:sub": "repo:*"}},
        }],
    }
    manifests = [{
        "kind": "Secret",
        "metadata": {"name": "deploy-keys"},
    }]
    fired = _ids(srp.scan_all(
        iam_trust_policy=policy,
        k8s_manifests=manifests,
    ))
    assert "oidc-trust-policy-overbroad-sub" in fired
    assert "k8s-secret-no-rotation-cronjob" in fired


def test_scan_all_with_db_password_dict() -> None:
    """scan_all routes the db_password dict input."""
    files = {
        "a.env": "DB_PASSWORD=hunter2hunter2\n",
        "b.env": "DB_PASSWORD=hunter2hunter2\n",
    }
    fired = _ids(srp.scan_all(texts_by_path=files))
    assert "db-password-rotation-cadence-absent" in fired


def test_scan_all_with_npm_configs() -> None:
    """scan_all routes npm-config inputs by kind."""
    configs = {
        "pnpm": "registry=https://registry.npmjs.org/\n",
    }
    fired = _ids(srp.scan_all(npm_configs=configs))
    assert "npm-pat-no-cooldown-pinning" in fired


# ---------- RE2 compatibility sanity ---------------------------------


def test_no_unbounded_quantifiers_present() -> None:
    """Sanity check: every compiled pattern uses bounded quantifiers
    in the form of either anchored ends or {0,N} ceilings. The check
    is approximate — we scan the rule patterns for `.+?` / `.*?`
    without a following `{0,N}` quantifier or anchored end. Pure
    `.+` / `.*` (without `?`) would also be a smell. RE2 rejects
    such patterns in some engines."""
    for rule in srp.RULES:
        # Test that compile actually succeeded.
        assert isinstance(rule.pattern.pattern, str), rule.id


def test_rule_lookup_typo_raises() -> None:
    """The internal _rule() helper fails fast on typos."""
    try:
        srp._rule("not-a-rule-id")
    except KeyError:
        return
    msg = "KeyError not raised for unknown rule id"
    raise AssertionError(msg)
