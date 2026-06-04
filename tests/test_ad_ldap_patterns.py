"""Tests for scripts/lib/ad_ldap_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 AD/LDAP/
Kerberos catalogue (7 patterns covering kerberoasting, AS-REP roast,
unconstrained / protocol-transition delegation, userAccountControl
bitmask family, DCSync ACL grant, LDAP signing / channel-binding
disabled, and golden / silver ticket forging).

Each rule has at least one positive test exercising a canary AND at
least one negative test exercising a carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ad_ldap_patterns as adp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(adp.RULES, tuple)
    rule_ids = {r.id for r in adp.RULES}
    expected = {
        "LDAP-KERBEROAST-001",
        "LDAP-ASREP-001",
        "LDAP-DELEG-UNCONSTRAINED-001",
        "LDAP-UAC-MASK-001",
        "LDAP-DCSYNC-ACL-001",
        "LDAP-LDAPSIGN-001",
        "KRB-GOLDEN-DETECT-001",
    }
    assert expected == rule_ids
    assert len(adp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in adp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = adp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert adp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — kerberoast filter
        "f1 = \"(&(samAccountType=805306368)(servicePrincipalName=*))\"\n"
        # Line 2 — AS-REP OID
        "f2 = \"(userAccountControl:1.2.840.113556.1.4.803:=4194304)\"\n"
    )
    findings = adp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[adp.Finding]:
    return [f for f in adp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : LDAP-KERBEROAST-001 -------------------------------------


def test_p1_kerberoast_full_filter_flags() -> None:
    """Classic kerberoasting LDAP filter → CRITICAL hit."""
    src = (
        "conn.search(\n"
        "    search_base='DC=corp,DC=example,DC=com',\n"
        "    search_filter='(&(samAccountType=805306368)"
        "(servicePrincipalName=*))',\n"
        "    attributes=['sAMAccountName', 'servicePrincipalName'],\n"
        ")\n"
    )
    hits = _hits("LDAP-KERBEROAST-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p1_getuserspns_import_flags() -> None:
    """impacket GetUserSPNs import → CRITICAL hit (tool fingerprint)."""
    src = "from impacket.examples.GetUserSPNs import GetUserSPNs\n"
    hits = _hits("LDAP-KERBEROAST-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p1_benign_ldap_search_silent() -> None:
    """Generic LDAP search without SPN enumeration → no hit."""
    src = (
        "conn.search(\n"
        "    search_base='DC=corp,DC=example,DC=com',\n"
        "    search_filter='(objectClass=user)',\n"
        "    attributes=['cn', 'mail'],\n"
        ")\n"
    )
    assert not _hits("LDAP-KERBEROAST-001", src)


# ---------- P2 : LDAP-ASREP-001 ------------------------------------------


def test_p2_asrep_oid_decimal_flags() -> None:
    """OID + decimal 4194304 → CRITICAL hit."""
    src = (
        "ASREP_FILTER = (\n"
        "    '(&(samAccountType=805306368)'\n"
        "    '(userAccountControl:1.2.840.113556.1.4.803:=4194304))'\n"
        ")\n"
    )
    hits = _hits("LDAP-ASREP-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p2_uf_dont_require_preauth_macro_flags() -> None:
    """UF_DONT_REQUIRE_PREAUTH constant reference → CRITICAL hit."""
    src = "if uac & UF_DONT_REQUIRE_PREAUTH:  # AS-REP roast candidate\n"
    hits = _hits("LDAP-ASREP-001", src)
    assert hits


def test_p2_get_np_users_tool_fingerprint_flags() -> None:
    """impacket GetNPUsers tool name → CRITICAL hit."""
    src = "from impacket.examples.GetNPUsers import GetNPUsers\n"
    assert _hits("LDAP-ASREP-001", src)


def test_p2_unrelated_oid_silent() -> None:
    """Different decimal next to the OID — no AS-REP hit (P4 may fire)."""
    src = (
        "filter = '(userAccountControl:1.2.840.113556.1.4.803:=2)'\n"
    )
    assert not _hits("LDAP-ASREP-001", src)


# ---------- P3 : LDAP-DELEG-UNCONSTRAINED-001 ----------------------------


def test_p3_unconstrained_delegation_oid_flags() -> None:
    """OID + decimal 524288 (UF_TRUSTED_FOR_DELEGATION) → hit."""
    src = (
        "LDAP_UNCONSTRAINED = (\n"
        "    '(&(objectCategory=computer)'\n"
        "    '(userAccountControl:1.2.840.113556.1.4.803:=524288))'\n"
        ")\n"
    )
    hits = _hits("LDAP-DELEG-UNCONSTRAINED-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p3_protocol_transition_decimal_flags() -> None:
    """OID + decimal 16777216 (UF_TRUSTED_TO_AUTH_FOR_DELEGATION) → hit."""
    src = (
        "constrained_proto = (\n"
        "    '(userAccountControl:1.2.840.113556.1.4.803:=16777216)'\n"
        ")\n"
    )
    assert _hits("LDAP-DELEG-UNCONSTRAINED-001", src)


def test_p3_rbcd_attribute_write_flags() -> None:
    """msDS-AllowedToActOnBehalfOfOtherIdentity reference → hit (RBCD)."""
    src = (
        "conn.modify(target_dn, {'msDS-AllowedToActOnBehalfOfOtherIdentity':"
        " [(MODIFY_REPLACE, sd.get_data())]})\n"
    )
    assert _hits("LDAP-DELEG-UNCONSTRAINED-001", src)


def test_p3_no_delegation_attribute_silent() -> None:
    """Unrelated LDAP search — no delegation hit."""
    src = (
        "conn.search(base, '(cn=jdoe)', attributes=['mail'])\n"
    )
    assert not _hits("LDAP-DELEG-UNCONSTRAINED-001", src)


# ---------- P4 : LDAP-UAC-MASK-001 ---------------------------------------


def test_p4_uac_oid_any_decimal_flags() -> None:
    """OID extensible-match form with ANY decimal → family hit."""
    src = (
        "filter = '(userAccountControl:1.2.840.113556.1.4.803:=8192)'\n"
    )
    hits = _hits("LDAP-UAC-MASK-001", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p4_des_hex_constant_flags() -> None:
    """userAccountControl & 0x200000 (DES) → HIGH hit."""
    src = (
        "if userAccountControl & 0x200000:  # UF_USE_DES_KEY_ONLY\n"
        "    print('DES-only account')\n"
    )
    assert _hits("LDAP-UAC-MASK-001", src)


def test_p4_uf_passwd_notreqd_macro_flags() -> None:
    """UF_PASSWD_NOTREQD macro → HIGH hit (NoPac precondition)."""
    src = "if uac & UF_PASSWD_NOTREQD:\n    flag_account(account)\n"
    assert _hits("LDAP-UAC-MASK-001", src)


def test_p4_unrelated_bitwise_op_silent() -> None:
    """flags & 0x20 WITHOUT userAccountControl anchor → no hit."""
    src = (
        "if flags & 0x20:\n"
        "    print('some other bitfield')\n"
    )
    assert not _hits("LDAP-UAC-MASK-001", src)


def test_p4_defensive_uf_constants_not_flagged() -> None:
    """UF_SMARTCARD_REQUIRED / UF_NOT_DELEGATED → no hit (defensive)."""
    src = (
        "if uac & UF_SMARTCARD_REQUIRED:\n"
        "    pass\n"
        "if uac & UF_NOT_DELEGATED:\n"
        "    pass\n"
    )
    assert not _hits("LDAP-UAC-MASK-001", src)


# ---------- P5 : LDAP-DCSYNC-ACL-001 -------------------------------------


def test_p5_dcsync_get_changes_guid_flags() -> None:
    """DS-Replication-Get-Changes GUID → CRITICAL hit."""
    src = (
        "ACE_GUID = '1131f6aa-9c07-11d1-f79f-00c04fc2dcd2'\n"
    )
    hits = _hits("LDAP-DCSYNC-ACL-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p5_get_changes_all_guid_flags() -> None:
    """DS-Replication-Get-Changes-All GUID → CRITICAL hit."""
    src = (
        "ALL_GUID = '1131f6ad-9c07-11d1-f79f-00c04fc2dcd2'\n"
    )
    assert _hits("LDAP-DCSYNC-ACL-001", src)


def test_p5_secretsdump_tool_fingerprint_flags() -> None:
    """impacket secretsdump fingerprint → CRITICAL hit."""
    src = "from impacket.examples.secretsdump import LocalOperations\n"
    assert _hits("LDAP-DCSYNC-ACL-001", src)


def test_p5_powerview_acl_grant_flags() -> None:
    """PowerView Add-DomainObjectAcl → CRITICAL hit."""
    src = (
        "Add-DomainObjectAcl -TargetIdentity 'DC=corp' "
        "-PrincipalIdentity lowpriv -Rights DCSync\n"
    )
    assert _hits("LDAP-DCSYNC-ACL-001", src)


def test_p5_unrelated_guid_silent() -> None:
    """A random UUID not matching the three replication GUIDs → no hit."""
    src = (
        "session_id = '550e8400-e29b-41d4-a716-446655440000'\n"
    )
    assert not _hits("LDAP-DCSYNC-ACL-001", src)


# ---------- P6 : LDAP-LDAPSIGN-001 ---------------------------------------


def test_p6_use_ssl_false_flags() -> None:
    """ldap3 Server(use_ssl=False) → HIGH hit."""
    src = (
        "server = Server('dc01.corp.example.com', port=389, use_ssl=False)\n"
    )
    hits = _hits("LDAP-LDAPSIGN-001", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p6_channel_binding_false_flags() -> None:
    """channel_binding=False (CBT off) → HIGH hit."""
    src = (
        "conn = Connection(server, user, pw, authentication=NTLM,\n"
        "                  channel_binding=False)\n"
    )
    assert _hits("LDAP-LDAPSIGN-001", src)


def test_p6_impacket_require_signing_false_flags() -> None:
    """impacket setRequireSigning(False) → HIGH hit."""
    src = "config.setRequireSigning(False)\n"
    assert _hits("LDAP-LDAPSIGN-001", src)


def test_p6_plain_ldap_initialize_flags() -> None:
    """python-ldap initialize('ldap://corp...') without start_tls → HIGH hit."""
    src = (
        "l = ldap.initialize('ldap://dc01.corp.acme.com')\n"
        "l.simple_bind_s(user, password)\n"
        "l.modify_s(dn, modlist)\n"
    )
    assert _hits("LDAP-LDAPSIGN-001", src)


def test_p6_initialize_with_starttls_suppressed() -> None:
    """initialize('ldap://...') followed by start_tls_s() → suppressed."""
    src = (
        "l = ldap.initialize('ldap://dc01.corp.acme.com')\n"
        "l.start_tls_s()\n"
        "l.simple_bind_s(user, password)\n"
    )
    assert not _hits("LDAP-LDAPSIGN-001", src)


def test_p6_localhost_test_fixture_suppressed() -> None:
    """initialize('ldap://localhost') → suppressed by loopback guard."""
    src = (
        "l = ldap.initialize('ldap://localhost:389')\n"
        "l.simple_bind_s('cn=test', 'test')\n"
    )
    assert not _hits("LDAP-LDAPSIGN-001", src)


# ---------- P7 : KRB-GOLDEN-DETECT-001 -----------------------------------


def test_p7_impacket_ticketer_flags() -> None:
    """impacket ticketer.py invocation → CRITICAL hit."""
    src = (
        "from impacket.examples.ticketer import TICKETER\n"
        "t = TICKETER(target='Administrator')\n"
    )
    hits = _hits("KRB-GOLDEN-DETECT-001", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p7_rubeus_golden_verb_flags() -> None:
    """Rubeus.exe golden verb → CRITICAL hit."""
    src = (
        r".\Rubeus.exe golden /user:Administrator /id:500 "
        r"/domain:corp.acme.com /krbtgt:DEADBEEF" + "\n"
    )
    assert _hits("KRB-GOLDEN-DETECT-001", src)


def test_p7_mimikatz_kerberos_golden_flags() -> None:
    """Mimikatz kerberos::golden module reference → CRITICAL hit."""
    src = (
        "cmd = 'kerberos::golden /user:Admin /domain:corp /sid:S-1-5-21-...'\n"
    )
    assert _hits("KRB-GOLDEN-DETECT-001", src)


def test_p7_krbtgt_hash_assignment_flags() -> None:
    """Variable assignment pairing krbtgt with hash → CRITICAL hit."""
    src = (
        "krbtgt_nthash = '8846f7eaee8fb117ad06bdd830b7586c'\n"
    )
    assert _hits("KRB-GOLDEN-DETECT-001", src)


def test_p7_benign_ticketing_prose_silent() -> None:
    """English prose mentioning 'ticket' → no hit."""
    src = (
        "# This function generates a support ticket for the customer.\n"
        "def make_support_ticket(user):\n"
        "    return Ticket(user=user)\n"
    )
    assert not _hits("KRB-GOLDEN-DETECT-001", src)


# ---------- Integration sanity --------------------------------------------


def test_scan_text_returns_findings_list() -> None:
    """scan_text returns a list (mutable) — same as sibling modules."""
    out = adp.scan_text("nothing to see here")
    assert isinstance(out, list)


def test_multiple_rules_co_fire_on_combo_src() -> None:
    """Combined source triggers multiple rules independently."""
    src = (
        # P1 — kerberoast filter
        "f1 = '(&(samAccountType=805306368)(servicePrincipalName=*))'\n"
        # P5 — DCSync GUID
        "g = '1131f6aa-9c07-11d1-f79f-00c04fc2dcd2'\n"
        # P7 — Rubeus golden
        "cmd = 'Rubeus.exe golden /user:Admin'\n"
    )
    findings = adp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "LDAP-KERBEROAST-001" in rule_ids
    assert "LDAP-DCSYNC-ACL-001" in rule_ids
    assert "KRB-GOLDEN-DETECT-001" in rule_ids


def test_no_findings_on_benign_text() -> None:
    """Benign English prose → 0 findings."""
    src = (
        "This module describes Active Directory integration patterns.\n"
        "It does not contain any LDAP filters or attack-tool fingerprints.\n"
        "The author writes about AD in prose only, not in code form.\n"
    )
    assert adp.scan_text(src) == []


def test_dedup_prevents_double_emission() -> None:
    """Same line / column / rule_id is only emitted once."""
    src = (
        "g = '1131f6aa-9c07-11d1-f79f-00c04fc2dcd2'\n"
    )
    findings = adp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
