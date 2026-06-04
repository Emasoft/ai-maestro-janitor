"""Tests for scripts/lib/webview_bridge_patterns.py.

Pattern-coverage tests for the Wave-32 distill-round-18 mobile WebView
JS-bridge security catalogue (10 rules). Each rule has at least 2 tests:
one positive (canary fires) and one negative (safe code is not flagged).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import webview_bridge_patterns as wvb  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(wvb.RULES, tuple)
    rule_ids = {r.id for r in wvb.RULES}
    expected = {
        "wvb-android-pre17-unconstrained-bridge",
        "wvb-ios-wkwebview-unvalidated-message",
        "wvb-cordova-allow-navigation-wildcard",
        "wvb-rn-webview-injected-js-dynamic",
        "wvb-flutter-js-channel-no-origin",
        "wvb-android-webview-file-access-js",
        "wvb-ios-wkwebview-backforward-no-delegate",
        "wvb-capacitor-localhost-cleartext",
        "wvb-android-webview-override-url-permissive",
        "wvb-rn-webview-file-data-uri-source",
    }
    assert expected == rule_ids
    assert len(wvb.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in wvb.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = wvb.Finding(
        rule_id="wvb-test",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-03",
    )
    assert f.rule_id == "wvb-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-03"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert wvb.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """scan_text output is ordered by (line, col)."""
    src = (
        # Line 1 — Cordova wildcard
        "<allow-navigation href='*' />\n"
        # Line 2 — Capacitor cleartext
        '"iosScheme": "http"\n'
    )
    findings = wvb.scan_text(src)
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[wvb.Finding]:
    return [f for f in wvb.scan_text(text) if f.rule_id == rule_id]


# ---------- WVB-1 : android-pre17-unconstrained-bridge -------------------


def test_wvb1_fires_on_public_method_without_annotation_and_bridge() -> None:
    """Public method without @JavascriptInterface in a file that calls addJavascriptInterface fires WVB-1."""
    src = """\
public class AnthropicBridge {
    public String getApiKey() {
        return BuildConfig.ANTHROPIC_API_KEY;
    }
}
webView.addJavascriptInterface(new AnthropicBridge(), "Claude");
"""
    hits = _hits("wvb-android-pre17-unconstrained-bridge", src)
    assert hits, "Expected WVB-1 finding for unannotated public method + bridge call"
    assert hits[0].severity == "CRITICAL"


def test_wvb1_suppressed_when_annotation_present() -> None:
    """@JavascriptInterface-annotated method does not fire WVB-1."""
    src = """\
public class AnthropicBridge {
    @JavascriptInterface
    public String getModelVersion() { return "claude-3-5"; }
}
webView.addJavascriptInterface(new AnthropicBridge(), "Claude");
"""
    hits = _hits("wvb-android-pre17-unconstrained-bridge", src)
    assert not hits, "Annotated method should not trigger WVB-1"


def test_wvb1_suppressed_without_bridge_call() -> None:
    """No addJavascriptInterface call means no WVB-1 (not used as bridge)."""
    src = """\
public class Helper {
    public String getVersion() { return "1.0"; }
}
"""
    hits = _hits("wvb-android-pre17-unconstrained-bridge", src)
    assert not hits, "No bridge call should suppress WVB-1"


# ---------- WVB-2 : ios-wkwebview-unvalidated-message --------------------


def test_wvb2_fires_on_handler_registration_without_origin_check() -> None:
    """WKUserContentController.add(self, name:) without securityOrigin fires WVB-2."""
    src = """\
webView.configuration.userContentController.add(self, name: "claudeNative")
func userContentController(_ ucc: WKUserContentController,
                           didReceive message: WKScriptMessage) {
    guard let body = message.body as? [String: Any] else { return }
    if let action = body["action"] as? String {
        message.webView?.evaluateJavaScript("window.token='\\(storedToken)'")
    }
}
"""
    hits = _hits("wvb-ios-wkwebview-unvalidated-message", src)
    assert hits, "Expected WVB-2 finding for handler without origin check"
    assert hits[0].severity == "HIGH"


def test_wvb2_suppressed_when_security_origin_present() -> None:
    """securityOrigin check in forward window suppresses WVB-2."""
    src = """\
webView.configuration.userContentController.add(self, name: "claudeNative")
func userContentController(_ ucc: WKUserContentController,
                           didReceive message: WKScriptMessage) {
    guard let origin = message.frameInfo.securityOrigin.host,
          origin == "claude.ai" else { return }
    // proceed
}
"""
    hits = _hits("wvb-ios-wkwebview-unvalidated-message", src)
    assert not hits, "securityOrigin check should suppress WVB-2"


# ---------- WVB-3 : cordova-allow-navigation-wildcard --------------------


def test_wvb3_fires_on_cordova_allow_navigation_wildcard() -> None:
    """Cordova <allow-navigation href='*'/> fires WVB-3."""
    src = """\
<widget>
  <allow-navigation href="*" />
  <plugin name="cordova-plugin-anthropic-sdk" />
</widget>
"""
    hits = _hits("wvb-cordova-allow-navigation-wildcard", src)
    assert hits, "Expected WVB-3 for Cordova wildcard allow-navigation"
    assert hits[0].severity == "HIGH"


def test_wvb3_fires_on_cordova_allow_intent_wildcard() -> None:
    """Cordova <allow-intent href='*'/> also fires WVB-3."""
    src = """\
<widget>
  <allow-intent href="*" />
</widget>
"""
    hits = _hits("wvb-cordova-allow-navigation-wildcard", src)
    assert hits, "Expected WVB-3 for Cordova wildcard allow-intent"


def test_wvb3_suppressed_on_specific_origin() -> None:
    """Pinned allow-navigation to specific origin does not fire WVB-3."""
    src = """\
<widget>
  <allow-navigation href="https://claude.ai/*" />
  <allow-navigation href="https://api.anthropic.com/*" />
</widget>
"""
    hits = _hits("wvb-cordova-allow-navigation-wildcard", src)
    assert not hits, "Specific allow-navigation should not trigger WVB-3"


def test_wvb3_fires_on_capacitor_allow_navigation_wildcard() -> None:
    """Capacitor allowNavigation: ['*'] fires WVB-3."""
    src = """\
{
  "server": {
    "allowNavigation": ["*"]
  }
}
"""
    hits = _hits("wvb-cordova-allow-navigation-wildcard", src)
    assert hits, "Expected WVB-3 for Capacitor allowNavigation wildcard"


# ---------- WVB-4 : rn-webview-injected-js-dynamic -----------------------


def test_wvb4_fires_on_template_literal_injection_with_on_message() -> None:
    """injectedJavaScript prop inline with ${...} template literal + onMessage fires WVB-4."""
    src = """\
<WebView
  injectedJavaScript={`window.userInfo = ${JSON.stringify(userData)};`}
  onMessage={({ nativeEvent }) => handleNativeMessage(nativeEvent.data)}
  source={{ uri: 'https://claude.ai/embed' }}
/>
"""
    hits = _hits("wvb-rn-webview-injected-js-dynamic", src)
    assert hits, "Expected WVB-4 for injectedJavaScript with inline template literal + onMessage"
    assert hits[0].severity == "HIGH"


def test_wvb4_suppressed_without_on_message() -> None:
    """injectedJavaScript with template literal but no onMessage is not flagged."""
    src = """\
const injectScript = `window.version = ${appVersion};`;
<WebView
  injectedJavaScript={injectScript}
  source={{ uri: 'https://claude.ai/embed' }}
/>
"""
    hits = _hits("wvb-rn-webview-injected-js-dynamic", src)
    assert not hits, "Without onMessage, WVB-4 should not fire"


# ---------- WVB-5 : flutter-js-channel-no-origin ------------------------


def test_wvb5_fires_on_add_js_channel_without_navigation_delegate() -> None:
    """addJavaScriptChannel with unrestricted JS and no NavigationDelegate fires WVB-5."""
    src = """\
_controller = WebViewController()
  ..setJavaScriptMode(JavaScriptMode.unrestricted)
  ..addJavaScriptChannel(
      'ClaudeNative',
      onMessageReceived: (JavaScriptMessage msg) {
        _handleBridgeMessage(msg.message);
      })
  ..loadRequest(Uri.parse(widget.url));
"""
    hits = _hits("wvb-flutter-js-channel-no-origin", src)
    assert hits, "Expected WVB-5 for addJavaScriptChannel without NavigationDelegate"
    assert hits[0].severity == "MEDIUM"


def test_wvb5_suppressed_when_navigation_delegate_present() -> None:
    """NavigationDelegate in same file suppresses WVB-5."""
    src = """\
_controller = WebViewController()
  ..setJavaScriptMode(JavaScriptMode.unrestricted)
  ..addJavaScriptChannel('ClaudeNative',
      onMessageReceived: (JavaScriptMessage msg) { _handle(msg.message); })
  ..setNavigationDelegate(NavigationDelegate(
    onNavigationRequest: (request) {
      if (!request.url.startsWith('https://claude.ai')) return NavigationDecision.prevent;
      return NavigationDecision.navigate;
    }
  ));
"""
    hits = _hits("wvb-flutter-js-channel-no-origin", src)
    assert not hits, "NavigationDelegate should suppress WVB-5"


def test_wvb5_suppressed_without_unrestricted_mode() -> None:
    """Without JavaScriptMode.unrestricted, WVB-5 does not fire."""
    src = """\
_controller = WebViewController()
  ..setJavaScriptMode(JavaScriptMode.disabled)
  ..addJavaScriptChannel('ClaudeNative',
      onMessageReceived: (JavaScriptMessage msg) { _handle(msg.message); });
"""
    hits = _hits("wvb-flutter-js-channel-no-origin", src)
    assert not hits, "Without unrestricted JS mode, WVB-5 should not fire"


# ---------- WVB-6 : android-webview-file-access-js -----------------------


def test_wvb6_fires_on_file_access_with_js_enabled() -> None:
    """allowFileAccess=true + javaScriptEnabled=true fires WVB-6."""
    src = """\
val settings = webView.settings
settings.javaScriptEnabled = true
settings.allowFileAccess = true
settings.allowContentAccess = true
webView.loadUrl(intentUrl)
"""
    hits = _hits("wvb-android-webview-file-access-js", src)
    assert hits, "Expected WVB-6 for allowFileAccess + javaScriptEnabled"
    assert hits[0].severity == "HIGH"


def test_wvb6_suppressed_when_js_disabled() -> None:
    """allowFileAccess=true without javaScriptEnabled does not fire WVB-6."""
    src = """\
val settings = webView.settings
settings.javaScriptEnabled = false
settings.allowFileAccess = true
webView.loadUrl("https://claude.ai/app")
"""
    hits = _hits("wvb-android-webview-file-access-js", src)
    assert not hits, "Without javaScriptEnabled, WVB-6 should not fire"


def test_wvb6_fires_on_java_setallowfileaccess_true() -> None:
    """setAllowFileAccess(true) method form also fires WVB-6 when JS enabled."""
    src = """\
webView.settings.setJavaScriptEnabled(true);
webView.settings.setAllowFileAccess(true);
webView.loadUrl(url);
"""
    hits = _hits("wvb-android-webview-file-access-js", src)
    assert hits, "Expected WVB-6 for setAllowFileAccess(true) + setJavaScriptEnabled(true)"


# ---------- WVB-7 : ios-wkwebview-backforward-no-delegate ----------------


def test_wvb7_fires_on_backforward_without_delegate() -> None:
    """allowsBackForwardNavigationGestures=true without navigationDelegate fires WVB-7."""
    src = """\
webView.allowsBackForwardNavigationGestures = true
webView.configuration.userContentController.add(self, name: "claudeNative")
webView.load(URLRequest(url: URL(string: "https://claude.ai/auth")!))
"""
    hits = _hits("wvb-ios-wkwebview-backforward-no-delegate", src)
    assert hits, "Expected WVB-7 for backForward gestures without navigationDelegate"
    assert hits[0].severity == "MEDIUM"


def test_wvb7_suppressed_when_navigation_delegate_assigned() -> None:
    """navigationDelegate assignment suppresses WVB-7."""
    src = """\
webView.allowsBackForwardNavigationGestures = true
webView.navigationDelegate = self
func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
             decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
    let host = action.request.url?.host
    decisionHandler(host == "claude.ai" ? .allow : .cancel)
}
"""
    hits = _hits("wvb-ios-wkwebview-backforward-no-delegate", src)
    assert not hits, "navigationDelegate should suppress WVB-7"


# ---------- WVB-8 : capacitor-localhost-cleartext ------------------------


def test_wvb8_fires_on_hostname_localhost() -> None:
    """hostname=localhost fires WVB-8."""
    src = """\
{
  "appId": "ai.claude.mobile",
  "server": {
    "hostname": "localhost",
    "androidScheme": "http"
  }
}
"""
    hits = _hits("wvb-capacitor-localhost-cleartext", src)
    assert hits, "Expected WVB-8 for hostname=localhost"
    assert hits[0].severity == "MEDIUM"


def test_wvb8_fires_on_android_http_scheme() -> None:
    """androidScheme=http directly fires WVB-8."""
    src = """\
{
  "server": {
    "androidScheme": "http",
    "iosScheme": "http"
  }
}
"""
    hits = _hits("wvb-capacitor-localhost-cleartext", src)
    assert hits, "Expected WVB-8 for androidScheme=http"


def test_wvb8_suppressed_on_https_scheme() -> None:
    """androidScheme=https and no localhost does not fire WVB-8."""
    src = """\
{
  "server": {
    "androidScheme": "https",
    "iosScheme": "https"
  }
}
"""
    hits = _hits("wvb-capacitor-localhost-cleartext", src)
    assert not hits, "https scheme should suppress WVB-8"


# ---------- WVB-9 : android-webview-override-url-permissive --------------


def test_wvb9_fires_on_should_override_returns_false_with_bridge() -> None:
    """shouldOverrideUrlLoading returning false unconditionally + bridge fires WVB-9."""
    src = """\
webView.webViewClient = object : WebViewClient() {
    override fun shouldOverrideUrlLoading(
        view: WebView, request: WebResourceRequest
    ): Boolean { return false }
}
webView.addJavascriptInterface(AnthropicBridge(), "Claude")
webView.loadUrl(url)
"""
    hits = _hits("wvb-android-webview-override-url-permissive", src)
    assert hits, "Expected WVB-9 for unconditional false return + bridge"
    assert hits[0].severity == "HIGH"


def test_wvb9_suppressed_without_bridge() -> None:
    """shouldOverrideUrlLoading returning false without bridge does not fire WVB-9."""
    src = """\
webView.webViewClient = object : WebViewClient() {
    override fun shouldOverrideUrlLoading(
        view: WebView, request: WebResourceRequest
    ): Boolean { return false }
}
webView.loadUrl("https://claude.ai/app")
"""
    hits = _hits("wvb-android-webview-override-url-permissive", src)
    assert not hits, "Without bridge, WVB-9 should not fire"


def test_wvb9_fires_on_java_boolean_form() -> None:
    """Java boolean shouldOverrideUrlLoading returning false + bridge fires WVB-9."""
    src = """\
@Override
public boolean shouldOverrideUrlLoading(WebView view, String url) {
    return false;
}
view.addJavascriptInterface(new AnthropicBridge(), "Claude");
"""
    hits = _hits("wvb-android-webview-override-url-permissive", src)
    assert hits, "Expected WVB-9 for Java boolean form + bridge"


# ---------- WVB-10 : rn-webview-file-data-uri-source --------------------


def test_wvb10_fires_on_file_uri_source_with_on_message() -> None:
    """source={{ uri: file://... }} with onMessage fires WVB-10."""
    src = """\
const { uri } = route.params;

<WebView
  source={{ uri: "file:///data/user/0/ai.claude.mobile/cache/content.html" }}
  onMessage={handleMessage}
/>
"""
    hits = _hits("wvb-rn-webview-file-data-uri-source", src)
    assert hits, "Expected WVB-10 for file:// source with onMessage"
    assert hits[0].severity == "HIGH"


def test_wvb10_fires_on_data_uri_source() -> None:
    """source={{ uri: 'data:text/html,...' }} fires WVB-10."""
    src = """\
<WebView
  source={{ uri: "data:text/html,<h1>hello</h1>" }}
  onMessage={handleMessage}
/>
"""
    hits = _hits("wvb-rn-webview-file-data-uri-source", src)
    assert hits, "Expected WVB-10 for data: URI source"


def test_wvb10_fires_on_dynamic_html_with_on_message() -> None:
    """source={{ html: dynamicVariable }} with onMessage fires WVB-10."""
    src = """\
<WebView
  source={{ html: serverResponse.content }}
  onMessage={handleMessage}
/>
"""
    hits = _hits("wvb-rn-webview-file-data-uri-source", src)
    assert hits, "Expected WVB-10 for dynamic html source + onMessage"


def test_wvb10_suppressed_on_static_https_source() -> None:
    """Static https:// source URI does not fire WVB-10."""
    src = """\
<WebView
  source={{ uri: "https://claude.ai/embed" }}
  onMessage={handleMessage}
/>
"""
    hits = _hits("wvb-rn-webview-file-data-uri-source", src)
    assert not hits, "Static https:// URI should not trigger WVB-10"


def test_wvb10_suppressed_on_static_html_without_on_message() -> None:
    """source={{ html: '<h1>Hello</h1>' }} without onMessage does not fire WVB-10."""
    src = """\
<WebView
  source={{ html: '<h1>Terms of Service</h1><p>Please read...</p>' }}
/>
"""
    hits = _hits("wvb-rn-webview-file-data-uri-source", src)
    assert not hits, "Static html string without onMessage should not trigger WVB-10"
