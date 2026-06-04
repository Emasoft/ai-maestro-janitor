"""Active Directory / LDAP / Kerberos misconfiguration patterns.

Wave-23 distillation round 9 — AD/LDAP/Kerberos angle.

Catalogue of 7 net-new patterns distilled in
`reports/distill-round-9/ad-ldap-kerberos.md`. Targets code that
*queries, configures, or operates on* Active Directory infrastructure
in ways that either reveal a misconfiguration of the target
environment or actively introduce one. Orthogonal to every prior
distill round (1-8) — no existing scanner covers AD/LDAP/Kerberos
protocol-level surfaces.

What is NOT here (intentional carve-outs documented in the report):

  * NTLMv1 server-side policy (`LMCompatibilityLevel`) — config-file
    knob, not code, so out of scope for a source-review scanner.
  * Pass-the-hash detection from logs — network telemetry, not code.
  * AdminSDHolder ACL tampering — already a subset of pattern 5
    (extended-right grant on a privileged container).
  * MS-RPC / DRSUAPI direct calls — covered by pattern 5's
    `DRSUAPI` / `GetNCChanges` literals.

What IS here (7 rules, regex-only, all RE2-safe):

  * LDAP-KERBEROAST-001        (CRITICAL) — SPN enumeration
  * LDAP-ASREP-001             (CRITICAL) — AS-REP roast recon
  * LDAP-DELEG-UNCONSTRAINED-001 (CRITICAL) — unconstrained delegation hunt
  * LDAP-UAC-MASK-001          (HIGH)     — userAccountControl bitmask family
  * LDAP-DCSYNC-ACL-001        (CRITICAL) — DCSync grant / GUID recon
  * LDAP-LDAPSIGN-001          (HIGH)     — channel binding / signing disabled
  * KRB-GOLDEN-DETECT-001      (CRITICAL) — golden / silver ticket forging

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — NamedTuple, mirrors chat_bot_patterns.Finding
            shape.

OWASP ASI mapping used:
  ASI-01 — Broken Access Control (DCSync ACL grant / extended right)
  ASI-02 — Cryptographic Failures (LDAP signing / channel binding off)
  ASI-04 — Insecure Design (delegation flags, golden-ticket blind spot)
  ASI-05 — Security Misconfiguration (userAccountControl bitmask family)
  ASI-07 — Identification / Authentication Failures (kerberoast, AS-REP roast)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.

Stage-A vs Stage-B:
  Stage-A (this module) is a regex pass: deterministic, RE2-safe,
  zero per-rule context allocation. Stage-B is the caller's job — for
  pattern 1 (kerberoast) and pattern 3 (unconstrained delegation), the
  same filter is used by both offensive enumeration AND defensive
  audit tooling (BloodHound / PingCastle / ADRecon). Stage-B reads
  ±20 lines of context and decides offensive vs defensive based on
  surrounding attribute lists, output sinks, and immediate use of
  the returned data.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : LDAP-KERBEROAST-001 -------------------------------------------


# The canonical kerberoasting LDAP filter or the impacket fingerprint.
# RFC 4515 filters routinely split across lines via Python `+` /
# `"..." "..."` concatenation, so we allow up to 120 chars between the
# &-conjunction and the `servicePrincipalName=*` predicate. The
# `[^()]` character class keeps the bridge bounded — no nested parens
# allowed, which is consistent with the LDAP filter grammar and keeps
# the regex RE2-safe (no backtracking explosion possible).
_KERBEROAST_FILTER_ANY = _re(
    # The "user-narrowed SPN enumeration" filter — both halves must
    # appear on the same logical line.
    r"\(\s*&[^()]{0,120}\bservicePrincipalName\s*=\s*\*\s*\)"
    r"|"
    # The samAccountType decimal for SAM_USER_OBJECT — the
    # kerberoasting-specific narrowing predicate. Machine accounts
    # also have SPNs but their NT-hash is a 240-bit random LSA
    # secret, not crackable in the same way.
    r"\bsamAccountType\s*=\s*805306368\b"
    r"|"
    # The impacket attack-tool fingerprint.
    r"\bGetUserSPNs(?:\.py)?\b"
    r"|"
    # Mimikatz / Rubeus kerberoast modules.
    r"\bkerberoast\b"
    r"|"
    r"\bRubeus(?:\.exe)?\s+kerberoast\b"
    r"|"
    # Direct getKerberosTGS call (impacket attack primitive).
    r"\bgetKerberosTGS\b"
)


# ---- P2 : LDAP-ASREP-001 ------------------------------------------------


# The OID-plus-decimal-4194304 combo is near-unique to AS-REP roast.
# The matching-rule OID `1.2.840.113556.1.4.803` IS the bit-AND
# extensible match operator in Active Directory schema.
_ASREP_ROAST_ANY = _re(
    # The unique OID + decimal shape.
    r"1\.2\.840\.113556\.1\.4\.803\s*:\s*=\s*4194304\b"
    r"|"
    # The constant name — Win32 macro from `iads.h` (= 0x400000).
    r"\bUF_DONT_REQUIRE_PREAUTH\b"
    r"|"
    # impacket attack-tool fingerprint.
    r"\bGetNPUsers(?:\.py)?\b"
    r"|"
    # Microsoft's tidier attribute name (Schema 2016+).
    r"\bmsDS-UserDontRequirePreAuth\b"
    r"|"
    # Direct hex literal of the flag.
    r"\b0x0*400000\b"
)


# ---- P3 : LDAP-DELEG-UNCONSTRAINED-001 ----------------------------------


# Two decimals: 524288 (UF_TRUSTED_FOR_DELEGATION) — unconstrained
# delegation — and 16777216 (UF_TRUSTED_TO_AUTH_FOR_DELEGATION) —
# constrained delegation WITH protocol transition (S4U2Self abuse).
_DELEG_UAC_FAMILY = _re(
    r"1\.2\.840\.113556\.1\.4\.803\s*:\s*=\s*(?:524288|16777216)\b"
    r"|"
    r"\bUF_TRUSTED_FOR_DELEGATION\b"
    r"|"
    r"\bUF_TRUSTED_TO_AUTH_FOR_DELEGATION\b"
    r"|"
    # Hex literals.
    r"\b0x0*80000\b"
    r"|"
    r"\b0x0*1000000\b"
    r"|"
    # The modern resource-based constrained-delegation attribute —
    # writes to this plant "Rubeus shadow credentials" backdoors.
    r"\bmsDS-AllowedToActOnBehalfOfOtherIdentity\b"
    r"|"
    r"\bmsDS-AllowedToDelegateTo\b"
)


# ---- P4 : LDAP-UAC-MASK-001 ---------------------------------------------


# Family-level detector for userAccountControl bitmask attacks. The
# decimal table:
#   0x20       UF_PASSWD_NOTREQD                NoPac precondition
#   0x40       UF_LOCKOUT                       Lockout bypass surface
#   0x800      UF_INTERDOMAIN_TRUST_ACCOUNT     Cross-trust pivot
#   0x1000     UF_WORKSTATION_TRUST_ACCOUNT     Machine accounts
#   0x2000     UF_SERVER_TRUST_ACCOUNT          Domain Controllers
#   0x10000    UF_DONT_EXPIRE_PASSWORD          Eternal-password
#   0x20000    UF_MNS_LOGON_ACCOUNT             Legacy NT4
#   0x40000    UF_SMARTCARD_REQUIRED            (Defensive — absence is bad)
#   0x80000    UF_TRUSTED_FOR_DELEGATION        Unconstrained delegation
#   0x100000   UF_NOT_DELEGATED                 (Defensive — absence is bad)
#   0x200000   UF_USE_DES_KEY_ONLY              DES — broken cipher
#   0x400000   UF_DONT_REQUIRE_PREAUTH          AS-REP roast (P2)
#   0x1000000  UF_TRUSTED_TO_AUTH_FOR_DELEGATION Constrained deleg + proto
#   0x4000000  UF_NO_AUTH_DATA_REQUIRED         Reduced PAC validation
#
# The detector picks up any of:
#   1. OID bit-AND match `userAccountControl:1.2.840.113556.1.4.803:=N`
#   2. Hex bit-AND in code (`uac & 0xNNNN`) — restricted to the
#      attack-relevant hex constants only (no generic `& 0x20`-style
#      false positives on unrelated bitfields)
#   3. Named UF_* constant from iads.h
_UAC_BITMASK_ANY = _re(
    # OID extensible-match shape — any decimal value.
    r"\buserAccountControl\s*:\s*1\.2\.840\.113556\.1\.4\.803\s*:\s*=\s*\d+\b"
    r"|"
    # Code-level bitwise-AND with one of the attack-relevant hex
    # literals. Anchored on the `userAccountControl` identifier to
    # suppress generic-bitfield false positives.
    r"\buserAccountControl\s*&\s*"
    r"0x0*(?:20|40|800|1000|2000|10000|20000|40000|80000|100000"
    r"|200000|400000|1000000|4000000)\b"
    r"|"
    # The full set of attack-relevant UF_* macro names. We DO NOT
    # match UF_SMARTCARD_REQUIRED / UF_NOT_DELEGATED here even
    # though they appear in the table — those are defensive
    # constants whose ABSENCE is the misconfig, so their presence
    # in code is benign.
    r"\bUF_(?:PASSWD_NOTREQD|LOCKOUT|INTERDOMAIN_TRUST_ACCOUNT"
    r"|WORKSTATION_TRUST_ACCOUNT|SERVER_TRUST_ACCOUNT"
    r"|DONT_EXPIRE_PASSWORD|MNS_LOGON_ACCOUNT|USE_DES_KEY_ONLY"
    r"|DONT_REQUIRE_PREAUTH|TRUSTED_FOR_DELEGATION"
    r"|TRUSTED_TO_AUTH_FOR_DELEGATION|NO_AUTH_DATA_REQUIRED)\b"
)


# ---- P5 : LDAP-DCSYNC-ACL-001 -------------------------------------------


# The three replication extended-right GUIDs are near-unique
# fingerprints — they appear in almost no other context except
# Kerberos / replication security tooling. A literal GUID match is
# already high-confidence; the additional `DCSync` / `DRSUAPI` /
# `secretsdump` literals catch tool-name fingerprints in shell
# scripts and PowerShell that may not embed the GUID directly.
_DCSYNC_ACL_ANY = _re(
    # DS-Replication-Get-Changes
    r"\b1131f6aa-9c07-11d1-f79f-00c04fc2dcd2\b"
    r"|"
    # DS-Replication-Get-Changes-All
    r"\b1131f6ad-9c07-11d1-f79f-00c04fc2dcd2\b"
    r"|"
    # DS-Replication-Get-Changes-In-Filtered-Set
    r"\b89e95b76-444d-4c62-991a-0facbeda640c\b"
    r"|"
    # PowerView's literal command verb.
    r"\bDCSync\b"
    r"|"
    # MS-RPC interface name.
    r"\bDRSUAPI\b"
    r"|"
    # The actual replication call.
    r"\bGetNCChanges\b"
    r"|"
    # impacket's secret-dump tool fingerprint.
    r"\bsecretsdump(?:\.py)?\b"
    r"|"
    # PowerView's add-ACL helper for granting DCSync.
    r"\bAdd-DomainObjectAcl\b"
    r"|"
    # The S-1-5-21- replication group SID (sometimes used as a
    # backdoor grant target).
    r"\bnTSecurityDescriptor\b"
)


# ---- P6 : LDAP-LDAPSIGN-001 ---------------------------------------------


# Trigger: any of the explicit "disable sign+seal" / "use plain
# ldap://" / "NTLM bind" shapes.
_LDAPSIGN_DISABLE_TRIGGER = _re(
    # ldap3 — Server(..., use_ssl=False)
    r"\buse_ssl\s*=\s*False\b"
    r"|"
    # ldap3 — channel_binding=False (CBT off)
    r"\bchannel_binding\s*=\s*False\b"
    r"|"
    # impacket / smbclient — require_signing=False
    r"\brequire_signing\s*=\s*False\b"
    r"|"
    r"\brequire_secure_negotiate\s*=\s*False\b"
    r"|"
    # impacket NTLMRelayxConfig
    r"\bsetRequireSigning\s*\(\s*False\s*\)"
    r"|"
    # impacket signing disable variants
    r"\bsetSMB2Support\s*\(\s*True\s*\)"
    r"|"
    # python-ldap — plain ldap:// (not ldaps://)
    r"\bldap\.initialize\s*\(\s*['\"]ldap://"
    r"|"
    # ldap3 NTLM authentication on a writable bind.
    r"\bauthentication\s*=\s*(?:NTLM|SIMPLE)\b"
)


# Stage-B mitigation: file calls start_tls_s() OR uses a known
# loopback / example host. Suppress only when the match is the
# `ldap.initialize("ldap://...")` shape and START_TLS follows
# within ~10 lines.
_LDAPSIGN_STARTTLS_GUARD = _re(
    r"\.start_tls_s\s*\("
    r"|"
    r"\bSTART_TLS\b"
    r"|"
    # Loopback / test hosts.
    r"ldap://(?:localhost|127\.0\.0\.1|\[::1\])"
    r"|"
    r"ldap://[a-z0-9.\-]*\.example\.(?:com|net|org|local)"
)


# ---- P7 : KRB-GOLDEN-DETECT-001 -----------------------------------------


# Tool/command fingerprints — the strongest signal.
_GOLDEN_TICKET_ANY = _re(
    # impacket ticketer.
    r"\bticketer(?:\.py)?\b"
    r"|"
    # Rubeus golden / silver verbs.
    r"\bRubeus(?:\.exe)?\s+(?:golden|silver)\b"
    r"|"
    # Mimikatz module names.
    r"\bkerberos::golden\b"
    r"|"
    r"\bkerberos::ptt\b"
    r"|"
    r"\bkerberos::ticket\b"
    r"|"
    # Variable assignment that pairs `krbtgt` with `hash`.
    r"\bkrbtgt[_\-]?(?:nt)?hash\b\s*="
    r"|"
    # impacket Ticketer programmatic API.
    r"\bTICKETER\b"
    r"|"
    # AS-REP / TGS-REP composition (forged-ticket assembly).
    r"\bgenerateTGT\b"
    r"|"
    r"\bgenerateTGS\b"
    r"|"
    # Mimikatz pass-the-ticket / over-pass-the-hash module.
    r"\bsekurlsa::pth\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="LDAP-KERBEROAST-001",
        name="Kerberoastable account enumeration via servicePrincipalName=*",
        severity="CRITICAL",
        description=(
            "Code performs an LDAP search whose filter enumerates "
            "every user-class account with a Service Principal Name. "
            "This is the canonical kerberoasting reconnaissance query: "
            "every account returned can be requested a TGS-REP that is "
            "RC4-HMAC-encrypted with the account's NT-hash and cracked "
            "offline. The samAccountType=805306368 (SAM_USER_OBJECT) "
            "narrowing predicate is the kerberoasting-specific "
            "discriminator. Tool fingerprints (impacket GetUserSPNs, "
            "Rubeus kerberoast) are direct attack-tool signatures. "
            "Stage-B: defensive audit tooling (BloodHound, PingCastle, "
            "ADRecon) uses the same filter — the discriminator is "
            "whether the code ALSO fetches msDS-SupportedEncryptionTypes "
            "/ pwdLastSet (defensive) or immediately calls "
            "getKerberosTGS / pipes to hashcat (offensive)."
        ),
        pattern=_KERBEROAST_FILTER_ANY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="LDAP-ASREP-001",
        name="AS-REP roast candidate enumeration via UF_DONT_REQUIRE_PREAUTH",
        severity="CRITICAL",
        description=(
            "Code constructs the LDAP bitwise-AND extensible-match "
            "filter `1.2.840.113556.1.4.803:=4194304` (= "
            "UF_DONT_REQUIRE_PREAUTH, 0x400000) or references the "
            "named constant directly. Such accounts will issue an "
            "AS-REP encrypted with the account's NT-hash without the "
            "pre-auth timestamp check — the AS-REP is offline-"
            "crackable WITHOUT the attacker knowing the password "
            "first, requiring only network reachability to a DC. The "
            "OID-plus-decimal-4194304 combination is near-unique to "
            "this attack. Tool fingerprint: impacket GetNPUsers. "
            "Modern attribute name: msDS-UserDontRequirePreAuth."
        ),
        pattern=_ASREP_ROAST_ANY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="LDAP-DELEG-UNCONSTRAINED-001",
        name="Unconstrained / protocol-transition delegation enumeration",
        severity="CRITICAL",
        description=(
            "Code enumerates accounts with UF_TRUSTED_FOR_DELEGATION "
            "(0x80000 = 524288) — unconstrained Kerberos delegation, "
            "the precondition for PetitPotam / PrinterBug / DFSCoerce "
            "DC-coercion attacks. Or with UF_TRUSTED_TO_AUTH_FOR_"
            "DELEGATION (0x1000000 = 16777216) — constrained "
            "delegation with protocol transition (S4U2Self abuse). "
            "Or writes to msDS-AllowedToActOnBehalfOfOtherIdentity — "
            "the modern resource-based constrained-delegation surface "
            "where Rubeus shadow-credentials attacks plant a backdoor. "
            "Reads are HIGH; writes to RBCD attribute are CRITICAL "
            "forest-wide compromise primitive."
        ),
        pattern=_DELEG_UAC_FAMILY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="LDAP-UAC-MASK-001",
        name="userAccountControl bitmask attack family",
        severity="HIGH",
        description=(
            "Code references the userAccountControl bitmask family — "
            "either via the LDAP extensible-match OID "
            "1.2.840.113556.1.4.803, a bitwise-AND with an attack-"
            "relevant hex constant (UF_PASSWD_NOTREQD 0x20, "
            "UF_USE_DES_KEY_ONLY 0x200000, UF_DONT_EXPIRE_PASSWORD "
            "0x10000, UF_NO_AUTH_DATA_REQUIRED 0x4000000, etc.), or "
            "a named UF_* macro. Family-level detector — the specific "
            "decimal determines the precise misconfiguration class "
            "and severity (per-flag table in the distill report). "
            "Defensive constants whose ABSENCE is the misconfig "
            "(UF_SMARTCARD_REQUIRED, UF_NOT_DELEGATED) are excluded "
            "from the macro-name half to keep precision high."
        ),
        pattern=_UAC_BITMASK_ANY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="LDAP-DCSYNC-ACL-001",
        name="DCSync grant or extended-right GUID reference",
        severity="CRITICAL",
        description=(
            "Code references one of the three Replicating-Directory-"
            "Changes extended-right GUIDs (1131f6aa-..., 1131f6ad-..., "
            "89e95b76-...) — the rights that authorise a DRSUAPI "
            "GetNCChanges call dumping every user's NT hash including "
            "krbtgt's, enabling golden-ticket forging. Legitimately, "
            "only Domain Controllers and a few replication accounts "
            "hold these rights — any code GRANTING them to a non-DC "
            "principal is planting a DCSync backdoor; any code "
            "ENUMERATING them is doing DCSync recon. Tool "
            "fingerprints: impacket secretsdump, PowerView's "
            "Add-DomainObjectAcl. Stage-B: a write marker "
            "(MODIFY_REPLACE / MODIFY_ADD / DACLEdit) on the same "
            "logical line as a GUID is the offensive-shape "
            "discriminator."
        ),
        pattern=_DCSYNC_ACL_ANY,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="LDAP-LDAPSIGN-001",
        name="LDAP channel-binding / signing disabled on writable connection",
        severity="HIGH",
        description=(
            "Client code explicitly disables LDAP channel-binding "
            "tokens (CBT), LDAP signing, or SMB signing, OR opens a "
            "plain `ldap://` (port 389) connection that is then used "
            "for write operations (modify, modify_dn, add, delete). "
            "Either shape exposes the bind to NTLM relay attacks. "
            "Server-side mitigation (LdapEnforceChannelBinding=2) is "
            "out of scope for code review; the code-side signal is "
            "the client explicitly opting OUT of the integrity layer. "
            "Stage-B carve-outs: localhost / 127.0.0.1 / *.example.* "
            "test fixtures and python-ldap initialize() followed by "
            "start_tls_s() within ~10 lines are safe."
        ),
        pattern=_LDAPSIGN_DISABLE_TRIGGER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="KRB-GOLDEN-DETECT-001",
        name="Golden / silver Kerberos ticket forging fingerprint",
        severity="CRITICAL",
        description=(
            "Code path produces a forged Kerberos ticket — impacket "
            "ticketer / TICKETER programmatic API, Rubeus golden / "
            "silver, Mimikatz kerberos::golden / kerberos::ptt, "
            "explicit krbtgt_hash / nt_hash assignment paired with a "
            "high-value principal (Administrator, krbtgt, "
            "domain_admin), Domain-Admin group RIDs (512, 513, 518, "
            "519, 520) in a group list, or an explicit 10-year ticket "
            "lifetime. Producing such tickets requires the krbtgt "
            "hash (obtained via DCSync — see LDAP-DCSYNC-ACL-001) or "
            "a service-account NT-hash (kerberoasting — see "
            "LDAP-KERBEROAST-001). Stage-B: code paths under "
            "tests/ / fixtures/ / examples/ are likely Atomic Red "
            "Team / Caldera / BloodHound CE seed data; same shapes "
            "in app/ / services/ / bin/ are production-path "
            "offensive code."
        ),
        pattern=_GOLDEN_TICKET_ANY,
        owasp_asi="ASI-04",
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


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consulted (the rest of the rules are pure Stage-A
    regex emissions because their fingerprints are near-unique on
    their own — three replication GUIDs, OID + 4194304, etc.):

      * P1 (LDAP-KERBEROAST-001) — emits on every match; defensive
        de-rating is left to the caller (downstream Stage-B step
        reads ±20 lines of context and decides offensive vs audit).
      * P6 (LDAP-LDAPSIGN-001) — for the `ldap.initialize("ldap://...")`
        shape only, suppress when start_tls_s() / loopback / example
        host appears within a 10-line forward window. The explicit
        `*=False` / NTLM-bind shapes always emit (those are
        unambiguous opt-outs).
      * P5 (LDAP-DCSYNC-ACL-001) and P7 (KRB-GOLDEN-DETECT-001) emit
        on every match; severity escalation to CRITICAL by Stage-B
        (write marker for P5, high-value principal for P7) is left
        to the caller (rule severity already starts at CRITICAL).

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

    # ---- P1 : LDAP-KERBEROAST-001 ----
    rule_p1 = rule_by_id["LDAP-KERBEROAST-001"]
    for m in _KERBEROAST_FILTER_ANY.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : LDAP-ASREP-001 ----
    rule_p2 = rule_by_id["LDAP-ASREP-001"]
    for m in _ASREP_ROAST_ANY.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : LDAP-DELEG-UNCONSTRAINED-001 ----
    rule_p3 = rule_by_id["LDAP-DELEG-UNCONSTRAINED-001"]
    for m in _DELEG_UAC_FAMILY.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : LDAP-UAC-MASK-001 ----
    rule_p4 = rule_by_id["LDAP-UAC-MASK-001"]
    for m in _UAC_BITMASK_ANY.finditer(text):
        _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : LDAP-DCSYNC-ACL-001 ----
    rule_p5 = rule_by_id["LDAP-DCSYNC-ACL-001"]
    for m in _DCSYNC_ACL_ANY.finditer(text):
        _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : LDAP-LDAPSIGN-001 ----
    # The `ldap.initialize("ldap://...")` half needs Stage-B
    # suppression for files that follow up with start_tls_s() or
    # use a test/loopback host. The other halves (*=False, NTLM
    # bind) always emit.
    rule_p6 = rule_by_id["LDAP-LDAPSIGN-001"]
    for m in _LDAPSIGN_DISABLE_TRIGGER.finditer(text):
        matched_text = m.group(0)
        # Only the python-ldap "plain ldap://" variant is
        # subject to start_tls / test-host suppression.
        if matched_text.lower().startswith("ldap.initialize"):
            line, _ = _line_col(text, m.start())
            window = _slice_forward(text, line, 10)
            if _LDAPSIGN_STARTTLS_GUARD.search(window) is not None:
                continue
        _emit(rule_p6, m.start(), matched_text)

    # ---- P7 : KRB-GOLDEN-DETECT-001 ----
    rule_p7 = rule_by_id["KRB-GOLDEN-DETECT-001"]
    for m in _GOLDEN_TICKET_ANY.finditer(text):
        _emit(rule_p7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


__all__ = (
    "Finding",
    "Rule",
    "RULES",
    "scan_text",
)
