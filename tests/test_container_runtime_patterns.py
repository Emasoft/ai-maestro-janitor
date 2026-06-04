"""Tests for scripts/lib/container_runtime_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 container-runtime
escape catalogue (10 rules targeting docker / podman / nerdctl CLI flag
surface, OCI hook config, gvisor / kata sandbox downgrades). Each rule
has at least one positive test exercising the canary AND at least one
negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import container_runtime_patterns as crp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(crp.RULES, tuple)
    rule_ids = {r.id for r in crp.RULES}
    expected = {
        "cre-runtime-privileged-flag",
        "cre-runtime-docker-sock-mount-cli",
        "cre-runtime-dangerous-cap-add",
        "cre-runtime-lsm-unconfined",
        "cre-runtime-host-namespace-flag",
        "cre-runtime-sensitive-host-mount-rw",
        "cre-runtime-raw-device-passthrough",
        "cre-runtime-oci-hook-host-writable-path",
        "cre-runtime-sandbox-downgrade",
        "cre-runtime-uid-zero-no-new-privileges-miss",
    }
    assert expected == rule_ids
    assert len(crp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in crp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = crp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert crp.scan_text("") == []


def test_public_surface_exports() -> None:
    """Module __all__ must advertise Finding, Rule, RULES, scan_text."""
    assert set(crp.__all__) == {"Finding", "Rule", "RULES", "scan_text"}


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — privileged
        "docker run --privileged alpine sh\n"
        # Line 2 — cap-add SYS_ADMIN
        "docker run --cap-add=SYS_ADMIN alpine sh\n"
    )
    findings = crp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[crp.Finding]:
    return [f for f in crp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : cre-runtime-privileged-flag -----------------------------


def test_r1_docker_run_privileged_flags() -> None:
    """`docker run --privileged` → CRITICAL hit."""
    src = "docker run --privileged -v /:/host alpine chroot /host /bin/bash\n"
    hits = _hits("cre-runtime-privileged-flag", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r1_podman_run_privileged_flags() -> None:
    """`podman run --privileged` → CRITICAL hit (podman alias)."""
    src = "podman run --privileged docker.io/library/alpine sh\n"
    assert _hits("cre-runtime-privileged-flag", src)


def test_r1_unrelated_docker_run_silent() -> None:
    """`docker run` without --privileged → no hit."""
    src = "docker run --user 1000:1000 --cap-drop=ALL alpine sh\n"
    assert not _hits("cre-runtime-privileged-flag", src)


def test_r1_word_privileged_alone_silent() -> None:
    """The word 'privileged' alone (not on a docker-run line) → no hit."""
    src = "# Notes: only the privileged path is mounted read-only.\n"
    assert not _hits("cre-runtime-privileged-flag", src)


# ---------- R2 : cre-runtime-docker-sock-mount-cli -----------------------


def test_r2_short_volume_flag_docker_sock_flags() -> None:
    """`-v /var/run/docker.sock:...` on CLI → CRITICAL hit."""
    src = (
        "docker run -v /var/run/docker.sock:/var/run/docker.sock "
        "--name monitor my/monitor:latest\n"
    )
    hits = _hits("cre-runtime-docker-sock-mount-cli", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r2_mount_source_form_flags() -> None:
    """`--mount type=bind,source=/var/run/docker.sock,...` → CRITICAL hit."""
    src = (
        "docker run --mount type=bind,source=/var/run/docker.sock,"
        "target=/var/run/docker.sock alpine\n"
    )
    assert _hits("cre-runtime-docker-sock-mount-cli", src)


def test_r2_unrelated_volume_silent() -> None:
    """A `-v` mount of `/etc/passwd` → no R2 hit (different rule)."""
    src = "docker run -v /tmp/data:/data alpine sh\n"
    assert not _hits("cre-runtime-docker-sock-mount-cli", src)


def test_r2_docker_sock_bak_path_silent() -> None:
    """`/var/run/docker.sock.bak` is not the live socket → no hit."""
    src = "docker run -v /var/run/docker.sock.bak:/foo alpine\n"
    assert not _hits("cre-runtime-docker-sock-mount-cli", src)


# ---------- R3 : cre-runtime-dangerous-cap-add ---------------------------


def test_r3_cap_add_sys_admin_flags() -> None:
    """`--cap-add=SYS_ADMIN` → HIGH hit."""
    src = "docker run --cap-add=SYS_ADMIN alpine sh\n"
    hits = _hits("cre-runtime-dangerous-cap-add", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_cap_add_sys_module_flags() -> None:
    """`--cap-add SYS_MODULE` (space form) → HIGH hit."""
    src = "docker run --cap-add SYS_MODULE alpine modprobe foo\n"
    assert _hits("cre-runtime-dangerous-cap-add", src)


def test_r3_cap_add_cap_prefix_flags() -> None:
    """`--cap-add=CAP_SYS_PTRACE` (CAP_ prefix form) → HIGH hit."""
    src = "docker run --cap-add=CAP_SYS_PTRACE alpine\n"
    assert _hits("cre-runtime-dangerous-cap-add", src)


def test_r3_cap_add_safe_cap_silent() -> None:
    """`--cap-add=NET_BIND_SERVICE` (non-escape-class) → no hit."""
    src = "docker run --cap-add=NET_BIND_SERVICE myapp\n"
    assert not _hits("cre-runtime-dangerous-cap-add", src)


# ---------- R4 : cre-runtime-lsm-unconfined ------------------------------


def test_r4_seccomp_unconfined_flags() -> None:
    """`--security-opt seccomp=unconfined` → HIGH hit."""
    src = "docker run --security-opt seccomp=unconfined alpine\n"
    hits = _hits("cre-runtime-lsm-unconfined", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r4_apparmor_unconfined_flags() -> None:
    """`--security-opt apparmor=unconfined` → HIGH hit."""
    src = "docker run --security-opt apparmor=unconfined alpine\n"
    assert _hits("cre-runtime-lsm-unconfined", src)


def test_r4_selinux_label_disable_flags() -> None:
    """`--security-opt label=disable` → HIGH hit (SELinux disable)."""
    src = "podman run --security-opt label=disable alpine\n"
    assert _hits("cre-runtime-lsm-unconfined", src)


def test_r4_custom_seccomp_profile_silent() -> None:
    """`--security-opt seccomp=/path/profile.json` → no hit (custom whitelist)."""
    src = "docker run --security-opt seccomp=/etc/seccomp/chrome.json chrome\n"
    assert not _hits("cre-runtime-lsm-unconfined", src)


# ---------- R5 : cre-runtime-host-namespace-flag -------------------------


def test_r5_pid_host_flags() -> None:
    """`--pid=host` → HIGH hit."""
    src = "docker run --pid=host alpine sh\n"
    hits = _hits("cre-runtime-host-namespace-flag", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r5_network_host_flags() -> None:
    """`--network=host` → HIGH hit."""
    src = "docker run --network=host nginx\n"
    assert _hits("cre-runtime-host-namespace-flag", src)


def test_r5_net_alias_host_flags() -> None:
    """`--net=host` (legacy alias) → HIGH hit."""
    src = "docker run --net=host alpine sh\n"
    assert _hits("cre-runtime-host-namespace-flag", src)


def test_r5_userns_host_flags() -> None:
    """`--userns=host` (rootless downgrade) → HIGH hit."""
    src = "podman run --userns=host alpine\n"
    assert _hits("cre-runtime-host-namespace-flag", src)


def test_r5_pid_container_ref_silent() -> None:
    """`--pid=container:abc` → no hit (sibling-container join, not host)."""
    src = "docker run --pid=container:sidecar alpine ps -ef\n"
    assert not _hits("cre-runtime-host-namespace-flag", src)


# ---------- R6 : cre-runtime-sensitive-host-mount-rw ---------------------


def test_r6_etc_mount_rw_flags() -> None:
    """`-v /etc:/host_etc` (no `:ro`) → HIGH hit."""
    src = "docker run -v /etc:/host_etc alpine sh\n"
    hits = _hits("cre-runtime-sensitive-host-mount-rw", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r6_sys_mount_rw_flags() -> None:
    """`-v /sys:/host_sys` (no `:ro`) → HIGH hit."""
    src = "docker run -v /sys:/host_sys --cap-add=SYS_ADMIN alpine\n"
    assert _hits("cre-runtime-sensitive-host-mount-rw", src)


def test_r6_proc_mount_readonly_silent() -> None:
    """`-v /proc:/host/proc:ro` → no hit (monitoring-agent pattern)."""
    src = "docker run -v /proc:/host/proc:ro node_exporter\n"
    assert not _hits("cre-runtime-sensitive-host-mount-rw", src)


def test_r6_proc_mount_ro_with_propagation_silent() -> None:
    """`-v /proc:/host/proc:ro,rslave` → no hit (ro present in suffix tokens)."""
    src = "docker run -v /proc:/host/proc:ro,rslave node_exporter\n"
    assert not _hits("cre-runtime-sensitive-host-mount-rw", src)


# ---------- R7 : cre-runtime-raw-device-passthrough ----------------------


def test_r7_dev_mem_passthrough_flags() -> None:
    """`--device=/dev/mem` → CRITICAL hit."""
    src = "docker run --device=/dev/mem --cap-add=SYS_RAWIO alpine\n"
    hits = _hits("cre-runtime-raw-device-passthrough", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r7_dev_sda_passthrough_flags() -> None:
    """`--device=/dev/sda` (raw block device) → CRITICAL hit."""
    src = "docker run --device=/dev/sda alpine dd if=/dev/zero of=/dev/sda\n"
    assert _hits("cre-runtime-raw-device-passthrough", src)


def test_r7_dev_kmsg_passthrough_flags() -> None:
    """`--device /dev/kmsg` (space form, kernel ring buffer) → CRITICAL hit."""
    src = "docker run --device /dev/kmsg alpine cat /dev/kmsg\n"
    assert _hits("cre-runtime-raw-device-passthrough", src)


def test_r7_gpu_passthrough_silent() -> None:
    """`--device=/dev/nvidia0` (legitimate GPU passthrough) → no hit."""
    src = "docker run --device=/dev/nvidia0 nvidia/cuda nvidia-smi\n"
    assert not _hits("cre-runtime-raw-device-passthrough", src)


def test_r7_serial_port_silent() -> None:
    """`--device=/dev/ttyS0` (serial console) → no hit."""
    src = "docker run --device=/dev/ttyS0 minicom\n"
    assert not _hits("cre-runtime-raw-device-passthrough", src)


# ---------- R8 : cre-runtime-oci-hook-host-writable-path -----------------


def test_r8_oci_prestart_hook_tmp_flags() -> None:
    """OCI prestart hook in `/tmp` → CRITICAL hit."""
    src = (
        '{ "hooks": { "prestart": [ { "path": "/tmp/oci-setup.sh", '
        '"args": ["setup"] } ] } }\n'
    )
    hits = _hits("cre-runtime-oci-hook-host-writable-path", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r8_oci_poststop_devshm_flags() -> None:
    """OCI poststop hook in `/dev/shm` → CRITICAL hit."""
    src = (
        '{ "hooks": { "poststop": [ { "path": "/dev/shm/cleanup", '
        '"args": [] } ] } }\n'
    )
    assert _hits("cre-runtime-oci-hook-host-writable-path", src)


def test_r8_containerd_binaryname_tmp_flags() -> None:
    """containerd `BinaryName = "/tmp/..."` → CRITICAL hit."""
    src = 'BinaryName = "/tmp/my-runc"\n'
    assert _hits("cre-runtime-oci-hook-host-writable-path", src)


def test_r8_vendored_hook_path_silent() -> None:
    """OCI hook under `/usr/libexec/oci/hooks.d/` → no hit (vendored)."""
    src = (
        '{ "hooks": { "prestart": [ { "path": "/usr/libexec/oci/hooks.d/seccomp", '
        '"args": [] } ] } }\n'
    )
    assert not _hits("cre-runtime-oci-hook-host-writable-path", src)


# ---------- R9 : cre-runtime-sandbox-downgrade ---------------------------


def test_r9_gvisor_platform_ptrace_flags() -> None:
    """`runsc --platform=ptrace` → HIGH hit."""
    src = "runsc --platform=ptrace --network=host run mycontainer\n"
    hits = _hits("cre-runtime-sandbox-downgrade", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r9_kata_runc_runtime_type_flags() -> None:
    """`runtime_type = "io.containerd.runc.v2"` under a kata config → HIGH hit."""
    src = 'runtime_type = "io.containerd.runc.v2"\n'
    assert _hits("cre-runtime-sandbox-downgrade", src)


def test_r9_kata_disable_vm_flags() -> None:
    """`disable_vm = true` → HIGH hit (explicit downgrade switch)."""
    src = "disable_vm = true\n"
    assert _hits("cre-runtime-sandbox-downgrade", src)


def test_r9_gvisor_platform_kvm_silent() -> None:
    """`runsc --platform=kvm` → no hit (the secure default)."""
    src = "runsc --platform=kvm run mycontainer\n"
    assert not _hits("cre-runtime-sandbox-downgrade", src)


def test_r9_kata_proper_runtime_type_silent() -> None:
    """`runtime_type = "io.containerd.kata.v2"` → no hit (correct kata config)."""
    src = 'runtime_type = "io.containerd.kata.v2"\n'
    assert not _hits("cre-runtime-sandbox-downgrade", src)


# ---------- R10 : cre-runtime-uid-zero-no-new-privileges-miss ------------


def test_r10_user_zero_alone_flags() -> None:
    """`docker run --user 0` without no-new-privileges → MEDIUM hit."""
    src = "docker run --user 0 -v /etc:/etc:ro alpine sh\n"
    hits = _hits("cre-runtime-uid-zero-no-new-privileges-miss", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r10_user_root_alone_flags() -> None:
    """`docker run --user root` without no-new-privileges → MEDIUM hit."""
    src = "docker run --user root --name app my/img\n"
    assert _hits("cre-runtime-uid-zero-no-new-privileges-miss", src)


def test_r10_user_zero_with_no_new_privs_silent() -> None:
    """`docker run --user 0 --security-opt no-new-privileges:true` → no hit."""
    src = (
        "docker run --user 0 --security-opt no-new-privileges:true "
        "--cap-drop=ALL my/img\n"
    )
    assert not _hits("cre-runtime-uid-zero-no-new-privileges-miss", src)


def test_r10_non_root_user_silent() -> None:
    """`docker run --user 1000:1000` → no hit (non-root user)."""
    src = "docker run --user 1000:1000 my/img\n"
    assert not _hits("cre-runtime-uid-zero-no-new-privileges-miss", src)


# ---------- Cross-rule integration --------------------------------------


def test_combined_anti_pattern_emits_multiple_findings() -> None:
    """A single privileged + sock-mount + cap-add line → all three rules fire."""
    src = (
        "docker run --privileged --cap-add=SYS_ADMIN "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "--network=host alpine sh\n"
    )
    rule_ids = {f.rule_id for f in crp.scan_text(src)}
    assert "cre-runtime-privileged-flag" in rule_ids
    assert "cre-runtime-docker-sock-mount-cli" in rule_ids
    assert "cre-runtime-dangerous-cap-add" in rule_ids
    assert "cre-runtime-host-namespace-flag" in rule_ids


def test_findings_dedupe_by_line_col_rule() -> None:
    """Scanning the same text twice and concatenating should not dedupe across
    calls, but within a single call each (rule_id, line, col) appears once."""
    src = "docker run --privileged alpine\n"
    findings = crp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
