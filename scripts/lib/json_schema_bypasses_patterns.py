"""JSON Schema validation bypass patterns.

Wave-33 distillation round 19, angle — JSON Schema / validator-library
bypasses in AI-agent infrastructure code.

Catalogue of 9 JSON-schema-bypass anti-patterns distilled in
`reports/distill-round-19/json-schema-bypasses.md`. Targets schema
declarations in MCP tool handlers, Claude Code hooks, Pydantic models,
Ajv/Node validators, Zod/Yup/Joi schema builders, and standalone
`jsonschema` usage that look like validation but leave the door wide open.

What is NOT here (already shipped — DO NOT duplicate):

  * Python pickle/Java ObjectInputStream/PHP unserialize deserialization —
    `cross_lang_deserialize_patterns.py`.
  * XSS via `JSON.parse(location.search)` injected into DOM —
    `frontend_patterns.py`.
  * browser extension `chrome.runtime.sendMessage` without origin check —
    `browser_extension_patterns.py`.
  * JS runtime message-event trust bugs —
    handled by round-11 JSDES-001.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * jsb-001  MCP inputSchema object missing additionalProperties:false   (HIGH)
  * jsb-002  Empty properties:{} + required:[] universal-bypass schema   (HIGH)
  * jsb-003  Hook stdin json.load without schema validation               (HIGH)
  * jsb-004  format email/uri in schema without checker registration     (MEDIUM)
  * jsb-005  Pydantic extra=ignore silently drops attacker keys          (MEDIUM)
  * jsb-006  Schema object missing top-level type field                  (MEDIUM)
  * jsb-007  ReDoS-vulnerable pattern: regex in JSON Schema              (MEDIUM)
  * jsb-008  Ajv useDefaults:true mutates input object in place          (MEDIUM)
  * jsb-009  Zod passthrough / Yup unknown(true) exposes extra fields    (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-T03 — Prompt Injection / Tool Misuse
  ASI-T04 — Hook Bypass
  ASI-T06 — Unvalidated Input to Tool
  OWASP A03:2021 — Injection
  OWASP A04:2021 — Insecure Design
  OWASP A05:2021 — Security Misconfiguration
  OWASP A06:2021 — Vulnerable and Outdated Components
  CWE-1321     — Prototype Pollution via Merge
  CWE-1333     — Inefficient Regular Expression Complexity (ReDoS)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- JSB-001 : MCP inputSchema missing additionalProperties:false --------

# Anchor on "type":"object" + "properties": present but no
# "additionalProperties" within 600 chars.  RE2-safe: the (?:...) group
# uses a negated-character-class gate, not a lookahead.  The window is
# intentionally SHORT (no nested repetition) — just enough to span a
# typical compact inline schema dict.
_INPUT_SCHEMA_OBJECT_ANCHOR = _re(
    r"""(?:"input[Ss]chema"\s*[=:]\s*\{|inputSchema\s*=\s*\{)[^}]{0,800}"type"\s*:\s*"object"""
)

# Presence detector for additionalProperties inside the same schema block.
_ADDITIONAL_PROPS_KEY = _re(r"additionalProperties")

# ---- JSB-002 : Empty properties:{} + required:[] schema -----------------

# Order A: properties:{} before required:[]
_EMPTY_PROPS_THEN_REQUIRED = _re(
    r'"properties"\s*:\s*\{\s*\}\s*,\s*"required"\s*:\s*\[\s*\]'
)
# Order B: required:[] before properties:{}
_EMPTY_REQUIRED_THEN_PROPS = _re(
    r'"required"\s*:\s*\[\s*\]\s*,\s*"properties"\s*:\s*\{\s*\}'
)

# ---- JSB-003 : Hook stdin json.load without schema validation ------------

# Anchor: json.load(sys.stdin)
_JSON_LOAD_STDIN = _re(r"json\.load\s*\(\s*sys\.stdin\s*\)")

# Presence detectors for a nearby schema validator call (any of these in
# a 10-line window suppresses the finding).
_SCHEMA_VALIDATOR_CALL = _re(
    r"(?:jsonschema|validate\s*\(|TypeAdapter|model_validate|Draft[0-9]+Validator)"
)

# ---- JSB-004 : format keyword without checker ---------------------------

_FORMAT_KEYWORD_UNSAFE = _re(
    r'"format"\s*:\s*"(?:email|uri|date-time|hostname|ipv4|ipv6)"'
)

# Presence of a format checker in the SAME FILE suppresses the finding.
_FORMAT_CHECKER_PRESENT = _re(
    r'(?:format[_\s]checker|format\s*:\s*"full"|ajv-formats|EmailStr|@hapi/joi)'
)

# ---- JSB-005 : Pydantic extra="ignore" ----------------------------------

# Pydantic v2 dict-style: {"extra": "ignore"}
_PYDANTIC_EXTRA_IGNORE_V2 = _re(r'"extra"\s*:\s*"ignore"')

# Pydantic v1 class Config style: extra = "ignore" / 'ignore' / Extra.ignore
_PYDANTIC_EXTRA_IGNORE_V1 = _re(
    r"extra\s*=\s*(?:Extra\.ignore|\"ignore\"|'ignore')"
)

# ---- JSB-006 : Schema object missing top-level "type" -------------------

# Anchor: "properties": key exists in an inputSchema / input_schema block.
_SCHEMA_PROPS_ANCHOR = _re(
    r'(?:input[Ss]chema|input_schema)\s*[=:]\s*\{[^}]{0,600}"properties"\s*:'
)

# Presence of "type": at the top of the same schema block.
_SCHEMA_TYPE_PRESENT = _re(r'"type"\s*:\s*"object"')

# ---- JSB-007 : ReDoS-vulnerable pattern: regex in schema ----------------

# Flag "pattern": "..." values that contain nested quantifier shapes.
# Shapes detected (all RE2-safe to FIND, not to execute):
#   A) (...+...)+  or (...+...)*  — nested plus inside group
#   B) (...*...)+  — nested star inside group
#   C) adjacent quantifiers: [+*] followed immediately by another [+*]
# We wrap inside a "pattern": "..." literal extraction.
_REDOS_IN_SCHEMA_PATTERN = _re(
    r'"pattern"\s*:\s*"[^"]*(?:'
    r'\([^)]*\+[^)]*\)\+'
    r'|\([^)]*\+[^)]*\)\*'
    r'|\([^)]*\*[^)]*\)\+'
    r'|[+*]\s*\+'
    r')[^"]*"'
)

# Also catch Python re.compile() calls with adjacent quantifiers — common
# when the schema pattern is built programmatically.
_REDOS_IN_RE_COMPILE = _re(
    r're\.compile\s*\(\s*r?"[^"]*(?:[+*]\s*){2,}[^"]*"'
)

# ---- JSB-008 : Ajv useDefaults:true -------------------------------------

_AJV_USE_DEFAULTS = _re(
    r"new\s+Ajv\s*\(\s*\{[^}]*useDefaults\s*:\s*true[^}]*\}"
)

# ---- JSB-009 : Zod passthrough / Yup unknown(true) / Joi / Marshmallow --

_ZOD_PASSTHROUGH = _re(r"\.passthrough\s*\(\s*\)")
_YUP_UNKNOWN_TRUE = _re(r"\.unknown\s*\(\s*true\s*\)")
_JOI_ALLOW_UNKNOWN = _re(r"\.options\s*\(\s*\{[^}]*allowUnknown\s*:\s*true")
_MARSHMALLOW_INCLUDE = _re(r"unknown\s*=\s*INCLUDE")


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="jsb-001",
        name="MCP inputSchema object missing additionalProperties:false",
        severity="HIGH",
        description=(
            "An MCP tool schema declares \"type\":\"object\" with a "
            "\"properties\" map but omits \"additionalProperties\":false. "
            "JSON Schema draft-07 defaults additionalProperties to true, "
            "so any extra key an LLM or attacker injects passes validation "
            "silently. In an agentic setting a prompt injection that adds "
            "extra keys (\"__proto__\", \"debug\", \"override\") has a "
            "clear path into downstream business logic via input.get() or "
            "**input unpacking."
        ),
        pattern=_INPUT_SCHEMA_OBJECT_ANCHOR,
        owasp_asi="ASI-T03, ASI-T06",
    ),
    Rule(
        id="jsb-002",
        name="Empty properties:{} + required:[] universal-bypass schema",
        severity="HIGH",
        description=(
            "A schema of {\"type\":\"object\",\"properties\":{},\"required\":[]} "
            "passes every input without error: no field is required, no field "
            "is type-checked, and without additionalProperties:false any input "
            "is valid. This is the logical equivalent of no validation at all "
            "while giving the false impression that validation is present."
        ),
        pattern=_EMPTY_PROPS_THEN_REQUIRED,
        owasp_asi="ASI-T06, ASI-T03",
    ),
    Rule(
        id="jsb-003",
        name="Hook stdin json.load with no schema validation in window",
        severity="HIGH",
        description=(
            "A Claude Code hook reads the stdin payload with bare "
            "json.load(sys.stdin) and accesses fields directly without any "
            "schema-validation call in the surrounding lines. An attacker who "
            "controls the hook invocation context can craft a payload with "
            "unexpected keys or wrong types to bypass the hook's safety checks "
            "or cause an unhandled AttributeError that silently exits the hook."
        ),
        pattern=_JSON_LOAD_STDIN,
        owasp_asi="ASI-T06, ASI-T04",
    ),
    Rule(
        id="jsb-004",
        name="JSON Schema format:email/uri used without format-checker registration",
        severity="MEDIUM",
        description=(
            "The \"format\" keyword is annotation-only by default in both "
            "Ajv (Node) and the Python jsonschema library — format checks do "
            "not reject invalid values unless a checker is explicitly "
            "registered. Code relying on \"format\":\"email\" to validate an "
            "email address without registering a checker gets no validation "
            "at all; the field can contain arbitrary injection payloads."
        ),
        pattern=_FORMAT_KEYWORD_UNSAFE,
        owasp_asi="ASI-T06, OWASP A03:2021",
    ),
    Rule(
        id="jsb-005",
        name="Pydantic extra=ignore silently discards attacker-controlled keys",
        severity="MEDIUM",
        description=(
            "Pydantic model_config {\"extra\":\"ignore\"} (v2) or class Config "
            "extra=\"ignore\" (v1) silently drops undeclared fields rather than "
            "rejecting them. Developers believe the model \"validates\" input "
            "when it only validates declared fields. A future refactor adding "
            "a new field immediately exposes previously-silenced attacker "
            "values. The secure default is extra=\"forbid\"."
        ),
        pattern=_PYDANTIC_EXTRA_IGNORE_V2,
        owasp_asi="ASI-T06, OWASP A05:2021",
    ),
    Rule(
        id="jsb-006",
        name="Schema properties block without peer top-level type:object field",
        severity="MEDIUM",
        description=(
            "A JSON Schema object that declares \"properties\" but omits a "
            "top-level \"type\":\"object\" constraint accepts any JSON value "
            "— string, number, array, null — without error. Code that later "
            "accesses input[\"field\"] or calls input.get() on a non-dict "
            "input will raise TypeError/AttributeError, which in many hook "
            "patterns silently exits and bypasses all safety checks."
        ),
        pattern=_SCHEMA_PROPS_ANCHOR,
        owasp_asi="ASI-T06",
    ),
    Rule(
        id="jsb-007",
        name="ReDoS-vulnerable nested-quantifier pattern in JSON Schema pattern keyword",
        severity="MEDIUM",
        description=(
            "The JSON Schema \"pattern\" keyword accepts a regex. Patterns "
            "with nested quantifiers (e.g. ([A-Za-z0-9.-]+)+ applied to a "
            "domain) cause catastrophic backtracking in Python re and JS "
            "RegExp when a crafted input contains many repeated valid chars "
            "followed by an invalid one, enabling CPU-exhaustion DoS in any "
            "validator called on untrusted input."
        ),
        pattern=_REDOS_IN_SCHEMA_PATTERN,
        owasp_asi="OWASP A06:2021, CWE-1333",
    ),
    Rule(
        id="jsb-008",
        name="Ajv({useDefaults:true}) mutates input object with schema defaults",
        severity="MEDIUM",
        description=(
            "Ajv's useDefaults:true writes schema default values directly into "
            "the input object, mutating it in place. If the input object is "
            "shared across callers (cached request body, merged config, spread "
            "before validation), the mutation propagates silently. An attacker "
            "who deliberately omits a field forces a known-safe default, "
            "bypassing assumptions that the field must be explicitly set."
        ),
        pattern=_AJV_USE_DEFAULTS,
        owasp_asi="ASI-T06, OWASP A04:2021",
    ),
    Rule(
        id="jsb-009",
        name="Zod passthrough / Yup unknown(true) retains extra attacker fields",
        severity="HIGH",
        description=(
            "Zod .passthrough(), Yup .unknown(true), Joi .options({allowUnknown:true}), "
            "and Marshmallow unknown=INCLUDE all retain undeclared fields in the "
            "parsed output and pass them to downstream consumers unchanged. If the "
            "output is spread (Object.assign, **kwargs) into application state, "
            "attacker-controlled keys reach internal config including __proto__ "
            "pollution paths."
        ),
        pattern=_ZOD_PASSTHROUGH,
        owasp_asi="ASI-T06, CWE-1321",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * JSB-001 (inputSchema-no-additionalProperties) — anchor on the
        inputSchema block; suppress if additionalProperties is present
        anywhere in the same 800-char window.
      * JSB-002 (empty-properties-required) — two-direction match; also
        check the reverse field order.
      * JSB-003 (hook-stdin-no-validation) — anchor on json.load(sys.stdin);
        require NO schema-validator call in a 10-line forward window.
      * JSB-004 (format-no-checker) — anchor on "format":"email/uri";
        suppress if any format-checker marker exists anywhere in the file.
      * JSB-005 (pydantic-extra-ignore) — also match Pydantic v1 style.
      * JSB-006 (schema-no-type) — anchor on inputSchema properties block;
        suppress if "type":"object" is present in the same block window.
      * JSB-007 (redos-schema-pattern) — pattern keyword nested quantifiers;
        also match re.compile() adjacent-quantifier shape.
      * JSB-008 (ajv-usedefaults) — literal Ajv constructor match.
      * JSB-009 (zod-passthrough) — also match Yup, Joi, Marshmallow shapes.

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

    # ---- JSB-001 : inputSchema missing additionalProperties:false ----
    rule_001 = rule_by_id["jsb-001"]
    for m in _INPUT_SCHEMA_OBJECT_ANCHOR.finditer(text):
        # Grab 200 more chars beyond the match to cover the rest of the schema block
        window_end = min(len(text), m.end() + 200)
        block = text[m.start():window_end]
        if not _ADDITIONAL_PROPS_KEY.search(block):
            _emit(rule_001, m.start(), m.group(0))

    # ---- JSB-002 : empty properties:{} + required:[] ----
    rule_002 = rule_by_id["jsb-002"]
    for m in _EMPTY_PROPS_THEN_REQUIRED.finditer(text):
        _emit(rule_002, m.start(), m.group(0))
    # also check reversed order
    for m in _EMPTY_REQUIRED_THEN_PROPS.finditer(text):
        _emit(rule_002, m.start(), m.group(0))

    # ---- JSB-003 : json.load(sys.stdin) without schema validation ----
    rule_003 = rule_by_id["jsb-003"]
    for m in _JSON_LOAD_STDIN.finditer(text):
        line, _ = _line_col(text, m.start())
        # Check 10 lines forward for any schema-validator call.
        window = _slice_forward(text, line, 10)
        if _SCHEMA_VALIDATOR_CALL.search(window) is None:
            _emit(rule_003, m.start(), m.group(0))

    # ---- JSB-004 : format keyword without checker ----
    rule_004 = rule_by_id["jsb-004"]
    # Suppress if any format-checker marker exists anywhere in the file.
    has_format_checker = _file_contains(text, _FORMAT_CHECKER_PRESENT)
    if not has_format_checker:
        for m in _FORMAT_KEYWORD_UNSAFE.finditer(text):
            _emit(rule_004, m.start(), m.group(0))

    # ---- JSB-005 : Pydantic extra="ignore" ----
    rule_005 = rule_by_id["jsb-005"]
    for m in _PYDANTIC_EXTRA_IGNORE_V2.finditer(text):
        _emit(rule_005, m.start(), m.group(0))
    # Also match Pydantic v1 style
    for m in _PYDANTIC_EXTRA_IGNORE_V1.finditer(text):
        _emit(rule_005, m.start(), m.group(0))

    # ---- JSB-006 : schema properties without top-level type:object ----
    rule_006 = rule_by_id["jsb-006"]
    for m in _SCHEMA_PROPS_ANCHOR.finditer(text):
        block = m.group(0)
        if not _SCHEMA_TYPE_PRESENT.search(block):
            _emit(rule_006, m.start(), m.group(0))

    # ---- JSB-007 : ReDoS-vulnerable pattern in JSON Schema ----
    rule_007 = rule_by_id["jsb-007"]
    for m in _REDOS_IN_SCHEMA_PATTERN.finditer(text):
        _emit(rule_007, m.start(), m.group(0))
    # Also flag Python re.compile() with adjacent quantifiers
    for m in _REDOS_IN_RE_COMPILE.finditer(text):
        _emit(rule_007, m.start(), m.group(0))

    # ---- JSB-008 : Ajv useDefaults:true ----
    rule_008 = rule_by_id["jsb-008"]
    for m in _AJV_USE_DEFAULTS.finditer(text):
        _emit(rule_008, m.start(), m.group(0))

    # ---- JSB-009 : Zod passthrough / Yup unknown(true) / Joi / Marshmallow ----
    rule_009 = rule_by_id["jsb-009"]
    for m in _ZOD_PASSTHROUGH.finditer(text):
        _emit(rule_009, m.start(), m.group(0))
    for m in _YUP_UNKNOWN_TRUE.finditer(text):
        _emit(rule_009, m.start(), m.group(0))
    for m in _JOI_ALLOW_UNKNOWN.finditer(text):
        _emit(rule_009, m.start(), m.group(0))
    for m in _MARSHMALLOW_INCLUDE.finditer(text):
        _emit(rule_009, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
