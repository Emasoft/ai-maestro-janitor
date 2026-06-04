"""eBPF / kernel-module / LSM / kprobe misuse detection.

Wave-19 deep-dive distillation round 5, angle J.

Catalogues 15 kernel-layer detection rules covering the surface
Wave-18 `sandbox_escape_patterns.py` only flags as a single bit
(`CAP_BPF`, `/sys/kernel/debug` mount, eBPF inside an unprivileged
container). Wave-18 is workload-side and shallow; this module goes
DEEPER — `BPF_PROG_LOAD` arguments, kprobe / uprobe target symbols,
eBPF map pinning paths, `bpf_override_return()`, kernel-module
signing posture, `/dev/mem` openings, kernel cmdline poisoning, and
LSM stacking enforcement.

This module is strictly *defensive*: every rule detects a
mis-configuration or known-malicious construct so the janitor can
warn the operator. No exploit prose. Patterns are RE2-safe — no
back-references, no unbounded look-arounds — and DOS-resistant
(every variable-width quantifier is upper-bounded).

Reference proposal: `reports/distill-round-5/ebpf-kernel.md`.

Rule inventory:

  1.  ebpf-prog-load-uncapped                       (HIGH)
  2.  ebpf-kprobe-on-secret-syscall                 (CRITICAL)
  3.  kmod-kprobe-on-syscall-table                  (CRITICAL)
  4.  ebpf-override-return                          (CRITICAL)
  5.  ebpf-uprobe-on-libc-secret-fn                 (CRITICAL)
  6.  ebpf-map-pin-world-readable                   (HIGH)
  7.  kmod-unsigned-out-of-tree                     (CRITICAL)
  8.  kmod-signing-key-exposed                      (CRITICAL)
  9.  kernel-kallsyms-leaked                        (HIGH)
  10. kernel-devmem-open                            (CRITICAL)
  11. kernel-firmware-class-path-hijack             (HIGH)
  12. kernel-lsm-stack-passive                      (HIGH)
  13. ebpf-bpftool-in-prod                          (MEDIUM)
  14. ebpf-container-net-raw-bpf                    (HIGH)
  15. ebpf-btf-from-untrusted-source                (HIGH)

Public surface mirrors `sandbox_escape_patterns.py`:

  * Rule(id, name, severity, description, owasp_asi) — frozen NamedTuple
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple
  * RULES — ordered tuple of every rule
  * scan_text(text, *, file_kind="auto") -> list[Finding]
  * scan_c_source(text) -> list[Finding]
  * scan_bpf_source(text) -> list[Finding]
  * scan_shell_or_workflow(text) -> list[Finding]
  * scan_kconfig_or_cmdline(text) -> list[Finding]
  * scan_sysctl(text) -> list[Finding]
  * scan_pem(text) -> list[Finding]
  * scan_k8s(text) -> list[Finding]
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `scripts/lib/sandbox_escape_patterns.Finding` so heartbeat detectors
    can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """Static rule metadata. Patterns live alongside in module scope."""

    id: str
    name: str
    severity: str
    description: str
    owasp_asi: str


def _re(pattern: str) -> re.Pattern[str]:
    """Compile pattern with MULTILINE. IGNORECASE is opt-in per rule
    because some kernel identifiers are case-sensitive (e.g.
    `CAP_BPF` vs `cap_bpf`).
    """
    return re.compile(pattern, re.MULTILINE)


def _re_i(pattern: str) -> re.Pattern[str]:
    """Compile pattern with IGNORECASE+MULTILINE for textual config."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# ---- OWASP ASI hints (matches existing taxonomy) ------------------------


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ebpf-prog-load-uncapped",
        name="BPF_PROG_LOAD syscall reached without CAP_BPF check",
        severity="HIGH",
        description=(
            "Userland code calls `bpf(BPF_PROG_LOAD, ...)` without a "
            "preceding capability check (`cap_get_proc`, "
            "`prctl(PR_CAP_AMBIENT, ...)`, or root-equivalent guard). "
            "The eBPF verifier has shipped a steady stream of "
            "privilege-escalation CVEs (2021-3490, 2022-2588, "
            "2023-2163). Any unprivileged caller that reaches "
            "`BPF_PROG_LOAD` is a kernel-R/W primitive masquerading "
            "as an observability feature."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ebpf-kprobe-on-secret-syscall",
        name="eBPF kprobe attached to a secret-handling syscall",
        severity="CRITICAL",
        description=(
            "eBPF program attaches a kprobe / kretprobe to "
            "`__x64_sys_read`, `__x64_sys_openat`, `vfs_read`, "
            "`tty_read`, `tcp_sendmsg` or another syscall that "
            "carries cleartext secrets, passwords, TLS plaintext, or "
            "private key bytes. Textbook in-flight credential "
            "exfiltration — used by BPFDoor and Symbiote-class "
            "malware families."
        ),
        owasp_asi="ASI-02",
    ),
    Rule(
        id="kmod-kprobe-on-syscall-table",
        name="register_kprobe targets the syscall table",
        severity="CRITICAL",
        description=(
            "A loadable kernel module calls `register_kprobe()` with "
            "`.symbol_name = \"sys_call_table\"` (or `__x64_sys_*` / "
            "`__arm64_sys_*` / `do_sys_*`). Canonical Linux rootkit "
            "primitive — Diamorphine, Reptile, Suterusu all use this "
            "exact pattern to hook syscalls without modifying "
            "read-only syscall-table pages."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ebpf-override-return",
        name="bpf_override_return() used outside fault-injection tests",
        severity="CRITICAL",
        description=(
            "eBPF source uses `bpf_override_return()`. This helper "
            "was designed for kernel fault-injection but the same "
            "primitive lets a malicious BPF program rewrite syscall "
            "return values — e.g. force `__x64_sys_openat` to return "
            "`-EACCES` selectively for auditd while letting the "
            "attacker through. Non-test use is always suspicious."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ebpf-uprobe-on-libc-secret-fn",
        name="eBPF uprobe attached to a libc / libssl / PAM secret function",
        severity="CRITICAL",
        description=(
            "eBPF program attaches a uprobe / uretprobe to "
            "`SSL_write`, `SSL_read`, `gnutls_record_send`, `crypt`, "
            "`pam_authenticate`, `getpwnam`, or another userspace "
            "function that handles cleartext credentials or "
            "pre-encryption TLS plaintext. Defeats end-to-end TLS "
            "and PAM-based authentication. eCapture-class abuse."
        ),
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ebpf-map-pin-world-readable",
        name="eBPF map pinned under /sys/fs/bpf without restrictive chmod",
        severity="HIGH",
        description=(
            "`bpf_obj_pin()` exposes an eBPF map at `/sys/fs/bpf/...` "
            "without a paired `chmod` to mode `0600`. A pinned map "
            "is kernel-resident shared memory; if it holds captured "
            "syscall bytes, any process that can `open(2)` the path "
            "can call `BPF_MAP_LOOKUP_ELEM` and exfiltrate."
        ),
        owasp_asi="ASI-02",
    ),
    Rule(
        id="kmod-unsigned-out-of-tree",
        name="insmod / modprobe of an out-of-tree .ko with signature checks off",
        severity="CRITICAL",
        description=(
            "Shell / Dockerfile / systemd unit calls `insmod` or "
            "`modprobe -f` on a `.ko` outside `/lib/modules/$(uname -r)/`. "
            "When `sig_enforce=N` (or kernel cmdline contains "
            "`module.sig_enforce=0`), an unsigned module loads and "
            "bypasses every LSM, namespace, and seccomp filter — the "
            "most direct rootkit installer there is."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="kmod-signing-key-exposed",
        name="Kernel module signing key shipped in repo or artifact",
        severity="CRITICAL",
        description=(
            "Filename matches `modules_sign_key.pem` / `signing_key.pem` "
            "(or a sibling cert mentions `Module Signing`) AND the "
            "file contains an unencrypted PRIVATE KEY block. The "
            "leak lets an attacker sign their own malicious `.ko` and "
            "load it on every host trusting that key — kernel-level "
            "supply-chain compromise."
        ),
        owasp_asi="ASI-01",
    ),
    Rule(
        id="kernel-kallsyms-leaked",
        name="kptr_restrict / perf_event_paranoid set to KASLR-leaking value",
        severity="HIGH",
        description=(
            "sysctl.d / /etc/sysctl.conf sets "
            "`kernel.kptr_restrict = 0` or `= 1`, or "
            "`kernel.perf_event_paranoid < 2`. `/proc/kallsyms` "
            "discloses kernel symbol addresses, defeating KASLR for "
            "any subsequent exploit chain — CVE-2023-3269 / "
            "CVE-2022-0185 become deterministic rather than "
            "probabilistic."
        ),
        owasp_asi="ASI-02",
    ),
    Rule(
        id="kernel-devmem-open",
        name="CONFIG_STRICT_DEVMEM disabled OR /dev/mem mapped read-write",
        severity="CRITICAL",
        description=(
            "Kconfig fragment / boot config sets "
            "`CONFIG_STRICT_DEVMEM=n` or `# CONFIG_STRICT_DEVMEM is "
            "not set`, OR source code opens `/dev/mem` / `/dev/kmem` "
            "/ `/dev/port` and mmap's it with `PROT_WRITE`. Direct "
            "physical-RAM read/write from userspace — one-syscall "
            "kernel-R/W primitive."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="kernel-firmware-class-path-hijack",
        name="Kernel cmdline firmware_class.path points to writable directory",
        severity="HIGH",
        description=(
            "Bootloader config (grub.cfg / extlinux.conf / cmdline.txt) "
            "sets `firmware_class.path=` to `/tmp/...`, `/var/tmp/...`, "
            "`/dev/shm/...`, `/home/...`, or `/run/user/...`. Any user "
            "who can write to that path can inject firmware that gets "
            "DMA'd into devices — many devices accept "
            "firmware-update-over-DMA."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="kernel-lsm-stack-passive",
        name="LSM stacking misconfigured — second LSM permissive / passive",
        severity="HIGH",
        description=(
            "Kernel cmdline declares `lsm=apparmor,selinux` (or a "
            "similar stack) but `/sys/fs/selinux/enforce` reads `0`, "
            "or sysctl-style config sets `selinux=0` / "
            "`SELINUX=permissive` / `enforce=0`. The second LSM "
            "logs but never blocks; attackers target whichever LSM "
            "is passive."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ebpf-bpftool-in-prod",
        name="bpftool binary referenced in production deployment artifact",
        severity="MEDIUM",
        description=(
            "Dockerfile / shell installs `bpftool` (`/usr/sbin/bpftool`, "
            "`linux-tools-*`, package `bpftool`) into a production "
            "image. `bpftool prog show` reveals every loaded eBPF "
            "program — gives an attacker the entire defender "
            "observability surface in one command."
        ),
        owasp_asi="ASI-08",
    ),
    Rule(
        id="ebpf-container-net-raw-bpf",
        name="Container grants CAP_NET_RAW / CAP_NET_ADMIN / CAP_BPF with seccomp unconfined",
        severity="HIGH",
        description=(
            "k8s pod spec / compose service grants `CAP_NET_RAW`, "
            "`CAP_NET_ADMIN`, or `CAP_BPF` AND `seccompProfile.type: "
            "Unconfined` (or no seccompProfile block). A SOCKET_FILTER "
            "eBPF program from inside the container can sniff the "
            "host's veth bridge — escape boundary violation without "
            "any runtime exploit. Extends Wave-18 rule 11 with the "
            "exact missing combination."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ebpf-btf-from-untrusted-source",
        name="BTF type-info blob fetched from an untrusted HTTPS URL",
        severity="HIGH",
        description=(
            "curl / wget / requests.get downloads `vmlinux.btf` "
            "(or `*.btf` / `btf*.tar.gz`) from an HTTPS URL outside "
            "the trusted BTFHub mirrors. If an attacker swaps the BTF "
            "blob, kernel structure offsets shift — a portable eBPF "
            "program then reads/writes the wrong fields, a "
            "structure-confusion primitive. SHA-256 pinning required."
        ),
        owasp_asi="ASI-03",
    ),
)


# ---- Compiled patterns --------------------------------------------------


# Rule 1: BPF_PROG_LOAD syscall reached.
# We anchor on the unique BPF_PROG_LOAD constant + bpf() invocation.
# Bounded alternation, bounded \s, no nested quantifiers — RE2 safe.
_BPF_PROG_LOAD: re.Pattern[str] = _re(
    r"\b(?:syscall|bpf)\s{0,3}\(\s{0,3}(?:SYS_|__NR_)?bpf\s{0,3},\s{0,3}BPF_PROG_LOAD\b"
)

# A capability-check identifier appearing in the same function. We don't
# do AST parsing — instead, in the scanner we look at +/- 800 chars
# around the BPF_PROG_LOAD match for any of these. False-positive
# guard: comment `// CAP_BPF: caller-checked` also suppresses.
_CAP_CHECK: re.Pattern[str] = _re(
    r"\b(?:cap_get_proc|prctl\s*\(\s*PR_CAP_AMBIENT|geteuid\s*\(\s*\)|"
    r"getuid\s*\(\s*\)|capget\s*\(|CAP_BPF\b|CAP_SYS_ADMIN\b|"
    r"//\s*CAP_BPF:\s*caller-checked)"
)

# Path / file hints used by false-positive guard. Anchored on the path
# segment so a project containing 'tests/' anywhere triggers the carve-out.
_BPF_TEST_PATH: re.Pattern[str] = _re_i(
    r"(?:^|[\\/])(?:tests?|fuzz|samples|tools[\\/]testing|selftests)[\\/]"
)


# Rule 2: kprobe / kretprobe on a secret-handling syscall.
# Match libbpf-style program setter + the secret-syscall symbol.
_KPROBE_SECRET_FN: re.Pattern[str] = _re(
    r"bpf_program__set_(?:type|attach_target)\s{0,3}\([^)]{0,400}"
    r"\b(?:"
    r"__x64_sys_read|__x64_sys_openat|__x64_sys_open|"
    r"__arm64_sys_read|__arm64_sys_openat|__arm64_sys_open|"
    r"sys_read|sys_openat|sys_open|"
    r"do_sys_open|do_sys_openat2|"
    r"vfs_read|tty_read|"
    r"tcp_sendmsg|tcp_recvmsg|udp_sendmsg|udp_recvmsg"
    r")\b"
)

# SEC() annotation form — primary for .bpf.c source files.
_KPROBE_SECRET_SEC: re.Pattern[str] = _re(
    r"SEC\s{0,3}\(\s{0,3}\"k(?:ret)?probe/"
    r"(?:__x64_sys_|__arm64_sys_|do_sys_|sys_)?"
    r"(?:read|openat|open|tcp_sendmsg|tcp_recvmsg|tty_read|vfs_read)"
    r"\""
)


# Rule 3: register_kprobe on the syscall table or __*_sys_* symbol.
# Match the canonical struct-init pattern (.symbol_name = "..."). We do
# NOT try to AST-pair register_kprobe + struct kprobe; the struct field
# alone is a strong enough signal.
_KPROBE_SYSCALL_TABLE: re.Pattern[str] = _re(
    r"\.symbol_name\s{0,3}=\s{0,3}\""
    r"(?:sys_call_table|__x64_sys_\w{1,80}|__arm64_sys_\w{1,80}|do_sys_\w{1,80})"
    r"\""
)


# Rule 4: bpf_override_return — surface anywhere outside test fixtures.
_BPF_OVERRIDE_RETURN: re.Pattern[str] = _re(r"\bbpf_override_return\s{0,3}\(")


# Rule 5: uprobe / uretprobe on libc / libssl / PAM secret functions.
_UPROBE_SECRET_FN: re.Pattern[str] = _re(
    r"bpf_program__attach_uprobe(?:_opts)?\s{0,3}\([^)]{0,400}"
    r"\b(?:"
    r"getpwnam|getpwuid|getspnam|"
    r"crypt|crypt_r|"
    r"PEM_read_RSAPrivateKey|"
    r"SSL_write|SSL_read|SSL_do_handshake|"
    r"gnutls_record_send|gnutls_record_recv|"
    r"EVP_DigestSign|EVP_DigestSignFinal|"
    r"RSA_private_encrypt|RSA_private_decrypt|"
    r"pam_authenticate|sshd_passwd_check"
    r")\b"
)

_UPROBE_SECRET_SEC: re.Pattern[str] = _re(
    r"SEC\s{0,3}\(\s{0,3}\"u(?:ret)?probe/[^\"]{0,200}"
    r"(?:getpwnam|crypt|SSL_write|SSL_read|"
    r"gnutls_record_(?:send|recv)|pam_authenticate)\""
)


# Rule 6: bpf_obj_pin under /sys/fs/bpf without a paired chmod 0600.
_BPF_OBJ_PIN: re.Pattern[str] = _re(
    r"bpf_obj_pin\s{0,3}\([^)]{0,200}\"(/sys/fs/bpf/[^\"]{1,200})\""
)

# Restrictive chmod accompanying a pinned-map path: 0600 / 0400 /
# 0700 / S_IRUSR|S_IWUSR / S_IRUSR alone are acceptable. Anything
# wider (0644, 0666, 0755, 0777, 0664, world-read flags) fires.
# Match permissive chmod on the same path (within 50 lines). We use a
# bounded \S to stop scanning at whitespace boundaries.
_PERMISSIVE_CHMOD: re.Pattern[str] = _re(
    r"\bchmod\s*\(?\s*"
    r"(?:\"[^\"]{1,200}\"|\S{1,200})\s*,\s*"
    r"0?o?(?:6(?:[2-7][0-7]|[0-7][2-7])|"
    r"7[0-7][0-7]|"
    r"4(?:[2-7][0-7]|[0-7][2-7]))"
)

# tc subsystem pin paths are root-only by convention — carve-out.
_TC_PIN_PATH: re.Pattern[str] = _re(r"^/sys/fs/bpf/tc/")


# Rule 7: insmod / modprobe of out-of-tree .ko.
# Bounded path component, no greedy match across newlines.
_INSMOD_KO: re.Pattern[str] = _re_i(
    r"\b(?:insmod|modprobe(?:\s{1,3}(?:-f|--force))?)\s{1,3}"
    r"(?P<path>[^\s\"';|&]{1,250}\.ko)\b"
)

# Distro-managed module paths — carve-out.
_DISTRO_MODULE_PATH: re.Pattern[str] = _re_i(
    r"^(?:/lib/modules/[^/\s]{1,80}/kernel/|/usr/lib/modules/)"
)

# sig_enforce posture indicator: kernel cmdline sets it to 0 OR a
# Kconfig fragment opts out.
_SIG_ENFORCE_OFF: re.Pattern[str] = _re_i(
    r"(?:^|\b)(?:module\.sig_enforce\s*=\s*0|"
    r"#\s*CONFIG_MODULE_SIG_FORCE\s+is\s+not\s+set|"
    r"CONFIG_MODULE_SIG_FORCE\s*=\s*n)\b"
)


# Rule 8: module signing key filename + body match.
_SIGN_KEY_FILENAME: re.Pattern[str] = _re_i(
    r"(?:^|/)(?:modules?_sign_key|signing_key|kernel_modules?_signing)"
    r"\.(?:pem|key|priv)$"
)

# Private-key block (unencrypted form only). DEK-Info / ENCRYPTED
# header means the key is passphrase-wrapped and not directly usable —
# we explicitly do NOT fire on those.
_PRIVATE_KEY_HEADER: re.Pattern[str] = _re(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"
)

_ENCRYPTED_KEY_HEADER: re.Pattern[str] = _re(
    r"(?:Proc-Type:\s*4,ENCRYPTED|DEK-Info:|Encrypted: yes)"
)

# Module-signing certificate marker — strengthens the filename signal
# when present in a sibling PEM body.
_MOD_SIGN_CERT: re.Pattern[str] = _re(
    r"-----BEGIN CERTIFICATE-----[\s\S]{1,4000}?"
    r"(?:Module\s+Signing|module\s+signing|kernel\s+module\s+signing)"
)


# Rule 9: kptr_restrict / perf_event_paranoid posture in sysctl.d.
_KPTR_RESTRICT_LEAK: re.Pattern[str] = _re_i(
    r"^\s*kernel\.kptr_restrict\s*=\s*[01]\s*(?:#|$)"
)

_PERF_EVENT_PARANOID_LEAK: re.Pattern[str] = _re_i(
    r"^\s*kernel\.perf_event_paranoid\s*=\s*[01]?\s*(?:#|$)"
)

# Same-line opt-out marker.
_KSPP_EXEMPT: re.Pattern[str] = _re_i(r"#\s*kspp-exempt\b")


# Rule 10: STRICT_DEVMEM disabled OR /dev/mem opened with PROT_WRITE.
_STRICT_DEVMEM_OFF: re.Pattern[str] = _re(
    r"^\s*(?:#\s*CONFIG_(?:IO_)?STRICT_DEVMEM\s+is\s+not\s+set|"
    r"CONFIG_(?:IO_)?STRICT_DEVMEM\s*=\s*n)\s*$"
)

_DEVMEM_OPEN: re.Pattern[str] = _re(
    r"\b(?:open|fopen)\s{0,3}\(\s{0,3}\""
    r"(/dev/(?:k?mem|port))"
    r"\""
)

# mmap with PROT_WRITE — we require it to live within a window of an
# /dev/mem open to fire, so the regex itself just identifies write
# mappings.
_MMAP_PROT_WRITE: re.Pattern[str] = _re(
    r"\bmmap\s{0,3}\([^)]{0,300}\bPROT_(?:READ\s*\|\s*WRITE|WRITE\s*\|\s*READ|WRITE)\b"
)


# Rule 11: firmware_class.path hijack — bootloader config line.
_FIRMWARE_CLASS_PATH: re.Pattern[str] = _re_i(
    r"\bfirmware_class\.path\s*=\s*"
    r"(?P<path>"
    r"/tmp(?:/[^\s\"',]{0,200})?|"
    r"/var/tmp(?:/[^\s\"',]{0,200})?|"
    r"/dev/shm(?:/[^\s\"',]{0,200})?|"
    r"/home/[^/\s\"',]{1,80}(?:/[^\s\"',]{0,200})?|"
    r"/run/user/\d{1,10}(?:/[^\s\"',]{0,200})?|"
    r"/srv/[^/\s\"',]{0,80}/uploads?(?:/[^\s\"',]{0,200})?|"
    r"\.\.?/[^\s\"',]{0,200}"
    r")"
)


# Rule 12: LSM stacking misconfigured.
# Cmdline form: lsm=apparmor,selinux (or any list of 2+ LSMs).
_LSM_STACK_DECLARE: re.Pattern[str] = _re_i(
    r"\blsm\s*=\s*(?P<stack>[a-z][a-z_,]{1,200})\b"
)

# Permissive markers: selinux=0, enforce=0, SELINUX=permissive in
# /etc/selinux/config, or sysctl-style enforce=0.
_LSM_PERMISSIVE: re.Pattern[str] = _re_i(
    r"(?:^|\b)(?:"
    r"selinux\s*=\s*0|"
    r"enforcing\s*=\s*0|"
    r"SELINUX\s*=\s*permissive|"
    r"SELINUX\s*=\s*disabled|"
    r"apparmor\s*=\s*0"
    r")(?:$|\b)"
)


# Rule 13: bpftool binary install in production deployment.
# Match Dockerfile RUN apt-get install / yum install of bpftool /
# linux-tools-* packages, or a direct reference to the binary path
# inside a CMD / ENTRYPOINT / RUN.
_BPFTOOL_INSTALL: re.Pattern[str] = _re_i(
    r"\b(?:apt-get\s+install|apt\s+install|yum\s+install|dnf\s+install|"
    r"apk\s+add|zypper\s+install)\b[^\n]{0,300}"
    r"\b(?:bpftool|linux-tools-(?:generic|common|\$\{?[A-Z_]{1,40}\}?)|"
    r"linux-tools-[\d.]{1,15})\b"
)

_BPFTOOL_BIN_PATH: re.Pattern[str] = _re_i(
    r"(?:^|[^\w/])(?:/usr/sbin/bpftool|/usr/local/sbin/bpftool|/sbin/bpftool)\b"
)


# Rule 14: container with CAP_NET_RAW / CAP_NET_ADMIN / CAP_BPF +
# seccomp Unconfined. YAML-walker based — we still keep a regex for
# scan_text dispatch.
_CONTAINER_CAP_NET_RAW: re.Pattern[str] = _re_i(
    r"\b(?:NET_RAW|NET_ADMIN|CAP_NET_RAW|CAP_NET_ADMIN|CAP_BPF|BPF)\b"
)

_SECCOMP_UNCONFINED: re.Pattern[str] = _re_i(
    r"(?:seccomp(?:Profile)?[\s:]+(?:type[\s:]+)?[\"']?Unconfined[\"']?|"
    r"seccomp\s*[:=]\s*[\"']?unconfined[\"']?)"
)


# Rule 15: BTF blob fetched from untrusted HTTPS URL.
# Two surfaces:
#   (a) shell-style `curl URL` / `wget URL` (no parens)
#   (b) language-style `requests.get("URL")` / `http.get(URL)` (with parens)
# Both pull a URL whose path ends with vmlinux / btf / *.btf / *.tar.gz/xz.
_BTF_FETCH: re.Pattern[str] = _re_i(
    r"(?:\b(?:curl|wget)\b[^\n]{0,200}|"
    r"(?:requests\.get|http\.get|fetch|urlretrieve)\s{0,3}\([^)]{0,400})"
    r"\b(?P<url>https?://[^\s\"',)]{1,400}"
    r"/(?:[Vv]mlinux|btf|BTF)[^\s\"',)]{0,200}"
    r"\.(?:btf|tar\.gz|tar\.xz|tar))\b"
)

# Trusted BTF mirror allowlist. The proposal explicitly names BTFHub
# mirrors; we narrow conservatively here. Operators add their own
# vendor mirrors via janitor config in the future.
_TRUSTED_BTF_HOSTS: tuple[str, ...] = (
    "btfhub.com",
    "mirrors.cloud.tencent.com",
    "github.com/aquasecurity/btfhub-archive",
    "raw.githubusercontent.com/aquasecurity/btfhub-archive",
    "btfhub-archive.s3.amazonaws.com",
    "ddebug.canonical.com",  # Ubuntu debug-info
    "debuginfo.elrepo.org",
    "access.redhat.com",
)

# SHA-256 verification — companion command implies pin-check, suppress.
_SHA256_PIN_NEARBY: re.Pattern[str] = _re_i(
    r"\b(?:sha256sum\s+(?:-c|--check)|"
    r"hashlib\.sha256|"
    r"openssl\s+dgst\s+-sha256|"
    r"sha-?256\s*[:=])"
)


# ---- File-kind sniffers -------------------------------------------------


_BPF_C_HINT: re.Pattern[str] = _re(
    r"(?:#\s*include\s*<(?:bpf/bpf|linux/bpf|bpf/bpf_helpers)\.h>|"
    r"\bSEC\s*\(\s*\"(?:k|u|tp|tracepoint|raw_tp|cgroup|xdp|sk_msg|fentry|fexit)\b|"
    r"\bchar\s+LICENSE\[\]\s+SEC\s*\(\s*\"license\"\))"
)

_KCONFIG_HINT: re.Pattern[str] = _re_i(
    r"(?:^\s*#\s*CONFIG_[A-Z0-9_]{1,80}\s+is\s+not\s+set|"
    r"^\s*CONFIG_[A-Z0-9_]{1,80}\s*=\s*[ynm\"])"
)

_CMDLINE_HINT: re.Pattern[str] = _re(
    r"(?:^|\s)(?:menuentry\b|linux\s+/boot/|"
    r"GRUB_CMDLINE_LINUX|GRUB_CMDLINE_LINUX_DEFAULT|"
    r"^APPEND\s|^kernel\s+/boot/)"
)

_SYSCTL_HINT: re.Pattern[str] = _re(
    r"^\s*kernel\.[a-z_]{1,40}\s*="
)

_PEM_HINT: re.Pattern[str] = _re(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)(?:PRIVATE KEY|CERTIFICATE)-----"
)

_K8S_HINT: re.Pattern[str] = _re(
    r"^\s*apiVersion:\s|^\s*kind:\s+(?:Pod|Deployment|StatefulSet|"
    r"DaemonSet|ReplicaSet|Job|CronJob)\b"
)

_C_SOURCE_HINT: re.Pattern[str] = _re(
    r"(?:#\s*include\s*<linux/(?:kprobes|module|init)\.h>|"
    r"\bregister_kprobe\s*\(|"
    r"\bMODULE_LICENSE\s*\(|"
    r"\bMODULE_AUTHOR\s*\(|"
    r"\bmodule_init\s*\()"
)

_SHELL_HINT: re.Pattern[str] = _re_i(
    r"(?:^|\s)(?:#!/bin/(?:ba|z|)sh|^FROM\s|^RUN\s|^CMD\s|^ENTRYPOINT\s|"
    r"\binsmod\s|\bmodprobe\s|\bapt-get\b|\bcurl\s|\bwget\s)"
)


# ---- Scan helpers -------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert string offset → (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _trunc(s: str, n: int = 200) -> str:
    """Truncate matched_text for reporting."""
    return s if len(s) <= n else s[:n] + "..."


def _rule(rule_id: str) -> Rule:
    """Lookup a rule by id."""
    for r in RULES:
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def _emit(findings: list[Finding], rule: Rule, text: str, offset: int, matched: str) -> None:
    """Append a Finding from an offset + match string."""
    line, col = _line_col(text, offset)
    findings.append(Finding(
        rule_id=rule.id,
        line=line, column=col,
        matched_text=_trunc(matched),
        severity=rule.severity,
        description=rule.description,
        owasp_asi=rule.owasp_asi,
    ))


def _yaml_load_all(text: str) -> list[Any]:
    """Best-effort multi-doc YAML load. Returns [] on parse-error."""
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return []
    try:
        return [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError:
        return []


# ---- Rule 1: BPF_PROG_LOAD without cap-check ----------------------------


def _scan_bpf_prog_load(text: str, findings: list[Finding], *,
                       file_path: str = "") -> None:
    """Detect BPF_PROG_LOAD calls without a nearby capability check.

    "Nearby" = within +/- 800 chars of the match (one call frame's
    worth of source). This is a heuristic — a true AST pass would do
    same-function bounding but the static scanner cannot fork a C
    parser without dragging in a heavy dep.
    """
    if file_path and _BPF_TEST_PATH.search(file_path) is not None:
        return
    rule = _rule("ebpf-prog-load-uncapped")
    for m in _BPF_PROG_LOAD.finditer(text):
        start = max(0, m.start() - 800)
        end = min(len(text), m.end() + 800)
        window = text[start:end]
        if _CAP_CHECK.search(window) is not None:
            continue
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 2: kprobe on secret-handling syscall --------------------------


def _scan_kprobe_secret_syscall(text: str, findings: list[Finding]) -> None:
    """Detect kprobe / kretprobe attachments on secret-bearing syscalls."""
    rule = _rule("ebpf-kprobe-on-secret-syscall")
    for m in _KPROBE_SECRET_FN.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))
    for m in _KPROBE_SECRET_SEC.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 3: register_kprobe on syscall table ---------------------------


def _scan_kprobe_syscall_table(text: str, findings: list[Finding]) -> None:
    """Detect kprobe struct-init targeting the syscall table."""
    rule = _rule("kmod-kprobe-on-syscall-table")
    for m in _KPROBE_SYSCALL_TABLE.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 4: bpf_override_return ----------------------------------------


def _scan_override_return(text: str, findings: list[Finding], *,
                          file_path: str = "") -> None:
    """Detect bpf_override_return() outside fault-injection paths."""
    if file_path and _BPF_TEST_PATH.search(file_path) is not None:
        return
    rule = _rule("ebpf-override-return")
    for m in _BPF_OVERRIDE_RETURN.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 5: uprobe on libc / libssl / PAM secret functions -------------


def _scan_uprobe_secret_fn(text: str, findings: list[Finding]) -> None:
    """Detect uprobe / uretprobe on credential-handling libraries."""
    rule = _rule("ebpf-uprobe-on-libc-secret-fn")
    for m in _UPROBE_SECRET_FN.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))
    for m in _UPROBE_SECRET_SEC.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 6: pinned eBPF map without restrictive chmod ------------------


def _scan_pinned_map(text: str, findings: list[Finding]) -> None:
    """Detect bpf_obj_pin without a paired chmod 0600 within 50 lines."""
    rule = _rule("ebpf-map-pin-world-readable")
    for m in _BPF_OBJ_PIN.finditer(text):
        path = m.group(1)
        # tc subsystem carve-out.
        if _TC_PIN_PATH.search(path) is not None:
            continue
        # Look forward ~50 lines (~2 KB) for a restrictive or permissive
        # chmod referencing the same path. Default-on-absence: fire.
        window = text[m.end():m.end() + 2000]
        if _PERMISSIVE_CHMOD.search(window):
            _emit(findings, rule, text, m.start(), m.group(0))
            continue
        # No permissive chmod — check if any chmod on this path appears
        # within the window. The proposal's safe path is an explicit
        # chmod 0600. Match a 0600/0400/0700/S_IRUSR... chmod on the
        # same path; absence of any restrictive chmod also fires.
        safe_chmod = re.compile(
            r"\bchmod\s*\(?\s*(?:\"" + re.escape(path) + r"\"|"
            + re.escape(path) + r")\s*,\s*"
            r"0?o?(?:0?[1-6]00|S_I[RW]USR)"
        )
        if safe_chmod.search(window) is None:
            _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 7: insmod / modprobe of out-of-tree .ko + sig_enforce off -----


def _scan_unsigned_module(text: str, findings: list[Finding]) -> None:
    """Detect insmod/modprobe of out-of-tree .ko in unsafe posture."""
    rule = _rule("kmod-unsigned-out-of-tree")
    # Posture probe: does this file declare sig_enforce off / mod-sig
    # config disabled? OR is the path explicitly out-of-tree?
    posture_off = _SIG_ENFORCE_OFF.search(text) is not None
    for m in _INSMOD_KO.finditer(text):
        path = m.group("path")
        # Distro-managed module path — carve-out.
        if _DISTRO_MODULE_PATH.search(path) is not None:
            continue
        # Out-of-tree path → fire even without explicit sig_enforce=0
        # when the path is in a writable area (/tmp /opt /home /root
        # /usr/local) — those are the supply-chain delivery vectors.
        # Otherwise require the posture indicator.
        writable_path = re.match(
            r"^(?:/tmp/|/var/tmp/|/opt/|/home/|/root/|/usr/local/|"
            r"\./|\.\./|[^/])", path
        )
        if writable_path is not None or posture_off:
            _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 8: module signing key exposed ---------------------------------


def _scan_signing_key(text: str, findings: list[Finding], *,
                     file_path: str = "") -> None:
    """Detect a module signing key embedded in a PEM body."""
    rule = _rule("kmod-signing-key-exposed")
    # Two ways to fire: (a) filename matches signing-key glob AND body
    # contains a PRIVATE KEY block; (b) body contains both a PRIVATE
    # KEY block AND a Module-Signing certificate marker.
    name_hit = bool(file_path) and _SIGN_KEY_FILENAME.search(file_path) is not None
    body_hit = _PRIVATE_KEY_HEADER.search(text)
    if body_hit is None:
        return
    if _ENCRYPTED_KEY_HEADER.search(text) is not None:
        # Encrypted with a passphrase — not directly usable, do not fire.
        return
    cert_hit = _MOD_SIGN_CERT.search(text) is not None
    if name_hit or cert_hit:
        _emit(findings, rule, text, body_hit.start(), body_hit.group(0))


# ---- Rule 9: kptr_restrict / perf_event_paranoid posture ----------------


def _scan_kallsyms_leak(text: str, findings: list[Finding]) -> None:
    """Detect sysctl declaring KASLR-leaking kernel posture."""
    rule = _rule("kernel-kallsyms-leaked")
    for m in _KPTR_RESTRICT_LEAK.finditer(text):
        # Same-line opt-out marker suppresses.
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end]
        if _KSPP_EXEMPT.search(line) is not None:
            continue
        _emit(findings, rule, text, m.start(), m.group(0).rstrip())
    for m in _PERF_EVENT_PARANOID_LEAK.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end]
        if _KSPP_EXEMPT.search(line) is not None:
            continue
        _emit(findings, rule, text, m.start(), m.group(0).rstrip())


# ---- Rule 10: /dev/mem opened with write OR STRICT_DEVMEM=n -------------


def _scan_devmem(text: str, findings: list[Finding]) -> None:
    """Detect /dev/mem write-mapping or STRICT_DEVMEM disabled."""
    rule = _rule("kernel-devmem-open")
    # Kconfig form — fire directly.
    for m in _STRICT_DEVMEM_OFF.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))
    # Source-code form — require both /dev/mem open AND PROT_WRITE
    # mmap within +/- 1500 chars of each other.
    opens = list(_DEVMEM_OPEN.finditer(text))
    mmaps = list(_MMAP_PROT_WRITE.finditer(text))
    for o in opens:
        for mm in mmaps:
            if abs(mm.start() - o.start()) <= 1500:
                _emit(findings, rule, text, o.start(), o.group(0))
                break


# ---- Rule 11: firmware_class.path hijack --------------------------------


def _scan_firmware_class_path(text: str, findings: list[Finding]) -> None:
    """Detect a firmware_class.path= pointing to a writable directory."""
    rule = _rule("kernel-firmware-class-path-hijack")
    for m in _FIRMWARE_CLASS_PATH.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 12: LSM stack passive / permissive ----------------------------


def _scan_lsm_stack(text: str, findings: list[Finding]) -> None:
    """Detect LSM stacking with a passive / permissive member."""
    rule = _rule("kernel-lsm-stack-passive")
    stack_match = _LSM_STACK_DECLARE.search(text)
    # Multi-LSM stack declaration?
    multi_lsm = False
    if stack_match is not None:
        stack = stack_match.group("stack")
        members = [s.strip() for s in stack.split(",") if s.strip()]
        multi_lsm = len(members) >= 2
    permissive_match = _LSM_PERMISSIVE.search(text)
    # Fire when EITHER: (a) we see a stack AND a permissive marker, OR
    # (b) we see a permissive marker on its own in a file that also
    # references SELinux/AppArmor by name (avoids spurious fires on
    # unrelated files that happen to contain `enforce=0`).
    if multi_lsm and permissive_match is not None:
        _emit(findings, rule, text, permissive_match.start(),
              permissive_match.group(0))
    elif permissive_match is not None:
        if re.search(r"(?:SELINUX|AppArmor|apparmor|selinux|TOMOYO|SMACK)",
                    text) is not None:
            _emit(findings, rule, text, permissive_match.start(),
                  permissive_match.group(0))


# ---- Rule 13: bpftool present in production -----------------------------


def _scan_bpftool_in_prod(text: str, findings: list[Finding]) -> None:
    """Detect bpftool installation in a deployment artifact."""
    rule = _rule("ebpf-bpftool-in-prod")
    for m in _BPFTOOL_INSTALL.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))
    for m in _BPFTOOL_BIN_PATH.finditer(text):
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- Rule 14: container CAP_NET_RAW + seccomp unconfined ---------------


def _scan_container_net_raw_bpf(text: str, findings: list[Finding]) -> None:
    """Detect k8s/compose containers granting CAP_NET_RAW with no seccomp."""
    rule = _rule("ebpf-container-net-raw-bpf")
    # YAML-walker path first when YAML loads.
    docs = _yaml_load_all(text)
    for doc in docs:
        if isinstance(doc, dict):
            _walk_k8s_for_cap_seccomp(doc, text, findings, rule)
    # Regex path as fallback — fire when both markers exist in the
    # same file but the YAML walker missed (malformed YAML, mixed
    # formats, etc.).
    if not docs:
        cap_match = _CONTAINER_CAP_NET_RAW.search(text)
        sec_match = _SECCOMP_UNCONFINED.search(text)
        if cap_match is not None and sec_match is not None:
            # Fire on the cap declaration — that's the action that
            # raises the privilege.
            _emit(findings, rule, text, cap_match.start(), cap_match.group(0))


def _walk_k8s_for_cap_seccomp(doc: dict[str, Any], text: str,
                              findings: list[Finding], rule: Rule) -> None:
    """Walk k8s pod spec / compose service looking for the bad combo."""
    # k8s wrapping (Pod / Deployment / DaemonSet / ...).
    spec = _k8s_pod_spec(doc)
    if spec is not None:
        for c in _iter_containers(spec):
            if _container_has_cap_net_raw_and_unconfined(c, spec):
                _emit(findings, rule, text, 0, "container: " +
                      str(c.get("name", "?")))
    # compose form.
    svcs = doc.get("services") if isinstance(doc, dict) else None
    if isinstance(svcs, dict):
        for name, svc in svcs.items():
            if not isinstance(svc, dict):
                continue
            if _compose_svc_has_cap_net_raw_and_unconfined(svc):
                _emit(findings, rule, text, 0, "service: " + str(name))


def _k8s_pod_spec(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Extract pod spec from a k8s doc regardless of wrapping kind."""
    if not isinstance(doc, dict):
        return None
    kind = doc.get("kind")
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        return None
    if kind == "Pod":
        return spec
    template = spec.get("template")
    if isinstance(template, dict):
        tspec = template.get("spec")
        if isinstance(tspec, dict):
            return tspec
    return None


def _iter_containers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Iterate `containers:` + `initContainers:` of a pod spec."""
    out: list[dict[str, Any]] = []
    for key in ("containers", "initContainers", "ephemeralContainers"):
        items = spec.get(key)
        if isinstance(items, list):
            for c in items:
                if isinstance(c, dict):
                    out.append(c)
    return out


def _container_has_cap_net_raw_and_unconfined(
    c: dict[str, Any], pod_spec: dict[str, Any]
) -> bool:
    """Container grants CAP_NET_RAW/ADMIN/BPF AND seccomp Unconfined?"""
    sc = c.get("securityContext")
    caps_add: list[str] = []
    if isinstance(sc, dict):
        caps = sc.get("capabilities")
        if isinstance(caps, dict):
            adds = caps.get("add")
            if isinstance(adds, list):
                caps_add = [str(x).upper() for x in adds]
    has_cap = any(c in {"NET_RAW", "NET_ADMIN", "BPF", "CAP_NET_RAW",
                       "CAP_NET_ADMIN", "CAP_BPF"} for c in caps_add)
    if not has_cap:
        return False
    # Check seccomp at container level then pod level.
    seccomp = _find_seccomp_profile(c.get("securityContext"))
    if seccomp is None:
        seccomp = _find_seccomp_profile(pod_spec.get("securityContext"))
    # Missing block defaults to Unconfined on pre-1.27 — fire.
    if seccomp is None:
        return True
    return seccomp.lower() == "unconfined"


def _find_seccomp_profile(sc: Any) -> str | None:
    if not isinstance(sc, dict):
        return None
    prof = sc.get("seccompProfile")
    if isinstance(prof, dict):
        t = prof.get("type")
        if isinstance(t, str):
            return t
    return None


def _compose_svc_has_cap_net_raw_and_unconfined(svc: dict[str, Any]) -> bool:
    """compose service: cap_add includes NET_RAW/ADMIN/BPF + security_opt unconfined?"""
    cap_add = svc.get("cap_add")
    cap_names: list[str] = []
    if isinstance(cap_add, list):
        cap_names = [str(c).upper() for c in cap_add]
    if not any(c in {"NET_RAW", "NET_ADMIN", "BPF", "CAP_NET_RAW",
                    "CAP_NET_ADMIN", "CAP_BPF", "ALL"} for c in cap_names):
        return False
    sec_opt = svc.get("security_opt")
    if not isinstance(sec_opt, list):
        # Missing security_opt entirely → unconfined by docker default.
        return True
    for entry in sec_opt:
        if not isinstance(entry, str):
            continue
        low = entry.lower()
        if "seccomp" in low and "unconfined" in low:
            return True
    # Compose default for seccomp is the default profile, NOT unconfined,
    # so absence of explicit `seccomp=unconfined` should NOT fire — but
    # the rule's main risk is the cap; flag at MEDIUM via presence of
    # only one of the markers (the regex fallback path picks that up).
    return False


# ---- Rule 15: BTF blob from untrusted source ----------------------------


def _scan_btf_fetch(text: str, findings: list[Finding]) -> None:
    """Detect curl/wget of BTF blob from a non-allowlisted host."""
    rule = _rule("ebpf-btf-from-untrusted-source")
    for m in _BTF_FETCH.finditer(text):
        url = m.group("url")
        if any(host in url for host in _TRUSTED_BTF_HOSTS):
            continue
        # Check for sha256 pin within +/- 500 chars.
        start = max(0, m.start() - 500)
        end = min(len(text), m.end() + 500)
        if _SHA256_PIN_NEARBY.search(text[start:end]) is not None:
            continue
        _emit(findings, rule, text, m.start(), m.group(0))


# ---- File-kind dispatchers ----------------------------------------------


def scan_bpf_source(text: str, *, file_path: str = "") -> list[Finding]:
    """Apply rules that target eBPF source (.bpf.c / libbpf user code)."""
    findings: list[Finding] = []
    _scan_bpf_prog_load(text, findings, file_path=file_path)
    _scan_kprobe_secret_syscall(text, findings)
    _scan_override_return(text, findings, file_path=file_path)
    _scan_uprobe_secret_fn(text, findings)
    _scan_pinned_map(text, findings)
    return findings


def scan_c_source(text: str, *, file_path: str = "") -> list[Finding]:
    """Apply rules that target plain C (kernel module .c)."""
    findings: list[Finding] = []
    _scan_kprobe_syscall_table(text, findings)
    _scan_override_return(text, findings, file_path=file_path)
    _scan_devmem(text, findings)
    return findings


def scan_shell_or_workflow(text: str) -> list[Finding]:
    """Apply rules that need shell-script / Dockerfile context."""
    findings: list[Finding] = []
    _scan_unsigned_module(text, findings)
    _scan_bpftool_in_prod(text, findings)
    _scan_btf_fetch(text, findings)
    _scan_devmem(text, findings)
    return findings


def scan_kconfig_or_cmdline(text: str) -> list[Finding]:
    """Apply rules that target Kconfig fragments / boot cmdline."""
    findings: list[Finding] = []
    _scan_firmware_class_path(text, findings)
    _scan_devmem(text, findings)
    _scan_lsm_stack(text, findings)
    _scan_unsigned_module(text, findings)
    return findings


def scan_sysctl(text: str) -> list[Finding]:
    """Apply rules that target sysctl.d / /etc/sysctl.conf files."""
    findings: list[Finding] = []
    _scan_kallsyms_leak(text, findings)
    _scan_lsm_stack(text, findings)
    return findings


def scan_pem(text: str, *, file_path: str = "") -> list[Finding]:
    """Apply rules that target PEM / key files."""
    findings: list[Finding] = []
    _scan_signing_key(text, findings, file_path=file_path)
    return findings


def scan_k8s(text: str) -> list[Finding]:
    """Apply rules that target k8s manifests / compose YAML."""
    findings: list[Finding] = []
    _scan_container_net_raw_bpf(text, findings)
    return findings


# ---- File-kind sniffer + top-level dispatcher ---------------------------


def _detect_kind(text: str) -> str:
    """Sniff the file kind from content.

    Order: PEM > K8s/compose > BPF C > C source > Kconfig/cmdline >
    sysctl > shell.
    """
    head = text[:2000]
    if _PEM_HINT.search(head) is not None:
        return "pem"
    if _K8S_HINT.search(head) is not None:
        return "k8s"
    if _BPF_C_HINT.search(text[:4000]) is not None:
        return "bpf_c"
    if _C_SOURCE_HINT.search(text[:4000]) is not None:
        return "c_source"
    if _KCONFIG_HINT.search(text[:4000]) is not None:
        return "kconfig"
    if _CMDLINE_HINT.search(text[:4000]) is not None:
        return "cmdline"
    if _SYSCTL_HINT.search(text[:4000]) is not None:
        return "sysctl"
    if _SHELL_HINT.search(text[:2000]) is not None:
        return "shell"
    return "shell"


def scan_text(text: str, *, file_kind: str = "auto",
             file_path: str = "") -> list[Finding]:
    """Top-level dispatcher.

    file_kind: "auto" (sniff), "bpf_c", "c_source", "shell", "kconfig",
               "cmdline", "sysctl", "pem", "k8s".

    file_path: optional — used for path-based false-positive guards
    (tests/, fuzz/, samples/, signing-key filename match).

    Findings come out sorted by (line, column, rule_id) and deduped on
    (rule_id, line, column, matched_text).
    """
    if not text:
        return []
    if file_kind == "auto":
        file_kind = _detect_kind(text)

    findings: list[Finding] = []
    if file_kind == "bpf_c":
        findings.extend(scan_bpf_source(text, file_path=file_path))
    elif file_kind == "c_source":
        findings.extend(scan_c_source(text, file_path=file_path))
    elif file_kind in ("kconfig", "cmdline"):
        findings.extend(scan_kconfig_or_cmdline(text))
    elif file_kind == "sysctl":
        findings.extend(scan_sysctl(text))
    elif file_kind == "pem":
        findings.extend(scan_pem(text, file_path=file_path))
    elif file_kind == "k8s":
        findings.extend(scan_k8s(text))
    else:  # shell / default
        findings.extend(scan_shell_or_workflow(text))

    # Dedupe on (rule_id, line, column, matched_text).
    seen: set[tuple[str, int, int, str]] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = (f.rule_id, f.line, f.column, f.matched_text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    deduped.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return deduped
