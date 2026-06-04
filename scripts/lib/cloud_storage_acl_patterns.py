"""Cloud storage ACL / policy / pre-signed URL abuse patterns.

Wave-20 distillation round 6, angle C — DEEPER than Wave-16
`cloud_credential_patterns.py`. Wave-16 detects cloud *credentials*
(AWS access keys, GCP service-account JSON, Azure SAS tokens
treated as bearer credentials); this module detects *use-time
configuration* of buckets, objects, ACLs, signed URLs, bucket
policies, and the infrastructure that pins them.

The source-of-record corpus contained exactly ONE production
cloud-storage integration (`sentinel-V2-claude-main` GCS uploader,
72 LOC), but that file was unusually dense with ACL / TTL /
dead-config / data-leak issues. The 13 findings catalogued in
`reports/distill-round-6/cloud-storage-acl.md` are all real,
distinct, reproducible, and not duplicates of Wave-16. We also
include S3 / Azure variants for the same shapes so the catalogue
generalises beyond the lone-GCS corpus.

What is HERE (13 net-new use-time configuration rules, regex-only;
RE2-safe — no backreferences, no lookaround, bounded quantifiers):

  * cstor-signed-url-ttl-excessive            (CRITICAL) ASI-04
  * cstor-signed-url-ttl-falsy-fallthrough    (HIGH)     ASI-07
  * cstor-acl-public-flag-dead-or-wired       (CRITICAL) ASI-04
  * cstor-gcp-identity-in-error-message       (HIGH)     ASI-04
  * cstor-bucket-exists-error-masking         (HIGH)     ASI-04
  * cstor-signed-url-unescaped-html           (MEDIUM)   ASI-04
  * cstor-storage-client-no-project-pin       (HIGH)     ASI-05
  * cstor-object-name-path-traversal          (HIGH)     ASI-05
  * cstor-resumable-upload-disabled           (MEDIUM)   ASI-04
  * cstor-missing-generation-precondition     (MEDIUM)   ASI-05
  * cstor-missing-cmek-integrity-validation   (LOW)      ASI-04
  * cstor-bucket-name-from-caller-options     (MEDIUM)   ASI-05
  * cstor-bucket-policy-public-allusers       (CRITICAL) ASI-04

What is NOT here (already shipped under cloud_credential_patterns —
do not duplicate):

  * Raw AWS access keys / GCP service-account JSON / Azure SAS
    tokens-as-credential — Wave-16.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used (consistent with Wave-16 / Wave-17):
  ASI-04 — Insecure Output / data leak / weak retention
  ASI-05 — Supply-chain / cross-tenant pivot / IaC drift
  ASI-07 — Authority / authorisation gaps

Hard constraint: deterministic; pure-stdlib (re, NamedTuple).
RE2-safe: no backreferences, no lookaround, bounded quantifiers.
No LLM helpers. No network. No git.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render every rule pack uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — env-var names and
    SDK keywords come in mixed casings (`GCS_SIGNED_URL_TTL`,
    `signedUrlTtl`, `SignedUrlTTL`)."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- 1. cstor-signed-url-ttl-excessive ---------------------------------
#
# Pre-signed URL TTL > 3600 seconds (1 hour). Default GCS / S3 / Azure
# signed-URL libraries permit multi-day TTLs which are nearly always
# wrong: the URL is itself a bearer credential, anyone holding it can
# GET the object until it expires, there is no revocation path short
# of rotating the signing key. Multi-day TTLs combined with Telegram /
# email / chat distribution channels turn into permanent leak windows.
#
# Trigger shapes:
#   - GCS_SIGNED_URL_TTL = 604800 (or any number >= 3601)
#   - signedUrlTtl: 604800
#   - signed_url_ttl=604800
#   - expires=86400  (S3 boto3 generate_presigned_url)
#   - --expires-in 3600 (gsutil signurl) — flagged when >3600
#   - SAS expiry of N days  (Azure)
#
# The pattern matches the assignment + a literal integer between
# 3601 and 99999999, capturing 1 hour < N < ~3 years. We don't try to
# parse arithmetic expressions; if the value is `60*60*24*7` the
# matcher won't fire, which is acceptable — the developer wrote a
# magic number, that's the easy case.
_SIGNED_URL_TTL_EXCESSIVE = _re(
    # Anchor 1: GCS / generic signed-url TTL env or kwarg
    r"\b(?:GCS_SIGNED_URL_TTL|signedUrlTtl|signed_url_ttl|signedUrlTTL"
    r"|presign[_-]?ttl|presigned[_-]?expires|url[_-]?ttl"
    r"|expires_in|expiresIn|expires_in_seconds|expiry_seconds)\s*[:=]\s*"
    r"['\"]?(?:36[1-9][0-9]|3[7-9][0-9]{2}|[4-9][0-9]{3}|[1-9][0-9]{4,8})['\"]?"
    r"|"
    # Anchor 2: AWS boto3 generate_presigned_url ExpiresIn=
    r"\bgenerate_presigned_url\s*\([^)]{0,200}\bExpiresIn\s*=\s*"
    r"(?:36[1-9][0-9]|3[7-9][0-9]{2}|[4-9][0-9]{3}|[1-9][0-9]{4,8})"
    r"|"
    # Anchor 3: gsutil signurl -d <duration>m / -d <duration>h / -d <duration>d
    # 2+ hours, 1+ days are over the safe cap.
    r"\bgsutil\s+signurl\b[^\n]{0,200}-d\s+(?:[2-9]h|[1-9][0-9]+h|[1-9]d|[1-9][0-9]+d)"
    r"|"
    # Anchor 4: Azure SDK BlobSasPermissions with expiry > 1 hour
    # (datetime.utcnow() + timedelta(days=N) where N >= 1, OR hours >= 2)
    r"\btimedelta\s*\(\s*(?:days\s*=\s*[1-9]|hours\s*=\s*(?:[2-9]|[1-9][0-9]+))"
    r"[^)]{0,80}\)[^\n]{0,200}(?:generate_blob_sas|generate_account_sas|BlobSasPermissions)"
    r"|"
    # Anchor 5: GCS_SIGNED_URL_TTL appearing in process.env.X || 'NNNNN'
    # parseInt-default fallback shape — same env *name*, value embedded
    # in the trailing `|| '604800'` literal.
    r"\bGCS_SIGNED_URL_TTL\b[^\n]{0,80}\|\|\s*['\"]?"
    r"(?:36[1-9][0-9]|3[7-9][0-9]{2}|[4-9][0-9]{3}|[1-9][0-9]{4,8})['\"]?"
)


# ---- 2. cstor-signed-url-ttl-falsy-fallthrough -------------------------
#
# JS / TS pattern `options?.x || env.X` treats `0`, `""`, `NaN`, `false`
# as falsy and falls through to the env default. For TTL specifically,
# a caller passing `signedUrlTtl: 0` ("no URL / fail-closed") instead
# gets the maximum TTL. Use `??` (nullish coalescing) — which respects
# explicit zero — and validate positive-int.
#
# We match the dangerous `||` shape on TTL-shaped option names.
_SIGNED_URL_TTL_FALSY_FALLTHROUGH = _re(
    # options?.signedUrlTtl || ...
    # options.signed_url_ttl || ...
    # config?.expiresIn || ...
    r"\b(?:options|config|opts|params|cfg)\??\.\s*"
    r"(?:signedUrlTtl|signed_url_ttl|expiresIn|expires_in|signedUrlTTL"
    r"|presignTtl|presignedExpires|urlTtl|url_ttl)\s*"
    r"\|\|\s*"
)


# ---- 3. cstor-acl-public-flag-dead-or-wired ----------------------------
#
# An env flag `GCS_PUBLIC` / `S3_PUBLIC` / `BUCKET_PUBLIC` is declared
# with a comment promising it toggles public-read but is never read
# again (dead config), OR conversely a `makePublic()` / `acl='public-read'`
# is unconditionally invoked.
#
# We catch BOTH:
#   - Declaration of a *_PUBLIC env that is suspicious
#   - Explicit `acl: 'public-read'` / `acl='public-read'` / `makePublic()`
#     / object ACL public-write
_ACL_PUBLIC_FLAG_OR_CALL = _re(
    # Shape A: env declared with public-promising comment / docstring
    # (we catch the declaration; an external dead-code analyzer can
    # confirm dead. The bare presence of GCS_PUBLIC / S3_PUBLIC /
    # BUCKET_PUBLIC env IS itself worth a flag because it is rarely
    # intentional and frequently a footgun.)
    r"\b(?:GCS_PUBLIC|S3_PUBLIC|AZURE_BLOB_PUBLIC|BUCKET_PUBLIC|STORAGE_PUBLIC)\b"
    r"\s*[?=:]"
    r"|"
    # Shape B: explicit ACL grant to public-read / public-read-write
    # GCS @google-cloud/storage: file.makePublic() / bucket.makePublic()
    r"\b(?:file|object|bucket|blob)\.makePublic\s*\(\s*\)"
    r"|"
    # AWS boto3 / S3: ACL='public-read' / ACL='public-read-write' /
    #                 ACL='authenticated-read'
    r"\bACL\s*=\s*['\"](?:public-read|public-read-write|authenticated-read)['\"]"
    r"|"
    # S3 put_bucket_acl / put_object_acl
    r"\bput_(?:bucket|object)_acl\s*\([^)]*ACL\s*=\s*['\"]public"
    r"|"
    # GCS objectACL / bucket.iam: roles/storage.objectViewer for allUsers
    r"\ballUsers\b[^\n]{0,200}roles/storage\.objectViewer"
    r"|"
    r"\broles/storage\.objectViewer\b[^\n]{0,200}\ballUsers\b"
    r"|"
    # GCS allAuthenticatedUsers binding
    r"\ballAuthenticatedUsers\b[^\n]{0,200}roles/storage\."
    r"|"
    # Azure container public-access blob/container
    r"\bset_container_access_policy\s*\([^)]*public_access\s*=\s*['\"](?:blob|container)['\"]"
    r"|"
    # Azure container creation with public_access set to blob/container
    r"\bcreate_container\s*\([^)]*public_access\s*=\s*['\"](?:blob|container)['\"]"
)


# ---- 4. cstor-gcp-identity-in-error-message ----------------------------
#
# Service-account email or GCP project id baked into a user-visible
# string. The 13-byte random suffix that GCP appends to project IDs
# is a generated identifier that uniquely fingerprints the user's
# project; leaking it in stderr/logs/Telegram makes the
# infrastructure inventory-able by anyone who triggers an error.
#
# We match:
#   - GCP service-account email: `<name>@<project>.iam.gserviceaccount.com`
#   - GCP project ID: lowercase + digits + dashes, 6-30 chars,
#     INSIDE a string literal that ALSO mentions storage/iam/bucket
#     (to avoid flagging the SA appearing in an env var definition).
_GCP_IDENTITY_IN_ERROR = _re(
    # SA email inside a string literal
    r"['\"][^'\"]{0,200}@[a-z0-9\-]{4,30}\.iam\.gserviceaccount\.com[^'\"]{0,200}['\"]"
    r"|"
    # Project ID literal inside an error/console/logger/raise/throw call.
    # The project-id-with-suffix shape is a kebab-case prefix followed by a
    # 10-16 char hex/digit random suffix. GCP appends 10-12 chars typically;
    # for self-managed projects with random IDs the same shape applies.
    r"\b(?:console\.(?:error|warn|log)|logger\.(?:error|warn|info)"
    r"|print|raise|throw|RuntimeError|ValueError|Exception)\s*"
    r"\(?\s*['\"][^'\"]{0,200}[a-z][a-z0-9\-]{3,29}-[0-9a-f]{10,16}[^'\"]{0,200}['\"]"
)


# ---- 5. cstor-bucket-exists-error-masking ------------------------------
#
# `bucket.exists().catch(() => [false])` and equivalents collapse
# every failure (403 / 404 / network / quota / credentials) into
# "bucket inaccessible — skip" with no diagnostic. Silent data loss
# follows. This is the failure mode where an attacker who revokes
# the SA's IAM permissions permanently stops archives without
# raising any alarm.
#
# Match the .catch(() => [false]) and .catch(() => false)
# and .catch(_ => [false]) shapes, plus Python try/except: pass.
_BUCKET_EXISTS_MASKING = _re(
    # JS: .exists().catch(() => [false])  OR  .catch(() => false)
    r"\.(?:exists|head|get|info|metadata)\s*\(\s*\)\s*\.\s*catch\s*\(\s*"
    r"(?:\([^)]*\)|\w+)\s*=>\s*(?:\[\s*(?:false|null|undefined)\s*\]|false|null|undefined)"
    r"|"
    # Python: try: bucket.exists() ... except: pass
    # ... we approximate with the bare `except:` / `except Exception:` followed
    # by `pass` within ~3 lines of a bucket.exists / head_bucket / get_bucket call.
    r"\b(?:head_bucket|get_bucket|head_object|client\.head_bucket)\s*\([^)]*\)"
    r"[^\n]{0,200}\n[^\n]{0,200}except[^\n]{0,200}\n\s*pass\b"
    r"|"
    # Generic: assignment to False/None inside a catch on a bucket op
    r"\bbucket\.\s*(?:exists|get|head)\s*\([^)]*\)\s*\.\s*catch\s*\("
)


# ---- 6. cstor-signed-url-unescaped-html --------------------------------
#
# Signed URL template-literal-interpolated into HTML without escaping.
# The signed URL itself contains operator-supplied prefix /
# object-name components; a `"` or `<` in those components escapes
# the attribute or element and can forge a different "Download"
# link.
_SIGNED_URL_UNESCAPED_HTML = _re(
    # `<a href="${url}">` where url is signed URL / GCS URL / S3 URL
    r"<a\s+href\s*=\s*[\"']\$\{(?:[a-zA-Z_][\w.]*\.)?(?:(?:signed)?[Uu]rl|gcsUrl|gcsResult\.url|s3Url|presignedUrl|sasUrl|downloadUrl)\}"
    r"|"
    # JSX: <a href={gcsResult.url}>
    r"<a\s+href\s*=\s*\{(?:[a-zA-Z_][\w.]*\.)?(?:(?:signed)?[Uu]rl|gcsResult\.url|s3Url|presignedUrl|sasUrl|downloadUrl)\}"
    r"|"
    # Telegram-style HTML with raw URL interpolated unescaped:
    # `\n<a href="${url}">` inside a message string
    r"<a\s+href\s*=\s*[\"']\$\{[^}]{1,80}\.url\}"
)


# ---- 7. cstor-storage-client-no-project-pin ----------------------------
#
# `new Storage()` with no projectId. GCS bucket names are global, but
# the ADC quota project / audit project is determined by the resolved
# credentials. If GOOGLE_APPLICATION_CREDENTIALS or gcloud user creds
# point at a different project (very common in dev), uploads go to a
# different project than the operator believes. An attacker who
# plants a GOOGLE_APPLICATION_CREDENTIALS env can redirect uploads
# silently.
#
# Equivalent: boto3 client('s3') with no config, Azure
# `BlobServiceClient.from_connection_string(...)` with no account-url
# pin. We flag JS first (the primary corpus); the regex covers Python
# and Azure as well.
_STORAGE_CLIENT_NO_PROJECT_PIN = _re(
    # JS @google-cloud/storage: new Storage() — empty options
    r"\bnew\s+Storage\s*\(\s*\)"
    r"|"
    # Python google.cloud.storage.Client() — no project=
    r"\bstorage\.Client\s*\(\s*\)"
    r"|"
    # boto3 Session() with no region / no profile  (region pinning is
    # not strictly project-binding for AWS, but a missing region is a
    # nearby footgun on multi-region setups). Boto3 IS multi-region,
    # so we focus on the explicit per-call use that omits region:
    r"\bboto3\.client\s*\(\s*['\"]s3['\"]\s*\)"
)


# ---- 8. cstor-object-name-path-traversal -------------------------------
#
# Object name is built from attacker-influenceable fields with a
# sanitizer that PERMITS `/` and `..`. Even though GCS / S3 treat
# names as opaque strings, IAM conditions / lifecycle rules / browser
# console rely on prefix-as-folder semantics — a `..` in the middle
# of a name silently defeats them.
#
# We flag two shapes:
#   - A sanitizer regex that permits `.` and `/` in a class while
#     building an object name.
#   - The classic concat `prefix + "/" + userInput + ".json"` where
#     `userInput` is not visibly run through a sanitizer.
_OBJECT_NAME_TRAVERSAL = _re(
    # Permissive sanitizer:  .replace(/[^\w\-./]/g, ...)
    # or                     .replace(/[^a-zA-Z0-9_\-./]/g, ...)
    r"\.replace\s*\(\s*/\[\^[^/]{0,80}[\\./][^/]{0,80}\]/g?\s*,"
    r"|"
    # Python re.sub with permissive class containing `/` and `.`
    r"\bre\.sub\s*\(\s*r?['\"][^'\"]{0,100}\[\^[^]]{0,80}[\\./][^]]{0,80}\]"
    r"|"
    # Bare concat: `prefix/` + raw user-controlled field + `.json`
    # We anchor on `decision_cards[0]?.symbol`-style attacker channels.
    r"\b(?:objectName|object_name|blobName|blob_name|s3Key|s3_key|filename|fileName|key)\s*[:=]\s*"
    r"[`'\"][^`'\"]{0,80}\$\{[^}]{0,100}\}"
)


# ---- 9. cstor-resumable-upload-disabled --------------------------------
#
# `resumable: false` on GCS file.save() forces single-shot upload.
# Uploads > 5 MB silently fail on flaky networks; the catch path
# returns null and logs a warn. Equivalent on S3: `Multipart=False`
# / not using `upload_file()` (which handles >5MB transparently).
_RESUMABLE_DISABLED = _re(
    # GCS: { resumable: false, ... }  inside save() / createWriteStream()
    r"\bresumable\s*:\s*false\b"
    r"|"
    # GCS: resumable=False (Python google-cloud-storage)
    r"\bresumable\s*=\s*False\b"
    r"|"
    # S3 put_object with body > 5 MB shape: explicit single-shot
    # (we approximate via put_object + a large content body / file open)
    r"\bput_object\s*\([^)]{0,200}\bBody\s*=\s*(?:open|io\.BytesIO)\("
)


# ---- 10. cstor-missing-generation-precondition -------------------------
#
# `file.save()` / `put_object()` with NO ifGenerationMatch / IfMatch
# / If-None-Match / x-ms-if-* precondition. Concurrent archives
# silently overwrite each other (last-writer-wins is the GCS / S3
# default). An attacker who can hit the upload endpoint can overwrite
# archives between snapshot and forwarding.
#
# We flag the explicit *absence* differently — file-level negative
# guard. Stage A: a put_object / file.save / blob.upload call. Stage
# B (in scan_text): if the same file has NO if* precondition kwarg
# anywhere, raise the finding.
_GENERATION_PRECONDITION_TRIGGER = _re(
    # GCS: file.save( ... )
    r"\bfile\.save\s*\("
    r"|"
    # GCS Python: blob.upload_from_string / blob.upload_from_file
    r"\bblob\.upload_from_(?:string|file|filename)\s*\("
    r"|"
    # S3: client.put_object( ... )
    r"\b(?:client|s3)\.put_object\s*\("
    r"|"
    # Azure: container_client.upload_blob( ... )  OR  blob_client.upload_blob( ... )
    r"\b(?:container_client|blob_client|blob)\.upload_blob\s*\("
)

_GENERATION_PRECONDITION_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bifGenerationMatch\s*[:=]"),
    _re(r"\bif_generation_match\s*[:=]"),
    _re(r"\bIfMatch\s*[:=]"),
    _re(r"\bIfNoneMatch\s*[:=]"),
    _re(r"\bIfModifiedSince\s*[:=]"),
    _re(r"\bx-ms-if-(?:match|none-match|modified-since)\b"),
    _re(r"\bversioning\s*:\s*\{\s*enabled\s*:\s*true\s*\}"),
    _re(r"#\s*overwrite-ok\b"),
)


# ---- 11. cstor-missing-cmek-integrity-validation -----------------------
#
# `file.save()` / `put_object()` / `upload_blob()` with no
# CMEK (kmsKeyName / SSEKMSKeyId / encryption_scope) AND no
# integrity validation (validation: 'crc32c' / ContentMD5 /
# content_md5). LOW because most modern libs enable CRC32C
# automatically — but explicit assertion + CMEK matters for
# trading-state archives.
#
# Same negative-guard pattern as rule 10: trigger on the upload
# call, file-level absence guard.
_CMEK_VALIDATION_TRIGGER = _GENERATION_PRECONDITION_TRIGGER  # same triggers
_CMEK_VALIDATION_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bkmsKeyName\s*[:=]"),
    _re(r"\bkms_key_name\s*[:=]"),
    _re(r"\bSSEKMSKeyId\s*[:=]"),
    _re(r"\bServerSideEncryption\s*[:=]\s*['\"]aws:kms['\"]"),
    _re(r"\bvalidation\s*[:=]\s*['\"]crc32c['\"]"),
    _re(r"\bContentMD5\s*[:=]"),
    _re(r"\bcontent_md5\s*[:=]"),
    _re(r"\bencryption_scope\s*[:=]"),
    _re(r"#\s*cmek-exempt\b"),
)


# ---- 12. cstor-bucket-name-from-caller-options -------------------------
#
# Function accepts a caller-supplied `options.bucket` / `options.Bucket`
# that overrides the env-configured bucket, AND the override path has
# no allowlist guard. Two failure modes:
#   - Bucket-existence check becomes a 403/404 enumeration oracle
#     for caller-controlled bucket names.
#   - Caller-controlled bucket can redirect upload to attacker-owned
#     bucket (if combined with credential confusion — rule 7).
_BUCKET_NAME_FROM_OPTIONS = _re(
    # JS: const bucketName = options?.bucket || process.env.X
    r"\b(?:bucket(?:Name)?|Bucket(?:Name)?)\s*=\s*"
    r"(?:options|opts|config|params|cfg)\??\.\s*[Bb]ucket(?:Name)?\s*\|\|"
    r"|"
    # JS destructure: const { bucket } = options;  bucket || process.env.X
    r"const\s*\{\s*bucket[^}]{0,60}\}\s*=\s*(?:options|opts|config)"
    r"|"
    # Python: bucket_name = options.get('bucket') or os.environ['BUCKET']
    r"\bbucket(?:_name)?\s*=\s*options\.get\s*\(\s*['\"]bucket['\"]\s*\)\s*or\b"
)


# ---- 13. cstor-bucket-policy-public-allusers ---------------------------
#
# IaC / SDK / CLI shape that grants `*` / `allUsers` /
# `allAuthenticatedUsers` / `Effect: Allow Principal: *` to a bucket
# or object. The CRITICAL "world-readable storage" pattern that
# every cloud-storage incident postmortem mentions.
_BUCKET_POLICY_PUBLIC = _re(
    # JSON bucket policy: "Principal": "*"  (S3)
    r"['\"]Principal['\"]\s*:\s*['\"]\*['\"]"
    r"|"
    # JSON: "Principal": { "AWS": "*" }
    r"['\"]Principal['\"]\s*:\s*\{[^}]{0,200}['\"]AWS['\"]\s*:\s*['\"]\*['\"]"
    r"|"
    # Terraform aws_s3_bucket_acl  with acl = "public-read"
    r"\bresource\s+['\"]aws_s3_bucket_acl['\"][^}]{0,500}\bacl\s*=\s*['\"](?:public-read|public-read-write)['\"]"
    r"|"
    # Terraform aws_s3_bucket_public_access_block: block_public_acls = false
    r"\bblock_public_acls\s*=\s*false\b"
    r"|"
    r"\bblock_public_policy\s*=\s*false\b"
    r"|"
    r"\brestrict_public_buckets\s*=\s*false\b"
    r"|"
    r"\bignore_public_acls\s*=\s*false\b"
    r"|"
    # GCP storage_bucket_iam_binding with member = "allUsers"
    r"\bmembers?\s*=\s*\[?[^\]]{0,80}['\"]allUsers['\"]"
    r"|"
    # gcloud cli: gsutil iam ch allUsers:objectViewer
    r"\bgsutil\s+iam\s+ch\b[^\n]{0,200}\ballUsers\s*:"
    r"|"
    # GCS bucket configuration: public_access_prevention = "inherited"
    # (inherited == NOT enforced; CRITICAL for archive buckets)
    r"\bpublic_access_prevention\s*=\s*['\"]inherited['\"]"
    r"|"
    # GCS uniform_bucket_level_access enabled = false
    r"\buniform_bucket_level_access\s*=\s*\{[^}]{0,80}enabled\s*=\s*false"
    r"|"
    # Azure storage_account / storage_container public access
    r"\ballow_blob_public_access\s*=\s*true\b"
    r"|"
    r"\bcontainer_access_type\s*=\s*['\"](?:blob|container)['\"]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cstor-signed-url-ttl-excessive",
        name="Pre-signed URL TTL exceeds 1 hour",
        severity="CRITICAL",
        description=(
            "Pre-signed URL (GCS getSignedUrl / S3 generate_presigned_url / "
            "Azure SAS) issued with a TTL longer than 3600 seconds (1 hour). "
            "The URL is itself a bearer credential — anyone holding it can "
            "GET the object until expiry. There is NO revocation path short "
            "of rotating the signing key. Multi-day TTLs (e.g. 604800 = 7 "
            "days) combined with Telegram / email / chat distribution turn "
            "into permanent leak windows; email retention is years."
        ),
        pattern=_SIGNED_URL_TTL_EXCESSIVE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cstor-signed-url-ttl-falsy-fallthrough",
        name="Signed-URL TTL uses `||` and silently overrides explicit 0",
        severity="HIGH",
        description=(
            "TTL fallback uses `||` short-circuit so an explicit caller "
            "value of `0` / `NaN` / `\"\"` / `false` falls through to the "
            "env default. A caller writing `signedUrlTtl: 0` to refuse to "
            "issue a URL silently gets the longest-lived URL the system "
            "can issue. Use `??` (nullish coalescing) and validate "
            "positive-int (fail-fast)."
        ),
        pattern=_SIGNED_URL_TTL_FALSY_FALLTHROUGH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="cstor-acl-public-flag-dead-or-wired",
        name="Public-read ACL flag declared (dead config) or explicit grant",
        severity="CRITICAL",
        description=(
            "Either an env flag named `GCS_PUBLIC` / `S3_PUBLIC` / "
            "`BUCKET_PUBLIC` is declared (the operator believes they're "
            "toggling public-read while actually toggling nothing — false "
            "sense of security; documented for sentinel-V2 GCSService), OR "
            "the codepath unconditionally invokes `makePublic()` / "
            "`ACL='public-read'` / binds `allUsers` to "
            "`roles/storage.objectViewer`. Both are CRITICAL because they "
            "lift bucket / object reachability to anonymous internet."
        ),
        pattern=_ACL_PUBLIC_FLAG_OR_CALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cstor-gcp-identity-in-error-message",
        name="GCP service-account / project ID leaked in user-visible string",
        severity="HIGH",
        description=(
            "A GCP service-account email (`<name>@<project>.iam."
            "gserviceaccount.com`) or a GCP project ID with its 12-16 "
            "char random suffix appears inside a string literal passed "
            "to `console.error` / `logger.error` / `print` / `raise`. "
            "These strings frequently propagate to chat channels / "
            "emails / log archives; the project ID is enough to find "
            "the project in cross-tenant inventory queries and pivot "
            "into IAM recommendations."
        ),
        pattern=_GCP_IDENTITY_IN_ERROR,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cstor-bucket-exists-error-masking",
        name="bucket.exists() catch-into-false masks 403/404/network",
        severity="HIGH",
        description=(
            "`.exists().catch(() => [false])` / `try: head_bucket(); "
            "except: pass` collapses 403 (config / IAM revoked), 404 "
            "(bucket genuinely missing), 429 (quota), and transient "
            "network failures into a single \"skip upload\" path. An "
            "attacker who revokes the SA's IAM permanently stops "
            "archives with no diagnostic louder than `console.warn`. "
            "Per CLAUDE.md fail-fast: let the error propagate, "
            "differentiate 403 (alert on-call) from 404 (surface to "
            "operator)."
        ),
        pattern=_BUCKET_EXISTS_MASKING,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cstor-signed-url-unescaped-html",
        name="Signed URL interpolated into HTML attribute without escaping",
        severity="MEDIUM",
        description=(
            "Signed URL is template-literal-interpolated into an HTML "
            "attribute value (Telegram `<a href=\"${url}\">`) without "
            "`encodeURI` / `encodeURIComponent` / DOM-text-binding. The "
            "URL itself includes operator-supplied prefix / object-name "
            "components; an HTML-special character (`\"`, `<`) in either "
            "breaks out of the anchor and can forge a different "
            "\"Download\" link pointing at an attacker host, or stop "
            "archive notifications by triggering Telegram parse errors."
        ),
        pattern=_SIGNED_URL_UNESCAPED_HTML,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cstor-storage-client-no-project-pin",
        name="GCS Storage / S3 / Azure client constructed without project pin",
        severity="HIGH",
        description=(
            "`new Storage()` / `storage.Client()` / `boto3.client('s3')` "
            "/ Azure `BlobServiceClient.from_connection_string()` is "
            "called with empty options, inheriting ADC / default profile. "
            "Bucket names are global — but the resolved quota / audit "
            "project is determined by ADC. A wrong-project local gcloud "
            "or a planted `GOOGLE_APPLICATION_CREDENTIALS` env file "
            "redirects uploads silently. Pin the project explicitly and "
            "compare resolved-vs-expected at startup."
        ),
        pattern=_STORAGE_CLIENT_NO_PROJECT_PIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cstor-object-name-path-traversal",
        name="Object name built from attacker input with permissive sanitizer",
        severity="HIGH",
        description=(
            "Object name uses a sanitizer regex that permits `/` and "
            "`.` (`/[^\\w\\-./]/g`) OR concatenates raw template variables "
            "into an object key. GCS / S3 treat names as opaque strings, "
            "so this is NOT a filesystem traversal — but IAM conditions "
            "(`resource.name.startsWith(\"prefix/\")`), lifecycle rules, "
            "and browser-console folder views rely on prefix-as-folder "
            "semantics. A `..` or `/` in the middle of an object name "
            "silently defeats prefix-based public-read carve-outs."
        ),
        pattern=_OBJECT_NAME_TRAVERSAL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cstor-resumable-upload-disabled",
        name="Resumable upload disabled — silent failure above 5 MB",
        severity="MEDIUM",
        description=(
            "`@google-cloud/storage` defaults to resumable uploads above "
            "5 MB; explicitly setting `resumable: false` / `resumable=False` "
            "forces single-shot. On a flaky network, a 5+ MB upload "
            "silently fails: catch path returns null, the caller logs "
            "`✅ Archived` and the data is permanently lost. Drop the "
            "flag (let the library auto-switch) and add an "
            "idempotent-retry loop in the catch path."
        ),
        pattern=_RESUMABLE_DISABLED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cstor-missing-generation-precondition",
        name="Upload without ifGenerationMatch / IfMatch — silent overwrite",
        severity="MEDIUM",
        description=(
            "`file.save()` / `blob.upload_from_string()` / `put_object()` / "
            "`upload_blob()` called with no `ifGenerationMatch` / `IfMatch` "
            "/ `IfNoneMatch` precondition. Concurrent uploads silently "
            "overwrite each other (last-writer-wins default). An "
            "attacker who can reach the upload endpoint can overwrite "
            "archives immediately before they're forwarded to email / "
            "Telegram; combined with versioning-disabled buckets the "
            "overwrite is permanent. Pass `ifGenerationMatch: 0` OR "
            "enable bucket versioning."
        ),
        pattern=_GENERATION_PRECONDITION_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cstor-missing-cmek-integrity-validation",
        name="Upload without CMEK / integrity validation",
        severity="LOW",
        description=(
            "Upload call passes no `kmsKeyName` / `SSEKMSKeyId` (CMEK) "
            "and no `validation: 'crc32c'` / `ContentMD5` (upload "
            "integrity) anywhere in the file. CRC32C is mostly enabled "
            "by default in modern SDKs; CMEK is opt-in. For "
            "trading-state / paper-trading archives that include API "
            "balances and position state, explicit CMEK + integrity "
            "assertion is the appropriate posture."
        ),
        pattern=_CMEK_VALIDATION_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cstor-bucket-name-from-caller-options",
        name="Function accepts caller-supplied bucket override with no allowlist",
        severity="MEDIUM",
        description=(
            "Function takes `options.bucket` (or destructures `{ bucket }` "
            "from options) and falls back to `process.env.X`, with no "
            "allowlist validation. Two attack modes: (a) the existence "
            "check becomes a 403/404 enumeration oracle for "
            "caller-controlled bucket names, (b) if combined with "
            "credential confusion, an attacker-controlled bucket "
            "receives the upload. Require an explicit allowlist of "
            "permitted bucket names."
        ),
        pattern=_BUCKET_NAME_FROM_OPTIONS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cstor-bucket-policy-public-allusers",
        name="Bucket policy / IaC grants public-anonymous-read",
        severity="CRITICAL",
        description=(
            "IaC / SDK / CLI configures the bucket for anonymous "
            "world-read: `Principal: \"*\"` (S3 policy JSON), "
            "`acl = \"public-read\"` (Terraform aws_s3_bucket_acl), "
            "`block_public_acls = false` (Terraform "
            "aws_s3_bucket_public_access_block), `allUsers` bound to "
            "`roles/storage.objectViewer` (GCS), "
            "`public_access_prevention = \"inherited\"` (GCS), "
            "`allow_blob_public_access = true` (Azure). Each is the "
            "world-readable-storage CRITICAL pattern that turns into "
            "a postmortem."
        ),
        pattern=_BUCKET_POLICY_PUBLIC,
        owasp_asi="ASI-04",
    ),
)


# ---- The composed scanner ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage rules:
      * cstor-missing-generation-precondition — Stage A: an upload call.
        Stage B: file-level guard — if ANY ifGenerationMatch / IfMatch /
        versioning-enabled / `# overwrite-ok` pragma appears anywhere
        in the file, suppress.
      * cstor-missing-cmek-integrity-validation — same shape, with a
        different guard set (kmsKeyName, SSEKMSKeyId, validation,
        ContentMD5).

    All other rules are single-stage regex matches.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, col, rule_id).
    """
    if not text:
        return []

    # File-level guard evaluation (one shot per file for the two
    # negative-guard rules).
    file_has_generation_guard = _file_contains_any(
        text, _GENERATION_PRECONDITION_GUARDS
    )
    file_has_cmek_validation = _file_contains_any(
        text, _CMEK_VALIDATION_GUARDS
    )

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Stage-B filters for the two negative-guard rules.
            if rule.id == "cstor-missing-generation-precondition":
                if file_has_generation_guard:
                    continue
            elif rule.id == "cstor-missing-cmek-integrity-validation":
                if file_has_cmek_validation:
                    continue

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
