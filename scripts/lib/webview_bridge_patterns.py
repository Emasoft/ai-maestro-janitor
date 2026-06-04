"""Mobile WebView JS-bridge security patterns.

Wave-32 distillation round 18, angle: Mobile WebView JS-bridge security.

Catalogue of 10 mobile WebView JS-bridge anti-patterns distilled in
`reports/distill-round-18/webview-bridge.md`. Targets Android
`addJavascriptInterface`, iOS `WKWebView` `userContentController`,
Cordova / Capacitor / Ionic plugin bridge whitelist gaps, React Native
`WebView.injectedJavaScript`, Flutter `webview_flutter` `onMessage`
trust boundary, and `file://` / `content://` URL handler misuse.

What is NOT here (already shipped — DO NOT duplicate):

  * Android `addJavascriptInterface` call-site detection —
    `mobile_manifest_patterns.py` rule `mobile.android-webview-js-bridge`.
  * iOS entitlement misuse / sandbox escapes —
    `ios_sandboxing_patterns.py`.
  * DRM key-exchange misuse — `mobile_drm_patterns.py`.
  * Build-time credential leaks — `mobile_build_patterns.py`.
  * Cordova keystore password — `mobile_build_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * wvb-android-pre17-unconstrained-bridge          (CRITICAL)
  * wvb-ios-wkwebview-unvalidated-message           (HIGH)
  * wvb-cordova-allow-navigation-wildcard           (HIGH)
  * wvb-rn-webview-injected-js-dynamic              (HIGH)
  * wvb-flutter-js-channel-no-origin               (MEDIUM)
  * wvb-android-webview-file-access-js              (HIGH)
  * wvb-ios-wkwebview-backforward-no-delegate       (MEDIUM)
  * wvb-capacitor-localhost-cleartext               (MEDIUM)
  * wvb-android-webview-override-url-permissive     (HIGH)
  * wvb-rn-webview-file-data-uri-source             (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (navigation policy bypass, swipe-back
                                   into untrusted origin)
  ASI-03 — Injection (JS→native bridge injection via untrusted content,
                      XSS escalating to RN bridge, cross-origin JS)
  ASI-06 — Security Misconfiguration (legacy insecure API, file/content
                                       URI access + JS, cleartext bridge)

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


# ---- WVB-1 : wvb-android-pre17-unconstrained-bridge ---------------------


# Stage A: public method without @JavascriptInterface annotation.
# Matches any `public <return-type> methodName(` shape.
_ANDROID_PUBLIC_METHOD_NO_ANNOTATION = _re(
    r"public\s+(?:String|void|int|boolean|Object|JSONObject|byte\[\]|double|long|float)"
    r"\s+\w+\s*\("
)

# Stage B: confirm file also calls addJavascriptInterface (bridge is wired).
_ANDROID_ADD_JAVASCRIPT_INTERFACE = _re(
    r"\.addJavascriptInterface\s*\("
)


# ---- WVB-2 : wvb-ios-wkwebview-unvalidated-message ----------------------


# Stage A: WKUserContentController message handler registration.
_IOS_WKWEBVIEW_HANDLER_REGISTRATION = _re(
    r"userContentController\s*\.\s*add\s*\(\s*self\s*,\s*name\s*:"
)

# Absence signal: securityOrigin / frameInfo origin check.
_IOS_WKWEBVIEW_ORIGIN_CHECK = _re(
    r"\bsecurityOrigin\b"
    r"|"
    r"\bframeInfo\b"
)


# ---- WVB-3 : wvb-cordova-allow-navigation-wildcard ----------------------


# Cordova config.xml wildcard allow-navigation.
_CORDOVA_ALLOW_NAVIGATION_WILDCARD = _re(
    r"<allow-navigation\s+href\s*=\s*[\"'][*]"
)

# Cordova config.xml wildcard allow-intent.
_CORDOVA_ALLOW_INTENT_WILDCARD = _re(
    r"<allow-intent\s+href\s*=\s*[\"'][*]"
)

# Capacitor allowNavigation wildcard (JSON/TS forms).
_CAPACITOR_ALLOW_NAVIGATION_WILDCARD = _re(
    r"[\"']allowNavigation[\"']\s*:\s*\[\s*[\"'][*]"
    r"|"
    r"\ballowNavigation\s*:\s*\[\s*[\"'][*]"
)


# ---- WVB-4 : wvb-rn-webview-injected-js-dynamic -------------------------


# Stage A: injectedJavaScript with template literal interpolation.
_RN_INJECTED_JS_TEMPLATE_LITERAL = _re(
    r"injectedJavaScript\s*=\s*\{[^}]*\$\{"
)

# Stage A alternative: injectedJavaScript with string concat using user-data var.
_RN_INJECTED_JS_STRING_CONCAT = _re(
    r"injectedJavaScript\s*=\s*\{[^}]*\+\s*"
    r"(?:user|data|param|input|req|body|name|value)\b"
)

# Stage B: onMessage bridge is wired up (corroborator).
_RN_ON_MESSAGE = _re(
    r"\bonMessage\s*=\s*\{"
)


# ---- WVB-5 : wvb-flutter-js-channel-no-origin ---------------------------


# Stage A: Flutter JavaScriptChannel registration (new and old API).
_FLUTTER_ADD_JS_CHANNEL = _re(
    r"addJavaScriptChannel\s*\("
    r"|"
    r"\bJavascriptChannel\s*\("
)

# Stage B: unrestricted JavaScript mode (corroborator).
_FLUTTER_UNRESTRICTED_JS = _re(
    r"JavaScriptMode\.unrestricted"
)

# Absence signal: navigation delegate that restricts navigation.
_FLUTTER_NAVIGATION_DELEGATE = _re(
    r"\bNavigationDelegate\b"
    r"|"
    r"\bonNavigationRequest\b"
)


# ---- WVB-6 : wvb-android-webview-file-access-js -------------------------


# Stage A: allowFileAccess enabled (Kotlin property or Java method).
_ANDROID_FILE_ACCESS_ENABLED = _re(
    r"\ballowFileAccess\s*=\s*true\b"
    r"|"
    r"\bsetAllowFileAccess\s*\(\s*true\s*\)"
)

# Stage B: JavaScript enabled (required for exploitability).
_ANDROID_JS_ENABLED = _re(
    r"\bjavaScriptEnabled\s*=\s*true\b"
    r"|"
    r"\bsetJavaScriptEnabled\s*\(\s*true\s*\)"
)


# ---- WVB-7 : wvb-ios-wkwebview-backforward-no-delegate ------------------


# Stage A: back/forward gestures enabled.
_IOS_BACKFORWARD_GESTURES = _re(
    r"\ballowsBackForwardNavigationGestures\s*=\s*true\b"
)

# Absence signal: navigationDelegate assignment.
_IOS_NAVIGATION_DELEGATE = _re(
    r"\bnavigationDelegate\s*="
    r"|"
    r"\bWKNavigationDelegate\b"
)


# ---- WVB-8 : wvb-capacitor-localhost-cleartext --------------------------


# Cleartext Android scheme.
_CAPACITOR_ANDROID_HTTP_SCHEME = _re(
    r"[\"']androidScheme[\"']\s*:\s*[\"']http[\"']"
)

# Cleartext iOS scheme.
_CAPACITOR_IOS_HTTP_SCHEME = _re(
    r"[\"']iosScheme[\"']\s*:\s*[\"']http[\"']"
)

# Hostname set to localhost.
_CAPACITOR_LOCALHOST_HOSTNAME = _re(
    r"[\"']hostname[\"']\s*:\s*[\"']localhost[\"']"
)


# ---- WVB-9 : wvb-android-webview-override-url-permissive ----------------


# Stage A: shouldOverrideUrlLoading overriding and returning false (Kotlin).
_ANDROID_SHOULD_OVERRIDE_RETURNS_FALSE_KT = _re(
    r"fun\s+shouldOverrideUrlLoading\s*\([^)]*\)\s*(?::\s*Boolean\s*)?\{[^}]*\breturn\s+false\s*\}"
)

# Stage A alternative: Java form.
_ANDROID_SHOULD_OVERRIDE_RETURNS_FALSE_JAVA = _re(
    r"boolean\s+shouldOverrideUrlLoading\s*\([^)]*\)\s*\{[^}]*return\s+false\s*;[^}]*\}"
)

# Stage B: bridge registered in same file.
_ANDROID_BRIDGE_PRESENT = _re(
    r"\.addJavascriptInterface\s*\("
    r"|"
    r"@JavascriptInterface\b"
)


# ---- WVB-10 : wvb-rn-webview-file-data-uri-source -----------------------


# Stage A: source uri with file:// or data: scheme.
_RN_SOURCE_FILE_DATA_URI = _re(
    r"source\s*=\s*\{\s*\{\s*uri\s*:\s*(?:[^}]*file://|[^}]*data:)"
)

# Stage A alternative: dynamic html source (non-literal).
# RE2-safe: no lookahead. Stage-B verifies the char after `html:` is not a quote.
_RN_SOURCE_DYNAMIC_HTML = _re(
    r"source\s*=\s*\{\s*\{\s*html\s*:\s*[^\"'`\s\}]"
)

# Stage B: onMessage bridge wired up (corroborator).
_RN_SOURCE_ON_MESSAGE = _re(
    r"\bonMessage\s*=\s*\{"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="wvb-android-pre17-unconstrained-bridge",
        name="Android addJavascriptInterface with public method lacking @JavascriptInterface annotation",
        severity="CRITICAL",
        description=(
            "Before Android API level 17, ALL public methods of objects "
            "passed to WebView.addJavascriptInterface() are accessible "
            "from JavaScript — regardless of @JavascriptInterface annotation. "
            "An attacker-controlled page can invoke Java reflection via the "
            "bridge object to execute arbitrary shell commands (CVE-2012-6636, "
            "CVE-2013-4710). The file contains addJavascriptInterface() AND "
            "at least one public method without the annotation guard. Apps "
            "with minSdkVersion < 17 in build.gradle remain vulnerable on "
            "pre-17 devices."
        ),
        pattern=_ANDROID_PUBLIC_METHOD_NO_ANNOTATION,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="wvb-ios-wkwebview-unvalidated-message",
        name="iOS WKWebView userContentController handler without securityOrigin check",
        severity="HIGH",
        description=(
            "WKUserContentController.add(self, name:) registers a JS→native "
            "handler reachable from ANY JavaScript running in the WebView. "
            "Without validating message.frameInfo.securityOrigin.host, any "
            "JS from a compromised CDN, XSS, or redirect to an attacker "
            "domain can post to the handler and trigger privileged operations "
            "(token retrieval, file access, push registration). Safe code "
            "guards on securityOrigin.host == expected-domain before acting."
        ),
        pattern=_IOS_WKWEBVIEW_HANDLER_REGISTRATION,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="wvb-cordova-allow-navigation-wildcard",
        name="Cordova / Capacitor allow-navigation or allow-intent wildcard in config",
        severity="HIGH",
        description=(
            "config.xml <allow-navigation href='*'/> or <allow-intent href='*'/> "
            "(Cordova), or allowNavigation: ['*'] (Capacitor), allows ANY URL "
            "to navigate into the WebView. Loaded attacker-controlled pages can "
            "call window.Cordova.exec() or window.Capacitor.nativeCallback() "
            "to invoke native plugin methods — full bridge access without "
            "authentication (CVE-2020-6506). Pin allow-navigation to the "
            "app's own origin(s) only."
        ),
        pattern=_CORDOVA_ALLOW_NAVIGATION_WILDCARD,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="wvb-rn-webview-injected-js-dynamic",
        name="React Native WebView.injectedJavaScript built via template literal or string concat with user data",
        severity="HIGH",
        description=(
            "React Native injectedJavaScript or injectedJavaScriptBeforeContentLoaded "
            "is constructed via template literal interpolation or string "
            "concatenation that includes user-controlled or server-provided data. "
            "An attacker who controls that data can inject arbitrary JavaScript "
            "running with the hosting page's origin. If onMessage is wired up, "
            "the injected JS reaches the RN native bridge via "
            "window.ReactNativeWebView.postMessage() — escalating XSS to "
            "full native-bridge access."
        ),
        pattern=_RN_INJECTED_JS_TEMPLATE_LITERAL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="wvb-flutter-js-channel-no-origin",
        name="Flutter webview_flutter addJavaScriptChannel without NavigationDelegate origin guard",
        severity="MEDIUM",
        description=(
            "Flutter addJavaScriptChannel() / JavascriptChannel() registers a "
            "named channel callable from any JavaScript running in the WebView. "
            "Unlike WKWebView, Flutter's JavascriptMessage carries NO origin or "
            "frame information — there is no API to origin-check the caller. "
            "When JavaScriptMode.unrestricted is set and no NavigationDelegate "
            "restricts navigation, any JS on any origin can invoke Dart-side "
            "logic. Safe code pairs addJavaScriptChannel with a NavigationDelegate "
            "that allowlists navigation destinations."
        ),
        pattern=_FLUTTER_ADD_JS_CHANNEL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="wvb-android-webview-file-access-js",
        name="Android WebView setAllowFileAccess(true) combined with JavaScript enabled",
        severity="HIGH",
        description=(
            "WebView.settings.allowFileAccess = true (or setAllowFileAccess(true)) "
            "combined with javaScriptEnabled = true creates a path to reading "
            "arbitrary local files. JavaScript running in a file:// origin can "
            "fetch() or XMLHttpRequest other file:// paths and exfiltrate content "
            "over the network (classic CVE-2012-6654 pattern). Disable "
            "allowFileAccess and allowContentAccess in all WebViews that load "
            "remote content. Escalates to CRITICAL when the URL is sourced from "
            "an external Intent."
        ),
        pattern=_ANDROID_FILE_ACCESS_ENABLED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="wvb-ios-wkwebview-backforward-no-delegate",
        name="iOS WKWebView allowsBackForwardNavigationGestures without navigationDelegate",
        severity="MEDIUM",
        description=(
            "allowsBackForwardNavigationGestures = true enables swipe-back/forward "
            "through the WebView's browsing history. Without a WKNavigationDelegate "
            "that re-validates each destination URL, a user or attacker with XSS "
            "can swipe into a previously-visited untrusted page. That page runs in "
            "the WebView's context and can post messages to any registered "
            "WKUserContentController handler, bypassing origin checks set only on "
            "initial load. Escalates to HIGH when a userContentController message "
            "handler is also registered in the same file."
        ),
        pattern=_IOS_BACKFORWARD_GESTURES,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wvb-capacitor-localhost-cleartext",
        name="Capacitor server.hostname localhost with http scheme — cleartext bridge",
        severity="MEDIUM",
        description=(
            "Capacitor routes the native bridge through a local HTTP/HTTPS server. "
            "Setting androidScheme or iosScheme to 'http' (instead of the default "
            "'capacitor' or 'https') opens two attack surfaces: "
            "(1) cleartext http://localhost traffic is sniffable on rooted devices "
            "or Wi-Fi proxies, leaking tokens and API keys injected via the bridge; "
            "(2) some Capacitor versions treat http://localhost as same-origin as "
            "file://, allowing file:// content to invoke native plugin methods. "
            "Use 'https' or the default 'capacitor' scheme in production."
        ),
        pattern=_CAPACITOR_LOCALHOST_HOSTNAME,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="wvb-android-webview-override-url-permissive",
        name="Android WebViewClient.shouldOverrideUrlLoading returns false unconditionally",
        severity="HIGH",
        description=(
            "shouldOverrideUrlLoading returns false unconditionally — approving "
            "ALL navigations including javascript: URIs, attacker-controlled "
            "redirects, and compromised CDN resources. When combined with a "
            "registered addJavascriptInterface bridge, any navigation to an "
            "attacker page reaches the bridge immediately. "
            "The safe pattern allowlists by host and returns true (block) for "
            "all unrecognised destinations (CVE-2014-1939 context)."
        ),
        pattern=_ANDROID_SHOULD_OVERRIDE_RETURNS_FALSE_KT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wvb-rn-webview-file-data-uri-source",
        name="React Native WebView source uri uses file:// or data: scheme, or dynamic html with onMessage",
        severity="HIGH",
        description=(
            "React Native WebView source={{ uri: 'file://...' }} or "
            "source={{ uri: 'data:...' }} loads content in the file:// or null "
            "(opaque) origin. source={{ html: <dynamic-expression> }} is equivalent "
            "to stored XSS. Both allow the loaded content to call "
            "window.ReactNativeWebView.postMessage() reaching the onMessage handler "
            "with full native-bridge access, bypassing any host-based origin check. "
            "Use static https:// URIs and validate onMessage origin where possible."
        ),
        pattern=_RN_SOURCE_FILE_DATA_URI,
        owasp_asi="ASI-03",
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
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines or whole-file context:

      * WVB-1 (android-pre17-unconstrained-bridge) — anchor on public method
        shape; require addJavascriptInterface anywhere in the same file as
        Stage-B confirmation that it is used as a bridge object.
      * WVB-2 (ios-wkwebview-unvalidated-message) — anchor on handler
        registration; require NO securityOrigin / frameInfo in a 60-line
        forward window (absence check).
      * WVB-3 (cordova-allow-navigation-wildcard) — direct match on wildcard
        patterns (three pattern variants); no Stage-B needed.
      * WVB-4 (rn-webview-injected-js-dynamic) — anchor on template-literal
        or string-concat injectedJavaScript; Stage-B requires onMessage
        anywhere in the file (bridge wired up).
      * WVB-5 (flutter-js-channel-no-origin) — anchor on addJavaScriptChannel;
        require JavaScriptMode.unrestricted in same file AND require absence
        of NavigationDelegate to emit finding.
      * WVB-6 (android-webview-file-access-js) — anchor on allowFileAccess;
        require javaScriptEnabled in same file (Stage-B).
      * WVB-7 (ios-wkwebview-backforward-no-delegate) — anchor on
        allowsBackForwardNavigationGestures; require NO navigationDelegate
        in same file (absence check).
      * WVB-8 (capacitor-localhost-cleartext) — anchor on hostname=localhost;
        escalate if androidScheme/iosScheme=http also present.
      * WVB-9 (android-webview-override-url-permissive) — anchor on
        shouldOverrideUrlLoading returning false; require bridge present
        in same file (Stage-B).
      * WVB-10 (rn-webview-file-data-uri-source) — direct match for file://
        /data: uri; also matches dynamic html source; Stage-B onMessage
        required for dynamic html variant.

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

    # ---- WVB-1 : android-pre17-unconstrained-bridge ----
    rule_wvb1 = rule_by_id["wvb-android-pre17-unconstrained-bridge"]
    has_bridge_call = _file_contains(text, _ANDROID_ADD_JAVASCRIPT_INTERFACE)
    if has_bridge_call:
        for m in _ANDROID_PUBLIC_METHOD_NO_ANNOTATION.finditer(text):
            line_no, _ = _line_col(text, m.start())
            # Check the 2 lines before this match for @JavascriptInterface.
            window = _slice_window(text, line_no, 2, 0)
            if "@JavascriptInterface" in window or "@javascriptinterface" in window.lower():
                continue
            _emit(rule_wvb1, m.start(), m.group(0))

    # ---- WVB-2 : ios-wkwebview-unvalidated-message ----
    rule_wvb2 = rule_by_id["wvb-ios-wkwebview-unvalidated-message"]
    for m in _IOS_WKWEBVIEW_HANDLER_REGISTRATION.finditer(text):
        line_no, _ = _line_col(text, m.start())
        # Check 60-line forward window for securityOrigin / frameInfo.
        window = _slice_forward(text, line_no, 60)
        if _IOS_WKWEBVIEW_ORIGIN_CHECK.search(window) is not None:
            continue
        _emit(rule_wvb2, m.start(), m.group(0))

    # ---- WVB-3 : cordova-allow-navigation-wildcard ----
    rule_wvb3 = rule_by_id["wvb-cordova-allow-navigation-wildcard"]
    for m in _CORDOVA_ALLOW_NAVIGATION_WILDCARD.finditer(text):
        _emit(rule_wvb3, m.start(), m.group(0))
    for m in _CORDOVA_ALLOW_INTENT_WILDCARD.finditer(text):
        _emit(rule_wvb3, m.start(), m.group(0))
    for m in _CAPACITOR_ALLOW_NAVIGATION_WILDCARD.finditer(text):
        _emit(rule_wvb3, m.start(), m.group(0))

    # ---- WVB-4 : rn-webview-injected-js-dynamic ----
    rule_wvb4 = rule_by_id["wvb-rn-webview-injected-js-dynamic"]
    has_on_message_rn4 = _file_contains(text, _RN_ON_MESSAGE)
    if has_on_message_rn4:
        for m in _RN_INJECTED_JS_TEMPLATE_LITERAL.finditer(text):
            _emit(rule_wvb4, m.start(), m.group(0))
        for m in _RN_INJECTED_JS_STRING_CONCAT.finditer(text):
            _emit(rule_wvb4, m.start(), m.group(0))

    # ---- WVB-5 : flutter-js-channel-no-origin ----
    rule_wvb5 = rule_by_id["wvb-flutter-js-channel-no-origin"]
    has_unrestricted_js = _file_contains(text, _FLUTTER_UNRESTRICTED_JS)
    has_nav_delegate = _file_contains(text, _FLUTTER_NAVIGATION_DELEGATE)
    if has_unrestricted_js and not has_nav_delegate:
        for m in _FLUTTER_ADD_JS_CHANNEL.finditer(text):
            _emit(rule_wvb5, m.start(), m.group(0))

    # ---- WVB-6 : android-webview-file-access-js ----
    rule_wvb6 = rule_by_id["wvb-android-webview-file-access-js"]
    has_js_enabled = _file_contains(text, _ANDROID_JS_ENABLED)
    if has_js_enabled:
        for m in _ANDROID_FILE_ACCESS_ENABLED.finditer(text):
            _emit(rule_wvb6, m.start(), m.group(0))

    # ---- WVB-7 : ios-wkwebview-backforward-no-delegate ----
    rule_wvb7 = rule_by_id["wvb-ios-wkwebview-backforward-no-delegate"]
    has_nav_delegate_ios = _file_contains(text, _IOS_NAVIGATION_DELEGATE)
    if not has_nav_delegate_ios:
        for m in _IOS_BACKFORWARD_GESTURES.finditer(text):
            _emit(rule_wvb7, m.start(), m.group(0))

    # ---- WVB-8 : capacitor-localhost-cleartext ----
    rule_wvb8 = rule_by_id["wvb-capacitor-localhost-cleartext"]
    for m in _CAPACITOR_LOCALHOST_HOSTNAME.finditer(text):
        _emit(rule_wvb8, m.start(), m.group(0))
    # Also flag cleartext scheme directly (androidScheme/iosScheme = http).
    for m in _CAPACITOR_ANDROID_HTTP_SCHEME.finditer(text):
        _emit(rule_wvb8, m.start(), m.group(0))
    for m in _CAPACITOR_IOS_HTTP_SCHEME.finditer(text):
        _emit(rule_wvb8, m.start(), m.group(0))

    # ---- WVB-9 : android-webview-override-url-permissive ----
    rule_wvb9 = rule_by_id["wvb-android-webview-override-url-permissive"]
    has_bridge_wvb9 = _file_contains(text, _ANDROID_BRIDGE_PRESENT)
    if has_bridge_wvb9:
        for m in _ANDROID_SHOULD_OVERRIDE_RETURNS_FALSE_KT.finditer(text):
            _emit(rule_wvb9, m.start(), m.group(0))
        for m in _ANDROID_SHOULD_OVERRIDE_RETURNS_FALSE_JAVA.finditer(text):
            _emit(rule_wvb9, m.start(), m.group(0))

    # ---- WVB-10 : rn-webview-file-data-uri-source ----
    rule_wvb10 = rule_by_id["wvb-rn-webview-file-data-uri-source"]
    # file:// / data: uri form — always flag (high precision).
    for m in _RN_SOURCE_FILE_DATA_URI.finditer(text):
        _emit(rule_wvb10, m.start(), m.group(0))
    # Dynamic html source — require onMessage (bridge wired up).
    has_on_message_wvb10 = _file_contains(text, _RN_SOURCE_ON_MESSAGE)
    if has_on_message_wvb10:
        for m in _RN_SOURCE_DYNAMIC_HTML.finditer(text):
            _emit(rule_wvb10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
