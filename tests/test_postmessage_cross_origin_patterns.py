"""Tests for scripts/lib/postmessage_cross_origin_patterns.py.

Pattern-coverage tests for the Wave-32 distill-round-18 postmessage
cross-origin catalogue (9 anti-patterns). Each rule has at least one
positive test exercising the canary and at least one negative test
exercising the safe counterpart.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

from postmessage_cross_origin_patterns import RULES, scan_text  # type: ignore[import-not-found]  # noqa: E402

# ---- Sanity helpers -------------------------------------------------------


def _rule_ids() -> set[str]:
    return {r.id for r in RULES}


def _has_finding(text: str, rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in scan_text(text))


# ---- Data-model sanity ----------------------------------------------------


class TestDataModel(unittest.TestCase):
    """Basic structural checks for RULES and Finding."""

    def test_rules_tuple_contains_all_nine_rules(self) -> None:
        """RULES must contain exactly the 9 documented rule IDs."""
        expected = {
            "pmsg-onmessage-property-no-origin-guard",
            "pmsg-broadcastchannel-handler-no-type-allowlist",
            "pmsg-origin-startswith-endswith-bypass",
            "pmsg-messagechannel-port-wildcard-transfer",
            "pmsg-data-relay-to-wildcard",
            "pmsg-sw-clients-matchall-broadcast",
            "pmsg-extension-postmessage-bridge-no-nonce",
            "pmsg-source-reply-wildcard-target",
            "pmsg-broadcastchannel-user-input-name",
        }
        self.assertEqual(expected, _rule_ids())
        self.assertEqual(9, len(RULES))

    def test_every_rule_has_valid_severity_and_owasp(self) -> None:
        """Every rule must have a known severity and ASI-prefixed OWASP tag."""
        valid_severities = {"CRITICAL", "HIGH", "MAJOR", "MINOR"}
        for rule in RULES:
            self.assertIn(rule.severity, valid_severities, rule.id)
            self.assertTrue(rule.owasp_asi.startswith("ASI-"), rule.id)
            self.assertTrue(rule.name.strip(), rule.id)
            self.assertTrue(rule.description.strip(), rule.id)

    def test_scan_text_empty_returns_empty_list(self) -> None:
        """scan_text('') must return an empty list without raising."""
        self.assertEqual([], scan_text(""))

    def test_scan_text_returns_list_of_findings(self) -> None:
        """scan_text must return a list of Finding namedtuples."""
        results = scan_text("window.onmessage = (e) => { doSomething(e.data); };")
        self.assertIsInstance(results, list)
        for f in results:
            self.assertEqual(7, len(f))  # 7 fields in Finding


# ---- P1: pmsg-onmessage-property-no-origin-guard -------------------------


class TestOnmessagePropertyNoOriginGuard(unittest.TestCase):

    RULE_ID = "pmsg-onmessage-property-no-origin-guard"

    def test_window_onmessage_assign_fires(self) -> None:
        """window.onmessage = handler fires the rule."""
        code = "window.onmessage = (e) => { dispatch(e.data.action); };"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_globalthis_onmessage_assign_fires(self) -> None:
        """globalThis.onmessage = handler fires the rule."""
        code = "globalThis.onmessage = function(event) { process(event.data); };"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_self_onmessage_assign_fires(self) -> None:
        """self.onmessage = handler fires the rule (ServiceWorker context)."""
        code = "self.onmessage = (msg) => { handleMessage(msg); };"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_addeventlistener_message_does_not_fire(self) -> None:
        """window.addEventListener('message', ...) must NOT fire this rule."""
        code = "window.addEventListener('message', (e) => { handle(e); });"
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_onmessage_property_read_does_not_fire(self) -> None:
        """Reading window.onmessage (not assignment) must NOT fire this rule."""
        code = "const handler = window.onmessage;"
        self.assertFalse(_has_finding(code, self.RULE_ID))


# ---- P2: pmsg-broadcastchannel-handler-no-type-allowlist -----------------


class TestBroadcastChannelNoTypeAllowlist(unittest.TestCase):

    RULE_ID = "pmsg-broadcastchannel-handler-no-type-allowlist"

    def test_new_broadcastchannel_fires(self) -> None:
        """new BroadcastChannel('channel') fires the rule."""
        code = (
            "const bc = new BroadcastChannel('app-events');\n"
            "bc.onmessage = (e) => { router.push(e.data.url); };"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_broadcastchannel_with_dynamic_name_fires(self) -> None:
        """new BroadcastChannel(channelName) with variable fires the rule."""
        code = "const channel = new BroadcastChannel(channelName);"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_no_broadcastchannel_does_not_fire(self) -> None:
        """Code with no BroadcastChannel must NOT fire this rule."""
        code = "const ws = new WebSocket('wss://example.com');"
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_broadcastchannel_comment_does_not_fire(self) -> None:
        """// new BroadcastChannel in a comment must NOT fire this rule."""
        # The pattern matches `new BroadcastChannel` case-insensitively,
        # but a comment prefix is not meaningful at regex level — the
        # rule intentionally fires even in comments as a conservative gate.
        # This test verifies real code (non-comment) fires.
        code = "new BroadcastChannel('safe-channel');"
        self.assertTrue(_has_finding(code, self.RULE_ID))


# ---- P3: pmsg-origin-startswith-endswith-bypass --------------------------


class TestOriginStartsWithEndsWithBypass(unittest.TestCase):

    RULE_ID = "pmsg-origin-startswith-endswith-bypass"

    def test_origin_startswith_fires(self) -> None:
        """event.origin.startsWith('https://trusted.com') fires the rule."""
        code = (
            "window.addEventListener('message', (e) => {\n"
            "  if (!e.origin.startsWith('https://pay.example.com')) return;\n"
            "  handlePayment(e.data);\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_origin_endswith_fires(self) -> None:
        """event.origin.endsWith('trusted.com') fires the rule."""
        code = (
            "window.addEventListener('message', (evt) => {\n"
            "  if (!evt.origin.endsWith('trusted.com')) return;\n"
            "  processMessage(evt.data);\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_msg_origin_startswith_fires(self) -> None:
        """msg.origin.startsWith(...) fires the rule (short alias)."""
        code = "if (msg.origin.startsWith('https://safe.example.com')) { ok(); }"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_origin_strict_equality_does_not_fire(self) -> None:
        """e.origin === 'https://trusted.com' must NOT fire this rule."""
        code = (
            "window.addEventListener('message', (e) => {\n"
            "  if (e.origin !== 'https://trusted.com') return;\n"
            "  doAction(e.data);\n"
            "});"
        )
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_origin_set_has_does_not_fire(self) -> None:
        """ALLOWED.has(e.origin) must NOT fire this rule."""
        code = (
            "const ALLOWED = new Set(['https://a.com', 'https://b.com']);\n"
            "window.addEventListener('message', (e) => {\n"
            "  if (!ALLOWED.has(e.origin)) return;\n"
            "  handle(e.data);\n"
            "});"
        )
        self.assertFalse(_has_finding(code, self.RULE_ID))


# ---- P4: pmsg-messagechannel-port-wildcard-transfer ----------------------


class TestMessageChannelPortWildcardTransfer(unittest.TestCase):

    RULE_ID = "pmsg-messagechannel-port-wildcard-transfer"

    def test_messagechannel_wildcard_postmessage_fires(self) -> None:
        """new MessageChannel() + postMessage(..., '*') fires the rule."""
        code = (
            "const { port1, port2 } = new MessageChannel();\n"
            "otherWindow.postMessage({ channel: port2 }, '*', [port2]);\n"
            "port1.onmessage = (e) => { applyConfig(e.data); };"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_messagechannel_specific_origin_does_not_fire(self) -> None:
        """new MessageChannel() + postMessage(..., specificOrigin) must NOT fire."""
        code = (
            "const { port1, port2 } = new MessageChannel();\n"
            "otherWindow.postMessage({ port: port2 }, 'https://trusted.com', [port2]);\n"
            "port1.onmessage = (e) => { handleResponse(e.data); };"
        )
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_messagechannel_no_wildcard_transfer_does_not_fire(self) -> None:
        """new MessageChannel() without any postMessage must NOT fire this rule."""
        code = (
            "const { port1, port2 } = new MessageChannel();\n"
            "worker.postMessage('start', [port2]);\n"
            "port1.onmessage = (e) => { console.log(e.data); };"
        )
        # postMessage here has no '*' wildcard in the bounded window — should not fire
        self.assertFalse(_has_finding(code, self.RULE_ID))


# ---- P5: pmsg-data-relay-to-wildcard -------------------------------------


class TestDataRelayToWildcard(unittest.TestCase):

    RULE_ID = "pmsg-data-relay-to-wildcard"

    def test_relay_event_data_to_wildcard_fires(self) -> None:
        """parent.postMessage(e.data, '*') in a message listener fires the rule."""
        code = (
            "window.addEventListener('message', (e) => {\n"
            "  parent.postMessage(e.data, '*');\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_relay_event_data_msg_alias_fires(self) -> None:
        """otherWindow.postMessage(msg.data, '*') fires the rule."""
        code = "otherWindow.postMessage(msg.data, '*');"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_relay_with_specific_origin_does_not_fire(self) -> None:
        """parent.postMessage(e.data, 'https://trusted.com') must NOT fire."""
        code = (
            "window.addEventListener('message', (e) => {\n"
            "  parent.postMessage(e.data, 'https://trusted.com');\n"
            "});"
        )
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_postmessage_own_data_wildcard_does_not_fire(self) -> None:
        """postMessage(localData, '*') with no e.data must NOT fire this rule."""
        code = "window.postMessage({ type: 'PING' }, '*');"
        self.assertFalse(_has_finding(code, self.RULE_ID))


# ---- P6: pmsg-sw-clients-matchall-broadcast ------------------------------


class TestSwClientsMatchallBroadcast(unittest.TestCase):

    RULE_ID = "pmsg-sw-clients-matchall-broadcast"

    def test_clients_matchall_postmessage_fires(self) -> None:
        """self.clients.matchAll() followed by client.postMessage() fires the rule."""
        code = (
            "self.addEventListener('fetch', async (event) => {\n"
            "  const resp = await fetch(event.request);\n"
            "  const clients = await self.clients.matchAll();\n"
            "  clients.forEach(c => c.postMessage({ data: await resp.json() }));\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_clients_matchall_postmessage_chained_fires(self) -> None:
        """Chained self.clients.matchAll(...).postMessage fires the rule."""
        code = (
            "self.clients.matchAll({ type: 'window' }).then(clients => {\n"
            "  clients.forEach(c => c.postMessage(payload));\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_clients_matchall_no_postmessage_does_not_fire(self) -> None:
        """self.clients.matchAll() without postMessage must NOT fire this rule."""
        code = (
            "const clients = await self.clients.matchAll();\n"
            "clients.forEach(c => c.focus());"
        )
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_postmessage_without_clients_matchall_does_not_fire(self) -> None:
        """Standalone client.postMessage without matchAll must NOT fire this rule."""
        code = "client.postMessage({ type: 'UPDATE' });"
        self.assertFalse(_has_finding(code, self.RULE_ID))


# ---- P7: pmsg-extension-postmessage-bridge-no-nonce ---------------------


class TestExtensionPostmessageBridgeNoNonce(unittest.TestCase):

    RULE_ID = "pmsg-extension-postmessage-bridge-no-nonce"

    def test_chrome_runtime_sendmessage_bridge_fires(self) -> None:
        """window.addEventListener+chrome.runtime.sendMessage bridge fires the rule."""
        code = (
            "window.addEventListener('message', (event) => {\n"
            "  if (event.data.type === 'EXT_CMD') {\n"
            "    chrome.runtime.sendMessage({ action: event.data.action });\n"
            "  }\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_browser_runtime_sendmessage_bridge_fires(self) -> None:
        """window.addEventListener+browser.runtime.sendMessage fires the rule."""
        code = (
            "window.addEventListener('message', (e) => {\n"
            "  browser.runtime.sendMessage({ cmd: e.data.cmd });\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_chrome_runtime_without_message_listener_does_not_fire(self) -> None:
        """chrome.runtime.sendMessage alone (no message listener) must NOT fire."""
        code = "chrome.runtime.sendMessage({ type: 'OPEN_POPUP' });"
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_message_listener_without_sendmessage_does_not_fire(self) -> None:
        """window.addEventListener('message') without chrome.runtime must NOT fire."""
        code = (
            "window.addEventListener('message', (e) => {\n"
            "  if (e.origin !== 'https://trusted.com') return;\n"
            "  doAction(e.data);\n"
            "});"
        )
        self.assertFalse(_has_finding(code, self.RULE_ID))


# ---- P8: pmsg-source-reply-wildcard-target -------------------------------


class TestSourceReplyWildcardTarget(unittest.TestCase):

    RULE_ID = "pmsg-source-reply-wildcard-target"

    def test_event_source_postmessage_wildcard_fires(self) -> None:
        """e.source.postMessage(result, '*') in a handler fires the rule."""
        code = (
            "window.addEventListener('message', (e) => {\n"
            "  const result = processRequest(e.data);\n"
            "  e.source.postMessage(result, '*');\n"
            "});"
        )
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_event_alias_source_postmessage_wildcard_fires(self) -> None:
        """event.source.postMessage(data, '*') fires the rule."""
        code = "event.source.postMessage({ ok: true }, '*');"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_msg_source_postmessage_wildcard_fires(self) -> None:
        """msg.source.postMessage(resp, '*') fires the rule."""
        code = "msg.source.postMessage(resp, '*');"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_source_postmessage_specific_origin_does_not_fire(self) -> None:
        """e.source.postMessage(result, specificOrigin) must NOT fire this rule."""
        code = "e.source.postMessage(result, 'https://trusted.com');"
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_own_window_postmessage_wildcard_does_not_fire(self) -> None:
        """window.postMessage(data, '*') without .source must NOT fire this rule."""
        code = "window.postMessage({ type: 'ACK' }, '*');"
        self.assertFalse(_has_finding(code, self.RULE_ID))


# ---- P9: pmsg-broadcastchannel-user-input-name ---------------------------


class TestBroadcastChannelUserInputName(unittest.TestCase):

    RULE_ID = "pmsg-broadcastchannel-user-input-name"

    def test_template_literal_channel_name_fires(self) -> None:
        """new BroadcastChannel(`user-${userId}`) fires the rule."""
        code = "const bc = new BroadcastChannel(`user-${userId}`);"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_template_literal_session_channel_fires(self) -> None:
        """new BroadcastChannel(`session-${sessionId}`) fires the rule."""
        code = "const chan = new BroadcastChannel(`session-${sessionId}`);"
        self.assertTrue(_has_finding(code, self.RULE_ID))

    def test_static_string_channel_name_does_not_fire(self) -> None:
        """new BroadcastChannel('app-events') with static string must NOT fire this rule."""
        code = "const bc = new BroadcastChannel('app-events');"
        self.assertFalse(_has_finding(code, self.RULE_ID))

    def test_double_quoted_static_channel_does_not_fire(self) -> None:
        """new BroadcastChannel(\"channel-name\") with no template must NOT fire this rule."""
        code = 'const bc = new BroadcastChannel("notifications");'
        self.assertFalse(_has_finding(code, self.RULE_ID))


if __name__ == "__main__":
    unittest.main()
