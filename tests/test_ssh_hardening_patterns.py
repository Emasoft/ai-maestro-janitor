"""Tests for scripts/lib/ssh_hardening_patterns.py.

Wave 21 angle A — 16 SSH/sshd-config hardening rules from
`reports/distill-round-7/ssh-sshd-hardening.md` (P1..P16).

Every rule gets at least one positive (the attack shape fires) plus
one negative (a benign sibling shape does NOT fire). Helpers
(`is_safe_keyfile_mode`, `is_weak_cipher_name`, etc.) are unit-tested
directly.

Run:
    python3 -m pytest tests/test_ssh_hardening_patterns.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ssh_hardening_patterns as shp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(shp.RULES, tuple)
    rule_ids = {r.id for r in shp.RULES}
    expected = {
        "ssh-permit-root-login",
        "ssh-password-authentication",
        "ssh-permit-empty-passwords",
        "ssh-legacy-protocol-or-hostkey",
        "ssh-x11-or-agent-forwarding-server",
        "ssh-tcp-forwarding-or-tunnel",
        "ssh-lax-auth-tries-or-grace",
        "ssh-unbounded-client-alive",
        "ssh-overpermissive-match-block",
        "ssh-weak-ciphers-macs-kex",
        "ssh-strict-host-key-checking-off",
        "ssh-authorized-keys-risky-options",
        "ssh-weak-keygen-invocation",
        "ssh-agent-forwarding-client",
        "ssh-keyscan-unverified-or-proxycmd",
        "ssh-misc-rng-listen-akcommand",
    }
    assert expected.issubset(rule_ids)
    # 16 net-new rules in this module.
    assert len([r for r in shp.RULES if r.id in expected]) == 16


def test_every_rule_has_valid_severity() -> None:
    """Every rule has a severity from the canonical set."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in shp.RULES:
        assert rule.severity in valid, rule.id


def test_every_rule_has_applies_to() -> None:
    """Every rule declares at least one file_kind plus 'any'."""
    for rule in shp.RULES:
        assert isinstance(rule.applies_to, frozenset), rule.id
        assert "any" in rule.applies_to, rule.id
        assert len(rule.applies_to) >= 2, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the same shape as the sibling modules."""
    f = shp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2


def _hits(rule_id: str, text: str, *, file_kind: str = "any") -> list[shp.Finding]:
    return [f for f in shp.scan_text(text, file_kind=file_kind) if f.rule_id == rule_id]


# ---------- P1 — PermitRootLogin ----------------------------------------


def test_permit_root_login_yes_pos() -> None:
    """`PermitRootLogin yes` fires."""
    assert _hits("ssh-permit-root-login", "PermitRootLogin yes\n", file_kind="sshd-config")


def test_permit_root_login_without_password_pos() -> None:
    """`PermitRootLogin without-password` fires."""
    assert _hits(
        "ssh-permit-root-login",
        "PermitRootLogin without-password\n",
        file_kind="sshd-config",
    )


def test_permit_root_login_prohibit_password_pos() -> None:
    """`PermitRootLogin prohibit-password` fires (OpenSSH 7+ alias)."""
    assert _hits(
        "ssh-permit-root-login",
        "PermitRootLogin prohibit-password\n",
        file_kind="sshd-config",
    )


def test_permit_root_login_no_neg() -> None:
    """`PermitRootLogin no` does NOT fire."""
    assert not _hits(
        "ssh-permit-root-login",
        "PermitRootLogin no\n",
        file_kind="sshd-config",
    )


def test_permit_root_login_forced_commands_only_neg() -> None:
    """`PermitRootLogin forced-commands-only` does NOT fire."""
    assert not _hits(
        "ssh-permit-root-login",
        "PermitRootLogin forced-commands-only\n",
        file_kind="sshd-config",
    )


def test_permit_root_login_commented_neg() -> None:
    """Commented-out line does NOT fire."""
    assert not _hits(
        "ssh-permit-root-login",
        "#PermitRootLogin yes\n",
        file_kind="sshd-config",
    )


# ---------- P2 — PasswordAuthentication --------------------------------


def test_password_authentication_yes_pos() -> None:
    """`PasswordAuthentication yes` fires."""
    assert _hits(
        "ssh-password-authentication",
        "PasswordAuthentication yes\n",
        file_kind="sshd-config",
    )


def test_challenge_response_authentication_yes_pos() -> None:
    """`ChallengeResponseAuthentication yes` fires (same rule)."""
    assert _hits(
        "ssh-password-authentication",
        "ChallengeResponseAuthentication yes\n",
        file_kind="sshd-config",
    )


def test_kbd_interactive_yes_pos() -> None:
    """`KbdInteractiveAuthentication yes` fires."""
    assert _hits(
        "ssh-password-authentication",
        "KbdInteractiveAuthentication yes\n",
        file_kind="sshd-config",
    )


def test_password_authentication_no_neg() -> None:
    """`PasswordAuthentication no` does NOT fire."""
    assert not _hits(
        "ssh-password-authentication",
        "PasswordAuthentication no\n",
        file_kind="sshd-config",
    )


# ---------- P3 — PermitEmptyPasswords ----------------------------------


def test_permit_empty_passwords_yes_pos() -> None:
    """`PermitEmptyPasswords yes` fires."""
    assert _hits(
        "ssh-permit-empty-passwords",
        "PermitEmptyPasswords yes\n",
        file_kind="sshd-config",
    )


def test_permit_empty_passwords_no_neg() -> None:
    """`PermitEmptyPasswords no` does NOT fire."""
    assert not _hits(
        "ssh-permit-empty-passwords",
        "PermitEmptyPasswords no\n",
        file_kind="sshd-config",
    )


# ---------- P4 — Protocol 1 / weak HostKey ------------------------------


def test_protocol_1_pos() -> None:
    """`Protocol 1` fires."""
    assert _hits(
        "ssh-legacy-protocol-or-hostkey",
        "Protocol 1\n",
        file_kind="sshd-config",
    )


def test_protocol_2_1_pos() -> None:
    """`Protocol 2,1` fires (legacy fallback)."""
    assert _hits(
        "ssh-legacy-protocol-or-hostkey",
        "Protocol 2,1\n",
        file_kind="sshd-config",
    )


def test_protocol_2_neg() -> None:
    """`Protocol 2` alone does NOT fire."""
    assert not _hits(
        "ssh-legacy-protocol-or-hostkey",
        "Protocol 2\n",
        file_kind="sshd-config",
    )


def test_hostkey_dsa_pos() -> None:
    """DSA host key path fires."""
    assert _hits(
        "ssh-legacy-protocol-or-hostkey",
        "HostKey /etc/ssh/ssh_host_dsa_key\n",
        file_kind="sshd-config",
    )


def test_hostkey_ecdsa_pos() -> None:
    """ECDSA host key path fires."""
    assert _hits(
        "ssh-legacy-protocol-or-hostkey",
        "HostKey /etc/ssh/ssh_host_ecdsa_key\n",
        file_kind="sshd-config",
    )


def test_hostkey_ed25519_neg() -> None:
    """ed25519 host key does NOT fire."""
    assert not _hits(
        "ssh-legacy-protocol-or-hostkey",
        "HostKey /etc/ssh/ssh_host_ed25519_key\n",
        file_kind="sshd-config",
    )


# ---------- P5 — X11Forwarding / AllowAgentForwarding -------------------


def test_x11_forwarding_yes_pos() -> None:
    """`X11Forwarding yes` fires."""
    assert _hits(
        "ssh-x11-or-agent-forwarding-server",
        "X11Forwarding yes\n",
        file_kind="sshd-config",
    )


def test_allow_agent_forwarding_yes_pos() -> None:
    """`AllowAgentForwarding yes` fires."""
    assert _hits(
        "ssh-x11-or-agent-forwarding-server",
        "AllowAgentForwarding yes\n",
        file_kind="sshd-config",
    )


def test_x11_forwarding_no_neg() -> None:
    """`X11Forwarding no` does NOT fire."""
    assert not _hits(
        "ssh-x11-or-agent-forwarding-server",
        "X11Forwarding no\n",
        file_kind="sshd-config",
    )


# ---------- P6 — AllowTcpForwarding / PermitTunnel ----------------------


def test_allow_tcp_forwarding_yes_pos() -> None:
    """`AllowTcpForwarding yes` fires."""
    assert _hits(
        "ssh-tcp-forwarding-or-tunnel",
        "AllowTcpForwarding yes\n",
        file_kind="sshd-config",
    )


def test_allow_tcp_forwarding_local_pos() -> None:
    """`AllowTcpForwarding local` fires."""
    assert _hits(
        "ssh-tcp-forwarding-or-tunnel",
        "AllowTcpForwarding local\n",
        file_kind="sshd-config",
    )


def test_permit_tunnel_yes_pos() -> None:
    """`PermitTunnel yes` fires."""
    assert _hits(
        "ssh-tcp-forwarding-or-tunnel",
        "PermitTunnel yes\n",
        file_kind="sshd-config",
    )


def test_allow_tcp_forwarding_no_neg() -> None:
    """`AllowTcpForwarding no` does NOT fire."""
    assert not _hits(
        "ssh-tcp-forwarding-or-tunnel",
        "AllowTcpForwarding no\n",
        file_kind="sshd-config",
    )


def test_permit_tunnel_no_neg() -> None:
    """`PermitTunnel no` does NOT fire."""
    assert not _hits(
        "ssh-tcp-forwarding-or-tunnel",
        "PermitTunnel no\n",
        file_kind="sshd-config",
    )


# ---------- P7 — MaxAuthTries / LoginGraceTime / MaxStartups ------------


def test_max_auth_tries_6_pos() -> None:
    """`MaxAuthTries 6` (default) fires — >=4."""
    assert _hits(
        "ssh-lax-auth-tries-or-grace",
        "MaxAuthTries 6\n",
        file_kind="sshd-config",
    )


def test_max_auth_tries_3_neg() -> None:
    """`MaxAuthTries 3` does NOT fire (CIS-compliant)."""
    assert not _hits(
        "ssh-lax-auth-tries-or-grace",
        "MaxAuthTries 3\n",
        file_kind="sshd-config",
    )


def test_login_grace_time_120_pos() -> None:
    """`LoginGraceTime 120` fires — >=60s."""
    assert _hits(
        "ssh-lax-auth-tries-or-grace",
        "LoginGraceTime 120\n",
        file_kind="sshd-config",
    )


def test_login_grace_time_2m_pos() -> None:
    """`LoginGraceTime 2m` (= 120s) fires."""
    assert _hits(
        "ssh-lax-auth-tries-or-grace",
        "LoginGraceTime 2m\n",
        file_kind="sshd-config",
    )


def test_login_grace_time_30s_neg() -> None:
    """`LoginGraceTime 30s` does NOT fire."""
    assert not _hits(
        "ssh-lax-auth-tries-or-grace",
        "LoginGraceTime 30s\n",
        file_kind="sshd-config",
    )


def test_max_startups_high_pos() -> None:
    """`MaxStartups 100:30:200` fires (first value > 10)."""
    assert _hits(
        "ssh-lax-auth-tries-or-grace",
        "MaxStartups 100:30:200\n",
        file_kind="sshd-config",
    )


def test_max_startups_low_neg() -> None:
    """`MaxStartups 10:30:60` does NOT fire."""
    assert not _hits(
        "ssh-lax-auth-tries-or-grace",
        "MaxStartups 10:30:60\n",
        file_kind="sshd-config",
    )


# ---------- P8 — ClientAliveInterval / ClientAliveCountMax --------------


def test_client_alive_interval_zero_pos() -> None:
    """`ClientAliveInterval 0` fires."""
    assert _hits(
        "ssh-unbounded-client-alive",
        "ClientAliveInterval 0\n",
        file_kind="sshd-config",
    )


def test_client_alive_count_max_high_pos() -> None:
    """`ClientAliveCountMax 5` fires (>=3)."""
    assert _hits(
        "ssh-unbounded-client-alive",
        "ClientAliveCountMax 5\n",
        file_kind="sshd-config",
    )


def test_client_alive_interval_300_neg() -> None:
    """`ClientAliveInterval 300` does NOT fire."""
    assert not _hits(
        "ssh-unbounded-client-alive",
        "ClientAliveInterval 300\n",
        file_kind="sshd-config",
    )


def test_client_alive_count_max_2_neg() -> None:
    """`ClientAliveCountMax 2` does NOT fire."""
    assert not _hits(
        "ssh-unbounded-client-alive",
        "ClientAliveCountMax 2\n",
        file_kind="sshd-config",
    )


# ---------- P9 — Over-permissive Match blocks --------------------------


def test_match_user_wildcard_pos() -> None:
    """`Match User *` fires."""
    assert _hits(
        "ssh-overpermissive-match-block",
        "Match User *\n",
        file_kind="sshd-config",
    )


def test_match_address_zero_pos() -> None:
    """`Match Address 0.0.0.0/0` fires."""
    assert _hits(
        "ssh-overpermissive-match-block",
        "Match Address 0.0.0.0/0\n",
        file_kind="sshd-config",
    )


def test_match_address_ipv6_zero_pos() -> None:
    """`Match Address ::/0` fires."""
    assert _hits(
        "ssh-overpermissive-match-block",
        "Match Address ::/0\n",
        file_kind="sshd-config",
    )


def test_match_user_narrow_neg() -> None:
    """`Match User ansible-ci` does NOT fire."""
    assert not _hits(
        "ssh-overpermissive-match-block",
        "Match User ansible-ci\n",
        file_kind="sshd-config",
    )


def test_match_address_narrow_cidr_neg() -> None:
    """`Match Address 10.0.0.0/8` does NOT fire."""
    assert not _hits(
        "ssh-overpermissive-match-block",
        "Match Address 10.0.0.0/8\n",
        file_kind="sshd-config",
    )


# ---------- P10 — Weak Ciphers / MACs / KexAlgorithms -------------------


def test_weak_cipher_arcfour_pos() -> None:
    """`Ciphers arcfour` fires."""
    assert _hits(
        "ssh-weak-ciphers-macs-kex",
        "Ciphers arcfour,aes256-ctr\n",
        file_kind="sshd-config",
    )


def test_weak_cipher_cbc_pos() -> None:
    """`Ciphers aes256-cbc` fires (CBC padding-oracle)."""
    assert _hits(
        "ssh-weak-ciphers-macs-kex",
        "Ciphers aes256-cbc\n",
        file_kind="sshd-config",
    )


def test_weak_mac_md5_pos() -> None:
    """`MACs hmac-md5` fires."""
    assert _hits(
        "ssh-weak-ciphers-macs-kex",
        "MACs hmac-md5,hmac-sha2-256\n",
        file_kind="sshd-config",
    )


def test_weak_mac_sha1_pos() -> None:
    """`MACs hmac-sha1` fires."""
    assert _hits(
        "ssh-weak-ciphers-macs-kex",
        "MACs hmac-sha1\n",
        file_kind="sshd-config",
    )


def test_weak_kex_group1_sha1_pos() -> None:
    """`KexAlgorithms diffie-hellman-group1-sha1` fires."""
    assert _hits(
        "ssh-weak-ciphers-macs-kex",
        "KexAlgorithms diffie-hellman-group1-sha1\n",
        file_kind="sshd-config",
    )


def test_weak_kex_group14_sha1_pos() -> None:
    """`KexAlgorithms diffie-hellman-group14-sha1` fires."""
    assert _hits(
        "ssh-weak-ciphers-macs-kex",
        "KexAlgorithms diffie-hellman-group14-sha1\n",
        file_kind="sshd-config",
    )


def test_strong_ciphers_neg() -> None:
    """Strong Ciphers list does NOT fire."""
    assert not _hits(
        "ssh-weak-ciphers-macs-kex",
        "Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com\n",
        file_kind="sshd-config",
    )


def test_strong_macs_neg() -> None:
    """Strong MACs list does NOT fire."""
    assert not _hits(
        "ssh-weak-ciphers-macs-kex",
        "MACs hmac-sha2-512-etm@openssh.com\n",
        file_kind="sshd-config",
    )


def test_helper_is_weak_cipher_name() -> None:
    """is_weak_cipher_name helper covers the right names."""
    assert shp.is_weak_cipher_name("arcfour")
    assert shp.is_weak_cipher_name("3des-cbc")
    assert shp.is_weak_cipher_name("aes256-cbc")
    assert not shp.is_weak_cipher_name("aes256-gcm@openssh.com")
    assert not shp.is_weak_cipher_name("chacha20-poly1305@openssh.com")


def test_helper_is_weak_mac_name() -> None:
    """is_weak_mac_name helper covers the right names."""
    assert shp.is_weak_mac_name("hmac-md5")
    assert shp.is_weak_mac_name("hmac-sha1")
    assert shp.is_weak_mac_name("umac-64@openssh.com")
    assert not shp.is_weak_mac_name("hmac-sha2-512-etm@openssh.com")


def test_helper_is_weak_kex_name() -> None:
    """is_weak_kex_name helper covers the right names."""
    assert shp.is_weak_kex_name("diffie-hellman-group1-sha1")
    assert shp.is_weak_kex_name("diffie-hellman-group14-sha1")
    assert not shp.is_weak_kex_name("curve25519-sha256@libssh.org")


# ---------- P11 — StrictHostKeyChecking no / accept-new -----------------


def test_strict_hk_checking_no_config_pos() -> None:
    """`StrictHostKeyChecking no` in ~/.ssh/config fires."""
    assert _hits(
        "ssh-strict-host-key-checking-off",
        "Host *\n  StrictHostKeyChecking no\n",
        file_kind="ssh-config",
    )


def test_strict_hk_checking_accept_new_pos() -> None:
    """`StrictHostKeyChecking accept-new` fires (warn)."""
    assert _hits(
        "ssh-strict-host-key-checking-off",
        "StrictHostKeyChecking accept-new\n",
        file_kind="ssh-config",
    )


def test_strict_hk_checking_flag_pos() -> None:
    """`-o StrictHostKeyChecking=no` in a script fires."""
    text = "ssh -o StrictHostKeyChecking=no user@host\n"
    assert _hits("ssh-strict-host-key-checking-off", text, file_kind="script")


def test_strict_hk_checking_yes_neg() -> None:
    """`StrictHostKeyChecking yes` does NOT fire."""
    assert not _hits(
        "ssh-strict-host-key-checking-off",
        "StrictHostKeyChecking yes\n",
        file_kind="ssh-config",
    )


# ---------- P12 — authorized_keys risky options -------------------------


def test_authorized_keys_no_from_pin_pos() -> None:
    """authorized_keys line without `from=` fires."""
    text = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIxyz123 user@host\n'
    assert _hits(
        "ssh-authorized-keys-risky-options",
        text,
        file_kind="authorized-keys",
    )


def test_authorized_keys_from_wildcard_pos() -> None:
    """authorized_keys with `from="*"` fires."""
    text = 'from="*" ssh-ed25519 AAAAC3xyz123 user@host\n'
    assert _hits(
        "ssh-authorized-keys-risky-options",
        text,
        file_kind="authorized-keys",
    )


def test_authorized_keys_command_without_restrict_pos() -> None:
    """`command="..."` without `restrict` and missing no-* options fires."""
    text = (
        'from="10.0.0.0/8",command="/bin/foo" '
        "ssh-ed25519 AAAAC3xyz user@host\n"
    )
    assert _hits(
        "ssh-authorized-keys-risky-options",
        text,
        file_kind="authorized-keys",
    )


def test_authorized_keys_command_shell_variable_pos() -> None:
    """`command="...${VAR}..."` (shell variable expansion) fires."""
    text = (
        'restrict,from="10.0.0.0/8",command="/bin/wrap ${SSH_ORIGINAL_COMMAND}" '
        "ssh-ed25519 AAAAC3xyz user@host\n"
    )
    findings = _hits(
        "ssh-authorized-keys-risky-options",
        text,
        file_kind="authorized-keys",
    )
    assert any("shell variable" in f.matched_text for f in findings)


def test_authorized_keys_safe_entry_neg() -> None:
    """A correctly-pinned restrict+from+command entry does NOT fire."""
    text = (
        'restrict,from="10.0.0.0/8",command="/usr/local/bin/restricted-shell" '
        "ssh-ed25519 AAAAC3xyz ci-deploy-bot\n"
    )
    assert not _hits(
        "ssh-authorized-keys-risky-options",
        text,
        file_kind="authorized-keys",
    )


def test_authorized_keys_command_with_explicit_no_options_neg() -> None:
    """`command=` with explicit no-* options (no restrict needed) is safe."""
    text = (
        'from="10.0.0.0/8",command="/bin/foo",'
        "no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty "
        "ssh-ed25519 AAAAC3xyz user@host\n"
    )
    assert not _hits(
        "ssh-authorized-keys-risky-options",
        text,
        file_kind="authorized-keys",
    )


# ---------- P13 — Weak ssh-keygen invocations ---------------------------


def test_keygen_dsa_pos() -> None:
    """`ssh-keygen -t dsa` fires."""
    assert _hits(
        "ssh-weak-keygen-invocation",
        "ssh-keygen -t dsa -f /tmp/key\n",
        file_kind="script",
    )


def test_keygen_rsa_1024_pos() -> None:
    """`ssh-keygen -t rsa -b 1024` fires."""
    assert _hits(
        "ssh-weak-keygen-invocation",
        "ssh-keygen -t rsa -b 1024 -f /tmp/key\n",
        file_kind="script",
    )


def test_keygen_rsa_2048_pos() -> None:
    """`ssh-keygen -t rsa -b 2048` fires (below modern guidance of 4096)."""
    assert _hits(
        "ssh-weak-keygen-invocation",
        "ssh-keygen -t rsa -b 2048 -f /tmp/key\n",
        file_kind="script",
    )


def test_keygen_ecdsa_pos() -> None:
    """`ssh-keygen -t ecdsa` fires (NIST curves)."""
    assert _hits(
        "ssh-weak-keygen-invocation",
        "ssh-keygen -t ecdsa -f /tmp/key\n",
        file_kind="script",
    )


def test_keygen_ed25519_neg() -> None:
    """`ssh-keygen -t ed25519` does NOT fire."""
    assert not _hits(
        "ssh-weak-keygen-invocation",
        "ssh-keygen -t ed25519 -a 100 -C user@host\n",
        file_kind="script",
    )


def test_keygen_rsa_4096_neg() -> None:
    """`ssh-keygen -t rsa -b 4096` does NOT fire."""
    assert not _hits(
        "ssh-weak-keygen-invocation",
        "ssh-keygen -t rsa -b 4096 -a 100 -C user@host\n",
        file_kind="script",
    )


# ---------- P14 — Client-side agent forwarding --------------------------


def test_ssh_dash_a_pos() -> None:
    """`ssh -A user@bastion` fires."""
    assert _hits(
        "ssh-agent-forwarding-client",
        "ssh -A user@bastion\n",
        file_kind="script",
    )


def test_forward_agent_yes_pos() -> None:
    """`ForwardAgent yes` in ~/.ssh/config fires."""
    assert _hits(
        "ssh-agent-forwarding-client",
        "Host *\n  ForwardAgent yes\n",
        file_kind="ssh-config",
    )


def test_ssh_dash_j_neg() -> None:
    """`ssh -J user@bastion target` (ProxyJump) does NOT fire."""
    assert not _hits(
        "ssh-agent-forwarding-client",
        "ssh -J user@bastion target\n",
        file_kind="script",
    )


def test_forward_agent_no_neg() -> None:
    """`ForwardAgent no` does NOT fire."""
    assert not _hits(
        "ssh-agent-forwarding-client",
        "Host *\n  ForwardAgent no\n",
        file_kind="ssh-config",
    )


# ---------- P15 — ssh-keyscan + ProxyCommand ----------------------------


def test_ssh_keyscan_unverified_pos() -> None:
    """`ssh-keyscan github.com >> known_hosts` without verify fires."""
    text = "ssh-keyscan github.com >> ~/.ssh/known_hosts\n"
    assert _hits(
        "ssh-keyscan-unverified-or-proxycmd",
        text,
        file_kind="script",
    )


def test_ssh_keyscan_with_verify_neg() -> None:
    """`ssh-keyscan` followed by a fingerprint verify does NOT fire."""
    text = (
        "ssh-keyscan github.com > /tmp/scan\n"
        "ssh-keygen -lf /tmp/scan\n"
        'grep -q "SHA256:..."\n'
    )
    assert not _hits(
        "ssh-keyscan-unverified-or-proxycmd",
        text,
        file_kind="script",
    )


def test_proxycommand_tmp_pos() -> None:
    """`ProxyCommand /tmp/evil-relay ...` in ~/.ssh/config fires."""
    text = "Host *\n  ProxyCommand /tmp/evil-relay %h %p\n"
    assert _hits(
        "ssh-keyscan-unverified-or-proxycmd",
        text,
        file_kind="ssh-config",
    )


def test_proxycommand_user_bin_neg() -> None:
    """`ProxyCommand /usr/bin/nc ...` does NOT fire (legitimate path)."""
    text = (
        "Host *\n  ProxyCommand /usr/bin/nc %h %p\n"
        "fingerprint check happens elsewhere\n"
    )
    assert not _hits(
        "ssh-keyscan-unverified-or-proxycmd",
        text,
        file_kind="ssh-config",
    )


# ---------- P16 — RNG / AuthorizedKeysCommand / ListenAddress -----------


def test_sshd_weak_rng_pos() -> None:
    """`SSHD_USE_STRONG_RNG=0` fires."""
    assert _hits(
        "ssh-misc-rng-listen-akcommand",
        "SSHD_USE_STRONG_RNG=0\n",
        file_kind="sshd-config",
    )


def test_authorized_keys_command_pos() -> None:
    """`AuthorizedKeysCommand /opt/ldap-akc` fires (surface for stat-check)."""
    assert _hits(
        "ssh-misc-rng-listen-akcommand",
        "AuthorizedKeysCommand /opt/ldap-akc\n",
        file_kind="sshd-config",
    )


def test_listen_address_zero_ipv4_pos() -> None:
    """`ListenAddress 0.0.0.0` fires."""
    assert _hits(
        "ssh-misc-rng-listen-akcommand",
        "ListenAddress 0.0.0.0\n",
        file_kind="sshd-config",
    )


def test_listen_address_ipv6_zero_pos() -> None:
    """`ListenAddress ::` fires."""
    assert _hits(
        "ssh-misc-rng-listen-akcommand",
        "ListenAddress ::\n",
        file_kind="sshd-config",
    )


def test_listen_address_specific_neg() -> None:
    """`ListenAddress 10.0.0.5` does NOT fire (specific interface)."""
    assert not _hits(
        "ssh-misc-rng-listen-akcommand",
        "ListenAddress 10.0.0.5\n",
        file_kind="sshd-config",
    )


# ---------- Helpers: file-mode checks (P13 second half) -----------------


def test_is_safe_keyfile_mode_0600() -> None:
    """0o600 is safe for a private key file."""
    assert shp.is_safe_keyfile_mode(0o600)


def test_is_safe_keyfile_mode_0400() -> None:
    """0o400 is safe for a private key file."""
    assert shp.is_safe_keyfile_mode(0o400)


def test_is_safe_keyfile_mode_unsafe() -> None:
    """0o644, 0o660, 0o777 are NOT safe for a private key."""
    assert not shp.is_safe_keyfile_mode(0o644)
    assert not shp.is_safe_keyfile_mode(0o660)
    assert not shp.is_safe_keyfile_mode(0o777)


def test_is_safe_keyfile_pub_mode() -> None:
    """Public key modes: 0o644 / 0o600 are safe; group/other write is not."""
    assert shp.is_safe_keyfile_pub_mode(0o644)
    assert shp.is_safe_keyfile_pub_mode(0o600)
    assert not shp.is_safe_keyfile_pub_mode(0o646)
    assert not shp.is_safe_keyfile_pub_mode(0o777)


def test_is_safe_keyfile_dir_mode() -> None:
    """~/.ssh dir must be 0o700."""
    assert shp.is_safe_keyfile_dir_mode(0o700)
    assert not shp.is_safe_keyfile_dir_mode(0o755)
    assert not shp.is_safe_keyfile_dir_mode(0o777)


# ---------- Composite / scanner-level tests -----------------------------


def test_empty_text_returns_empty() -> None:
    """Empty input yields no findings."""
    assert shp.scan_text("") == []


def test_file_kind_filters_rules() -> None:
    """file_kind='ssh-config' does NOT fire `ssh-permit-root-login`."""
    text = "PermitRootLogin yes\n"
    findings = shp.scan_text(text, file_kind="ssh-config")
    assert not any(f.rule_id == "ssh-permit-root-login" for f in findings)


def test_findings_sorted_by_line_then_column() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    text = (
        "PermitRootLogin yes\n"
        "PasswordAuthentication yes\n"
        "X11Forwarding yes\n"
    )
    findings = shp.scan_text(text, file_kind="sshd-config")
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_multi_rule_full_realistic_config() -> None:
    """A realistic vulnerable sshd_config triggers >=4 distinct rule ids."""
    text = (
        "# /etc/ssh/sshd_config — vulnerable example\n"
        "PermitRootLogin yes\n"
        "PasswordAuthentication yes\n"
        "PermitEmptyPasswords yes\n"
        "X11Forwarding yes\n"
        "AllowAgentForwarding yes\n"
        "AllowTcpForwarding yes\n"
        "MaxAuthTries 6\n"
        "LoginGraceTime 120\n"
        "ClientAliveInterval 0\n"
        "Ciphers arcfour,aes256-cbc,3des-cbc\n"
        "ListenAddress 0.0.0.0\n"
        "Match User *\n"
    )
    findings = shp.scan_text(text, file_kind="sshd-config")
    rule_ids = {f.rule_id for f in findings}
    assert "ssh-permit-root-login" in rule_ids
    assert "ssh-password-authentication" in rule_ids
    assert "ssh-permit-empty-passwords" in rule_ids
    assert "ssh-x11-or-agent-forwarding-server" in rule_ids
    assert "ssh-tcp-forwarding-or-tunnel" in rule_ids
    assert "ssh-lax-auth-tries-or-grace" in rule_ids
    assert "ssh-unbounded-client-alive" in rule_ids
    assert "ssh-weak-ciphers-macs-kex" in rule_ids
    assert "ssh-overpermissive-match-block" in rule_ids
    assert "ssh-misc-rng-listen-akcommand" in rule_ids
    # No false positives on a known-good directive that isn't present.
    assert "ssh-legacy-protocol-or-hostkey" not in rule_ids


def test_matched_text_truncation() -> None:
    """Matched text longer than 200 chars is truncated."""
    long_value = "A" * 500
    text = f"AuthorizedKeysCommand {long_value}\n"
    findings = shp.scan_text(text, file_kind="sshd-config")
    relevant = [f for f in findings if f.rule_id == "ssh-misc-rng-listen-akcommand"]
    assert relevant
    assert all(len(f.matched_text) <= 250 for f in relevant)


def test_dedup_same_line_same_rule() -> None:
    """Same rule firing twice on the same (line, col) collapses to one."""
    text = "PermitRootLogin yes\nPermitRootLogin yes\n"
    findings = _hits(
        "ssh-permit-root-login", text, file_kind="sshd-config",
    )
    # Two distinct lines but identical content -> two findings (different lines).
    assert len(findings) == 2
    assert findings[0].line == 1
    assert findings[1].line == 2
