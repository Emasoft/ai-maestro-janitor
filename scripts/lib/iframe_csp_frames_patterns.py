"""Iframe sandbox / CSP frame-ancestors / X-Frame-Options security patterns.

Wave-29 distillation round 15, angle: iframe/CSP frame-ancestors.

Catalogue of 7 iframe-embedding and CSP anti-patterns distilled in
`reports/distill-round-15/iframe-csp-frames.md`. Targets clickjacking,
sandbox escape, postMessage injection, user-controlled iframe src/srcdoc,
overly broad Permissions-Policy delegation, and frame-ancestors delivered
via meta (silently ignored).

What is NOT here (already shipped — DO NOT duplicate):

  * CORS null-origin sandbox iframe trick (attacker sends `Origin: null`
    from sandboxed iframe to bypass CORS allowlists) —
    `cors_misconfig_patterns.py`.
  * Generic HTTP security header presence/absence audit (X-Frame-Options
    in the abstract header-hygiene sense) — `http_header_patterns.py`.
  * General browser cookie security — `browser_cookies_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * iframe-csp-missing-frame-ancestors-and-xfo                (HIGH)
  * iframe-csp-sandbox-scripts-same-origin-combo              (HIGH)
  * iframe-csp-postmessage-no-origin-check                    (CRITICAL)
  * iframe-csp-user-controlled-src                            (HIGH)
  * iframe-csp-srcdoc-user-html                               (HIGH)
  * iframe-csp-allow-sensitive-permissions                     (MEDIUM)
  * iframe-csp-frame-ancestors-in-meta-tag                    (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Information leak / UI redress (clickjacking, content injection,
            open redirector enabling phishing via user-controlled src)
  ASI-05 — Supply-chain / cross-tenant pivot (overly broad Permissions-
            Policy delegation grants third-party frames sensitive APIs)
  ASI-06 — Injection (srcdoc user-HTML injection, postMessage XSS via
            unvalidated origin, sandbox escape enabling same-origin access)
  ASI-08 — Security misconfiguration (missing frame-ancestors + XFO,
            frame-ancestors in meta CSP silently ignored by browsers)

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


# ---- IF-001 : Missing frame-ancestors + absent X-Frame-Options ----------

# Positive signal A: X-Frame-Options set to ALLOWALL or ALLOW-FROM * (effectively absent).
_XFO_ALLOWALL = _re(
    r"""X-Frame-Options[\s'":\,]+(?:ALLOWALL|ALLOW-FROM\s+\*)"""
)

# Positive signal B: Helmet frameguard explicitly disabled in Node/Express config.
_FRAMEGUARD_DISABLED = _re(
    r"""frameguard\s*:\s*false"""
)

# ---- IF-002 : sandbox="allow-scripts allow-same-origin" combo -----------

# Dangerous combination: both allow-scripts and allow-same-origin in any order.
# Two patterns cover both orderings (allow-scripts first, allow-same-origin first).
_SANDBOX_SCRIPTS_THEN_SAME_ORIGIN = _re(
    r"""sandbox\s*=\s*["'][^"']*allow-scripts[^"']*allow-same-origin[^"']*["']"""
)

_SANDBOX_SAME_ORIGIN_THEN_SCRIPTS = _re(
    r"""sandbox\s*=\s*["'][^"']*allow-same-origin[^"']*allow-scripts[^"']*["']"""
)

# ---- IF-003 : postMessage handler without event.origin check ------------

# Insecure pattern A: substring origin check (known bypass).
_POSTMESSAGE_ORIGIN_INCLUDES = _re(
    r"""(?:event|e)\.origin\.includes\s*\("""
)

# Insecure pattern B: postMessage sent to wildcard target origin.
_POSTMESSAGE_WILDCARD_TARGET = _re(
    r"""\.postMessage\s*\([^,)]+,\s*["']\*["']\s*\)"""
)

# ---- IF-004 : user-controlled iframe src --------------------------------

# JSX/HTML: iframe src bound to a JS expression (variable, not string literal).
_IFRAME_SRC_EXPRESSION = _re(
    r"""<iframe[^>]*\bsrc\s*=\s*\{[^}"']{1,200}\}"""
)

# Template / Jinja2 / Django: iframe src with variable interpolation.
_IFRAME_SRC_TEMPLATE = _re(
    r"""<iframe[^>]*\bsrc\s*=\s*["'][^"']*\{\{[^}]{1,100}\}\}[^"']*["']"""
)

# DOM: frame.src assigned from common user-input source functions.
_IFRAME_SRC_DOM_USERINPUT = _re(
    r"""(?:iframe|frame)\b[^;\n]{0,80}\.src\s*=\s*(?:getParam|getParameter|req\.(?:query|params)|"""
    r"""route\.query|searchParams\.get|location\.(?:search|hash)|"""
    r"""params\.get|URLSearchParams)[^;\n]{0,60}"""
)

# ---- IF-005 : srcdoc populated from user-controlled HTML ----------------

# HTML/template: srcdoc bound to a template variable (JSX expression or template literal).
_SRCDOC_EXPRESSION = _re(
    r"""<iframe[^>]*\bsrcdoc\s*=\s*\{[^}"']{1,200}\}"""
)

# Jinja2 / Django / server-side template: srcdoc with {{ }} interpolation.
_SRCDOC_TEMPLATE = _re(
    r"""<iframe[^>]*\bsrcdoc\s*=\s*["'][^"']*\{\{[^}]{1,100}\}\}[^"']*["']"""
)

# Python f-string / format string building srcdoc from variable.
# Optional string prefix (f/b/r/u) before the quote delimiter.
_SRCDOC_PYTHON_FORMAT = _re(
    r"""srcdoc\s*=\s*[fFbBrRuU]?["']{1,3}[^"']*\{[A-Za-z_][^}]{0,60}\}[^"']*["']{1,3}"""
)

# ---- IF-006 : overly broad Permissions-Policy delegation ----------------

# Wildcard allow attribute on iframe.
_IFRAME_ALLOW_WILDCARD = _re(
    r"""<iframe[^>]*\ballow\s*=\s*["']\*["']"""
)

# allow attribute containing payment together with camera, microphone, geolocation, or display-capture.
_IFRAME_ALLOW_PAYMENT_SENSITIVE = _re(
    r"""<iframe[^>]*\ballow\s*=\s*["'][^"']*\bpayment\b[^"']*"""
    r"""\b(?:camera|microphone|geolocation|display-capture)\b[^"']*["']"""
)

# ---- IF-007 : frame-ancestors in meta CSP (silently ignored) ------------

# Meta tag delivering CSP that includes frame-ancestors (http-equiv first).
# Use [^>]* for the content value span so single quotes inside a double-quoted
# attribute do not prematurely stop the match (stops at tag close '>' instead).
_META_CSP_FRAME_ANCESTORS_A = _re(
    r"""<meta[^>]*http-equiv\s*=\s*["']Content-Security-Policy["'][^>]*"""
    r"""content\s*=\s*["'][^>]*frame-ancestors[^>]*["']"""
)

# Commutative form: content attribute before http-equiv.
_META_CSP_FRAME_ANCESTORS_B = _re(
    r"""<meta[^>]*content\s*=\s*["'][^>]*frame-ancestors[^>]*["'][^>]*"""
    r"""http-equiv\s*=\s*["']Content-Security-Policy["']"""
)

# React/JSX: httpEquiv prop form.
_META_CSP_FRAME_ANCESTORS_JSX = _re(
    r"""httpEquiv\s*=\s*["']Content-Security-Policy["'][^>]*"""
    r"""content\s*=\s*["'][^>]*frame-ancestors[^>]*["']"""
)


# ---- Rule catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="iframe-csp-missing-frame-ancestors-and-xfo",
        name="X-Frame-Options set to permissive value or Helmet frameguard disabled (clickjacking exposure)",
        severity="HIGH",
        description=(
            "Either `X-Frame-Options` is explicitly set to ALLOWALL / "
            "ALLOW-FROM * (effectively disabling clickjacking protection) "
            "or the Helmet `frameguard` middleware is explicitly set to "
            "`false`. Without a restrictive X-Frame-Options or CSP "
            "`frame-ancestors` directive, any third-party origin can embed "
            "the page in an <iframe> and perform clickjacking attacks. "
            "Verify that both defenses are not simultaneously absent or "
            "disabled before accepting this as a true finding."
        ),
        pattern=_XFO_ALLOWALL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="iframe-csp-frameguard-disabled",
        name="Helmet frameguard middleware explicitly disabled (clickjacking)",
        severity="HIGH",
        description=(
            "The Express/Helmet `frameguard` option is set to `false`, "
            "explicitly removing the X-Frame-Options header that Helmet "
            "would otherwise inject. Combined with absence of a CSP "
            "`frame-ancestors` directive this leaves the application "
            "vulnerable to clickjacking. "
            "Helmet's frameguard defaults to `SAMEORIGIN`; disabling it "
            "is almost always a mistake."
        ),
        pattern=_FRAMEGUARD_DISABLED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="iframe-csp-sandbox-scripts-same-origin-combo",
        name="iframe sandbox combines allow-scripts and allow-same-origin (sandbox escape)",
        severity="HIGH",
        description=(
            "The HTML `sandbox` attribute contains both `allow-scripts` "
            "and `allow-same-origin`. This combination defeats the "
            "sandbox: `allow-same-origin` lets the frame access the "
            "parent's cookies and DOM (when sharing the same origin), "
            "and `allow-scripts` provides the JavaScript to do so. An "
            "attacker who can influence the iframe `src` or `srcdoc` can "
            "escape the sandbox and access the parent document."
        ),
        pattern=_SANDBOX_SCRIPTS_THEN_SAME_ORIGIN,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iframe-csp-sandbox-same-origin-scripts-combo",
        name="iframe sandbox combines allow-same-origin and allow-scripts (sandbox escape, reverse order)",
        severity="HIGH",
        description=(
            "The HTML `sandbox` attribute contains both `allow-same-origin` "
            "and `allow-scripts` (in reverse order relative to rule "
            "iframe-csp-sandbox-scripts-same-origin-combo). The "
            "vulnerability is identical: this pair defeats the iframe "
            "sandbox, granting the embedded document same-origin DOM access "
            "plus the JavaScript to exploit it."
        ),
        pattern=_SANDBOX_SAME_ORIGIN_THEN_SCRIPTS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iframe-csp-postmessage-origin-includes-bypass",
        name="postMessage handler uses .includes() for origin check (bypassable)",
        severity="CRITICAL",
        description=(
            "A `window.addEventListener('message', ...)` handler validates "
            "`event.origin` using `.includes()` (substring match). This is "
            "trivially bypassed: an attacker registers `evil-trusted.com` "
            "when the trusted domain is `trusted.com`. Any cross-origin "
            "window (including attacker pages embedding the target in an "
            "iframe) can call `postMessage` to send arbitrary payloads "
            "that pass the weak origin check."
        ),
        pattern=_POSTMESSAGE_ORIGIN_INCLUDES,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iframe-csp-postmessage-wildcard-target",
        name="postMessage sent with wildcard target origin ('*')",
        severity="CRITICAL",
        description=(
            "A call to `window.postMessage(data, '*')` sends the message "
            "to any window regardless of origin. If `data` contains "
            "sensitive information (tokens, session IDs, PII, commands), "
            "any embedded frame or cross-origin listener can intercept "
            "it. Always specify the explicit target origin as the second "
            "argument to postMessage."
        ),
        pattern=_POSTMESSAGE_WILDCARD_TARGET,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iframe-csp-user-controlled-src-expression",
        name="iframe src bound to a JS/JSX expression (user-controlled content injection)",
        severity="HIGH",
        description=(
            "An `<iframe>` element has its `src` attribute set from a "
            "JavaScript expression or JSX variable, indicating user-supplied "
            "or dynamic input. Without URL allowlisting this enables: "
            "(1) embedding arbitrary external pages under the application's "
            "chrome (phishing / UI redress), (2) `javascript:` or `data:` "
            "URI injection, (3) using the app as an open redirector. "
            "Even with `sandbox`, a user-controlled URL can load malicious "
            "content with postMessage exfiltration."
        ),
        pattern=_IFRAME_SRC_EXPRESSION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="iframe-csp-user-controlled-src-template",
        name="iframe src set from server-side template variable (user-controlled content injection)",
        severity="HIGH",
        description=(
            "An `<iframe>` element's `src` attribute is populated from a "
            "server-side template variable (e.g., `{{ user.embed_url }}`). "
            "If the variable originates from user-supplied data without "
            "strict URL allowlist validation server-side, an attacker can "
            "inject arbitrary URLs, enabling phishing, UI redress, and "
            "open-redirect attacks under the application's domain."
        ),
        pattern=_IFRAME_SRC_TEMPLATE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="iframe-csp-user-controlled-src-dom",
        name="iframe/frame .src assigned from user-input source (DOM open content injection)",
        severity="HIGH",
        description=(
            "A dynamically-created iframe or frame element has its `.src` "
            "property set from a known user-input source function "
            "(`getParam`, `req.query`, `searchParams.get`, etc.) without "
            "visible URL allowlisting. This enables the same content "
            "injection risks as template-based user-controlled src: "
            "phishing, UI redress, and open redirectors operating under "
            "the application's origin."
        ),
        pattern=_IFRAME_SRC_DOM_USERINPUT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="iframe-csp-srcdoc-user-html-expression",
        name="iframe srcdoc bound to a JS/JSX expression containing user HTML (injection)",
        severity="HIGH",
        description=(
            "The `srcdoc` attribute of an `<iframe>` is set from a "
            "JavaScript/JSX expression containing user-supplied content. "
            "`srcdoc` inlines an HTML document without a network fetch and "
            "runs in the framing page's origin (unless `sandbox` is set). "
            "Injecting user-controlled HTML into `srcdoc` is equivalent to "
            "a scoped `innerHTML` at document scope. Even with "
            "`sandbox='allow-scripts'` a crafted payload can exfiltrate "
            "data via postMessage. CSP `frame-src` does NOT constrain "
            "`srcdoc` (it governs fetched URLs, not inline documents)."
        ),
        pattern=_SRCDOC_EXPRESSION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iframe-csp-srcdoc-user-html-template",
        name="iframe srcdoc set from server-side template variable (user HTML injection)",
        severity="HIGH",
        description=(
            "The `srcdoc` attribute is populated from a server-side "
            "template variable (e.g., Jinja2 `{{ comment.rendered_html }}`). "
            "If the template variable is not strictly HTML-encoded before "
            "insertion this is a direct HTML injection at document scope "
            "inside the framing page's origin. Severity is CRITICAL when "
            "a `| safe` filter (or equivalent) bypasses auto-escaping."
        ),
        pattern=_SRCDOC_TEMPLATE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iframe-csp-srcdoc-python-format",
        name="iframe srcdoc constructed via Python f-string/format from variable (injection)",
        severity="HIGH",
        description=(
            "The `srcdoc` attribute value is assembled in Python using an "
            "f-string or `.format()` call that interpolates a variable. "
            "If that variable originates from user input or an API response "
            "without HTML encoding, the injected content runs in the "
            "framing page's origin. Treat all `srcdoc` construction via "
            "string interpolation as a potential injection point."
        ),
        pattern=_SRCDOC_PYTHON_FORMAT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="iframe-csp-allow-wildcard",
        name="iframe allow='*' grants all Permissions-Policy features to embedded content",
        severity="MEDIUM",
        description=(
            "The `allow='*'` attribute on an `<iframe>` delegates ALL "
            "browser Permissions-Policy features (camera, microphone, "
            "payment, geolocation, display-capture, etc.) to the embedded "
            "document. An attacker who compromises the embedded page, or "
            "who controls the `src` URL, gains access to every sensitive "
            "browser API at the user's privilege level. Always restrict "
            "`allow` to only the specific features the embed genuinely requires."
        ),
        pattern=_IFRAME_ALLOW_WILDCARD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="iframe-csp-allow-payment-sensitive",
        name="iframe allow attribute grants payment + sensitive API to embedded content",
        severity="MEDIUM",
        description=(
            "The `allow` attribute on an `<iframe>` grants `payment` "
            "together with at least one other sensitive feature "
            "(camera, microphone, geolocation, or display-capture). "
            "An attacker who compromises the embedded page or controls "
            "its `src` URL can access users' payment handlers and "
            "camera/microphone/geolocation at the user's privilege level. "
            "Severity escalates to HIGH when the iframe `src` is "
            "user-controlled."
        ),
        pattern=_IFRAME_ALLOW_PAYMENT_SENSITIVE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="iframe-csp-frame-ancestors-in-meta-a",
        name="CSP frame-ancestors delivered via <meta http-equiv> (silently ignored by browsers)",
        severity="MEDIUM",
        description=(
            "A `<meta http-equiv='Content-Security-Policy'>` tag carries a "
            "`frame-ancestors` directive. Per the W3C CSP Level 2 spec, "
            "browsers silently ignore `frame-ancestors` in meta-delivered "
            "policies — only HTTP response headers enforce it. The developer "
            "believes they have clickjacking protection, but they do not. "
            "This is a false sense of security: if no HTTP `Content-Security-Policy` "
            "header or `X-Frame-Options` header is also present, the page "
            "is fully embeddable. Severity escalates to HIGH when both HTTP "
            "headers are absent."
        ),
        pattern=_META_CSP_FRAME_ANCESTORS_A,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="iframe-csp-frame-ancestors-in-meta-b",
        name="CSP frame-ancestors in <meta> (content attr first, silently ignored)",
        severity="MEDIUM",
        description=(
            "Same vulnerability as iframe-csp-frame-ancestors-in-meta-a "
            "but with the `content` attribute appearing before `http-equiv` "
            "in the HTML source (attribute order is not semantically "
            "significant in HTML, but the regex must handle both forms). "
            "The CSP `frame-ancestors` directive in a meta-tag policy is "
            "silently discarded by all browsers per the W3C CSP Level 2 "
            "specification — only HTTP response headers enforce it."
        ),
        pattern=_META_CSP_FRAME_ANCESTORS_B,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="iframe-csp-frame-ancestors-in-meta-jsx",
        name="CSP frame-ancestors in React <meta httpEquiv> prop (silently ignored)",
        severity="MEDIUM",
        description=(
            "A React/Next.js `<meta httpEquiv='Content-Security-Policy'>` "
            "element carries a `frame-ancestors` directive in its `content` "
            "prop. Next.js static exports and React document heads commonly "
            "use this pattern, believing it enforces clickjacking protection "
            "globally. It does not — browsers ignore `frame-ancestors` in "
            "meta-delivered CSP. The HTTP response header must carry the "
            "policy for it to be enforced."
        ),
        pattern=_META_CSP_FRAME_ANCESTORS_JSX,
        owasp_asi="ASI-08",
    ),
)


# ---- Helper utilities ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Each rule is applied to the full text; matches are deduplicated by
    (rule_id, line, col). The sandbox escape rules (IF-002 / IF-004) use
    two complementary patterns each (one per ordering of the attributes).

    Findings are returned in (line, column) ascending order.
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

    # ---- IF-001a : X-Frame-Options set to permissive value ----
    rule_if001a = rule_by_id["iframe-csp-missing-frame-ancestors-and-xfo"]
    for m in _XFO_ALLOWALL.finditer(text):
        _emit(rule_if001a, m.start(), m.group(0))

    # ---- IF-001b : Helmet frameguard disabled ----
    rule_if001b = rule_by_id["iframe-csp-frameguard-disabled"]
    for m in _FRAMEGUARD_DISABLED.finditer(text):
        _emit(rule_if001b, m.start(), m.group(0))

    # ---- IF-002a : sandbox allow-scripts first ----
    rule_if002a = rule_by_id["iframe-csp-sandbox-scripts-same-origin-combo"]
    for m in _SANDBOX_SCRIPTS_THEN_SAME_ORIGIN.finditer(text):
        _emit(rule_if002a, m.start(), m.group(0))

    # ---- IF-002b : sandbox allow-same-origin first ----
    rule_if002b = rule_by_id["iframe-csp-sandbox-same-origin-scripts-combo"]
    for m in _SANDBOX_SAME_ORIGIN_THEN_SCRIPTS.finditer(text):
        _emit(rule_if002b, m.start(), m.group(0))

    # ---- IF-003a : origin.includes() bypass ----
    rule_if003a = rule_by_id["iframe-csp-postmessage-origin-includes-bypass"]
    for m in _POSTMESSAGE_ORIGIN_INCLUDES.finditer(text):
        _emit(rule_if003a, m.start(), m.group(0))

    # ---- IF-003b : postMessage wildcard target ----
    rule_if003b = rule_by_id["iframe-csp-postmessage-wildcard-target"]
    for m in _POSTMESSAGE_WILDCARD_TARGET.finditer(text):
        _emit(rule_if003b, m.start(), m.group(0))

    # ---- IF-004a : iframe src JSX expression ----
    rule_if004a = rule_by_id["iframe-csp-user-controlled-src-expression"]
    for m in _IFRAME_SRC_EXPRESSION.finditer(text):
        _emit(rule_if004a, m.start(), m.group(0))

    # ---- IF-004b : iframe src server-side template ----
    rule_if004b = rule_by_id["iframe-csp-user-controlled-src-template"]
    for m in _IFRAME_SRC_TEMPLATE.finditer(text):
        _emit(rule_if004b, m.start(), m.group(0))

    # ---- IF-004c : iframe src DOM user-input ----
    rule_if004c = rule_by_id["iframe-csp-user-controlled-src-dom"]
    for m in _IFRAME_SRC_DOM_USERINPUT.finditer(text):
        _emit(rule_if004c, m.start(), m.group(0))

    # ---- IF-005a : srcdoc JSX expression ----
    rule_if005a = rule_by_id["iframe-csp-srcdoc-user-html-expression"]
    for m in _SRCDOC_EXPRESSION.finditer(text):
        _emit(rule_if005a, m.start(), m.group(0))

    # ---- IF-005b : srcdoc server-side template ----
    rule_if005b = rule_by_id["iframe-csp-srcdoc-user-html-template"]
    for m in _SRCDOC_TEMPLATE.finditer(text):
        _emit(rule_if005b, m.start(), m.group(0))

    # ---- IF-005c : srcdoc Python format ----
    rule_if005c = rule_by_id["iframe-csp-srcdoc-python-format"]
    for m in _SRCDOC_PYTHON_FORMAT.finditer(text):
        _emit(rule_if005c, m.start(), m.group(0))

    # ---- IF-006a : iframe allow wildcard ----
    rule_if006a = rule_by_id["iframe-csp-allow-wildcard"]
    for m in _IFRAME_ALLOW_WILDCARD.finditer(text):
        _emit(rule_if006a, m.start(), m.group(0))

    # ---- IF-006b : iframe allow payment + sensitive ----
    rule_if006b = rule_by_id["iframe-csp-allow-payment-sensitive"]
    for m in _IFRAME_ALLOW_PAYMENT_SENSITIVE.finditer(text):
        _emit(rule_if006b, m.start(), m.group(0))

    # ---- IF-007a : meta CSP frame-ancestors (http-equiv first) ----
    rule_if007a = rule_by_id["iframe-csp-frame-ancestors-in-meta-a"]
    for m in _META_CSP_FRAME_ANCESTORS_A.finditer(text):
        _emit(rule_if007a, m.start(), m.group(0))

    # ---- IF-007b : meta CSP frame-ancestors (content attr first) ----
    rule_if007b = rule_by_id["iframe-csp-frame-ancestors-in-meta-b"]
    for m in _META_CSP_FRAME_ANCESTORS_B.finditer(text):
        _emit(rule_if007b, m.start(), m.group(0))

    # ---- IF-007c : meta CSP frame-ancestors (React JSX httpEquiv) ----
    rule_if007c = rule_by_id["iframe-csp-frame-ancestors-in-meta-jsx"]
    for m in _META_CSP_FRAME_ANCESTORS_JSX.finditer(text):
        _emit(rule_if007c, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
