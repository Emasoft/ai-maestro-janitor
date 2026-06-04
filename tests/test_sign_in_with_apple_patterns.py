"""Tests for scripts/lib/sign_in_with_apple_patterns.py.

Pattern-coverage tests for the Wave-31 distillation round 17 SIWA catalogue
(6 Sign in with Apple trust-chain failure patterns). Each rule gets a
positive test for the canonical shape PLUS at least one negative test
exercising the context filter / carve-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import sign_in_with_apple_patterns as siwa  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# PEM markers are split at module level so no contiguous real-format PEM
# header/footer exists at rest in this file. The detector still receives
# the fully-assembled string at runtime (byte-identical), so coverage is
# unchanged.
_PEM_EC_BEGIN = "-----BEGIN EC " + "PRIVATE KEY-----"
_PEM_EC_END = "-----END EC " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must be a tuple covering all 6 documented rule IDs."""
    assert isinstance(siwa.RULES, tuple)
    rule_ids = {r.id for r in siwa.RULES}
    expected = {
        "siwa-jwt-aud-not-validated",
        "siwa-jwt-iss-not-pinned",
        "siwa-private-email-truthy-string",
        "siwa-revoke-url-dynamic-construction",
        "siwa-apple-id-implicit-reauth",
        "siwa-apple-private-key-in-bundle",
    }
    assert expected == rule_ids
    assert len(siwa.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a non-empty ASI- prefix and a known severity level."""
    for rule in siwa.RULES:
        assert "ASI-" in rule.owasp_asi, rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding NamedTuple must expose all seven expected fields."""
    f = siwa.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-01",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-01"


def test_scan_text_empty_string_returns_empty_list() -> None:
    """scan_text('') must return an empty list without raising."""
    assert siwa.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[siwa.Finding]:
    return [f for f in siwa.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule S1 : siwa-jwt-aud-not-validated -------------------------


def test_s1_fires_on_jwt_decode_without_audience() -> None:
    """jwt.decode with RS256 and no audience parameter triggers S1."""
    src = (
        "decoded = jwt.decode(\n"
        "    identity_token,\n"
        "    apple_public_key,\n"
        "    algorithms=['RS256'],\n"
        ")\n"
        "user_id = decoded['sub']\n"
    )
    assert _hits("siwa-jwt-aud-not-validated", src)


def test_s1_fires_on_jwt_verify_without_audience() -> None:
    """jwt.verify with algorithms=['RS256'] and no audience triggers S1."""
    src = (
        "const payload = jwt.verify(identityToken, applePublicKey, {\n"
        "  algorithms: ['RS256'],\n"
        "});\n"
    )
    assert _hits("siwa-jwt-aud-not-validated", src)


def test_s1_suppressed_when_audience_present() -> None:
    """Explicit audience parameter suppresses S1."""
    src = (
        "decoded = jwt.decode(\n"
        "    identity_token,\n"
        "    apple_public_key,\n"
        "    algorithms=['RS256'],\n"
        "    audience='com.example.myapp',\n"
        ")\n"
    )
    assert not _hits("siwa-jwt-aud-not-validated", src)


def test_s1_suppressed_when_aud_kwarg_present() -> None:
    """aud= keyword argument suppresses S1."""
    src = (
        "const payload = jwt.verify(tok, key, {\n"
        "  algorithms: ['RS256'],\n"
        "  audience: 'com.example.app',\n"
        "});\n"
    )
    assert not _hits("siwa-jwt-aud-not-validated", src)


# ---------- Rule S2 : siwa-jwt-iss-not-pinned ----------------------------


def test_s2_fires_on_decoded_sub_without_iss_pin() -> None:
    """decoded['sub'] accessed in a file with no appleid.apple.com reference triggers S2."""
    src = (
        "decoded = jwt.decode(identity_token, key, algorithms=['RS256'],\n"
        "                     audience='com.example.app')\n"
        "# BUG: no iss check\n"
        "user_sub = decoded['sub']\n"
        "store_user(user_sub)\n"
    )
    assert _hits("siwa-jwt-iss-not-pinned", src)


def test_s2_fires_on_payload_dot_sub_without_iss_pin() -> None:
    """payload.sub trust without iss check fires S2 when no appleid domain present."""
    src = (
        "const userId = payload.sub;\n"
        "await db.upsertUser(userId);\n"
    )
    assert _hits("siwa-jwt-iss-not-pinned", src)


def test_s2_suppressed_when_iss_pinned_in_file() -> None:
    """appleid.apple.com anywhere in the file suppresses S2 globally."""
    src = (
        "if decoded['iss'] != 'https://appleid.apple.com':\n"
        "    raise ValueError('invalid issuer')\n"
        "user_sub = decoded['sub']\n"
    )
    assert not _hits("siwa-jwt-iss-not-pinned", src)


def test_s2_suppressed_when_appleid_domain_referenced() -> None:
    """Reference to appleid.apple.com domain (any context) suppresses S2."""
    src = (
        "APPLE_JWKS_URL = 'https://appleid.apple.com/auth/keys'\n"
        "user_id = decoded['sub']\n"
    )
    assert not _hits("siwa-jwt-iss-not-pinned", src)


# ---------- Rule S3 : siwa-private-email-truthy-string -------------------


def test_s3_fires_on_raw_is_private_email_truthy_test() -> None:
    """is_private_email used without string equality check triggers S3."""
    src = (
        "decoded = verify_apple_jwt(identity_token)\n"
        "is_private = decoded['is_private_email']\n"
        "if is_private:\n"
        "    decoded['email'] = None\n"
    )
    assert _hits("siwa-private-email-truthy-string", src)


def test_s3_fires_on_dot_access_without_string_cmp() -> None:
    """decoded.is_private_email without equality check triggers S3."""
    src = (
        "if (decoded.is_private_email) {\n"
        "  hideEmail(decoded);\n"
        "}\n"
    )
    assert _hits("siwa-private-email-truthy-string", src)


def test_s3_suppressed_when_string_equality_present() -> None:
    """Explicit == 'true' comparison in the nearby window suppresses S3."""
    src = (
        "is_private = decoded['is_private_email']\n"
        "if is_private_email == 'true':\n"
        "    decoded['email'] = None\n"
    )
    assert not _hits("siwa-private-email-truthy-string", src)


def test_s3_suppressed_when_triple_equals_string_cmp() -> None:
    """JS === 'true' string comparison suppresses S3."""
    src = (
        "const isPrivate = decoded.is_private_email;\n"
        "if (is_private_email === 'true') {\n"
        "  suppressEmail();\n"
        "}\n"
    )
    assert not _hits("siwa-private-email-truthy-string", src)


# ---------- Rule S4 : siwa-revoke-url-dynamic-construction ---------------


def test_s4_fires_on_python_fstring_iss_revoke_url() -> None:
    """Python f-string interpolating iss into /auth/revoke triggers S4."""
    src = (
        "issuer = decoded_token.get('iss', 'https://appleid.apple.com')\n"
        "revoke_url = f\"{issuer}/auth/revoke\"\n"
        "requests.post(revoke_url, data={...})\n"
    )
    assert _hits("siwa-revoke-url-dynamic-construction", src)


def test_s4_fires_on_non_canonical_apple_domain() -> None:
    """Non-canonical subdomain after apple.com in revoke URL triggers S4."""
    src = (
        "const APPLE_REVOKE_URL = "
        "'https://appleid.apple.com.internal/auth/revoke';\n"
    )
    assert _hits("siwa-revoke-url-dynamic-construction", src)


def test_s4_does_not_fire_on_canonical_hardcoded_url() -> None:
    """Canonical hardcoded appleid.apple.com revoke URL does not trigger S4."""
    src = (
        "REVOKE_URL = 'https://appleid.apple.com/auth/revoke'\n"
        "requests.post(REVOKE_URL, data={'token': tok})\n"
    )
    assert not _hits("siwa-revoke-url-dynamic-construction", src)


def test_s4_fires_on_js_template_literal_iss_revoke() -> None:
    """JavaScript template literal interpolating iss into /auth/revoke triggers S4."""
    src = (
        "const revokeUrl = `${iss}/auth/revoke`;\n"
        "await fetch(revokeUrl, { method: 'POST' });\n"
    )
    assert _hits("siwa-revoke-url-dynamic-construction", src)


# ---------- Rule S5 : siwa-apple-id-implicit-reauth ----------------------


def test_s5_fires_on_create_request_without_login_operation() -> None:
    """createRequest() + performRequests() without .login operation triggers S5."""
    src = (
        "let provider = ASAuthorizationAppleIDProvider()\n"
        "let request = provider.createRequest()\n"
        "request.requestedScopes = [.fullName, .email]\n"
        "let controller = ASAuthorizationController(authorizationRequests: [request])\n"
        "controller.delegate = self\n"
        "controller.performRequests()\n"
    )
    assert _hits("siwa-apple-id-implicit-reauth", src)


def test_s5_fires_on_expo_sign_in_async_without_requested_operation() -> None:
    """expo-apple-authentication signInAsync without requestedOperation triggers S5."""
    src = (
        "const credential = await AppleAuthentication.signInAsync({\n"
        "  requestedScopes: [\n"
        "    AppleAuthentication.AppleAuthenticationScope.FULL_NAME,\n"
        "    AppleAuthentication.AppleAuthenticationScope.EMAIL,\n"
        "  ],\n"
        "});\n"
    )
    assert _hits("siwa-apple-id-implicit-reauth", src)


def test_s5_suppressed_when_login_operation_set() -> None:
    """Explicit requestedOperation = .login in same window suppresses S5."""
    src = (
        "let request = provider.createRequest()\n"
        "request.requestedOperation = .login\n"
        "request.requestedScopes = [.fullName]\n"
        "controller.performRequests()\n"
    )
    assert not _hits("siwa-apple-id-implicit-reauth", src)


def test_s5_suppressed_when_expo_has_requested_operation() -> None:
    """expo signInAsync with requestedOperation field suppresses S5."""
    src = (
        "const credential = await AppleAuthentication.signInAsync({\n"
        "  requestedOperation: AppleAuthentication.AppleAuthenticationOperation.LOGIN,\n"
        "  requestedScopes: [\n"
        "    AppleAuthentication.AppleAuthenticationScope.EMAIL,\n"
        "  ],\n"
        "});\n"
    )
    assert not _hits("siwa-apple-id-implicit-reauth", src)


# ---------- Rule S6 : siwa-apple-private-key-in-bundle -------------------


def test_s6_fires_on_apple_pem_block_with_apple_context() -> None:
    """Apple .p8 PEM block in a file that mentions 'apple' triggers S6."""
    src = (
        "# Apple Sign In configuration\n"
        "APPLE_TEAM_ID = 'ABC1234567'\n"
        "APPLE_KEY_ID = 'XYZ9876543'\n"
        "APPLE_PRIVATE_KEY = '''\n"
        f"{_PEM_EC_BEGIN}\n"
        "MHQCAQEEIOaFMxdkEhAoNMRpGPSrPqBWn4WXtJFzFHmDpNxyzABCoAoGCCqGSM49\n"
        "AwEHoWQDYgAEabcdefghijklmnopqrstuvwxyz0123456789ABCDEF\n"
        f"{_PEM_EC_END}\n"
        "'''\n"
    )
    assert _hits("siwa-apple-private-key-in-bundle", src)


def test_s6_fires_on_vite_apple_private_key_env_var() -> None:
    """VITE_APPLE_PRIVATE_KEY environment variable triggers S6."""
    src = (
        "# .env — should not be committed!\n"
        "VITE_APPLE_PRIVATE_KEY=MEECAQAwEwYHKoZIzj0CAQYIKoZIzj0DAQcEJzAl\n"  # gitleaks:allow  pragma: allowlist secret
    )
    assert _hits("siwa-apple-private-key-in-bundle", src)


def test_s6_fires_on_next_public_apple_secret() -> None:
    """NEXT_PUBLIC_APPLE_SECRET environment variable triggers S6."""
    src = (
        "NEXT_PUBLIC_APPLE_SECRET=some-secret-value\n"
    )
    assert _hits("siwa-apple-private-key-in-bundle", src)


def test_s6_does_not_fire_on_pem_block_without_apple_context() -> None:
    """PEM block in a non-Apple file (no apple keyword) does not trigger S6."""
    src = (
        "# Generic RSA key for internal service\n"
        f"{_PEM_EC_BEGIN}\n"
        "MHQCAQEEIOaFMxdkEhAoNMRpGPSrPqBWn4WXtJFzFHmDpNxyzABCoAoGCCqGSM49\n"
        "AwEHoWQDYgAEabcdefghijklmnopqrstuvwxyz0123456789ABCDEF\n"
        f"{_PEM_EC_END}\n"
    )
    assert not _hits("siwa-apple-private-key-in-bundle", src)


def test_s6_does_not_fire_on_vite_apple_client_id_only() -> None:
    """VITE_APPLE_CLIENT_ID (legitimately public) does not trigger S6."""
    src = (
        "VITE_APPLE_CLIENT_ID=com.example.myapp\n"
    )
    assert not _hits("siwa-apple-private-key-in-bundle", src)
