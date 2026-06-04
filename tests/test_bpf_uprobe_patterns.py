"""Tests for scripts/lib/bpf_uprobe_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 catalogue
(9 eBPF/uprobe/kprobe security anti-patterns not covered by the existing
ebpf_kernel_patterns.py). Each rule has at least two tests: one positive
exercising the canary and one negative exercising the carve-out or
context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import bpf_uprobe_patterns as bup  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs."""
    assert isinstance(bup.RULES, tuple)
    rule_ids = {r.id for r in bup.RULES}
    expected = {
        "bpf-probe-read-user-exfil",
        "bpf-ringbuf-covert-channel",
        "bpf-bpftrace-in-ci-pipeline",
        "bpf-usdt-prod-probe",
        "bpf-cgroup-skb-intercept",
        "bpf-fentry-lsm-hook-bypass",
        "bpf-monitor-rules-disabled-explicit",
        "bpf-monitor-rules-file-empty",
        "bpf-cilium-empty-egress-policy",
    }
    assert expected == rule_ids
    assert len(bup.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in bup.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = bup.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-SEC-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-SEC-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert bup.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — triggers R1 (probe_read)
        "bpf_probe_read_user(buf, sizeof(buf), ptr);\n"
        # Line 2 — triggers R2 (ringbuf, only fires because R1 present)
        "bpf_perf_event_output(ctx, &events, BPF_F_CURRENT_CPU, buf, 64);\n"
    )
    findings = bup.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


# ---------- Helper -------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[bup.Finding]:
    return [f for f in bup.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : bpf-probe-read-user-exfil -------------------------------


def test_r1_bpf_probe_read_user_fires() -> None:
    """bpf_probe_read_user() call in BPF C source → CRITICAL hit."""
    src = (
        'SEC("kprobe/do_execve")\n'
        "int dump_argv(struct pt_regs *ctx) {\n"
        "    char buf[256];\n"
        "    bpf_probe_read_user(buf, sizeof(buf), filename);\n"
        "    return 0;\n"
        "}\n"
    )
    hits = _hits("bpf-probe-read-user-exfil", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r1_bpf_probe_read_kernel_str_fires() -> None:
    """bpf_probe_read_kernel_str() variant also fires."""
    src = "bpf_probe_read_kernel_str(buf, sizeof(buf), ptr);\n"
    assert _hits("bpf-probe-read-user-exfil", src)


def test_r1_bpf_probe_read_bare_fires() -> None:
    """Plain bpf_probe_read() (legacy) also fires."""
    src = "    ret = bpf_probe_read(buf, 128, (void *)addr);\n"
    assert _hits("bpf-probe-read-user-exfil", src)


def test_r1_unrelated_bpf_call_silent() -> None:
    """bpf_map_lookup_elem() is NOT a probe-read — no hit."""
    src = "val = bpf_map_lookup_elem(&my_map, &key);\n"
    assert not _hits("bpf-probe-read-user-exfil", src)


# ---------- R2 : bpf-ringbuf-covert-channel ------------------------------


def test_r2_ringbuf_output_with_probe_read_fires() -> None:
    """bpf_ringbuf_output present when probe_read also in file → HIGH hit."""
    src = (
        "bpf_probe_read_user(buf, sizeof(buf), ptr);\n"
        "bpf_ringbuf_output(&ring, &event, sizeof(event), 0);\n"
    )
    hits = _hits("bpf-ringbuf-covert-channel", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_perf_event_output_with_probe_read_fires() -> None:
    """bpf_perf_event_output fires when probe_read also present."""
    src = (
        "bpf_probe_read_user(buf, 64, (void __user *)addr);\n"
        "bpf_perf_event_output(ctx, &events, BPF_F_CURRENT_CPU, buf, 64);\n"
    )
    assert _hits("bpf-ringbuf-covert-channel", src)


def test_r2_ringbuf_without_probe_read_suppressed() -> None:
    """bpf_ringbuf_output alone (no probe_read) is suppressed — FP reduction."""
    src = "bpf_ringbuf_output(&ring, &event, sizeof(event), 0);\n"
    assert not _hits("bpf-ringbuf-covert-channel", src)


def test_r2_perf_event_output_without_probe_read_suppressed() -> None:
    """bpf_perf_event_output alone does not fire without probe_read context."""
    src = "bpf_perf_event_output(ctx, &m, BPF_F_CURRENT_CPU, &ev, sizeof(ev));\n"
    assert not _hits("bpf-ringbuf-covert-channel", src)


# ---------- R3 : bpf-bpftrace-in-ci-pipeline -----------------------------


def test_r3_sudo_bpftrace_in_ci_fires() -> None:
    """sudo bpftrace in a CI run step → HIGH hit."""
    src = (
        "- name: Profile build\n"
        "  run: |\n"
        "    sudo bpftrace -e 'tracepoint:syscalls:sys_enter_write { "
        "printf(\"%s\\n\", str(args->buf)); }' &\n"
    )
    hits = _hits("bpf-bpftrace-in-ci-pipeline", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_sudo_bpftool_fires() -> None:
    """sudo bpftool invocation also fires."""
    src = "    sudo bpftool prog show\n"
    assert _hits("bpf-bpftrace-in-ci-pipeline", src)


def test_r3_plain_bpftrace_without_sudo_silent() -> None:
    """bpftrace without sudo or run-as-root marker does NOT fire."""
    src = "# bpftrace example — for docs only\n"
    assert not _hits("bpf-bpftrace-in-ci-pipeline", src)


def test_r3_unrelated_sudo_command_silent() -> None:
    """sudo apt-get (unrelated) does not fire."""
    src = "    sudo apt-get install -y build-essential\n"
    assert not _hits("bpf-bpftrace-in-ci-pipeline", src)


# ---------- R4 : bpf-usdt-prod-probe -------------------------------------


def test_r4_usdt_postgres_probe_fires() -> None:
    """USDT probe on PostgreSQL binary → HIGH hit."""
    src = (
        "bpftrace -e 'usdt:/usr/lib/postgresql/14/bin/postgres:"
        "postgresql:query__start { printf(\"query: %s\\n\", str(arg0)); }'\n"
    )
    hits = _hits("bpf-usdt-prod-probe", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r4_usdt_python_probe_fires() -> None:
    """USDT probe on Python binary fires."""
    src = (
        'bpftrace -e \'usdt:/usr/bin/python3:python:function__entry '
        '{ printf("%s\\n", str(arg0)); }\'\n'
    )
    assert _hits("bpf-usdt-prod-probe", src)


def test_r4_usdt_openssl_probe_fires() -> None:
    """USDT probe on openssl-linked binary fires."""
    src = "usdt:/usr/lib/x86_64-linux-gnu/libssl.so.3:openssl:rsa__sign\n"
    assert _hits("bpf-usdt-prod-probe", src)


def test_r4_usdt_unknown_binary_silent() -> None:
    """USDT probe on an unrecognized binary does NOT fire."""
    src = "usdt:/usr/local/bin/myprivateapp:myprovider:myprobe\n"
    assert not _hits("bpf-usdt-prod-probe", src)


# ---------- R5 : bpf-cgroup-skb-intercept --------------------------------


def test_r5_cgroup_skb_egress_fires() -> None:
    """SEC(\"cgroup_skb/egress\") → CRITICAL hit."""
    src = (
        'SEC("cgroup_skb/egress")\n'
        "int intercept_egress(struct __sk_buff *skb) {\n"
        "    bpf_clone_redirect(skb, attacker_ifindex, BPF_F_INGRESS);\n"
        "    return 1;\n"
        "}\n"
    )
    hits = _hits("bpf-cgroup-skb-intercept", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r5_cgroup_sock_fires() -> None:
    """SEC(\"cgroup_sock/\") variant also fires."""
    src = 'SEC("cgroup_sock/post_bind4")\nint cb(struct bpf_sock *sk) { return 1; }\n'
    assert _hits("bpf-cgroup-skb-intercept", src)


def test_r5_cgroup_sockaddr_fires() -> None:
    """SEC(\"cgroup_sockaddr/connect4\") fires."""
    src = 'SEC("cgroup_sockaddr/connect4")\nint redir(struct bpf_sock_addr *ctx) { return 1; }\n'
    assert _hits("bpf-cgroup-skb-intercept", src)


def test_r5_xdp_program_does_not_fire() -> None:
    """SEC(\"xdp\") is NOT a cgroup program — should not fire."""
    src = 'SEC("xdp")\nint xdp_drop(struct xdp_md *ctx) { return XDP_PASS; }\n'
    assert not _hits("bpf-cgroup-skb-intercept", src)


# ---------- R6 : bpf-fentry-lsm-hook-bypass ------------------------------


def test_r6_fentry_security_file_open_fires() -> None:
    """SEC(\"fentry/security_file_open\") → CRITICAL hit."""
    src = (
        'SEC("fentry/security_file_open")\n'
        "int BPF_PROG(trace_file_open, struct file *file) {\n"
        "    return 0;\n"
        "}\n"
    )
    hits = _hits("bpf-fentry-lsm-hook-bypass", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r6_fexit_security_socket_connect_fires() -> None:
    """SEC(\"fexit/security_socket_connect\") also fires."""
    src = 'SEC("fexit/security_socket_connect")\nint BPF_PROG(t) { return 0; }\n'
    assert _hits("bpf-fentry-lsm-hook-bypass", src)


def test_r6_fentry_on_non_lsm_hook_silent() -> None:
    """SEC(\"fentry/do_sys_open\") is NOT an LSM hook — no hit."""
    src = 'SEC("fentry/do_sys_open")\nint BPF_PROG(t, int dfd, const char *fn) { return 0; }\n'
    assert not _hits("bpf-fentry-lsm-hook-bypass", src)


def test_r6_kprobe_on_security_fn_silent() -> None:
    """SEC(\"kprobe/security_file_open\") is kprobe, not fentry — no hit."""
    src = 'SEC("kprobe/security_file_open")\nint probe(struct pt_regs *ctx) { return 0; }\n'
    assert not _hits("bpf-fentry-lsm-hook-bypass", src)


# ---------- R7a : bpf-monitor-rules-disabled-explicit --------------------


def test_r7a_enabled_false_with_debug_priority_fires() -> None:
    """enabled: false + priority: DEBUG in Falco rule → CRITICAL hit."""
    src = (
        "- rule: All network traffic\n"
        "  desc: Allow all\n"
        "  condition: evt.type in (connect)\n"
        "  output: \"%evt.type\"\n"
        "  priority: DEBUG\n"
        "  enabled: false\n"
    )
    hits = _hits("bpf-monitor-rules-disabled-explicit", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r7a_enabled_false_with_override_block_fires() -> None:
    """enabled: false + override: {condition: replace} fires."""
    src = (
        "  enabled: false\n"
        "  override: {condition: replace, output: replace}\n"
    )
    assert _hits("bpf-monitor-rules-disabled-explicit", src)


def test_r7a_enabled_true_silent() -> None:
    """enabled: true does not fire."""
    src = "  enabled: true\n  priority: WARNING\n"
    assert not _hits("bpf-monitor-rules-disabled-explicit", src)


def test_r7a_enabled_false_without_debug_or_override_silent() -> None:
    """enabled: false without DEBUG priority or override block — no hit."""
    src = "  enabled: false\n  priority: WARNING\n  condition: evt.type=read\n"
    assert not _hits("bpf-monitor-rules-disabled-explicit", src)


# ---------- R7b : bpf-monitor-rules-file-empty ---------------------------


def test_r7b_comments_only_file_fires() -> None:
    """File containing only comments → CRITICAL hit (empty rules file)."""
    src = (
        "# Falco rules\n"
        "# TODO: add rules\n"
        "\n"
    )
    hits = _hits("bpf-monitor-rules-file-empty", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r7b_blank_file_fires() -> None:
    """File containing only whitespace → CRITICAL hit."""
    src = "   \n\n   \n"
    assert _hits("bpf-monitor-rules-file-empty", src)


def test_r7b_file_with_rule_content_silent() -> None:
    """File containing an actual rule definition → no hit."""
    src = (
        "# Falco rules\n"
        "- rule: Unexpected process\n"
        "  desc: Detect unexpected process\n"
        "  condition: proc.name = bash\n"
        "  output: \"Process started: %proc.name\"\n"
        "  priority: WARNING\n"
        "  enabled: true\n"
    )
    assert not _hits("bpf-monitor-rules-file-empty", src)


def test_r7b_mixed_comments_and_rules_silent() -> None:
    """File with comments AND a real rule does not fire."""
    src = "# header\n- rule: test\n  enabled: true\n"
    assert not _hits("bpf-monitor-rules-file-empty", src)


# ---------- R8 : bpf-cilium-empty-egress-policy --------------------------


def test_r8_network_policy_with_egress_type_no_egress_key_fires() -> None:
    """NetworkPolicy with Egress in policyTypes but no egress: → HIGH hit."""
    src = (
        "apiVersion: networking.k8s.io/v1\n"
        "kind: NetworkPolicy\n"
        "metadata:\n"
        "  name: default-deny-egress\n"
        "spec:\n"
        "  podSelector: {}\n"
        "  policyTypes:\n"
        "    - Egress\n"
        "  # no egress stanza\n"
    )
    hits = _hits("bpf-cilium-empty-egress-policy", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r8_network_policy_with_explicit_egress_key_suppressed() -> None:
    """NetworkPolicy with an explicit egress: stanza → suppressed (not ambiguous)."""
    src = (
        "kind: NetworkPolicy\n"
        "spec:\n"
        "  policyTypes:\n"
        "    - Egress\n"
        "  egress:\n"
        "    - to:\n"
        "        - ipBlock:\n"
        "            cidr: 0.0.0.0/0\n"
    )
    assert not _hits("bpf-cilium-empty-egress-policy", src)


def test_r8_network_policy_without_egress_policy_type_silent() -> None:
    """NetworkPolicy that only lists Ingress in policyTypes → no hit."""
    src = (
        "kind: NetworkPolicy\n"
        "spec:\n"
        "  podSelector: {}\n"
        "  policyTypes:\n"
        "    - Ingress\n"
        "  ingress:\n"
        "    - {}\n"
    )
    assert not _hits("bpf-cilium-empty-egress-policy", src)


def test_r8_non_network_policy_kind_silent() -> None:
    """Deployment kind does not fire."""
    src = (
        "kind: Deployment\n"
        "spec:\n"
        "  policyTypes:\n"
        "    - Egress\n"
    )
    assert not _hits("bpf-cilium-empty-egress-policy", src)
