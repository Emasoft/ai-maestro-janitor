"""Linux kernel-modules / kernel-config / capability-surface patterns.

Wave-23 distillation round 9 — Linux kernel hardening posture.

Catalogue of 7 kernel-layer anti-patterns distilled in
`reports/distill-round-9/linux-kernel-modules.md`. Targets the surface
that Wave-19 `scripts/lib/ebpf_kernel_patterns.py` does NOT already
cover: sysfs/debugfs world-writable flips, insmod/modprobe
``--allow-unsigned`` / ``--force`` flags, kernel-build with module
signature enforcement disabled, ``CAP_SYS_ADMIN`` retention past init,
the KSPP hardening-sysctl "off-switch six-pack", ``setcap`` of
``cap_sys_admin`` (and friends) on filesystem binaries, and
``prctl(PR_SET_DUMPABLE, 1)`` / ``prctl(PR_SET_NO_NEW_PRIVS, 0)``
regressions.

What is NOT here (already shipped by Wave-19, DO NOT duplicate):

  * ``BPF_PROG_LOAD`` without capability — ``ebpf-prog-load-uncapped``.
  * kprobe/uprobe on secret syscalls — ``ebpf-kprobe-on-secret-syscall``.
  * ``bpf_override_return`` — ``ebpf-override-return``.
  * Out-of-tree ``.ko`` paths — ``kmod-unsigned-out-of-tree``.
  * Module-signing key PEMs — ``kmod-signing-key-exposed``.
  * ``kernel.kptr_restrict = 0`` / ``perf_event_paranoid = 0`` —
    ``kernel-kallsyms-leaked``.
  * ``/dev/mem`` / ``/dev/kmem`` opens — ``kernel-devmem-open``.
  * ``firmware_class.path=`` hijack — ``kernel-firmware-class-path-hijack``.
  * LSM stack permissive — ``kernel-lsm-stack-passive``.
  * ``bpftool`` in production — ``ebpf-bpftool-in-prod``.
  * ``CAP_NET_RAW`` + seccomp unconfined — ``ebpf-container-net-raw-bpf``.
  * BTF fetch from untrusted source — ``ebpf-btf-from-untrusted-source``.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * kernel-debugfs-world-writable                       (CRITICAL)
  * kmod-force-unsigned-flag                            (CRITICAL)
  * kmod-sig-force-disabled-buildflag                   (HIGH)
  * cap-sys-admin-retained-post-init                    (CRITICAL)
  * kernel-hardening-sysctl-disabled                    (HIGH)
  * binary-setcap-sys-admin-on-fs                       (CRITICAL)
  * prctl-dumpable-or-noprivs-regression                (HIGH)

Public surface (mirrors ``chat_bot_patterns`` / ``ebpf_kernel_patterns``):

  * ``Rule(id, name, severity, description, pattern, owasp_asi)`` — frozen
    NamedTuple with the pre-compiled pattern.
  * ``RULES`` — ordered tuple of every rule.
  * ``scan_text(text) -> list[Finding]``.
  * ``Finding(rule_id, line, column, matched_text, severity, description,
    owasp_asi)`` — frozen NamedTuple, same shape as
    ``webhook_signature_patterns.Finding``.

OWASP ASI mapping used:
  ASI-02 — Sensitive info disclosure (``PR_SET_DUMPABLE`` re-enable).
  ASI-04 — Authentication / authority gap (``CAP_SYS_ADMIN`` retention,
                                            ``setcap`` on fs binary).
  ASI-07 — Privilege escalation (debugfs world-writable, signed-module
                                  bypass, hardening sysctl regression).

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/webhook_signature_patterns.Finding`` so heartbeat
    detectors can render either kind uniformly."""

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
    """Compile with MULTILINE+UNICODE. IGNORECASE is opt-in per rule
    because some kernel identifiers are case-sensitive
    (e.g. ``CAP_SYS_ADMIN`` vs ``cap_sys_admin``). Mirror of the helper
    in ``ebpf_kernel_patterns``."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_i(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE for textual config /
    shell shapes where case is incidental."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# Shared opt-out marker. Reuse the Wave-19 ``# kspp-exempt`` token so a
# single line-comment opt-out works across every kernel-hardening rule.
_KSPP_EXEMPT_MARKER = _re_i(r"#\s*(?:kspp-exempt|kernel-debugfs-allow|kmod-force-allow|cap-retained-intentional)\b")


# ---- P1 : kernel-debugfs-world-writable ---------------------------------


# ``chmod 0666 /sys/kernel/debug`` (or ``a+w``/``o+w``/``ugo+w``) on
# debugfs or the cgroup/security sysfs roots. The path tail can extend
# arbitrarily (a single child node like ``tracing/enable`` is still the
# same risk class).
_DEBUGFS_CHMOD_WORLD_WRITABLE = _re_i(
    r"\bchmod\s+(?:-R\s+)?(?:0?666|0?777|a\+w|o\+w|ugo\+w)\s+(?:-R\s+)?"
    r"/sys/(?:kernel/(?:debug|security)|fs/cgroup)(?:/[A-Za-z0-9_\-./]{0,200})?\b"
    r"|"
    r"\bchmod\s+(?:0?666|0?777|a\+w|o\+w|ugo\+w)\s+(?:-R\s+)?"
    r"/sys/kernel/debug\b"
)


# ---- P2 : kmod-force-unsigned-flag --------------------------------------


# ``insmod`` / ``modprobe`` with a flag that skips signature / vermagic
# / modversion checks. The flag may appear anywhere in a 200-char window
# after the command (handles ``modprobe -q --force evil.ko`` shapes).
_KMOD_FORCE_UNSIGNED_FLAG = _re_i(
    r"\b(?:insmod|modprobe)\b[^\n]{0,200}?\s"
    r"(?:--force(?:-(?:modversion|vermagic))?|--allow-unsigned)\b"
)


# ---- P3 : kmod-sig-force-disabled-buildflag -----------------------------


# Three shapes of disabling MODULE_SIG enforcement at build time:
#   (a) ``CONFIG_MODULE_SIG=n`` / ``CONFIG_MODULE_SIG_FORCE=n`` in a
#       defconfig fragment or ``.config`` line;
#   (b) ``-DCONFIG_MODULE_SIG_FORCE=0`` as a ``CFLAGS``/``EXTRA_CFLAGS``
#       build flag;
#   (c) ``# CONFIG_MODULE_SIG is not set`` — the kernel's Kconfig
#       convention for explicit-off.
_KMOD_SIG_DISABLED_CONFIG = _re(
    r"(?:^|\s)CONFIG_MODULE_SIG(?:_FORCE)?\s*[:=]\s*n\b"
)
_KMOD_SIG_DISABLED_CFLAG = _re(
    # NOTE: no ``\b`` prefix before the literal ``-`` — both ``-`` and a
    # preceding space are non-word characters, so ``\b-`` would only
    # match after a word char. The left-side context is enforced by
    # the literal ``-D`` prefix instead.
    r"-DCONFIG_MODULE_SIG(?:_FORCE)?\s*=\s*0\b"
)
_KMOD_SIG_DISABLED_NOTSET = _re(
    r"^\s*#\s*CONFIG_MODULE_SIG(?:_FORCE)?\s+is\s+not\s+set\s*$"
)


# ---- P4 : cap-sys-admin-retained-post-init ------------------------------


# Anchor on raising a high-authority capability. Stage-B filter checks
# the surrounding ~30 lines for a paired drop primitive — same window-
# walk shape as Wave-19's ``_scan_bpf_prog_load``.
_CAP_RAISE_ANCHOR = _re(
    # cap_set_proc(cap)  — libcap call form
    r"\bcap_set_proc\s*\(\s*[A-Za-z_][A-Za-z0-9_]{0,40}\s*\)"
    r"|"
    # prctl(PR_CAP_AMBIENT_RAISE, CAP_SYS_ADMIN | CAP_SYS_MODULE | ...)
    r"\bprctl\s*\(\s*PR_CAP_AMBIENT_RAISE\s*,\s*"
    r"CAP_(?:SYS_ADMIN|SYS_MODULE|SYS_RAWIO|DAC_READ_SEARCH|NET_ADMIN)\b"
)

# A drop / clear primitive: prctl(PR_CAPBSET_DROP, ...) OR cap_clear(...).
_CAP_DROP_PAIR = _re(
    r"\bprctl\s*\(\s*PR_CAPBSET_DROP\b"
    r"|"
    r"\bcap_clear\s*\("
    r"|"
    r"\bcap_set_flag\s*\([^)]*\bCAP_CLEAR\b"
)


# ---- P5 : kernel-hardening-sysctl-disabled ------------------------------


# Six knobs set to a value that turns OFF a defence. Each is matched as
# a full-line sysctl declaration so ``find /etc -name '*.conf' | xargs grep``
# style audits work identically. End-of-line anchored: trailing comments
# allowed.
_HARDENING_SYSCTL_OFF_TO_ZERO = _re(
    r"^\s*(?:"
    r"kernel\.dmesg_restrict"
    r"|kernel\.randomize_va_space"
    r"|kernel\.yama\.ptrace_scope"
    r"|kernel\.unprivileged_bpf_disabled"
    r"|fs\.protected_hardlinks"
    r"|fs\.protected_symlinks"
    r")\s*=\s*0\s*(?:#.*)?$"
)

# ``fs.suid_dumpable = 2`` is the dangerous SETUID-allows-coredump mode
# (value 0 means "off"; value 1 means "debugger-only"). Only value 2
# is the regression.
_HARDENING_SYSCTL_SUID_DUMPABLE_2 = _re(
    r"^\s*fs\.suid_dumpable\s*=\s*2\s*(?:#.*)?$"
)

# ``kernel.sysrq = 1`` (full-mask) or = 0xff / = 255 (full-mask numeric)
# enables every SysRq operation including kernel-pointer leak via
# ``show ALL registers`` and process-table reset. The hardened default
# is 0 or 176 (a curated subset).
_HARDENING_SYSCTL_SYSRQ_FULL = _re(
    r"^\s*kernel\.sysrq\s*=\s*(?:1|0xff|255)\s*(?:#.*)?$"
)


# ---- P6 : binary-setcap-sys-admin-on-fs ---------------------------------


# ``setcap cap_sys_admin+ep /path/to/binary`` — a filesystem extended-
# attribute capability grant. Allowlist is the EXCLUSION list: we
# deliberately omit ``cap_net_bind_service`` (the canonical correct
# use). Capability tokens may be comma-joined inside quoted shapes
# (``setcap "cap_a,cap_b+ep" /bin/x``) — the dangerous capability
# anywhere in the token list triggers the rule.
_SETCAP_DANGEROUS_FS = _re_i(
    r"\bsetcap\s+(?:[\"'])?"
    r"(?:[a-z_,]{0,80},)?"
    r"cap_(?:sys_admin|sys_module|sys_rawio|dac_read_search|dac_override"
    r"|net_admin|net_raw|chown|fowner|setuid|setgid|sys_ptrace)"
    r"(?:,[a-z_,]{0,80})?"
    r"\+(?:e?p|eip)"
    r"(?:[\"'])?\s+\S{1,400}"
)


# ---- P7 : prctl-dumpable-or-noprivs-regression --------------------------


_PRCTL_DUMPABLE_REGRESSION = _re(
    r"\bprctl\s*\(\s*PR_SET_DUMPABLE\s*,\s*1\b"
)

_PRCTL_NOPRIVS_RESET = _re(
    r"\bprctl\s*\(\s*PR_SET_NO_NEW_PRIVS\s*,\s*0\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="kernel-debugfs-world-writable",
        name="debugfs / sysfs hardening root chmoded world-writable",
        severity="CRITICAL",
        description=(
            "A script or Dockerfile sets ``/sys/kernel/debug`` "
            "(debugfs) or another kernel-internal sysfs root "
            "(``/sys/fs/cgroup``, ``/sys/kernel/security``) "
            "world-writable. debugfs exposes raw kernel state — "
            "kprobes, tracing, dynamic_debug control, kvm — and "
            "writes to it are kernel operations. World-writable "
            "lets any unprivileged process inside the container "
            "(or any local user on the host) toggle kernel "
            "primitives, dump kernel pointers, and exfiltrate "
            "kernel state. Suppress legitimate test harnesses "
            "via same-line ``# kspp-exempt`` marker."
        ),
        pattern=_DEBUGFS_CHMOD_WORLD_WRITABLE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="kmod-force-unsigned-flag",
        name="insmod / modprobe invoked with --force or --allow-unsigned",
        severity="CRITICAL",
        description=(
            "Distinct from Wave-19's ``kmod-unsigned-out-of-tree`` "
            "(which fires on the .ko path being outside the signed "
            "tree). This rule fires on the FLAG: any ``insmod`` or "
            "``modprobe`` invocation that carries ``--force``, "
            "``--force-modversion``, ``--force-vermagic``, or "
            "``--allow-unsigned``. Those flags explicitly tell the "
            "kernel to skip the signature / vermagic / modversion "
            "checks that prevent a foreign ``.ko`` from loading. "
            "An attacker who lands a shell uses these flags to "
            "ship a rootkit compiled against any kernel — bypassing "
            "the very protection the path-based rule was written "
            "for."
        ),
        pattern=_KMOD_FORCE_UNSIGNED_FLAG,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="kmod-sig-force-disabled-buildflag",
        name="Kernel built with MODULE_SIG_FORCE / MODULE_SIG disabled",
        severity="HIGH",
        description=(
            "A Makefile, ``make`` invocation, defconfig fragment, "
            "Kconfig override, or ``dpkg-buildpackage`` rule "
            "explicitly disables module-signature ENFORCEMENT at "
            "build time. Distinct from 'module loaded without "
            "signature' — this is the BUILD PRODUCT itself being "
            "incapable of enforcing signatures, which means every "
            "future module load on the resulting kernel skips "
            "signature verification. One commit ships a kernel "
            "that downstream users cannot defend."
        ),
        pattern=_KMOD_SIG_DISABLED_CONFIG,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="cap-sys-admin-retained-post-init",
        name="CAP_SYS_ADMIN raised in init but not dropped",
        severity="CRITICAL",
        description=(
            "A daemon raises ``CAP_SYS_ADMIN`` (or ``CAP_SYS_MODULE``, "
            "``CAP_SYS_RAWIO``, ``CAP_DAC_READ_SEARCH``, "
            "``CAP_NET_ADMIN``) during init — legitimate need to "
            "bind a privileged port, load a helper module, chroot, "
            "or mount tmpfs. The bug is NOT dropping it after the "
            "init step. Without a paired ``prctl(PR_CAPBSET_DROP, "
            "...)`` or ``cap_clear()`` / ``cap_set_flag(..., "
            "CAP_CLEAR)`` call inside the SAME function (or a "
            "registered cleanup handler), the capability persists "
            "for the entire process lifetime — so any later RCE in "
            "the daemon's request handler runs with kernel-level "
            "authority. Suppress legitimate single-purpose root "
            "daemons via same-line ``# cap-retained-intentional`` "
            "marker."
        ),
        pattern=_CAP_RAISE_ANCHOR,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="kernel-hardening-sysctl-disabled",
        name="KSPP hardening sysctl turned off (the off-switch six-pack)",
        severity="HIGH",
        description=(
            "A sysctl declaration explicitly disables a well-known "
            "kernel-hardening knob. Wave-19's "
            "``kernel-kallsyms-leaked`` already covers "
            "``kptr_restrict=0`` and ``perf_event_paranoid=0``; "
            "this rule covers the SIX OTHER knobs the KSPP / lynis "
            "/ CIS-DIL hardening guides treat as table stakes: "
            "``dmesg_restrict=0`` (kernel-pointer leak via dmesg), "
            "``randomize_va_space=0`` (ASLR off), "
            "``yama.ptrace_scope=0`` (any-PID ptrace), "
            "``unprivileged_bpf_disabled=0`` (pre-5.16 default), "
            "``fs.protected_hardlinks=0`` / "
            "``fs.protected_symlinks=0`` (symlink-race CVE class), "
            "``fs.suid_dumpable=2`` (setuid coredumps allowed), "
            "and ``kernel.sysrq=1|0xff|255`` (magic SysRq full "
            "mask). Suppress via same-line ``# kspp-exempt`` "
            "marker (re-using the Wave-19 token for consistency)."
        ),
        pattern=_HARDENING_SYSCTL_OFF_TO_ZERO,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="binary-setcap-sys-admin-on-fs",
        name="setcap grants CAP_SYS_ADMIN (or other dangerous cap) on fs binary",
        severity="CRITICAL",
        description=(
            "A ``setcap`` invocation in a Dockerfile, install "
            "script, or ``postinst`` puts ``CAP_SYS_ADMIN`` (or "
            "``CAP_SYS_MODULE``, ``CAP_DAC_READ_SEARCH``, "
            "``CAP_DAC_OVERRIDE``, ``CAP_NET_ADMIN``, "
            "``CAP_SYS_RAWIO``, ``CAP_SYS_PTRACE``, etc.) onto a "
            "binary's filesystem extended attribute. Distinct "
            "from Wave-19's ``ebpf-container-net-raw-bpf`` (which "
            "fires on container-spec ``cap_add``); this fires on "
            "the BINARY capability that survives reboot, persists "
            "per-file, and evades ``cap_add`` audits because the "
            "privilege is encoded in xattrs rather than the "
            "container spec. ``setcap cap_sys_admin+ep "
            "/usr/local/bin/agent`` makes every execution of that "
            "binary by ANY user equivalent to root. The regex "
            "deliberately EXCLUDES ``cap_net_bind_service`` (the "
            "textbook correct use)."
        ),
        pattern=_SETCAP_DANGEROUS_FS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="prctl-dumpable-or-noprivs-regression",
        name="prctl re-enables PR_SET_DUMPABLE or resets PR_SET_NO_NEW_PRIVS",
        severity="HIGH",
        description=(
            "Two distinct anti-hardening prctls. (a) "
            "``prctl(PR_SET_DUMPABLE, 1)`` re-enables core dumps "
            "for a process that previously disabled them; once "
            "dumpable=1 is restored, ANY subsequent crash writes a "
            "core file containing the process's full address "
            "space, including decrypted secrets, JWT signing keys, "
            "and session cookies. Common anti-pattern: a daemon "
            "disables dumpable during init, then a later code "
            "path resets it 'for debuggability' without realising "
            "the heap now contains secrets. (b) "
            "``prctl(PR_SET_NO_NEW_PRIVS, 0)`` — no_new_privs is a "
            "one-way latch, so the kernel rejects the call; but "
            "the attempt is a strong intent signal that the "
            "author wanted setuid execs to honour suid bits again. "
            "Suppress via same-line ``# kspp-exempt`` marker."
        ),
        pattern=_PRCTL_DUMPABLE_REGRESSION,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of line ``line_no`` (1-based) for opt-out
    marker checks."""
    parts = text.split("\n")
    if 1 <= line_no <= len(parts):
        return parts[line_no - 1]
    return ""


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to ``backward`` lines preceding ``line_no`` plus
    ``line_no`` itself plus the next ``forward`` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _has_kspp_exempt(text: str, line_no: int) -> bool:
    """True if the matched line carries an opt-out comment."""
    return _KSPP_EXEMPT_MARKER.search(_line_text(text, line_no)) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Each finding is emitted at most once per (rule_id, line, column).
    Stage-B filters for context-sensitive rules:

      * P4 (cap-sys-admin-retained-post-init) — anchor on the raise
        primitive; suppress if a paired drop primitive
        (``PR_CAPBSET_DROP`` or ``cap_clear``) appears within a
        1500-character window (heuristic for "same function").
      * P5 (kernel-hardening-sysctl-disabled) — emits a separate
        match for the suid_dumpable=2 form and the sysrq full-mask
        form on top of the six-zero-knobs form. Same rule id.

    All rules honour same-line ``# kspp-exempt`` /
    ``# kernel-debugfs-allow`` / ``# kmod-force-allow`` /
    ``# cap-retained-intentional`` opt-out markers.

    Findings are sorted by (line, column, rule_id) for deterministic
    output.
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        if _has_kspp_exempt(text, line):
            return
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

    # ---- P1 : kernel-debugfs-world-writable ----
    rule_p1 = rule_by_id["kernel-debugfs-world-writable"]
    for m in _DEBUGFS_CHMOD_WORLD_WRITABLE.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : kmod-force-unsigned-flag ----
    rule_p2 = rule_by_id["kmod-force-unsigned-flag"]
    for m in _KMOD_FORCE_UNSIGNED_FLAG.finditer(text):
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : kmod-sig-force-disabled-buildflag ----
    # Three regex shapes feeding one rule id.
    rule_p3 = rule_by_id["kmod-sig-force-disabled-buildflag"]
    for pat in (_KMOD_SIG_DISABLED_CONFIG, _KMOD_SIG_DISABLED_CFLAG, _KMOD_SIG_DISABLED_NOTSET):
        for m in pat.finditer(text):
            _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : cap-sys-admin-retained-post-init ----
    # Pair-detector: emit only when no drop primitive lives within ~1500
    # characters of the raise. The character window approximates "same
    # function body" without parsing — same heuristic Wave-19 uses for
    # ``_scan_devmem``.
    rule_p4 = rule_by_id["cap-sys-admin-retained-post-init"]
    for m in _CAP_RAISE_ANCHOR.finditer(text):
        start = max(0, m.start() - 1500)
        end = min(len(text), m.end() + 1500)
        window = text[start:end]
        if _CAP_DROP_PAIR.search(window) is not None:
            continue
        _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : kernel-hardening-sysctl-disabled ----
    rule_p5 = rule_by_id["kernel-hardening-sysctl-disabled"]
    for pat in (
        _HARDENING_SYSCTL_OFF_TO_ZERO,
        _HARDENING_SYSCTL_SUID_DUMPABLE_2,
        _HARDENING_SYSCTL_SYSRQ_FULL,
    ):
        for m in pat.finditer(text):
            _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : binary-setcap-sys-admin-on-fs ----
    rule_p6 = rule_by_id["binary-setcap-sys-admin-on-fs"]
    for m in _SETCAP_DANGEROUS_FS.finditer(text):
        _emit(rule_p6, m.start(), m.group(0))

    # ---- P7 : prctl-dumpable-or-noprivs-regression ----
    # Two shapes feeding one rule id.
    rule_p7 = rule_by_id["prctl-dumpable-or-noprivs-regression"]
    for pat in (_PRCTL_DUMPABLE_REGRESSION, _PRCTL_NOPRIVS_RESET):
        for m in pat.finditer(text):
            _emit(rule_p7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
