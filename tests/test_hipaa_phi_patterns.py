"""Tests for scripts/lib/hipaa_phi_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 HIPAA / PHI
healthcare-specific catalogue (8 anti-patterns). Each rule has at
least one positive test exercising the canary AND at least one
negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import hipaa_phi_patterns as hpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(hpp.RULES, tuple)
    rule_ids = {r.id for r in hpp.RULES}
    expected = {
        "hipaa-phi-hl7-pid-segment-logged",
        "hipaa-phi-fhir-route-no-auth-middleware",
        "hipaa-phi-fhir-bundle-unbounded-searchset",
        "hipaa-phi-dicom-patient-id-in-path",
        "hipaa-phi-baa-marker-missing-on-cloud-sdk-call",
        "hipaa-phi-icd-code-with-identifier-in-log",
        "hipaa-phi-openehr-aql-no-ehr-id-filter",
        "hipaa-phi-hl7-mllp-plaintext-public-bind",
    }
    assert expected == rule_ids
    assert len(hpp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in hpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = hpp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert hpp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[hpp.Finding]:
    return [f for f in hpp.scan_text(text) if f.rule_id == rule_id]


# ---------- H1 : hipaa-phi-hl7-pid-segment-logged ------------------------


def test_h1_console_log_pid_segment_flags() -> None:
    """console.log of an HL7 v2 PID segment → CRITICAL hit."""
    src = (
        "const hl7 = require('simple-hl7');\n"
        "server.use((req, res, next) => {\n"
        "  console.log('Received ADT: PID|1||MRN12345^^^HOSP||DOE^JOHN^A||19700101|M');\n"
        "  next();\n"
        "});\n"
    )
    hits = _hits("hipaa-phi-hl7-pid-segment-logged", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h1_redaction_marker_suppresses() -> None:
    """A `redact` call near the PID log line → no hit."""
    src = (
        "const sanitized = redactPid(msg);\n"
        "console.log('Received ADT (redacted):', sanitized);\n"
        "// upstream PID|1||REDACTED^^^HOSP|| not logged anymore\n"
    )
    assert not _hits("hipaa-phi-hl7-pid-segment-logged", src)


# ---------- H2 : hipaa-phi-fhir-route-no-auth-middleware -----------------


def test_h2_express_patient_route_no_auth_flags() -> None:
    """Express /fhir/Patient route with inline handler → CRITICAL hit."""
    src = (
        "const express = require('express');\n"
        "const app = express();\n"
        "app.get('/fhir/Patient/:id', async (req, res) => {\n"
        "  const patient = await db.fhir.findOne({ id: req.params.id });\n"
        "  res.json(patient);\n"
        "});\n"
    )
    hits = _hits("hipaa-phi-fhir-route-no-auth-middleware", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h2_capability_statement_metadata_exempt() -> None:
    """`/fhir/metadata` CapabilityStatement is anonymous-by-spec → no hit."""
    src = (
        "app.get('/fhir/metadata', async (req, res) => {\n"
        "  res.json(CAPABILITY_STATEMENT);\n"
        "});\n"
    )
    assert not _hits("hipaa-phi-fhir-route-no-auth-middleware", src)


# ---------- H3 : hipaa-phi-fhir-bundle-unbounded-searchset ---------------


def test_h3_bundle_searchset_with_all_query_flags() -> None:
    """Bundle.type=searchset populated by Patient.objects.all() → HIGH hit."""
    src = (
        "from fhir.resources.bundle import Bundle, BundleEntry\n"
        "bundle = Bundle.construct()\n"
        "bundle.type = 'searchset'\n"
        "bundle.entry = [BundleEntry(resource=p) for p in Patient.objects.all()]\n"
        "return JsonResponse(bundle.dict())\n"
    )
    hits = _hits("hipaa-phi-fhir-bundle-unbounded-searchset", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_h3_bundle_with_patient_id_filter_suppresses() -> None:
    """Bundle scoped to a single patient_id filter → no hit."""
    src = (
        "bundle = Bundle.construct()\n"
        "bundle.type = 'searchset'\n"
        "rows = Patient.objects.filter(patient_id=requested_id).all()\n"
        "bundle.entry = [BundleEntry(resource=p) for p in rows]\n"
    )
    assert not _hits("hipaa-phi-fhir-bundle-unbounded-searchset", src)


# ---------- H4 : hipaa-phi-dicom-patient-id-in-path ----------------------


def test_h4_mrn_in_filepath_flags() -> None:
    """A filesystem path that embeds an MRN segment → HIGH hit."""
    src = (
        "import pydicom\n"
        "ds = pydicom.dcmread(input_path)\n"
        "out = f'/var/dicom/store/MRN12345/{ds.StudyInstanceUID}.dcm'\n"
        "logger.info(f'Stored study at {out}')\n"
    )
    hits = _hits("hipaa-phi-dicom-patient-id-in-path", src)
    assert hits


def test_h4_constant_assignment_low_signal() -> None:
    """DICOM tag constant in code only (no path) → no hit."""
    src = (
        "# Library constant only — no path concatenation\n"
        "DICOM_TAG_PATIENT_ID = 0x00100020\n"
        "DICOM_TAG_PATIENT_NAME = 0x00100010\n"
    )
    assert not _hits("hipaa-phi-dicom-patient-id-in-path", src)


# ---------- H5 : hipaa-phi-baa-marker-missing-on-cloud-sdk-call ----------


def test_h5_openai_call_with_fhir_no_baa_flags() -> None:
    """openai.ChatCompletion with FHIR encounter variable, no BAA → HIGH hit."""
    src = (
        "import openai\n"
        "def summarize_encounter(encounter_fhir: dict) -> str:\n"
        "    return openai.ChatCompletion.create(\n"
        "        model='gpt-4o',\n"
        "        messages=[{'role': 'user',\n"
        "                   'content': f'Summarize this Patient encounter: {encounter_fhir}'}],\n"
        "    ).choices[0].message.content\n"
    )
    hits = _hits("hipaa-phi-baa-marker-missing-on-cloud-sdk-call", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_h5_baa_marker_in_file_suppresses() -> None:
    """File contains an explicit BAA / HIPAA-eligibility marker → no hit."""
    src = (
        "# hipaa_eligible = true (Bedrock / Anthropic Enterprise tier)\n"
        "import openai\n"
        "def summarize_encounter(encounter_fhir: dict) -> str:\n"
        "    return openai.ChatCompletion.create(model='gpt-4o',\n"
        "        messages=[{'role': 'user', 'content': f'Patient: {encounter_fhir}'}]\n"
        "    ).choices[0].message.content\n"
    )
    assert not _hits("hipaa-phi-baa-marker-missing-on-cloud-sdk-call", src)


# ---------- H6 : hipaa-phi-icd-code-with-identifier-in-log ---------------


def test_h6_log_with_icd10_and_mrn_flags() -> None:
    """logger.info with ICD-10 code AND MRN identifier → CRITICAL hit."""
    src = (
        "logger.info(f'Patient {p.name} (MRN {p.mrn}) diagnosed with ICD-10 E11.9')\n"
    )
    hits = _hits("hipaa-phi-icd-code-with-identifier-in-log", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h6_threejs_phi_angle_does_not_flag() -> None:
    """Three.js shader code with Greek phi angle variable → no hit."""
    src = (
        "// 3D widget — `phi` is the Greek polar-angle variable here\n"
        "import * as THREE from 'three';\n"
        "const phi = Math.acos(1 - Math.random() * 2);\n"
        "logger.info(`render phi=${phi}, user_id=${userId}, code A12.3`);\n"
    )
    assert not _hits("hipaa-phi-icd-code-with-identifier-in-log", src)


# ---------- H7 : hipaa-phi-openehr-aql-no-ehr-id-filter ------------------


def test_h7_aql_without_ehr_id_filter_flags() -> None:
    """AQL `SELECT ... FROM EHR e` with no ehr_id/value filter → HIGH hit."""
    src = (
        "aql = '''\n"
        "    SELECT c/uid/value, c/context/start_time\n"
        "    FROM EHR e CONTAINS COMPOSITION c\n"
        "    WHERE c/archetype_node_id = 'openEHR-EHR-COMPOSITION.encounter.v1'\n"
        "'''\n"
        "results = client.aql.execute(aql)\n"
    )
    hits = _hits("hipaa-phi-openehr-aql-no-ehr-id-filter", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_h7_aql_with_ehr_id_filter_suppresses() -> None:
    """AQL with `e[ehr_id/value = ...]` predicate → no hit."""
    src = (
        "aql = '''\n"
        "    SELECT c/uid/value\n"
        "    FROM EHR e CONTAINS COMPOSITION c\n"
        "    WHERE e/ehr_id/value = $ehr_id\n"
        "'''\n"
    )
    assert not _hits("hipaa-phi-openehr-aql-no-ehr-id-filter", src)


# ---------- H8 : hipaa-phi-hl7-mllp-plaintext-public-bind ----------------


def test_h8_mllp_listener_public_bind_no_tls_flags() -> None:
    """net.createServer bound 0.0.0.0 with MLLP marker, no TLS → CRITICAL hit."""
    src = (
        "const net = require('net');\n"
        "const MLLP_START = '\\x0B', MLLP_END = '\\x1C\\x0D';\n"
        "const server = net.createServer((sock) => {\n"
        "  sock.on('data', (buf) => {\n"
        "    const msg = buf.toString().replace(MLLP_START, '').replace(MLLP_END, '');\n"
        "    parseHL7(msg);\n"
        "  });\n"
        "});\n"
        "server.listen(2575, '0.0.0.0');\n"
    )
    hits = _hits("hipaa-phi-hl7-mllp-plaintext-public-bind", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h8_mllps_with_tls_wrap_suppresses() -> None:
    """Same MLLP listener wrapped in tls.createServer → no hit."""
    src = (
        "const tls = require('tls');\n"
        "const MLLP_START = '\\x0B';\n"
        "const server = tls.createServer(tlsOpts, (sock) => {\n"
        "  parseHL7(sock);\n"
        "});\n"
        "server.listen(2576, '0.0.0.0');\n"
    )
    assert not _hits("hipaa-phi-hl7-mllp-plaintext-public-bind", src)


# ---------- Cross-rule determinism ---------------------------------------


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — H4 anchor: MRN in path
        "logger.info(f'Stored at /var/dicom/MRN12345/study.dcm')\n"
        # Line 2 — H6 anchor: ICD-10 + identifier in log
        "logger.info(f'Patient {p.name} (MRN {p.mrn}) ICD-10 E11.9')\n"
    )
    findings = hpp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )
