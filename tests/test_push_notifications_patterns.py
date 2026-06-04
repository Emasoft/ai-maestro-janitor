"""Tests for scripts/lib/push_notifications_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 angle
"push notifications" catalogue (6 anti-patterns covering APNs / FCM /
Web-Push / Twilio / MagicLink / SNS-SMS).

At least 2 tests per rule (one positive exercising the canary, one
negative exercising the carve-out / context filter) per the Wave-27
contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import push_notifications_patterns as pnp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# PEM markers are split at the space so the contiguous PEM header never
# exists at rest. Runtime value is byte-identical — coverage unchanged.
_PEM_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
_PEM_END = "-----END " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(pnp.RULES, tuple)
    rule_ids = {r.id for r in pnp.RULES}
    expected = {
        "push-apns-p8-auth-key-committed",
        "push-fcm-legacy-server-key-in-client-bundle",
        "push-vapid-private-key-in-client-bundle",
        "push-twilio-auth-token-in-client-bundle",
        "push-magiclink-token-no-expiry",
        "push-sns-topic-policy-principal-wildcard",
    }
    assert expected == rule_ids
    assert len(pnp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in pnp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = pnp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert pnp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — APNs .p8 filename
        "// see AuthKey_ABC123XYZ9.p8 attached in build secrets\n"
        # Line 2 — FCM legacy key
        "const FCM_SERVER_KEY = \"AAAA" + "x" * 145 + ":" + "y" * 150 + "\";\n"
    )
    findings = pnp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[pnp.Finding]:
    return [f for f in pnp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : push-apns-p8-auth-key-committed -------------------------


def test_p1_apns_p8_filename_flags() -> None:
    """Reference to an `AuthKey_<keyid>.p8` token → CRITICAL hit."""
    src = (
        "# Token-based APNs auth\n"
        "AUTH_KEY_PATH = 'config/AuthKey_ABC123XYZ9.p8'\n"
    )
    hits = _hits("push-apns-p8-auth-key-committed", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p1_pkcs8_body_with_apns_context_flags() -> None:
    """A PKCS#8 PRIVATE KEY block alongside an APNs context marker → flagged."""
    body_lines = "MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEH" * 20
    src = (
        "# apns provider config (token-based)\n"
        "key_id = 'ABC123XYZ9'\n"
        "team_id = 'TEAM12345Z'\n"
        f"{_PEM_BEGIN}\n"
        f"{body_lines}\n"
        f"{_PEM_END}\n"
    )
    assert _hits("push-apns-p8-auth-key-committed", src)


def test_p1_unrelated_pkcs8_block_no_apns_marker_silent() -> None:
    """Generic PKCS#8 block with no APNs context → no P1 hit (defer to generic detectors)."""
    body_lines = "MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEH" * 20
    src = (
        "# Stripe webhook signing config\n"
        f"{_PEM_BEGIN}\n"
        f"{body_lines}\n"
        f"{_PEM_END}\n"
    )
    assert not _hits("push-apns-p8-auth-key-committed", src)


def test_p1_no_p8_no_pkcs8_silent() -> None:
    """No APNs / no PKCS#8 → no hit."""
    src = "const config = { api: 'https://api.example.com' };\n"
    assert not _hits("push-apns-p8-auth-key-committed", src)


# ---------- P2 : push-fcm-legacy-server-key-in-client-bundle -------------


def test_p2_fcm_server_key_assign_flags() -> None:
    """`FCM_SERVER_KEY = "AAAA...:..."` → CRITICAL hit."""
    key = "AAAA" + "x" * 145 + ":" + "y" * 150
    src = f"const FCM_SERVER_KEY = \"{key}\";\n"
    hits = _hits("push-fcm-legacy-server-key-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p2_authorization_header_literal_flags() -> None:
    """`Authorization: key=AAAA...` header literal → flagged."""
    key = "AAAA" + "a" * 145 + ":" + "b" * 150
    src = (
        "await fetch('https://fcm.googleapis.com/fcm/send', {\n"
        f"  headers: {{ 'Authorization': 'key={key}' }}\n"
        "});\n"
    )
    assert _hits("push-fcm-legacy-server-key-in-client-bundle", src)


def test_p2_messaging_sender_id_safe_silent() -> None:
    """`messagingSenderId` is a digit-only public identifier → no hit."""
    src = (
        "const firebaseConfig = {\n"
        f"  apiKey: '{secret('AI' + 'za', 'push-p2-aiza', 35)}',\n"
        "  messagingSenderId: '766951619099',\n"
        "  appId: '1:766951619099:web:abc123def456'\n"
        "};\n"
    )
    assert not _hits("push-fcm-legacy-server-key-in-client-bundle", src)


def test_p2_short_aaaa_placeholder_not_flagged() -> None:
    """Short `AAAA…` placeholder (well below 150 chars) → no hit."""
    src = "const FCM_SERVER_KEY = 'AAAAPlaceholder';\n"
    assert not _hits("push-fcm-legacy-server-key-in-client-bundle", src)


# ---------- P3 : push-vapid-private-key-in-client-bundle -----------------


def test_p3_vapid_private_key_assign_flags() -> None:
    """`VAPID_PRIVATE_KEY = "<43-char>"` → HIGH hit."""
    priv = "ZHt2Rv" + "x" * 37  # 43 chars total
    src = f"const VAPID_PRIVATE_KEY = \"{priv}\";\n"
    hits = _hits("push-vapid-private-key-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p3_setvapiddetails_call_flags() -> None:
    """`webpush.setVapidDetails(subject, publicKey, privateKey)` → flagged."""
    pub = "BP" + "x" * 86  # 88 chars
    priv = "ZH" + "y" * 41  # 43 chars
    src = (
        "webpush.setVapidDetails(\n"
        "  'mailto:admin@example.com',\n"
        f"  '{pub}',\n"
        f"  '{priv}'\n"
        ");\n"
    )
    assert _hits("push-vapid-private-key-in-client-bundle", src)


def test_p3_public_only_assign_safe_silent() -> None:
    """`vapidKey = "<88-char-public-half>"` → no hit (public IS meant to be shared)."""
    pub = "BP" + "x" * 86  # 88 chars
    src = f"const vapidKey = \"{pub}\";\n"
    assert not _hits("push-vapid-private-key-in-client-bundle", src)


def test_p3_too_short_value_not_flagged() -> None:
    """`VAPID_PRIVATE_KEY = "short"` → no hit (placeholder shape)."""
    src = "const VAPID_PRIVATE_KEY = 'short-placeholder';\n"
    assert not _hits("push-vapid-private-key-in-client-bundle", src)


# ---------- P4 : push-twilio-auth-token-in-client-bundle -----------------


def test_p4_twilio_auth_token_with_account_sid_flags() -> None:
    """`TWILIO_AUTH_TOKEN = "<32-hex>"` paired with `ACxx…` SID → CRITICAL hit."""
    sid = "AC" + "0" * 32
    tok = "0123456789abcdef0123456789abcdef"
    src = (
        f"const TWILIO_ACCOUNT_SID = \"{sid}\";\n"
        f"const TWILIO_AUTH_TOKEN = \"{tok}\";\n"
        f"fetch(`https://api.twilio.com/2010-04-01/Accounts/${{TWILIO_ACCOUNT_SID}}/Messages.json`);\n"
    )
    hits = _hits("push-twilio-auth-token-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p4_python_paired_assignment_flags() -> None:
    """Python `twilio_auth_token = '<hex>'` paired with SID → flagged."""
    sid = "AC" + "f" * 32
    tok = "ffffffffffffffffffffffffffffffff"
    src = (
        f"TWILIO_ACCOUNT_SID = '{sid}'\n"
        f"twilio_auth_token = '{tok}'\n"
    )
    assert _hits("push-twilio-auth-token-in-client-bundle", src)


def test_p4_token_without_sid_silent() -> None:
    """Auth-token-shape variable WITHOUT a paired SID → no hit (too noisy alone)."""
    src = "const TWILIO_AUTH_TOKEN = '0123456789abcdef0123456789abcdef';\n"  # gitleaks:allow  pragma: allowlist secret
    assert not _hits("push-twilio-auth-token-in-client-bundle", src)


def test_p4_unrelated_hex32_with_md5_label_silent() -> None:
    """A 32-hex string assigned to an `md5`-style variable → no hit."""
    src = (
        "const md5 = '5d41402abc4b2a76b9719d911017c592';\n"
        "const etag = 'd41d8cd98f00b204e9800998ecf8427e';\n"
    )
    assert not _hits("push-twilio-auth-token-in-client-bundle", src)


# ---------- P5 : push-magiclink-token-no-expiry --------------------------


def test_p5_magiclink_insert_no_expiry_flags() -> None:
    """`INSERT INTO magic_links (user_id, token)` with no expiry anywhere → HIGH hit."""
    src = (
        "await db.execute(\n"
        "  \"INSERT INTO magic_links (user_id, token) VALUES ($1, $2)\",\n"
        "  [userId, token]\n"
        ");\n"
        "await sendPush({ to: user.fcm_token, data: { url: link } });\n"
    )
    hits = _hits("push-magiclink-token-no-expiry", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p5_otp_token_insert_no_expiry_flags() -> None:
    """`INSERT INTO otp_tokens` with no expiry anywhere → flagged."""
    src = (
        "cursor.execute(\n"
        "    \"INSERT INTO otp_tokens (user_id, code) VALUES (%s, %s)\",\n"
        "    (user_id, code),\n"
        ")\n"
    )
    assert _hits("push-magiclink-token-no-expiry", src)


def test_p5_magiclink_insert_with_expires_at_suppressed() -> None:
    """`INSERT INTO magic_links` with explicit `expires_at` column → no hit."""
    src = (
        "await db.execute(\n"
        "  \"INSERT INTO magic_links (user_id, token, expires_at) VALUES ($1, $2, NOW() + INTERVAL '15 minutes')\",\n"
        "  [userId, token]\n"
        ");\n"
    )
    assert not _hits("push-magiclink-token-no-expiry", src)


def test_p5_file_with_ttl_marker_suppresses() -> None:
    """File contains a `ttl` marker → suppress P5 (file-wide context)."""
    src = (
        "# magic_link table schema includes ttl seconds\n"
        "ttl_seconds = 900\n"
        "cursor.execute(\n"
        "    \"INSERT INTO magic_links (user_id, token) VALUES (%s, %s)\",\n"
        "    (user_id, token),\n"
        ")\n"
    )
    assert not _hits("push-magiclink-token-no-expiry", src)


# ---------- P6 : push-sns-topic-policy-principal-wildcard ----------------


def test_p6_sns_topic_policy_open_principal_flags() -> None:
    """SNS topic policy with `Principal: "*"` and sns:Publish/Subscribe → HIGH hit."""
    src = (
        "{\n"
        "  \"PolicyDocument\": {\n"
        "    \"Statement\": [{\n"
        "      \"Effect\": \"Allow\",\n"
        "      \"Principal\": \"*\",\n"
        "      \"Action\": [\"sns:Subscribe\", \"sns:Publish\"],\n"
        "      \"Resource\": \"*\"\n"
        "    }]\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("push-sns-topic-policy-principal-wildcard", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p6_terraform_sns_open_publish_flags() -> None:
    """HCL Terraform `Principal = "*"` near `sns:Publish` → flagged."""
    src = (
        "resource \"aws_sns_topic_policy\" \"default\" {\n"
        "  arn    = aws_sns_topic.push_events.arn\n"
        "  policy = jsonencode({\n"
        "    Statement = [{\n"
        "      Effect    = \"Allow\"\n"
        "      Principal = \"*\"\n"
        "      Action    = [\"sns:Publish\"]\n"
        "      Resource  = \"*\"\n"
        "    }]\n"
        "  })\n"
        "}\n"
    )
    assert _hits("push-sns-topic-policy-principal-wildcard", src)


def test_p6_sns_policy_with_source_arn_condition_suppressed() -> None:
    """SNS policy with `aws:SourceArn` Condition → no hit (constrained)."""
    src = (
        "{\n"
        "  \"Statement\": [{\n"
        "    \"Effect\": \"Allow\",\n"
        "    \"Principal\": \"*\",\n"
        "    \"Action\": [\"sns:Subscribe\"],\n"
        "    \"Resource\": \"*\",\n"
        "    \"Condition\": {\n"
        "      \"StringEquals\": {\n"
        "        \"aws:SourceArn\": \"arn:aws:s3:::my-bucket\"\n"
        "      }\n"
        "    }\n"
        "  }]\n"
        "}\n"
    )
    assert not _hits("push-sns-topic-policy-principal-wildcard", src)


def test_p6_sns_with_scoped_principal_silent() -> None:
    """SNS policy with a scoped `Principal` (specific account ARN) → no hit."""
    src = (
        "{\n"
        "  \"Statement\": [{\n"
        "    \"Effect\": \"Allow\",\n"
        "    \"Principal\": {\"AWS\": \"arn:aws:iam::123456789012:root\"},\n"
        "    \"Action\": [\"sns:Subscribe\"],\n"
        "    \"Resource\": \"*\"\n"
        "  }]\n"
        "}\n"
    )
    assert not _hits("push-sns-topic-policy-principal-wildcard", src)
