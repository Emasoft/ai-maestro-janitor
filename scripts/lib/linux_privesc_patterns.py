"""Linux user-space privilege escalation patterns.

Wave-25 distillation round 11 — Linux USER-SPACE privesc primitives.

Catalogue of 7 user-space privesc anti-patterns distilled in
``reports/distill-round-11/linux-privesc.md``. Targets the surface
that Wave-23 ``scripts/lib/linux_kernel_patterns.py`` does NOT cover:
sudoers ``NOPASSWD: ALL`` injection, SUID bit on attacker-dropped
binary/script, polkit ``.rules`` permissive or world-writable, Yama
LSM ``ptrace_scope`` reset, ``setcap`` of lesser caps
(``cap_net_raw``, ``cap_dac_override``, ``cap_setuid``) on
user-installed binaries, ``/etc/shadow`` read / ``/etc/passwd``
write, and PAM ``pam_permit.so`` / ``nullok`` loosening.

What is NOT here (already shipped by Wave-23, DO NOT duplicate):

  * ``CAP_SYS_ADMIN`` retention — ``cap-sys-admin-retained-post-init``.
  * ``setcap cap_sys_admin+ep`` on fs binary —
    ``binary-setcap-sys-admin-on-fs`` (this rule covers the OTHER
    lethal caps Wave-23 deliberately omits).
  * KSPP hardening sysctls — ``kernel-hardening-sysctl-disabled``
    (this rule zooms in on ``yama.ptrace_scope`` specifically and
    on runtime / prctl setters that Wave-23 does not catch).
  * debugfs world-writable — ``kernel-debugfs-world-writable``.
  * Module-sig disabled at build — ``kmod-sig-force-disabled-buildflag``.
  * ``insmod`` / ``modprobe`` force flags — ``kmod-force-unsigned-flag``.
  * ``prctl(PR_SET_DUMPABLE, 1)`` — ``prctl-dumpable-or-noprivs-regression``
    (this rule covers ``prctl(PR_SET_PTRACER_ANY)`` which is a
    distinct primitive Wave-23 does not match).

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * linux-privesc-sudoers-nopasswd-all                      (CRITICAL)
  * linux-privesc-suid-bit-on-dropped-binary                (HIGH)
  * linux-privesc-polkit-permissive-rule                    (CRITICAL)
  * linux-privesc-yama-ptrace-scope-reset                   (HIGH)
  * linux-privesc-setcap-userspace-dangerous-cap            (HIGH)
  * linux-privesc-shadow-read-or-passwd-write               (CRITICAL)
  * linux-privesc-pam-permit-or-nullok                      (CRITICAL)

Public surface (mirrors ``chat_bot_patterns`` / ``linux_kernel_patterns``):

  * ``Rule(id, name, severity, description, pattern, owasp_asi)`` — frozen
    NamedTuple with the pre-compiled pattern.
  * ``RULES`` — ordered tuple of every rule.
  * ``scan_text(text) -> list[Finding]``.
  * ``Finding(rule_id, line, column, matched_text, severity, description,
    owasp_asi)`` — frozen NamedTuple, same shape as
    ``webhook_signature_patterns.Finding``.

OWASP ASI mapping used:
  ASI-02 — Sensitive info disclosure (``/etc/shadow`` read, credential
                                       harvest).
  ASI-03 — Identity & privilege abuse (sudoers, SUID, polkit, ptrace
                                        scope, dangerous caps,
                                        ``/etc/passwd`` write, PAM
                                        bypass).

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
    because some Linux identifiers are case-sensitive (e.g. PAM
    module names). Mirror of ``linux_kernel_patterns._re``."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_i(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE for shell shapes
    where case is incidental."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# Shared opt-out marker. Reuse the Wave-23 ``# kspp-exempt`` token so a
# single line-comment opt-out works across every Linux-hardening rule;
# also accept rule-specific markers for clarity.
_PRIVESC_EXEMPT_MARKER = _re_i(
    r"#\s*(?:kspp-exempt|privesc-allow|sudoers-allow|suid-intentional"
    r"|polkit-allow|ptrace-dev|setcap-intentional|pam-intentional"
    r"|shadow-audit|passwd-admin)\b"
)


# ---- L1 : linux-privesc-sudoers-nopasswd-all ----------------------------


# Match the canonical sudoers ``NOPASSWD: ALL`` content line. The
# spec/principal can be ``user``, ``%group``, ``+netgroup``, or a User_Alias
# token. NOPASSWD is case-insensitive in real droppers (Shai-Hulud uses
# uppercase; ansible variants use mixed case). The runas spec
# ``(ALL[:ALL])`` is wrapped in literal parens; the trailing ``ALL`` is
# the command list.
_SUDOERS_NOPASSWD_ALL_LINE = _re_i(
    r"(?:^|[\n;&|])\s*[%+]?[A-Za-z_][\w.\-]{0,40}\s+ALL\s*=\s*"
    r"\([A-Za-z0-9_:,\-\s]{1,40}\)\s*NOPASSWD\s*:\s*ALL\b"
)

# Match a write/append/tee operation that targets ``/etc/sudoers`` or
# ``/etc/sudoers.d/<file>``. We do NOT require ``NOPASSWD`` in this
# shape because the write target alone is the strong signal — the
# content variant is detected by the line above.
_SUDOERS_WRITE_TARGET = _re_i(
    r"(?:>>?\s*|\btee\s+(?:-a\s+)?|\bopen\s*\(\s*[\"'])"
    r"/etc/sudoers(?:\.d/[A-Za-z0-9_.\-]{1,80})?\b"
)


# ---- L2 : linux-privesc-suid-bit-on-dropped-binary ----------------------


# ``chmod`` with a SUID-setting mode (numeric ``4xxx`` / ``6xxx`` /
# symbolic ``u+s``). Also catch ``S_ISUID`` (Python ``stat``,
# C/Go syscall numeric flag) and ``setuid(0)`` calls. The target path
# carve-out (distro-canonical ``/usr/bin/{ping,passwd,...}``) is
# applied at the scanner layer.
_SUID_CHMOD_OR_FLAG = _re_i(
    # chmod 4755 / 06755 / 4111 / 5755 / 6755 / 7755 — numeric mode
    # whose leading non-zero digit carries the SUID bit
    # (4 = setuid, 5 = setuid|sticky, 6 = setuid|setgid, 7 = all three).
    r"\bchmod\s+(?:-R\s+)?(?:0?[4-7][0-7]{3})\b"
    r"|"
    # chmod u+s / chmod +s — symbolic SUID
    r"\bchmod\s+(?:-R\s+)?[ugo]*\+s\b"
    r"|"
    # Python: stat.S_ISUID flag or S_ISUID constant
    r"\bstat\.S_ISUID\b"
    r"|"
    r"\bS_ISUID\b"
    r"|"
    # Go / C / Python numeric setuid mode constant: 0o4xxx with leading
    # 4 (setuid), 5 (setuid|sticky), 6 (setuid|setgid), or 7. Requires
    # the explicit Python ``0o`` / Go ``0`` octal prefix so we do not
    # match a stray ``4755`` decimal literal.
    r"\b0[oO]?[4567][0-7]{3}\b"
    r"|"
    # explicit setuid(0) — drops to UID 0 from a SUID-root binary
    r"\bsetuid\s*\(\s*0\s*\)"
)

# Distro-canonical SUID paths that legitimately ship setuid bits.
# A match on this list at the SAME line as the chmod suppresses.
_SUID_CANONICAL_PATH = _re_i(
    r"/(?:usr/)?(?:s?bin)/(?:ping6?|passwd|chsh|chfn|su|sudo|mount"
    r"|umount|newgrp|gpasswd|chage|sg|expiry|crontab|at|pkexec|fusermount3?"
    r"|ssh-agent|wall|write)\b"
)


# ---- L3 : linux-privesc-polkit-permissive-rule --------------------------


# Three shapes:
#   (a) ``polkit.Result.YES`` returned UNCONDITIONALLY (no ``if``
#       guard on the SAME line — guarded YES is the normal pattern
#       for distro packaging).
#   (b) ``chmod`` with world-writable mode (``666``/``777``/``o+w``)
#       targeting a polkit rules / pkla / policy file.
#   (c) ``install -m 0666`` / ``install -m 0777`` of an attacker
#       file into the polkit rules directory.
_POLKIT_RESULT_YES_UNGUARDED = _re(
    r"^\s*return\s+polkit\.Result\.YES\s*;?\s*$"
)

_POLKIT_RULES_FILE_WORLD_WRITABLE = _re_i(
    # Mode forms that include world-write (last digit even+2, i.e. 2/3/6/7).
    # Numeric: 0?XYZ where Z ∈ {2,3,6,7}. Symbolic: o+w / a+w / ugo+w.
    r"\bchmod\s+(?:-R\s+)?"
    r"(?:0?[0-7]{2}[2367]|[ugoa]+\+w)"
    r"\s+(?:-R\s+)?"
    r"/(?:etc|usr/share)/polkit-1/[A-Za-z0-9_./\-]{1,200}"
)

_POLKIT_INSTALL_WORLD_WRITABLE = _re_i(
    r"\binstall\s+(?:-[A-Za-z]\s+\S+\s+)*-m\s+0?(?:666|777)\s+\S+\s+"
    r"/(?:etc|usr/share)/polkit-1/(?:rules\.d|localauthority"
    r"(?:\.d)?|actions)/[A-Za-z0-9_./\-]{1,200}"
)


# ---- L4 : linux-privesc-yama-ptrace-scope-reset -------------------------


# Three shapes:
#   (a) Write of ``0`` to ``/proc/sys/kernel/yama/ptrace_scope`` —
#       runtime toggle via shell or ``open()``.
#   (b) ``sysctl -w kernel.yama.ptrace_scope=0`` — runtime sysctl.
#   (c) ``prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY)`` — per-process
#       opt-in that allows ANY pid to ptrace the calling process.
_YAMA_PROCFS_RESET = _re_i(
    # echo 0 > /proc/.../ptrace_scope  (shell redirect)
    r"\becho\s+0\b[^\n]{0,80}?>\s*/proc/sys/kernel/yama/ptrace_scope\b"
    r"|"
    # tee /proc/.../ptrace_scope  (with prior pipe of 0)
    r"\btee\s+(?:-a\s+)?/proc/sys/kernel/yama/ptrace_scope\b"
    r"|"
    # open("/proc/.../ptrace_scope", "w") / fopen(... "w") — programmatic write
    r"\b(?:open|fopen)\s*\(\s*[\"']/proc/sys/kernel/yama/ptrace_scope[\"']"
    r"\s*,\s*[\"'][aw][bt+]?[\"']"
    r"|"
    # plain Python idiom: open('/proc/.../ptrace_scope', 'w').write('0')
    r"\bopen\s*\(\s*[\"']/proc/sys/kernel/yama/ptrace_scope[\"']"
)

_YAMA_SYSCTL_RESET = _re_i(
    r"\bsysctl\s+(?:-w\s+)?kernel\.yama\.ptrace_scope\s*=\s*0\b"
    r"|"
    # sysctl.d file declaration
    r"^\s*kernel\.yama\.ptrace_scope\s*=\s*0\s*(?:#.*)?$"
)

_PRCTL_SET_PTRACER_ANY = _re(
    # prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, ...)
    r"\bprctl\s*\(\s*PR_SET_PTRACER\s*,\s*PR_SET_PTRACER_ANY\b"
    r"|"
    # syscall.Prctl(unix.PR_SET_PTRACER, ...) — go syscall raw, or
    # libc.prctl(...) ctypes wrappers
    r"\b(?:syscall|unix|libc)\.[Pp]rctl\s*\([^)]*PR_SET_PTRACER(?:_ANY)?\b"
)


# ---- L5 : linux-privesc-setcap-userspace-dangerous-cap ------------------


# ``setcap`` with one of the LESSER lethal caps (Wave-23 already
# covers ``cap_sys_admin``, ``cap_sys_module``, etc.). The caps here
# — ``cap_net_raw``, ``cap_dac_override``, ``cap_dac_read_search``,
# ``cap_setuid``, ``cap_setgid``, ``cap_chown``, ``cap_fowner`` —
# also enable a full privesc chain on attacker-controlled binaries.
# Distro-canonical paths (``/usr/bin/ping``, etc.) are filtered at
# the scanner layer.
_SETCAP_USERSPACE_DANGEROUS = _re_i(
    r"\bsetcap\s+(?:[\"'])?"
    r"(?:[a-z_,]{0,80},)?"
    r"cap_(?:net_raw|dac_override|dac_read_search|setuid|setgid|chown|fowner)"
    r"(?:,[a-z_,]{0,80})?"
    r"\+(?:e?p|eip)"
    r"(?:[\"'])?\s+\S{1,400}"
    r"|"
    # xattr direct: setxattr(p, "security.capability", ...)
    r"\bsetxattr\s*\(\s*[^,)]+,\s*[\"']security\.capability[\"']"
    r"|"
    # Python os.setxattr / Go syscall.Setxattr same target
    r"\bos\.setxattr\s*\(\s*[^,)]+,\s*[\"']security\.capability[\"']"
    r"|"
    r"\bsyscall\.Setxattr\s*\(\s*[^,)]+,\s*[\"']security\.capability[\"']"
)

# Distro-canonical paths that legitimately ship file capabilities.
# A match on this list at the SAME line as setcap suppresses.
_SETCAP_CANONICAL_PATH = _re_i(
    r"/(?:usr/(?:s?bin|libexec)|s?bin)/"
    r"(?:ping6?|mtr(?:-packet)?|traceroute6?|tcpdump|wireshark|dumpcap"
    r"|fping|arping|nmap|fusermount3?|systemd-resolved|pkexec)\b"
)


# ---- L6 : linux-privesc-shadow-read-or-passwd-write ---------------------


# /etc/shadow read OR /etc/passwd write. /etc/passwd is world-readable
# by design so a plain read is NOT flagged; only writes there.
# /etc/shadow is mode 0640 — even reads imply privesc-or-equivalent.
_SHADOW_READ = _re_i(
    # cat/less/head/tail/grep + /etc/shadow
    r"\b(?:cat|less|more|head|tail|grep|awk|sed|hashcat|john)\s+"
    r"(?:-[A-Za-z]+\s+)*[^|;&\n]*?/etc/shadow\b"
    r"|"
    # programmatic open of /etc/shadow for read
    r"\b(?:open|fopen|os\.open)\s*\(\s*[\"']/etc/shadow[\"']"
    r"|"
    # python idiom: open('/etc/shadow').read()
    r"\bopen\s*\(\s*[\"']/etc/shadow[\"']\s*\)\.read\b"
    r"|"
    # generic redirection FROM shadow
    r"<\s*/etc/shadow\b"
)

_PASSWD_WRITE = _re_i(
    # >> /etc/passwd or > /etc/passwd
    r"(?:>>?\s*|\btee\s+(?:-a\s+)?)/etc/passwd\b"
    r"|"
    # programmatic append/write of /etc/passwd
    r"\b(?:open|fopen)\s*\(\s*[\"']/etc/passwd[\"']\s*,\s*[\"'][aw][bt+]?[\"']"
    r"|"
    # chmod 666 /etc/passwd (write-prep)
    r"\bchmod\s+(?:-R\s+)?0?[26][26]6\s+/etc/passwd\b"
    r"|"
    # chmod 666 /etc/shadow (write-prep on the hash file itself)
    r"\bchmod\s+(?:-R\s+)?0?[26][26]6\s+/etc/shadow\b"
)


# ---- L7 : linux-privesc-pam-permit-or-nullok ----------------------------


# Three shapes:
#   (a) ``pam_permit.so`` inserted into a privesc-relevant PAM stack
#       (``sudo`` / ``su`` / ``login`` / ``sshd`` / ``system-auth`` /
#       ``common-auth`` / ``password-auth``).
#   (b) ``nullok`` modifier added to ``pam_unix.so`` in the same set
#       of files.
#   (c) Shell heredoc / sed that writes those constructs into the
#       PAM directory.
_PAM_PERMIT_IN_PRIVESC_STACK = _re(
    r"^\s*auth\s+(?:sufficient|required|requisite)\s+pam_permit\.so\b"
)

_PAM_NULLOK_ON_UNIX = _re(
    r"^\s*auth\s+(?:sufficient|required|requisite)\s+"
    r"pam_unix\.so[^\n]*\bnullok\b"
)

_PAM_WRITE_TO_PRIVESC_FILE = _re_i(
    r"(?:>>?\s*|\btee\s+(?:-a\s+)?|\bsed\s+-i\s+[^\n]{1,160}?)"
    r"/etc/pam\.d/(?:sudo|su|login|sshd|system-auth|common-auth"
    r"|password-auth)\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="linux-privesc-sudoers-nopasswd-all",
        name="sudoers NOPASSWD: ALL rule injection / drop-in file write",
        severity="CRITICAL",
        description=(
            "A dropper writes (or appends) a ``NOPASSWD: ALL`` rule "
            "into ``/etc/sudoers`` or a fragment under "
            "``/etc/sudoers.d/``. Effect: the named principal "
            "obtains password-less full root, persisting across "
            "reboots and invisible to ``last``/``who``. Real-world "
            "IOC: the Shai-Hulud / @antv npm worm literally writes "
            "``runner ALL=(ALL) NOPASSWD:ALL`` into CI sudoers. "
            "This rule fires on the CONTENT line shape (matches all "
            "four delivery vehicles: ``>``, ``>>``, ``tee``, "
            "in-process ``open()``) AND on any write/append/tee "
            "operation targeting a sudoers path. Suppress legitimate "
            "fixture/test/documentation cases via same-line "
            "``# sudoers-allow`` marker."
        ),
        pattern=_SUDOERS_NOPASSWD_ALL_LINE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="linux-privesc-suid-bit-on-dropped-binary",
        name="SUID bit (chmod 4xxx / u+s / S_ISUID / setuid(0)) on user-controlled binary",
        severity="HIGH",
        description=(
            "A script sets the setuid bit on a binary or script the "
            "attacker controls — ``chmod 4755 /tmp/...``, "
            "``chmod u+s /opt/dropped/x``, ``os.chmod(p, m | "
            "stat.S_ISUID)``, ``setuid(0)``. Any unprivileged "
            "caller subsequently executes the file as its owner — "
            "root, if the file was chowned to root first. The "
            "textbook Linux user-space privesc primitive (GTFOBins "
            "lists hundreds of standard binaries that pop a shell "
            "when SUID-tagged). Distro-canonical SUID paths "
            "(``/usr/bin/{ping,passwd,su,sudo,mount,...}``) are "
            "carved out at the scanner. Suppress legitimate "
            "package-manager re-application via same-line "
            "``# suid-intentional`` marker."
        ),
        pattern=_SUID_CHMOD_OR_FLAG,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="linux-privesc-polkit-permissive-rule",
        name="polkit .rules file made world-writable or returns Result.YES unconditionally",
        severity="CRITICAL",
        description=(
            "Polkit (PolicyKit) evaluates JavaScript rules in "
            "``/etc/polkit-1/rules.d/*.rules`` and "
            "``/usr/share/polkit-1/rules.d/*.rules`` to decide "
            "whether actions like ``org.freedesktop.systemd1."
            "manage-units``, ``pkexec``-launches, or USB-mount "
            "approvals require auth. A rule that returns "
            "``polkit.Result.YES`` unconditionally, OR an existing "
            "rule file that the attacker can modify in place "
            "because it was chmoded world-writable, is a permanent "
            "root grant. CVE-2021-3560 (pkexec) was the most famous "
            "polkit user-space privesc; this rule is the "
            "configuration-level parallel. Suppress legitimate "
            "distro-shipped rule files via same-line "
            "``# polkit-allow`` marker."
        ),
        pattern=_POLKIT_RULES_FILE_WORLD_WRITABLE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="linux-privesc-yama-ptrace-scope-reset",
        name="Yama LSM ptrace_scope reset to 0 (runtime, sysctl, or prctl PR_SET_PTRACER_ANY)",
        severity="HIGH",
        description=(
            "The Yama LSM restricts which processes can ``ptrace()`` "
            "which other processes. Default on most distros is "
            "``kernel.yama.ptrace_scope=1`` (restricted ptrace — "
            "only descendants). Setting it to 0 lets any process "
            "attach to any same-uid process — combined with a SUID "
            "binary or elevated-caps process, lets an attacker "
            "inject shellcode into a privileged process. Distinct "
            "from Wave-23's ``kernel-hardening-sysctl-disabled`` "
            "(which covers the KSPP six-pack at the sysctl.d declar"
            "ation level) — this rule zooms in on ``yama.ptrace_"
            "scope`` specifically and adds the RUNTIME write to "
            "``/proc/sys/kernel/yama/ptrace_scope`` plus "
            "``prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY)`` "
            "primitives Wave-23 does not match. Suppress dev/CI "
            "documentation via same-line ``# ptrace-dev`` marker."
        ),
        pattern=_YAMA_SYSCTL_RESET,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="linux-privesc-setcap-userspace-dangerous-cap",
        name="setcap grants cap_net_raw / cap_dac_override / cap_setuid (etc) on user binary",
        severity="HIGH",
        description=(
            "File capabilities are a finer-grained alternative to "
            "SUID. ``setcap cap_net_raw+ep ./tool`` lets ``tool`` "
            "open raw sockets without root; ``cap_dac_override+ep`` "
            "lets it bypass DAC file-permission checks (read any "
            "file); ``cap_setuid+ep`` lets it call ``setuid()`` to "
            "arbitrary UIDs. Wave-23's ``binary-setcap-sys-admin-"
            "on-fs`` already covers ``CAP_SYS_ADMIN`` (the new "
            "root) and friends; this rule covers the OTHER lethal "
            "caps Wave-23 deliberately does NOT match — "
            "``cap_net_raw``, ``cap_dac_override``, "
            "``cap_dac_read_search``, ``cap_setuid``, "
            "``cap_setgid``, ``cap_chown``, ``cap_fowner``. Also "
            "matches the ``security.capability`` xattr-direct form "
            "(``setxattr``/``os.setxattr``/``syscall.Setxattr``) "
            "that bypasses the ``setcap`` binary. Distro-canonical "
            "paths (``/usr/bin/ping``, ``/usr/sbin/tcpdump``, etc.) "
            "are carved out at the scanner. Suppress via same-line "
            "``# setcap-intentional`` marker."
        ),
        pattern=_SETCAP_USERSPACE_DANGEROUS,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="linux-privesc-shadow-read-or-passwd-write",
        name="/etc/shadow read OR /etc/passwd write (UID 0 user injection)",
        severity="CRITICAL",
        description=(
            "Two complementary primitives. (a) ``/etc/shadow`` "
            "(mode 0640, owner root:shadow) holds password hashes; "
            "reading it as non-root requires having already "
            "escalated. A successful read enables offline cracking "
            "against ``rockyou``-class wordlists. (b) ``/etc/"
            "passwd`` is world-readable but root-writable — "
            "appending an attacker-controlled UID 0 user "
            "(``backdoor::0:0:root:/root:/bin/bash``) hands out "
            "root on next ``su backdoor``. Both ``cat /etc/shadow`` "
            "and ``echo backdoor::0:0:... >> /etc/passwd`` are "
            "matched. Note: a plain read of ``/etc/passwd`` is NOT "
            "flagged (the file is world-readable by design); only "
            "writes there are. Suppress legitimate "
            "``useradd``/``vipw`` contexts via same-line "
            "``# passwd-admin`` / ``# shadow-audit`` markers."
        ),
        pattern=_PASSWD_WRITE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="linux-privesc-pam-permit-or-nullok",
        name="PAM stack loosened with pam_permit.so or pam_unix.so nullok in /etc/pam.d/{sudo,su,...}",
        severity="CRITICAL",
        description=(
            "PAM configuration files in ``/etc/pam.d/`` control "
            "authentication for ``sudo``, ``su``, ``login``, and "
            "``sshd``. Replacing the auth stack with "
            "``pam_permit.so`` (always succeeds) or adding the "
            "``nullok`` modifier to ``pam_unix.so`` (accept empty "
            "passwords) creates a passwordless root path that does "
            "NOT appear in sudoers and does NOT require a SUID "
            "flip — the AUTHENTICATION-LAYER companion to the "
            "sudoers-config attack. Defeats ``/var/log/auth.log`` "
            "audit (no password prompt entry). Single edit; "
            "persists. Matches three delivery vehicles: literal "
            "PAM stack lines, ``sed -i`` modifying a PAM file, "
            "and shell-redirection writes to a PAM file. Suppress "
            "legitimate cloud-image first-login PAM via same-line "
            "``# pam-intentional`` marker."
        ),
        pattern=_PAM_PERMIT_IN_PRIVESC_STACK,
        owasp_asi="ASI-03",
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


def _has_exempt_marker(text: str, line_no: int) -> bool:
    """True if the matched line carries an opt-out comment."""
    return _PRIVESC_EXEMPT_MARKER.search(_line_text(text, line_no)) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Each finding is emitted at most once per (rule_id, line, column).
    Stage-B filters for context-sensitive rules:

      * L2 (suid-bit-on-dropped-binary) — suppress when the same
        chmod line targets a distro-canonical SUID path
        (``/usr/bin/{ping,passwd,...}``).
      * L5 (setcap-userspace-dangerous-cap) — suppress when the
        same setcap line targets a distro-canonical net-tool path
        (``/usr/bin/ping``, ``/usr/sbin/tcpdump``, etc.).
      * L6 (shadow-read-or-passwd-write) — two regex shapes
        (``_SHADOW_READ``, ``_PASSWD_WRITE``) feed the same rule
        id.

    All rules honour same-line ``# kspp-exempt`` / ``# privesc-allow``
    / per-rule opt-out markers (``# sudoers-allow``,
    ``# suid-intentional``, ``# polkit-allow``, ``# ptrace-dev``,
    ``# setcap-intentional``, ``# pam-intentional``,
    ``# shadow-audit``, ``# passwd-admin``).

    Findings are sorted by (line, column, rule_id) for deterministic
    output.
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        if _has_exempt_marker(text, line):
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

    # ---- L1 : linux-privesc-sudoers-nopasswd-all ----
    # Two regex shapes feed one rule id: the NOPASSWD content line and
    # any write-target operation against /etc/sudoers[.d/*].
    rule_l1 = rule_by_id["linux-privesc-sudoers-nopasswd-all"]
    for pat in (_SUDOERS_NOPASSWD_ALL_LINE, _SUDOERS_WRITE_TARGET):
        for m in pat.finditer(text):
            _emit(rule_l1, m.start(), m.group(0))

    # ---- L2 : linux-privesc-suid-bit-on-dropped-binary ----
    # Carve out distro-canonical SUID paths that legitimately ship
    # with the bit set (ping, passwd, su, sudo, mount, ...).
    rule_l2 = rule_by_id["linux-privesc-suid-bit-on-dropped-binary"]
    for m in _SUID_CHMOD_OR_FLAG.finditer(text):
        line, _ = _line_col(text, m.start())
        line_str = _line_text(text, line)
        # Same-line canonical-path match → legitimate package mode.
        if _SUID_CANONICAL_PATH.search(line_str) is not None:
            continue
        _emit(rule_l2, m.start(), m.group(0))

    # ---- L3 : linux-privesc-polkit-permissive-rule ----
    # Three regex shapes feed one rule id: unguarded Result.YES,
    # world-writable chmod on a polkit path, and install -m 0666/0777
    # of an attacker rule.
    rule_l3 = rule_by_id["linux-privesc-polkit-permissive-rule"]
    for pat in (
        _POLKIT_RESULT_YES_UNGUARDED,
        _POLKIT_RULES_FILE_WORLD_WRITABLE,
        _POLKIT_INSTALL_WORLD_WRITABLE,
    ):
        for m in pat.finditer(text):
            _emit(rule_l3, m.start(), m.group(0))

    # ---- L4 : linux-privesc-yama-ptrace-scope-reset ----
    # Three regex shapes feed one rule id: procfs write, sysctl(.d)
    # reset to 0, and prctl(PR_SET_PTRACER_ANY).
    rule_l4 = rule_by_id["linux-privesc-yama-ptrace-scope-reset"]
    for pat in (
        _YAMA_PROCFS_RESET,
        _YAMA_SYSCTL_RESET,
        _PRCTL_SET_PTRACER_ANY,
    ):
        for m in pat.finditer(text):
            _emit(rule_l4, m.start(), m.group(0))

    # ---- L5 : linux-privesc-setcap-userspace-dangerous-cap ----
    # Carve out distro-canonical net-tool paths that legitimately
    # ship cap_net_raw+ep (ping, tcpdump, mtr, ...).
    rule_l5 = rule_by_id["linux-privesc-setcap-userspace-dangerous-cap"]
    for m in _SETCAP_USERSPACE_DANGEROUS.finditer(text):
        line, _ = _line_col(text, m.start())
        line_str = _line_text(text, line)
        if _SETCAP_CANONICAL_PATH.search(line_str) is not None:
            continue
        _emit(rule_l5, m.start(), m.group(0))

    # ---- L6 : linux-privesc-shadow-read-or-passwd-write ----
    # Two regex shapes feed one rule id: shadow READ and passwd WRITE.
    rule_l6 = rule_by_id["linux-privesc-shadow-read-or-passwd-write"]
    for pat in (_SHADOW_READ, _PASSWD_WRITE):
        for m in pat.finditer(text):
            _emit(rule_l6, m.start(), m.group(0))

    # ---- L7 : linux-privesc-pam-permit-or-nullok ----
    # Three regex shapes feed one rule id: pam_permit.so line,
    # pam_unix.so nullok line, and write to a privesc PAM file.
    rule_l7 = rule_by_id["linux-privesc-pam-permit-or-nullok"]
    for pat in (
        _PAM_PERMIT_IN_PRIVESC_STACK,
        _PAM_NULLOK_ON_UNIX,
        _PAM_WRITE_TO_PRIVESC_FILE,
    ):
        for m in pat.finditer(text):
            _emit(rule_l7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
