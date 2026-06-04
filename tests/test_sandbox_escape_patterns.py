"""Tests for scripts/lib/sandbox_escape_patterns.py.

Pattern-coverage tests for the Wave-18 distillation round 4 angle H
catalogue (Dockerfile setuid, privileged LABEL, docker.sock mount,
host namespace share, dangerous host path, no-hardening, cap_add
dangerous, seccomp unconfined, privileged: true, host network leak,
k8s SecurityContext gap, cluster-admin binding, docker run missing
hardening, OCI runtime hook injection).

Each rule gets at least one positive test + at least one negative
test exercising the carve-out / safe shape. ~40 tests total.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import sandbox_escape_patterns as sep  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(sep.RULES, tuple)
    rule_ids = {r.id for r in sep.RULES}
    expected = {
        "container-dockerfile-setuid-binary",
        "container-dockerfile-privileged-label",
        "container-compose-docker-sock-mount",
        "container-compose-host-namespace-share",
        "container-compose-hostpath-dangerous",
        "container-compose-no-hardening",
        "container-compose-cap-add-dangerous",
        "container-compose-seccomp-unconfined",
        "container-compose-privileged-true",
        "container-compose-host-network-bridge-leak",
        "k8s-securitycontext-gap",
        "k8s-clusterrolebinding-cluster-admin",
        "docker-run-invocation-missing-hardening",
        "oci-runtime-hook-injection",
    }
    assert expected.issubset(rule_ids)
    assert len(expected) == 14


def test_every_rule_has_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and valid severity."""
    for rule in sep.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = sep.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1 and f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def _hits(rule_id: str, text: str, *, file_kind: str = "auto") -> list[sep.Finding]:
    return [f for f in sep.scan_text(text, file_kind=file_kind) if f.rule_id == rule_id]


# ---------- Rule 1: Dockerfile setuid binary ------------------------------


def test_dockerfile_setuid_chmod_octal_4755() -> None:
    """`chmod 4755 /usr/local/bin/foo` sets the setuid bit."""
    src = "FROM alpine\nRUN chmod 4755 /usr/local/bin/foo\n"
    assert _hits("container-dockerfile-setuid-binary", src)


def test_dockerfile_setuid_chmod_octal_6755() -> None:
    """`chmod 6755 /usr/local/bin/foo` sets setuid+setgid."""
    src = "FROM alpine\nRUN chmod 6755 /usr/local/bin/foo\n"
    assert _hits("container-dockerfile-setuid-binary", src)


def test_dockerfile_setuid_symbolic_u_plus_s() -> None:
    """`chmod u+s /usr/bin/foo` is symbolic setuid."""
    src = "FROM alpine\nRUN chmod u+s /usr/bin/foo\n"
    assert _hits("container-dockerfile-setuid-binary", src)


def test_dockerfile_setcap_ep_grant() -> None:
    """`setcap cap_net_bind_service=ep` is the suid alternative."""
    src = "FROM alpine\nRUN setcap cap_net_bind_service=ep /usr/bin/foo\n"
    assert _hits("container-dockerfile-setuid-binary", src)


def test_dockerfile_setcap_all_ep_grant() -> None:
    """`setcap all=ep` grants every capability."""
    src = "FROM alpine\nRUN setcap all=ep /usr/bin/foo\n"
    assert _hits("container-dockerfile-setuid-binary", src)


def test_dockerfile_chmod_755_no_setuid_safe() -> None:
    """Plain 755 mode (no leading 4/6/2) does not fire."""
    src = "FROM alpine\nRUN chmod 755 /usr/bin/foo\n"
    assert not _hits("container-dockerfile-setuid-binary", src)


# ---------- Rule 2: Dockerfile privileged LABEL ---------------------------


def test_dockerfile_label_privileged() -> None:
    """`LABEL privileged=true` self-declares need-for-privilege."""
    src = 'FROM alpine\nLABEL privileged="true"\n'
    assert _hits("container-dockerfile-privileged-label", src)


def test_dockerfile_label_requires_sys_admin() -> None:
    """`LABEL requires_cap_sys_admin=true` is a privilege contract."""
    src = 'FROM alpine\nLABEL requires_cap_sys_admin="true"\n'
    assert _hits("container-dockerfile-privileged-label", src)


def test_dockerfile_run_dev_kvm_reference() -> None:
    """RUN referencing `/dev/kvm` signals host-device dependency."""
    src = "FROM alpine\nRUN test -c /dev/kvm\n"
    assert _hits("container-dockerfile-privileged-label", src)


def test_dockerfile_run_sys_kernel_debug_reference() -> None:
    """RUN touching `/sys/kernel/debug` is a host-only path."""
    src = "FROM alpine\nRUN mkdir -p /sys/kernel/debug/x\n"
    assert _hits("container-dockerfile-privileged-label", src)


def test_dockerfile_normal_label_safe() -> None:
    """`LABEL maintainer="…"` is benign."""
    src = 'FROM alpine\nLABEL maintainer="dev@example.com"\n'
    assert not _hits("container-dockerfile-privileged-label", src)


# ---------- Rule 3: Compose docker.sock mount -----------------------------


def test_compose_docker_sock_mount_short_form() -> None:
    """`/var/run/docker.sock:/var/run/docker.sock` is the canonical mount."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /var/run/docker.sock:/var/run/docker.sock\n"
    )
    assert _hits("container-compose-docker-sock-mount", src)


def test_compose_docker_sock_mount_readonly_still_fires() -> None:
    """:ro suffix does not stop the rule — API still reachable."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /var/run/docker.sock:/var/run/docker.sock:ro\n"
    )
    assert _hits("container-compose-docker-sock-mount", src)


def test_compose_containerd_sock_mount() -> None:
    """containerd socket mount also fires."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /var/run/containerd/containerd.sock:/sock\n"
    )
    assert _hits("container-compose-docker-sock-mount", src)


def test_compose_no_socket_mount_safe() -> None:
    """Plain `./data:/data` volume is benign."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - ./data:/data\n"
    )
    assert not _hits("container-compose-docker-sock-mount", src)


# ---------- Rule 4: Compose host namespace share --------------------------


def test_compose_pid_host_critical() -> None:
    """`pid: host` is CRITICAL."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    pid: host\n"
    )
    hits = _hits("container-compose-host-namespace-share", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_compose_network_mode_host_critical() -> None:
    """`network_mode: host` is CRITICAL."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    network_mode: host\n"
    )
    hits = _hits("container-compose-host-namespace-share", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_compose_ipc_host_critical() -> None:
    """`ipc: host` enables host-shared memory access."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    ipc: host\n"
    )
    assert _hits("container-compose-host-namespace-share", src)


def test_compose_uts_host_medium() -> None:
    """`uts: host` is MEDIUM, not CRITICAL."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    uts: host\n"
    )
    hits = _hits("container-compose-host-namespace-share", src)
    assert hits and all(h.severity == "MEDIUM" for h in hits)


def test_compose_pid_default_safe() -> None:
    """Default (no pid: host) is benign."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
    )
    assert not _hits("container-compose-host-namespace-share", src)


# ---------- Rule 5: Compose dangerous hostpath ----------------------------


def test_compose_hostpath_root_critical() -> None:
    """Bind-mount of `/` to anywhere is CRITICAL."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /:/host\n"
    )
    hits = _hits("container-compose-hostpath-dangerous", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_compose_hostpath_proc_high() -> None:
    """Bind-mount of `/proc` is HIGH (kernel surface)."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /proc:/host/proc\n"
    )
    hits = _hits("container-compose-hostpath-dangerous", src)
    assert hits and any(h.severity == "HIGH" for h in hits)


def test_compose_hostpath_etc_critical() -> None:
    """`/etc` mount leaks passwd / shadow."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /etc:/host-etc\n"
    )
    hits = _hits("container-compose-hostpath-dangerous", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_compose_hostpath_var_run_medium() -> None:
    """`/var/run` aggregate is MEDIUM."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /var/run:/var-run\n"
    )
    hits = _hits("container-compose-hostpath-dangerous", src)
    assert hits and any(h.severity == "MEDIUM" for h in hits)


def test_compose_hostpath_safe_app_dir() -> None:
    """`/srv/app` is not in the danger list."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    volumes:\n"
        "      - /srv/app:/app\n"
    )
    assert not _hits("container-compose-hostpath-dangerous", src)


# ---------- Rule 6: Compose no-hardening ---------------------------------


def test_compose_no_hardening_bare_image() -> None:
    """Default-insecure compose: image + nothing else."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu:latest\n"
    )
    assert _hits("container-compose-no-hardening", src)


def test_compose_hardening_cap_drop_all_safe() -> None:
    """`cap_drop: [ALL]` is sufficient to suppress."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu:latest\n"
        "    cap_drop:\n"
        "      - ALL\n"
    )
    assert not _hits("container-compose-no-hardening", src)


def test_compose_hardening_readonly_safe() -> None:
    """`read_only: true` is sufficient to suppress."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu:latest\n"
        "    read_only: true\n"
    )
    assert not _hits("container-compose-no-hardening", src)


def test_compose_hardening_nonroot_user_safe() -> None:
    """`user: 1000:1000` is sufficient to suppress."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu:latest\n"
        "    user: \"1000:1000\"\n"
    )
    assert not _hits("container-compose-no-hardening", src)


# ---------- Rule 7: Compose cap_add dangerous -----------------------------


def test_compose_cap_add_sys_admin_high() -> None:
    """SYS_ADMIN is HIGH."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    cap_add:\n"
        "      - SYS_ADMIN\n"
    )
    hits = _hits("container-compose-cap-add-dangerous", src)
    assert hits and any(h.severity == "HIGH" for h in hits)


def test_compose_cap_add_sys_module_high() -> None:
    """SYS_MODULE is HIGH (kernel modules)."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    cap_add:\n"
        "      - SYS_MODULE\n"
    )
    hits = _hits("container-compose-cap-add-dangerous", src)
    assert hits and any(h.severity == "HIGH" for h in hits)


def test_compose_cap_add_net_admin_medium() -> None:
    """NET_ADMIN is MEDIUM (still bad but lower)."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    cap_add:\n"
        "      - NET_ADMIN\n"
    )
    hits = _hits("container-compose-cap-add-dangerous", src)
    assert hits and any(h.severity == "MEDIUM" for h in hits)


def test_compose_cap_add_with_cap_prefix_normalizes() -> None:
    """`CAP_SYS_ADMIN` normalises to `SYS_ADMIN`."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    cap_add:\n"
        "      - CAP_SYS_ADMIN\n"
    )
    assert _hits("container-compose-cap-add-dangerous", src)


def test_compose_no_cap_add_safe() -> None:
    """No cap_add at all does not fire rule 7."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
    )
    assert not _hits("container-compose-cap-add-dangerous", src)


# ---------- Rule 8: Compose seccomp unconfined ----------------------------


def test_compose_seccomp_unconfined() -> None:
    """`seccomp:unconfined` disables the syscall filter."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    security_opt:\n"
        "      - seccomp:unconfined\n"
    )
    assert _hits("container-compose-seccomp-unconfined", src)


def test_compose_apparmor_unconfined() -> None:
    """`apparmor:unconfined` is equivalent for AppArmor systems."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    security_opt:\n"
        "      - apparmor:unconfined\n"
    )
    assert _hits("container-compose-seccomp-unconfined", src)


def test_compose_custom_seccomp_profile_medium() -> None:
    """Custom seccomp profile path is MEDIUM (needs review)."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    security_opt:\n"
        "      - seccomp:/etc/seccomp/custom.json\n"
    )
    hits = _hits("container-compose-seccomp-unconfined", src)
    assert hits and any(h.severity == "MEDIUM" for h in hits)


def test_compose_seccomp_default_safe() -> None:
    """No security_opt at all does not fire rule 8."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
    )
    assert not _hits("container-compose-seccomp-unconfined", src)


# ---------- Rule 9: Compose privileged: true ------------------------------


def test_compose_privileged_true_critical() -> None:
    """`privileged: true` is CRITICAL."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    privileged: true\n"
    )
    hits = _hits("container-compose-privileged-true", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_compose_no_new_privileges_false_critical() -> None:
    """Explicit `no-new-privileges:false` is CRITICAL."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    security_opt:\n"
        "      - no-new-privileges:false\n"
    )
    hits = _hits("container-compose-privileged-true", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_compose_privileged_false_safe() -> None:
    """`privileged: false` is the safe default."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    privileged: false\n"
    )
    assert not _hits("container-compose-privileged-true", src)


# ---------- Rule 10: Compose host network leak ----------------------------


def test_compose_extra_hosts_host_gateway() -> None:
    """`host.docker.internal:host-gateway` exposes host services."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    extra_hosts:\n"
        "      - host.docker.internal:host-gateway\n"
    )
    assert _hits("container-compose-host-network-bridge-leak", src)


def test_compose_unbound_postgres_port_fires() -> None:
    """`5432:5432` (no 127.0.0.1: prefix) exposes Postgres to LAN."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: postgres\n"
        "    ports:\n"
        "      - \"5432:5432\"\n"
    )
    assert _hits("container-compose-host-network-bridge-leak", src)


def test_compose_loopback_bound_port_safe() -> None:
    """`127.0.0.1:5432:5432` is local-only — safe."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: postgres\n"
        "    ports:\n"
        "      - \"127.0.0.1:5432:5432\"\n"
    )
    assert not _hits("container-compose-host-network-bridge-leak", src)


# ---------- Rule 11: k8s SecurityContext gap ------------------------------


def test_k8s_pod_privileged_critical() -> None:
    """`privileged: true` on a container is CRITICAL."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: bad\n"
        "spec:\n"
        "  containers:\n"
        "    - name: c\n"
        "      image: ubuntu\n"
        "      securityContext:\n"
        "        privileged: true\n"
    )
    hits = _hits("k8s-securitycontext-gap", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_k8s_pod_host_network_high() -> None:
    """`hostNetwork: true` is HIGH."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: bad\n"
        "spec:\n"
        "  hostNetwork: true\n"
        "  containers:\n"
        "    - name: c\n"
        "      image: ubuntu\n"
    )
    hits = _hits("k8s-securitycontext-gap", src)
    assert hits and any(h.severity == "HIGH" for h in hits)


def test_k8s_pod_hostpath_root_critical() -> None:
    """`hostPath: /` is CRITICAL."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: bad\n"
        "spec:\n"
        "  containers:\n"
        "    - name: c\n"
        "      image: ubuntu\n"
        "  volumes:\n"
        "    - name: root\n"
        "      hostPath:\n"
        "        path: /\n"
    )
    hits = _hits("k8s-securitycontext-gap", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_k8s_deployment_allow_privilege_escalation_high() -> None:
    """Deployment wrapper resolves to pod spec inside template."""
    src = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: bad\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: c\n"
        "          image: ubuntu\n"
        "          securityContext:\n"
        "            allowPrivilegeEscalation: true\n"
    )
    hits = _hits("k8s-securitycontext-gap", src)
    assert hits and any(h.severity == "HIGH" for h in hits)


def test_k8s_pod_capabilities_add_sys_admin_high() -> None:
    """capabilities.add: ['SYS_ADMIN'] is HIGH."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: bad\n"
        "spec:\n"
        "  containers:\n"
        "    - name: c\n"
        "      image: ubuntu\n"
        "      securityContext:\n"
        "        capabilities:\n"
        "          add: ['SYS_ADMIN']\n"
    )
    assert _hits("k8s-securitycontext-gap", src)


def test_k8s_pod_seccomp_unconfined_high() -> None:
    """`seccompProfile.type: Unconfined` is HIGH."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: bad\n"
        "spec:\n"
        "  containers:\n"
        "    - name: c\n"
        "      image: ubuntu\n"
        "      securityContext:\n"
        "        seccompProfile:\n"
        "          type: Unconfined\n"
    )
    assert _hits("k8s-securitycontext-gap", src)


def test_k8s_pod_hardened_safe() -> None:
    """Pod with proper context produces no SC-gap finding."""
    src = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        "  name: good\n"
        "spec:\n"
        "  containers:\n"
        "    - name: c\n"
        "      image: ubuntu\n"
        "      securityContext:\n"
        "        runAsNonRoot: true\n"
        "        allowPrivilegeEscalation: false\n"
        "        readOnlyRootFilesystem: true\n"
        "        capabilities:\n"
        "          drop: ['ALL']\n"
    )
    assert not _hits("k8s-securitycontext-gap", src)


# ---------- Rule 12: k8s cluster-admin binding ----------------------------


def test_k8s_clusterrolebinding_cluster_admin_critical() -> None:
    """ClusterRoleBinding → cluster-admin is CRITICAL."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata:\n"
        "  name: bad\n"
        "roleRef:\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "  kind: ClusterRole\n"
        "  name: cluster-admin\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: default\n"
        "    namespace: default\n"
    )
    hits = _hits("k8s-clusterrolebinding-cluster-admin", src)
    assert hits and any(h.severity == "CRITICAL" for h in hits)


def test_k8s_clusterrolebinding_system_authenticated_critical() -> None:
    """system:authenticated subject = literally everyone."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata:\n"
        "  name: bad\n"
        "roleRef:\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "  kind: ClusterRole\n"
        "  name: view\n"
        "subjects:\n"
        "  - kind: Group\n"
        "    name: system:authenticated\n"
    )
    assert _hits("k8s-clusterrolebinding-cluster-admin", src)


def test_k8s_clusterrole_triple_star_critical() -> None:
    """ClusterRole with verbs/resources/apiGroups all `*` = admin."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRole\n"
        "metadata:\n"
        "  name: superuser\n"
        "rules:\n"
        "  - apiGroups: ['*']\n"
        "    resources: ['*']\n"
        "    verbs: ['*']\n"
    )
    assert _hits("k8s-clusterrolebinding-cluster-admin", src)


def test_k8s_clusterrolebinding_scoped_role_safe() -> None:
    """Binding to a scoped role is not a cluster-admin grant."""
    src = (
        "apiVersion: rbac.authorization.k8s.io/v1\n"
        "kind: ClusterRoleBinding\n"
        "metadata:\n"
        "  name: ok\n"
        "roleRef:\n"
        "  apiGroup: rbac.authorization.k8s.io\n"
        "  kind: ClusterRole\n"
        "  name: view\n"
        "subjects:\n"
        "  - kind: ServiceAccount\n"
        "    name: viewer\n"
        "    namespace: default\n"
    )
    assert not _hits("k8s-clusterrolebinding-cluster-admin", src)


# ---------- Rule 13: docker run missing hardening -------------------------


def test_docker_run_no_hardening_high() -> None:
    """`docker run -it ubuntu bash` is missing 4 hardening flags."""
    src = "docker run -it ubuntu bash\n"
    hits = _hits("docker-run-invocation-missing-hardening", src)
    assert hits and any(h.severity == "HIGH" for h in hits)


def test_docker_run_partial_hardening_high() -> None:
    """Missing 2 of 4 hardening flags is still HIGH."""
    src = "docker run --cap-drop=ALL --read-only ubuntu bash\n"
    hits = _hits("docker-run-invocation-missing-hardening", src)
    assert hits and any(h.severity == "HIGH" for h in hits)


def test_docker_run_one_missing_medium() -> None:
    """Missing only 1 of 4 hardening flags is MEDIUM (advisory)."""
    src = (
        "docker run --cap-drop=ALL "
        "--security-opt=no-new-privileges "
        "--read-only ubuntu bash\n"
    )
    hits = _hits("docker-run-invocation-missing-hardening", src)
    assert hits and any(h.severity == "MEDIUM" for h in hits)


def test_docker_run_fully_hardened_safe() -> None:
    """All 4 hardening flags present = safe."""
    src = (
        "docker run --rm -it "
        "--cap-drop=ALL "
        "--security-opt=no-new-privileges "
        "--read-only "
        "--user 1000:1000 "
        "ubuntu bash\n"
    )
    assert not _hits("docker-run-invocation-missing-hardening", src)


def test_docker_run_line_continuation_joined() -> None:
    """Multi-line `docker run \\` is joined before tokenisation."""
    src = (
        "docker run --rm -it \\\n"
        "  --cap-drop=ALL \\\n"
        "  --security-opt=no-new-privileges \\\n"
        "  --read-only \\\n"
        "  --user 1000:1000 \\\n"
        "  ubuntu bash\n"
    )
    assert not _hits("docker-run-invocation-missing-hardening", src)


# ---------- Rule 14: OCI runtime hook injection ---------------------------


def test_oci_hook_prestart_tmp_path_fires() -> None:
    """`hooks.prestart` pointing to `/tmp/` is writable & escapable."""
    src = (
        '{"ociVersion": "1.0.2",'
        ' "process": {"args": ["bash"]},'
        ' "root": {"path": "rootfs"},'
        ' "hooks": {"prestart": ['
        '   {"path": "/tmp/hook.sh", "args": ["hook.sh"]}'
        '  ]}'
        '}'
    )
    assert _hits("oci-runtime-hook-injection", src, file_kind="oci")


def test_oci_hook_poststart_var_tmp_fires() -> None:
    """`/var/tmp/` is equally writable."""
    src = (
        '{"ociVersion": "1.0.2",'
        ' "process": {"args": ["bash"]},'
        ' "root": {"path": "rootfs"},'
        ' "hooks": {"poststart": ['
        '   {"path": "/var/tmp/hook.sh"}'
        '  ]}'
        '}'
    )
    assert _hits("oci-runtime-hook-injection", src, file_kind="oci")


def test_oci_hook_traversal_fires() -> None:
    """A `..` path-traversal in the hook path fires."""
    src = (
        '{"ociVersion": "1.0.2",'
        ' "process": {"args": ["bash"]},'
        ' "root": {"path": "rootfs"},'
        ' "hooks": {"poststop": ['
        '   {"path": "/opt/hooks/../tmp/x.sh"}'
        '  ]}'
        '}'
    )
    assert _hits("oci-runtime-hook-injection", src, file_kind="oci")


def test_oci_hook_safe_path_no_fire() -> None:
    """Hook in `/opt/hooks/` (immutable image path) is safe."""
    src = (
        '{"ociVersion": "1.0.2",'
        ' "process": {"args": ["bash"]},'
        ' "root": {"path": "rootfs"},'
        ' "hooks": {"prestart": ['
        '   {"path": "/opt/hooks/safe.sh"}'
        '  ]}'
        '}'
    )
    assert not _hits("oci-runtime-hook-injection", src, file_kind="oci")


def test_oci_no_hooks_block_safe() -> None:
    """An OCI config with no hooks at all is benign."""
    src = (
        '{"ociVersion": "1.0.2",'
        ' "process": {"args": ["bash"]},'
        ' "root": {"path": "rootfs"}'
        '}'
    )
    assert not _hits("oci-runtime-hook-injection", src, file_kind="oci")


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_empty_returns_empty() -> None:
    assert sep.scan_text("") == []


def test_scan_text_autodetect_dockerfile() -> None:
    """`FROM` opener triggers dockerfile autodetect."""
    src = "FROM alpine\nRUN chmod 4755 /usr/bin/foo\n"
    findings = sep.scan_text(src)
    assert any(f.rule_id == "container-dockerfile-setuid-binary" for f in findings)


def test_scan_text_autodetect_compose() -> None:
    """`services:` opener triggers compose autodetect."""
    src = (
        "services:\n"
        "  agent:\n"
        "    image: ubuntu\n"
        "    privileged: true\n"
    )
    findings = sep.scan_text(src)
    assert any(f.rule_id == "container-compose-privileged-true" for f in findings)


def test_scan_text_findings_sorted() -> None:
    """Findings come out sorted by (line, column, rule_id)."""
    src = (
        "services:\n"
        "  a:\n"
        "    image: ubuntu\n"
        "    privileged: true\n"
        "  b:\n"
        "    image: ubuntu\n"
        "    pid: host\n"
    )
    findings = sep.scan_text(src)
    for prev, curr in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line, curr.column, curr.rule_id
        )
