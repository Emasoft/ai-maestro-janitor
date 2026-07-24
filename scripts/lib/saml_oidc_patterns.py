"""SAML 2.0 / OIDC federated-identity trust-chain patterns.

Wave-23 implementation, distillation round 9.

A targeted catalogue of 9 anti-patterns covering **SP-side / RP-side
trust failures** in SAML XML assertion handling, OIDC discovery, IdP
metadata, federation chains, and JWE encryption envelopes. The shared
theme is "the relying party trusted the wrong attribute, the wrong
endpoint, or the wrong signature scope."

What is NOT here (already shipped — DO NOT duplicate):

  * `oauth_device_flow_patterns.py` — RFC 8628 device-code grant abuses
    (polling, user_code phishing, audience confusion in the device flow).
  * `jwt_deeper_patterns.py` — JWS header tricks (`alg=none`, `kid`
    injection, RS-to-HS confusion, JKU/X5U side-loading) at the **single
    token** level.
  * `auth_flow_patterns.py` — generic OAuth code/state/PKCE
    state-machine bugs (callback `state` compare, refresh REUSE,
    PKCE absence broadly).

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * saml-xsw-no-referenced-element-check                 (CRITICAL)
  * saml-response-inresponseto-not-validated             (HIGH)
  * oidc-discovery-not-pinned                            (HIGH)
  * oidc-id-token-sub-trusted-without-iss-pinning        (CRITICAL)
  * oidc-jwe-crit-header-not-pinned                      (HIGH)
  * oidc-pkce-downgrade-s256-to-plain                    (HIGH)
  * saml-acs-url-not-pinned                              (HIGH)
  * saml-xml-loaded-without-defused-xml                  (HIGH)
  * oidc-confidential-client-uses-none-auth              (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape used across the lib/.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control / Identity Confusion (cross-IdP `sub`
                                                        impersonation,
                                                        ACS redirection)
  ASI-02 — Improper Authentication (InResponseTo replay, PKCE downgrade,
                                     confidential-client `none` auth)
  ASI-04 — Insufficient Cryptographic Validation (XSW signature scope,
                                                   JWE `crit` allowlist,
                                                   XXE on SAML XML)
  ASI-08 — Software and Data Integrity Failures (OIDC discovery pinning)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    chat_bot_patterns / oauth_device_flow_patterns / jwt_deeper_patterns.
    RE2-safe: no nested quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- S1 : saml-xsw-no-referenced-element-check --------------------------


# XSW (XML Signature Wrapping, Somorovsky 2012) succeeds when the SP
# verifies a signature in the SAML document but then re-queries the
# whole doc for `<Assertion>` and reads attributes from a node the
# signature does NOT actually cover. The trigger is a signature-verify
# call followed (within ~5 lines) by a generic XPath/find lookup for an
# Assertion node. RE2-safe: no backreference, no lookbehind.
_SAML_XSW_VERIFY_THEN_REQUERY = _re(
    # signxml.XMLVerifier().verify(...) | XMLVerifier().verify(...) |
    # xmlsec.verify(...) | obj.verify(...) — the discriminator is the
    # literal substring `.verify(` immediately on a Python/Java/Node
    # crypto-validator object.
    r"(?:XMLVerifier\s*\(\s*\)\s*\.\s*verify|xmlsec\.verify|signxml[^\n]{0,60}\.verify)"
    r"\s*\([^\n)]{0,300}\)"
    r"[\s\S]{0,400}?"
    # The bug: re-querying the whole document.
    r"\b(?:find|findall|xpath)\s*\(\s*['\"]\.{0,2}//[^'\"]*Assertion"
)


# ---- S2 : saml-response-inresponseto-not-validated ----------------------


# An SP that base64-decodes a SAMLResponse, verifies its signature, but
# never cross-checks `InResponseTo` against a stored AuthnRequest ID is
# vulnerable to cross-session assertion replay. The Stage-A trigger is
# any code path consuming `SAMLResponse` AND calling a signature-verify
# function. Stage-B (in scan_text) requires the absence of any
# `InResponseTo` reference AND the absence of an unsolicited-SSO opt-in.
_SAML_RESPONSE_VERIFY_TRIGGER = _re(
    # The literal string `SAMLResponse` (parameter / dict key /
    # query-string name) anchors the SP-side code path.
    r"\bSAMLResponse\b"
)

# Stage-B markers (RE2-safe — no `(?!...)` lookbehind/lookahead needed).
_SAML_VERIFY_CALL = _re(
    r"\b(?:verify(?:Signature)?|XMLVerifier|signxml|xmlsec\.verify)\b"
)

_SAML_INRESPONSETO_MARKER = _re(
    r"\b(?:InResponseTo|in_response_to|inResponseTo|in-response-to)\b"
)

_SAML_UNSOLICITED_OPTIN = _re(
    # SimpleSAMLphp / python-saml / passport-saml allow-unsolicited names.
    r"\b(?:allow[_-]?unsolicited|unsolicited\s*[:=]\s*(?:true|True|1))\b"
)


# ---- S3 : oidc-discovery-not-pinned -------------------------------------


# OIDC RPs that build the .well-known/openid-configuration URL with an
# f-string / template-literal interpolation of a runtime variable
# (tenant, request param, env var) are at risk if the variable is
# attacker-influenced. A constant literal URL is safe; an f-string with
# `{...}` interpolation is the bug.
_OIDC_DISCOVERY_INTERPOLATED = _re(
    # Python f-string OR JS template literal (backtick).  Both contain a
    # `{...}` / `${...}` interpolation marker AND end with the literal
    # .well-known/openid-configuration suffix.
    r"f['\"][^'\"]*\{[^}]+\}[^'\"]*\.well-known/openid-configuration"
    r"|"
    r"`[^`]*\$\{[^}]+\}[^`]*\.well-known/openid-configuration"
)

# Same-file allowlist marker — if present, the rule is suppressed
# (the implementer is doing a tenant-allowlist lookup before fetching).
_OIDC_DISCOVERY_ALLOWLIST_MARKER = _re(
    r"\ballowed_issuers?\b"
    r"|"
    r"\bis_allowed_issuer\b"
    r"|"
    r"\btenant\.allowed_issuers\b"
    r"|"
    r"\bISSUER_ALLOWLIST\b"
)


# ---- S4 : oidc-id-token-sub-trusted-without-iss-pinning -----------------


# Multi-IdP RPs that index a user by `claims.sub` alone (without
# matching `claims.iss` first) can be impersonated cross-IdP by any
# federated issuer the RP also trusts. Trigger: a verify call producing
# a `claims` (or similar) object, followed by a lookup keyed on `.sub`
# / `.subject`. Stage-B requires absence of `.iss` / `issuer` matching
# in the same 30-line window.
_OIDC_VERIFY_THEN_SUB_LOOKUP = _re(
    # `jwtVerify` / `jwt.verify` / `verify_jwt` / `decode_token` call,
    # within 200 chars followed by a lookup whose key is `.sub` /
    # `.subject` / external_id of a claims object.
    r"\b(?:jwtVerify|jwt\.verify|verify_jwt|decode_token|verify_token|verify_id_token)\s*\("
    r"[\s\S]{0,300}?"
    r"\b(?:findOne|findBy|filter|get|query|select|first|fetch)\s*\("
    r"[^)\n]{0,200}\b(?:sub|subject|external_id|user_id)\b"
)

_OIDC_ISSUER_PINNED_MARKER = _re(
    # An explicit issuer match in the same window: `claims.iss ===`,
    # `claims["iss"] ==`, `assert claims.iss ==`, expected_issuer, etc.
    r"\b(?:iss|issuer|expected_issuer|EXPECTED_ISSUER|trusted_issuers?)\b"
)


# ---- S5 : oidc-jwe-crit-header-not-pinned -------------------------------


# JWE decrypt calls that don't pass an explicit `crit` allowlist are
# vulnerable to attacker-supplied `"crit": [...]` headers altering
# validation semantics. The trigger is any compactDecrypt /
# jwe.decrypt / JWE.Decrypt call. Stage-B requires the *call's argument
# list* to not contain a `crit` / `allowedCritOptions` / `allow_crit`
# / `critical` keyword.
_OIDC_JWE_DECRYPT_CALL = _re(
    # Match the call AND capture its argument list (up to 500 chars,
    # bounded so RE2-safe). The Stage-B filter in scan_text checks the
    # captured argument substring for the crit-keyword.
    r"\b(?:jwe\.decrypt|compactDecrypt|JWE\.Decrypt|jose\.JSONWebEncryption|JWE\.decrypt)"
    r"\s*\(([^)]{0,500})\)"
)

_OIDC_JWE_CRIT_KEYWORD = _re(
    r"\b(?:crit|allowedCritOptions|allow_crit|critical|crit_allowlist)\b"
)


# ---- S6 : oidc-pkce-downgrade-s256-to-plain -----------------------------


# Two variants:
#   (a) An auth URL emits `code_challenge=...` but no
#       `code_challenge_method=S256` parameter. Server default is
#       `plain` under RFC 7636 §4.3 — downgrade.
#   (b) An auth URL explicitly sets `code_challenge_method=plain`.
#       Trivial detection.
_OIDC_PKCE_METHOD_PLAIN_EXPLICIT = _re(
    r"code_challenge_method\s*[:=]\s*['\"]?plain['\"]?\b"
)

# Stage-A for variant (a): the literal `code_challenge=` token in an
# emitted URL / dict.  Stage-B requires no `code_challenge_method` in
# the same window AND no `ALLOW_PLAIN_PKCE` deliberate-downgrade gate.
_OIDC_PKCE_CHALLENGE_TOKEN = _re(
    r"\bcode_challenge\s*[:=]\s*['\"`]?[^,&\s'\"`]+"
)

_OIDC_PKCE_METHOD_S256_MARKER = _re(
    r"code_challenge_method\s*[:=]\s*['\"]?S256['\"]?"
)

_OIDC_PKCE_DELIBERATE_PLAIN_MARKER = _re(
    r"\bALLOW_PLAIN_PKCE\b"
    r"|"
    r"#\s*PKCE\s+plain\s+intentional\b"
)


# ---- S7 : saml-acs-url-not-pinned ---------------------------------------


# AssertionConsumerServiceURL pulled from request input rather than SP
# metadata. The IdP will post the signed assertion to attacker-chosen
# host, leaking the assertion. RE2-safe: pattern is a single bounded
# expression with no nested repetition.
_SAML_ACS_URL_FROM_INPUT = _re(
    # Python: AssertionConsumerServiceURL="...{request.args.get(...)}..."
    r"AssertionConsumerServiceURL\s*=\s*['\"][^'\"]{0,40}\{[^}]*"
    r"(?:request|req|params|args|tenant|user_input|userInput)"
    r"|"
    # JS template literal: AssertionConsumerServiceURL=`...${req.body...}...`
    r"AssertionConsumerServiceURL\s*=\s*`[^`]{0,40}\$\{[^}]*"
    r"(?:request|req|params|args|tenant|user_input|userInput)"
    r"|"
    # Setter form: setAssertionConsumerServiceURL(req.body.acs_url) etc.
    r"\bset(?:AssertionConsumerServiceURL|AcsUrl|ACS(?:Url|URL))\s*\("
    r"[^)\n]{0,80}\b(?:request|req|params|args|tenant|user_input|userInput|body)\b"
)

# Same-file metadata-allowlist marker — if present, finding suppressed.
_SAML_ACS_ALLOWLIST_MARKER = _re(
    r"\bacs_allowed_for_tenant\b"
    r"|"
    r"\bacs\s*in\s*metadata\.acs_list\b"
    r"|"
    r"\bACS_ALLOWLIST\b"
    r"|"
    r"\bmetadata\.acs_endpoints\b"
)


# ---- S8 : saml-xml-loaded-without-defused-xml ---------------------------


# Direct use of `etree.fromstring` / `xml.etree.ElementTree.parse` /
# `ET.fromstring` on a parameter named `saml*` is an XXE / billion-laughs
# vector unless the same file imports `defusedxml`.
_SAML_XML_PARSE_SAML_INPUT = _re(
    # The function call on a variable whose name contains `saml` (case
    # insensitive — the _re helper sets IGNORECASE). RE2-safe: bounded
    # quantifiers, no nesting.
    r"\b(?:etree|xml\.etree\.ElementTree|ET|lxml\.etree)\.(?:fromstring|parse|XML)"
    r"\s*\(\s*[A-Za-z_][A-Za-z0-9_]{0,30}saml[A-Za-z0-9_]{0,30}\b"
    r"|"
    # Allow the variable to START with `saml` (e.g. `saml_xml`,
    # `samlResponseBytes`).
    r"\b(?:etree|xml\.etree\.ElementTree|ET|lxml\.etree)\.(?:fromstring|parse|XML)"
    r"\s*\(\s*saml[A-Za-z0-9_]{0,30}\b"
)

# Java equivalent — SAXParserFactory without disallow-doctype-decl.
_SAML_SAXPARSER_DEFAULT = _re(
    r"\bSAXParserFactory\.newInstance\s*\(\s*\)"
)

_SAML_DEFUSED_XML_MARKER = _re(
    r"\bdefusedxml\b"
    r"|"
    r"\bdefused_xml\b"
)

_SAML_JAVA_XXE_GUARD_MARKER = _re(
    # Any of the canonical SAX/DOM XXE-hardening feature toggles.
    r"disallow-doctype-decl"
    r"|"
    r"external-general-entities"
    r"|"
    r"external-parameter-entities"
    r"|"
    r"load-external-dtd"
    r"|"
    r"FEATURE_SECURE_PROCESSING"
)

# We only flag the Java SAXParser case if a `saml` token shows up in the
# file (otherwise we'd flag every Java XML parse on the planet).
_SAML_JAVA_FILE_SAML_CONTEXT = _re(
    r"\bsaml\b"
)


# ---- S9 : oidc-confidential-client-uses-none-auth -----------------------


# A configuration object that BOTH carries a `client_secret` AND
# advertises `token_endpoint_auth_method="none"`. Native/device apps
# legitimately do this with an explicit IS_NATIVE_APP / DEVICE_FLOW
# marker; everyone else is mis-configured.
_OIDC_CONFIDENTIAL_NONE_AUTH_AB = _re(
    # client_secret = ... within 200 chars of token_endpoint_auth_method = "none"
    r"client_secret\s*[:=]\s*[^,\n)\]]+[\s\S]{0,250}?"
    r"token_endpoint_auth_method\s*[:=]\s*['\"]none['\"]"
)

_OIDC_CONFIDENTIAL_NONE_AUTH_BA = _re(
    # Same shape, reversed order (token_endpoint_auth_method first).
    r"token_endpoint_auth_method\s*[:=]\s*['\"]none['\"][\s\S]{0,250}?"
    r"client_secret\s*[:=]\s*[^,\n)\]]+"
)

_OIDC_NATIVE_APP_MARKER = _re(
    r"\bIS_NATIVE_APP\b"
    r"|"
    r"\bDEVICE_FLOW\b"
    r"|"
    r"#\s*device\s+flow\s+requires\s+none"
    r"|"
    # passing both is OK when a same-file device-grant call exists.
    r"\bgrant_type\s*[:=]\s*['\"]urn:ietf:params:oauth:grant-type:device_code['\"]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="saml-xsw-no-referenced-element-check",
        name="SAML signature verified but Assertion re-queried by XPath after the fact",
        severity="CRITICAL",
        description=(
            "XML Signature Wrapping (XSW, Somorovsky 2012) class attack. "
            "The SP calls `XMLVerifier().verify(doc, ...)` or "
            "`xmlsec.verify(...)` and then, instead of reading attributes "
            "from the node the signature actually covers, re-queries the "
            "whole document with `doc.find('//Assertion')` or "
            "`xpath('//Assertion')`. An attacker prepends a forged "
            "Assertion that ends up at index [0] — the signature is "
            "valid (over a different node), but the SP reads identity "
            "from the forged one. Full identity impersonation against "
            "every tenant of the SP. Maps to CVE-2017-11428 and the "
            "OneLogin / Vault / SimpleSAMLphp XSW advisories."
        ),
        pattern=_SAML_XSW_VERIFY_THEN_REQUERY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="saml-response-inresponseto-not-validated",
        name="SAMLResponse signature verified without matching InResponseTo",
        severity="HIGH",
        description=(
            "An SP that base64-decodes a SAMLResponse and verifies the "
            "embedded signature but never cross-checks `InResponseTo` "
            "against a server-stored AuthnRequest ID is vulnerable to "
            "cross-session assertion replay: one stolen signed assertion "
            "logs in any session for that user. Maps to CVE-2022-29173 "
            "(Vault), CVE-2017-11430 (python-saml), and the SimpleSAMLphp "
            "InResponseTo advisory. The mitigation is to either reject "
            "responses with no matching stored request OR require an "
            "explicit `allowUnsolicited=true` opt-in for IdP-initiated "
            "SSO."
        ),
        pattern=_SAML_RESPONSE_VERIFY_TRIGGER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="oidc-discovery-not-pinned",
        name="OIDC discovery URL built from runtime interpolation",
        severity="HIGH",
        description=(
            "OIDC RP fetches `<issuer>/.well-known/openid-configuration` "
            "where the `<issuer>` segment is interpolated from a runtime "
            "variable (tenant-supplied, request param, env var) without "
            "an allowlist. An attacker who controls / takes-over a "
            "sub-tenant issuer can swap the `jwks_uri` in the returned "
            "discovery document and forge id_tokens. Mitigation: pin "
            "issuer to a constant string OR allowlist tenants via "
            "DB lookup before fetching. See OIDC discovery §10.2."
        ),
        pattern=_OIDC_DISCOVERY_INTERPOLATED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="oidc-id-token-sub-trusted-without-iss-pinning",
        name="ID-token claims.sub used as user identity without iss pinning",
        severity="CRITICAL",
        description=(
            "OIDC `(iss, sub)` is the canonical user identity; `sub` "
            "alone is per-IdP-scoped. An RP that verifies an id_token "
            "then looks up a user by `claims.sub` without also matching "
            "`claims.iss` against an expected issuer is vulnerable to "
            "cross-IdP impersonation: any IdP the RP federates with can "
            "mint a token whose `sub` equals the target's `sub` at a "
            "different IdP. CWE-287 / CWE-290 — improper authentication "
            "and authentication-bypass-by-spoofing. Critical for any "
            "multi-tenant SaaS that federates with > 1 IdP."
        ),
        pattern=_OIDC_VERIFY_THEN_SUB_LOOKUP,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="oidc-jwe-crit-header-not-pinned",
        name="JWE decrypt called without explicit crit allowlist",
        severity="HIGH",
        description=(
            "JWE (encrypted JWT) consumers MUST pass an explicit `crit` "
            "allowlist (often `[]` or `['b64']`) to reject "
            "attacker-supplied critical-extension headers. Several JWE "
            "libraries (jose4j pre-fix, node-jose, pyjwt pre-2.0) "
            "default-trust unknown crit values; an attacker can inject "
            "`\"crit\": [\"b64\", \"exp\"]` to alter validation semantics. "
            "Maps to CVE-2018-1000531 (jose4j) and similar advisories. "
            "Detection: any `compactDecrypt` / `jwe.decrypt` / "
            "`JWE.Decrypt` call whose argument list does NOT contain a "
            "`crit` / `allowedCritOptions` / `allow_crit` keyword."
        ),
        pattern=_OIDC_JWE_DECRYPT_CALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="oidc-pkce-downgrade-s256-to-plain",
        name="PKCE code-challenge emitted without S256 method (downgrade to plain)",
        severity="HIGH",
        description=(
            "OIDC PKCE specifies `S256` (mandatory for confidential, "
            "recommended for all public clients) and `plain` (deprecated "
            "for SPAs, forbidden for mobile). Two failure modes: "
            "(a) auth URL contains `code_challenge=` but no "
            "`code_challenge_method=S256` — server defaults to `plain` "
            "per RFC 7636 §4.3; (b) the URL explicitly sets "
            "`code_challenge_method=plain`. Both effectively disable "
            "PKCE. CWE-310 cryptographic downgrade class."
        ),
        pattern=_OIDC_PKCE_METHOD_PLAIN_EXPLICIT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="saml-acs-url-not-pinned",
        name="AssertionConsumerServiceURL built from request input",
        severity="HIGH",
        description=(
            "The `<AssertionConsumerService>` URL tells the IdP where to "
            "POST the signed assertion. An SP that pulls this URL from "
            "request parameters / tenant input instead of from its own "
            "metadata can be tricked into instructing the IdP to POST to "
            "an attacker-controlled host — leaking the signed assertion "
            "and enabling silent SSO takeover. Maps to CVE-2024-39891 "
            "(Twilio Authy), CVE-2023-22501 (Jira Service Desk), and "
            "Cloudflare 2022. Mitigation: refuse to honour ACS URL from "
            "inbound requests OR validate against same-file "
            "metadata.acs_list."
        ),
        pattern=_SAML_ACS_URL_FROM_INPUT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="saml-xml-loaded-without-defused-xml",
        name="SAML XML parsed with vanilla etree/SAXParser (no defusedxml / no XXE guards)",
        severity="HIGH",
        description=(
            "Python's `lxml.etree.fromstring` / `xml.etree.ElementTree."
            "parse` and Java's default `SAXParserFactory` process "
            "external entities and DTDs by default. Parsing an "
            "attacker-controlled SAML XML response without "
            "`defusedxml` (Python) or `disallow-doctype-decl` / "
            "`FEATURE_SECURE_PROCESSING` (Java) exposes XXE → "
            "SSRF, local-file read, billion-laughs DoS. CVE-2017-9233 "
            "(libxml2), CWE-611. SAML spec explicitly forbids DTD "
            "processing in assertions."
        ),
        pattern=_SAML_XML_PARSE_SAML_INPUT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="oidc-confidential-client-uses-none-auth",
        name="Confidential OIDC client ships token_endpoint_auth_method=none",
        severity="HIGH",
        description=(
            "An OIDC client configuration that BOTH stores a "
            "`client_secret` (i.e. it is a confidential client) AND "
            "advertises `token_endpoint_auth_method=\"none\"` to the IdP "
            "effectively downgrades to a public client. The "
            "`client_secret` is no longer enforced at the token "
            "endpoint, so a stolen authorization `code` is sufficient "
            "for token issuance. Device-code flow legitimately uses "
            "`none` (the device IS public) but only when paired with "
            "an explicit `IS_NATIVE_APP`/`DEVICE_FLOW` marker or a "
            "device-code grant_type in the same file. CWE-287 / CWE-310 "
            "downgrade class."
        ),
        pattern=_OIDC_CONFIDENTIAL_NONE_AUTH_AB,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


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


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters:

      * S1 (xsw-no-referenced-element-check) — Stage-A regex already
        encodes the verify-then-find shape; no extra context check.
      * S2 (inresponseto-not-validated) — anchor on `SAMLResponse`,
        require a same-file verify call, AND require BOTH the absence
        of `InResponseTo` AND the absence of unsolicited-SSO opt-in.
      * S3 (oidc-discovery-not-pinned) — flag interpolated discovery
        URLs unless a same-file `allowed_issuers` allowlist marker
        appears.
      * S4 (id-token-sub-without-iss) — flag a verify→sub-lookup chain
        unless `iss`/`issuer`/`expected_issuer` appears in the same
        30-line window.
      * S5 (jwe-crit-not-pinned) — flag every `compactDecrypt` /
        `jwe.decrypt` call whose argument list does NOT contain a
        `crit` keyword.
      * S6 (pkce-downgrade) — Stage-A flags explicit `=plain`;
        Stage-B flags `code_challenge=` lines with no `S256` method
        in the surrounding 5-line window and no `ALLOW_PLAIN_PKCE`
        deliberate-downgrade marker.
      * S7 (acs-url-not-pinned) — flag unless a same-file metadata
        allowlist marker appears.
      * S8 (xml-loaded-without-defused) — flag SAML-named-parameter
        XML parses unless `defusedxml` appears in the file. The Java
        SAXParser variant requires a same-file `saml` token AND the
        absence of XXE-hardening feature toggles.
      * S9 (confidential-none-auth) — flag the AB / BA shape unless a
        same-file `IS_NATIVE_APP` / `DEVICE_FLOW` / device-code-grant
        marker appears.

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

    # ---- S1 : saml-xsw-no-referenced-element-check ----
    rule_s1 = rule_by_id["saml-xsw-no-referenced-element-check"]
    for m in _SAML_XSW_VERIFY_THEN_REQUERY.finditer(text):
        _emit(rule_s1, m.start(), m.group(0))

    # ---- S2 : saml-response-inresponseto-not-validated ----
    rule_s2 = rule_by_id["saml-response-inresponseto-not-validated"]
    has_inresponseto = _file_contains(text, _SAML_INRESPONSETO_MARKER)
    has_unsolicited = _file_contains(text, _SAML_UNSOLICITED_OPTIN)
    has_verify_call = _file_contains(text, _SAML_VERIFY_CALL)
    if has_verify_call and not has_inresponseto and not has_unsolicited:
        # Emit at the first SAMLResponse anchor so the finding has a
        # concrete file:line target.
        m2 = _SAML_RESPONSE_VERIFY_TRIGGER.search(text)
        if m2 is not None:
            _emit(rule_s2, m2.start(), m2.group(0))

    # ---- S3 : oidc-discovery-not-pinned ----
    rule_s3 = rule_by_id["oidc-discovery-not-pinned"]
    has_issuer_allowlist = _file_contains(text, _OIDC_DISCOVERY_ALLOWLIST_MARKER)
    if not has_issuer_allowlist:
        for m in _OIDC_DISCOVERY_INTERPOLATED.finditer(text):
            _emit(rule_s3, m.start(), m.group(0))

    # ---- S4 : oidc-id-token-sub-trusted-without-iss-pinning ----
    rule_s4 = rule_by_id["oidc-id-token-sub-trusted-without-iss-pinning"]
    for m in _OIDC_VERIFY_THEN_SUB_LOOKUP.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 30)
        if _OIDC_ISSUER_PINNED_MARKER.search(window) is not None:
            continue
        _emit(rule_s4, m.start(), m.group(0))

    # ---- S5 : oidc-jwe-crit-header-not-pinned ----
    rule_s5 = rule_by_id["oidc-jwe-crit-header-not-pinned"]
    for m in _OIDC_JWE_DECRYPT_CALL.finditer(text):
        # group(1) is the captured argument list of the call.
        args = m.group(1) or ""
        if _OIDC_JWE_CRIT_KEYWORD.search(args) is not None:
            continue
        _emit(rule_s5, m.start(), m.group(0))

    # ---- S6 : oidc-pkce-downgrade-s256-to-plain ----
    rule_s6 = rule_by_id["oidc-pkce-downgrade-s256-to-plain"]
    has_deliberate_plain = _file_contains(text, _OIDC_PKCE_DELIBERATE_PLAIN_MARKER)
    if not has_deliberate_plain:
        # Variant (b): explicit =plain — always emit at the literal.
        for m in _OIDC_PKCE_METHOD_PLAIN_EXPLICIT.finditer(text):
            _emit(rule_s6, m.start(), m.group(0))
        # Variant (a): code_challenge= without S256 method nearby.
        for m in _OIDC_PKCE_CHALLENGE_TOKEN.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 3, 5)
            if _OIDC_PKCE_METHOD_S256_MARKER.search(window) is not None:
                continue
            if _OIDC_PKCE_METHOD_PLAIN_EXPLICIT.search(window) is not None:
                # Already flagged by variant (b) at its own line; suppress
                # duplicate-from-missing-method here.
                continue
            _emit(rule_s6, m.start(), m.group(0))

    # ---- S7 : saml-acs-url-not-pinned ----
    rule_s7 = rule_by_id["saml-acs-url-not-pinned"]
    has_acs_allowlist = _file_contains(text, _SAML_ACS_ALLOWLIST_MARKER)
    if not has_acs_allowlist:
        for m in _SAML_ACS_URL_FROM_INPUT.finditer(text):
            _emit(rule_s7, m.start(), m.group(0))

    # ---- S8 : saml-xml-loaded-without-defused-xml ----
    rule_s8 = rule_by_id["saml-xml-loaded-without-defused-xml"]
    has_defusedxml = _file_contains(text, _SAML_DEFUSED_XML_MARKER)
    if not has_defusedxml:
        # Python variant: etree.fromstring(saml_xxx)
        for m in _SAML_XML_PARSE_SAML_INPUT.finditer(text):
            _emit(rule_s8, m.start(), m.group(0))
        # Java variant: SAXParserFactory in a SAML-context file
        # without canonical XXE-hardening toggles.
        if (
            _file_contains(text, _SAML_JAVA_FILE_SAML_CONTEXT)
            and not _file_contains(text, _SAML_JAVA_XXE_GUARD_MARKER)
        ):
            for m in _SAML_SAXPARSER_DEFAULT.finditer(text):
                _emit(rule_s8, m.start(), m.group(0))

    # ---- S9 : oidc-confidential-client-uses-none-auth ----
    rule_s9 = rule_by_id["oidc-confidential-client-uses-none-auth"]
    has_native_marker = _file_contains(text, _OIDC_NATIVE_APP_MARKER)
    if not has_native_marker:
        # Order AB: client_secret first, then method=none
        for m in _OIDC_CONFIDENTIAL_NONE_AUTH_AB.finditer(text):
            _emit(rule_s9, m.start(), m.group(0))
        # Order BA: method=none first, then client_secret
        for m in _OIDC_CONFIDENTIAL_NONE_AUTH_BA.finditer(text):
            _emit(rule_s9, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
