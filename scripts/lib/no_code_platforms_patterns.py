"""No-code / low-code platform anti-patterns.

Wave-30 distillation round 16.

Catalogue of 15 no-code-platform-specific anti-patterns distilled from
`reports/distill-round-16/no-code-platforms.md`. Targets Bubble, Webflow,
Retool, Zapier, Make (Integromat), n8n, and Airtable surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic outbound webhook without allowlist —
    `dns_email_patterns.py` rule 5.
  * Webhook HMAC / signature bypass —
    `webhook_signature_patterns.py`.
  * OAuth device-flow — `oauth_device_flow_patterns.py`.
  * LLM prompt injection via user-supplied text —
    `ai_jailbreak_patterns.py`.
  * Credential literals (API keys, tokens) —
    `credential_lifecycle_patterns.py`.

What IS here (15 net-new rules, regex-only, all RE2-safe):

  * no-code-bubble-unsafe-data-api-public              (CRITICAL)
  * no-code-bubble-client-side-condition-only-privacy  (HIGH)
  * no-code-webflow-custom-code-unescaped-cms-field    (HIGH)
  * no-code-webflow-designer-api-key-in-frontend       (CRITICAL)
  * no-code-retool-resource-cred-in-query              (CRITICAL)
  * no-code-retool-js-eval-user-input                  (HIGH)
  * no-code-zapier-webhook-no-secret                   (MEDIUM)
  * no-code-zapier-action-http-plaintext-secret        (HIGH)
  * no-code-make-webhook-no-ip-restriction             (MEDIUM)
  * no-code-make-http-module-basic-auth-hardcoded      (HIGH)
  * no-code-n8n-expression-os-exec                     (CRITICAL)
  * no-code-n8n-credential-exposed-in-node-output      (HIGH)
  * no-code-airtable-personal-access-token-committed   (CRITICAL)
  * no-code-airtable-base-writable-formula-injection   (HIGH)
  * no-code-platform-oauth-redirect-open               (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (API key / PAT / credential committed or logged)
  ASI-04 — Information leak (credential in query output, node output)
  ASI-05 — Supply-chain / injection (CMS field injection, exec injection)
  ASI-07 — Authority / authorisation gaps (public data API, client-side
            privacy, open redirect, webhook without validation)

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


# ---- N1 : no-code-bubble-unsafe-data-api-public -------------------------
# Bubble's Data API exposes all database types by default; enabling it
# without privacy rules set makes the entire table public.
_BUBBLE_DATA_API_PUBLIC = _re(
    r"\benable_data_api\s*[=:]\s*(?:true|1|yes)"
    r"|data[_\-]api[_\-]enabled\s*[=:]\s*(?:true|1|yes)"
    r"|bubble[_\-]data[_\-]api\s*[=:]\s*(?:true|1|yes)"
)

# ---- N2 : no-code-bubble-client-side-condition-only-privacy -------------
# Bubble "When" / "Only when" conditions are purely client-side; they can
# be bypassed via direct API calls. Server-side privacy rules are required.
_BUBBLE_CLIENT_CONDITION_ONLY = _re(
    r"\b(?:only.when.condition|when.condition|client.side.condition)\b"
    r".{0,80}(?:data.visible|show.data|hide.data|restrict.data)"
)

# ---- N3 : no-code-webflow-custom-code-unescaped-cms-field ---------------
# Webflow "Embed" code blocks that interpolate CMS/collection fields
# directly into innerHTML or document.write without escaping.
_WEBFLOW_UNESCAPED_CMS = _re(
    r"\.innerHTML\s*[+]?=\s*[^;]*\bwf_cms\b"
    r"|document\.write\s*\([^)]*\bwf_cms\b"
    r"|innerHTML\s*[+]?=\s*['\"`][^'\"`;]*\{\{[^}]+\}\}"
    r"|\.innerHTML\s*[+]?=\s*['\"`][^'\"`;]*\bfield\b"
)

# ---- N4 : no-code-webflow-designer-api-key-in-frontend ------------------
# Webflow Designer API keys embedded in client-side <script> tags or JS
# bundles give full site write access from the browser.
_WEBFLOW_API_KEY_FRONTEND = _re(
    r"\bwf(?:_|-)?api(?:_|-)?(?:key|token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{20,80}['\"]"
    r"|\bX-Webflow-Api-Token\b[^A-Za-z0-9]"
    r"|\bwebflow(?:_|-)?(?:secret|api_key|token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{20,80}['\"]"
)

# ---- N5 : no-code-retool-resource-cred-in-query -------------------------
# Retool query editors allow inline credential strings; these get saved in
# the app JSON and shared with anyone who can view/edit the app.
_RETOOL_CRED_IN_QUERY = _re(
    r"\b(?:password|passwd|secret|api_key|apikey|access_key)\s*[=:]\s*['\"][^'\"]{6,}['\"]"
    r"\s*(?://|#|/\*)?.*\b(?:retool|query|resource)\b"
    r"|\bretool(?:_|-)?resource\b.*(?:password|secret|api_key)\s*[=:]\s*['\"][^'\"]{6,}['\"]"
)

# ---- N6 : no-code-retool-js-eval-user-input -----------------------------
# Retool JavaScript query transformers that pass user-supplied values into
# eval(), Function(), or setTimeout/setInterval with a string argument.
_RETOOL_JS_EVAL_INPUT = _re(
    r"\beval\s*\(\s*(?:.*?)\b(?:input|textInput|selectInput|query\.data"
    r"|widget\.value|currentUser)\b"
    r"|\bnew\s+Function\s*\([^)]*\b(?:input|textInput|widget\.value)\b"
    r"|\bsetTimeout\s*\(\s*['\"`][^'\"`;]*\b(?:input|textInput)\b"
)

# ---- N7 : no-code-zapier-webhook-no-secret ------------------------------
# Zapier "Catch Hook" steps configured without a secret parameter expose a
# publicly-reachable URL that any actor can trigger.
_ZAPIER_WEBHOOK_NO_SECRET = _re(
    r"\bCatch\s+Hook\b(?:(?!\bsecret\b).){0,300}\burl\s*[=:]\s*['\"]https://hooks\.zapier\.com"
    r"|\bhooks\.zapier\.com/hooks/catch/\d{5,12}/[A-Za-z0-9]{8,20}/"
    r"(?!.*\bsecret\b)"
)

# ---- N8 : no-code-zapier-action-http-plaintext-secret -------------------
# Zapier "Webhooks by Zapier" or custom HTTP actions that include
# Authorization / API-key headers with literal secret values.
_ZAPIER_HTTP_PLAINTEXT_SECRET = _re(
    r"\bAuthorization\s*[=:]\s*['\"](?:Bearer|Basic|Token|ApiKey)\s+[A-Za-z0-9+/=_\-]{16,}['\"]"
    r"|\bapi[_\-]?key\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
    r"|\bX-Api-Key\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
)

# ---- N9 : no-code-make-webhook-no-ip-restriction ------------------------
# Make (Integromat) Custom Webhook modules without IP-address filtering
# accept requests from any origin.
_MAKE_WEBHOOK_NO_IP = _re(
    r"\bmake(?:\.com)?[_\-]webhook\b(?:(?!\bip\b|\brestrict\b|\ballow\b).){0,200}\burl\b"
    r"|\bhook\.(?:integromat|make)\.com/[A-Za-z0-9/_\-]{8,}"
    r"(?:(?!\bip_restriction\b|\bwhitelist\b|\ballowlist\b).){0,300}$"
)

# ---- N10 : no-code-make-http-module-basic-auth-hardcoded ----------------
# Make "HTTP" module connection settings with hardcoded Basic-auth
# credentials stored in the scenario JSON.
_MAKE_HTTP_BASIC_AUTH = _re(
    r"\bbasic[_\-]?auth\s*[=:]\s*['\"][^'\"]{4,}['\"]"
    r"|\bHTTP\b.*\bBasic\b[^'\"\n]{0,30}[A-Za-z0-9+/=]{8,}"
    r"|\bpassword\s*[=:]\s*['\"][^'\"]{4,}['\"].*\bHTTP\b"
)

# ---- N11 : no-code-n8n-expression-os-exec ------------------------------
# n8n "Function" / "Code" nodes that call child_process.exec(),
# execSync(), or spawn() with a value sourced from workflow input.
_N8N_EXPRESSION_OS_EXEC = _re(
    r"\b(?:exec|execSync|spawn|spawnSync)\s*\(\s*(?:[^)]*\$json\b"
    r"|[^)]*\$node\b|[^)]*\$input\b|[^)]*\$workflow\b)"
    r"|\bchild_process\b.*\b(?:exec|spawn)\b.*\$(?:json|node|input|workflow)\b"
)

# ---- N12 : no-code-n8n-credential-exposed-in-node-output ---------------
# n8n "Set" nodes that copy a credential item directly into the output
# data, making it visible in execution logs and downstream nodes.
_N8N_CRED_IN_OUTPUT = _re(
    r"\$credentials\.[A-Za-z0-9_]+\s*[,}]"
    r"|\bSet\b.*\bvalue\s*[=:]\s*['\"]?\s*\$credentials\b"
    r"|\breturn\s*\{[^}]*\$credentials\.[A-Za-z0-9_]+"
)

# ---- N13 : no-code-airtable-personal-access-token-committed -------------
# Airtable Personal Access Tokens (PATs) have a fixed prefix; committing
# them exposes full base read/write access.
_AIRTABLE_PAT_COMMITTED = _re(
    r"\bpat[A-Za-z0-9]{14,18}\.[A-Za-z0-9]{64,}\b"
    r"|\bairtable[_\-](?:api[_\-]?key|pat|token)\s*[=:]\s*['\"][A-Za-z0-9_.]{30,}['\"]"
    r"|\bATAP[A-Za-z0-9]{10,}\.[A-Za-z0-9]{60,}\b"
)

# ---- N14 : no-code-airtable-base-writable-formula-injection -------------
# Airtable formula fields that concatenate user-supplied values without
# sanitisation allow formula injection (e.g., RECORD_ID() exfil).
_AIRTABLE_FORMULA_INJECTION = _re(
    r"filterByFormula\s*[=:][^\n]*(?:\+|\|\||%2B)[^\n]*(?:req\.|request\.|user\.|input\.|body\.|query\.|param\.)"
    r"|filterByFormula\s*[=:]\s*`[^`]*\$\{[^}]*(?:req|request|user|input|body|query|param)\b"
    r"|formula\s*[=:]\s*['\"`][^'\"`;]*(?:\+|\|\|)[^'\"`;]*(?:req\.|body\.|query\.|param\.)"
)

# ---- N15 : no-code-platform-oauth-redirect-open -------------------------
# No-code platform OAuth integrations that pass the redirect_uri from a
# user-controlled query parameter without validating against a registered
# allowlist, enabling open-redirect attacks to steal auth codes.
_OAUTH_REDIRECT_OPEN = _re(
    r"\bredirect_uri\s*[=:]\s*(?:req\.query|req\.body|request\.GET|request\.POST"
    r"|params\[|query\[|ctx\.query|event\.queryStringParameters)\b"
    r"|\bredirect_uri\s*[=:]\s*['\"`][^'\"`;]*(?:\$\{|%s|%v|\+\s*)"
    r"(?:req|request|query|body|param|args)\b"
)


# ---- Rule catalogue -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="no-code-bubble-unsafe-data-api-public",
        name="Bubble Data API enabled without server-side privacy rules",
        severity="CRITICAL",
        description=(
            "Bubble's Data API exposes all database types publicly when "
            "enabled. Without server-side privacy rules configured in the "
            "Privacy tab, every record in the exposed type is readable and "
            "writable by unauthenticated callers via the REST endpoint "
            "`/api/1.1/obj/<type>`. Enabling the Data API must always be "
            "paired with Privacy rules on every type before deployment."
        ),
        pattern=_BUBBLE_DATA_API_PUBLIC,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="no-code-bubble-client-side-condition-only-privacy",
        name="Bubble data visibility controlled only by client-side conditions",
        severity="HIGH",
        description=(
            "Bubble 'Only when' / 'When condition' visibility guards are "
            "purely client-side UI logic; direct API calls bypass them "
            "entirely. Sensitive data that should be restricted must use "
            "server-side Privacy rules — not frontend conditionals."
        ),
        pattern=_BUBBLE_CLIENT_CONDITION_ONLY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="no-code-webflow-custom-code-unescaped-cms-field",
        name="Webflow Embed block writes CMS field to innerHTML without escaping",
        severity="HIGH",
        description=(
            "Webflow custom-code Embed blocks that interpolate CMS / "
            "collection field values directly into `innerHTML` or "
            "`document.write` introduce a stored XSS vector. CMS content "
            "edited by any CMS Editor user is attacker-controlled; the "
            "value must be escaped (textContent, DOMParser, or a sanitizer "
            "such as DOMPurify) before insertion."
        ),
        pattern=_WEBFLOW_UNESCAPED_CMS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="no-code-webflow-designer-api-key-in-frontend",
        name="Webflow Designer API key embedded in client-side code",
        severity="CRITICAL",
        description=(
            "Webflow Designer API tokens grant full read/write access to "
            "site structure, CMS content, and asset publishing. Embedding "
            "them in client-side `<script>` tags or JS bundles exposes them "
            "to every site visitor via browser devtools. API calls that "
            "require a Designer token must be proxied through a server-side "
            "function with the key stored in an environment variable."
        ),
        pattern=_WEBFLOW_API_KEY_FRONTEND,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="no-code-retool-resource-cred-in-query",
        name="Retool query contains hardcoded resource credential",
        severity="CRITICAL",
        description=(
            "Retool query definitions that include literal password, secret, "
            "or API-key strings are saved in the application JSON and visible "
            "to any user with edit or view access to the app. Credentials "
            "must be stored in Retool Resource configuration (encrypted at "
            "rest), not in query body text."
        ),
        pattern=_RETOOL_CRED_IN_QUERY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="no-code-retool-js-eval-user-input",
        name="Retool JavaScript transformer passes user input to eval()",
        severity="HIGH",
        description=(
            "Retool JavaScript query transformers or Custom Components that "
            "pass values from `input.*`, `textInput.value`, `widget.value`, "
            "or `query.data` into `eval()`, `new Function()`, or a string "
            "argument to `setTimeout`/`setInterval` allow arbitrary code "
            "execution in the Retool iframe sandbox. User-controlled data "
            "must never be evaluated as code."
        ),
        pattern=_RETOOL_JS_EVAL_INPUT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="no-code-zapier-webhook-no-secret",
        name="Zapier Catch Hook URL exposed without a secret parameter",
        severity="MEDIUM",
        description=(
            "A Zapier 'Catch Hook' trigger URL without a secret query "
            "parameter is publicly reachable; any actor who discovers the "
            "URL can trigger the Zap with arbitrary payloads. Add a secret "
            "parameter and validate it in the first step of the Zap, or use "
            "the built-in Zapier webhook secret field."
        ),
        pattern=_ZAPIER_WEBHOOK_NO_SECRET,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="no-code-zapier-action-http-plaintext-secret",
        name="Zapier HTTP action stores Authorization header with plaintext secret",
        severity="HIGH",
        description=(
            "Zapier 'Webhooks by Zapier' or custom HTTP action steps that "
            "embed literal API keys or Bearer tokens in the Authorization or "
            "X-Api-Key header store those secrets in the Zap definition, "
            "which is accessible to any Zapier account member. Use Zapier "
            "Storage or an App authentication layer instead of inline "
            "plaintext secrets."
        ),
        pattern=_ZAPIER_HTTP_PLAINTEXT_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="no-code-make-webhook-no-ip-restriction",
        name="Make Custom Webhook module has no IP-address restriction",
        severity="MEDIUM",
        description=(
            "Make (Integromat) Custom Webhook modules that do not configure "
            "an IP address restriction accept trigger requests from any "
            "source on the internet. Enable 'IP restrictions' in the webhook "
            "settings, or add a Data Store / Router step that validates the "
            "source IP / a shared secret before processing the payload."
        ),
        pattern=_MAKE_WEBHOOK_NO_IP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="no-code-make-http-module-basic-auth-hardcoded",
        name="Make HTTP module Basic-auth credentials hardcoded in scenario JSON",
        severity="HIGH",
        description=(
            "Make 'HTTP - Make a request' module configurations that embed "
            "Basic-auth username:password or a pre-encoded Base64 credential "
            "directly in the scenario JSON expose those credentials to anyone "
            "with Scenario view/edit access. Use a dedicated Make Connection "
            "with the credential stored in the encrypted Connection store."
        ),
        pattern=_MAKE_HTTP_BASIC_AUTH,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="no-code-n8n-expression-os-exec",
        name="n8n Code node executes OS command built from workflow input",
        severity="CRITICAL",
        description=(
            "n8n 'Function' or 'Code' nodes that call `child_process.exec()`, "
            "`execSync()`, `spawn()`, or `spawnSync()` with a string derived "
            "from `$json`, `$node`, `$input`, or `$workflow` allow workflow "
            "input to execute arbitrary OS commands on the n8n server host. "
            "Never construct shell commands from untrusted data; use "
            "parameterised APIs or sandboxed computation instead."
        ),
        pattern=_N8N_EXPRESSION_OS_EXEC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="no-code-n8n-credential-exposed-in-node-output",
        name="n8n Set node copies credential value into node output data",
        severity="HIGH",
        description=(
            "n8n 'Set' or 'Function' nodes that reference `$credentials.*` "
            "and include the value in the returned output object expose "
            "credential values in execution logs and to all downstream nodes. "
            "Credentials should only be used in HTTP header / authentication "
            "fields of compatible nodes; never forwarded as data items."
        ),
        pattern=_N8N_CRED_IN_OUTPUT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="no-code-airtable-personal-access-token-committed",
        name="Airtable Personal Access Token literal committed to source",
        severity="CRITICAL",
        description=(
            "Airtable Personal Access Tokens (PATs) follow a fixed prefix "
            "pattern (`pat…` with a 64-character secret) and grant full "
            "read/write access to all bases the owning user can access. "
            "Committing a PAT to source code or configuration files exposes "
            "it to anyone with repository access. Store PATs in environment "
            "variables or a secrets manager and rotate immediately on "
            "detection."
        ),
        pattern=_AIRTABLE_PAT_COMMITTED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="no-code-airtable-base-writable-formula-injection",
        name="Airtable filterByFormula built from user-supplied input",
        severity="HIGH",
        description=(
            "Airtable API queries that construct `filterByFormula` strings "
            "by concatenating or interpolating user-supplied values (request "
            "parameters, body fields) without sanitisation are vulnerable to "
            "formula injection. An attacker can craft formulas that leak "
            "fields from other records (e.g., `RECORD_ID()`, `{SecretField}`) "
            "or enumerate all records regardless of intended filters. Use "
            "parameterised server-side logic to build formulae."
        ),
        pattern=_AIRTABLE_FORMULA_INJECTION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="no-code-platform-oauth-redirect-open",
        name="No-code platform OAuth redirect_uri taken from unvalidated user input",
        severity="HIGH",
        description=(
            "OAuth integrations in no-code platforms (Bubble, Webflow, "
            "Retool, Zapier, Make, n8n) that pass `redirect_uri` directly "
            "from a user-controlled query parameter or body field without "
            "validating against a pre-registered allowlist enable open "
            "redirect attacks: an attacker supplies their own URI to steal "
            "the authorization code and exchange it for tokens. The "
            "`redirect_uri` must be derived from an allowlist, not from "
            "request input."
        ),
        pattern=_OAUTH_REDIRECT_OPEN,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    All 15 rules use single-pass regex matching. Findings are deduped by
    (rule_id, line, col) and returned in (line, col, rule_id) order.
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

    # N1 : bubble-unsafe-data-api-public
    rule_n1 = rule_by_id["no-code-bubble-unsafe-data-api-public"]
    for m in _BUBBLE_DATA_API_PUBLIC.finditer(text):
        _emit(rule_n1, m.start(), m.group(0))

    # N2 : bubble-client-side-condition-only-privacy
    rule_n2 = rule_by_id["no-code-bubble-client-side-condition-only-privacy"]
    for m in _BUBBLE_CLIENT_CONDITION_ONLY.finditer(text):
        _emit(rule_n2, m.start(), m.group(0))

    # N3 : webflow-custom-code-unescaped-cms-field
    rule_n3 = rule_by_id["no-code-webflow-custom-code-unescaped-cms-field"]
    for m in _WEBFLOW_UNESCAPED_CMS.finditer(text):
        _emit(rule_n3, m.start(), m.group(0))

    # N4 : webflow-designer-api-key-in-frontend
    rule_n4 = rule_by_id["no-code-webflow-designer-api-key-in-frontend"]
    for m in _WEBFLOW_API_KEY_FRONTEND.finditer(text):
        _emit(rule_n4, m.start(), m.group(0))

    # N5 : retool-resource-cred-in-query
    rule_n5 = rule_by_id["no-code-retool-resource-cred-in-query"]
    for m in _RETOOL_CRED_IN_QUERY.finditer(text):
        _emit(rule_n5, m.start(), m.group(0))

    # N6 : retool-js-eval-user-input
    rule_n6 = rule_by_id["no-code-retool-js-eval-user-input"]
    for m in _RETOOL_JS_EVAL_INPUT.finditer(text):
        _emit(rule_n6, m.start(), m.group(0))

    # N7 : zapier-webhook-no-secret
    rule_n7 = rule_by_id["no-code-zapier-webhook-no-secret"]
    for m in _ZAPIER_WEBHOOK_NO_SECRET.finditer(text):
        _emit(rule_n7, m.start(), m.group(0))

    # N8 : zapier-action-http-plaintext-secret
    rule_n8 = rule_by_id["no-code-zapier-action-http-plaintext-secret"]
    for m in _ZAPIER_HTTP_PLAINTEXT_SECRET.finditer(text):
        _emit(rule_n8, m.start(), m.group(0))

    # N9 : make-webhook-no-ip-restriction
    rule_n9 = rule_by_id["no-code-make-webhook-no-ip-restriction"]
    for m in _MAKE_WEBHOOK_NO_IP.finditer(text):
        _emit(rule_n9, m.start(), m.group(0))

    # N10 : make-http-module-basic-auth-hardcoded
    rule_n10 = rule_by_id["no-code-make-http-module-basic-auth-hardcoded"]
    for m in _MAKE_HTTP_BASIC_AUTH.finditer(text):
        _emit(rule_n10, m.start(), m.group(0))

    # N11 : n8n-expression-os-exec
    rule_n11 = rule_by_id["no-code-n8n-expression-os-exec"]
    for m in _N8N_EXPRESSION_OS_EXEC.finditer(text):
        _emit(rule_n11, m.start(), m.group(0))

    # N12 : n8n-credential-exposed-in-node-output
    rule_n12 = rule_by_id["no-code-n8n-credential-exposed-in-node-output"]
    for m in _N8N_CRED_IN_OUTPUT.finditer(text):
        _emit(rule_n12, m.start(), m.group(0))

    # N13 : airtable-personal-access-token-committed
    rule_n13 = rule_by_id["no-code-airtable-personal-access-token-committed"]
    for m in _AIRTABLE_PAT_COMMITTED.finditer(text):
        _emit(rule_n13, m.start(), m.group(0))

    # N14 : airtable-base-writable-formula-injection
    rule_n14 = rule_by_id["no-code-airtable-base-writable-formula-injection"]
    for m in _AIRTABLE_FORMULA_INJECTION.finditer(text):
        _emit(rule_n14, m.start(), m.group(0))

    # N15 : platform-oauth-redirect-open
    rule_n15 = rule_by_id["no-code-platform-oauth-redirect-open"]
    for m in _OAUTH_REDIRECT_OPEN.finditer(text):
        _emit(rule_n15, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
