"""Tests for scripts/lib/kerberos_spnego_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 Kerberos /
SPNEGO / GSSAPI misconfiguration catalogue (9 rules). Each rule has at
least two tests: one positive (canary must fire) and one negative
(carve-out or context filter must suppress the finding).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import kerberos_spnego_patterns as ksp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs."""
    assert isinstance(ksp.RULES, tuple)
    rule_ids = {r.id for r in ksp.RULES}
    expected = {
        "krb-rc4-hmac-etype-permitted",
        "krb-preauth-disabled-kdc-config",
        "krb-forwardable-tickets-global",
        "krb-dns-canonicalize-hostname",
        "krb-spnego-http-no-origin-binding",
        "krb-gssapi-ntlm-fallback-mechoid",
        "krb-jaas-keytab-no-principal",
        "krb-dotnet-negotiate-delegation",
        "krb-gmsa-password-extraction",
    }
    assert expected == rule_ids
    assert len(ksp.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ksp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = ksp.Finding(
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
    assert ksp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — rc4-hmac weak crypto
        "allow_weak_crypto = true\n"
        # Line 2 — GMSA extraction
        "msDS-ManagedPassword\n"
    )
    findings = ksp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[ksp.Finding]:
    return [f for f in ksp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : krb-rc4-hmac-etype-permitted ----------------------------


def test_p1_allow_weak_crypto_true_flags() -> None:
    """allow_weak_crypto = true in krb5.conf triggers HIGH finding."""
    src = "[libdefaults]\n    allow_weak_crypto = true\n    default_realm = CORP.EXAMPLE.COM\n"
    hits = _hits("krb-rc4-hmac-etype-permitted", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p1_rc4_hmac_in_etype_list_flags() -> None:
    """rc4-hmac in default_tkt_enctypes triggers finding when [libdefaults] present."""
    src = (
        "[libdefaults]\n"
        "    default_tkt_enctypes = rc4-hmac aes256-cts-hmac-sha1-96\n"
        "    default_realm = CORP.EXAMPLE.COM\n"
    )
    hits = _hits("krb-rc4-hmac-etype-permitted", src)
    assert hits


def test_p1_arcfour_hmac_md5_in_default_etypes_flags() -> None:
    """arcfour-hmac-md5 alias in default_etypes triggers finding."""
    src = (
        "[libdefaults]\n"
        "    default_etypes = arcfour-hmac-md5 des3-cbc-sha1\n"
    )
    hits = _hits("krb-rc4-hmac-etype-permitted", src)
    assert hits


def test_p1_aes_only_no_hit() -> None:
    """AES-only etype list in krb5.conf does not flag."""
    src = (
        "[libdefaults]\n"
        "    default_tkt_enctypes = aes256-cts-hmac-sha1-96 aes128-cts-hmac-sha1-96\n"
        "    allow_weak_crypto = false\n"
    )
    assert not _hits("krb-rc4-hmac-etype-permitted", src)


def test_p1_rc4_hmac_without_libdefaults_section_silent() -> None:
    """rc4-hmac in etype list without [libdefaults] section does not flag (FP guard)."""
    src = "    default_tkt_enctypes = rc4-hmac aes256-cts-hmac-sha1-96\n"
    assert not _hits("krb-rc4-hmac-etype-permitted", src)


# ---------- P2 : krb-preauth-disabled-kdc-config -------------------------


def test_p2_require_preauth_false_flags() -> None:
    """require_preauth = false in kdc.conf triggers CRITICAL finding."""
    src = "[kdcdefaults]\n    require_preauth = false\n"
    hits = _hits("krb-preauth-disabled-kdc-config", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p2_restrict_anonymous_to_tgt_false_flags() -> None:
    """restrict_anonymous_to_tgt = false triggers finding."""
    src = "[kdcdefaults]\n    restrict_anonymous_to_tgt = false\n"
    assert _hits("krb-preauth-disabled-kdc-config", src)


def test_p2_kadmin_remove_preauth_flags() -> None:
    """kadmin modprinc -requires_preauth triggers finding."""
    src = 'kadmin.local -q "modprinc -requires_preauth svc_app@REALM"\n'
    assert _hits("krb-preauth-disabled-kdc-config", src)


def test_p2_kadmin_add_preauth_safe() -> None:
    """kadmin modprinc +requires_preauth (adding the flag) does not flag."""
    src = 'kadmin.local -q "modprinc +requires_preauth user@REALM"\n'
    assert not _hits("krb-preauth-disabled-kdc-config", src)


def test_p2_require_preauth_true_silent() -> None:
    """require_preauth = true does not flag."""
    src = "[kdcdefaults]\n    require_preauth = true\n"
    assert not _hits("krb-preauth-disabled-kdc-config", src)


# ---------- P3 : krb-forwardable-tickets-global --------------------------


def test_p3_forwardable_true_flags() -> None:
    """forwardable = true triggers HIGH finding."""
    src = "[libdefaults]\n    forwardable = true\n    default_realm = CORP.EXAMPLE.COM\n"
    hits = _hits("krb-forwardable-tickets-global", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p3_proxiable_true_flags() -> None:
    """proxiable = true triggers finding."""
    src = "[libdefaults]\n    proxiable = true\n"
    assert _hits("krb-forwardable-tickets-global", src)


def test_p3_gssapi_delegate_to_peer_flags() -> None:
    """RequirementFlag.delegate_to_peer in Python GSSAPI code triggers finding."""
    src = (
        "import gssapi\n"
        "ctx = gssapi.SecurityContext(\n"
        "    name=name,\n"
        "    flags=[gssapi.RequirementFlag.delegate_to_peer],\n"
        "    usage='initiate',\n"
        ")\n"
    )
    assert _hits("krb-forwardable-tickets-global", src)


def test_p3_gss_c_deleg_flag_flags() -> None:
    """GSS_C_DELEG_FLAG constant in C code triggers finding."""
    src = "gss_flags = GSS_C_MUTUAL_FLAG | GSS_C_DELEG_FLAG;\n"
    assert _hits("krb-forwardable-tickets-global", src)


def test_p3_forwardable_false_silent() -> None:
    """forwardable = false does not flag."""
    src = "[libdefaults]\n    forwardable = false\n"
    assert not _hits("krb-forwardable-tickets-global", src)


# ---------- P4 : krb-dns-canonicalize-hostname ---------------------------


def test_p4_dns_canonicalize_hostname_true_flags() -> None:
    """dns_canonicalize_hostname = true triggers HIGH finding."""
    src = "[libdefaults]\n    dns_canonicalize_hostname = true\n"
    hits = _hits("krb-dns-canonicalize-hostname", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p4_rdns_true_flags() -> None:
    """rdns = true triggers finding."""
    src = "[libdefaults]\n    rdns = true\n"
    assert _hits("krb-dns-canonicalize-hostname", src)


def test_p4_dns_lookup_kdc_true_without_realms_flags() -> None:
    """dns_lookup_kdc = true without [realms] hard-codes triggers finding."""
    src = "[libdefaults]\n    dns_lookup_kdc = true\n"
    assert _hits("krb-dns-canonicalize-hostname", src)


def test_p4_dns_lookup_kdc_suppressed_when_realms_present() -> None:
    """dns_lookup_kdc = true is suppressed when [realms] section is present."""
    src = (
        "[libdefaults]\n"
        "    dns_lookup_kdc = true\n"
        "\n"
        "[realms]\n"
        " CORP.EXAMPLE.COM = {\n"
        "  kdc = dc01.corp.example.com\n"
        " }\n"
    )
    # dns_lookup_kdc hit should be suppressed
    hits = _hits("krb-dns-canonicalize-hostname", src)
    dns_kdc_hits = [h for h in hits if "dns_lookup_kdc" in h.matched_text]
    assert not dns_kdc_hits


def test_p4_dns_canonicalize_false_silent() -> None:
    """dns_canonicalize_hostname = false does not flag."""
    src = "[libdefaults]\n    dns_canonicalize_hostname = false\n"
    assert not _hits("krb-dns-canonicalize-hostname", src)


# ---------- P5 : krb-spnego-http-no-origin-binding -----------------------


def test_p5_negotiate_header_no_origin_check_flags() -> None:
    """WWW-Authenticate: Negotiate without Origin check triggers HIGH finding."""
    src = (
        'def authenticate(request):\n'
        '    auth = request.headers.get("Authorization", "")\n'
        '    if not auth.startswith("Negotiate "):\n'
        '        return Response(401, headers={"WWW-Authenticate": "Negotiate"})\n'
        '    token = base64.b64decode(auth[10:])\n'
        '    ctx = validate_spnego(token)\n'
        '    return jsonify({"user": str(ctx.name)})\n'
    )
    hits = _hits("krb-spnego-http-no-origin-binding", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p5_negotiate_ntlm_dual_challenge_flags() -> None:
    """Dual Negotiate+NTLM WWW-Authenticate header triggers finding."""
    src = (
        'res.setHeader("WWW-Authenticate", "Negotiate, NTLM");\n'
        'return res.status(401).end();\n'
    )
    assert _hits("krb-spnego-http-no-origin-binding", src)


def test_p5_negotiate_with_origin_check_suppressed() -> None:
    """WWW-Authenticate: Negotiate with Origin header check is suppressed."""
    src = (
        'def authenticate(request):\n'
        '    origin = request.headers.get("origin", "")\n'
        '    if origin not in ORIGIN_ALLOWLIST:\n'
        '        abort(403)\n'
        '    auth = request.headers.get("Authorization", "")\n'
        '    if not auth.startswith("Negotiate "):\n'
        '        return Response(401, headers={"WWW-Authenticate": "Negotiate"})\n'
        '    ctx = validate_spnego(base64.b64decode(auth[10:]))\n'
        '    return jsonify({"user": str(ctx.name)})\n'
    )
    assert not _hits("krb-spnego-http-no-origin-binding", src)


def test_p5_negotiate_with_channel_binding_suppressed() -> None:
    """WWW-Authenticate: Negotiate with channel binding reference is suppressed."""
    src = (
        "# Enforce TLS channel binding (tls-unique) before processing Negotiate token.\n"
        'res.set("WWW-Authenticate", "Negotiate");\n'
        "const binding = getTlsChannelBinding(socket);\n"
    )
    assert not _hits("krb-spnego-http-no-origin-binding", src)


# ---------- P6 : krb-gssapi-ntlm-fallback-mechoid ------------------------


def test_p6_ntlm_oid_literal_flags() -> None:
    """NTLM mechOID 1.3.6.1.4.1.311.2.2.10 triggers HIGH finding."""
    src = (
        "import gssapi\n"
        "NTLM_OID = gssapi.OID.from_int_seq([1, 3, 6, 1, 4, 1, 311, 2, 2, 10])\n"
    )
    hits = _hits("krb-gssapi-ntlm-fallback-mechoid", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p6_ntlm_oid_java_flags() -> None:
    """NTLM OID string in Java Oid constructor triggers finding."""
    src = 'Oid ntlmOid = new Oid("1.3.6.1.4.1.311.2.2.10");\n'
    assert _hits("krb-gssapi-ntlm-fallback-mechoid", src)


def test_p6_spnego_oid_only_no_ntlm_silent() -> None:
    """SPNEGO OID alone (no NTLM OID) does not flag."""
    src = 'Oid spnegoOid = new Oid("1.3.6.1.5.5.2");\n'
    assert not _hits("krb-gssapi-ntlm-fallback-mechoid", src)


def test_p6_kerberos_oid_only_silent() -> None:
    """Kerberos 5 OID alone does not flag."""
    src = 'Oid krb5Oid = new Oid("1.2.840.113554.1.2.2");\n'
    assert not _hits("krb-gssapi-ntlm-fallback-mechoid", src)


# ---------- P7 : krb-jaas-keytab-no-principal ----------------------------


def test_p7_krb5loginmodule_no_principal_flags() -> None:
    """Krb5LoginModule with useKeyTab+storeKey but no principal= triggers HIGH."""
    src = (
        "KerberosLogin {\n"
        "    com.sun.security.auth.module.Krb5LoginModule required\n"
        "    useKeyTab=true\n"
        "    storeKey=true\n"
        "    doNotPrompt=true\n"
        '    keyTab="/etc/security/app.keytab"\n'
        "    ;\n"
        "};\n"
    )
    hits = _hits("krb-jaas-keytab-no-principal", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p7_krb5loginmodule_with_principal_suppressed() -> None:
    """Krb5LoginModule with useKeyTab+storeKey AND principal= is suppressed."""
    src = (
        "KerberosLogin {\n"
        "    com.sun.security.auth.module.Krb5LoginModule required\n"
        "    useKeyTab=true\n"
        "    storeKey=true\n"
        '    principal="svc_app@CORP.EXAMPLE.COM"\n'
        "    doNotPrompt=true\n"
        '    keyTab="/etc/security/app.keytab"\n'
        "    ;\n"
        "};\n"
    )
    assert not _hits("krb-jaas-keytab-no-principal", src)


def test_p7_krb5loginmodule_missing_storkey_silent() -> None:
    """Krb5LoginModule with useKeyTab but without storeKey does not flag."""
    src = (
        "KerberosLogin {\n"
        "    com.sun.security.auth.module.Krb5LoginModule required\n"
        "    useKeyTab=true\n"
        "    doNotPrompt=true\n"
        "    ;\n"
        "};\n"
    )
    assert not _hits("krb-jaas-keytab-no-principal", src)


def test_p7_no_krb5_login_module_silent() -> None:
    """File with no Krb5LoginModule at all does not flag."""
    src = "useKeyTab=true\nstoreKey=true\n"
    assert not _hits("krb-jaas-keytab-no-principal", src)


# ---------- P8 : krb-dotnet-negotiate-delegation -------------------------


def test_p8_delegation_level_flags_critical() -> None:
    """TokenImpersonationLevel.Delegation triggers HIGH finding (CRITICAL tier)."""
    src = (
        "stream.AuthenticateAsServer(\n"
        "    CredentialCache.DefaultNetworkCredentials,\n"
        "    ProtectionLevel.EncryptAndSign,\n"
        "    TokenImpersonationLevel.Delegation\n"
        ");\n"
    )
    hits = _hits("krb-dotnet-negotiate-delegation", src)
    assert hits


def test_p8_negotiate_stream_auth_as_server_flags() -> None:
    """NegotiateStream + AuthenticateAsServer co-occurrence triggers finding."""
    src = (
        "var stream = new NegotiateStream(networkStream, leaveInnerStreamOpen: false);\n"
        "// no impersonation level specified\n"
        "stream.AuthenticateAsServer();\n"
    )
    assert _hits("krb-dotnet-negotiate-delegation", src)


def test_p8_windows_identity_impersonate_flags() -> None:
    """WindowsIdentity.Impersonate() triggers finding."""
    src = (
        "WindowsIdentity identity = (WindowsIdentity)HttpContext.Current.User.Identity;\n"
        "using (identity.Impersonate())\n"
        "{\n"
        "    // network requests run as the client\n"
        "}\n"
    )
    assert _hits("krb-dotnet-negotiate-delegation", src)


def test_p8_allow_ntlm_true_flags() -> None:
    """AllowNtlm = true triggers finding."""
    src = "options.AllowNtlm = true;\n"
    assert _hits("krb-dotnet-negotiate-delegation", src)


def test_p8_negotiate_stream_without_auth_as_server_silent() -> None:
    """NegotiateStream mention without AuthenticateAsServer in window does not flag."""
    src = (
        "// NegotiateStream is used in the client path.\n"
        "// The client calls AuthenticateAsClient instead.\n"
        "var stream = new NegotiateStream(inner);\n"
        "stream.AuthenticateAsClient();\n"
    )
    # No AuthenticateAsServer in the window — should not trigger.
    hits = _hits("krb-dotnet-negotiate-delegation", src)
    # NegotiateStream alone without AuthenticateAsServer co-occurrence is silent.
    server_hits = [h for h in hits if "AuthenticateAsServer" in h.matched_text or "NegotiateStream" in h.matched_text]
    # AuthenticateAsClient is not the trigger so hits should be empty
    assert not server_hits


# ---------- P9 : krb-gmsa-password-extraction ----------------------------


def test_p9_msds_managed_password_attr_flags() -> None:
    """msDS-ManagedPassword attribute in code triggers CRITICAL finding."""
    src = (
        "$gmsa = Get-ADServiceAccount svc_gmsa -Properties 'msDS-ManagedPassword'\n"
    )
    hits = _hits("krb-gmsa-password-extraction", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p9_gmsa_password_reader_tool_flags() -> None:
    """GMSAPasswordReader tool fingerprint triggers finding."""
    src = "Invoke-Expression .\\GMSAPasswordReader.exe\n"
    assert _hits("krb-gmsa-password-extraction", src)


def test_p9_get_gmsa_password_flags() -> None:
    """Get-GMSAPassword PowerShell cmdlet triggers finding."""
    src = "$pass = Get-GMSAPassword -Identity svc_app$\n"
    assert _hits("krb-gmsa-password-extraction", src)


def test_p9_convert_to_nthash_flags() -> None:
    """ConvertTo-NTHash function call triggers finding."""
    src = "$hash = ConvertTo-NTHash -Password $blob.CurrentPassword\n"
    assert _hits("krb-gmsa-password-extraction", src)


def test_p9_principals_allowed_attr_flags() -> None:
    """PrincipalsAllowedToRetrieveManagedPassword attribute reference triggers finding."""
    src = (
        "Set-ADServiceAccount svc_app$ "
        "-PrincipalsAllowedToRetrieveManagedPassword web_servers_group\n"
    )
    assert _hits("krb-gmsa-password-extraction", src)


def test_p9_unrelated_ldap_code_silent() -> None:
    """Generic LDAP code without GMSA-specific attributes does not flag."""
    src = (
        "conn.search(base_dn, '(objectClass=user)', attributes=['sAMAccountName'])\n"
    )
    assert not _hits("krb-gmsa-password-extraction", src)
