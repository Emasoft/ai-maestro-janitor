"""HIPAA / PHI healthcare-specific anti-pattern detectors.

Wave-27 distillation round 13 — HIPAA Protected Health Information
(PHI) exposure on healthcare protocol surfaces (HL7 v2, FHIR, DICOM,
openEHR, ICD-10/SNOMED) and BAA-coverage gaps. Catalogue of 8
anti-patterns documented in
`reports/distill-round-13/hipaa-phi.md`. Targets PHI-specific
combination semantics that generic PII detectors miss.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic email / SSN / IP / cookie PII regexes —
    `gdpr_privacy_patterns.py` (general PII outside healthcare).
  * PCI cardholder-data patterns (PAN, CVV, Track-2) —
    no overlap with HL7/FHIR/DICOM surfaces.
  * Generic `SELECT *` SQL detector — covered elsewhere; AQL here
    is openEHR-specific.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * hipaa-phi-hl7-pid-segment-logged                  (CRITICAL)
  * hipaa-phi-fhir-route-no-auth-middleware           (CRITICAL)
  * hipaa-phi-fhir-bundle-unbounded-searchset         (HIGH)
  * hipaa-phi-dicom-patient-id-in-path                (HIGH)
  * hipaa-phi-baa-marker-missing-on-cloud-sdk-call    (HIGH)
  * hipaa-phi-icd-code-with-identifier-in-log         (CRITICAL)
  * hipaa-phi-openehr-aql-no-ehr-id-filter            (HIGH)
  * hipaa-phi-hl7-mllp-plaintext-public-bind          (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / data leak (PHI in logs, file paths, error trackers)
  ASI-04 — Information leak (PHI in logs, broken object-property
                              authz, excessive data exposure)
  ASI-05 — Supply-chain / authorisation gaps (FHIR route without
                                                auth middleware)
  ASI-07 — Authority / authorisation gaps (broken FLA, unbounded
                                            bundles, missing BAA flag)

All regexes are RE2-compatible (no backreferences, no lookbehind on
variable-length subpatterns, no catastrophic backtracking shapes).
Patterns are PRE-COMPILED at module load. Fail-fast: callers receive
structured Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / voice_audio_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind on variable runs."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- H1 : hipaa-phi-hl7-pid-segment-logged ------------------------------


# Anchor: a logging primitive sink followed (within ≤120 chars on the
# same line) by an HL7 v2 PID segment shape. HL7 v2 segments are pipe-
# delimited: `PID|1||MRN12345^^^FACILITY||DOE^JOHN^A||19700101|M`.
# The `^^^` triplet (component separators) is the structural fingerprint
# that distinguishes a real PID segment from generic text.
# Bounded run `[^;\n]{0,120}` keeps the regex RE2-safe.
_HL7_PID_LOGGED = _re(
    r"\b(?:"
    r"console\s*\.\s*(?:log|info|debug|warn|error)"
    r"|logger\s*\.\s*(?:info|debug|warn|error|trace)"
    r"|print"
    r"|fmt\s*\.\s*Print[A-Za-z]{0,12}"
    r"|log\s*\.\s*Print[A-Za-z]{0,12}"
    r"|System\s*\.\s*out\s*\.\s*println"
    r"|slog\s*\.\s*(?:Info|Debug|Warn|Error)"
    r")\b"
    r"[^;\n]{0,120}"
    r"\bPID\|[0-9]{1,4}\|"
    r"[^;\n]{0,120}"
    r"\^\^\^"
)

# Redaction / sanitisation guard. If any marker is present within the
# same window we treat the log as safe.
_HL7_REDACT_GUARD = _re(
    r"\b(?:redact|sanitiz[ae]|hash(?:ed)?|mask(?:ed)?|deident|de-?identif)"
)


# ---- H2 : hipaa-phi-fhir-route-no-auth-middleware -----------------------


# Anchor: an Express / Koa / Fastify route registration whose path
# starts with `/fhir` or contains a FHIR-resource path. The handler
# arrow function is inlined directly after the path string (no auth
# middleware between path and handler).
_FHIR_ROUTE_NO_AUTH_INLINE = _re(
    r"\b(?:app|router|server|fastify)"
    r"\s*\.\s*(?:get|post|put|patch|delete)"
    r"\s*\(\s*['\"`]"
    r"(?:/fhir(?:/[A-Za-z][A-Za-z0-9_]{0,40})*"
    r"|/(?:Patient|Observation|Bundle|Encounter|MedicationRequest"
    r"|Condition|AllergyIntolerance|DiagnosticReport|Procedure"
    r"|Immunization|CarePlan|Coverage|Claim))"
    r"(?:/[A-Za-z0-9:_\-{}]{0,60})?"
    r"['\"`]"
    r"\s*,\s*"
    r"(?:async\s+)?"
    r"\(?\s*(?:req|request|ctx|c)\b"
)

# A separate guard pattern: presence of an auth middleware anywhere
# in the same route-definition call signature, OR an explicit auth
# call inside the handler body.
_FHIR_AUTH_MIDDLEWARE = _re(
    r"\b(?:"
    r"requireAuth|verifyJwt|verifyJWT|authenticate|authMiddleware"
    r"|smartOnFhir|smart-on-fhir|requireScope|checkAuth|isAuthenticated"
    r"|passport\s*\.\s*authenticate|ensureAuth|protect"
    r"|jwt\s*\.\s*verify|verify_token|requireOAuth|oauthGuard"
    r")\b"
)

# FHIR metadata endpoint exemption — by spec `GET /fhir/metadata`
# (CapabilityStatement) is anonymous-readable.
_FHIR_METADATA_EXEMPTION = _re(
    r"['\"`]/fhir/metadata['\"`]"
)


# ---- H3 : hipaa-phi-fhir-bundle-unbounded-searchset ---------------------


# Anchor: assignment that sets a Bundle's `.type` to "searchset" or
# "collection". The unbounded entry population is enforced as a
# SECOND pattern in the same window via Stage-B.
_FHIR_BUNDLE_SEARCHSET_TYPE = _re(
    r"\b(?:Bundle|bundle)"
    r"[^=\n]{0,60}"
    r"(?:\.\s*type\s*=\s*['\"`]"
    r"|type\s*:\s*['\"`]"
    r"|type\s*=\s*['\"`])"
    r"(?:searchset|collection)"
    r"['\"`]"
)

# Unbounded query shape near the bundle: `.all()`, `findAll()`,
# `.find({})`, `Patient.objects.all()`, `SELECT * FROM`.
_FHIR_BUNDLE_UNBOUNDED_QUERY = _re(
    r"\b(?:"
    r"\.\s*all\s*\(\s*\)"
    r"|findAll\s*\(\s*\)"
    r"|find\s*\(\s*\{\s*\}\s*\)"
    r"|\.\s*objects\s*\.\s*all\s*\(\s*\)"
    r"|SELECT\s+\*\s+FROM"
    r"|\.\s*find\s*\(\s*\)"
    r")"
)

# Single-patient scope filter — if present, suppress (longitudinal
# export for one patient is an intended Bundle shape).
_FHIR_BUNDLE_PATIENT_FILTER = _re(
    r"\b(?:"
    r"patient[_-]?id\s*[=:]"
    r"|filter\s*\(\s*[^)]{0,80}patient"
    r"|where\s*\(\s*[^)]{0,80}patient"
    r"|\$everything"
    r"|Patient\s*\.\s*get\s*\(\s*['\"`][^'\"`]{1,80}['\"`]\s*\)"
    r")"
)


# ---- H4 : hipaa-phi-dicom-patient-id-in-path ----------------------------


# Anchor: a path-like string that includes a Patient-ID-prefixed
# segment (`MRN1234/`, `PatientID_AB123/`, `pt_id-CD45-...`). The
# segment must be inside a quoted string or path separator context.
# Bounded character classes keep RE2 happy.
_DICOM_PATIENT_ID_IN_PATH = _re(
    r"(?:['\"`/])"
    r"(?:MRN|PID|Patient(?:ID|Name)|pt[_-]?id)"
    r"[_-]?"
    r"[0-9A-Z]{4,16}"
    r"(?:[/\\]|['\"`])"
)

# Alternative anchor: raw DICOM tag literal in string context.
# `(0010,0020)` or `(0010, 0010)` — Patient ID / Patient Name tags.
_DICOM_RAW_TAG_LITERAL = _re(
    r"\(\s*0010\s*,\s*00[12]0\s*\)"
)


# ---- H5 : hipaa-phi-baa-marker-missing-on-cloud-sdk-call ----------------


# Anchor: a cloud SDK call adjacent (within bounded window) to a
# healthcare-context keyword. The negative-presence half of the rule
# (BAA marker absence) is enforced as a file-level Stage-B check.
# The bridge is `[\s\S]{0,400}` (any 400 chars, RE2-safe — bounded
# upper limit, no nested quantifiers) so the keyword can appear in
# a multi-line argument list a few lines below the SDK call.
_PHI_CLOUD_SDK_WITH_HEALTHCARE = _re(
    r"\b(?:"
    r"boto3\s*\.\s*client"
    r"|s3\s*\.\s*put_object"
    r"|s3Client\s*\.\s*putObject"
    r"|openai\s*\.\s*(?:ChatCompletion|Completion|Embedding|chat)"
    r"|anthropic\s*\.\s*messages"
    r"|anthropic\s*\.\s*Anthropic"
    r"|sentry_sdk\s*\.\s*capture"
    r"|datadog\s*\.\s*api"
    r"|honeycomb\s*\.\s*send"
    r"|google\s*\.\s*cloud\s*\.\s*storage"
    r"|azure\s*\.\s*storage\s*\.\s*blob"
    r")"
    r"[\s\S]{0,400}?"
    r"\b(?:Patient|patient|fhir|FHIR|hl7|HL7|dicom|DICOM|PHI|MRN|EHR|ehr)\b"
)

# BAA / HIPAA-eligibility marker pattern (positive presence check).
_PHI_BAA_MARKER = _re(
    r"\b(?:"
    r"business[_-]?associate[_-]?agreement"
    r"|baa[_-]?(?:signed|on|enabled|covered)"
    r"|hipaa[_-]?(?:eligible|compliant|enabled|covered)"
    r"|phi[_-]?(?:enabled|allowed|covered)"
    r"|SYNTHEA|FAKE_PATIENTS_ONLY|SYNTHETIC_PHI"
    r")\b"
)


# ---- H6 : hipaa-phi-icd-code-with-identifier-in-log ---------------------


# Anchor: a logging primitive sink call. Within the same line, both
# an ICD-10 code shape AND an identifier-noun must co-occur.
_PHI_LOG_SINK_WITH_ICD = _re(
    r"\b(?:"
    r"console\s*\.\s*(?:log|info|debug|warn|error)"
    r"|logger\s*\.\s*(?:info|debug|warn|error|trace)"
    r"|print"
    r"|fmt\s*\.\s*Print[A-Za-z]{0,12}"
    r"|log\s*\.\s*Print[A-Za-z]{0,12}"
    r"|System\s*\.\s*out\s*\.\s*println"
    r")\b"
    r"[^;\n]{0,300}"
    r"\b[A-Z][0-9]{2}(?:\.[0-9]{1,4})?\b"
)

# Identifier-noun (name, email, phone, DOB, MRN, patient_id, user_id).
_PHI_LOG_IDENTIFIER_NOUN = _re(
    r"\b(?:"
    r"name|email|phone|dob|date[_-]?of[_-]?birth"
    r"|mrn|MRN|patient[_-]?id|user[_-]?id|ssn"
    r")\b"
)

# 3D / shader / educational-content carve-out — Greek phi (φ) variable,
# WebGL / Three.js / GLSL contexts.
_PHI_SHADER_CARVEOUT = _re(
    r"\b(?:"
    r"THREE\s*\.|gl_Position|gl_FragColor|gl_PointSize"
    r"|attribute\s+vec|uniform\s+(?:mat|vec)|varying\s+vec"
    r"|Math\s*\.\s*acos|Math\s*\.\s*sin|Math\s*\.\s*cos"
    r"|phi\s*=\s*Math\."
    r")"
)


# ---- H7 : hipaa-phi-openehr-aql-no-ehr-id-filter ------------------------


# Anchor: an AQL query opener — `SELECT ... FROM EHR e CONTAINS ...`
# with the `FROM EHR <alias>` shape. Bounded run keeps RE2-safe.
_AQL_QUERY_TRIGGER = _re(
    r"\bSELECT\b"
    r"[^;'\"`]{0,400}"
    r"\bFROM\s+EHR\s+[a-z]\b"
)

# Same-string ehr_id filter — positive presence suppresses the flag.
_AQL_EHR_ID_FILTER = _re(
    r"\behr_id\s*/\s*value\s*=\s*"
)

# Aggregation / count-only carve-out — population-health analytics.
_AQL_AGGREGATION_CARVEOUT = _re(
    r"\b(?:COUNT|AVG|SUM|MIN|MAX|GROUP\s+BY)\s*\("
)


# ---- H8 : hipaa-phi-hl7-mllp-plaintext-public-bind ----------------------


# Anchor: a TCP-listen / server-bind to `0.0.0.0` / `::` / `'*'` or
# host-less form. The HL7 / MLLP and TLS-absence checks are enforced
# at file level as Stage-B guards.
_TCP_PUBLIC_BIND = _re(
    r"\b(?:"
    r"net\s*\.\s*createServer"
    r"|socket\s*\.\s*socket"
    r"|asyncio\s*\.\s*start_server"
    r"|TcpListener\s*::\s*bind"
    r"|server\s*\.\s*listen"
    r")\s*\("
    r"[^)]{0,400}"
    r"(?:['\"]0\.0\.0\.0['\"]|['\"]::['\"]|['\"]\*['\"]|0\.0\.0\.0)"
)

# Same-file presence of HL7 / MLLP markers. Relax word boundaries:
# real-world code commonly names identifiers `MLLP_START`, `parseHL7`,
# `HL7_PORT` — the substring is the marker.
_HL7_MLLP_MARKER = _re(
    r"(?:"
    r"MLLP|\\x0[bB]|\\x1[cC]|HL7|MSH\||hl7[_-]?mllp"
    r"|simple-?hl7|hl7-?parser|nodehl7"
    r")"
)

# Same-file TLS / SSL wrapping marker — positive presence suppresses.
_TLS_WRAP_MARKER = _re(
    r"\b(?:"
    r"tls\s*\.\s*create(?:Server|Socket)"
    r"|wrap_socket"
    r"|TlsAcceptor"
    r"|SSLContext"
    r"|ssl_context"
    r"|ssl\s*\.\s*wrap_socket"
    r"|tls\s*\.\s*connect"
    r")"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="hipaa-phi-hl7-pid-segment-logged",
        name="HL7 v2 PID segment with PHI flows into a plaintext log sink",
        severity="CRITICAL",
        description=(
            "An HL7 v2 PID (Patient Identification) segment — the "
            "pipe-delimited structure containing PID-3 Patient ID "
            "list, PID-5 Patient Name, and PID-7 Date of Birth — "
            "appears in the argument list of `console.log`, "
            "`logger.info`, `print`, `fmt.Println`, `log.Printf`, "
            "`System.out.println` or a structured logger without an "
            "intervening redaction / sanitisation / hashing call. "
            "PID-3 + PID-5 + PID-7 together meet the HHS Safe Harbor "
            "definition of PHI (45 CFR § 164.514); logs ingested into "
            "Splunk / ELK / Datadog routinely lack BAA coverage, so "
            "first unauthorized access triggers HIPAA breach "
            "notification under § 164.404. The `^^^` triplet is the "
            "PID segment's distinguishing fingerprint."
        ),
        pattern=_HL7_PID_LOGGED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="hipaa-phi-fhir-route-no-auth-middleware",
        name="FHIR REST endpoint declared with no auth middleware in route signature",
        severity="CRITICAL",
        description=(
            "An Express / Koa / Fastify route serving `/fhir/`, "
            "`/Patient`, `/Observation`, `/Bundle`, `/Encounter`, "
            "`/MedicationRequest`, `/Condition`, "
            "`/AllergyIntolerance`, `/DiagnosticReport` etc., is "
            "declared with the handler arrow-function inlined "
            "directly after the path string — no `requireAuth`, "
            "`verifyJwt`, `smartOnFhir`, `authenticate`, or "
            "`passport.authenticate` middleware between path and "
            "handler. SMART-on-FHIR (OAuth 2.0) is the de-facto "
            "auth standard; an unauthenticated FHIR endpoint is a "
            "mass-PHI disclosure surface (cf. the 2019 AMCA / "
            "LabCorp 20M-record breach). The `/fhir/metadata` "
            "CapabilityStatement is exempt by spec."
        ),
        pattern=_FHIR_ROUTE_NO_AUTH_INLINE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="hipaa-phi-fhir-bundle-unbounded-searchset",
        name="FHIR Bundle type=searchset populated by unbounded query",
        severity="HIGH",
        description=(
            "Code constructs a FHIR `Bundle` resource with "
            "`type: \"searchset\"` or `type: \"collection\"` and "
            "populates `.entry` from an unbounded query — `.all()`, "
            "`findAll()`, `Patient.objects.all()`, `find({})`, or "
            "`SELECT * FROM`. The endpoint may BE authenticated, "
            "but the authenticated principal still receives every "
            "patient in the EHR (broken function-level "
            "authorisation, API4:2023 Unrestricted Resource "
            "Consumption). Bundles with a `patient_id=` / `$everything` "
            "filter (single-patient longitudinal export) are the "
            "intended shape and are exempt."
        ),
        pattern=_FHIR_BUNDLE_SEARCHSET_TYPE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="hipaa-phi-dicom-patient-id-in-path",
        name="DICOM file path embeds Patient ID / Patient Name as a path segment",
        severity="HIGH",
        description=(
            "A file path (in code, log message, S3 key, or audit "
            "trail) embeds the DICOM Patient ID (tag 0010,0020) or "
            "Patient Name (tag 0010,0010) as a path component — "
            "e.g. `/var/dicom/store/MRN12345/StudyUID/file.dcm` or "
            "`f\"{ds.PatientID}/{ds.StudyInstanceUID}.dcm\"`. The "
            "path itself becomes PHI; it flows into CloudWatch "
            "logs, S3 bucket inventories, Sentry / Rollbar error "
            "trackers, and backup tapes — every one a separate "
            "BAA-coverage requirement. The raw DICOM tag literal "
            "`(0010,0020)` in a string context is the secondary "
            "fingerprint."
        ),
        pattern=_DICOM_PATIENT_ID_IN_PATH,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="hipaa-phi-baa-marker-missing-on-cloud-sdk-call",
        name="Cloud SDK call adjacent to PHI variable lacks BAA / HIPAA-eligibility marker",
        severity="HIGH",
        description=(
            "A cloud SDK call (`boto3.client`, `s3.put_object`, "
            "`openai.ChatCompletion`, `anthropic.messages`, "
            "`sentry_sdk.capture`, `datadog.api`, Google Cloud "
            "Storage, Azure Blob) appears in a code window that "
            "also references PHI variables (Patient, fhir, hl7, "
            "dicom, MRN, EHR) WITHOUT a "
            "`business_associate_agreement` / `baa_signed` / "
            "`hipaa_eligible` / `hipaa_compliant` marker, and "
            "WITHOUT a `SYNTHEA` / `FAKE_PATIENTS_ONLY` synthetic-"
            "data marker. HHS treats sending PHI to a non-BAA "
            "vendor as a reportable breach under § 164.402 even "
            "if no exfiltration occurred — the legal exposure is "
            "automatic."
        ),
        pattern=_PHI_CLOUD_SDK_WITH_HEALTHCARE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="hipaa-phi-icd-code-with-identifier-in-log",
        name="ICD-10 diagnosis code logged alongside a personal identifier noun",
        severity="CRITICAL",
        description=(
            "A log statement contains BOTH an ICD-10 diagnosis "
            "code shape (1 letter + 2 digits + optional `.<1-4 "
            "digits>`) AND an identifier noun (`name`, `email`, "
            "`phone`, `dob`, `mrn`, `patient_id`, `user_id`, "
            "`ssn`) in the same line — for example "
            "`logger.info(f\"Patient {p.name} (MRN {p.mrn}) "
            "diagnosed with ICD-10 {dx.code}\")`. Neither alone is "
            "PHI; the combination is the canonical HHS § "
            "164.514(b)(2)(i) definition (identifier + health "
            "condition). Shader / WebGL / 3D code using Greek "
            "`phi` (φ) as an angle variable is carved out."
        ),
        pattern=_PHI_LOG_SINK_WITH_ICD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="hipaa-phi-openehr-aql-no-ehr-id-filter",
        name="openEHR AQL query crosses every EHR — missing ehr_id/value filter",
        severity="HIGH",
        description=(
            "An openEHR Archetype Query Language (AQL) string "
            "shaped `SELECT ... FROM EHR e CONTAINS ...` lacks an "
            "`ehr_id/value = ...` predicate, meaning the query "
            "crosses every EHR in the openEHR repository (the "
            "openEHR equivalent of `SELECT * FROM patients`). "
            "Most-common openEHR misconfiguration per OpenEHR "
            "community advisories — same risk profile as an "
            "unbounded FHIR Bundle. Population-health aggregations "
            "(`COUNT(`, `AVG(`, `SUM(`, `GROUP BY`) operating on "
            "de-identified projections are carved out."
        ),
        pattern=_AQL_QUERY_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="hipaa-phi-hl7-mllp-plaintext-public-bind",
        name="HL7 v2 MLLP TCP server binds to 0.0.0.0 with no TLS wrap",
        severity="CRITICAL",
        description=(
            "A minimal lower-layer protocol (MLLP) listener — the "
            "HL7 v2 TCP transport with `\\x0B…\\x1C\\x0D` framing "
            "— binds to `0.0.0.0`, `::`, or `'*'` (all interfaces) "
            "without a TLS wrap (`tls.createServer`, "
            "`wrap_socket`, `TlsAcceptor`, `SSLContext`). HL7 "
            "deprecated plaintext MLLP in 2018 in favour of "
            "MLLP-S. Any party with L2 access (cloud VPC peering, "
            "on-prem VLAN tap, AWS Direct Connect, misconfigured "
            "security group) sees every ADT / ORU stream in "
            "cleartext — the historical pattern behind the "
            "Anthem-era hospital interface breaches."
        ),
        pattern=_TCP_PUBLIC_BIND,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * H1 (hl7-pid-segment-logged) — anchor on log sink + PID
        segment; suppress if a redact / sanitise / hash / mask /
        deident marker appears in a ±2-line window.
      * H2 (fhir-route-no-auth-middleware) — anchor on FHIR route
        with inline handler; suppress if an auth-middleware marker
        OR the `/fhir/metadata` exemption appears in the same
        route signature window.
      * H3 (fhir-bundle-unbounded-searchset) — anchor on Bundle
        type assignment; require an unbounded-query marker in a
        ±5-line window AND require ABSENCE of a single-patient
        filter in the same window.
      * H5 (baa-marker-missing-on-cloud-sdk-call) — anchor on the
        cloud SDK + healthcare-keyword combination; suppress if
        any BAA / HIPAA-eligibility / synthetic-data marker
        appears anywhere in the file.
      * H6 (icd-code-with-identifier-in-log) — anchor on log sink
        + ICD-10 code shape; require an identifier noun on the
        same line AND require ABSENCE of a shader / 3D context
        marker in the file.
      * H7 (openehr-aql-no-ehr-id-filter) — anchor on the AQL
        `SELECT ... FROM EHR e` opener; suppress if an
        `ehr_id/value =` filter OR an aggregation (`COUNT(`,
        `GROUP BY`) appears in the same statement window.
      * H8 (hl7-mllp-plaintext-public-bind) — anchor on a public
        TCP bind; require an HL7 / MLLP marker anywhere in the
        file AND require ABSENCE of a TLS wrap marker anywhere
        in the file.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- H1 : hipaa-phi-hl7-pid-segment-logged ----
    rule_h1 = rule_by_id["hipaa-phi-hl7-pid-segment-logged"]
    for m in _HL7_PID_LOGGED.finditer(text):
        line, _ = _line_col(text, m.start())
        # ±2-line window — a redaction call usually precedes or
        # immediately follows the log statement.
        window = _slice_window(text, line, 2, 2)
        if _HL7_REDACT_GUARD.search(window) is not None:
            continue
        _emit(rule_h1, m.start(), m.group(0))

    # ---- H2 : hipaa-phi-fhir-route-no-auth-middleware ----
    rule_h2 = rule_by_id["hipaa-phi-fhir-route-no-auth-middleware"]
    for m in _FHIR_ROUTE_NO_AUTH_INLINE.finditer(text):
        matched = m.group(0)
        # CapabilityStatement metadata is anonymous by spec — exempt.
        if _FHIR_METADATA_EXEMPTION.search(matched) is not None:
            continue
        line, _ = _line_col(text, m.start())
        # Auth middleware may appear on the same line (chained) or
        # in the immediately preceding line — check a ±1-line window.
        window = _slice_window(text, line, 1, 1)
        if _FHIR_AUTH_MIDDLEWARE.search(window) is not None:
            continue
        _emit(rule_h2, m.start(), matched)

    # ---- H3 : hipaa-phi-fhir-bundle-unbounded-searchset ----
    rule_h3 = rule_by_id["hipaa-phi-fhir-bundle-unbounded-searchset"]
    for m in _FHIR_BUNDLE_SEARCHSET_TYPE.finditer(text):
        line, _ = _line_col(text, m.start())
        # ±5-line window — the entry assignment and query call
        # typically appear within a few lines of the type assignment.
        window = _slice_window(text, line, 5, 5)
        if _FHIR_BUNDLE_UNBOUNDED_QUERY.search(window) is None:
            continue
        if _FHIR_BUNDLE_PATIENT_FILTER.search(window) is not None:
            continue
        _emit(rule_h3, m.start(), m.group(0))

    # ---- H4 : hipaa-phi-dicom-patient-id-in-path ----
    rule_h4 = rule_by_id["hipaa-phi-dicom-patient-id-in-path"]
    for m in _DICOM_PATIENT_ID_IN_PATH.finditer(text):
        _emit(rule_h4, m.start(), m.group(0))
    # Raw DICOM tag literal — secondary signal.
    for m in _DICOM_RAW_TAG_LITERAL.finditer(text):
        _emit(rule_h4, m.start(), m.group(0))

    # ---- H5 : hipaa-phi-baa-marker-missing-on-cloud-sdk-call ----
    rule_h5 = rule_by_id["hipaa-phi-baa-marker-missing-on-cloud-sdk-call"]
    has_baa_marker = _file_contains(text, _PHI_BAA_MARKER)
    if not has_baa_marker:
        for m in _PHI_CLOUD_SDK_WITH_HEALTHCARE.finditer(text):
            _emit(rule_h5, m.start(), m.group(0))

    # ---- H6 : hipaa-phi-icd-code-with-identifier-in-log ----
    rule_h6 = rule_by_id["hipaa-phi-icd-code-with-identifier-in-log"]
    is_shader_file = _file_contains(text, _PHI_SHADER_CARVEOUT)
    if not is_shader_file:
        for m in _PHI_LOG_SINK_WITH_ICD.finditer(text):
            # Identifier noun must appear on the SAME line for the
            # PHI-combination semantics to hold.
            line_no, _ = _line_col(text, m.start())
            window = _slice_window(text, line_no, 0, 0)
            if _PHI_LOG_IDENTIFIER_NOUN.search(window) is None:
                continue
            _emit(rule_h6, m.start(), m.group(0))

    # ---- H7 : hipaa-phi-openehr-aql-no-ehr-id-filter ----
    rule_h7 = rule_by_id["hipaa-phi-openehr-aql-no-ehr-id-filter"]
    for m in _AQL_QUERY_TRIGGER.finditer(text):
        matched = m.group(0)
        # Same-statement window — AQL strings are typically multi-
        # line literals; widen window to capture WHERE clause.
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 2, 10)
        if _AQL_EHR_ID_FILTER.search(window) is not None:
            continue
        if _AQL_AGGREGATION_CARVEOUT.search(window) is not None:
            continue
        _emit(rule_h7, m.start(), matched)

    # ---- H8 : hipaa-phi-hl7-mllp-plaintext-public-bind ----
    rule_h8 = rule_by_id["hipaa-phi-hl7-mllp-plaintext-public-bind"]
    has_hl7_marker = _file_contains(text, _HL7_MLLP_MARKER)
    has_tls_marker = _file_contains(text, _TLS_WRAP_MARKER)
    if has_hl7_marker and not has_tls_marker:
        for m in _TCP_PUBLIC_BIND.finditer(text):
            _emit(rule_h8, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
