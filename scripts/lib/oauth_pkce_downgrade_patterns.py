"""OAuth 2.1 PKCE downgrade & state-parameter omission patterns.

Wave-32 implementation, distill-round-18 angle — OAuth PKCE downgrade.

A targeted pattern catalogue for OAuth 2.1 downgrade attacks, deprecated
grant types, authorization-server enforcement gaps, and state-parameter
omissions that are orthogonal to existing rule modules.

What is NOT here (already shipped — DO NOT duplicate):

  * Client-side PKCE absence in auth URL — ``auth_flow_patterns.py``
    (``auth-oauth-pkce-missing-public-client``) and
    ``oauth_device_flow_patterns.py``
    (``oauth-authorize-pkce-missing-public-client``).
  * OIDC PKCE downgrade from S256 to plain — ``saml_oidc_patterns.py``
    (``oidc-pkce-downgrade-s256-to-plain``).
  * Static/reused OAuth state literal — ``auth_flow_patterns.py``
    (``auth-oauth-state-reused-constant``).
  * Device-flow state missing outbound — ``oauth_device_flow_patterns.py``
    (``oauth-authorize-state-missing-outbound``).
  * Refresh-token rotation YAML/JSON disable flag —
    ``secret_rotation_patterns.py`` (``refresh-token-rotation-disabled``).
  * OIDC nonce missing in authorization URL — ``credential_lifecycle_patterns.py``
    (``oidc-nonce-missing``).
  * Browser-side code replay / history.replaceState —
    ``oauth_device_flow_patterns.py``
    (``oauth-authorize-code-replay-no-history-clear``).
  * Redirect-URI wildcard in registered configuration —
    ``auth_flow_patterns.py`` (``auth-oauth-redirect-uri-wildcard``).

What IS here (10 net-new rules, all RE2-safe):

  * opkce-ropc-grant-type-used                        (HIGH)
  * opkce-implicit-flow-response-type-token           (HIGH)
  * opkce-as-pkce-not-enforced-config                 (CRITICAL)
  * opkce-authorization-code-no-single-use-server     (HIGH)
  * opkce-confidential-client-no-dpop-binding         (MEDIUM)
  * opkce-refresh-token-no-rotation-check-client      (MEDIUM)
  * opkce-authorize-state-param-absent-web            (HIGH)
  * opkce-redirect-uri-open-redirect-runtime          (HIGH)
  * opkce-oidc-nonce-not-validated-server             (HIGH)
  * opkce-token-scope-elevation-from-request          (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors the
            chat_bot_patterns.Finding shape used by every other
            rule module in scripts/lib/.

OWASP ASI mapping used:
  ASI-04 — Broken Authentication (ROPC, implicit flow, PKCE enforcement,
                                   code replay, DPoP absent, nonce replay)
  ASI-05 — Open Redirect (redirect_uri path traversal via user input)
  ASI-07 — CSRF / Broken Authorization (state param absent, scope elevation,
                                         refresh-token rotation gap)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
non-greedy quantifiers nested under alternation). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
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
    auth_flow_patterns / chat_bot_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : opkce-ropc-grant-type-used ------------------------------------
# RFC 9700 (OAuth 2.1 draft) removes ROPC entirely. grant_type=password
# passes plaintext credentials to the client — incompatible with MFA,
# phishing-resistant flows, and the redirect-based user-agent separation
# guarantee. Keycloak's `directAccessGrantsEnabled: true` enables ROPC
# server-side; both forms are flagged.
# The optional trailing quote handles Python/JSON dict key notation where
# the key itself is quoted: 'grant_type': 'password'.

_ROPC_GRANT_TYPE = _re(
    r"""grant_type['"]?\s*[:=]\s*['"]password['"]"""
)

_ROPC_KEYCLOAK_CONFIG = _re(
    r"""directAccessGrantsEnabled['":\s]+true"""
)


# ---- P2 : opkce-implicit-flow-response-type-token -----------------------
# OAuth implicit grant (response_type=token) returns the access token
# directly in the URL fragment — exposed to browser history, Referer
# header, and XSS. RFC 9700 §2.1.2 prohibits it for new deployments.
# Config-level: Auth0 `allowed_oauth_flows` list containing "implicit".
# The .set(key, value) form used in JS URLSearchParams APIs is also covered.

_IMPLICIT_RESPONSE_TYPE = _re(
    r"""response_type['"]\s*,\s*['"]token['"]"""
    r"""|"""
    r"""response_type['"]?\s*[:=]\s*['"]token['"]"""
)

_IMPLICIT_FLOW_CONFIG = _re(
    r"""allowed_oauth_flows['":\s\[]+implicit"""
)


# ---- P3 : opkce-as-pkce-not-enforced-config -----------------------------
# Authorization-server configuration explicitly disabling PKCE enforcement.
# An AS that does not require PKCE allows attackers to replay authorization
# codes via referrer/history leakage even when clients send PKCE — because
# the AS never validates the verifier.
# Covers: Keycloak (empty pkce.code.challenge.method), Auth0
# (enforce_pkce: false), Spring Authorization Server (require-proof-key: false).

_AS_PKCE_KEYCLOAK_EMPTY = _re(
    r"""pkce[._-]?code[._-]?challenge[._-]?method['":\s=]+["']{2}"""
)

_AS_PKCE_ENFORCE_FALSE = _re(
    r"""enforce[_-]pkce['":\s=]+false"""
)

_AS_PKCE_SPRING_FALSE = _re(
    r"""require[_-]proof[_-]key['":\s:]+false"""
)


# ---- P4 : opkce-authorization-code-no-single-use-server ----------------
# Server-side handler performs an ORM lookup for an authorization code but
# never marks it consumed / deletes it — allowing code replay.
# Anchor: AuthorizationCode.objects.get / findOne / find calls, or
# SQL SELECT on auth_code tables.
# Suppression: delete / used=True / consumed in a 30-line forward window.

_AUTH_CODE_ORM_LOOKUP = _re(
    r"""AuthorizationCode\s*\.\s*(?:objects\s*\.\s*get|findOne|find)\s*\("""
    r"""|"""
    r"""SELECT\s+[^;]{0,200}auth(?:_|orization[_]?)code"""
    r"""|"""
    r"""db\.(?:query|findOne|find)\s*\([^)]{0,200}(?:auth_code|authorization_code|authcode)"""
)

_AUTH_CODE_SINGLE_USE_GUARD = _re(
    r"""\bdelete\b"""
    r"""|"""
    r"""\bused\s*=\s*True\b"""
    r"""|"""
    r"""\bconsumed\b"""
    r"""|"""
    r"""\bdestroy\b"""
    r"""|"""
    r"""UPDATE\s+[A-Za-z_]+\s+SET\s+used"""
    r"""|"""
    r"""\.deleteOne\s*\("""
    r"""|"""
    r"""\.remove\s*\("""
)


# ---- P5 : opkce-confidential-client-no-dpop-binding --------------------
# Confidential client (client_secret present) performs a token request
# without DPoP header or mTLS sender-constraining. Scoped to high-value
# OAuth scopes to reduce false-positives.
# Anchor: client_secret= in a token endpoint request body.
# Suppression: DPoP header reference or dpop_nonce within the file.

_CONFIDENTIAL_CLIENT_TOKEN_REQUEST = _re(
    r"""client_secret['"]?\s*[:=]\s*['"]\S{8,}['"]"""
)

_HIGH_VALUE_SCOPE = _re(
    r"""scope\s*[:=]\s*['""][^'"]*(?:payments?|admin|transfer|finance|billing)[^'"]*['"]"""
    r"""|"""
    r"""scope.*(?:payments?|admin|transfer|finance|billing)"""
)

_DPOP_GUARD = _re(
    r"""\bDPoP\b"""
    r"""|"""
    r"""\bdpop_nonce\b"""
    r"""|"""
    r"""\bdpop_proof\b"""
    r"""|"""
    r"""\bcreate_dpop_proof\b"""
    r"""|"""
    r"""\brequireDPoP\b"""
)


# ---- P6 : opkce-refresh-token-no-rotation-check-client -----------------
# Client-side refresh_token grant that does not capture the new refresh
# token from the server response — silently accepting rotation failure.
# Anchor: grant_type=refresh_token in a token POST body.
# Suppression: reference to updating/storing refresh_token from response
# within a 50-line forward window.

_REFRESH_GRANT_ANCHOR = _re(
    r"""grant_type['"]?\s*[:=]\s*['"]refresh_token['"]"""
)

_REFRESH_ROTATION_GUARD = _re(
    r"""(?:new|updated?)_?refresh_token"""
    r"""|"""
    r"""data\[['"]refresh_token['"]\]"""
    r"""|"""
    r"""\.get\(['"]refresh_token['"]\)"""
    r"""|"""
    r"""response\[['"]refresh_token['"]\]"""
    r"""|"""
    r"""result\.refresh_token"""
    r"""|"""
    r"""tokens\.refresh_token"""
    r"""|"""
    r"""save.*refresh|store.*refresh|persist.*refresh"""
)


# ---- P7 : opkce-authorize-state-param-absent-web -----------------------
# Authorization URL constructed with response_type=code but no state=
# parameter on the same line — CSRF via OAuth flow.
# Covers the URL-string form, dict/param form, and JS .set(key, value) form.
# Suppression: any state= assignment or state param in a nearby window.
# Orthogonal to the existing state-reused-constant and device-flow-state rules.

_AUTHORIZE_RESPONSE_TYPE_CODE = _re(
    r"""response_type['"]\s*,\s*['"]code['"]"""
    r"""|"""
    r"""response_type['"]?\s*[:=]\s*['"]code['"]"""
    r"""|"""
    r"""[?&]response_type=code"""
)

_STATE_PARAM_GUARD = _re(
    r"""[?&]state\s*="""
    r"""|"""
    r"""\bstate\s*[:=]\s*[A-Za-z_$('"`]"""
    r"""|"""
    r"""\bstate\s*[:=]\s*crypto\b"""
    r"""|"""
    r"""\bstate\s*[:=]\s*secrets\b"""
    r"""|"""
    r"""\bstate\s*[:=]\s*uuid"""
    r"""|"""
    r"""\bstate\s*[:=]\s*os\.urandom"""
    r"""|"""
    r"""\bstate\s*[:=]\s*randomBytes"""
    r"""|"""
    r"""\b\.set\s*\(\s*['"]state['"]"""
    r"""|"""
    r"""params\.append\s*\(\s*['"]state['"]"""
)


# ---- P8 : opkce-redirect-uri-open-redirect-runtime --------------------
# Runtime-constructed redirect_uri whose path is built from user-controlled
# input — exploitable if the AS validates only the scheme+host prefix.
# Orthogonal to the registered-URI wildcard rule in auth_flow_patterns.
# The pattern anchors on the user-input source and looks forward for
# redirect_uri assignment (not backward), matching the typical code order.

_REDIRECT_URI_USER_INPUT = _re(
    # User input read then redirect_uri built within 300 chars (DOTALL handled in scan)
    r"""request\.(?:args|params|form|json|query)\.(?:get\s*\([^)]{0,100}\)|[A-Za-z_]+)[\s\S]{0,300}redirect_uri"""
    r"""|"""
    r"""req\.(?:query|params|body)\.(?:[A-Za-z_]+)[\s\S]{0,300}redirect_uri"""
    r"""|"""
    r"""r\.URL\.Query\(\)[\s\S]{0,300}redirect"""
    r"""|"""
    r"""redirect_uri.*argv\["""
)

_REDIRECT_URI_TEMPLATE_USER_INPUT = _re(
    r"""redirect_uri\s*=\s*f['"]https?://[^'"]+\{[^}]+\}"""
    r"""|"""
    r"""redirect_uri\s*=\s*['"]https?://[^'"]*['"\s]*\+\s*[A-Za-z_]"""
)


# ---- P9 : opkce-oidc-nonce-not-validated-server -------------------------
# Server-side OIDC ID token decode that consumes the `sub` claim without
# comparing the token's `nonce` claim to the stored session nonce.
# Orthogonal to the client-side `oidc-nonce-missing` rule.

_OIDC_TOKEN_DECODE = _re(
    r"""jwt\.decode\s*\([^)]{0,300}\)"""
    r"""|"""
    r"""jwtVerify\s*\([^)]{0,300}\)"""
    r"""|"""
    r"""jose\.JWT\.verify"""
    r"""|"""
    r"""PyJWT\.decode"""
)

_OIDC_SUB_CONSUMED = _re(
    r"""id_token\[['"]sub['"]\]"""
    r"""|"""
    r"""payload\.sub\b"""
    r"""|"""
    r"""claims\[['"]sub['"]\]"""
    r"""|"""
    r"""decoded\[['"]sub['"]\]"""
)

_OIDC_NONCE_VALIDATED = _re(
    r"""\bnonce\b.*=="""
    r"""|"""
    r"""==.*\bnonce\b"""
    r"""|"""
    r"""session\[['"]nonce['"]\]"""
    r"""|"""
    r"""session\.nonce\b"""
    r"""|"""
    r"""expected_nonce\b"""
    r"""|"""
    r"""oidc_client\.validate_token"""
    r"""|"""
    r"""verify_nonce"""
)


# ---- P10 : opkce-token-scope-elevation-from-request --------------------
# Server-side token endpoint reads the `scope` value directly from the
# incoming request body and passes it to the token-creation function,
# allowing scope elevation beyond what the stored grant authorizes.

_SCOPE_FROM_REQUEST = _re(
    # Don't require closing paren — handles multi-arg calls like get('scope', 'read')
    r"""request\.form\.get\s*\(['"]scope['"]"""
    r"""|"""
    r"""req\.body\.scope\b"""
    r"""|"""
    r"""request\.args\.get\s*\(['"]scope['"]"""
    r"""|"""
    r"""req\.query\.scope\b"""
    r"""|"""
    r"""body\[['"]scope['"]\]"""
)

_SCOPE_TOKEN_CREATE = _re(
    r"""create_token\s*\("""
    r"""|"""
    r"""signToken\s*\("""
    r"""|"""
    r"""jwt\.encode\s*\("""
    r"""|"""
    r"""createAccessToken\s*\("""
    r"""|"""
    r"""generate_token\s*\("""
    r"""|"""
    r"""issue_token\s*\("""
)

_SCOPE_SUBSET_GUARD = _re(
    # Must indicate active scope validation, not just a fallback assignment.
    # "grant.scope" alone is too broad — it also matches "req.body.scope || grant.scope".
    r"""scope\s+not\s+in\s+grant"""
    r"""|"""
    r"""if\s+scope\s+(?:not\s+)?in\s+grant"""
    r"""|"""
    r"""scope\s+in\s+grant\."""
    r"""|"""
    r"""isSubset\s*\("""
    r"""|"""
    r"""scope_is_subset"""
    r"""|"""
    r"""allowed_scopes"""
    r"""|"""
    r"""every\s*\(\s*s\s*=>"""
    r"""|"""
    r"""grant_scope\.split"""
)


# ---- RULES tuple (ordered, mirrors declaration order above) -------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="opkce-ropc-grant-type-used",
        name="OAuth ROPC grant type (grant_type=password) used — deprecated in OAuth 2.1",
        severity="HIGH",
        description=(
            "The Resource Owner Password Credentials (ROPC) grant passes "
            "the user's plaintext credentials to the application, which "
            "forwards them to the authorization server. RFC 9700 (OAuth 2.1 "
            "draft) removes ROPC entirely — it cannot support MFA, breaks "
            "the redirect-based user-agent separation guarantee, and exposes "
            "credentials to the client. Any production code sending "
            "grant_type=password to an OAuth token endpoint is implementing "
            "a deprecated, credential-harvesting-friendly flow. Keycloak's "
            "directAccessGrantsEnabled: true enables ROPC server-side. "
            "Replace with authorization code + PKCE."
        ),
        pattern=_ROPC_GRANT_TYPE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="opkce-implicit-flow-response-type-token",
        name="OAuth implicit grant (response_type=token) used — prohibited by RFC 9700",
        severity="HIGH",
        description=(
            "The OAuth implicit grant (response_type=token) returns the "
            "access token directly in the URL fragment, bypassing the "
            "authorization code exchange. RFC 9700 and the OAuth 2.0 Security "
            "BCP (RFC 9700 §2.1.2) prohibit response_type=token for new "
            "deployments. The token is exposed to browser history, the "
            "Referer header, and any JavaScript running on the redirect page. "
            "The only safe response type for modern public clients is "
            "response_type=code combined with PKCE. Config-level "
            "allowed_oauth_flows: implicit also enables this insecure flow."
        ),
        pattern=_IMPLICIT_RESPONSE_TYPE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="opkce-as-pkce-not-enforced-config",
        name="Authorization server config disables PKCE enforcement — code interception risk",
        severity="CRITICAL",
        description=(
            "Authorization server configuration explicitly disabling PKCE "
            "enforcement (Keycloak pkce.code.challenge.method empty, Auth0 "
            "enforce_pkce: false, Spring require-proof-key: false). An AS "
            "that does not require PKCE allows attackers to steal and replay "
            "authorization codes via referrer leakage or browser history, "
            "even when the legitimate client sends PKCE — because the AS "
            "never validates the code verifier. This is a server-side "
            "enforcement gap orthogonal to client-side PKCE omission."
        ),
        pattern=_AS_PKCE_KEYCLOAK_EMPTY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="opkce-authorization-code-no-single-use-server",
        name="Authorization code lookup without marking consumed — replay vulnerability",
        severity="HIGH",
        description=(
            "Server-side token endpoint performs an ORM or SQL lookup for "
            "an authorization code but never marks it consumed, deletes it, "
            "or sets used=True after the first exchange. RFC 6749 §4.1.2 "
            "requires authorization codes to be single-use and short-lived. "
            "A code intercepted via referrer or browser history can be "
            "replayed by an attacker to obtain a fresh access token. This "
            "is orthogonal to the browser-side history.replaceState rule "
            "(oauth-authorize-code-replay-no-history-clear)."
        ),
        pattern=_AUTH_CODE_ORM_LOOKUP,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="opkce-confidential-client-no-dpop-binding",
        name="Confidential client token request without DPoP sender-constraining",
        severity="MEDIUM",
        description=(
            "Confidential client (client_secret present) performs a token "
            "endpoint request for a high-value scope (payments, admin, "
            "transfer) without DPoP (RFC 9449) or mTLS sender-constraining. "
            "A stolen bearer token is usable by any holder without the "
            "corresponding private key. DPoP header or dpop_nonce must be "
            "present on the token request to bind the token to the requester's "
            "key pair. Use requireDPoP(true) on the authorization server or "
            "add the DPoP header to every token request."
        ),
        pattern=_CONFIDENTIAL_CLIENT_TOKEN_REQUEST,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="opkce-refresh-token-no-rotation-check-client",
        name="Refresh-token grant that drops server-issued new refresh token",
        severity="MEDIUM",
        description=(
            "Client-side code performs a grant_type=refresh_token token "
            "request but never captures and stores the new refresh_token "
            "returned by the server. OAuth 2.0 refresh token rotation "
            "requires the client to replace the old refresh token with "
            "the newly issued one on every exchange. Silently dropping the "
            "new token breaks rotation — a compromised old token remains "
            "valid for as long as the server keeps issuing new tokens to "
            "both the attacker and the legitimate client. Check "
            "data['refresh_token'] on every token response."
        ),
        pattern=_REFRESH_GRANT_ANCHOR,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="opkce-authorize-state-param-absent-web",
        name="OAuth authorization URL with response_type=code but no state= parameter",
        severity="HIGH",
        description=(
            "Authorization URL constructed with response_type=code but no "
            "state parameter — CSRF vulnerability. An attacker tricks the "
            "victim's browser into initiating an OAuth flow bound to the "
            "attacker's session, resulting in account takeover if the victim "
            "completes the flow (login-CSRF). This rule covers the web/SPA "
            "non-device-flow case. Orthogonal to the existing "
            "auth-oauth-state-reused-constant rule (which catches static "
            "literals) and oauth-authorize-state-missing-outbound (device "
            "flow). Generate state with crypto.randomUUID() or "
            "secrets.token_urlsafe(32)."
        ),
        pattern=_AUTHORIZE_RESPONSE_TYPE_CODE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="opkce-redirect-uri-open-redirect-runtime",
        name="OAuth redirect_uri constructed from user-controlled input — open redirect",
        severity="HIGH",
        description=(
            "OAuth redirect_uri built from user-controlled input "
            "(request.args, req.body, r.URL.Query) at runtime. If the "
            "authorization server validates only the scheme+host prefix, "
            "an attacker can supply a redirect_uri with a crafted path "
            "component that routes the authorization code to an "
            "attacker-controlled endpoint. Orthogonal to the existing "
            "auth-oauth-redirect-uri-wildcard rule (registered-URI "
            "wildcards). Validate that the resolved redirect_uri is an "
            "exact match against a registered allowlist before use."
        ),
        pattern=_REDIRECT_URI_USER_INPUT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="opkce-oidc-nonce-not-validated-server",
        name="OIDC ID token decoded with sub consumed but nonce not compared to session",
        severity="HIGH",
        description=(
            "Server-side code decodes an OIDC ID token and consumes the "
            "sub (subject) claim without comparing the token's nonce claim "
            "to the stored session nonce. Without this check, a stolen or "
            "replayed ID token from a different session is accepted and the "
            "user is logged in as the token's subject. Orthogonal to the "
            "client-side oidc-nonce-missing rule (which checks whether "
            "nonce is present in the authorization request URL). After "
            "jwt.decode / jwtVerify, always assert "
            "id_token['nonce'] == session['nonce']."
        ),
        pattern=_OIDC_TOKEN_DECODE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="opkce-token-scope-elevation-from-request",
        name="Token endpoint reads scope from request body instead of stored grant",
        severity="HIGH",
        description=(
            "Server-side token endpoint reads the scope value directly from "
            "the incoming request form/body (request.form.get('scope'), "
            "req.body.scope) and passes it to the token-creation function "
            "without validating it is a subset of the stored authorization "
            "grant's scopes. This allows scope elevation: an attacker "
            "interacting with the /token endpoint can request elevated "
            "scopes not consented to by the user. Always compare the "
            "requested scope against grant.scope and reject or downscope "
            "if it exceeds the original authorization."
        ),
        pattern=_SCOPE_FROM_REQUEST,
        owasp_asi="ASI-04",
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
    """Run every applicable RULES pattern against ``text`` and return findings.

    Stage-B filters consult adjacent lines for context:

      * P1 (ROPC code form) — fires on the grant_type=password literal;
        Keycloak config form fires on directAccessGrantsEnabled: true
        (separate pattern, both share the same rule id).
      * P2 (implicit flow) — code form fires on response_type=token;
        config form fires on allowed_oauth_flows[implicit.
      * P3 (AS PKCE config) — fires on three separate config patterns
        (Keycloak empty method, enforce_pkce=false, require-proof-key=false).
      * P4 (code single-use) — anchor on AuthorizationCode ORM lookup;
        suppressed if delete/used=True/consumed found in the forward 30-line
        window.
      * P5 (DPoP missing) — anchor on client_secret literal; suppressed
        unless a high-value scope keyword co-occurs in ±20 lines; then
        suppressed if any DPoP reference appears anywhere in the file.
      * P6 (refresh rotation) — anchor on grant_type=refresh_token;
        suppressed if a refresh-token capture/store pattern appears in the
        forward 50-line window.
      * P7 (state absent web) — anchor on response_type=code; suppressed
        if a state= assignment or state parameter appears in a 20-line
        bilateral window.
      * P8 (open redirect) — fires on redirect_uri + user-input source
        co-occurrence; template form also covered by a second pattern.
      * P9 (OIDC nonce) — anchor on jwt.decode / jwtVerify call; fires
        only if sub is consumed within 30 lines forward; suppressed if a
        nonce comparison appears in the same 40-line window.
      * P10 (scope elevation) — anchor on request-side scope read; fires
        only if a token-creation call appears within 30 lines; suppressed
        if a scope-subset guard appears in the same window.

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

    # ---- P1 : opkce-ropc-grant-type-used ----
    rule_p1 = rule_by_id["opkce-ropc-grant-type-used"]
    for m in _ROPC_GRANT_TYPE.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))
    for m in _ROPC_KEYCLOAK_CONFIG.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : opkce-implicit-flow-response-type-token ----
    rule_p2 = rule_by_id["opkce-implicit-flow-response-type-token"]
    for m in _IMPLICIT_RESPONSE_TYPE.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))
    for m in _IMPLICIT_FLOW_CONFIG.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : opkce-as-pkce-not-enforced-config ----
    rule_p3 = rule_by_id["opkce-as-pkce-not-enforced-config"]
    for m in _AS_PKCE_KEYCLOAK_EMPTY.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))
    for m in _AS_PKCE_ENFORCE_FALSE.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))
    for m in _AS_PKCE_SPRING_FALSE.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : opkce-authorization-code-no-single-use-server ----
    rule_p4 = rule_by_id["opkce-authorization-code-no-single-use-server"]
    for m in _AUTH_CODE_ORM_LOOKUP.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 30)
        if _AUTH_CODE_SINGLE_USE_GUARD.search(window) is not None:
            continue
        _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : opkce-confidential-client-no-dpop-binding ----
    rule_p5 = rule_by_id["opkce-confidential-client-no-dpop-binding"]
    for m in _CONFIDENTIAL_CLIENT_TOKEN_REQUEST.finditer(text):
        line, _ = _line_col(text, m.start())
        # Must co-occur with a high-value scope within ±20 lines.
        window = _slice_window(text, line, 20, 20)
        if _HIGH_VALUE_SCOPE.search(window) is None:
            continue
        # Suppressed if any DPoP reference is present anywhere in the file.
        if _file_contains(text, _DPOP_GUARD):
            continue
        _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : opkce-refresh-token-no-rotation-check-client ----
    rule_p6 = rule_by_id["opkce-refresh-token-no-rotation-check-client"]
    for m in _REFRESH_GRANT_ANCHOR.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 50)
        if _REFRESH_ROTATION_GUARD.search(window) is not None:
            continue
        _emit(rule_p6, m.start(), m.group(0))

    # ---- P7 : opkce-authorize-state-param-absent-web ----
    rule_p7 = rule_by_id["opkce-authorize-state-param-absent-web"]
    for m in _AUTHORIZE_RESPONSE_TYPE_CODE.finditer(text):
        line, _ = _line_col(text, m.start())
        # 10-line bilateral window — state may be set before or after.
        window = _slice_window(text, line, 10, 20)
        if _STATE_PARAM_GUARD.search(window) is not None:
            continue
        _emit(rule_p7, m.start(), m.group(0))

    # ---- P8 : opkce-redirect-uri-open-redirect-runtime ----
    rule_p8 = rule_by_id["opkce-redirect-uri-open-redirect-runtime"]
    for m in _REDIRECT_URI_USER_INPUT.finditer(text):
        _emit(rule_p8, m.start(), m.group(0))
    for m in _REDIRECT_URI_TEMPLATE_USER_INPUT.finditer(text):
        _emit(rule_p8, m.start(), m.group(0))

    # ---- P9 : opkce-oidc-nonce-not-validated-server ----
    rule_p9 = rule_by_id["opkce-oidc-nonce-not-validated-server"]
    for m in _OIDC_TOKEN_DECODE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Must see sub consumed within 30 lines forward.
        fwd_window = _slice_forward(text, line, 30)
        if _OIDC_SUB_CONSUMED.search(fwd_window) is None:
            continue
        # Suppressed if nonce validation appears in the 40-line bilateral window.
        full_window = _slice_window(text, line, 5, 40)
        if _OIDC_NONCE_VALIDATED.search(full_window) is not None:
            continue
        _emit(rule_p9, m.start(), m.group(0))

    # ---- P10 : opkce-token-scope-elevation-from-request ----
    rule_p10 = rule_by_id["opkce-token-scope-elevation-from-request"]
    for m in _SCOPE_FROM_REQUEST.finditer(text):
        line, _ = _line_col(text, m.start())
        # Must co-occur with a token-creation call within 30 lines.
        window = _slice_forward(text, line, 30)
        if _SCOPE_TOKEN_CREATE.search(window) is None:
            continue
        # Suppressed if a scope-subset guard appears in the same window.
        if _SCOPE_SUBSET_GUARD.search(window) is not None:
            continue
        _emit(rule_p10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
