"""SSH / sshd config hardening, agent-forwarding and key-permissions
attack patterns.

Wave 21, angle A — distill-round-7 / `ssh-sshd-hardening.md` (16 proposals).

Detects misconfigurations and risky shapes across the SSH surface:

  * `/etc/ssh/sshd_config` (server side; `sshd-config` file_kind)
  * `~/.ssh/config` / `/etc/ssh/ssh_config` (client side; `ssh-config`)
  * `~/.ssh/authorized_keys` (`authorized-keys`)
  * shell/CI/Dockerfile scripts that invoke `ssh`, `ssh-keygen`,
    `ssh-keyscan` (`script`)

The catalogue does NOT duplicate anything already in
`git_ops_patterns.py` — git's `core.sshCommand` is handled there. The
file-permissions half of P13 (mode of `~/.ssh/id_*` files on disk) is
NOT in this regex module — it is a filesystem walk performed by the
heartbeat detector; this module exposes a helper (`is_safe_keyfile_mode`,
`is_safe_keyfile_dir_mode`, `is_safe_keyfile_pub_mode`) it can call.

Rules (1:1 with proposals P1 .. P16 in ssh-sshd-hardening.md):

| id                                    | severity | file_kind         |
|---------------------------------------|----------|-------------------|
| ssh-permit-root-login                 | CRITICAL | sshd-config       |
| ssh-password-authentication           | HIGH     | sshd-config       |
| ssh-permit-empty-passwords            | CRITICAL | sshd-config       |
| ssh-legacy-protocol-or-hostkey        | HIGH     | sshd-config       |
| ssh-x11-or-agent-forwarding-server    | HIGH     | sshd-config       |
| ssh-tcp-forwarding-or-tunnel          | HIGH     | sshd-config       |
| ssh-lax-auth-tries-or-grace           | MEDIUM   | sshd-config       |
| ssh-unbounded-client-alive            | MEDIUM   | sshd-config       |
| ssh-overpermissive-match-block        | HIGH     | sshd-config       |
| ssh-weak-ciphers-macs-kex             | HIGH     | sshd/ssh-config   |
| ssh-strict-host-key-checking-off      | CRITICAL | ssh-config/script |
| ssh-authorized-keys-risky-options     | HIGH     | authorized-keys   |
| ssh-weak-keygen-invocation            | HIGH     | script            |
| ssh-agent-forwarding-client           | HIGH     | ssh-config/script |
| ssh-keyscan-unverified-or-proxycmd    | HIGH     | ssh-config/script |
| ssh-misc-rng-listen-akcommand         | MEDIUM   | sshd-config       |

Public surface mirrors `auth_flow_patterns` and `git_ops_patterns`:
  * Rule(id, name, severity, description, pattern, owasp_asi, applies_to)
  * Finding (frozen NamedTuple, identical shape to siblings)
  * RULES — ordered tuple of every rule
  * scan_text(text, *, file_kind="any") -> list[Finding]
  * Helpers: is_safe_keyfile_mode(int)/is_safe_keyfile_dir_mode(int)/
    is_safe_keyfile_pub_mode(int), is_weak_cipher_name(str),
    is_weak_mac_name(str), is_weak_kex_name(str)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as the sibling modules so
    detectors can render every kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - stdlib name
    owasp_asi: str
    applies_to: frozenset[str]


def _re(pattern: str) -> re.Pattern:
    """Compile a regex with MULTILINE+UNICODE. `sshd_config` directive
    names are matched case-insensitively per `sshd_config(5)`
    ('Arguments may optionally be enclosed in double quotes', keywords
    are case-insensitive in OpenSSH parser) so IGNORECASE is set."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Compile a regex with MULTILINE+UNICODE only — for paths / shell
    commands where case is load-bearing."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- P1 — PermitRootLogin yes / without-password / prohibit-password ----


# Captures the value so the gate can WARN on `yes`, `without-password`,
# `prohibit-password` and pass on `no` or `forced-commands-only`. We
# anchor at start-of-line + optional whitespace and reject `#`-led
# comment lines (the `[^\s#]` look-ahead-by-negation works because
# the directive name itself cannot begin with `#`).
_PERMIT_ROOT_LOGIN = _re(
    r"^[ \t]*PermitRootLogin[ \t]+([A-Za-z0-9_\-]+)[ \t]*(?:#.*)?$"
)

# Risky values (anything other than `no` or `forced-commands-only`).
_PERMIT_ROOT_LOGIN_RISKY = frozenset({
    "yes", "without-password", "prohibit-password",
})


# ---- P2 — PasswordAuthentication yes ------------------------------------


# Three related directives that re-introduce password auth if left on.
_PASSWORD_AUTHN = _re(
    r"^[ \t]*(PasswordAuthentication|ChallengeResponseAuthentication"
    r"|KbdInteractiveAuthentication)[ \t]+(yes)\b"
)


# ---- P3 — PermitEmptyPasswords yes --------------------------------------


_PERMIT_EMPTY_PW = _re(
    r"^[ \t]*PermitEmptyPasswords[ \t]+(yes)\b"
)


# ---- P4 — legacy Protocol 1 / weak HostKey (DSA/ECDSA) ------------------


# Active Protocol 1 line (any value list containing 1).
_PROTOCOL_LEGACY = _re(
    r"^[ \t]*Protocol[ \t]+([0-9, ]*\b1\b[0-9, ]*)$"
)

# HostKey pointing at dsa or ecdsa host keys. Matches typical paths
# (`/etc/ssh/ssh_host_dsa_key`, `~/.ssh/ssh_host_ecdsa_key`).
_HOSTKEY_WEAK = _re(
    r"^[ \t]*HostKey[ \t]+\S*ssh_host_(dsa|ecdsa)_key\b"
)


# ---- P5 — X11Forwarding yes / AllowAgentForwarding yes ------------------


_X11_OR_AGENT_FWD = _re(
    r"^[ \t]*(X11Forwarding|AllowAgentForwarding)[ \t]+(yes)\b"
)


# ---- P6 — AllowTcpForwarding / PermitTunnel -----------------------------


# AllowTcpForwarding: `yes`, `local`, `remote`, `all` are all permissive.
_TCP_FORWARDING = _re(
    r"^[ \t]*AllowTcpForwarding[ \t]+(yes|local|remote|all)\b"
)

# PermitTunnel: anything other than `no` is a finding.
_PERMIT_TUNNEL = _re(
    r"^[ \t]*PermitTunnel[ \t]+(yes|point-to-point|ethernet)\b"
)


# ---- P7 — MaxAuthTries / LoginGraceTime / MaxStartups -------------------


_MAX_AUTH_TRIES = _re(
    r"^[ \t]*MaxAuthTries[ \t]+(\d+)\b"
)

# LoginGraceTime accepts plain seconds OR a suffixed form: `2m`, `30s`,
# `1h`. We capture the number + optional suffix; the gate normalises.
_LOGIN_GRACE_TIME = _re(
    r"^[ \t]*LoginGraceTime[ \t]+(\d+)([smhdw]?)\b"
)

_MAX_STARTUPS = _re(
    r"^[ \t]*MaxStartups[ \t]+(\d+)(?::\d+:\d+)?\b"
)


# ---- P8 — ClientAliveInterval / ClientAliveCountMax ---------------------


_CLIENT_ALIVE_INTERVAL = _re(
    r"^[ \t]*ClientAliveInterval[ \t]+(\d+)\b"
)

_CLIENT_ALIVE_COUNT_MAX = _re(
    r"^[ \t]*ClientAliveCountMax[ \t]+(\d+)\b"
)


# ---- P9 — Over-permissive Match blocks ----------------------------------


# `Match User *` / `Match Address 0.0.0.0/0` / `Match Address ::/0` —
# patterns that are effectively no-match-narrowing. We catch the
# header line; severity escalation when paired with a re-enabling
# directive in the block body is the detector's job.
_MATCH_OVERPERMISSIVE = _re(
    r"^[ \t]*Match[ \t]+(?:"
    r"User[ \t]+\*"
    r"|Address[ \t]+0\.0\.0\.0/0"
    r"|Address[ \t]+::/0"
    r"|Group[ \t]+\*"
    r"|Host[ \t]+\*"
    r")[ \t]*$"
)


# ---- P10 — Weak Ciphers / MACs / KexAlgorithms / HostKeyAlgorithms ------


# Match the entire directive line so the gate can pick out names.
_CIPHERS_LINE = _re(
    r"^[ \t]*Ciphers[ \t]+([A-Za-z0-9@,_\-.+]+)[ \t]*(?:#.*)?$"
)
_MACS_LINE = _re(
    r"^[ \t]*MACs[ \t]+([A-Za-z0-9@,_\-.+]+)[ \t]*(?:#.*)?$"
)
_KEX_LINE = _re(
    r"^[ \t]*KexAlgorithms[ \t]+([A-Za-z0-9@,_\-.+]+)[ \t]*(?:#.*)?$"
)
_HOSTKEYALGOS_LINE = _re(
    r"^[ \t]*HostKeyAlgorithms[ \t]+([A-Za-z0-9@,_\-.+]+)[ \t]*(?:#.*)?$"
)

# Weak entries — the gate matches each comma-separated value against
# these sets. Sources: Mozilla OpenSSH Modern profile + sshaudit.com.
_WEAK_CIPHERS = frozenset({
    "arcfour", "arcfour128", "arcfour256",
    "blowfish-cbc", "3des-cbc", "cast128-cbc",
    "aes128-cbc", "aes192-cbc", "aes256-cbc",
    "des-cbc",
})
_WEAK_MACS = frozenset({
    "hmac-md5", "hmac-md5-96", "hmac-md5-etm@openssh.com",
    "hmac-md5-96-etm@openssh.com",
    "hmac-sha1", "hmac-sha1-96", "hmac-sha1-etm@openssh.com",
    "hmac-sha1-96-etm@openssh.com",
    "umac-64@openssh.com", "umac-64-etm@openssh.com",
    "hmac-ripemd160", "hmac-ripemd160-etm@openssh.com",
})
_WEAK_KEX = frozenset({
    "diffie-hellman-group1-sha1",
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group-exchange-sha1",
    "gss-gex-sha1-",
    "rsa1024-sha1",
})


# ---- P11 — StrictHostKeyChecking no / accept-new ------------------------


# Two shapes: an `~/.ssh/config` line, or a shell `-o` flag.
_STRICT_HK_CHECKING_CONFIG = _re(
    r"^[ \t]*StrictHostKeyChecking[ \t]+(no|accept-new)\b"
)

# Inline -o flag, with optional quotes, in scripts.
_STRICT_HK_CHECKING_FLAG = _re_cs(
    r"-o\s*['\"]?\s*StrictHostKeyChecking\s*=\s*(no|accept-new)\b"
)


# ---- P12 — Risky authorized_keys options --------------------------------


# An authorized_keys line begins with an OPTIONS field (anything before
# the first key-type token) followed by the key type. We capture the
# options blob to gate on missing/risky fields.
_AUTHORIZED_KEY_TYPES = (
    r"ssh-ed25519|ssh-rsa|ssh-dss"
    r"|ecdsa-sha2-nistp(?:256|384|521)"
    r"|sk-ecdsa-sha2-nistp256@openssh\.com"
    r"|sk-ssh-ed25519@openssh\.com"
)

_AUTHORIZED_KEY_LINE = _re_cs(
    # `options` is everything before the key-type token, on the same
    # line. It MAY be empty (an authorized_keys line with no options
    # at all is a finding because it has no `from=` pin). We anchor at
    # start of line, optionally consume an options blob followed by
    # whitespace, then match the key-type token + base64 blob.
    rf"^(?P<options>[^\r\n]*?)(?:[ \t]+)?"
    rf"\b(?P<keytype>{_AUTHORIZED_KEY_TYPES})\b"
    rf"[ \t]+[A-Za-z0-9+/=]+"
)

# Inline detectors used by the gate, applied to the options blob.
_OPT_FROM_WILDCARD = re.compile(r'\bfrom="[^"]*\*[^"]*"')
_OPT_FROM_PRESENT = re.compile(r'\bfrom="[^"]+"')
_OPT_RESTRICT = re.compile(r"\brestrict\b")
_OPT_COMMAND = re.compile(r'\bcommand="(?P<cmd>[^"]*)"')
_OPT_NO_PORT_FWD = re.compile(r"\bno-port-forwarding\b")
_OPT_NO_X11_FWD = re.compile(r"\bno-X11-forwarding\b")
_OPT_NO_AGENT_FWD = re.compile(r"\bno-agent-forwarding\b")
_OPT_NO_PTY = re.compile(r"\bno-pty\b")


# ---- P13 — Weak ssh-keygen invocation -----------------------------------


# Captures `ssh-keygen` invocations with weak algorithm choices. We
# rely on POSIX argv form `-t TYPE [-b BITS]`.
# Cases flagged:
#   * `-t dsa`
#   * `-t rsa` followed elsewhere by `-b 512|-b 1024`
#   * `-t ecdsa` followed by any `-b` (NIST curves of contested provenance)
_KEYGEN_DSA = _re_cs(
    r"\bssh-keygen\b[^\n]{0,200}-t\s+dsa\b"
)

_KEYGEN_RSA_WEAK_BITS = _re_cs(
    r"\bssh-keygen\b[^\n]{0,200}-t\s+rsa\b[^\n]{0,200}-b\s+(512|1024|2048)\b"
    r"|"
    r"\bssh-keygen\b[^\n]{0,200}-b\s+(512|1024|2048)\b[^\n]{0,200}-t\s+rsa\b"
)

_KEYGEN_ECDSA = _re_cs(
    r"\bssh-keygen\b[^\n]{0,200}-t\s+ecdsa\b"
)


# ---- P14 — ssh -A / ForwardAgent yes (client-side agent forwarding) -----


# `ssh -A` flag in scripts. We must not match `-Av` (verbose), but
# `-A` followed by a space or end-of-arg is fine. We also accept the
# `-A` placed anywhere among other short flags.
_SSH_AGENT_FWD_FLAG = _re_cs(
    r"\bssh\s+(?:-[A-Za-z0-9]*A[A-Za-z0-9]*\s|"
    r"[^\n#]{0,100}\s-A(?=\s))"
)

_FORWARD_AGENT_YES = _re(
    r"^[ \t]*ForwardAgent[ \t]+(yes)\b"
)


# ---- P15 — ssh-keyscan unverified + ProxyCommand from suspicious path ---


# `ssh-keyscan` line in a script — the gate then checks the surrounding
# text for a fingerprint-verification step. We catch the invocation.
_SSH_KEYSCAN_INVOCATION = _re_cs(
    r"\bssh-keyscan\b[^\n|]{0,200}"
)

# Pattern that demonstrates fingerprint verification (anywhere in the
# file). Presence suppresses every keyscan hit for that file.
_KEYSCAN_VERIFY_HINTS: tuple[re.Pattern, ...] = (
    re.compile(r"\bssh-keygen\b[^\n]{0,80}-l\b", re.MULTILINE),
    re.compile(r"\bsha256\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bfingerprint\b", re.IGNORECASE | re.MULTILINE),
)

# ProxyCommand line pointing into a tmp / cache / download dir. Same
# regex used in both `~/.ssh/config` and shell `-o ProxyCommand=` flag.
_PROXYCOMMAND_LINE = _re(
    r"^[ \t]*ProxyCommand[ \t]+(?P<cmd>[^\r\n]+)$"
)

_PROXYCOMMAND_FLAG = _re_cs(
    r"-o\s*['\"]?ProxyCommand\s*=\s*['\"]?(?P<cmd>[^'\"\r\n]+)"
)

# Suspicious prefix list applied to the ProxyCommand value.
_PROXYCOMMAND_SUSPICIOUS_PREFIX = re.compile(
    r"^(?:/tmp/|/var/tmp/|~/Downloads/|~/\.cache/|/dev/shm/)",
    re.MULTILINE,
)


# ---- P16 — SSHD_USE_STRONG_RNG=0 / AuthorizedKeysCommand / ListenAddress


_SSHD_WEAK_RNG = _re(
    r"^[ \t]*SSHD_USE_STRONG_RNG\s*=\s*0\b"
)

_AUTHORIZED_KEYS_COMMAND = _re(
    r"^[ \t]*AuthorizedKeysCommand[ \t]+([^\r\n]+?)[ \t]*$"
)

# `ListenAddress 0.0.0.0` or absent default; we flag explicit `0.0.0.0`
# and `::` because the heartbeat detector can pair this with a
# multi-NIC check externally.
_LISTEN_ADDRESS_ALL = _re(
    r"^[ \t]*ListenAddress[ \t]+(0\.0\.0\.0|::)[ \t]*$"
)


# ---- Helpers exposed to the heartbeat detector --------------------------


def is_safe_keyfile_mode(mode: int) -> bool:
    """True if `mode` is a safe SSH private-key file mode.

    Safe values: 0o600 or 0o400. `mode` is the octal int already
    masked to file-permission bits (`stat().st_mode & 0o777`)."""
    return mode in {0o600, 0o400}


def is_safe_keyfile_pub_mode(mode: int) -> bool:
    """True if `mode` is a safe SSH public-key file mode.

    Safe values: 0o644 or stricter (0o600, 0o400 also fine)."""
    # Any mode where group/other have only read or no bits is fine.
    return (mode & 0o133) == 0


def is_safe_keyfile_dir_mode(mode: int) -> bool:
    """True if `mode` is a safe `~/.ssh/` directory mode.

    Safe value: 0o700. Group/other must have no permissions."""
    return mode == 0o700


def is_weak_cipher_name(name: str) -> bool:
    """True if `name` is in the weak-cipher allowlist."""
    return name.strip() in _WEAK_CIPHERS


def is_weak_mac_name(name: str) -> bool:
    """True if `name` is in the weak-MAC allowlist."""
    return name.strip() in _WEAK_MACS


def is_weak_kex_name(name: str) -> bool:
    """True if `name` is in the weak-KEX allowlist."""
    return name.strip() in _WEAK_KEX


def _login_grace_time_seconds(value: str, suffix: str) -> int:
    """Normalise a LoginGraceTime value to seconds. OpenSSH suffixes:
    s=1, m=60, h=3600, d=86400, w=604800. Empty suffix = seconds."""
    n = int(value)
    mult = {
        "": 1, "s": 1,
        "m": 60, "h": 3600, "d": 86400, "w": 604800,
    }.get(suffix, 1)
    return n * mult


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ssh-permit-root-login",
        name="`PermitRootLogin` allows root login over SSH",
        severity="CRITICAL",
        description=(
            "`sshd_config` sets `PermitRootLogin` to a value that allows "
            "root login (`yes`, `without-password`, `prohibit-password`). "
            "Root login over SSH is the canonical privilege-escalation "
            "vector. CIS Benchmarks 5.2.7 / NIST 800-53 AC-6 require "
            "`PermitRootLogin no`; `forced-commands-only` is the narrow "
            "exception for backup / orchestration automation."
        ),
        pattern=_PERMIT_ROOT_LOGIN,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-password-authentication",
        name="`PasswordAuthentication` / challenge-response / KbdInteractive enabled",
        severity="HIGH",
        description=(
            "`PasswordAuthentication yes` (or `ChallengeResponseAuthentication "
            "yes`, `KbdInteractiveAuthentication yes`) makes the host a "
            "brute-force target. With public-key auth + key-file mode "
            "enforced, password auth is unnecessary. CIS 5.2.8 / NIST "
            "800-53 IA-2(11) require `no`."
        ),
        pattern=_PASSWORD_AUTHN,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-permit-empty-passwords",
        name="`PermitEmptyPasswords yes` allows authentication without a password",
        severity="CRITICAL",
        description=(
            "`PermitEmptyPasswords yes` lets an account with an empty "
            "password authenticate over SSH. Even when password auth is "
            "globally disabled this is a defense-in-depth slip. CIS 5.2.9 "
            "requires the explicit `no`. There is no legitimate use case."
        ),
        pattern=_PERMIT_EMPTY_PW,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-legacy-protocol-or-hostkey",
        name="Legacy `Protocol 1` or weak HostKey (DSA / ECDSA)",
        severity="HIGH",
        description=(
            "`Protocol 1` was removed from OpenSSH 7.0 (2015). DSA host "
            "keys are capped at 1024 bits; ECDSA host keys rely on NIST "
            "curves of contested provenance. Mozilla OpenSSH Modern "
            "profile / sshaudit.com recommend ed25519 + RSA 4096."
        ),
        pattern=_PROTOCOL_LEGACY,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-x11-or-agent-forwarding-server",
        name="`X11Forwarding yes` / `AllowAgentForwarding yes` on server",
        severity="HIGH",
        description=(
            "`X11Forwarding yes` has a long history of privilege-escalation "
            "CVEs (CVE-2023-28531 chain). `AllowAgentForwarding yes` lets "
            "a downstream compromised host pivot through the user's "
            "ssh-agent — the spider-web attack. Both default to `yes` on "
            "stock OpenSSH; both should be `no` unless a narrow `Match` "
            "block re-enables them for a specific account."
        ),
        pattern=_X11_OR_AGENT_FWD,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-tcp-forwarding-or-tunnel",
        name="`AllowTcpForwarding` / `PermitTunnel` permissive value",
        severity="HIGH",
        description=(
            "`AllowTcpForwarding yes` (default) lets any authenticated user "
            "open arbitrary TCP tunnels — exfiltration and internal-network "
            "pivot. `PermitTunnel yes` allows full Layer-3 tunneling. "
            "Bastion hosts need `AllowTcpForwarding yes` but never "
            "`PermitTunnel`; general-purpose servers need neither."
        ),
        pattern=_TCP_FORWARDING,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-lax-auth-tries-or-grace",
        name="`MaxAuthTries` / `LoginGraceTime` / `MaxStartups` too lax",
        severity="MEDIUM",
        description=(
            "OpenSSH defaults of `MaxAuthTries 6`, `LoginGraceTime 120s`, "
            "`MaxStartups 10:30:100` permit brute-force scripts to exhaust "
            "auth retries / hold connections open. CIS 5.2.20–5.2.21 "
            "recommend `MaxAuthTries 3`, `LoginGraceTime 30`, "
            "`MaxStartups 10:30:60`."
        ),
        pattern=_MAX_AUTH_TRIES,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-unbounded-client-alive",
        name="`ClientAliveInterval` 0 / unbounded session timeout",
        severity="MEDIUM",
        description=(
            "`ClientAliveInterval 0` (default) plus a high "
            "`ClientAliveCountMax` lets an orphaned session sit idle "
            "forever — an attacker finding an unlocked terminal can "
            "resume the session. CIS 5.2.22 recommends "
            "`ClientAliveInterval 300` + `ClientAliveCountMax 2`."
        ),
        pattern=_CLIENT_ALIVE_INTERVAL,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-overpermissive-match-block",
        name="`Match` block uses an effectively-wildcard predicate",
        severity="HIGH",
        description=(
            "`Match User *` / `Match Address 0.0.0.0/0` / `Match Address "
            "::/0` / `Match Group *` / `Match Host *` are predicates that "
            "match every connection — usually a copy-paste error from a "
            "HOWTO that re-opens settings the global config locked down. "
            "Narrow the predicate (e.g. `Match User ansible-ci`)."
        ),
        pattern=_MATCH_OVERPERMISSIVE,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
    Rule(
        id="ssh-weak-ciphers-macs-kex",
        name="`Ciphers` / `MACs` / `KexAlgorithms` / `HostKeyAlgorithms` weak entry",
        severity="HIGH",
        description=(
            "Symmetric / MAC / KEX algorithm list contains a known-weak "
            "entry (arcfour, 3des-cbc, *-cbc, hmac-md5*, hmac-sha1*, "
            "umac-64*, diffie-hellman-group1-sha1, group14-sha1, "
            "group-exchange-sha1). Mozilla OpenSSH Modern profile + "
            "sshaudit.com keep the modern-only allowlist."
        ),
        pattern=_CIPHERS_LINE,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "ssh-config", "any"}),
    ),
    Rule(
        id="ssh-strict-host-key-checking-off",
        name="`StrictHostKeyChecking no` / `accept-new` (MITM exposure)",
        severity="CRITICAL",
        description=(
            "`StrictHostKeyChecking no` accepts any host key without "
            "prompting — a MITM attacker can re-terminate the SSH session. "
            "`StrictHostKeyChecking accept-new` is TOFU; acceptable in CI "
            "ONLY when paired with `UserKnownHostsFile` pinning to a "
            "checked-in fingerprint, otherwise the safety claim is empty."
        ),
        pattern=_STRICT_HK_CHECKING_CONFIG,
        owasp_asi="",
        applies_to=frozenset({"ssh-config", "script", "any"}),
    ),
    Rule(
        id="ssh-authorized-keys-risky-options",
        name="`authorized_keys` entry lacks `from=` / `restrict` / has injection-prone `command=`",
        severity="HIGH",
        description=(
            "`authorized_keys` line carries no `from=\"...\"` source "
            "restriction, uses `from=\"*\"` (matches everything), has a "
            "`command=\"...\"` without `restrict` (or without all of "
            "`no-port-forwarding`, `no-X11-forwarding`, `no-agent-forwarding`, "
            "`no-pty`), or has a `command=` value containing an unquoted "
            "shell variable expansion."
        ),
        pattern=_AUTHORIZED_KEY_LINE,
        owasp_asi="",
        applies_to=frozenset({"authorized-keys", "any"}),
    ),
    Rule(
        id="ssh-weak-keygen-invocation",
        name="`ssh-keygen` invocation uses weak algorithm / key size",
        severity="HIGH",
        description=(
            "`ssh-keygen -t dsa` produces a 1024-bit DSA key (removed in "
            "OpenSSH 7.0). `-t rsa -b <=2048` is below modern guidance. "
            "`-t ecdsa` uses NIST curves of contested provenance. Modern "
            "guidance: `ssh-keygen -t ed25519 -a 100 -C ...` (preferred) "
            "or `-t rsa -b 4096 -a 100`."
        ),
        pattern=_KEYGEN_DSA,
        owasp_asi="",
        applies_to=frozenset({"script", "any"}),
    ),
    Rule(
        id="ssh-agent-forwarding-client",
        name="`ssh -A` flag / `ForwardAgent yes` (client-side agent forwarding)",
        severity="HIGH",
        description=(
            "Client-side agent-forwarding (the `-A` flag, or `ForwardAgent "
            "yes` in `~/.ssh/config`) forwards the local ssh-agent socket "
            "into the remote host. If the remote is compromised, every "
            "key in the agent can authenticate as the user. Use "
            "`ssh -J user@bastion target` (ProxyJump) instead."
        ),
        pattern=_SSH_AGENT_FWD_FLAG,
        owasp_asi="",
        applies_to=frozenset({"ssh-config", "script", "any"}),
    ),
    Rule(
        id="ssh-keyscan-unverified-or-proxycmd",
        name="`ssh-keyscan` without fingerprint verify / `ProxyCommand` from suspicious path",
        severity="HIGH",
        description=(
            "Either (1) `ssh-keyscan ... >> known_hosts` without a "
            "fingerprint-verification step in the same script (TOFU at "
            "the worst time), or (2) `ProxyCommand` pointing at a binary "
            "under `/tmp/`, `/var/tmp/`, `~/Downloads/`, `~/.cache/`, "
            "`/dev/shm/` — almost always either malware or an experimental "
            "setup that escaped cleanup."
        ),
        pattern=_SSH_KEYSCAN_INVOCATION,
        owasp_asi="",
        applies_to=frozenset({"ssh-config", "script", "any"}),
    ),
    Rule(
        id="ssh-misc-rng-listen-akcommand",
        name="`SSHD_USE_STRONG_RNG=0` / `AuthorizedKeysCommand` / `ListenAddress 0.0.0.0`",
        severity="MEDIUM",
        description=(
            "Three smaller findings: `SSHD_USE_STRONG_RNG=0` (cargo-cult "
            "RNG tuning), `AuthorizedKeysCommand` (path will be stat-ed "
            "for root-ownership + non-world-writable by the heartbeat "
            "detector), `ListenAddress 0.0.0.0` (binds every interface "
            "on a multi-NIC host)."
        ),
        pattern=_SSHD_WEAK_RNG,
        owasp_asi="",
        applies_to=frozenset({"sshd-config", "any"}),
    ),
)


# ---- Scanner -----------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _emit(
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
    rule_id: str,
    line: int,
    column: int,
    matched: str,
    severity: str,
    description: str,
) -> None:
    """Dedupe + append a finding. Truncate matched_text to 200 chars."""
    key = (rule_id, line, column)
    if key in seen:
        return
    seen.add(key)
    if len(matched) > 200:
        matched = matched[:200] + "…"
    findings.append(Finding(
        rule_id=rule_id,
        line=line,
        column=column,
        matched_text=matched,
        severity=severity,
        description=description,
        owasp_asi="",
    ))


def _scan_weak_algorithms(
    text: str,
    pattern: re.Pattern,
    weak_set: frozenset[str],
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
) -> None:
    """Common scanner for Ciphers/MACs/KexAlgorithms lines."""
    rule = next(r for r in RULES if r.id == "ssh-weak-ciphers-macs-kex")
    for m in pattern.finditer(text):
        value_list = m.group(1)
        # Emit one finding per weak entry. The line is the directive
        # line itself; the column points to the start of the directive.
        for name in value_list.split(","):
            n = name.strip()
            if n in weak_set:
                line, col = _line_col(text, m.start())
                _emit(
                    findings, seen, rule.id, line, col,
                    f"{m.group(0).strip()} -> weak entry: {n}",
                    rule.severity, rule.description,
                )


def _scan_authorized_keys_options(
    text: str,
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
) -> None:
    """Apply P12 gates to every authorized_keys entry."""
    rule = next(r for r in RULES if r.id == "ssh-authorized-keys-risky-options")
    for m in _AUTHORIZED_KEY_LINE.finditer(text):
        options = m.group("options") or ""
        options = options.strip()
        line, col = _line_col(text, m.start())
        line_text = m.group(0)

        # Skip comment / blank lines (the regex anchoring already
        # excludes pure-comment lines but we guard anyway).
        if options.startswith("#"):
            continue

        # 1) from="*" — actively permissive wildcard. Always a finding.
        if _OPT_FROM_WILDCARD.search(options):
            _emit(
                findings, seen, rule.id, line, col,
                f'{line_text.strip()[:160]} -> from="*" matches every source',
                rule.severity, rule.description,
            )
            continue

        # 2) No from= at all — automation keys MUST be source-pinned.
        if not _OPT_FROM_PRESENT.search(options):
            _emit(
                findings, seen, rule.id, line, col,
                f'{line_text.strip()[:160]} -> missing from="..." pin',
                rule.severity, rule.description,
            )
            # Fall through — also check command= shape below.

        # 3) command="..." without `restrict` AND missing one or more
        #    of the no-* options.
        cmd_match = _OPT_COMMAND.search(options)
        if cmd_match:
            has_restrict = _OPT_RESTRICT.search(options) is not None
            if not has_restrict:
                missing = []
                if not _OPT_NO_PORT_FWD.search(options):
                    missing.append("no-port-forwarding")
                if not _OPT_NO_X11_FWD.search(options):
                    missing.append("no-X11-forwarding")
                if not _OPT_NO_AGENT_FWD.search(options):
                    missing.append("no-agent-forwarding")
                if not _OPT_NO_PTY.search(options):
                    missing.append("no-pty")
                if missing:
                    _emit(
                        findings, seen, rule.id, line, col,
                        (
                            f'{line_text.strip()[:160]} -> command="..." '
                            f"without restrict and missing: {','.join(missing)}"
                        ),
                        rule.severity, rule.description,
                    )

            # 4) Shell-variable expansion inside command="..." value.
            cmd_value = cmd_match.group("cmd")
            if "$" in cmd_value:
                _emit(
                    findings, seen, rule.id, line, col,
                    (
                        f'{line_text.strip()[:160]} -> command="..." '
                        f"contains shell variable: {cmd_value[:80]}"
                    ),
                    rule.severity, rule.description,
                )


def _scan_match_blocks(
    text: str,
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
) -> None:
    """Emit one finding per over-permissive `Match` header line."""
    rule = next(r for r in RULES if r.id == "ssh-overpermissive-match-block")
    for m in _MATCH_OVERPERMISSIVE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            findings, seen, rule.id, line, col,
            m.group(0).strip(), rule.severity, rule.description,
        )


def _scan_keyscan_and_proxycommand(
    text: str,
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
    file_kind: str,
) -> None:
    """P15 — composite rule covering ssh-keyscan + ProxyCommand."""
    rule = next(r for r in RULES if r.id == "ssh-keyscan-unverified-or-proxycmd")

    # ssh-keyscan: only emit when there is NO verification hint
    # anywhere in the file.
    has_verify = any(p.search(text) for p in _KEYSCAN_VERIFY_HINTS)
    if not has_verify:
        for m in _SSH_KEYSCAN_INVOCATION.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                (
                    f"{m.group(0).strip()[:160]} -> "
                    "no fingerprint verification in this file"
                ),
                rule.severity, rule.description,
            )

    # ProxyCommand from suspicious path — config line shape.
    for m in _PROXYCOMMAND_LINE.finditer(text):
        cmd = m.group("cmd").strip()
        if _PROXYCOMMAND_SUSPICIOUS_PREFIX.match(cmd):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                f"ProxyCommand {cmd[:160]} -> suspicious path prefix",
                rule.severity, rule.description,
            )

    # ProxyCommand flag in scripts.
    if file_kind in ("script", "any"):
        for m in _PROXYCOMMAND_FLAG.finditer(text):
            cmd = m.group("cmd").strip()
            if _PROXYCOMMAND_SUSPICIOUS_PREFIX.match(cmd):
                line, col = _line_col(text, m.start())
                _emit(
                    findings, seen, rule.id, line, col,
                    f"-o ProxyCommand={cmd[:160]} -> suspicious path prefix",
                    rule.severity, rule.description,
                )


def _scan_misc(
    text: str,
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
) -> None:
    """P16 — composite rule covering three smaller findings."""
    rule = next(r for r in RULES if r.id == "ssh-misc-rng-listen-akcommand")

    # SSHD_USE_STRONG_RNG=0
    for m in _SSHD_WEAK_RNG.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            findings, seen, rule.id, line, col,
            m.group(0).strip(), rule.severity, rule.description,
        )

    # AuthorizedKeysCommand — emit the directive line (the path stat
    # gate happens externally; we just surface the directive).
    for m in _AUTHORIZED_KEYS_COMMAND.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            findings, seen, rule.id, line, col,
            (
                f"{m.group(0).strip()} -> "
                "verify path owner=root, mode<=0755"
            ),
            rule.severity, rule.description,
        )

    # ListenAddress 0.0.0.0 / ::
    for m in _LISTEN_ADDRESS_ALL.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            findings, seen, rule.id, line, col,
            f"{m.group(0).strip()} -> binds every interface",
            rule.severity, rule.description,
        )


def scan_text(text: str, *, file_kind: str = "any") -> list[Finding]:
    """Run every applicable rule against `text` and return findings.

    `file_kind` selects which subset of rules runs (mirrors the on-disk
    file routing done by the heartbeat detector):

    * `sshd-config`    — `/etc/ssh/sshd_config`, `sshd_config.d/*.conf`
    * `ssh-config`     — `~/.ssh/config`, `/etc/ssh/ssh_config`,
                         `ssh_config.d/*.conf`
    * `authorized-keys`— `~/.ssh/authorized_keys`
    * `script`         — shell, Python, Dockerfile, Makefile, GitHub
                         Actions workflows
    * `any` (default)  — run every rule; caller filters by file path

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id) — same shape as the sibling modules.
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def applies(rule: Rule) -> bool:
        return file_kind == "any" or file_kind in rule.applies_to

    # P1 — PermitRootLogin
    rule = next(r for r in RULES if r.id == "ssh-permit-root-login")
    if applies(rule):
        for m in _PERMIT_ROOT_LOGIN.finditer(text):
            value = m.group(1).strip().lower()
            if value not in _PERMIT_ROOT_LOGIN_RISKY:
                continue
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P2 — PasswordAuthentication / Challenge / KbdInteractive
    rule = next(r for r in RULES if r.id == "ssh-password-authentication")
    if applies(rule):
        for m in _PASSWORD_AUTHN.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P3 — PermitEmptyPasswords
    rule = next(r for r in RULES if r.id == "ssh-permit-empty-passwords")
    if applies(rule):
        for m in _PERMIT_EMPTY_PW.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P4 — Protocol 1 / weak HostKey
    rule = next(r for r in RULES if r.id == "ssh-legacy-protocol-or-hostkey")
    if applies(rule):
        for m in _PROTOCOL_LEGACY.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )
        for m in _HOSTKEY_WEAK.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P5 — X11Forwarding / AllowAgentForwarding (server side)
    rule = next(r for r in RULES if r.id == "ssh-x11-or-agent-forwarding-server")
    if applies(rule):
        for m in _X11_OR_AGENT_FWD.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P6 — AllowTcpForwarding / PermitTunnel
    rule = next(r for r in RULES if r.id == "ssh-tcp-forwarding-or-tunnel")
    if applies(rule):
        for m in _TCP_FORWARDING.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )
        for m in _PERMIT_TUNNEL.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P7 — MaxAuthTries / LoginGraceTime / MaxStartups
    rule = next(r for r in RULES if r.id == "ssh-lax-auth-tries-or-grace")
    if applies(rule):
        for m in _MAX_AUTH_TRIES.finditer(text):
            try:
                value = int(m.group(1))
            except ValueError:
                continue
            if value >= 4:
                line, col = _line_col(text, m.start())
                _emit(
                    findings, seen, rule.id, line, col,
                    m.group(0).strip(), rule.severity, rule.description,
                )
        for m in _LOGIN_GRACE_TIME.finditer(text):
            try:
                seconds = _login_grace_time_seconds(m.group(1), m.group(2))
            except ValueError:
                continue
            if seconds >= 60:
                line, col = _line_col(text, m.start())
                _emit(
                    findings, seen, rule.id, line, col,
                    m.group(0).strip(), rule.severity, rule.description,
                )
        for m in _MAX_STARTUPS.finditer(text):
            try:
                value = int(m.group(1))
            except ValueError:
                continue
            if value > 10:
                line, col = _line_col(text, m.start())
                _emit(
                    findings, seen, rule.id, line, col,
                    m.group(0).strip(), rule.severity, rule.description,
                )

    # P8 — ClientAliveInterval / ClientAliveCountMax
    rule = next(r for r in RULES if r.id == "ssh-unbounded-client-alive")
    if applies(rule):
        for m in _CLIENT_ALIVE_INTERVAL.finditer(text):
            try:
                value = int(m.group(1))
            except ValueError:
                continue
            if value == 0:
                line, col = _line_col(text, m.start())
                _emit(
                    findings, seen, rule.id, line, col,
                    m.group(0).strip(), rule.severity, rule.description,
                )
        for m in _CLIENT_ALIVE_COUNT_MAX.finditer(text):
            try:
                value = int(m.group(1))
            except ValueError:
                continue
            if value >= 3:
                line, col = _line_col(text, m.start())
                _emit(
                    findings, seen, rule.id, line, col,
                    m.group(0).strip(), rule.severity, rule.description,
                )

    # P9 — Over-permissive Match blocks
    rule = next(r for r in RULES if r.id == "ssh-overpermissive-match-block")
    if applies(rule):
        _scan_match_blocks(text, findings, seen)

    # P10 — Weak Ciphers / MACs / KexAlgorithms / HostKeyAlgorithms
    rule = next(r for r in RULES if r.id == "ssh-weak-ciphers-macs-kex")
    if applies(rule):
        _scan_weak_algorithms(text, _CIPHERS_LINE, _WEAK_CIPHERS, findings, seen)
        _scan_weak_algorithms(text, _MACS_LINE, _WEAK_MACS, findings, seen)
        _scan_weak_algorithms(text, _KEX_LINE, _WEAK_KEX, findings, seen)
        # HostKeyAlgorithms — weak entries overlap with KEX/Cipher names
        # for our purposes (anything ssh-dss / ssh-rsa-only). For now we
        # check against the union to flag obvious legacy listings.
        _scan_weak_algorithms(
            text, _HOSTKEYALGOS_LINE,
            frozenset({"ssh-dss", "ssh-rsa", "ssh-dss-cert-v01@openssh.com"}),
            findings, seen,
        )

    # P11 — StrictHostKeyChecking no / accept-new
    rule = next(r for r in RULES if r.id == "ssh-strict-host-key-checking-off")
    if applies(rule):
        for m in _STRICT_HK_CHECKING_CONFIG.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )
        for m in _STRICT_HK_CHECKING_FLAG.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P12 — authorized_keys risky options
    rule = next(r for r in RULES if r.id == "ssh-authorized-keys-risky-options")
    if applies(rule):
        _scan_authorized_keys_options(text, findings, seen)

    # P13 — Weak ssh-keygen invocations
    rule = next(r for r in RULES if r.id == "ssh-weak-keygen-invocation")
    if applies(rule):
        for m in _KEYGEN_DSA.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )
        for m in _KEYGEN_RSA_WEAK_BITS.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )
        for m in _KEYGEN_ECDSA.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P14 — ssh -A / ForwardAgent yes (client side)
    rule = next(r for r in RULES if r.id == "ssh-agent-forwarding-client")
    if applies(rule):
        for m in _SSH_AGENT_FWD_FLAG.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )
        for m in _FORWARD_AGENT_YES.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                findings, seen, rule.id, line, col,
                m.group(0).strip(), rule.severity, rule.description,
            )

    # P15 — ssh-keyscan unverified + ProxyCommand from suspicious path
    rule = next(r for r in RULES if r.id == "ssh-keyscan-unverified-or-proxycmd")
    if applies(rule):
        _scan_keyscan_and_proxycommand(text, findings, seen, file_kind)

    # P16 — SSHD_USE_STRONG_RNG / AuthorizedKeysCommand / ListenAddress
    rule = next(r for r in RULES if r.id == "ssh-misc-rng-listen-akcommand")
    if applies(rule):
        _scan_misc(text, findings, seen)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
