"""Tests for scripts/lib/apns_fcm_push_patterns.py.

Pattern-coverage tests for the Wave-35 distill-round-21 angle
"APNS / FCM push notification security" catalogue (10 anti-patterns).

2 tests per rule (one positive exercising the canary, one negative
exercising the suppression / context filter), plus data-model sanity
checks, per the Wave-35 contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import apns_fcm_push_patterns as afp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# Prefixes are assembled from fragments at runtime so no contiguous real-format
# secret literal exists in this file at rest. Detectors receive the fully-
# assembled string byte-identically; secret scanners see only the fragments.
_PEM_RSA_BEGIN = "-----BEGIN RSA " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs with pn- prefix."""
    assert isinstance(afp.RULES, tuple)
    rule_ids = {r.id for r in afp.RULES}
    expected = {
        "pn-fcm-v1-service-account-key-committed",
        "pn-apns-jwt-credentials-inline",
        "pn-device-token-no-validation",
        "pn-apns-silent-push-unchecked-background-exec",
        "pn-fcm-topic-subscribe-wildcard",
        "pn-apns-token-auth-no-rotation",
        "pn-fcm-data-message-untrusted-origin",
        "pn-voip-push-no-call-validation",
        "pn-vapid-key-no-rotation-path",
        "pn-fcm-payload-size-exhaustion",
    }
    assert expected == rule_ids
    assert len(afp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule must have a valid ASI- tag and a known severity."""
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in afp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), f"{rule.id} bad owasp_asi"
        assert rule.severity in valid_severities, f"{rule.id} bad severity"
        assert rule.description.strip(), f"{rule.id} empty description"
        assert rule.name.strip(), f"{rule.id} empty name"


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror push_notifications_patterns.Finding shape."""
    f = afp.Finding(
        rule_id="pn-test",
        line=1,
        column=5,
        matched_text="x",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "pn-test"
    assert f.line == 1
    assert f.column == 5
    assert f.matched_text == "x"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """scan_text('') must short-circuit to []."""
    assert afp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings must be sorted (line, col, rule_id) for determinism."""
    src = (
        'APNS_AUTH_TOKEN = generate_apns_jwt(key=k)\n'
        '"type": "service_account", '
        '"client_email": "firebase-adminsdk-abc@proj.iam.gserviceaccount.com"\n'
    )
    findings = afp.scan_text(src)
    if len(findings) >= 2:
        for a, b in zip(findings, findings[1:]):
            assert (a.line, a.column, a.rule_id) <= (b.line, b.column, b.rule_id)


# ---------- pn-fcm-v1-service-account-key-committed ----------------------


def test_fcm_v1_sa_key_positive() -> None:
    """Detects Firebase Admin SDK service-account JSON with firebase-adminsdk email."""
    src = (
        '{\n'
        '  "type": "service_account",\n'
        '  "project_id": "my-app-prod",\n'
        '  "private_key_id": "abc123",\n'
        f'  "private_key": "{_PEM_RSA_BEGIN}\\n...",\n'
        '  "client_email": "firebase-adminsdk-xxxx@my-app-prod.iam.gserviceaccount.com"\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-v1-service-account-key-committed" in ids


def test_fcm_v1_sa_key_negative_generic_service_account() -> None:
    """Does NOT flag a non-Firebase service-account (no firebase-adminsdk)."""
    src = (
        '{\n'
        '  "type": "service_account",\n'
        '  "client_email": "myapp@my-project.iam.gserviceaccount.com"\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-v1-service-account-key-committed" not in ids


# ---------- pn-apns-jwt-credentials-inline --------------------------------


def test_apns_jwt_credentials_positive() -> None:
    """Detects inline key_id + team_id 10-char pair in Python config."""
    src = (
        'client = APNSClient(\n'
        '    key_id="ABC1234567",\n'
        '    team_id="TEAMID0001",\n'
        ')\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-apns-jwt-credentials-inline" in ids


def test_apns_jwt_credentials_negative_env_refs() -> None:
    """Does NOT flag when key_id/team_id values come from env-var placeholders."""
    src = (
        'client = APNSClient(\n'
        '    key_id=os.environ["APNS_KEY_ID"],\n'
        '    team_id=os.environ["APNS_TEAM_ID"],\n'
        ')\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-apns-jwt-credentials-inline" not in ids


# ---------- pn-device-token-no-validation ---------------------------------


def test_device_token_no_validation_positive() -> None:
    """Detects bare INSERT INTO device_tokens without validation."""
    src = (
        'def register(user_id, token):\n'
        '    db.execute(\n'
        '        "INSERT INTO device_tokens (user_id, token) VALUES (?, ?)",\n'
        '        (user_id, token),\n'
        '    )\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-device-token-no-validation" in ids


def test_device_token_no_validation_negative_unrelated_table() -> None:
    """Does NOT flag INSERT into an unrelated table like 'users'."""
    src = (
        'db.execute(\n'
        '    "INSERT INTO users (id, name) VALUES (?, ?)",\n'
        '    (uid, name),\n'
        ')\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-device-token-no-validation" not in ids


# ---------- pn-apns-silent-push-unchecked-background-exec -----------------


def test_silent_push_exec_positive_swift() -> None:
    """Detects Swift handler using userInfo field to call URLSession."""
    src = (
        'func application(_ application: UIApplication,\n'
        '    didReceiveRemoteNotification userInfo: [AnyHashable: Any],\n'
        '    fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void) {\n'
        '    if let url = userInfo["action_url"] as? String {\n'
        '        URLSession.shared.dataTask(with: URL(string: url)!).resume()\n'
        '    }\n'
        '    completionHandler(.newData)\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-apns-silent-push-unchecked-background-exec" in ids


def test_silent_push_exec_negative_no_exec_call() -> None:
    """Does NOT flag a silent-push handler that only reads data — no exec call."""
    src = (
        'func application(_ application: UIApplication,\n'
        '    didReceiveRemoteNotification userInfo: [AnyHashable: Any],\n'
        '    fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void) {\n'
        '    let badge = userInfo["badge_count"] as? Int ?? 0\n'
        '    UIApplication.shared.applicationIconBadgeNumber = badge\n'
        '    completionHandler(.newData)\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-apns-silent-push-unchecked-background-exec" not in ids


# ---------- pn-fcm-topic-subscribe-wildcard -------------------------------


def test_fcm_topic_wildcard_positive_literal() -> None:
    """Detects hardcoded /topics/all subscription."""
    src = 'messaging.subscribeToTopic(token, "/topics/all")\n'
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-topic-subscribe-wildcard" in ids


def test_fcm_topic_wildcard_negative_named_topic() -> None:
    """Does NOT flag subscription to a specific named topic."""
    src = 'messaging.subscribeToTopic(token, "/topics/news-updates")\n'
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-topic-subscribe-wildcard" not in ids


# ---------- pn-apns-token-auth-no-rotation --------------------------------


def test_apns_token_no_rotation_positive() -> None:
    """Detects module-level APNS_AUTH_TOKEN assigned from generate_apns_jwt."""
    src = (
        'APNS_AUTH_TOKEN = generate_apns_jwt(\n'
        '    private_key=APNS_PRIVATE_KEY,\n'
        '    key_id=APNS_KEY_ID,\n'
        '    team_id=APNS_TEAM_ID,\n'
        ')\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-apns-token-auth-no-rotation" in ids


def test_apns_token_no_rotation_negative_inside_function() -> None:
    """Does NOT flag generate_apns_jwt called inside a rotation function body."""
    # The rule anchors on ^APNS_AUTH_TOKEN (start of line); indented code is safe.
    src = (
        'def rotate_apns_token():\n'
        '    APNS_AUTH_TOKEN = generate_apns_jwt(\n'
        '        private_key=APNS_PRIVATE_KEY,\n'
        '    )\n'
        '    return APNS_AUTH_TOKEN\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-apns-token-auth-no-rotation" not in ids


# ---------- pn-fcm-data-message-untrusted-origin --------------------------


def test_fcm_data_untrusted_origin_positive_kotlin() -> None:
    """Detects Kotlin onMessageReceived using message.data to call loadUrl."""
    src = (
        'override fun onMessageReceived(message: RemoteMessage) {\n'
        '    val action = message.data["action"] ?: return\n'
        '    val payload = message.data["payload"] ?: return\n'
        '    when (action) {\n'
        '        "load_url" -> webView.loadUrl(payload)\n'
        '    }\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-data-message-untrusted-origin" in ids


def test_fcm_data_untrusted_origin_negative_safe_display() -> None:
    """Does NOT flag onMessageReceived handler that only displays text."""
    src = (
        'override fun onMessageReceived(message: RemoteMessage) {\n'
        '    val title = message.data["title"] ?: return\n'
        '    showNotification(title)\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-data-message-untrusted-origin" not in ids


# ---------- pn-voip-push-no-call-validation --------------------------------


def test_voip_push_no_validation_positive_swift() -> None:
    """Detects Swift PushKit handler driving reportNewIncomingCall from payload."""
    src = (
        'func pushRegistry(_ registry: PKPushRegistry,\n'
        '    didReceiveIncomingPushWith payload: PKPushPayload,\n'
        '    for type: PKPushType) {\n'
        '    let callUUID = payload.dictionaryPayload["call_id"] as? String ?? UUID().uuidString\n'
        '    let handle  = payload.dictionaryPayload["caller"] as? String ?? "Unknown"\n'
        '    provider.reportNewIncomingCall(\n'
        '        with: UUID(uuidString: callUUID) ?? UUID(),\n'
        '        update: CXCallUpdate()\n'
        '    )\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-voip-push-no-call-validation" in ids


def test_voip_push_no_validation_negative_no_payload_usage() -> None:
    """Does NOT flag a VoIP handler that ignores the payload entirely."""
    src = (
        'func pushRegistry(_ registry: PKPushRegistry,\n'
        '    didReceiveIncomingPushWith payload: PKPushPayload,\n'
        '    for type: PKPushType) {\n'
        '    // Payload intentionally ignored; call info fetched from server.\n'
        '    fetchCallFromServer { callInfo in\n'
        '        provider.reportNewIncomingCall(with: callInfo.uuid, update: callInfo.update)\n'
        '    }\n'
        '}\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-voip-push-no-call-validation" not in ids


# ---------- pn-vapid-key-no-rotation-path ---------------------------------


def test_vapid_no_rotation_positive_node() -> None:
    """Detects Node.js VAPID key generation + writeFileSync to .env."""
    src = (
        'const vapidKeys = webpush.generateVAPIDKeys();\n'
        'fs.writeFileSync(".env", `VAPID_PRIVATE_KEY=${vapidKeys.privateKey}\\n`, { flag: "a" });\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-vapid-key-no-rotation-path" in ids


def test_vapid_no_rotation_negative_read_only() -> None:
    """Does NOT flag code that only reads an existing VAPID key from env."""
    src = (
        'const vapidPublicKey = process.env.VAPID_PUBLIC_KEY;\n'
        'const vapidPrivateKey = process.env.VAPID_PRIVATE_KEY;\n'
        'webpush.setVapidDetails("mailto:admin@example.com", vapidPublicKey, vapidPrivateKey);\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-vapid-key-no-rotation-path" not in ids


# ---------- pn-fcm-payload-size-exhaustion --------------------------------


def test_fcm_payload_exhaustion_positive() -> None:
    """Detects user.display_name assigned directly to notification_data title."""
    src = (
        'notification_data["title"] = user.display_name\n'
        'notification_data["body"] = comment.text\n'
        'send_fcm(notification_data, token)\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-payload-size-exhaustion" in ids


def test_fcm_payload_exhaustion_negative_unrelated_dict() -> None:
    """Does NOT flag assignment to an unrelated dict key (e.g. 'analytics_data')."""
    src = (
        'analytics_data["title"] = user.display_name\n'
        'analytics_data["body"] = comment.text\n'
    )
    findings = afp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "pn-fcm-payload-size-exhaustion" not in ids
