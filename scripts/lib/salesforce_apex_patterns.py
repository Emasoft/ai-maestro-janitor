"""Salesforce / SOQL / Apex security patterns.

Wave-34 distillation round 20, Salesforce security angle.

Catalogue of 9 Salesforce-specific anti-patterns covering SOQL injection,
sharing-model bypasses, credential leaks, and OAuth scope over-privilege.
Targets Apex (.cls, .trigger), Visualforce (.page), sfdx JSON auth files,
and Connected App metadata XML.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * sf-soql-inject-concat          — Database.query() + string concat (HIGH)
  * sf-soql-inject-bare-var        — Database.query() bare variable (MEDIUM)
  * sf-without-sharing-class       — without sharing class declaration (HIGH)
  * sf-aura-enabled-method         — @AuraEnabled on static method (MEDIUM)
  * sf-callout-non-named-cred      — setEndpoint() non-Named-Credential (HIGH)
  * sf-soql-like-wildcard-inject   — SOQL LIKE '%' + var + '%' (HIGH)
  * sf-sfdx-access-token           — sfdx accessToken in JSON (CRITICAL)
  * sf-visualforce-no-https        — <apex:page> without requireSecureRendering (MEDIUM)
  * sf-connected-app-full-scope    — ConnectedApp Full OAuth scope (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)

OWASP ASI mapping used:
  ASI-01 — Injection (SOQL injection via dynamic query / LIKE wildcard)
  ASI-02 — Sensitive Data Exposure (Salesforce OAuth token in VCS)
  ASI-05 — Broken Access Control (without sharing, AuraEnabled, OAuth scope)
  ASI-06 — Security Misconfiguration (Visualforce non-HTTPS rendering)
  ASI-10 — SSRF (Apex callout to user-controlled endpoint)

All regexes are RE2-compatible (no backreferences, no variable-length
lookbehind, no catastrophic backtracking shapes). Patterns are pre-compiled
at module load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A compiled detection rule."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # type: ignore[type-arg]
    owasp_asi: str


# ---- Pre-compiled patterns -----------------------------------------------

# sf-soql-inject-concat: Database.query() with + concatenation inside args
_PAT_SOQL_INJECT_CONCAT = re.compile(
    r"Database\.query\s*\(\s*[^)]{0,400}\+[^)]{0,200}\)"
)

# sf-soql-inject-bare-var: Database.query(someVariable) — no visible escaping
_PAT_SOQL_INJECT_BARE_VAR = re.compile(
    r"Database\.query\s*\(\s*[a-zA-Z_][a-zA-Z0-9_]{0,60}\s*\)"
)

# sf-without-sharing-class: without sharing class declaration
_PAT_WITHOUT_SHARING = re.compile(
    r"without\s+sharing\s+class\s+[A-Za-z][A-Za-z0-9_]{0,80}"
)

# sf-aura-enabled-method: @AuraEnabled on a public/global static method
_PAT_AURA_ENABLED = re.compile(
    r"@AuraEnabled\s*(?:\(\s*cacheable\s*=\s*(?:true|false)\s*\))?\s*(?:public|global)\s+static"
)

# sf-callout-non-named-cred: setEndpoint() called with a variable (not 'callout:' string)
_PAT_CALLOUT_NON_NAMED_CRED = re.compile(
    r"setEndpoint\s*\(\s*[a-zA-Z_][a-zA-Z0-9_]{0,80}\s*\)"
)

# sf-soql-like-wildcard-inject: LIKE '%' + var + '%' pattern
_PAT_SOQL_LIKE_WILDCARD = re.compile(
    r"LIKE\s+['\"][%]['\"]\s*\+\s*[a-zA-Z_][a-zA-Z0-9_.]{0,80}\s*\+\s*['\"][%]['\"]"
)

# sf-sfdx-access-token: sfdx accessToken value in JSON (starts with 00...)
_PAT_SFDX_ACCESS_TOKEN = re.compile(
    r'"accessToken"\s*:\s*"00[A-Za-z0-9!_]{20,250}"'
)

# sf-visualforce-no-https: <apex:page ...> opening tag (two-step: check absence of requireSecureRendering)
_PAT_VISUALFORCE_PAGE = re.compile(
    r"<apex:page\s[^>]{0,500}>"
)

# sf-connected-app-full-scope: <scopes>Full</scopes> in Connected App XML
_PAT_CONNECTED_APP_FULL_SCOPE = re.compile(
    r"<scopes>\s*(?:Full|full)\s*</scopes>"
)


# ---- Rules tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="sf-soql-inject-concat",
        name="SOQL Injection via Database.query() String Concatenation",
        severity="HIGH",
        description=(
            "Database.query() called with a string that contains + concatenation. "
            "If user-controlled data is concatenated without String.escapeSingleQuotes(), "
            "attackers can inject arbitrary SOQL clauses."
        ),
        pattern=_PAT_SOQL_INJECT_CONCAT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sf-soql-inject-bare-var",
        name="Database.query() with Bare Variable Argument",
        severity="MEDIUM",
        description=(
            "Database.query() called with a single variable argument. "
            "If the variable was assembled from user input without escapeSingleQuotes(), "
            "the query is injectable."
        ),
        pattern=_PAT_SOQL_INJECT_BARE_VAR,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sf-without-sharing-class",
        name="Apex Class Declared without sharing",
        severity="HIGH",
        description=(
            "Classes annotated 'without sharing' run in system context, bypassing "
            "field-level security, CRUD permissions, and sharing rules. If reachable "
            "from external callers (AuraEnabled, REST endpoints), this is a privilege escalation vector."
        ),
        pattern=_PAT_WITHOUT_SHARING,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sf-aura-enabled-method",
        name="@AuraEnabled Static Method (Implicit Sharing Context)",
        severity="MEDIUM",
        description=(
            "@AuraEnabled exposes Apex methods to Lightning Web Components. "
            "If the enclosing class lacks an explicit 'with sharing' or 'without sharing' "
            "annotation, sharing mode is ambiguous and may be inherited permissively."
        ),
        pattern=_PAT_AURA_ENABLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sf-callout-non-named-cred",
        name="Apex Callout to Non-Named-Credential Endpoint",
        severity="HIGH",
        description=(
            "HttpRequest.setEndpoint() called with a variable instead of a 'callout:' "
            "Named Credential reference. If the variable is user-controlled, attackers "
            "can redirect callouts to arbitrary hosts (SSRF)."
        ),
        pattern=_PAT_CALLOUT_NON_NAMED_CRED,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="sf-soql-like-wildcard-inject",
        name="SOQL LIKE Wildcard Injection Pattern",
        severity="HIGH",
        description=(
            "SOQL LIKE '%' + variable + '%' pattern detected. The wildcard context "
            "is a common injection vector: unescaped input can close the string literal "
            "and append additional SOQL clauses, bypassing record-level security."
        ),
        pattern=_PAT_SOQL_LIKE_WILDCARD,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sf-sfdx-access-token",
        name="Salesforce CLI Access Token in Committed File",
        severity="CRITICAL",
        description=(
            "An 'accessToken' JSON field starting with '00' (Salesforce org prefix) "
            "was found. Committing sfdx auth files exposes OAuth tokens that grant "
            "full REST/SOAP/Bulk API access as the authenticated user."
        ),
        pattern=_PAT_SFDX_ACCESS_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sf-visualforce-no-https",
        name="Visualforce apex:page Without requireSecureRendering",
        severity="MEDIUM",
        description=(
            "A <apex:page> opening tag was detected without 'requireSecureRendering'. "
            "In older org configurations this page can be served over HTTP, exposing "
            "session tokens and view state to network interception."
        ),
        pattern=_PAT_VISUALFORCE_PAGE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="sf-connected-app-full-scope",
        name="Connected App with Full OAuth Scope",
        severity="HIGH",
        description=(
            "<scopes>Full</scopes> in Connected App metadata grants complete API access "
            "equivalent to the authenticated user's profile, including destructive operations. "
            "Least-privilege alternatives (api, chatter_api) are almost always sufficient."
        ),
        pattern=_PAT_CONNECTED_APP_FULL_SCOPE,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner -------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* for all rules and return de-duplicated, sorted Findings.

    De-duplication key: (rule_id, line, column). Output is sorted by
    (line, column, rule_id).
    """
    seen: set[tuple[str, int, int]] = set()
    findings: list[Finding] = []

    lines = text.splitlines(keepends=True)
    # Build cumulative byte offsets for line-number lookup
    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)

    def _line_col(match_start: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= match_start:
                lo = mid
            else:
                hi = mid - 1
        line_num = lo + 1  # 1-based
        col_num = match_start - offsets[lo] + 1  # 1-based
        return line_num, col_num

    for rule in RULES:
        if rule.id == "sf-visualforce-no-https":
            # Two-step check: regex match + substring absence
            for m in rule.pattern.finditer(text):
                tag_text = m.group(0)
                if "requireSecureRendering" in tag_text:
                    continue  # attribute present — not vulnerable
                line_num, col_num = _line_col(m.start())
                key = (rule.id, line_num, col_num)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        rule_id=rule.id,
                        line=line_num,
                        column=col_num,
                        matched_text=m.group(0),
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    )
                )
        else:
            for m in rule.pattern.finditer(text):
                line_num, col_num = _line_col(m.start())
                key = (rule.id, line_num, col_num)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        rule_id=rule.id,
                        line=line_num,
                        column=col_num,
                        matched_text=m.group(0),
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    )
                )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
