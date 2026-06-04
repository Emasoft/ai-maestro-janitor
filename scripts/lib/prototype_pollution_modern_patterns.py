"""Prototype Pollution in Modern JavaScript / TypeScript — Security Patterns.

Wave-32 distillation round 18, angle: prototype pollution gaps not yet
covered by the existing pattern library.

What is NOT here (already shipped — DO NOT duplicate):

  * ``Object.assign(target, JSON.parse(input))`` and
    ``Object.assign(target, req.body/params/query)`` —
    ``frontend_patterns.py::prototype-pollution-object-assign-json-parse``
  * ``structuredClone()`` piped into ``Object.assign`` —
    ``js_deserialization_patterns.py::jsdes-structured-clone-untrusted-into-object-assign``
  * ``JSON.parse(localStorage…)`` spread into React state —
    ``js_deserialization_patterns.py::jsdes-storage-parse-into-state-spread``
  * ``Object.defineProperty`` with externally-sourced key —
    ``frontend_patterns.py::js-object-defineproperty-untrusted-key``

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * pp-lodash-merge-req           — lodash _.merge/_.defaultsDeep with req.*  (HIGH)
  * pp-qs-allow-prototypes        — qs.parse allowPrototypes:true              (HIGH)
  * pp-orm-constructor-req-body   — ORM constructor/create from req.body       (HIGH)
  * pp-hasownproperty-on-untrusted — .hasOwnProperty on req.* / JSON.parse     (MEDIUM)
  * pp-object-assign-this-options — Object.assign(this, options/opts/config)   (MEDIUM)
  * pp-third-party-deep-merge     — merge-deep/deep-extend/deepmerge import    (HIGH)
  * pp-set-prototype-of-external  — Object.setPrototypeOf with external arg    (HIGH)
  * pp-loop-bracket-assign        — Object.entries(req.*).forEach              (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors chat_bot_patterns.Finding.

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- PP-01 : pp-lodash-merge-req ----------------------------------------
# lodash _.merge / _.defaultsDeep / _.mergeWith called with req.* argument.
# CVE-2019-10744 (lodash < 4.17.12).

_LODASH_MERGE_REQ = _re(
    r"\b_\.\s*(?:merge|defaultsDeep|mergeWith)\s*\("
    r"[^)]{0,120}"
    r"\breq\.\s*(?:body|query|params|headers)\b"
    r"|"
    r"\blodash\.\s*(?:merge|defaultsDeep|mergeWith)\s*\("
    r"[^)]{0,120}"
    r"\breq\.\s*(?:body|query|params|headers)\b"
)

# ---- PP-02 : pp-qs-allow-prototypes -------------------------------------
# qs.parse or bodyParser.urlencoded called with allowPrototypes:true.
# GHSA-jf85-cpcp-j695, GHSA-cjmd-3w8h-gmvh.

_QS_ALLOW_PROTOTYPES = _re(
    r"\bqs\.parse\s*\([^)]{0,200}allowPrototypes\s*:\s*true"
    r"|"
    r"bodyParser\.urlencoded\s*\([^)]{0,200}allowPrototypes\s*:\s*true"
)

# ---- PP-03 : pp-orm-constructor-req-body --------------------------------
# ORM constructor / create / save / insert called with raw req.body.
# CVE-2022-25912 (mongoose < 6.4.6 mass-assignment).

_ORM_CONSTRUCTOR_REQ_BODY = _re(
    r"\bnew\s+[A-Z][A-Za-z0-9_]+\s*\(\s*req\.\s*(?:body|query|params)\s*[,)]"
    r"|"
    r"\b(?:[A-Z][A-Za-z0-9_]+)\.create\s*\(\s*req\.\s*(?:body|query|params)\s*[,)]"
    r"|"
    r"\bprisma\.[a-z][A-Za-z0-9_]*\.create\s*\(\s*\{\s*data\s*:\s*req\.\s*(?:body|query|params)\s*\}"
    r"|"
    r"\brepository\.(?:create|save|insert)\s*\(\s*req\.\s*(?:body|query|params)\s*[,)]"
)

# ---- PP-04 : pp-hasownproperty-on-untrusted -----------------------------
# .hasOwnProperty() called directly on req.* or JSON.parse(...) result.
# GHSA-896r-m6j4-xj95 (express-fileupload); safe alternative is Object.hasOwn.

_HASOWNPROPERTY_ON_UNTRUSTED = _re(
    r"\breq\.\s*(?:body|query|params)\s*(?:\.[A-Za-z_$][\w$]*)?\s*\.hasOwnProperty\s*\("
    r"|"
    r"\bJSON\.parse\s*\([^)]{0,120}\)\s*\.hasOwnProperty\s*\("
)

# ---- PP-05 : pp-object-assign-this-options ------------------------------
# Object.assign(this, options/opts/config/settings/params/props/req.*).
# HackerOne report #1104890, lodash CVE writeups.

_OBJECT_ASSIGN_THIS_OPTIONS = _re(
    r"\bObject\.assign\s*\(\s*this\s*,"
    r"\s*(?:options|opts|config|settings|params|props|req\.\s*(?:body|query|params))\s*[,)]"
)

# ---- PP-06 : pp-third-party-deep-merge ----------------------------------
# import/require of merge-deep / deep-extend / deepmerge / defaults-deep / hoek.
# GHSA-jf85-cpcp-j695; GHSA-896r-m6j4-xj95; HackerOne #1104890; CVE-2020-28282;
# CVE-2018-3728 (hoek); CVE-2021-23337 (lodash 4.17.21).

_THIRD_PARTY_DEEP_MERGE = _re(
    r"\brequire\s*\(\s*['\"](?:merge-deep|deep-extend|deepmerge|defaults-deep|hoek)['\"]"
    r"|"
    r"\bimport\s+(?:[A-Za-z_$][\w$]*\s+from\s+)?['\"](?:merge-deep|deep-extend|deepmerge|defaults-deep|hoek)['\"]"
)

# ---- PP-07 : pp-set-prototype-of-external -------------------------------
# Object.setPrototypeOf with an externally-sourced second argument.
# No single CVE — "explicit prototype swap" attack class.

_SET_PROTOTYPE_OF_EXTERNAL = _re(
    r"\bObject\.setPrototypeOf\s*\(\s*[A-Za-z_$][\w$.]*\s*,"
    r"\s*[A-Za-z_$][\w$.]*\.__proto__"
    r"|"
    r"\bObject\.setPrototypeOf\s*\(\s*[A-Za-z_$][\w$.]*\s*,"
    r"\s*req\.\s*(?:body|query|params)"
    r"|"
    r"\bObject\.setPrototypeOf\s*\(\s*[A-Za-z_$][\w$.]*\s*,\s*JSON\.parse\s*\("
)

# ---- PP-08 : pp-loop-bracket-assign -------------------------------------
# Object.entries/keys(req.*).forEach/reduce/map — bracket-assign loop.
# CVE-2022-22965 analog; OWASP NodeGoat; HackerOne report class.

_LOOP_BRACKET_ASSIGN = _re(
    r"\bObject\.(?:entries|keys)\s*\(\s*req\.\s*(?:body|query|params)\s*\)"
    r"\s*\.(?:forEach|reduce|map)\s*\("
)


# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="pp-lodash-merge-req",
        name="lodash-merge-with-req-body",
        severity="HIGH",
        description=(
            "_.merge / _.defaultsDeep / _.mergeWith called with direct req.body/"
            "query/params argument — prototype pollution vector (CVE-2019-10744)."
        ),
        pattern=_LODASH_MERGE_REQ,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pp-qs-allow-prototypes",
        name="qs-parse-allow-prototypes-true",
        severity="HIGH",
        description=(
            "qs.parse or bodyParser.urlencoded called with allowPrototypes:true — "
            "re-enables __proto__ key in parsed query strings (GHSA-jf85-cpcp-j695)."
        ),
        pattern=_QS_ALLOW_PROTOTYPES,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pp-orm-constructor-req-body",
        name="orm-constructor-over-assignment-from-req-body",
        severity="HIGH",
        description=(
            "ORM constructor/create/save called with raw req.body — mass-assignment "
            "and prototype pollution vector (CVE-2022-25912 mongoose)."
        ),
        pattern=_ORM_CONSTRUCTOR_REQ_BODY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pp-hasownproperty-on-untrusted",
        name="hasownproperty-called-on-untrusted-object",
        severity="MEDIUM",
        description=(
            ".hasOwnProperty() called directly on req.body/query/params or "
            "JSON.parse result — fails on null-prototype objects; use Object.hasOwn."
        ),
        pattern=_HASOWNPROPERTY_ON_UNTRUSTED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pp-object-assign-this-options",
        name="object-assign-this-caller-supplied-options",
        severity="MEDIUM",
        description=(
            "Object.assign(this, options/opts/config/settings) in a constructor — "
            "merges caller-supplied props directly onto this without key filtering."
        ),
        pattern=_OBJECT_ASSIGN_THIS_OPTIONS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pp-third-party-deep-merge",
        name="vulnerable-third-party-deep-merge-import",
        severity="HIGH",
        description=(
            "Import/require of merge-deep, deep-extend, deepmerge, defaults-deep, or "
            "hoek — packages with known prototype pollution vectors (CVE-2018-3728, "
            "CVE-2020-28282, HackerOne #1104890)."
        ),
        pattern=_THIRD_PARTY_DEEP_MERGE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pp-set-prototype-of-external",
        name="object-setprototypeof-with-external-arg",
        severity="HIGH",
        description=(
            "Object.setPrototypeOf called with externally-sourced second argument "
            "(.__proto__, req.*, or JSON.parse result) — explicit prototype swap attack."
        ),
        pattern=_SET_PROTOTYPE_OF_EXTERNAL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pp-loop-bracket-assign",
        name="loop-bracket-assign-from-req-body",
        severity="HIGH",
        description=(
            "Object.entries/keys(req.*).forEach/reduce/map — dynamic bracket "
            "assignment loop without __proto__/constructor key filtering."
        ),
        pattern=_LOOP_BRACKET_ASSIGN,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    return findings
