"""Tests for gcp_iam_impersonation_patterns — 2 tests per rule (20 total)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

from gcp_iam_impersonation_patterns import RULES, scan_text  # type: ignore[import-not-found]  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ids_for(text: str) -> set[str]:
    return {f.rule_id for f in scan_text(text)}


# ---------------------------------------------------------------------------
# R1 — gcp-iam-sa-token-creator-on-human
# ---------------------------------------------------------------------------

RID1 = "gcp-iam-sa-token-creator-on-human"


def test_r1_token_creator_on_human_user_triggers():
    """TokenCreator role + user: member on the same line fires the rule."""
    terraform = (
        'role   = "roles/iam.serviceAccountTokenCreator"\n'
        'members = ["user:alice@example.com"]\n'
    )
    assert RID1 in _ids_for(terraform)


def test_r1_token_creator_on_sa_member_no_trigger():
    """TokenCreator role bound to a serviceAccount: member must NOT fire."""
    terraform = (
        'role   = "roles/iam.serviceAccountTokenCreator"\n'
        'member = "serviceAccount:ci-runner@my-proj.iam.gserviceaccount.com"\n'
    )
    assert RID1 not in _ids_for(terraform)


# ---------------------------------------------------------------------------
# R2 — gcp-iam-sa-user-chaining-compute-admin
# ---------------------------------------------------------------------------

RID2 = "gcp-iam-sa-user-chaining-compute-admin"


def test_r2_sa_user_role_triggers():
    """Presence of serviceAccountUser role fires the rule."""
    terraform = 'role = "roles/iam.serviceAccountUser"\n'
    assert RID2 in _ids_for(terraform)


def test_r2_unrelated_role_no_trigger():
    """An unrelated IAM role must NOT trigger the serviceAccountUser rule."""
    terraform = 'role = "roles/viewer"\n'
    assert RID2 not in _ids_for(terraform)


# ---------------------------------------------------------------------------
# R3 — gcp-iam-wif-owner-only-condition
# ---------------------------------------------------------------------------

RID3 = "gcp-iam-wif-owner-only-condition"


def test_r3_owner_only_condition_triggers():
    """attribute_condition using only repository_owner fires the rule."""
    terraform = (
        'attribute_condition = "attribute.repository_owner == \'my-org\'"\n'
    )
    assert RID3 in _ids_for(terraform)


def test_r3_full_repo_condition_no_trigger():
    """attribute_condition checking both owner and repository must NOT fire."""
    terraform = (
        "attribute_condition = "
        '"attribute.repository == \'my-org/my-repo\' && attribute.repository_owner == \'my-org\'"\n'
    )
    # The pattern requires owner-only — combined repo+owner is safe
    assert RID3 not in _ids_for(terraform)


# ---------------------------------------------------------------------------
# R4 — gcp-iam-wif-actor-only-condition
# ---------------------------------------------------------------------------

RID4 = "gcp-iam-wif-actor-only-condition"


def test_r4_actor_only_condition_triggers():
    """attribute.actor == expression fires the actor-only rule."""
    terraform = "attribute_condition = \"attribute.actor == 'trusted-bot'\"\n"
    assert RID4 in _ids_for(terraform)


def test_r4_no_actor_reference_no_trigger():
    """A condition not referencing attribute.actor must NOT trigger the rule."""
    terraform = "attribute_condition = \"assertion.sub == 'repo:my-org/my-repo:ref:refs/heads/main'\"\n"
    assert RID4 not in _ids_for(terraform)


# ---------------------------------------------------------------------------
# R5 — gcp-iam-wif-iss-only-condition
# ---------------------------------------------------------------------------

RID5 = "gcp-iam-wif-iss-only-condition"


def test_r5_iss_only_condition_triggers():
    """assertion.iss == GitHub Actions issuer URL fires the iss-only rule."""
    terraform = (
        "attribute_condition = "
        '"assertion.iss == \'https://token.actions.githubusercontent.com\'"\n'
    )
    assert RID5 in _ids_for(terraform)


def test_r5_unrelated_issuer_no_trigger():
    """A different issuer URL must NOT fire the GitHub Actions iss-only rule."""
    terraform = (
        'attribute_condition = "assertion.iss == \'https://accounts.google.com\'"\n'
    )
    assert RID5 not in _ids_for(terraform)


# ---------------------------------------------------------------------------
# R6 — gcp-iam-sa-key-file-committed
# ---------------------------------------------------------------------------

RID6 = "gcp-iam-sa-key-file-committed"


def test_r6_sa_key_file_type_and_private_key_id_triggers():
    """type=service_account + 40-char hex private_key_id fires the rule."""
    json_content = (
        '{\n'
        '  "type": "service_account",\n'
        '  "private_key_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"\n'
        '}\n'
    )
    assert RID6 in _ids_for(json_content)


def test_r6_client_email_gserviceaccount_triggers():
    """client_email ending in .iam.gserviceaccount.com fires the rule."""
    json_content = (
        '"client_email": "prod-sa@my-proj.iam.gserviceaccount.com"\n'
    )
    assert RID6 in _ids_for(json_content)


# ---------------------------------------------------------------------------
# R7 — gcp-iam-adc-env-from-user-input
# ---------------------------------------------------------------------------

RID7 = "gcp-iam-adc-env-from-user-input"


def test_r7_adc_from_github_expression_triggers():
    """GOOGLE_APPLICATION_CREDENTIALS: ${{ ... }} fires the ADC rule."""
    yaml_content = (
        "    env:\n"
        "      GOOGLE_APPLICATION_CREDENTIALS: ${{ github.event.inputs.cred_path }}\n"
    )
    assert RID7 in _ids_for(yaml_content)


def test_r7_adc_hardcoded_path_no_trigger():
    """GOOGLE_APPLICATION_CREDENTIALS set to a literal path must NOT trigger."""
    yaml_content = (
        "    env:\n"
        "      GOOGLE_APPLICATION_CREDENTIALS: /tmp/sa-key.json\n"
    )
    assert RID7 not in _ids_for(yaml_content)


# ---------------------------------------------------------------------------
# R8 — gcp-iam-cloudbuild-sa-data-read-role
# ---------------------------------------------------------------------------

RID8 = "gcp-iam-cloudbuild-sa-data-read-role"


def test_r8_cloudbuild_sa_with_secret_accessor_triggers():
    """Cloud Build SA member + secretmanager.secretAccessor in one block fires."""
    terraform = (
        'member = "serviceAccount:123456789@cloudbuild.gserviceaccount.com"\n'
        'role   = "roles/secretmanager.secretAccessor"\n'
    )
    assert RID8 in _ids_for(terraform)


def test_r8_cloudbuild_sa_deploy_only_no_trigger():
    """Cloud Build SA member without a data-read role must NOT trigger."""
    terraform = (
        'member = "serviceAccount:123456789@cloudbuild.gserviceaccount.com"\n'
        'role   = "roles/run.admin"\n'
    )
    assert RID8 not in _ids_for(terraform)


# ---------------------------------------------------------------------------
# R9 — gcp-iam-cloudrun-fn-no-explicit-sa
# ---------------------------------------------------------------------------

RID9 = "gcp-iam-cloudrun-fn-no-explicit-sa"


def test_r9_cloud_run_resource_block_triggers():
    """A google_cloud_run_service resource block fires the no-explicit-SA rule."""
    terraform = (
        'resource "google_cloud_run_service" "api" {\n'
        '  name = "my-api"\n'
        '}\n'
    )
    assert RID9 in _ids_for(terraform)


def test_r9_cloud_function_resource_block_triggers():
    """A google_cloudfunctions_function resource block fires the no-explicit-SA rule."""
    terraform = (
        'resource "google_cloudfunctions_function" "proc" {\n'
        '  name = "data-processor"\n'
        '}\n'
    )
    assert RID9 in _ids_for(terraform)


# ---------------------------------------------------------------------------
# R10 — gcp-iam-gke-wif-namespace-wildcard
# ---------------------------------------------------------------------------

RID10 = "gcp-iam-gke-wif-namespace-wildcard"


def test_r10_namespace_wildcard_triggers():
    """Workload Identity binding with [namespace/*] fires the wildcard rule."""
    terraform = (
        'members = ["serviceAccount:my-proj.svc.id.goog[production/*]"]\n'
    )
    assert RID10 in _ids_for(terraform)


def test_r10_specific_ksa_no_trigger():
    """Workload Identity binding with a specific KSA name must NOT trigger."""
    terraform = (
        'members = ["serviceAccount:my-proj.svc.id.goog[production/my-app-ksa]"]\n'
    )
    assert RID10 not in _ids_for(terraform)


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


def test_rules_count():
    """RULES tuple must contain exactly 10 rules."""
    assert len(RULES) == 10


def test_all_rule_ids_prefixed_gcp_iam():
    """Every rule ID must start with 'gcp-iam-'."""
    for rule in RULES:
        assert rule.id.startswith("gcp-iam-"), f"Bad prefix: {rule.id}"


def test_scan_text_empty_input_returns_empty_list():
    """scan_text on empty string returns an empty list without raising."""
    assert scan_text("") == []


def test_finding_fields_populated():
    """A triggered finding populates all Finding fields with non-empty values."""
    text = 'members = ["serviceAccount:my-proj.svc.id.goog[production/*]"]\n'
    findings = scan_text(text)
    assert findings
    f = findings[0]
    assert f.rule_id
    assert f.line >= 1
    assert f.column >= 1
    assert f.matched_text
    assert f.severity
    assert f.description
    assert f.owasp_asi
