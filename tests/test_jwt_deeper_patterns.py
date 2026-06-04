"""Tests for scripts/lib/jwt_deeper_patterns.py.

Pattern-coverage tests for the Wave-21 distillation round 7 angle B
catalogue (JWT-specific attacks deeper than Wave 17/18). Each of the 15
rules gets 2-4 tests (positive / negative / edge / carve-out as
applicable).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import jwt_deeper_patterns as jdp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(jdp.RULES, tuple)
    rule_ids = {r.id for r in jdp.RULES}
    expected = {
        "jwt.algorithm-from-env-or-config",
        "jwt.verify-no-algorithms-allowlist",
        "jwt.vulnerable-library-version",
        "jwt.kid-header-used-as-unsafe-lookup",
        "jwt.jku-header-fetched-unrestricted",
        "jwt.x5u-header-fetched-unrestricted",
        "jwt.x5c-header-chain-trusted-inline",
        "jwt.decode-options-verify-signature-false",
        "jwt.unverified-claims-as-identity",
        "jwt.decode-missing-audience-or-issuer",
        "jwt.leeway-excessive-clock-skew",
        "jwt.long-exp-stateless-no-revocation",
        "jwt.token-in-url-querystring",
        "jwt.cookie-missing-httponly-secure",
        "jwt.rsa-key-with-hs-algorithm-allowed",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Every rule must declare an OWASP-ASI mapping + valid severity."""
    for rule in jdp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape."""
    f = jdp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-07"


def test_scan_empty_text() -> None:
    """Empty text yields zero findings (no exception, no crash)."""
    assert jdp.scan_text("") == []


# ---------- helper -------------------------------------------------------


def _hits(rule_id: str, text: str, *, filename: str = "") -> list:
    return [
        f for f in jdp.scan_text(text, filename=filename)
        if f.rule_id == rule_id
    ]


# ---------- Rule P1 : jwt.algorithm-from-env-or-config -------------------


def test_p1_algorithm_from_settings_attr_positive() -> None:
    """`algorithms=[settings.ALGORITHM]` (env-overridable) fires."""
    src = "jwt.decode(token, key, algorithms=[settings.ALGORITHM])\n"
    assert _hits("jwt.algorithm-from-env-or-config", src)


def test_p1_algorithm_from_os_getenv_positive() -> None:
    """`algorithm=os.getenv('JWT_ALG')` on encode side fires."""
    src = "jwt.encode(payload, secret, algorithm=os.getenv('JWT_ALG'))\n"
    assert _hits("jwt.algorithm-from-env-or-config", src)


def test_p1_algorithm_literal_string_does_not_fire() -> None:
    """`algorithms=['HS256']` (literal) must NOT fire — Wave 18 territory."""
    src = "jwt.decode(token, key, algorithms=['HS256'])\n"
    assert not _hits("jwt.algorithm-from-env-or-config", src)


def test_p1_algorithm_constant_uppercase_var_positive() -> None:
    """`algorithm=JWT_ALGORITHM` (ALL_CAPS module-level constant) fires."""
    src = "jwt.encode(payload, key, algorithm=JWT_ALGORITHM)\n"
    assert _hits("jwt.algorithm-from-env-or-config", src)


# ---------- Rule P2/P15 : jwt.verify-no-algorithms-allowlist -------------


def test_p2_verify_with_publickey_no_algorithms_positive() -> None:
    """`jsonwebtoken.verify(token, publicKey)` with no algorithms fires."""
    src = (
        "const decoded = jsonwebtoken.verify(token, publicKey);\n"
    )
    assert _hits("jwt.verify-no-algorithms-allowlist", src)


def test_p2_verify_with_pem_readfile_no_algorithms_positive() -> None:
    """`jwt.verify(token, fs.readFileSync('cert.pem'))` no algorithms fires."""
    src = (
        "const ok = jwt.verify(token, fs.readFileSync('cert.pem'));\n"
    )
    assert _hits("jwt.verify-no-algorithms-allowlist", src)


def test_p2_verify_with_algorithms_kwarg_does_not_fire() -> None:
    """When `algorithms:` is provided, do NOT fire."""
    src = (
        "const ok = jwt.verify(token, publicKey, "
        "{ algorithms: ['RS256'] });\n"
    )
    assert not _hits("jwt.verify-no-algorithms-allowlist", src)


def test_p2_verify_with_secret_string_only_does_not_fire() -> None:
    """`jwt.verify(token, secret)` with a plain non-pubkey name — Wave 17."""
    src = "const ok = jwt.verify(token, secret);\n"
    assert not _hits("jwt.verify-no-algorithms-allowlist", src)


# ---------- Rule P3/P12 : jwt.vulnerable-library-version ----------------


def test_p3_python_jose_3_3_0_pinned_positive() -> None:
    """`python-jose[cryptography]==3.3.0` in requirements.txt fires."""
    src = "python-jose[cryptography]==3.3.0\n"
    assert _hits(
        "jwt.vulnerable-library-version", src,
        filename="requirements.txt",
    )


def test_p3_jsonwebtoken_caret_8_pinned_positive() -> None:
    """`"jsonwebtoken": "^8.5.1"` in package.json fires."""
    src = '  "jsonwebtoken": "^8.5.1",\n'
    assert _hits(
        "jwt.vulnerable-library-version", src,
        filename="package.json",
    )


def test_p3_pyjwt_pre_2_pinned_positive() -> None:
    """`PyJWT<2.0` in requirements.txt fires."""
    src = "PyJWT<2.0\n"
    assert _hits(
        "jwt.vulnerable-library-version", src,
        filename="requirements.txt",
    )


def test_p3_python_jose_3_4_0_does_not_fire() -> None:
    """`python-jose==3.4.0` (post-fix) does NOT fire."""
    src = "python-jose==3.4.0\n"
    assert not _hits(
        "jwt.vulnerable-library-version", src,
        filename="requirements.txt",
    )


def test_p3_jsonwebtoken_9_5_pinned_does_not_fire() -> None:
    """`"jsonwebtoken": "^9.0.2"` (post-fix) does NOT fire."""
    src = '  "jsonwebtoken": "^9.0.2",\n'
    assert not _hits(
        "jwt.vulnerable-library-version", src,
        filename="package.json",
    )


def test_p3_outside_manifest_does_not_fire() -> None:
    """Same vulnerable line in a *.py file does NOT fire (manifest gate)."""
    src = 'pkg = "python-jose==3.3.0"\n'
    assert not _hits(
        "jwt.vulnerable-library-version", src,
        filename="config.py",
    )


def test_p3_jwt_decode_pinned_positive() -> None:
    """`"jwt-decode": "^3.1.2"` fires (decode-only misuse vector)."""
    src = '  "jwt-decode": "^3.1.2",\n'
    assert _hits(
        "jwt.vulnerable-library-version", src,
        filename="package.json",
    )


# ---------- Rule P4 : jwt.kid-header-used-as-unsafe-lookup --------------


def test_p4_kid_in_open_path_positive() -> None:
    """`open(f'keys/{kid}.pem')` flags path injection via kid."""
    src = (
        "header = jwt.get_unverified_header(token)\n"
        "kid = header['kid']\n"
        "with open(f'keys/{kid}.pem') as fh: key = fh.read()\n"
    )
    assert _hits("jwt.kid-header-used-as-unsafe-lookup", src)


def test_p4_kid_in_sql_query_positive() -> None:
    """SQL string-format with `kid =` plus parameter token fires."""
    src = (
        "cursor.execute(\"SELECT secret FROM keys WHERE kid = %s\", (kid,))\n"
    )
    assert _hits("jwt.kid-header-used-as-unsafe-lookup", src)


def test_p4_kid_with_allowlist_check_does_not_fire() -> None:
    """File-level `ALLOWED_KIDS` set suppresses (allowlist present)."""
    src = (
        "ALLOWED_KIDS = {'kid-1', 'kid-2'}\n"
        "header = jwt.get_unverified_header(token)\n"
        "kid = header['kid']\n"
        "with open(f'keys/{kid}.pem') as fh: key = fh.read()\n"
    )
    assert not _hits("jwt.kid-header-used-as-unsafe-lookup", src)


def test_p4_kid_node_readfilesync_positive() -> None:
    """Node `fs.readFileSync(\\`keys/${kid}.pem\\`)` fires."""
    src = "const key = fs.readFileSync(`keys/${kid}.pem`);\n"
    assert _hits("jwt.kid-header-used-as-unsafe-lookup", src)


# ---------- Rule P5 : jwt.jku-header-fetched-unrestricted ---------------


def test_p5_jku_requests_get_positive() -> None:
    """`requests.get(header['jku'])` fires."""
    src = (
        "header = jwt.get_unverified_header(token)\n"
        "jwks = requests.get(header['jku']).json()\n"
    )
    assert _hits("jwt.jku-header-fetched-unrestricted", src)


def test_p5_jku_axios_get_positive() -> None:
    """Node `axios.get(header.jku)` fires."""
    src = "const jwks = await axios.get(header.jku);\n"
    assert _hits("jwt.jku-header-fetched-unrestricted", src)


def test_p5_jku_with_allowlist_suppressed() -> None:
    """`TRUSTED_JWKS_URIS` allowlist suppresses."""
    src = (
        "TRUSTED_JWKS_URIS = {'https://idp.example.com/.well-known/jwks.json'}\n"
        "header = jwt.get_unverified_header(token)\n"
        "jwks = requests.get(header['jku']).json()\n"
    )
    assert not _hits("jwt.jku-header-fetched-unrestricted", src)


def test_p5_static_jwks_uri_does_not_fire() -> None:
    """Hardcoded JWKS URL does NOT fire."""
    src = (
        "jwks = requests.get('https://idp.example.com/.well-known/jwks.json').json()\n"
    )
    assert not _hits("jwt.jku-header-fetched-unrestricted", src)


# ---------- Rule P6 : jwt.x5u-header-fetched-unrestricted ---------------


def test_p6_x5u_requests_get_positive() -> None:
    """`requests.get(header['x5u'])` fires."""
    src = (
        "header = jwt.get_unverified_header(token)\n"
        "cert = requests.get(header['x5u']).text\n"
    )
    assert _hits("jwt.x5u-header-fetched-unrestricted", src)


def test_p6_x5u_axios_get_positive() -> None:
    """Node `axios.get(header.x5u)` fires."""
    src = "const cert = await axios.get(header.x5u);\n"
    assert _hits("jwt.x5u-header-fetched-unrestricted", src)


def test_p6_static_x5u_url_does_not_fire() -> None:
    """Hardcoded x5u URL does NOT fire."""
    src = "cert = requests.get('https://ca.example.com/cert.pem').text\n"
    assert not _hits("jwt.x5u-header-fetched-unrestricted", src)


# ---------- Rule P7 : jwt.x5c-header-chain-trusted-inline ---------------


def test_p7_x5c_zero_index_positive() -> None:
    """`header['x5c'][0]` read inline fires."""
    src = (
        "header = jwt.get_unverified_header(token)\n"
        "cert_pem = header['x5c'][0]\n"
    )
    assert _hits("jwt.x5c-header-chain-trusted-inline", src)


def test_p7_x5c_attr_access_positive() -> None:
    """Node `decoded.header.x5c[0]` fires."""
    src = "const certB64 = decoded.header.x5c[0];\n"
    assert _hits("jwt.x5c-header-chain-trusted-inline", src)


def test_p7_x5c_full_chain_iteration_does_not_fire() -> None:
    """`for cert in header['x5c']:` (chain walk) does NOT fire on element 0."""
    src = "for cert in header['x5c']: validate(cert)\n"
    assert not _hits("jwt.x5c-header-chain-trusted-inline", src)


# ---------- Rule P8 : jwt.decode-options-verify-signature-false ---------


def test_p8_verify_signature_false_positive() -> None:
    """`options={'verify_signature': False}` fires."""
    src = (
        "claims = jwt.decode(token, options={'verify_signature': False})\n"
    )
    assert _hits("jwt.decode-options-verify-signature-false", src)


def test_p8_verify_exp_false_positive() -> None:
    """`options={'verify_exp': False}` fires."""
    src = (
        "claims = jwt.decode(token, key, options={'verify_exp': False})\n"
    )
    assert _hits("jwt.decode-options-verify-signature-false", src)


def test_p8_legacy_verify_false_kwarg_positive() -> None:
    """`jwt.decode(..., verify=False)` (legacy PyJWT) fires."""
    src = "claims = jwt.decode(token, verify=False)\n"
    assert _hits("jwt.decode-options-verify-signature-false", src)


def test_p8_node_ignore_expiration_positive() -> None:
    """Node `jwt.verify(..., {ignoreExpiration: true})` fires."""
    src = "jwt.verify(token, secret, { ignoreExpiration: true });\n"
    assert _hits("jwt.decode-options-verify-signature-false", src)


def test_p8_normal_decode_does_not_fire() -> None:
    """Normal `jwt.decode(token, key, algorithms=['HS256'])` does NOT fire."""
    src = "claims = jwt.decode(token, key, algorithms=['HS256'])\n"
    assert not _hits("jwt.decode-options-verify-signature-false", src)


def test_p8_test_filename_suppresses() -> None:
    """test_*.py file legitimately uses verify=False for fixtures."""
    src = "claims = jwt.decode(token, verify=False)\n"
    assert not _hits(
        "jwt.decode-options-verify-signature-false",
        src, filename="test_decode.py",
    )


# ---------- Rule P8b : jwt.unverified-claims-as-identity ----------------


def test_p8b_get_unverified_claims_alone_positive() -> None:
    """Plain `jwt.get_unverified_claims(token)` (no real verify in file) fires."""
    src = (
        "user_id = jwt.get_unverified_claims(token)['sub']\n"
        "return get_user(user_id)\n"
    )
    assert _hits("jwt.unverified-claims-as-identity", src)


def test_p8b_with_real_verify_in_file_suppressed() -> None:
    """If file ALSO has a real `jwt.decode(token, key, algorithms=...)`, suppress."""
    src = (
        "header = jwt.get_unverified_header(token)\n"
        "key = get_key(header['kid'])\n"
        "claims = jwt.decode(token, key, algorithms=['RS256'])\n"
    )
    assert not _hits("jwt.unverified-claims-as-identity", src)


def test_p8b_jwt_decode_import_positive() -> None:
    """Importing the `jwt-decode` library fires (decode-only)."""
    src = "import jwtDecode from 'jwt-decode';\n"
    assert _hits("jwt.unverified-claims-as-identity", src)


# ---------- Rule P9 : jwt.decode-missing-audience-or-issuer -------------


def test_p9_decode_without_audience_positive() -> None:
    """`jwt.decode(token, key, algorithms=['HS256'])` with file aud in encode fires."""
    src = (
        "def issue():\n"
        "    return jwt.encode({'sub': 'u', 'aud': 'svcA'}, k, algorithm='HS256')\n"
        "def verify(token):\n"
        "    return jwt.decode(token, k, algorithms=['HS256'])\n"
    )
    assert _hits("jwt.decode-missing-audience-or-issuer", src)


def test_p9_decode_with_audience_kwarg_suppressed() -> None:
    """`jwt.decode(..., audience='svcA')` does NOT fire."""
    src = (
        "def issue():\n"
        "    return jwt.encode({'sub': 'u', 'aud': 'svcA'}, k, algorithm='HS256')\n"
        "def verify(token):\n"
        "    return jwt.decode(token, k, algorithms=['HS256'], audience='svcA')\n"
    )
    assert not _hits("jwt.decode-missing-audience-or-issuer", src)


def test_p9_decode_no_encode_with_aud_in_file_suppressed() -> None:
    """If the file never adds aud/iss in encode, presume relay-only — suppress."""
    src = "claims = jwt.decode(token, key, algorithms=['HS256'])\n"
    assert not _hits("jwt.decode-missing-audience-or-issuer", src)


# ---------- Rule P10 : jwt.leeway-excessive-clock-skew ------------------


def test_p10_leeway_3600_positive() -> None:
    """`leeway=3600` (1h) fires."""
    src = "claims = jwt.decode(token, key, leeway=3600)\n"
    assert _hits("jwt.leeway-excessive-clock-skew", src)


def test_p10_leeway_86400_positive() -> None:
    """`leeway=86400` (1 day) fires."""
    src = "claims = jwt.decode(token, key, leeway=86400)\n"
    assert _hits("jwt.leeway-excessive-clock-skew", src)


def test_p10_leeway_60_does_not_fire() -> None:
    """`leeway=60` (1 minute — RFC suggested) does NOT fire."""
    src = "claims = jwt.decode(token, key, leeway=60)\n"
    assert not _hits("jwt.leeway-excessive-clock-skew", src)


def test_p10_leeway_300_does_not_fire() -> None:
    """`leeway=300` (5 minutes exactly — boundary) does NOT fire."""
    src = "claims = jwt.decode(token, key, leeway=300)\n"
    assert not _hits("jwt.leeway-excessive-clock-skew", src)


def test_p10_clock_tolerance_large_positive() -> None:
    """Node `clockTolerance: 600` fires."""
    src = "jwt.verify(token, secret, { clockTolerance: 600 });\n"
    assert _hits("jwt.leeway-excessive-clock-skew", src)


def test_p10_leeway_timedelta_days_positive() -> None:
    """`leeway=timedelta(days=1)` fires."""
    src = "claims = jwt.decode(token, key, leeway=timedelta(days=1))\n"
    assert _hits("jwt.leeway-excessive-clock-skew", src)


# ---------- Rule P11 : jwt.long-exp-stateless-no-revocation -------------


def test_p11_access_token_expire_minutes_1440_positive() -> None:
    """`ACCESS_TOKEN_EXPIRE_MINUTES = 1440` (24h) fires when no revocation."""
    src = (
        "class Settings:\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440\n"
    )
    assert _hits("jwt.long-exp-stateless-no-revocation", src)


def test_p11_expires_in_24h_node_positive() -> None:
    """Node `expiresIn: '24h'` fires."""
    src = "const token = jwt.sign(payload, secret, { expiresIn: '24h' });\n"
    assert _hits("jwt.long-exp-stateless-no-revocation", src)


def test_p11_expires_in_7d_positive() -> None:
    """Node `expiresIn: '7d'` fires."""
    src = "const token = jwt.sign(payload, secret, { expiresIn: '7d' });\n"
    assert _hits("jwt.long-exp-stateless-no-revocation", src)


def test_p11_revocation_guard_suppresses() -> None:
    """File with revocation logic suppresses the long-exp finding."""
    src = (
        "class Settings:\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440\n"
        "def is_token_revoked(jti): return jti in revoked_tokens\n"
    )
    assert not _hits("jwt.long-exp-stateless-no-revocation", src)


def test_p11_expires_in_15m_does_not_fire() -> None:
    """Short-lived `expiresIn: '15m'` does NOT fire."""
    src = "const token = jwt.sign(payload, secret, { expiresIn: '15m' });\n"
    assert not _hits("jwt.long-exp-stateless-no-revocation", src)


# ---------- Rule P13 : jwt.token-in-url-querystring ---------------------


def test_p13_jwt_in_url_query_positive() -> None:
    """`?jwt=...` in a URL string fires."""
    src = "url = f'https://api.example.com/me?jwt={token}'\n"
    assert _hits("jwt.token-in-url-querystring", src)


def test_p13_id_token_in_url_positive() -> None:
    """`?id_token=...` in fetch fires."""
    src = "fetch(`https://api.example.com/me?id_token=${token}`)\n"
    assert _hits("jwt.token-in-url-querystring", src)


def test_p13_params_dict_jwt_positive() -> None:
    """`params={'jwt': tok}` in Python requests fires."""
    src = "requests.get(url, params={'jwt': token})\n"
    assert _hits("jwt.token-in-url-querystring", src)


def test_p13_token_in_auth_header_does_not_fire() -> None:
    """Token in `Authorization` header does NOT fire."""
    src = "requests.get(url, headers={'Authorization': f'Bearer {token}'})\n"
    assert not _hits("jwt.token-in-url-querystring", src)


# ---------- Rule P14 : jwt.cookie-missing-httponly-secure ---------------


def test_p14_cookie_no_flags_positive() -> None:
    """`res.cookie('token', val, {})` with no flags fires."""
    src = "res.cookie('token', accessToken, {});\n"
    assert _hits("jwt.cookie-missing-httponly-secure", src)


def test_p14_cookie_full_hardening_does_not_fire() -> None:
    """`res.cookie('jwt', tok, {httpOnly:true, secure:true, sameSite:'lax'})` OK."""
    src = (
        "res.cookie('jwt', tok, { httpOnly: true, secure: true, "
        "sameSite: 'lax' });\n"
    )
    assert not _hits("jwt.cookie-missing-httponly-secure", src)


def test_p14_python_set_cookie_no_flags_positive() -> None:
    """`response.set_cookie('jwt', value)` with no flags fires."""
    src = "response.set_cookie('jwt', value)\n"
    assert _hits("jwt.cookie-missing-httponly-secure", src)


def test_p14_cookie_missing_secure_only_positive() -> None:
    """HttpOnly + SameSite present but missing Secure — fires (any missing)."""
    src = (
        "res.cookie('access_token', tok, { httpOnly: true, "
        "sameSite: 'lax' });\n"
    )
    assert _hits("jwt.cookie-missing-httponly-secure", src)


# ---------- Rule P15 : jwt.rsa-key-with-hs-algorithm-allowed ------------


def test_p15_mixed_hs_rs_algorithms_python_positive() -> None:
    """`algorithms=['HS256', 'RS256']` (HS+RS mix) fires."""
    src = (
        "jwt.decode(token, public_key, algorithms=['HS256', 'RS256'])\n"
    )
    assert _hits("jwt.rsa-key-with-hs-algorithm-allowed", src)


def test_p15_mixed_rs_hs_node_positive() -> None:
    """Node `algorithms: ['RS256', 'HS256']` (reversed order) fires."""
    src = (
        "jwt.verify(token, fs.readFileSync('pub.pem'), "
        "{ algorithms: ['RS256', 'HS256'] });\n"
    )
    assert _hits("jwt.rsa-key-with-hs-algorithm-allowed", src)


def test_p15_only_rs256_does_not_fire() -> None:
    """`algorithms=['RS256']` alone (no HS) does NOT fire."""
    src = "jwt.decode(token, public_key, algorithms=['RS256'])\n"
    assert not _hits("jwt.rsa-key-with-hs-algorithm-allowed", src)


# ---------- Cross-cutting / scan integration ----------------------------


def test_findings_sorted_by_line_col_ruleid() -> None:
    """Multiple findings come back sorted by (line, col, rule_id)."""
    src = (
        "jwt.decode(token, key, algorithms=[settings.ALGORITHM])\n"
        "res.cookie('jwt', tok, {});\n"
    )
    out = jdp.scan_text(src)
    lines = [f.line for f in out]
    assert lines == sorted(lines)


def test_dedupe_by_rule_line_col() -> None:
    """The same match site at the same (rule,line,col) is reported once."""
    src = "jwt.decode(token, key, algorithms=[settings.ALGORITHM])\n"
    out = jdp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in out]
    assert len(keys) == len(set(keys))


def test_file_kind_kwarg_accepted() -> None:
    """`file_kind=` kwarg is accepted (parity with sibling modules)."""
    # Should not raise.
    jdp.scan_text("x = 1\n", file_kind="source")


def test_scan_text_returns_list() -> None:
    """Return type is always a list (never None / iterator)."""
    out = jdp.scan_text("")
    assert isinstance(out, list)
    out = jdp.scan_text("x = 1\n")
    assert isinstance(out, list)
