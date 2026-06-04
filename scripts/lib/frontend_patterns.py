"""TypeScript / web-frontend attack-surface patterns.

Wave 17 (impl-z) — distillation of 10 proposals from the
``distill3-f-ts-frontend`` report into deterministic regex rules.
This module catalogues TS/TSX/JSX/Vue/Svelte client-side attack
shapes that the janitor's existing rulesets do NOT cover:

  * React ``dangerouslySetInnerHTML`` un-sanitized.
  * Vue ``v-html`` un-sanitized.
  * Angular ``DomSanitizer.bypassSecurityTrustHtml`` family.
  * Svelte ``{@html ...}`` un-sanitized.
  * Prototype-pollution carriers
    (``Object.assign(target, JSON.parse(input))``,
     ``Object.defineProperty(obj, untrustedKey, ...)``).
  * ``eval()`` / ``new Function(...)`` / string-``setTimeout`` with
    template-literal interpolation.
  * TypeScript ``as any`` reflective write
    (``(obj as any)[userKey] = value``).
  * ``JSON.parse(input, reviver)`` where the reviver body itself
    contains ``eval`` / ``new Function``.

Architecture mirrors ``scripts/lib/agent_config_patterns.py``:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
                                  — single rule record. Patterns are
                                    pre-compiled at module load.
  * ``RULES``                     — ordered tuple of every catalogued rule.
  * ``scan_text(text)`` -> list[Finding]
                                  — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)``
                                  — single finding record.

Pure-stdlib (re, NamedTuple) so it loads in every PEP 723 script
block without third-party deps. Patterns favour FP-tolerance over
precision — the caller (the doctor's TS/TSX sweep) is responsible
for the additional context gates documented in the source report:

  * ``react-dangerously-set-inner-html-untrusted`` — caller should
    skip the finding when the file imports
    ``DOMPurify`` / ``dompurify`` / ``sanitize-html`` / ``isomorphic-dompurify``.
  * ``nextjs-server-action-no-csrf`` — caller should skip when
    ``next.config.{js,mjs,ts}`` declares
    ``experimental.serverActions.allowedOrigins``.
  * ``json-parse-reviver-with-eval`` — the structural rule matches
    ``JSON.parse(..., function(...){ ... eval(...) ... })`` across a
    400-character window using ``[\\s\\S]`` instead of ``re.DOTALL``
    (preserves MULTILINE ``^``/``$`` for downstream callers).

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW",
matching the existing janitor sentinel/zizmor convention. The
mapping from the source report's severity is verbatim
(CRITICAL / HIGH / MEDIUM / LOW one-to-one).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/agent_config_patterns.Finding`` so the heartbeat
    detectors and SARIF emitter can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-06"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE.

    Most TS/JSX identifiers and JSX-attribute names ARE
    case-sensitive (``dangerouslySetInnerHTML`` vs
    ``dangerouslysetinnerhtml``), but Vue / Svelte / Angular
    template attributes (``v-html``, ``{@html}``, ``[innerHTML]``)
    are conventionally lowercase. IGNORECASE preserves matches in
    both casings without forcing the caller to fold the source. The
    cost is a small FP risk on a project that capitalises a
    JSX attribute non-canonically — those are vanishingly rare.

    MULTILINE makes ``^`` / ``$`` line-anchored, which is what we
    want for the ``"use server"`` directive (``rule #5``).

    UNICODE is the default in Python 3 but stated explicitly so the
    behaviour is identical on every platform the doctor runs on.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule 1: React dangerouslySetInnerHTML — untrusted ------------------


# Match the dangerous shape:
#   dangerouslySetInnerHTML={{ __html: <expression> }}
# where <expression> is a bare identifier or member access
# (e.g. ``post.body`` / ``content``), NOT a string literal and NOT
# a DOMPurify-sanitized call. The Python ``re`` engine has full
# lookahead support; the RE2 fallback path (zizmor RegexSet) will
# need ``PATTERN_FALLBACK_FLAGS[rule_id] = False`` set elsewhere.
_REACT_DANGER_HTML = _re(
    r"dangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html\s*:"
    # Lookahead: zero-or-more WS, then the FIRST non-WS char must NOT be
    # a quote. Using a positive lookahead with explicit ``\s*`` anchors
    # the test to the start of the RHS expression so the surrounding
    # ``\s*`` outside cannot backtrack and bypass the gate. Bare
    # ``(?![\"'`])`` after ``\s*`` is unsafe because the engine
    # backtracks ``\s*`` to zero-length matches and the lookahead then
    # sees the leading whitespace (not the quote), accepting the input
    # incorrectly. This idiom is the standard workaround for engines
    # that lack possessive quantifiers / atomic groups.
    r"(?=\s*[^\s\"'`])"
    # Reject DOMPurify / sanitize-html / xss-filters helpers — these
    # lookaheads are safe to leave as ``(?!...)`` because the body that
    # follows the colon is fully bracketed by the next ``\}`` anyway.
    r"(?![^}]*\bDOMPurify\.sanitize\b)"
    r"(?![^}]*\bsanitizeHtml\b)"
    r"(?![^}]*\bdompurify\.sanitize\b)"
    r"(?![^}]*\bxss\s*\()"
    # Now skip leading WS and accept the rest up to the closing braces.
    r"\s*[^}]+\}\s*\}"
)


# ---- Rule 2: Vue v-html — untrusted -------------------------------------


# Combined Vue XSS pattern: alternation of the two variants. The RE2-safe
# engine compiles this as a single DFA so the union has no per-branch cost.
#
# Variant A — ``v-html="<expr>"`` template directive. ``<expr>`` is a
# Vue expression (identifier / member access / $store.state.x). The
# leading-``<`` lookahead rejects literal-HTML RHS (safe-by-construction
# at template-compile time).
#
# Variant B — Vue 2 render-function shape ``domProps: { innerHTML: <id> }``.
# Same XSS carrier as React's dangerouslySetInnerHTML in render form.
_VUE_COMBINED = _re(
    r"\bv-html\s*=\s*[\"'](?![<])[^\"']+[\"']"
    r"|\bdomProps\s*:\s*\{\s*innerHTML\s*:\s*[A-Za-z_$][\w$.]*\s*[,}]"
)


# ---- Rule 3: Angular bypassSecurityTrust* family ------------------------


# Angular sanitizer escape hatch: every ``DomSanitizer.bypassSecurityTrust*``
# call is by-design suspicious. Capture the kind for the caller to
# derive a kind-specific severity (Script / ResourceUrl → CRITICAL;
# Html / Url → HIGH; Style → MAJOR). The pattern accepts both
# identifier-RHS (untrusted) and string-literal RHS (less suspicious
# but still worth flagging — the rule itself does not differentiate).
_ANGULAR_BYPASS = _re(
    r"\bbypassSecurityTrust(?:Html|Script|Style|Url|ResourceUrl)\s*\("
)


# Angular template binding ``[innerHTML]="someVar"`` — same identifier
# vs string-literal gate as React's ``dangerouslySetInnerHTML``.
# Reject leading ``<`` on the RHS (literal-html shape).
_ANGULAR_INNER_HTML_BINDING = _re(
    r"\[innerHTML\]\s*=\s*[\"'](?![<])[^\"']+[\"']"
)


# ---- Rule 4: Svelte {@html ...} — untrusted -----------------------------


# Svelte's ``{@html expression}`` is the explicit XSS escape hatch.
# Reject a bare string literal or backtick literal (no template
# interpolation) — those are the rare safe form. Accept anything
# else (identifier, member access, function call).
_SVELTE_AT_HTML = _re(
    r"\{@html\s+"
    # Reject leading backtick (literal) UNLESS it contains an
    # interpolation `${...}` — that means it's a template literal
    # with runtime values, which IS dangerous. Anchored to the next
    # non-WS char via a positive lookahead so that the surrounding
    # ``\s+`` cannot backtrack past the gate. See the React rule
    # above for the same defensive idiom.
    r"(?=\s*[^\s])"  # require at least one non-WS char after @html
    # The first non-WS char must NOT be a single/double quote — those
    # are non-template string literals (safe-by-construction).
    r"(?!\s*[\"'])"
    # If the first non-WS char IS a backtick, it must contain a
    # `${...}` interpolation; reject a pure-literal backtick like
    # ``` ``` ` static ` ``` ```.
    r"(?!\s*`[^`${]*`\s*\})"
    # Accept the rest up to the closing brace.
    r"[^}]+\}"
)


# ---- Rule 5: Next.js Server Action without CSRF allowlist ---------------


# The ``"use server"`` directive declares a Next.js Server Action.
# This rule matches files that DECLARE the directive — the doctor's
# cross-file gate then verifies whether the repo's ``next.config.*``
# sets ``experimental.serverActions.allowedOrigins``. The
# cross-file step is the caller's job; this regex only catches the
# directive line in a file.
_NEXTJS_USE_SERVER = _re(
    r"^\s*[\"']use server[\"']\s*;?\s*$"
)


# ---- Rule 6: Prototype pollution — Object.assign + JSON.parse -----------


# Combined prototype-pollution carrier: alternation of three shapes.
# Each branch rejects ``Object.create(null)`` targets because they
# have no prototype to pollute.
#
# Variant A — ``Object.assign(target, JSON.parse(<expr>))``: direct
# merge of attacker-controlled JSON into a stateful target without
# ``__proto__`` / ``constructor`` filtering.
#
# Variant B — Express handler shape ``Object.assign(target, req.body)``
# (also ``req.params`` / ``req.query``): same pollution shape with a
# different source.
#
# Variant C — Generic reflective write ``obj[userKey] = JSON.parse(in)``
# where the bracket key is an identifier (untrusted) rather than a
# string literal.
_PROTO_POLLUTION = _re(
    r"Object\.assign\s*\((?!\s*Object\.create\s*\(\s*null\s*\))\s*[A-Za-z_$][\w$.]*\s*,\s*JSON\.parse\s*\("
    r"|Object\.assign\s*\((?!\s*Object\.create\s*\(\s*null\s*\))\s*[A-Za-z_$][\w$.]*\s*,\s*req\.(?:body|params|query)\b"
    r"|[A-Za-z_$][\w$.]*\s*\[\s*[A-Za-z_$][\w$.]*\s*\]\s*=\s*JSON\.parse\s*\("
)


# ---- Rule 7: eval / Function / setTimeout — template-literal interp -----


# Combined eval-class pattern: alternation of three runtime-string-execution
# sinks, each requiring a ``${…}`` template interpolation (which is what
# carries runtime values into the executed code). Pure-literal arguments
# (``new Function('a','b','return a+b')``) are intentionally NOT matched —
# they're how pino/depd build dispatch tables and are safe-by-construction.
#
# Variant A — ``eval(`...${user}...`)``: backtick template with at least
# one ``${…}`` interpolation. ``${[^}]+}`` requires a non-empty body to
# stay precise.
#
# Variant B — ``new Function(..., `...${user}...`)``: Function constructor
# carrying template interpolation in its body argument.
#
# Variant C — ``setTimeout("...${u}...", 0)`` / ``setInterval`` with a
# string argument containing ``${…}``: JS engines treat the string form
# as ``eval`` at call time, regardless of quoting style (the ``["'`]``
# charset covers all three).
_EVAL_OR_FUNCTION_TEMPLATE = _re(
    r"\beval\s*\(\s*`[^`]*\$\{[^}]+\}"
    r"|new\s+Function\s*\([^)]*`[^`]*\$\{[^}]+\}"
    r"|\bset(?:Timeout|Interval)\s*\(\s*[\"'`][^\"'`]*\$\{"
)


# ---- Rule 8: TypeScript ``as any`` reflective write ---------------------


# ``(obj as any)[userKey] = userValue`` — type-system bypass at the
# most security-relevant boundary. Both the new-style ``as any``
# cast and the legacy ``<any>obj`` cast are covered. The bracket
# key MUST be an identifier (not a string literal) — that's the
# reflective-write shape.
_TS_AS_ANY_REFLECTIVE = _re(
    r"\(\s*[A-Za-z_$][\w$.]*\s+as\s+any\s*\)\s*\[\s*[A-Za-z_$][\w$.]*\s*\]\s*="
    r"|\(\s*<\s*any\s*>\s*[A-Za-z_$][\w$.]*\s*\)\s*\[\s*[A-Za-z_$][\w$.]*\s*\]\s*="
)


# ---- Rule 9: JSON.parse with reviver containing eval --------------------


# ``JSON.parse(input, function (k, v) { … eval(...) … })`` — the
# reviver fires for every key/value pair, so every value becomes
# an arbitrary-code-execution opportunity. The pattern is a
# multi-line structural match across a 400-character window using
# ``[\s\S]`` (which is RE2-compatible and equivalent to the dot
# under re.DOTALL — but we DON'T want DOTALL because that breaks
# MULTILINE for sibling callers). The character class encodes the
# multi-line span without flag changes.
_JSON_PARSE_REVIVER_EVAL = _re(
    r"JSON\.parse\s*\([^)]+,\s*"
    # Reviver function — both ``function(k,v){…}`` and arrow form
    # ``(k,v) => {…}`` are valid.
    r"(?:function\s*\([^)]*\)\s*\{|\([^)]*\)\s*=>\s*\{)"
    # Body window: up to 400 chars (RE2-safe), then eval / Function.
    r"[\s\S]{0,400}?"
    r"\b(?:eval\s*\(|new\s+Function\s*\(|\bFunction\s*\()"
)


# ---- Rule 10: Object.defineProperty with untrusted key ------------------


# ``Object.defineProperty(obj, untrustedKey, descriptor)`` is a
# richer prototype-pollution carrier — descriptors can install
# getters/setters. The dangerous shape is when the second argument
# is an identifier (untrusted) rather than a string literal.
# ``Reflect.defineProperty`` has the same trust profile.
_OBJECT_DEFINE_PROPERTY_UNTRUSTED = _re(
    r"(?:Object|Reflect)\.defineProperty\s*\(\s*"
    # Target identifier.
    r"[A-Za-z_$][\w$.]*\s*,\s*"
    # Key MUST be an identifier (not a string literal).
    r"[A-Za-z_$][\w$.]*\s*,"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="react-dangerously-set-inner-html-untrusted",
        name="React dangerouslySetInnerHTML — untrusted RHS",
        severity="HIGH",
        description=(
            "JSX attribute dangerouslySetInnerHTML={{ __html: <expr> }} "
            "where <expr> is a non-string-literal, non-DOMPurify-sanitized "
            "expression — the canonical React XSS carrier. Suppress at the "
            "caller when the file imports DOMPurify / sanitize-html / "
            "isomorphic-dompurify / xss-filters."
        ),
        pattern=_REACT_DANGER_HTML,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="vue-v-html-untrusted",
        name="Vue v-html / domProps.innerHTML — untrusted RHS",
        severity="HIGH",
        description=(
            "Vue template directive v-html=\"<expr>\" or Vue 2 render-function "
            "domProps: { innerHTML: <ident> }. The Vue docs flag v-html as "
            "the documented XSS hole and recommend never using it on "
            "user-provided content."
        ),
        pattern=_VUE_COMBINED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="angular-bypass-security-trust-html",
        name="Angular DomSanitizer.bypassSecurityTrust* call",
        severity="CRITICAL",
        description=(
            "Code calls DomSanitizer.bypassSecurityTrustHtml / Script / "
            "Style / Url / ResourceUrl — Angular's documented sanitizer "
            "escape hatch. Every call deserves a manual review even when "
            "the input looks hard-coded. Script and ResourceUrl variants "
            "are RCE-class."
        ),
        pattern=_ANGULAR_BYPASS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="angular-inner-html-binding-untrusted",
        name="Angular template [innerHTML]=\"<expr>\" binding",
        severity="HIGH",
        description=(
            "Angular template binds [innerHTML] to a non-string-literal "
            "expression — same XSS carrier shape as React's "
            "dangerouslySetInnerHTML in template form."
        ),
        pattern=_ANGULAR_INNER_HTML_BINDING,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="svelte-at-html-untrusted",
        name="Svelte {@html ...} — untrusted RHS",
        severity="HIGH",
        description=(
            "Svelte's {@html expression} tag bypasses character escaping. "
            "The Svelte docs explicitly warn against using it with "
            "user-provided content. Match flags non-literal expressions."
        ),
        pattern=_SVELTE_AT_HTML,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="nextjs-server-action-no-csrf",
        name="Next.js Server Action without allowedOrigins gate",
        severity="HIGH",
        description=(
            "File declares a Next.js 14+ Server Action via the 'use server' "
            "directive. The caller's cross-file gate then verifies whether "
            "next.config.{js,mjs,ts} declares "
            "experimental.serverActions.allowedOrigins — when the gate is "
            "missing and the action is invoked from a public form, the "
            "framework's CSRF posture is documented as best-effort only."
        ),
        pattern=_NEXTJS_USE_SERVER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="prototype-pollution-object-assign-json-parse",
        name="Prototype-pollution carrier — Object.assign + JSON.parse / req.*",
        severity="CRITICAL",
        description=(
            "Object.assign(target, JSON.parse(<input>)) or "
            "Object.assign(target, req.body/params/query) without "
            "__proto__ / constructor filtering — canonical prototype-"
            "pollution carrier (CVE-2022-22965 class). Also fires on "
            "obj[userKey] = JSON.parse(input) generic reflective write."
        ),
        pattern=_PROTO_POLLUTION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="js-eval-or-function-with-template-literal",
        name="eval / new Function / string-setTimeout with template interpolation",
        severity="CRITICAL",
        description=(
            "eval(`...${expr}...`), new Function(..., `...${expr}...`), or "
            "setTimeout/setInterval with a string argument containing a "
            "${...} template interpolation. Pure literal arguments are "
            "rare and usually fine; template-literal interpolation carries "
            "runtime values straight into the JS code-execution sink."
        ),
        pattern=_EVAL_OR_FUNCTION_TEMPLATE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ts-as-any-reflective-write",
        name="TypeScript `as any` cast followed by reflective write",
        severity="HIGH",
        description=(
            "(obj as any)[userKey] = value or (<any>obj)[userKey] = value "
            "— the TS type system is being bypassed precisely at the "
            "reflective-write boundary that prototype-pollution and "
            "missing-input-validation exploit."
        ),
        pattern=_TS_AS_ANY_REFLECTIVE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="json-parse-reviver-with-eval",
        name="JSON.parse reviver body contains eval / new Function",
        severity="CRITICAL",
        description=(
            "JSON.parse(input, function(k, v) { ... eval(...) / new Function "
            "/ Function(...) ... }) — the reviver function is invoked for "
            "every key/value pair in the parsed payload, turning every JSON "
            "value into an arbitrary-code-execution opportunity."
        ),
        pattern=_JSON_PARSE_REVIVER_EVAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="js-object-defineproperty-untrusted-key",
        name="Object/Reflect.defineProperty with identifier key",
        severity="HIGH",
        description=(
            "Object.defineProperty(target, <ident>, descriptor) or "
            "Reflect.defineProperty(target, <ident>, descriptor) — when "
            "the second argument is an identifier (not a string literal), "
            "the descriptor can install getter/setter on an attacker-"
            "chosen key including __proto__ / prototype."
        ),
        pattern=_OBJECT_DEFINE_PROPERTY_UNTRUSTED,
        owasp_asi="ASI-06",
    ),
)


# ---- Composed scanner ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same line emits one.

    The caller is responsible for the contextual gates documented at
    module top:

      * Skip ``react-dangerously-set-inner-html-untrusted`` when the
        file imports a sanitizer (DOMPurify / sanitize-html /
        isomorphic-dompurify / xss-filters).
      * Skip ``nextjs-server-action-no-csrf`` when the repo's
        ``next.config.*`` declares
        ``experimental.serverActions.allowedOrigins``.

    Returned findings are sorted by (line, column, rule_id) so output
    is reproducible across Python versions.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
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
