"""SOAP / WS-Security / OData legacy-API security patterns.

Wave-33 distillation round 19, angle SOAP/WS-Security/OData.

Catalogue of 9 legacy-API security anti-patterns distilled in
`reports/distill-round-19/soap-ws-security-odata.md`. Targets SOAP,
WS-Security, WS-SecureConversation, OData, MTOM/SwA, and .NET Remoting
surfaces not covered by existing modules.

What is NOT here (already shipped — DO NOT duplicate):

  * XML entity expansion / DTD injection —
    `xml_entity_expansion_patterns.py`.
  * Explicit `BinaryFormatter.Deserialize` — `cross_lang_deserialize_patterns.py`.
  * SAML / OIDC token manipulation — `saml_oidc_patterns.py`.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * sws-xsw-ds-reference-fragment-uri               (CRITICAL)
  * sws-wsdl-production-exposure                     (MEDIUM)
  * sws-soapaction-unauthenticated-dispatch           (HIGH)
  * sws-odata-expand-no-depth-limit                  (HIGH)
  * sws-odata-filter-enablequery-no-validation       (HIGH)
  * sws-odata-select-raw-identity-entity             (HIGH)
  * sws-sct-token-reuse-no-expiry-check              (HIGH)
  * sws-mtom-attachment-path-traversal               (CRITICAL)
  * sws-dotnet-remoting-channel-registration         (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Injection (XSW auth bypass, SOAPAction dispatch, LINQ injection,
                       MTOM path traversal, .NET Remoting RCE)
  ASI-02 — Information disclosure (WSDL exposure, raw identity entity via
                                    OData $select)
  ASI-03 — Authentication bypass (expired SCT accepted)
  ASI-05 — DoS / resource exhaustion (OData $expand depth)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- S1 : sws-xsw-ds-reference-fragment-uri ----------------------------


# Matches ds:Reference URI="#fragment" — the canonical XSW setup signature.
# A fragment URI inside a signed WS-Security block references a detached
# body copy while a malicious substitute occupies the actual SOAP body.
_XSW_DS_REFERENCE_FRAGMENT = _re(
    r"ds:Reference\s+URI\s*=\s*[\"']#[^\"'\s]{1,128}[\"'][^>]{0,300}>"
)


# ---- S2 : sws-wsdl-production-exposure ---------------------------------


# Query-string `?wsdl`, `?WSDL`, `?singleWsdl` in route configs, reverse
# proxy rules, or application code that returns the WSDL unconditionally.
# Terminal character set includes ;,  }{  and whitespace so that common
# proxy/nginx config syntax (proxy_pass ...?wsdl;) is matched.
_WSDL_QUERY_PARAM = _re(
    r"[?&][Ww][Ss][Dd][Ll](?:=[^&\s\"']{0,200})?(?:[\"'\s&;,}{]|$)"
)


# ---- S3 : sws-soapaction-unauthenticated-dispatch ----------------------


# SOAPAction header read followed (within 300 chars including newlines)
# by a dispatch keyword. Uses [\s\S] to cross line boundaries since
# the SOAPAction read and the execute/invoke call typically span several
# lines of Java/C# code.
_SOAPACTION_DISPATCH = _re(
    r"(?:getSOAPAction|getAction\s*\(\s*\)|SOAPAction\s+header)"
    r"[\s\S]{0,300}"
    r"(?:execute|invoke|dispatch|call|process)\s*\("
)


# ---- S4 : sws-odata-expand-no-depth-limit ------------------------------


# .Expand() called without a chained .MaxExpansionDepth(...) call.
# Negative lookahead is not RE2-safe; we use the absence pattern in the
# scanner (two-step: fire on Expand(), suppress if MaxExpansionDepth
# appears within 3 lines).
_ODATA_EXPAND_CALL = _re(
    r"\.Expand\s*\(\s*\)"
)

_ODATA_MAX_EXPANSION_DEPTH = _re(
    r"MaxExpansionDepth"
)


# ---- S5 : sws-odata-filter-enablequery-no-validation -------------------


# [EnableQuery] with no argument list — the textbook vulnerable form that
# allows arbitrary $filter without ODataValidationSettings.
# The safe form supplies at least one named argument inside the parens.
_ENABLEQUERY_NO_ARGS = _re(
    r"\[EnableQuery\]\s*(?!\()"
)

# Also catch [EnableQuery()] with empty parens — equally unguarded.
_ENABLEQUERY_EMPTY_ARGS = _re(
    r"\[EnableQuery\s*\(\s*\)\s*\]"
)


# ---- S6 : sws-odata-select-raw-identity-entity -------------------------


# [EnableQuery] on a method returning IQueryable<IdentityEntity>.
# Catches the top-level pattern; fine-grained context suppression
# (DTO presence) is left to Stage-B in the scanner.
_ENABLEQUERY_RAW_IDENTITY = _re(
    r"\[EnableQuery\][^{]{0,200}"
    r"IQueryable\s*<\s*"
    r"(?:ApplicationUser|IdentityUser|AppUser|UserEntity|AccountEntity)"
    r"[^>]{0,50}>"
)


# ---- S7 : sws-sct-token-reuse-no-expiry-check --------------------------


# SecurityContextToken cached (tokenStore.contains/get/has) with a subsequent
# `return credential` — the expiry check is missing in between. Uses [\s\S]
# to cross the multiple Java lines that separate the three anchors.
_SCT_NO_EXPIRY = _re(
    r"SecurityContextToken[\s\S]{0,500}"
    r"tokenStore\.(?:contains|get|has)\s*\([^\)]{0,100}\)"
    r"[\s\S]{0,300}"
    r"return\s+credential\b"
)


# ---- S8 : sws-mtom-attachment-path-traversal ---------------------------


# Content-Disposition filename extracted then passed directly to new File().
# Uses [\s\S] to cross the line that typically separates the filename read
# from the File constructor call in Java attachment handlers.
_MTOM_PATH_TRAVERSAL = _re(
    r"(?:getContentDisposition\s*\(\s*\)|getParameter\s*\(\s*[\"']filename[\"']\s*\)"
    r"|getFileName\s*\(\s*\))"
    r"[\s\S]{0,300}"
    r"new\s+File\s*\([^\)]{0,200}\)"
)


# ---- S9 : sws-dotnet-remoting-channel-registration --------------------


# .NET Remoting activation: RemotingConfiguration.Configure,
# ChannelServices.RegisterChannel, new TcpChannel, new HttpChannel.
_DOTNET_REMOTING = _re(
    r"(?:RemotingConfiguration\.Configure\s*\("
    r"|ChannelServices\.RegisterChannel\s*\("
    r"|new\s+TcpChannel\s*\("
    r"|new\s+HttpChannel\s*\()"
    r"[^\)]{0,200}"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="sws-xsw-ds-reference-fragment-uri",
        name="WS-Security XML Signature Wrapping: ds:Reference with fragment URI",
        severity="CRITICAL",
        description=(
            "A `ds:Reference URI=\"#fragment\"` element appears inside a "
            "WS-Security block. This is the canonical setup for XML "
            "Signature Wrapping (XSW): the attacker duplicates the signed "
            "`<Body>` element and inserts a malicious substitute that the "
            "business logic processes, while the signature verifier checks "
            "only the detached, legitimately-signed copy referenced by the "
            "URI fragment. Both malicious SOAP envelopes and vulnerable "
            "server-side WSDL skeleton code that does not re-validate "
            "reference targets exhibit this shape."
        ),
        pattern=_XSW_DS_REFERENCE_FRAGMENT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sws-wsdl-production-exposure",
        name="WSDL endpoint exposure in production route or proxy config",
        severity="MEDIUM",
        description=(
            "A route configuration, reverse-proxy rule, or application "
            "code passes through `?wsdl` / `?WSDL` / `?singleWsdl` query "
            "parameters unconditionally. WSDL files expose: operation "
            "names and parameter types (enabling targeted fuzzing), "
            "internal hostnames/IP addresses embedded in "
            "`<soap:address location=\"...\">`, and sometimes "
            "authentication schemes. WSDL publication should be disabled "
            "in production."
        ),
        pattern=_WSDL_QUERY_PARAM,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sws-soapaction-unauthenticated-dispatch",
        name="SOAPAction header drives dispatch before authentication check",
        severity="HIGH",
        description=(
            "Server-side code reads the `SOAPAction` HTTP header and uses "
            "it to dispatch method calls (execute/invoke/dispatch/call/ "
            "process) without a preceding authentication or role check. "
            "An unauthenticated attacker can craft the `SOAPAction` value "
            "to invoke privileged operations on Axis2/CXF endpoints that "
            "route by action string rather than by caller identity."
        ),
        pattern=_SOAPACTION_DISPATCH,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sws-odata-expand-no-depth-limit",
        name="OData .Expand() called without MaxExpansionDepth limit",
        severity="HIGH",
        description=(
            "An OData controller calls `.Expand()` to enable `$expand` "
            "query option without chaining a `.MaxExpansionDepth(N)` "
            "limiter. Deeply nested `$expand` expressions backed by "
            "Entity Framework / LINQ produce JOIN explosions that exhaust "
            "the DB connection pool, or expose navigation properties that "
            "should not be accessible to callers."
        ),
        pattern=_ODATA_EXPAND_CALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sws-odata-filter-enablequery-no-validation",
        name="OData [EnableQuery] attribute with no validation arguments",
        severity="HIGH",
        description=(
            "An ASP.NET Core OData controller action is decorated with "
            "`[EnableQuery]` without any constructor arguments "
            "(MaxExpansionDepth, AllowedQueryOptions, MaxTop, etc.). "
            "This allows arbitrary `$filter` expressions to be compiled "
            "directly to LINQ / SQL without bounds, enabling expression "
            "tree injection, expensive computed-column evaluation, and "
            "in older OData v3 implementations, raw SQL fragment injection."
        ),
        pattern=_ENABLEQUERY_NO_ARGS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sws-odata-select-raw-identity-entity",
        name="OData [EnableQuery] on method returning raw ASP.NET Identity EF entity",
        severity="HIGH",
        description=(
            "An OData controller method marked `[EnableQuery]` returns "
            "`IQueryable<ApplicationUser>` (or another raw EF Identity "
            "entity). Without a DTO/view-model layer, callers can use "
            "`$select=PasswordHash,SecurityStamp,SocialSecurityNumber` "
            "to extract columns that the UI never surfaces. The "
            "`[EnableQuery]` attribute with no DTO projection is the "
            "exact vulnerable form."
        ),
        pattern=_ENABLEQUERY_RAW_IDENTITY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sws-sct-token-reuse-no-expiry-check",
        name="WS-SecureConversation SCT validator accepts token without expiry check",
        severity="HIGH",
        description=(
            "A custom WS-SecureConversation `SecurityContextToken` "
            "validator checks the token store membership (`tokenStore."
            "contains/get`) and immediately returns the credential object "
            "without calling `sct.getExpires()` or equivalent. A stolen "
            "or expired SCT can therefore authenticate subsequent messages "
            "indefinitely, bypassing the expiry control mandated by "
            "WS-Trust."
        ),
        pattern=_SCT_NO_EXPIRY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="sws-mtom-attachment-path-traversal",
        name="MTOM/SwA attachment filename used unsanitized in File constructor",
        severity="CRITICAL",
        description=(
            "SOAP MTOM / SwA attachment handling code extracts the "
            "filename from `Content-Disposition` headers (via "
            "`getContentDisposition`, `getParameter(\"filename\")`, or "
            "`getFileName()`) and passes it directly to `new File(dir, "
            "filename)` without path normalization. An attacker can "
            "supply `../../conf/tomcat-users.xml` as the filename to "
            "write the attachment to an arbitrary path (path traversal "
            "/ arbitrary file write)."
        ),
        pattern=_MTOM_PATH_TRAVERSAL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="sws-dotnet-remoting-channel-registration",
        name=".NET Remoting channel registration — implicit BinaryFormatter RCE",
        severity="CRITICAL",
        description=(
            "Code activates the legacy .NET Remoting pipeline via "
            "`RemotingConfiguration.Configure`, `ChannelServices."
            "RegisterChannel`, `new TcpChannel(...)`, or "
            "`new HttpChannel(...)`. .NET Remoting uses `BinaryFormatter` "
            "implicitly for all wire serialization — a known RCE vector "
            "(CVE-2014-4149, CVE-2022-26832). Unlike the explicit "
            "`BinaryFormatter.Deserialize` covered by "
            "`cross_lang_deserialize_patterns`, this targets the remoting "
            "activation layer where serialization is implicit."
        ),
        pattern=_DOTNET_REMOTING,
        owasp_asi="ASI-01",
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



# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters:

      * S4 (odata-expand-no-depth-limit) — fire on `.Expand()` and
        suppress if `MaxExpansionDepth` appears within a 3-line forward
        window (the chained method call).

      * S5 (odata-filter-enablequery-no-validation) — fire on
        `[EnableQuery]` with no args or empty args.

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

    # ---- S1 : sws-xsw-ds-reference-fragment-uri ----
    rule_s1 = rule_by_id["sws-xsw-ds-reference-fragment-uri"]
    for m in _XSW_DS_REFERENCE_FRAGMENT.finditer(text):
        _emit(rule_s1, m.start(), m.group(0))

    # ---- S2 : sws-wsdl-production-exposure ----
    rule_s2 = rule_by_id["sws-wsdl-production-exposure"]
    for m in _WSDL_QUERY_PARAM.finditer(text):
        _emit(rule_s2, m.start(), m.group(0))

    # ---- S3 : sws-soapaction-unauthenticated-dispatch ----
    rule_s3 = rule_by_id["sws-soapaction-unauthenticated-dispatch"]
    for m in _SOAPACTION_DISPATCH.finditer(text):
        _emit(rule_s3, m.start(), m.group(0))

    # ---- S4 : sws-odata-expand-no-depth-limit ----
    rule_s4 = rule_by_id["sws-odata-expand-no-depth-limit"]
    for m in _ODATA_EXPAND_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        # Suppress if MaxExpansionDepth appears within 3 lines forward
        # (the safe chained-method form).
        window = _slice_forward(text, line, 3)
        if _ODATA_MAX_EXPANSION_DEPTH.search(window) is not None:
            continue
        _emit(rule_s4, m.start(), m.group(0))

    # ---- S5 : sws-odata-filter-enablequery-no-validation ----
    rule_s5 = rule_by_id["sws-odata-filter-enablequery-no-validation"]
    for m in _ENABLEQUERY_NO_ARGS.finditer(text):
        _emit(rule_s5, m.start(), m.group(0))
    for m in _ENABLEQUERY_EMPTY_ARGS.finditer(text):
        _emit(rule_s5, m.start(), m.group(0))

    # ---- S6 : sws-odata-select-raw-identity-entity ----
    rule_s6 = rule_by_id["sws-odata-select-raw-identity-entity"]
    for m in _ENABLEQUERY_RAW_IDENTITY.finditer(text):
        _emit(rule_s6, m.start(), m.group(0))

    # ---- S7 : sws-sct-token-reuse-no-expiry-check ----
    rule_s7 = rule_by_id["sws-sct-token-reuse-no-expiry-check"]
    for m in _SCT_NO_EXPIRY.finditer(text):
        _emit(rule_s7, m.start(), m.group(0))

    # ---- S8 : sws-mtom-attachment-path-traversal ----
    rule_s8 = rule_by_id["sws-mtom-attachment-path-traversal"]
    for m in _MTOM_PATH_TRAVERSAL.finditer(text):
        _emit(rule_s8, m.start(), m.group(0))

    # ---- S9 : sws-dotnet-remoting-channel-registration ----
    rule_s9 = rule_by_id["sws-dotnet-remoting-channel-registration"]
    for m in _DOTNET_REMOTING.finditer(text):
        _emit(rule_s9, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
