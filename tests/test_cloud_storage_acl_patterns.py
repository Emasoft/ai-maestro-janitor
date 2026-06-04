"""Tests for scripts/lib/cloud_storage_acl_patterns.py.

Pattern-coverage tests for the Wave-20 distillation round 6 angle C
catalogue (cloud storage ACL / policy / pre-signed URL abuse). Each
rule gets one or more positive tests + at least one negative test
exercising the carve-out.

Source-of-record: reports/distill-round-6/cloud-storage-acl.md
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cloud_storage_acl_patterns as csap  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(csap.RULES, tuple)
    rule_ids = {r.id for r in csap.RULES}
    expected = {
        "cstor-signed-url-ttl-excessive",
        "cstor-signed-url-ttl-falsy-fallthrough",
        "cstor-acl-public-flag-dead-or-wired",
        "cstor-gcp-identity-in-error-message",
        "cstor-bucket-exists-error-masking",
        "cstor-signed-url-unescaped-html",
        "cstor-storage-client-no-project-pin",
        "cstor-object-name-path-traversal",
        "cstor-resumable-upload-disabled",
        "cstor-missing-generation-precondition",
        "cstor-missing-cmek-integrity-validation",
        "cstor-bucket-name-from-caller-options",
        "cstor-bucket-policy-public-allusers",
    }
    assert expected.issubset(rule_ids), f"missing: {expected - rule_ids}"


def test_every_rule_has_owasp_mapping_and_valid_severity() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in csap.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = csap.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_scan_text_empty_returns_empty_list() -> None:
    """scan_text('') and scan_text(None-ish) return []."""
    assert csap.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[csap.Finding]:
    return [f for f in csap.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1: cstor-signed-url-ttl-excessive ------------------------


def test_ttl_excessive_flags_604800_seven_days() -> None:
    """7 days (604800s) is way over the 1-hour safe cap."""
    src = "GCS_SIGNED_URL_TTL = 604800  # 7 days\n"
    assert _hits("cstor-signed-url-ttl-excessive", src)


def test_ttl_excessive_flags_javascript_signedurlttl() -> None:
    """JS kwarg variant: signedUrlTtl: 86400 (1 day)."""
    src = "const opts = { signedUrlTtl: 86400 };\n"
    assert _hits("cstor-signed-url-ttl-excessive", src)


def test_ttl_excessive_flags_boto3_expiresin() -> None:
    """boto3 generate_presigned_url with ExpiresIn=86400."""
    src = (
        "url = s3.generate_presigned_url(\n"
        "    'get_object', Params={'Bucket': b}, ExpiresIn=86400\n"
        ")\n"
    )
    assert _hits("cstor-signed-url-ttl-excessive", src)


def test_ttl_excessive_flags_gsutil_signurl_day() -> None:
    """gsutil signurl with -d 7d (over 1 hour)."""
    src = "gsutil signurl -d 7d sa.json gs://bucket/object\n"
    assert _hits("cstor-signed-url-ttl-excessive", src)


def test_ttl_excessive_flags_azure_sas_timedelta_days() -> None:
    """Azure SAS with timedelta(days=7) before generate_blob_sas."""
    src = (
        "expiry = datetime.utcnow() + timedelta(days=7)  "
        "# generate_blob_sas\n"
        "sas = generate_blob_sas(\n"
        "  account_name=a, container_name=c, blob_name=b,\n"
        "  expiry=expiry,\n"
        ")\n"
    )
    assert _hits("cstor-signed-url-ttl-excessive", src)


def test_ttl_under_cap_300s_does_not_fire() -> None:
    """300s (5 min) is the recommended default — must NOT fire."""
    src = "GCS_SIGNED_URL_TTL = 300\n"
    assert not _hits("cstor-signed-url-ttl-excessive", src)


def test_ttl_exactly_3600_does_not_fire() -> None:
    """The 1-hour boundary (3600s) is the maximum safe value — no hit."""
    src = "const opts = { signedUrlTtl: 3600 };\n"
    assert not _hits("cstor-signed-url-ttl-excessive", src)


# ---------- Rule 2: cstor-signed-url-ttl-falsy-fallthrough ---------------


def test_falsy_fallthrough_flags_options_dot_signedUrlTtl_pipe_pipe() -> None:
    """The canonical `options?.signedUrlTtl || env.X` shape."""
    src = (
        "const signedUrlTtl = options?.signedUrlTtl "
        "|| parseInt(process.env.GCS_SIGNED_URL_TTL || '604800', 10);\n"
    )
    assert _hits("cstor-signed-url-ttl-falsy-fallthrough", src)


def test_falsy_fallthrough_flags_python_get_or() -> None:
    """Python: config.expires_in || env — same footgun shape."""
    src = "ttl = config.expires_in || os.environ.get('TTL', '604800')\n"
    assert _hits("cstor-signed-url-ttl-falsy-fallthrough", src)


def test_falsy_fallthrough_flags_opts_expiresIn() -> None:
    """Alternate name: opts.expiresIn || default."""
    src = "const ttl = opts.expiresIn || 3600;\n"
    assert _hits("cstor-signed-url-ttl-falsy-fallthrough", src)


def test_nullish_coalescing_does_not_fire() -> None:
    """`??` (nullish coalescing) respects explicit zero — no hit."""
    src = "const ttl = options?.signedUrlTtl ?? 300;\n"
    assert not _hits("cstor-signed-url-ttl-falsy-fallthrough", src)


# ---------- Rule 3: cstor-acl-public-flag-dead-or-wired -------------------


def test_acl_public_flags_gcs_public_env() -> None:
    """The dead GCS_PUBLIC env declaration."""
    src = (
        "const GCS_PUBLIC = String(process.env.GCS_PUBLIC || 'false') === 'true';\n"
    )
    assert _hits("cstor-acl-public-flag-dead-or-wired", src)


def test_acl_public_flags_s3_public_env() -> None:
    """S3 variant of the same footgun."""
    src = "S3_PUBLIC = os.environ.get('S3_PUBLIC', 'false') == 'true'\n"
    assert _hits("cstor-acl-public-flag-dead-or-wired", src)


def test_acl_public_flags_make_public_call() -> None:
    """Explicit file.makePublic() call (GCS)."""
    src = "await file.makePublic();\n"
    assert _hits("cstor-acl-public-flag-dead-or-wired", src)


def test_acl_public_flags_s3_acl_public_read() -> None:
    """boto3 / S3 ACL='public-read'."""
    src = "s3.put_object(Bucket=b, Key=k, Body=body, ACL='public-read')\n"
    assert _hits("cstor-acl-public-flag-dead-or-wired", src)


def test_acl_public_flags_gcs_iam_allusers_storage_viewer() -> None:
    """GCS IAM grant: allUsers → roles/storage.objectViewer."""
    src = (
        "bucket.iam.setPolicy({ bindings: [{ role: 'roles/storage.objectViewer', "
        "members: ['allUsers'] }] });\n"
    )
    assert _hits("cstor-acl-public-flag-dead-or-wired", src)


def test_acl_public_flags_azure_public_blob() -> None:
    """Azure: create_container with public_access='blob'."""
    src = "client.create_container(name='c', public_access='blob')\n"
    assert _hits("cstor-acl-public-flag-dead-or-wired", src)


def test_acl_private_grant_does_not_fire() -> None:
    """ACL='private' is the safe shape — no hit."""
    src = "s3.put_object(Bucket=b, Key=k, Body=body, ACL='private')\n"
    assert not _hits("cstor-acl-public-flag-dead-or-wired", src)


# ---------- Rule 4: cstor-gcp-identity-in-error-message -------------------


def test_gcp_identity_flags_service_account_email_in_string() -> None:
    """SA email embedded inside a string literal."""
    src = (
        "console.error('SA ais-sandbox@ais-asia-southeast1-7ebde40c3e."
        "iam.gserviceaccount.com lacks permission');\n"
    )
    assert _hits("cstor-gcp-identity-in-error-message", src)


def test_gcp_identity_flags_project_id_in_console_error() -> None:
    """Project ID with random suffix inside a console.error call."""
    src = (
        "console.error('Permission denied on project "
        "ais-asia-southeast1-7ebde40c3e for bucket', name);\n"
    )
    assert _hits("cstor-gcp-identity-in-error-message", src)


def test_gcp_identity_flags_python_raise_with_project() -> None:
    """Python raise with project ID in the message."""
    src = (
        "raise RuntimeError('GCP project my-prod-project-1a2b3c4d5e6f "
        "denied write')\n"
    )
    assert _hits("cstor-gcp-identity-in-error-message", src)


def test_gcp_identity_short_project_name_no_suffix_does_not_fire() -> None:
    """A simple project name with no random suffix isn't sensitive."""
    src = "console.error('Project: my-project failed')\n"
    assert not _hits("cstor-gcp-identity-in-error-message", src)


# ---------- Rule 5: cstor-bucket-exists-error-masking ---------------------


def test_bucket_exists_masking_flags_catch_array_false() -> None:
    """The canonical .exists().catch(() => [false]) shape."""
    src = "const [exists] = await bucket.exists().catch(() => [false]);\n"
    assert _hits("cstor-bucket-exists-error-masking", src)


def test_bucket_exists_masking_flags_catch_arrow_false() -> None:
    """Variant: .exists().catch(() => false)."""
    src = "const exists = await bucket.exists().catch(() => false);\n"
    assert _hits("cstor-bucket-exists-error-masking", src)


def test_bucket_exists_masking_flags_catch_with_arg_arrow() -> None:
    """Variant: .exists().catch(e => [false])."""
    src = "await bucket.exists().catch(e => [false]);\n"
    assert _hits("cstor-bucket-exists-error-masking", src)


def test_bucket_exists_masking_flags_python_try_except_pass() -> None:
    """Python try: head_bucket(); except: pass."""
    src = (
        "try:\n"
        "    client.head_bucket(Bucket=b)\n"
        "except Exception:\n"
        "    pass\n"
    )
    assert _hits("cstor-bucket-exists-error-masking", src)


def test_bucket_exists_with_structured_catch_does_not_fire() -> None:
    """A structured catch that re-throws on 403 is fine — no hit."""
    src = (
        "try {\n"
        "  await bucket.exists();\n"
        "} catch (e) {\n"
        "  if (e.code === 403) throw e;\n"
        "  throw new Error('bucket missing');\n"
        "}\n"
    )
    assert not _hits("cstor-bucket-exists-error-masking", src)


# ---------- Rule 6: cstor-signed-url-unescaped-html -----------------------


def test_unescaped_html_flags_template_literal_attr_url() -> None:
    """`<a href="${url}">` with template literal interpolation."""
    src = 'msg += `\\n<a href="${url}">Download</a>`;\n'
    assert _hits("cstor-signed-url-unescaped-html", src)


def test_unescaped_html_flags_jsx_curly_braces_url() -> None:
    """JSX: <a href={gcsResult.url}>."""
    src = "return <a href={gcsResult.url}>Open</a>;\n"
    assert _hits("cstor-signed-url-unescaped-html", src)


def test_unescaped_html_flags_telegram_anchor_with_signedUrl() -> None:
    """Telegram-style HTML with `signedUrl` interpolated raw."""
    src = "const m = `<a href=\"${signedUrl}\">Link</a>`;\n"
    assert _hits("cstor-signed-url-unescaped-html", src)


def test_unescaped_html_encodeURI_pattern_does_not_fire() -> None:
    """Static href with no interpolation — no hit."""
    src = "const m = '<a href=\"https://example.com\">x</a>';\n"
    assert not _hits("cstor-signed-url-unescaped-html", src)


# ---------- Rule 7: cstor-storage-client-no-project-pin -------------------


def test_storage_client_no_pin_flags_new_storage_empty() -> None:
    """`new Storage()` with empty options."""
    src = "const storage = new Storage();\n"
    assert _hits("cstor-storage-client-no-project-pin", src)


def test_storage_client_no_pin_flags_python_storage_client_empty() -> None:
    """Python: storage.Client() with no project=."""
    src = "client = storage.Client()\n"
    assert _hits("cstor-storage-client-no-project-pin", src)


def test_storage_client_no_pin_flags_boto3_client_s3_empty() -> None:
    """boto3.client('s3') with no config — region-pin gap."""
    src = "s3 = boto3.client('s3')\n"
    assert _hits("cstor-storage-client-no-project-pin", src)


def test_storage_client_with_project_pin_does_not_fire() -> None:
    """`new Storage({ projectId: 'my-proj' })` is the safe shape."""
    src = "const storage = new Storage({ projectId: 'my-proj' });\n"
    assert not _hits("cstor-storage-client-no-project-pin", src)


# ---------- Rule 8: cstor-object-name-path-traversal ----------------------


def test_object_name_traversal_flags_permissive_replace() -> None:
    """The canonical `.replace(/[^\\w\\-./]/g, ...)` permissive sanitizer."""
    src = "const sym = String(s).replace(/[^\\w\\-./]/g, '_');\n"
    assert _hits("cstor-object-name-path-traversal", src)


def test_object_name_traversal_flags_python_re_sub_permissive() -> None:
    """Python re.sub with permissive character class containing `.` and `/`."""
    src = "sanitized = re.sub(r'[^a-zA-Z0-9_\\-./]', '_', symbol)\n"
    assert _hits("cstor-object-name-path-traversal", src)


def test_object_name_traversal_flags_template_concat_user_field() -> None:
    """Bare template-literal concat into an object key name."""
    src = "const objectName = `archives/${userInput}.json`;\n"
    assert _hits("cstor-object-name-path-traversal", src)


def test_object_name_strict_sanitizer_does_not_fire() -> None:
    """Strict `[^A-Za-z0-9_-]` sanitizer is OK — no hit."""
    src = "const sym = String(s).replace(/[^A-Za-z0-9_-]/g, '_');\n"
    assert not _hits("cstor-object-name-path-traversal", src)


# ---------- Rule 9: cstor-resumable-upload-disabled -----------------------


def test_resumable_disabled_flags_js_resumable_false() -> None:
    """The canonical `resumable: false` GCS save kwarg."""
    src = "await file.save(body, { resumable: false });\n"
    assert _hits("cstor-resumable-upload-disabled", src)


def test_resumable_disabled_flags_python_resumable_false() -> None:
    """Python google-cloud-storage: resumable=False."""
    src = "blob.upload_from_string(data, resumable=False)\n"
    assert _hits("cstor-resumable-upload-disabled", src)


def test_resumable_default_not_specified_does_not_fire() -> None:
    """No `resumable` kwarg at all — library default fires — no hit."""
    src = "await file.save(body, { contentType: 'application/json' });\n"
    assert not _hits("cstor-resumable-upload-disabled", src)


# ---------- Rule 10: cstor-missing-generation-precondition ----------------


def test_generation_precondition_missing_flags_file_save_no_kwarg() -> None:
    """file.save() with no ifGenerationMatch anywhere in the file."""
    src = (
        "await file.save(body, {\n"
        "  resumable: false,\n"
        "  contentType: 'application/json',\n"
        "});\n"
    )
    assert _hits("cstor-missing-generation-precondition", src)


def test_generation_precondition_missing_flags_python_upload_no_kwarg() -> None:
    """Python blob.upload_from_string with no if_generation_match."""
    src = "blob.upload_from_string(json.dumps(d))\n"
    assert _hits("cstor-missing-generation-precondition", src)


def test_generation_precondition_present_suppresses_hit() -> None:
    """File-level guard: ifGenerationMatch anywhere → no hit."""
    src = (
        "await file.save(body, {\n"
        "  resumable: false,\n"
        "  ifGenerationMatch: 0,\n"
        "});\n"
    )
    assert not _hits("cstor-missing-generation-precondition", src)


def test_generation_precondition_versioning_enabled_suppresses_hit() -> None:
    """File-level guard: versioning: { enabled: true } → no hit."""
    src = (
        "// bucket configured with versioning: { enabled: true }\n"
        "await file.save(body, { resumable: false });\n"
    )
    assert not _hits("cstor-missing-generation-precondition", src)


def test_generation_precondition_pragma_suppresses_hit() -> None:
    """The `# overwrite-ok` pragma is an operator opt-out."""
    src = (
        "# overwrite-ok\n"
        "blob.upload_from_string(d)\n"
    )
    assert not _hits("cstor-missing-generation-precondition", src)


def test_generation_precondition_s3_put_object_no_match() -> None:
    """S3 put_object with no IfMatch — flagged."""
    src = "client.put_object(Bucket=b, Key=k, Body=body)\n"
    assert _hits("cstor-missing-generation-precondition", src)


# ---------- Rule 11: cstor-missing-cmek-integrity-validation -------------


def test_cmek_missing_flags_file_save_no_cmek_no_validation() -> None:
    """file.save() with no kmsKeyName and no validation kwarg."""
    src = (
        "await file.save(body, {\n"
        "  resumable: false,\n"
        "  contentType: 'application/json',\n"
        "});\n"
    )
    assert _hits("cstor-missing-cmek-integrity-validation", src)


def test_cmek_present_suppresses_hit() -> None:
    """kmsKeyName: ... anywhere suppresses the hit."""
    src = (
        "await file.save(body, {\n"
        "  resumable: false,\n"
        "  kmsKeyName: 'projects/p/locations/eu/keyRings/k/cryptoKeys/c',\n"
        "});\n"
    )
    assert not _hits("cstor-missing-cmek-integrity-validation", src)


def test_cmek_crc32c_validation_suppresses_hit() -> None:
    """validation: 'crc32c' suppresses the hit."""
    src = (
        "await file.save(body, {\n"
        "  validation: 'crc32c',\n"
        "});\n"
    )
    assert not _hits("cstor-missing-cmek-integrity-validation", src)


def test_cmek_aws_sse_kms_suppresses_hit() -> None:
    """SSEKMSKeyId anywhere suppresses the hit on S3 upload."""
    src = (
        "client.put_object(Bucket=b, Key=k, Body=body,\n"
        "                  ServerSideEncryption='aws:kms',\n"
        "                  SSEKMSKeyId='arn:aws:kms:...:key/abc')\n"
    )
    assert not _hits("cstor-missing-cmek-integrity-validation", src)


# ---------- Rule 12: cstor-bucket-name-from-caller-options ---------------


def test_bucket_options_override_flags_js_options_dot_bucket() -> None:
    """The canonical `options?.bucket || env.X` shape."""
    src = "const bucketName = options?.bucket || process.env.GCS_BUCKET;\n"
    assert _hits("cstor-bucket-name-from-caller-options", src)


def test_bucket_options_override_flags_js_destructure() -> None:
    """Destructured `const { bucket } = options;` shape."""
    src = "const { bucket } = options;\n"
    assert _hits("cstor-bucket-name-from-caller-options", src)


def test_bucket_options_override_flags_python_options_get_or() -> None:
    """Python: options.get('bucket') or env."""
    src = "bucket_name = options.get('bucket') or os.environ['GCS_BUCKET']\n"
    assert _hits("cstor-bucket-name-from-caller-options", src)


def test_bucket_pure_env_var_does_not_fire() -> None:
    """Direct env-var read with no caller-override — no hit."""
    src = "const bucketName = process.env.GCS_BUCKET;\n"
    assert not _hits("cstor-bucket-name-from-caller-options", src)


# ---------- Rule 13: cstor-bucket-policy-public-allusers -----------------


def test_bucket_policy_public_flags_s3_principal_star() -> None:
    """S3 bucket policy JSON with Principal: '*'."""
    src = '"Principal": "*",\n'
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_public_flags_s3_principal_aws_star() -> None:
    """S3 bucket policy JSON: Principal: { 'AWS': '*' }."""
    src = '"Principal": { "AWS": "*" },\n'
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_public_flags_terraform_acl_public_read() -> None:
    """Terraform aws_s3_bucket_acl: acl = 'public-read'."""
    src = (
        'resource "aws_s3_bucket_acl" "x" {\n'
        '  bucket = aws_s3_bucket.x.id\n'
        '  acl    = "public-read"\n'
        '}\n'
    )
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_public_flags_block_public_acls_false() -> None:
    """Terraform: block_public_acls = false."""
    src = "block_public_acls = false\n"
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_public_flags_gcs_allusers_member() -> None:
    """Terraform google_storage_bucket_iam_binding with allUsers."""
    src = (
        'resource "google_storage_bucket_iam_binding" "x" {\n'
        '  role    = "roles/storage.objectViewer"\n'
        '  members = ["allUsers"]\n'
        '}\n'
    )
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_public_flags_gsutil_iam_ch_allusers() -> None:
    """gsutil iam ch allUsers:objectViewer."""
    src = "gsutil iam ch allUsers:objectViewer gs://bucket\n"
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_public_flags_gcs_pap_inherited() -> None:
    """public_access_prevention = 'inherited' — not enforced."""
    src = 'public_access_prevention = "inherited"\n'
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_public_flags_azure_allow_public_access() -> None:
    """Azure allow_blob_public_access = true."""
    src = "allow_blob_public_access = true\n"
    assert _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_private_principal_does_not_fire() -> None:
    """Principal pointing at a specific account is the safe shape."""
    src = '"Principal": "arn:aws:iam::123:root"\n'
    assert not _hits("cstor-bucket-policy-public-allusers", src)


def test_bucket_policy_pap_enforced_does_not_fire() -> None:
    """public_access_prevention = 'enforced' is the safe shape."""
    src = 'public_access_prevention = "enforced"\n'
    assert not _hits("cstor-bucket-policy-public-allusers", src)


# ---------- Compound / integration ---------------------------------------


def test_real_world_gcs_service_snippet_flags_many_rules() -> None:
    """The real sentinel-V2-claude GCSService snippet flags multiple rules at once."""
    src = (
        "const signedUrlTtl = options?.signedUrlTtl "
        "|| parseInt(process.env.GCS_SIGNED_URL_TTL || '604800', 10);\n"
        "const storage = new Storage();\n"
        "const bucketName = options?.bucket || process.env.GCS_BUCKET;\n"
        "const [exists] = await bucket.exists().catch(() => [false]);\n"
        "const sym = String(s).replace(/[^\\w\\-./]/g, '_');\n"
        "await file.save(body, {\n"
        "  resumable: false,\n"
        "  contentType: 'application/json',\n"
        "});\n"
    )
    findings = csap.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    # All seven of these rules MUST trigger on this real-world snippet.
    expected = {
        "cstor-signed-url-ttl-excessive",
        "cstor-signed-url-ttl-falsy-fallthrough",
        "cstor-storage-client-no-project-pin",
        "cstor-bucket-name-from-caller-options",
        "cstor-bucket-exists-error-masking",
        "cstor-object-name-path-traversal",
        "cstor-resumable-upload-disabled",
        "cstor-missing-generation-precondition",
        "cstor-missing-cmek-integrity-validation",
    }
    missing = expected - rule_ids
    assert not missing, f"missing rules in compound test: {missing}"


def test_findings_are_sorted_by_line_col_rule_id() -> None:
    """Findings come out sorted by (line, col, rule_id)."""
    src = (
        "GCS_PUBLIC = 'true'\n"
        "ttl = 604800\n"
        "storage = storage.Client()\n"
    )
    findings = csap.scan_text(src)
    sorted_findings = sorted(findings, key=lambda f: (f.line, f.column, f.rule_id))
    assert findings == sorted_findings


def test_findings_are_deduped_by_rule_id_line_col() -> None:
    """A single match offset emits exactly one Finding for that rule."""
    src = "const ttl = options?.signedUrlTtl || 604800;\n"
    findings = csap.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_matched_text_is_truncated_at_200_chars() -> None:
    """Long matches get truncated with ellipsis."""
    # Build a long line that matches one of the rules.
    long_value = "x" * 250
    src = f"const u = `<a href=\"${{signedUrl_{long_value}}}\">x</a>`;\n"
    findings = csap.scan_text(src)
    for f in findings:
        assert len(f.matched_text) <= 201, f.matched_text  # 200 chars + ellipsis


# ---------- Regex safety -------------------------------------------------


def test_all_patterns_compile_without_lookaround_or_backref() -> None:
    """RE2-safety: every rule's pattern is plain regex (re module accepts
    lookaround/backref but RE2 does not). We detect lookaround / backref
    by scanning the source-of-pattern strings — every pattern shipped
    must avoid them."""
    forbidden_substrings = ("(?=", "(?!", "(?<=", "(?<!", "(?P=")
    for rule in csap.RULES:
        pat = rule.pattern.pattern
        for forbidden in forbidden_substrings:
            assert forbidden not in pat, f"{rule.id}: contains {forbidden!r}"
        # Backreferences (\1-\9): we look for `\` followed by a digit
        # that is NOT a regex octal escape (which in `re` only fires
        # when 3 octal digits are present — rare in our catalogue).
        # Simpler: forbid `\1`-`\9` outright.
        for d in "123456789":
            assert f"\\{d}" not in pat, f"{rule.id}: backreference \\{d}"


def test_scan_text_does_not_crash_on_unicode() -> None:
    """Unicode input must not raise (UNICODE flag is set)."""
    src = (
        "// 测试 — Chinese comment\n"
        "const ttl = options?.signedUrlTtl || 604800;\n"
        "// эмодзи 🚀\n"
    )
    # Should not raise — and should still find the falsy-fallthrough.
    findings = csap.scan_text(src)
    assert any(
        f.rule_id == "cstor-signed-url-ttl-falsy-fallthrough" for f in findings
    )
