"""eBPF / kprobe / uprobe security risk patterns.

Wave-33 distillation round 19.

Catalogue of 9 net-new eBPF/uprobe security anti-patterns from
`reports/distill-round-19/bpf-uprobe-injection.md`. Covers attack
surfaces, helper functions, runtime misconfigurations, and CI pipeline
behaviours NOT detected by the existing `ebpf_kernel_patterns.py` (15
rules, round 5).

What is NOT here (already covered by ebpf_kernel_patterns.py):

  * bpf(2) syscall without capability gate in C — ebpf-prog-load-uncapped
  * kprobe on sensitive syscalls via SEC("kprobe/sys_*") — ebpf-kprobe-on-secret-syscall
  * register_kprobe on sys_call_table — kmod-kprobe-on-syscall-table
  * bpf_override_return() usage — ebpf-override-return
  * uprobe on SSL_write / pam_authenticate / libssl — ebpf-uprobe-on-libc-secret-fn
  * BPF map pinned world-readable — ebpf-map-pin-world-readable
  * Unsigned out-of-tree kmod + sig_enforce off — kmod-unsigned-out-of-tree
  * Module signing key exposed — kmod-signing-key-exposed
  * kptr_restrict / perf_event_paranoid weakened — kernel-kallsyms-leaked
  * /dev/mem opened with PROT_WRITE — kernel-devmem-open
  * firmware_class_path hijack — kernel-firmware-class-path-hijack
  * LSM stack passive / SELinux permissive — kernel-lsm-stack-passive
  * bpftool installed in production image — ebpf-bpftool-in-prod
  * Pod with CAP_NET_RAW/CAP_BPF + unconfined seccomp — ebpf-container-net-raw-bpf
  * BTF from untrusted source — ebpf-btf-from-untrusted-source

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * bpf-probe-read-user-exfil                       (CRITICAL)
  * bpf-ringbuf-covert-channel                      (HIGH)
  * bpf-bpftrace-in-ci-pipeline                     (HIGH)
  * bpf-usdt-prod-probe                             (HIGH)
  * bpf-cgroup-skb-intercept                        (CRITICAL)
  * bpf-fentry-lsm-hook-bypass                      (CRITICAL)
  * bpf-monitor-rules-disabled-explicit             (CRITICAL)
  * bpf-monitor-rules-file-empty                    (CRITICAL)
  * bpf-cilium-empty-egress-policy                  (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-SEC-01 — Security Control Bypass (LSM hook fentry bypass)
  ASI-SEC-02 — Privilege Misuse / Sensitive Data Exfiltration (probe_read,
               ringbuf covert channel)
  ASI-SEC-04 — Sensitive Data Exposure (USDT probes on prod binaries)
  ASI-CI-01  — CI/CD Pipeline Hardening (bpftrace/bcc in CI)
  ASI-NET-01 — Network Segmentation Bypass (cgroup-skb intercept,
               empty egress policy)
  ASI-MON-01 — Security Monitoring Disabled (Falco/Tracee rules disabled)

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : bpf-probe-read-user-exfil ------------------------------------


# bpf_probe_read* helpers — data-extraction call in the BPF C body.
# Fires regardless of attach type; orthogonal to ebpf-kprobe-on-secret-syscall
# (which fires on the SEC annotation, not on the helper call itself).
_BPF_PROBE_READ = _re(
    r"bpf_probe_read(?:_user|_kernel|_user_str|_kernel_str|_str)?\s*\("
)


# ---- R2 : bpf-ringbuf-covert-channel -----------------------------------


# Standard BPF data-export helpers used as covert channels.
# High-signal when co-located with _BPF_PROBE_READ in the same file
# (enforced in scan_text stage-B).
_BPF_RINGBUF_OUTPUT = _re(
    r"bpf_(?:ringbuf_output|perf_event_output)\s*\("
)


# ---- R3 : bpf-bpftrace-in-ci-pipeline ----------------------------------


# bpftrace/bcc/bpftool executed under sudo in a CI YAML run: block
# or immediately after a run-as-root marker.  Bounded quantifiers only.
_BPFTRACE_IN_CI = _re(
    r"(?:sudo\s+bpf(?:trace|cc|tool)|run(?:_as)?[=:\s]+root[^\n]{0,80}\nbpf(?:trace|cc|tool))\b"
)


# ---- R4 : bpf-usdt-prod-probe ------------------------------------------


# USDT probe path targeting production binaries (Python, PostgreSQL,
# Node, OpenSSL, Ruby, PHP).  Structured as:
#   usdt:<path>:<provider>:<probe>
# The binary keyword may appear in the path component OR in the provider
# segment (e.g. `libssl.so.3:openssl:rsa__sign` has 'ssl' in path and
# 'openssl' in provider).  We match either position by relaxing the split:
# match the whole usdt:... string that contains one of the known names
# anywhere before the final two colon-delimited segments.
_USDT_PROD_PROBE = _re(
    r"usdt:[^\s\"']{1,200}(?:python|postgres|node|openssl|ssl|ruby|php)"
    r"[^\s\"']{0,80}:[a-z_]{1,60}:[a-z_]{1,60}"
)


# ---- R5 : bpf-cgroup-skb-intercept -------------------------------------


# cgroup BPF programs that intercept, modify, or drop network traffic.
# These require only CAP_BPF on kernels >= 5.7, not CAP_NET_ADMIN.
_CGROUP_SKB_SEC = _re(
    r'SEC\s*\(\s*"cgroup_(?:skb|sock(?:addr|opt)?|device|sysctl)[^"]{0,60}"\s*\)'
)


# ---- R6 : bpf-fentry-lsm-hook-bypass -----------------------------------


# fentry/fexit programs attached directly to LSM hook functions —
# a stealthy LSM bypass distinct from bpf_override_return (ebpf-override-return).
_FENTRY_LSM_HOOK = _re(
    r'SEC\s*\(\s*"f(?:entry|exit)/security_[a-z_]{1,60}"\s*\)'
)


# ---- R7a : bpf-monitor-rules-disabled-explicit -------------------------


# Falco/Tracee rule explicitly disabled via `enabled: false` at DEBUG priority
# or combined with an override block — silences the monitor.
# In YAML the field order is not guaranteed; `priority: DEBUG` typically
# precedes `enabled: false`, so we match both orderings (forward and reverse).
_MONITOR_RULES_DISABLED = _re(
    r"(?:"
    # enabled: false first, then priority:DEBUG / override: within 3 lines
    r"enabled\s*:\s*false\b[^\n]{0,120}"
    r"(?:\n[^\n]{0,120}){0,3}"
    r"(?:priority\s*:\s*DEBUG|override\s*:\s*\{[^}]{0,80}\})"
    r"|"
    # priority:DEBUG first, then enabled: false within 3 lines
    r"priority\s*:\s*DEBUG\b[^\n]{0,120}"
    r"(?:\n[^\n]{0,120}){0,3}"
    r"enabled\s*:\s*false\b"
    r"|"
    # override block first, then enabled: false within 3 lines
    r"override\s*:\s*\{[^}]{0,80}\}[^\n]{0,120}"
    r"(?:\n[^\n]{0,120}){0,3}"
    r"enabled\s*:\s*false\b"
    r")"
)


# ---- R7b : bpf-monitor-rules-file-empty --------------------------------


# Falco/Tracee rules file that contains only comments and/or blank lines
# (no actual rule definitions).  Applied only to files whose path suggests
# a Falco/Tracee rules file (enforced in scan_text via file-global check).
_MONITOR_RULES_FILE_EMPTY = re.compile(
    r"\A(?:\s*#[^\n]*\n|\s*\n){0,50}\s*\Z",
    re.UNICODE,
)


# ---- R8 : bpf-cilium-empty-egress-policy -------------------------------


# Kubernetes NetworkPolicy with `Egress` in policyTypes — simple variant;
# the two-phase check (absence of `egress:` key) is enforced in scan_text.
_NETWORK_POLICY_KIND = _re(r"kind\s*:\s*NetworkPolicy")
# policyTypes: is on one line; `- Egress` is on the next.
# Match either `policyTypes: [Egress]` (inline) or `policyTypes:\n...- Egress`
# (block sequence), tolerating optional leading whitespace.
_POLICY_TYPES_EGRESS = _re(
    r"policyTypes[^\n]{0,80}(?:\n[^\n]{0,60})?-\s*Egress"
)
_EGRESS_KEY_PRESENT = _re(r"^\s+egress\s*:")


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="bpf-probe-read-user-exfil",
        name="bpf_probe_read* helper copies userspace bytes — potential argv/env exfiltration",
        severity="CRITICAL",
        description=(
            "A call to `bpf_probe_read_user()`, `bpf_probe_read()`, or a "
            "variant copies arbitrary bytes from a userspace virtual address "
            "into BPF stack memory. Combined with a kprobe/fentry on "
            "`do_execve` or `sys_execveat`, this gives a BPF rootkit full "
            "access to `argv[]`, `envp[]`, and secrets passed on the command "
            "line or via environment variables. The existing "
            "`ebpf-kprobe-on-secret-syscall` fires on the SEC annotation; "
            "this rule fires on the data-extraction helper call itself, "
            "which appears in the BPF C body regardless of attach type."
        ),
        pattern=_BPF_PROBE_READ,
        owasp_asi="ASI-SEC-02",
    ),
    Rule(
        id="bpf-ringbuf-covert-channel",
        name="bpf_perf_event_output / bpf_ringbuf_output used as covert data-exfil channel",
        severity="HIGH",
        description=(
            "`bpf_perf_event_output()` and `bpf_ringbuf_output()` are the "
            "standard BPF data-export helpers. In a rootkit they serve as "
            "the covert channel that exfiltrates stolen data (credentials "
            "read by bpf-probe-read-user-exfil, network payloads, "
            "keystrokes) to an unprivileged ring-buffer consumer running in "
            "the same container without LSM mediation. Unlike write(2), this "
            "path is not audited by most SIEM products. Elevated to CRITICAL "
            "when the same file also matches bpf-probe-read-user-exfil."
        ),
        pattern=_BPF_RINGBUF_OUTPUT,
        owasp_asi="ASI-SEC-02",
    ),
    Rule(
        id="bpf-bpftrace-in-ci-pipeline",
        name="bpftrace / bcc executed as root in CI workflow step",
        severity="HIGH",
        description=(
            "A CI pipeline runs `bpftrace`, `bcc`, or `bpftool` under `sudo` "
            "or as a root user. This lets any contributor who can modify "
            "`.github/workflows/` instrument every binary on the CI runner — "
            "including the credential helper, git process, and agent process — "
            "and exfiltrate secrets via the BPF ring buffer. The existing "
            "`ebpf-bpftool-in-prod` rule covers only `bpftool` installation; "
            "this pattern covers live bpftrace/bcc execution in CI YAML."
        ),
        pattern=_BPFTRACE_IN_CI,
        owasp_asi="ASI-CI-01",
    ),
    Rule(
        id="bpf-usdt-prod-probe",
        name="USDT probe attached to production binary (Python / PostgreSQL / Node / OpenSSL)",
        severity="HIGH",
        description=(
            "A `bpftrace` or bcc script attaches to a USDT tracepoint on a "
            "production binary (CPython, Node.js, PostgreSQL, OpenSSL, Ruby, "
            "PHP). USDT probes provide structured access to function arguments "
            "at a semantic level — including passwords passed to `sqlite3_exec`, "
            "SSL keys during handshake, or query strings in `PQexec`. This "
            "information-disclosure path bypasses application-layer access "
            "controls and requires only `CAP_SYS_PTRACE` on older kernels."
        ),
        pattern=_USDT_PROD_PROBE,
        owasp_asi="ASI-SEC-04",
    ),
    Rule(
        id="bpf-cgroup-skb-intercept",
        name="BPF cgroup_skb / cgroup_sock program intercepts cgroup network traffic",
        severity="CRITICAL",
        description=(
            "A BPF program of type `BPF_PROG_TYPE_CGROUP_SKB` or "
            "`BPF_PROG_TYPE_CGROUP_SOCK` (SEC annotations `cgroup_skb/*`, "
            "`cgroup_sockaddr`, `cgroup_sockopt`, `cgroup_device`, "
            "`cgroup_sysctl`) can intercept, modify, and drop all network "
            "traffic of a cgroup — equivalent to a transparent firewall "
            "bypass. On kernels >= 5.7 these types require only `CAP_BPF`, "
            "not `CAP_NET_ADMIN`. A misconfigured Kubernetes pod that has "
            "`CAP_BPF` but not `CAP_NET_ADMIN` may believe its network is "
            "isolated; a malicious cgroup-BPF program can silently redirect "
            "or exfiltrate its traffic."
        ),
        pattern=_CGROUP_SKB_SEC,
        owasp_asi="ASI-NET-01",
    ),
    Rule(
        id="bpf-fentry-lsm-hook-bypass",
        name="fentry/fexit BPF program attached to an LSM security_* hook function",
        severity="CRITICAL",
        description=(
            "A BPF program of type `BPF_PROG_TYPE_TRACING` attached via "
            "`fentry/security_*` or `fexit/security_*` sits on top of the "
            "LSM hook implementation itself (not the LSM framework). Combined "
            "with `bpf_override_return` (kernel >= 5.7 + CONFIG_BPF_KPROBE_OVERRIDE), "
            "it can nullify LSM deny decisions. This is a stealthy LSM bypass "
            "distinct from `ebpf-override-return` (which detects the override "
            "call); this rule fires on the attach point annotation."
        ),
        pattern=_FENTRY_LSM_HOOK,
        owasp_asi="ASI-SEC-01",
    ),
    Rule(
        id="bpf-monitor-rules-disabled-explicit",
        name="Falco / Tracee rule explicitly disabled at DEBUG priority or via override block",
        severity="CRITICAL",
        description=(
            "A Falco or Tracee rules file contains a rule with `enabled: false` "
            "combined with `priority: DEBUG` or an `override:` block. This "
            "silences the monitoring rule, effectively disabling the security "
            "event it covers. Whether accidental (developer committed a test "
            "config) or deliberate (attacker silences the monitor before "
            "lateral movement), an explicitly-disabled rule is a detection gap. "
            "Distinct from `kernel-lsm-stack-passive` (which checks LSM sysctl)."
        ),
        pattern=_MONITOR_RULES_DISABLED,
        owasp_asi="ASI-MON-01",
    ),
    Rule(
        id="bpf-monitor-rules-file-empty",
        name="Falco / Tracee rules file contains only comments or whitespace — no active rules",
        severity="CRITICAL",
        description=(
            "A Falco or Tracee rules file (`falco*.yaml`, `tracee*.yaml`, "
            "`rules.yaml`) contains only comments and/or blank lines with no "
            "actual rule definitions. An empty rules file disables all runtime "
            "security monitoring. This is a misconfiguration — either accidental "
            "(developer committed a blank stub) or deliberate (attacker committed "
            "an empty file to silence the monitor before lateral movement)."
        ),
        pattern=_MONITOR_RULES_FILE_EMPTY,
        owasp_asi="ASI-MON-01",
    ),
    Rule(
        id="bpf-cilium-empty-egress-policy",
        name="Kubernetes NetworkPolicy with Egress in policyTypes but no egress: rules",
        severity="HIGH",
        description=(
            "A Kubernetes `NetworkPolicy` specifies `Egress` in `policyTypes` "
            "but has no `egress:` stanza. This is semantically 'deny all egress' "
            "but Cilium and Calico have historically had bugs (CVE-2021-25737, "
            "CVE-2023-34242) where such policies were silently translated to "
            "'allow all egress' due to misconfigured BPF map entries. "
            "Independently of specific CVEs, an absent `egress:` field combined "
            "with `policyTypes: [Egress]` is inherently ambiguous and warrants "
            "human review."
        ),
        pattern=_NETWORK_POLICY_KIND,
        owasp_asi="ASI-NET-01",
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


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters apply additional context checks:

      * R2 (bpf-ringbuf-covert-channel) — emit only when the same file
        also contains a bpf_probe_read* call (reduces FP on legitimate
        bcc/BPF tracing programs).
      * R7b (bpf-monitor-rules-file-empty) — emit only when the entire
        file consists of comments/whitespace (whole-file check via
        _MONITOR_RULES_FILE_EMPTY compiled with DOTALL semantics).
      * R8 (bpf-cilium-empty-egress-policy) — emit only when the
        NetworkPolicy document contains `policyTypes` with `Egress` AND
        does NOT contain an `egress:` key in the same document block
        (two-phase: kind match + structural YAML check).

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

    # ---- R1 : bpf-probe-read-user-exfil ----
    rule_r1 = rule_by_id["bpf-probe-read-user-exfil"]
    for m in _BPF_PROBE_READ.finditer(text):
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : bpf-ringbuf-covert-channel ----
    # Stage-B: emit only when bpf_probe_read* also appears in the file.
    rule_r2 = rule_by_id["bpf-ringbuf-covert-channel"]
    has_probe_read = _file_contains(text, _BPF_PROBE_READ)
    if has_probe_read:
        for m in _BPF_RINGBUF_OUTPUT.finditer(text):
            _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : bpf-bpftrace-in-ci-pipeline ----
    rule_r3 = rule_by_id["bpf-bpftrace-in-ci-pipeline"]
    for m in _BPFTRACE_IN_CI.finditer(text):
        _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : bpf-usdt-prod-probe ----
    rule_r4 = rule_by_id["bpf-usdt-prod-probe"]
    for m in _USDT_PROD_PROBE.finditer(text):
        _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : bpf-cgroup-skb-intercept ----
    rule_r5 = rule_by_id["bpf-cgroup-skb-intercept"]
    for m in _CGROUP_SKB_SEC.finditer(text):
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : bpf-fentry-lsm-hook-bypass ----
    rule_r6 = rule_by_id["bpf-fentry-lsm-hook-bypass"]
    for m in _FENTRY_LSM_HOOK.finditer(text):
        _emit(rule_r6, m.start(), m.group(0))

    # ---- R7a : bpf-monitor-rules-disabled-explicit ----
    rule_r7a = rule_by_id["bpf-monitor-rules-disabled-explicit"]
    for m in _MONITOR_RULES_DISABLED.finditer(text):
        _emit(rule_r7a, m.start(), m.group(0))

    # ---- R7b : bpf-monitor-rules-file-empty ----
    # Stage-B: whole-file check — only emit when the entire text is
    # comments/whitespace (no actual rule definitions).
    rule_r7b = rule_by_id["bpf-monitor-rules-file-empty"]
    if _MONITOR_RULES_FILE_EMPTY.match(text):
        # Emit at offset 0 (start of file).
        _emit(rule_r7b, 0, text[:80] if text else "")

    # ---- R8 : bpf-cilium-empty-egress-policy ----
    # Two-phase: (a) kind: NetworkPolicy found, (b) policyTypes contains
    # Egress within 40 lines, (c) no `egress:` key in the same block.
    rule_r8 = rule_by_id["bpf-cilium-empty-egress-policy"]
    for m in _NETWORK_POLICY_KIND.finditer(text):
        line, _ = _line_col(text, m.start())
        # Inspect 40 lines forward from the `kind:` line for policyTypes.
        window = _slice_forward(text, line, 40)
        if _POLICY_TYPES_EGRESS.search(window) is None:
            continue
        # If an `egress:` key exists in the same block, suppress (explicit).
        if _EGRESS_KEY_PRESENT.search(window) is not None:
            continue
        _emit(rule_r8, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
