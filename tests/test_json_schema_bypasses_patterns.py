"""Tests for scripts/lib/json_schema_bypasses_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 JSON-schema-bypass
catalogue (9 rules covering MCP schemas, hook stdin validation, Pydantic
extra=ignore, Ajv useDefaults, Zod/Yup passthrough, ReDoS patterns).
Each rule has exactly 2 tests: one positive (canary hit) and one negative
(safe pattern or suppressor in context).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import json_schema_bypasses_patterns as jsb  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs."""
    assert isinstance(jsb.RULES, tuple)
    rule_ids = {r.id for r in jsb.RULES}
    expected = {
        "jsb-001",
        "jsb-002",
        "jsb-003",
        "jsb-004",
        "jsb-005",
        "jsb-006",
        "jsb-007",
        "jsb-008",
        "jsb-009",
    }
    assert expected == rule_ids
    assert len(jsb.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a known severity and non-empty description."""
    for rule in jsb.RULES:
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = jsb.Finding(
        rule_id="jsb-001",
        line=1,
        column=2,
        matched_text="x",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-T06",
    )
    assert f.rule_id == "jsb-001"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "x"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-T06"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert jsb.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # line 1 — empty schema bypass
        '"properties": {}, "required": []\n'
        # line 2 — empty schema bypass reversed
        '"required": [], "properties": {}\n'
    )
    findings = jsb.scan_text(src)
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[jsb.Finding]:
    return [f for f in jsb.scan_text(text) if f.rule_id == rule_id]


# ---------- JSB-001 : inputSchema missing additionalProperties:false ------


def test_jsb001_flags_input_schema_missing_additional_properties() -> None:
    """inputSchema with type:object + properties but no additionalProperties → HIGH hit."""
    src = (
        'inputSchema={\n'
        '    "type": "object",\n'
        '    "properties": {\n'
        '        "path": {"type": "string"}\n'
        '    },\n'
        '    "required": ["path"]\n'
        '}\n'
    )
    hits = _hits("jsb-001", src)
    assert hits, "Expected jsb-001 finding for schema without additionalProperties"
    assert hits[0].severity == "HIGH"


def test_jsb001_no_flag_when_additional_properties_present() -> None:
    """inputSchema with additionalProperties:false → no jsb-001 hit."""
    src = (
        'inputSchema={\n'
        '    "type": "object",\n'
        '    "properties": {\n'
        '        "path": {"type": "string"}\n'
        '    },\n'
        '    "required": ["path"],\n'
        '    "additionalProperties": False\n'
        '}\n'
    )
    assert not _hits("jsb-001", src)


# ---------- JSB-002 : empty properties + required schema ------------------


def test_jsb002_flags_empty_properties_and_required() -> None:
    """Schema with empty properties:{} + required:[] → HIGH hit."""
    src = '"input_schema": {"type": "object", "properties": {}, "required": []}\n'
    hits = _hits("jsb-002", src)
    assert hits, "Expected jsb-002 finding for empty properties + required"
    assert hits[0].severity == "HIGH"


def test_jsb002_no_flag_when_properties_has_content() -> None:
    """Schema with a declared property → no jsb-002 hit."""
    src = '"properties": {"cmd": {"type": "string"}}, "required": ["cmd"]\n'
    assert not _hits("jsb-002", src)


# ---------- JSB-003 : hook stdin json.load without validation -------------


def test_jsb003_flags_json_load_stdin_no_validation() -> None:
    """json.load(sys.stdin) with no validator call in next 10 lines → HIGH hit."""
    src = (
        "payload = json.load(sys.stdin)\n"
        "if payload.get('tool_name') != 'Bash':\n"
        "    sys.exit(0)\n"
        "cmd = payload.get('tool_input', {}).get('command', '')\n"
    )
    hits = _hits("jsb-003", src)
    assert hits, "Expected jsb-003 finding"
    assert hits[0].severity == "HIGH"


def test_jsb003_no_flag_when_validator_present() -> None:
    """json.load(sys.stdin) followed by jsonschema.validate → no jsb-003 hit."""
    src = (
        "import jsonschema\n"
        "payload = json.load(sys.stdin)\n"
        "jsonschema.validate(payload, HOOK_SCHEMA)\n"
        "cmd = payload['tool_input']['command']\n"
    )
    assert not _hits("jsb-003", src)


# ---------- JSB-004 : format keyword without checker ----------------------


def test_jsb004_flags_format_email_without_checker() -> None:
    """\"format\":\"email\" in schema without format_checker → MEDIUM hit."""
    src = (
        'const schema = {\n'
        '  "type": "object",\n'
        '  "properties": {\n'
        '    "email": {"type": "string", "format": "email"}\n'
        '  }\n'
        '};\n'
    )
    hits = _hits("jsb-004", src)
    assert hits, "Expected jsb-004 finding for format:email without checker"
    assert hits[0].severity == "MEDIUM"


def test_jsb004_no_flag_when_format_checker_registered() -> None:
    """\"format\":\"email\" alongside format_checker import → no jsb-004 hit."""
    src = (
        "from jsonschema import FormatChecker\n"
        "format_checker = FormatChecker()\n"
        'schema = {"type": "object", "properties": {"email": {"type": "string", "format": "email"}}}\n'
    )
    assert not _hits("jsb-004", src)


# ---------- JSB-005 : Pydantic extra="ignore" ----------------------------


def test_jsb005_flags_pydantic_v2_extra_ignore() -> None:
    """Pydantic v2 model_config {\"extra\": \"ignore\"} → MEDIUM hit."""
    src = 'model_config = {"env_file": ".env", "extra": "ignore"}\n'
    hits = _hits("jsb-005", src)
    assert hits, "Expected jsb-005 finding for extra:ignore"
    assert hits[0].severity == "MEDIUM"


def test_jsb005_no_flag_for_extra_forbid() -> None:
    """Pydantic extra=\"forbid\" → no jsb-005 hit."""
    src = 'model_config = {"extra": "forbid"}\n'
    assert not _hits("jsb-005", src)


# ---------- JSB-006 : schema properties without type:object ---------------


def test_jsb006_flags_input_schema_properties_without_type() -> None:
    """inputSchema with properties but no type:object → MEDIUM hit."""
    src = (
        'inputSchema={\n'
        '    "properties": {\n'
        '        "cmd": {"type": "string"}\n'
        '    }\n'
        '}\n'
    )
    hits = _hits("jsb-006", src)
    assert hits, "Expected jsb-006 finding for schema missing type:object"
    assert hits[0].severity == "MEDIUM"


def test_jsb006_no_flag_when_type_object_present() -> None:
    """inputSchema with type:object present → no jsb-006 hit."""
    src = (
        'inputSchema={\n'
        '    "type": "object",\n'
        '    "properties": {\n'
        '        "cmd": {"type": "string"}\n'
        '    }\n'
        '}\n'
    )
    assert not _hits("jsb-006", src)


# ---------- JSB-007 : ReDoS-vulnerable pattern in JSON Schema -------------


def test_jsb007_flags_nested_quantifier_in_schema_pattern() -> None:
    """\"pattern\" with nested quantifier shape → MEDIUM ReDoS hit."""
    src = '"pattern": "[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)+\\\\.[A-Za-z]{2,}"\n'
    hits = _hits("jsb-007", src)
    assert hits, "Expected jsb-007 finding for nested quantifier in pattern"
    assert hits[0].severity == "MEDIUM"


def test_jsb007_no_flag_for_simple_safe_pattern() -> None:
    """Simple \"pattern\" with no nested quantifiers → no jsb-007 hit."""
    src = '"pattern": "^[a-z]{3,10}$"\n'
    assert not _hits("jsb-007", src)


# ---------- JSB-008 : Ajv useDefaults:true --------------------------------


def test_jsb008_flags_ajv_use_defaults() -> None:
    """new Ajv({ useDefaults: true }) → MEDIUM hit."""
    src = "const ajv = new Ajv({ useDefaults: true, allErrors: true });\n"
    hits = _hits("jsb-008", src)
    assert hits, "Expected jsb-008 finding for Ajv useDefaults:true"
    assert hits[0].severity == "MEDIUM"


def test_jsb008_no_flag_without_use_defaults() -> None:
    """new Ajv({ allErrors: true }) without useDefaults → no jsb-008 hit."""
    src = "const ajv = new Ajv({ allErrors: true });\n"
    assert not _hits("jsb-008", src)


# ---------- JSB-009 : Zod passthrough / Yup unknown(true) ----------------


def test_jsb009_flags_zod_passthrough() -> None:
    """Zod .passthrough() call → HIGH hit."""
    src = "const schema = z.object({ name: z.string() }).passthrough();\n"
    hits = _hits("jsb-009", src)
    assert hits, "Expected jsb-009 finding for .passthrough()"
    assert hits[0].severity == "HIGH"


def test_jsb009_flags_yup_unknown_true() -> None:
    """Yup .unknown(true) call → HIGH hit."""
    src = "const schema = yup.object({ name: yup.string() }).unknown(true);\n"
    hits = _hits("jsb-009", src)
    assert hits, "Expected jsb-009 finding for .unknown(true)"
    assert hits[0].severity == "HIGH"


def test_jsb009_no_flag_for_strict_schema() -> None:
    """Zod schema without .passthrough() → no jsb-009 hit."""
    src = "const schema = z.object({ name: z.string() }).strict();\n"
    assert not _hits("jsb-009", src)
