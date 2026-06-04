"""Tests for scripts/lib/linux_kernel_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 Linux
kernel-modules / kernel-config / capability-surface catalogue
(7 rules covering debugfs world-writable, insmod/modprobe
``--force``, MODULE_SIG disabled at build, ``CAP_SYS_ADMIN``
retention, KSPP hardening sysctl regression, ``setcap`` on fs
binaries, ``PR_SET_DUMPABLE`` / ``PR_SET_NO_NEW_PRIVS`` reset).

Each rule has exactly 2 tests (one positive, one negative/carve-out)
plus a small block of data-model sanity tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import linux_kernel_patterns as lkp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(lkp.RULES, tuple)
    rule_ids = {r.id for r in lkp.RULES}
    expected = {
        "kernel-debugfs-world-writable",
        "kmod-force-unsigned-flag",
        "kmod-sig-force-disabled-buildflag",
        "cap-sys-admin-retained-post-init",
        "kernel-hardening-sysctl-disabled",
        "binary-setcap-sys-admin-on-fs",
        "prctl-dumpable-or-noprivs-regression",
    }
    assert expected == rule_ids
    assert len(lkp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in lkp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = lkp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-07",
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
    assert lkp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[lkp.Finding]:
    return [f for f in lkp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : kernel-debugfs-world-writable ---------------------------


def test_p1_chmod_debugfs_world_writable_flags() -> None:
    """``chmod -R 0666 /sys/kernel/debug`` → CRITICAL hit."""
    src = (
        "RUN mount -t debugfs none /sys/kernel/debug \\\n"
        " && chmod -R 0666 /sys/kernel/debug\n"
    )
    hits = _hits("kernel-debugfs-world-writable", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p1_chmod_with_exempt_marker_suppressed() -> None:
    """Same chmod with ``# kspp-exempt`` opt-out → no hit."""
    src = (
        "chmod 0666 /sys/kernel/debug  # kspp-exempt — CI sandbox\n"
    )
    assert not _hits("kernel-debugfs-world-writable", src)


# ---------- P2 : kmod-force-unsigned-flag --------------------------------


def test_p2_modprobe_allow_unsigned_flags() -> None:
    """``modprobe --allow-unsigned evil.ko`` → CRITICAL hit."""
    src = (
        "modprobe --allow-unsigned --force-vermagic ./evil-rootkit.ko\n"
    )
    hits = _hits("kmod-force-unsigned-flag", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p2_plain_modprobe_not_flagged() -> None:
    """Plain ``modprobe foo`` without the dangerous flags → no hit."""
    src = "modprobe nf_conntrack\ninsmod /lib/modules/$(uname -r)/extra/foo.ko\n"
    assert not _hits("kmod-force-unsigned-flag", src)


# ---------- P3 : kmod-sig-force-disabled-buildflag -----------------------


def test_p3_config_module_sig_force_n_flags() -> None:
    """``CONFIG_MODULE_SIG_FORCE=n`` in a defconfig fragment → HIGH hit."""
    src = (
        "CONFIG_MODULE_SIG=n\n"
        "CONFIG_MODULE_SIG_FORCE=n\n"
    )
    hits = _hits("kmod-sig-force-disabled-buildflag", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p3_config_module_sig_force_y_not_flagged() -> None:
    """``CONFIG_MODULE_SIG_FORCE=y`` (the safe value) → no hit."""
    src = "CONFIG_MODULE_SIG=y\nCONFIG_MODULE_SIG_FORCE=y\n"
    assert not _hits("kmod-sig-force-disabled-buildflag", src)


# ---------- P4 : cap-sys-admin-retained-post-init ------------------------


def test_p4_cap_set_proc_without_drop_flags() -> None:
    """``cap_set_proc(cap)`` with NO paired drop → CRITICAL hit."""
    src = (
        "void daemon_init(void) {\n"
        "    cap_t cap = cap_get_proc();\n"
        "    cap_value_t needed[] = { CAP_SYS_ADMIN };\n"
        "    cap_set_flag(cap, CAP_EFFECTIVE, 1, needed, CAP_SET);\n"
        "    cap_set_proc(cap);\n"
        "    mount_helper_fs();\n"
        "    enter_request_loop();\n"
        "}\n"
    )
    hits = _hits("cap-sys-admin-retained-post-init", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p4_cap_set_proc_with_drop_pair_suppressed() -> None:
    """Same code with ``cap_clear`` follow-up → no hit."""
    src = (
        "void daemon_init(void) {\n"
        "    cap_t cap = cap_get_proc();\n"
        "    cap_value_t needed[] = { CAP_SYS_ADMIN };\n"
        "    cap_set_flag(cap, CAP_EFFECTIVE, 1, needed, CAP_SET);\n"
        "    cap_set_proc(cap);\n"
        "    mount_helper_fs();\n"
        "    cap_clear(cap);\n"
        "    cap_set_proc(cap);\n"
        "    enter_request_loop();\n"
        "}\n"
    )
    assert not _hits("cap-sys-admin-retained-post-init", src)


# ---------- P5 : kernel-hardening-sysctl-disabled ------------------------


def test_p5_dmesg_restrict_zero_flags() -> None:
    """``kernel.dmesg_restrict = 0`` in sysctl.d → HIGH hit."""
    src = (
        "# /etc/sysctl.d/99-perf-tweaks.conf\n"
        "kernel.dmesg_restrict        = 0\n"
        "kernel.randomize_va_space    = 0\n"
        "kernel.yama.ptrace_scope     = 0\n"
        "fs.protected_hardlinks       = 0\n"
        "fs.protected_symlinks        = 0\n"
        "fs.suid_dumpable             = 2\n"
        "kernel.sysrq                 = 1\n"
    )
    hits = _hits("kernel-hardening-sysctl-disabled", src)
    # Every one of those lines is a hit; verify we got at least the six
    # documented ones (multiple regexes, deduped per-line).
    assert len(hits) >= 6
    assert all(h.severity == "HIGH" for h in hits)


def test_p5_hardening_sysctl_at_safe_values_not_flagged() -> None:
    """Same knobs at safe values (=1 / =2 / =176) → no hits."""
    src = (
        "kernel.dmesg_restrict        = 1\n"
        "kernel.randomize_va_space    = 2\n"
        "kernel.yama.ptrace_scope     = 1\n"
        "fs.protected_hardlinks       = 1\n"
        "fs.protected_symlinks        = 1\n"
        "fs.suid_dumpable             = 0\n"
        "kernel.sysrq                 = 176\n"
    )
    assert not _hits("kernel-hardening-sysctl-disabled", src)


# ---------- P6 : binary-setcap-sys-admin-on-fs ---------------------------


def test_p6_setcap_sys_admin_on_binary_flags() -> None:
    """``setcap cap_sys_admin+ep /usr/local/bin/agent`` → CRITICAL hit."""
    src = (
        "RUN setcap cap_sys_admin+ep /usr/local/bin/agent-helper\n"
        'RUN setcap "cap_sys_module,cap_net_admin+ep" /usr/local/bin/probe-loader\n'
    )
    hits = _hits("binary-setcap-sys-admin-on-fs", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p6_setcap_net_bind_service_not_flagged() -> None:
    """``setcap cap_net_bind_service+ep`` (textbook correct use) → no hit."""
    src = "RUN setcap cap_net_bind_service+ep /usr/bin/python3\n"
    assert not _hits("binary-setcap-sys-admin-on-fs", src)


# ---------- P7 : prctl-dumpable-or-noprivs-regression --------------------


def test_p7_prctl_set_dumpable_one_flags() -> None:
    """``prctl(PR_SET_DUMPABLE, 1)`` → HIGH hit."""
    src = (
        "void enable_corefiles(void) {\n"
        "    prctl(PR_SET_DUMPABLE, 1);\n"
        "}\n"
    )
    hits = _hits("prctl-dumpable-or-noprivs-regression", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p7_prctl_set_dumpable_zero_not_flagged() -> None:
    """``prctl(PR_SET_DUMPABLE, 0)`` (the SAFE direction) → no hit."""
    src = "prctl(PR_SET_DUMPABLE, 0);\n"
    assert not _hits("prctl-dumpable-or-noprivs-regression", src)
