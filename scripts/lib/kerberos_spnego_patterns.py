"""Pattern library for Kerberos / SPNEGO / GSSAPI misconfigurations.

Wave-33 distill-round-19 — 9 rules covering:
  krb5.conf crypto policy, GSSAPI application code, SPNEGO HTTP middleware,
  Java JAAS Kerberos config, .NET NegotiateStream, DNS canonicalization,
  and GMSA private-key extraction.

Rule IDs are prefixed ``krb-`` (for GMSA the ID starts ``krb-`` as well,
consistent with the overall Kerberos theme). All patterns are RE2-safe:
no lookaheads, no lookbehinds, no nested quantifiers, no backreferences.
Proximity logic is implemented as Python scan_text() window logic.

Orthogonality note
------------------
These rules are complementary to ad_ldap_patterns.py, which covers the
LDAP/AD-side footprints (SPN enumeration, UAC flags, AS-REP roast via
UF_DONT_REQUIRE_PREAUTH, DCSync GUIDs, kerberoasting). The rules here
fire on protocol configuration and application code footprints:
krb5.conf, GSSAPI initiator code, JAAS modules, .NET NegotiateStream,
and GMSA attribute access.

Usage
-----
    import kerberos_spnego_patterns as ksp
    findings = ksp.scan_text(source_code)
    for f in findings:
        print(f.rule_id, f.line, f.severity)
"""

from __future__ import annotations

import re
from typing import NamedTuple


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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---------------------------------------------------------------------------
# P1 — krb-rc4-hmac-etype-permitted
# RC4-HMAC (etype 23) permitted in krb5.conf
# ---------------------------------------------------------------------------

# Master switch that re-enables all legacy ciphers.
_KRB_WEAK_CRYPTO_ENABLED = _re(r"^\s*allow_weak_crypto\s*=\s*true\b")

# Explicit legacy etype in the enctypes lists.
_KRB_LEGACY_ETYPE_LIST = _re(
    r"^\s*(?:default_tkt_enctypes|default_tgs_enctypes"
    r"|permitted_enctypes|default_etypes)\s*=[^\n#]*"
    r"(?:rc4-hmac|arcfour-hmac|arcfour-hmac-md5"
    r"|des-cbc-md5|des-cbc-crc|des3-cbc-sha1)\b"
)

# File-context guard: is this a krb5.conf-like file?
_KRB_LIBDEFAULTS_SECTION = _re(r"^\s*\[lib(?:defaults|deflt)\]")

# ---------------------------------------------------------------------------
# P2 — krb-preauth-disabled-kdc-config
# Kerberos pre-authentication disabled in kdc.conf or kadmin command
# ---------------------------------------------------------------------------

_KRB_PREAUTH_FALSE = _re(r"^\s*require_preauth\s*=\s*false\b")

_KRB_ANON_TGT_FALSE = _re(r"^\s*restrict_anonymous_to_tgt\s*=\s*false\b")

# kadmin command removing the requires_preauth flag (the minus form).
_KRB_KADMIN_REMOVE_PREAUTH = _re(
    r"\bkadmin(?:\.local)?\b[^\n]*-requires_preauth\b"
)

# ---------------------------------------------------------------------------
# P3 — krb-forwardable-tickets-global
# Forwardable / proxiable tickets globally enabled; GSSAPI delegation flag
# ---------------------------------------------------------------------------

_KRB_FORWARDABLE_TRUE = _re(r"^\s*forwardable\s*=\s*true\b")

_KRB_PROXIABLE_TRUE = _re(r"^\s*proxiable\s*=\s*true\b")

_KRB_GSSAPI_DELEG_FLAG = _re(
    r"\bRequirementFlag\.delegate_to_peer\b"
    r"|"
    r"\bGSS_C_DELEG_FLAG\b"
)

# ---------------------------------------------------------------------------
# P4 — krb-dns-canonicalize-hostname
# DNS canonicalization / KDC discovery enabled — SPN/KDC spoofing risk
# ---------------------------------------------------------------------------

_KRB_DNS_CANONICALIZE = _re(r"^\s*dns_canonicalize_hostname\s*=\s*true\b")

_KRB_DNS_LOOKUP_KDC = _re(r"^\s*dns_lookup_kdc\s*=\s*true\b")

_KRB_RDNS_TRUE = _re(r"^\s*rdns\s*=\s*true\b")

# Mitigation guard: explicit KDC address list makes DNS discovery a fallback.
_KRB_REALMS_SECTION = _re(r"^\s*\[realms\]")

# ---------------------------------------------------------------------------
# P5 — krb-spnego-http-no-origin-binding
# SPNEGO HTTP middleware without Origin / channel binding enforcement
# ---------------------------------------------------------------------------

# Trigger: Negotiate header being emitted / validated in HTTP middleware.
_SPNEGO_NEGOTIATE_EMIT = _re(
    r"""(?:WWW-Authenticate|Proxy-Authenticate)['":\s,]+Negotiate"""
    r"|"
    r"""['"']Negotiate['"']\s*,\s*['"']NTLM['"']"""
)

_SPNEGO_NEGOTIATE_RECV = _re(
    r"""Authorization['":\s]+Negotiate\b"""
    r"|"
    r"""auth(?:orization)?\s*\.\s*startsWith\s*\(\s*['"']Negotiate\b"""
)

# Mitigation guards for the proximity window.
_SPNEGO_ORIGIN_CHECK = _re(
    r"\breq(?:uest)?\.headers\b[^\n]*\borigin\b"
    r"|"
    r"\bOrigin\b[^\n]*(?:allowlist|whitelist|allowed|check|validate|verify)\b"
    r"|"
    r"\bchannel.?bind(?:ing)?\b"
    r"|"
    r"\btls.?unique\b"
    r"|"
    r"\btls.?server.?end.?point\b"
)

# ---------------------------------------------------------------------------
# P6 — krb-gssapi-ntlm-fallback-mechoid
# GSSAPI mechOID accepts NTLM fallback
# ---------------------------------------------------------------------------

# The NTLM mechOID literal — appears almost exclusively in GSSAPI code.
# Matches both dotted notation (1.3.6.1.4.1.311.2.2.10) and
# space/comma-separated integer-sequence form used in Python/Java APIs
# (e.g. from_int_seq([1, 3, 6, 1, 4, 1, 311, 2, 2, 10])).
_GSSAPI_NTLM_OID = _re(
    r"\b1\.3\.6\.1\.4\.1\.311\.2\.2\.10\b"
    r"|"
    r"\b1[,\s]+3[,\s]+6[,\s]+1[,\s]+4[,\s]+1[,\s]+311[,\s]+2[,\s]+2[,\s]+10\b"
)

# Broader: `negotiateMechanism` / mechList referencing NTLM symbol.
_GSSAPI_NTLM_MECHLIST = _re(
    r"\bnegotateMechanism\b[^\n]*\bNTLM\b"
    r"|"
    r"\bNTLMSecurityProvider\b"
    r"|"
    r"\bnegotiate_mechanism\b[^\n]*ntlm"
)

# ---------------------------------------------------------------------------
# P7 — krb-jaas-keytab-no-principal
# Java JAAS Krb5LoginModule with keytab but no principal restriction
# ---------------------------------------------------------------------------

# Trigger: JAAS Krb5LoginModule present.
_JAAS_KRB5_LOGIN = _re(r"\bKrb5LoginModule\b")

# Required options that escalate risk.
_JAAS_USE_KEYTAB = _re(r"\buseKeyTab\s*=\s*[\"']?true\b")

_JAAS_STORE_KEY = _re(r"\bstoreKey\s*=\s*[\"']?true\b")

# Mitigation: explicit principal binding in the same block.
_JAAS_PRINCIPAL_SET = _re(r"\bprincipal\s*=\s*[\"']?[A-Za-z0-9_@.]+")

# ---------------------------------------------------------------------------
# P8 — krb-dotnet-negotiate-delegation
# .NET NegotiateStream / WindowsIdentity without ImpersonationLevel constraint
# ---------------------------------------------------------------------------

# CRITICAL tier: explicit Delegation request.
_DOTNET_DELEG_LEVEL = _re(r"\bTokenImpersonationLevel\.Delegation\b")

# HIGH tier: NegotiateStream.AuthenticateAsServer usage.
_DOTNET_NEGOTIATE_STREAM = _re(r"\bNegotiateStream\b")

_DOTNET_AUTH_AS_SERVER = _re(r"\bAuthenticateAsServer\b")

# WindowsIdentity.Impersonate() without level restriction.
# Uses [\s\S]{0,300} to cross line boundaries (WindowsIdentity declaration
# and .Impersonate() call are typically on separate lines).
_DOTNET_WIN_IDENTITY_IMPERSONATE = _re(
    r"\bWindowsIdentity\b[\s\S]{0,300}\bImpersonate\s*\(\s*\)"
)

# AllowNtlm fallback setting.
_DOTNET_ALLOW_NTLM = _re(r"\bAllowNtlm\s*=\s*true\b")

# ---------------------------------------------------------------------------
# P9 — krb-gmsa-password-extraction
# GMSA managed-password attribute access / extraction tool fingerprints
# ---------------------------------------------------------------------------

_GMSA_ATTR_ACCESS = _re(r"\bmsDS-ManagedPassword\b")

_GMSA_INTERVAL_ATTR = _re(r"\bmsDS-ManagedPasswordInterval\b")

_GMSA_TOOL_FINGERPRINT = _re(
    r"\bGMSAPasswordReader\b"
    r"|"
    r"\bGet-GMSAPassword\b"
    r"|"
    r"\bConvertTo-NTHash\b"
    r"|"
    r"\bPrincipalsAllowedToRetrieveManagedPassword\b"
)

# ---------------------------------------------------------------------------
# RULES tuple — one Rule per pattern sub-group used directly in scan_text()
# ---------------------------------------------------------------------------

_RULES_LIST: list[Rule] = [
    Rule(
        id="krb-rc4-hmac-etype-permitted",
        name="RC4-HMAC (etype 23) permitted in krb5.conf",
        severity="HIGH",
        description=(
            "krb5.conf allow_weak_crypto=true or an explicit rc4-hmac / des etype in "
            "default_tkt_enctypes, default_tgs_enctypes, or permitted_enctypes. RC4-HMAC "
            "is crackable by offline dictionary attack using the NT hash directly."
        ),
        pattern=_KRB_WEAK_CRYPTO_ENABLED,  # primary; legacy etype list checked separately
        owasp_asi="ASI-02",
    ),
    Rule(
        id="krb-preauth-disabled-kdc-config",
        name="Kerberos pre-authentication disabled in kdc.conf or kadmin",
        severity="CRITICAL",
        description=(
            "require_preauth=false or restrict_anonymous_to_tgt=false in kdc.conf, "
            "or a kadmin modprinc -requires_preauth command. Disabling pre-auth globally "
            "enables AS-REP roasting of any principal from the network."
        ),
        pattern=_KRB_PREAUTH_FALSE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="krb-forwardable-tickets-global",
        name="Forwardable / proxiable Kerberos tickets globally enabled",
        severity="HIGH",
        description=(
            "forwardable=true or proxiable=true in krb5.conf [libdefaults], or "
            "RequirementFlag.delegate_to_peer / GSS_C_DELEG_FLAG in application code. "
            "A forwardable TGT is the prerequisite for unconstrained delegation exploitation."
        ),
        pattern=_KRB_FORWARDABLE_TRUE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="krb-dns-canonicalize-hostname",
        name="DNS canonicalization or DNS KDC discovery enabled in krb5.conf",
        severity="HIGH",
        description=(
            "dns_canonicalize_hostname=true, dns_lookup_kdc=true, or rdns=true in "
            "krb5.conf. DNS-based SPN construction allows an attacker controlling DNS to "
            "redirect service tickets to a machine they control."
        ),
        pattern=_KRB_DNS_CANONICALIZE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="krb-spnego-http-no-origin-binding",
        name="SPNEGO HTTP middleware without Origin or channel binding enforcement",
        severity="HIGH",
        description=(
            "HTTP Negotiate challenge or response without an Origin header allowlist or "
            "TLS channel binding check in the same handler. Cross-origin Negotiate relay "
            "allows a malicious page to obtain a valid SPNEGO token for an internal "
            "service. Dual Negotiate+NTLM WWW-Authenticate is a downgrade path."
        ),
        pattern=_SPNEGO_NEGOTIATE_EMIT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="krb-gssapi-ntlm-fallback-mechoid",
        name="GSSAPI mechOID includes NTLM fallback (OID 1.3.6.1.4.1.311.2.2.10)",
        severity="HIGH",
        description=(
            "NTLM mechOID 1.3.6.1.4.1.311.2.2.10 present in GSSAPI / SPNEGO negotiation "
            "code, or a negotiateMechanism referencing NTLM. NTLM is relay-vulnerable and "
            "deprecated by Microsoft ADV190023."
        ),
        pattern=_GSSAPI_NTLM_OID,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="krb-jaas-keytab-no-principal",
        name="Java JAAS Krb5LoginModule with keytab but no principal restriction",
        severity="HIGH",
        description=(
            "Krb5LoginModule with useKeyTab=true and storeKey=true but no principal= "
            "binding. Any keytab entry can be used for authentication. "
            "refreshKrb5Config=true adds a config-injection surface."
        ),
        pattern=_JAAS_KRB5_LOGIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="krb-dotnet-negotiate-delegation",
        name=".NET NegotiateStream or WindowsIdentity without ImpersonationLevel constraint",
        severity="HIGH",
        description=(
            "NegotiateStream.AuthenticateAsServer without an explicit impersonation level, "
            "WindowsIdentity.Impersonate() in application code, AllowNtlm=true, or "
            "TokenImpersonationLevel.Delegation (CRITICAL — full unconstrained delegation)."
        ),
        pattern=_DOTNET_DELEG_LEVEL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="krb-gmsa-password-extraction",
        name="GMSA managed-password attribute access or extraction tool fingerprint",
        severity="CRITICAL",
        description=(
            "msDS-ManagedPassword attribute read, GMSAPasswordReader, Get-GMSAPassword, "
            "ConvertTo-NTHash, or PrincipalsAllowedToRetrieveManagedPassword in code. "
            "These are attack-tool fingerprints for GMSA credential theft."
        ),
        pattern=_GMSA_ATTR_ACCESS,
        owasp_asi="ASI-01",
    ),
]

RULES: tuple[Rule, ...] = tuple(_RULES_LIST)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---------------------------------------------------------------------------
# scan_text — composed scanner
# ---------------------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:  # noqa: C901 — complexity is deliberate
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * P1 (rc4-hmac-etype-permitted) — fire on allow_weak_crypto=true directly;
        also fire on legacy etype list but only when a [libdefaults] section
        marker is present anywhere in the file.
      * P2 (preauth-disabled-kdc-config) — fire on require_preauth=false,
        restrict_anonymous_to_tgt=false, and kadmin modprinc -requires_preauth.
      * P3 (forwardable-tickets-global) — fire on forwardable=true,
        proxiable=true, and GSSAPI delegation flags.
      * P4 (dns-canonicalize-hostname) — fire on dns_canonicalize_hostname=true,
        dns_lookup_kdc=true, and rdns=true; suppress dns_lookup_kdc when a
        [realms] section is present (hard-coded KDCs make DNS a fallback).
      * P5 (spnego-http-no-origin-binding) — anchor on Negotiate header emitted
        or received; suppress when an Origin/channel-binding check appears in
        the same 50-line window.
      * P6 (gssapi-ntlm-fallback-mechoid) — fire on NTLM OID literal and on
        negotiateMechanism/NTLMSecurityProvider references.
      * P7 (jaas-keytab-no-principal) — fire when Krb5LoginModule + useKeyTab=true
        + storeKey=true all appear within 30 lines without a principal= line.
      * P8 (dotnet-negotiate-delegation) — CRITICAL tier for
        TokenImpersonationLevel.Delegation; HIGH tier for NegotiateStream +
        AuthenticateAsServer, WindowsIdentity.Impersonate(), and AllowNtlm=true.
      * P9 (gmsa-password-extraction) — fire on msDS-ManagedPassword,
        msDS-ManagedPasswordInterval, and tool-fingerprint tokens.

    Findings are deduped by (rule_id, line, col) and sorted by (line, col).
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

    # ---- P1 : krb-rc4-hmac-etype-permitted ----
    rule_p1 = rule_by_id["krb-rc4-hmac-etype-permitted"]
    for m in _KRB_WEAK_CRYPTO_ENABLED.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))
    # Legacy etype list: only fire when file looks like a krb5.conf.
    has_libdefaults = _file_contains(text, _KRB_LIBDEFAULTS_SECTION)
    if has_libdefaults:
        for m in _KRB_LEGACY_ETYPE_LIST.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : krb-preauth-disabled-kdc-config ----
    rule_p2 = rule_by_id["krb-preauth-disabled-kdc-config"]
    for m in _KRB_PREAUTH_FALSE.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))
    for m in _KRB_ANON_TGT_FALSE.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))
    for m in _KRB_KADMIN_REMOVE_PREAUTH.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : krb-forwardable-tickets-global ----
    rule_p3 = rule_by_id["krb-forwardable-tickets-global"]
    for m in _KRB_FORWARDABLE_TRUE.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))
    for m in _KRB_PROXIABLE_TRUE.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))
    for m in _KRB_GSSAPI_DELEG_FLAG.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : krb-dns-canonicalize-hostname ----
    rule_p4 = rule_by_id["krb-dns-canonicalize-hostname"]
    for m in _KRB_DNS_CANONICALIZE.finditer(text):
        _emit(rule_p4, m.start(), m.group(0))
    has_realms_section = _file_contains(text, _KRB_REALMS_SECTION)
    for m in _KRB_DNS_LOOKUP_KDC.finditer(text):
        # Suppress dns_lookup_kdc when [realms] hard-codes KDC addresses.
        if has_realms_section:
            continue
        _emit(rule_p4, m.start(), m.group(0))
    for m in _KRB_RDNS_TRUE.finditer(text):
        _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : krb-spnego-http-no-origin-binding ----
    rule_p5 = rule_by_id["krb-spnego-http-no-origin-binding"]
    for m in _SPNEGO_NEGOTIATE_EMIT.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 40)
        if _SPNEGO_ORIGIN_CHECK.search(window) is not None:
            continue
        _emit(rule_p5, m.start(), m.group(0))
    for m in _SPNEGO_NEGOTIATE_RECV.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 40)
        if _SPNEGO_ORIGIN_CHECK.search(window) is not None:
            continue
        _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : krb-gssapi-ntlm-fallback-mechoid ----
    rule_p6 = rule_by_id["krb-gssapi-ntlm-fallback-mechoid"]
    for m in _GSSAPI_NTLM_OID.finditer(text):
        _emit(rule_p6, m.start(), m.group(0))
    for m in _GSSAPI_NTLM_MECHLIST.finditer(text):
        _emit(rule_p6, m.start(), m.group(0))

    # ---- P7 : krb-jaas-keytab-no-principal ----
    rule_p7 = rule_by_id["krb-jaas-keytab-no-principal"]
    for m in _JAAS_KRB5_LOGIN.finditer(text):
        line, _ = _line_col(text, m.start())
        # 30-line forward window for the JAAS block content.
        window = _slice_forward(text, line, 30)
        if _JAAS_USE_KEYTAB.search(window) is None:
            continue
        if _JAAS_STORE_KEY.search(window) is None:
            continue
        if _JAAS_PRINCIPAL_SET.search(window) is not None:
            continue
        _emit(rule_p7, m.start(), m.group(0))

    # ---- P8 : krb-dotnet-negotiate-delegation ----
    rule_p8 = rule_by_id["krb-dotnet-negotiate-delegation"]
    # CRITICAL tier: Delegation level explicitly requested.
    for m in _DOTNET_DELEG_LEVEL.finditer(text):
        _emit(rule_p8, m.start(), m.group(0))
    # HIGH tier: NegotiateStream + AuthenticateAsServer co-occurrence.
    for m in _DOTNET_NEGOTIATE_STREAM.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 20)
        if _DOTNET_AUTH_AS_SERVER.search(window) is not None:
            _emit(rule_p8, m.start(), m.group(0))
    # HIGH tier: WindowsIdentity.Impersonate() call.
    for m in _DOTNET_WIN_IDENTITY_IMPERSONATE.finditer(text):
        _emit(rule_p8, m.start(), m.group(0))
    # HIGH tier: AllowNtlm=true fallback.
    for m in _DOTNET_ALLOW_NTLM.finditer(text):
        _emit(rule_p8, m.start(), m.group(0))

    # ---- P9 : krb-gmsa-password-extraction ----
    rule_p9 = rule_by_id["krb-gmsa-password-extraction"]
    for m in _GMSA_ATTR_ACCESS.finditer(text):
        _emit(rule_p9, m.start(), m.group(0))
    for m in _GMSA_INTERVAL_ATTR.finditer(text):
        _emit(rule_p9, m.start(), m.group(0))
    for m in _GMSA_TOOL_FINGERPRINT.finditer(text):
        _emit(rule_p9, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
