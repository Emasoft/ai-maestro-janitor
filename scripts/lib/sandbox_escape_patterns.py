"""Sandbox / container-escape detection — deeper than Dockerfile surface.

Wave-18 deep-dive distillation round 4, angle H.

Catalogues 14 sandbox-escape detection rules that go BEYOND the
single-file Dockerfile surface already shipped in
`scripts/lib/container_patterns.py`. We catch kernel capability flags,
seccomp/AppArmor/SELinux drift, namespace sharing (PID/IPC/network),
host-path mounts, k8s SecurityContext gaps, RBAC over-grant, OCI
runtime hooks, and unhardened `docker run` invocations.

This module is strictly *defensive*: every rule detects a
mis-configuration that lowers sandbox isolation so the janitor can
warn the operator. No exploit prose. Patterns are RE2-safe — no
back-references, no unbounded look-arounds — and DOS-resistant
(every variable-width quantifier is upper-bounded).

Reference proposal: `reports/distill-round-4/sandbox-container-escape.md`.

Rule inventory:

  1.  container-dockerfile-setuid-binary             (HIGH)
  2.  container-dockerfile-privileged-label          (HIGH)
  3.  container-compose-docker-sock-mount            (CRITICAL)
  4.  container-compose-host-namespace-share         (CRITICAL)
  5.  container-compose-hostpath-dangerous           (CRITICAL/HIGH/MEDIUM)
  6.  container-compose-no-hardening                 (MEDIUM)
  7.  container-compose-cap-add-dangerous            (HIGH)
  8.  container-compose-seccomp-unconfined           (HIGH)
  9.  container-compose-privileged-true              (CRITICAL)
  10. container-compose-host-network-bridge-leak     (MEDIUM)
  11. k8s-securitycontext-gap                        (HIGH/CRITICAL)
  12. k8s-clusterrolebinding-cluster-admin           (CRITICAL)
  13. docker-run-invocation-missing-hardening        (HIGH)
  14. oci-runtime-hook-injection                     (HIGH)

Public surface mirrors `agent_config_patterns.py` /
`auth_flow_patterns.py`:

  * Rule(id, name, severity, description, owasp_asi) — frozen NamedTuple
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple
  * RULES — ordered tuple of every rule
  * scan_text(text, *, file_kind="auto") -> list[Finding]
  * scan_dockerfile(text) -> list[Finding]
  * scan_compose(text) -> list[Finding]
  * scan_k8s(text) -> list[Finding]
  * scan_oci_config(text) -> list[Finding]
  * scan_shell_or_workflow(text) -> list[Finding]
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `scripts/lib/agent_config_patterns.Finding` so heartbeat detectors
    can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """Static rule metadata. Patterns live alongside in module scope
    because some rules need YAML/JSON walkers (no single regex)."""

    id: str
    name: str
    severity: str
    description: str
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile pattern with IGNORECASE+MULTILINE.

    Dockerfiles, compose YAML and shell commands are ASCII-by-convention
    so UNICODE is omitted. Every alternation branch is bounded — RE2
    safe. Catastrophic-backtrack rejected at module load.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# ---- OWASP ASI hints (matches existing taxonomy) ------------------------
#
# ASI-05 = Supply-chain / cross-tenant pivot (capabilities, namespaces,
#          host-network exposure)
# ASI-07 = Authority / authorisation gaps (privilege escalation, RBAC
#          over-grant, k8s SecurityContext gaps)


# ---- Shared constants ---------------------------------------------------


# Dangerous Linux capabilities. Each is documented in capabilities(7).
# Kept conservative — every entry is the canonical "give me root in
# the container" or "escape the namespace" cap.
DANGEROUS_CAPS: frozenset[str] = frozenset({
    "ALL",
    "SYS_ADMIN",        # mount(), swapon(), kexec, BPF, perf_event_open
    "SYS_PTRACE",       # debugger access to other PIDs
    "SYS_MODULE",       # insmod / modprobe arbitrary kernel modules
    "SYS_BOOT",         # kexec, reboot()
    "SYS_TIME",         # clock manipulation
    "SYS_RAWIO",        # raw I/O port access
    "SYS_CHROOT",       # break out of chroot
    "NET_ADMIN",        # modify routing, iptables
    "NET_RAW",          # raw sockets; ARP/DHCP spoofing
    "DAC_READ_SEARCH",  # bypass DAC read checks
    "DAC_OVERRIDE",     # bypass DAC checks
    "SETUID",           # broader than the suid bit
    "SETGID",
    "MKNOD",            # create device nodes
    "AUDIT_WRITE",      # write to kernel audit log
    "AUDIT_CONTROL",    # modify audit subsystem
})


# Host paths that map to "root-equivalent" when mounted (any rw, often
# even ro — several runtimes have had :ro→rw upgrade CVEs).
_HOSTPATH_CRITICAL: tuple[str, ...] = (
    "/",
    "/etc",
    "/root",
    "/var/lib/docker",
    "/var/lib/containerd",
    "/var/lib/kubelet",
)

_HOSTPATH_HIGH: tuple[str, ...] = (
    "/proc",
    "/sys",
    "/dev",
    "/boot",
)

# Medium severity — config / data leakage but not direct root.
_HOSTPATH_MEDIUM: tuple[str, ...] = (
    "/etc/kubernetes",
    "/var/run",
    "/etc/cni",
)

# Medium severity — user creds. Tilde-expanded by the caller.
_HOSTPATH_USER_MEDIUM: tuple[str, ...] = (
    ".ssh",
    ".aws",
    ".kube",
    ".docker",
    ".gnupg",
)

# Container runtime sockets — owning any of these = host root.
_RUNTIME_SOCKETS: tuple[str, ...] = (
    "/var/run/docker.sock",
    "/var/run/containerd/containerd.sock",
    "/var/run/crio/crio.sock",
    "/var/run/podman/podman.sock",
    "/var/lib/kubelet",
)

# Rootless docker socket lives at /run/user/<uid>/docker.sock — caught
# by suffix.
_RUNTIME_SOCKET_SUFFIXES: tuple[str, ...] = (
    "/docker.sock",
    "/containerd.sock",
    "/crio.sock",
    "/podman.sock",
    "/kubelet.sock",
)

# World-writable path prefixes an OCI runtime-spec hook must NOT point
# at — a hook binary placed here can be swapped by any process.
# CPV-skillaudit: module-level pure-literal tuple → abspath inert-data
# guard recognises these as membership-test prefixes (never opened),
# not an fs sink; the function-local form was conservatively kept MINOR.
_CONTAINER_HOOK_DANGER_PREFIXES: tuple[str, ...] = (
    "/tmp/", "/var/tmp/", "/dev/shm/", "/run/user/",
)


# Compose namespace-share keys → severity. host or "host:*" both qualify.
_NAMESPACE_HOST_SHARE_SEVERITY: dict[str, str] = {
    "pid": "CRITICAL",
    "network_mode": "CRITICAL",
    "ipc": "CRITICAL",
    "cgroup": "CRITICAL",
    "userns_mode": "HIGH",
    "uts": "MEDIUM",
}


# ---- Rule 1: Dockerfile setuid / setcap ---------------------------------


# Detects setuid / setgid bit assignment in a RUN directive, and the
# functionally equivalent `setcap cap_*=ep` / `setcap all=ep`. Bounded
# octal alternation (4xxx, 6xxx, 2xxx with optional sticky bit) — keeps
# the regex DOS-safe.
_DOCKERFILE_SETUID = _re(
    r"^\s*RUN\s+(?:[^\n]{0,400}?)\b("
    # chmod octal with setuid (4xxx) or setgid (2xxx) bit set
    r"chmod\s+(?:[2467][0-7]{3})\b"
    r"|"
    # chmod symbolic +s / u+s / g+s / o+s
    r"chmod\s+[ugoa]?\+s\b"
    r"|"
    # setcap cap_*=ep — the file-capability alternative to suid
    r"setcap\s+(?:cap_[a-z_]{1,40}|all)=ep\b"
    r")"
)


# ---- Rule 2: Dockerfile privileged LABEL / device requirement ----------


# Detects images that *self-document* a privileged-runtime requirement
# via LABEL keys or by referencing host-only device nodes inside
# RUN/COPY/ADD/VOLUME directives.
_DOCKERFILE_PRIVILEGED_LABEL = _re(
    r"^\s*LABEL\s+[^\n]{0,200}?\b("
    r"privileged"
    r"|requires?_cap_(?:sys_admin|sys_ptrace|sys_module|net_admin|net_raw)"
    r"|requires?[_-]privileged"
    r"|run[_-]?as[_-]privileged"
    r")\b"
)

# Host-device dependencies. /dev/kvm is legitimate for VM workloads but
# is a strong signal nonetheless — flag MEDIUM through Rule 2.
_DOCKERFILE_HOST_DEVICE_REF = _re(
    r"^\s*(?:RUN|VOLUME|COPY|ADD)\s+[^\n]{0,300}?"
    r"(?:/dev/kvm|/dev/mem|/dev/kmem|/dev/kmsg|/dev/sd[a-z]"
    r"|/sys/kernel/debug|/sys/fs/cgroup|/sys/fs/bpf)\b"
)


# ---- Rule 13: docker-run invocation missing hardening -------------------


# Plain-text trigger; the structural analysis happens in
# `_scan_docker_run_invocation`. We only need a starting point —
# `docker run` anywhere on a line.
_DOCKER_RUN_TRIGGER = _re(
    r"^\s*(?:\$\s+)?(?:sudo\s+)?docker\s+run\b"
)


# ---- Compose / k8s utility: rough YAML pre-check ------------------------


# Cheap regex to decide "this YAML smells like compose" (top-level
# `services:` key) or "this smells like k8s" (`apiVersion:` +
# `kind: Pod|Deployment|...`). Used by scan_text() to dispatch to the
# correct YAML walker when called with file_kind="auto".
_COMPOSE_HINT = _re(r"^services\s*:")
_K8S_HINT = _re(r"^(?:apiVersion|kind)\s*:")
_DOCKERFILE_HINT = _re(r"^\s*(?:FROM|RUN|COPY|ADD|CMD|ENTRYPOINT|LABEL)\s+")
_OCI_HINT = _re(r'^\s*\{\s*"ociVersion"\s*:')


# ---- The rule catalogue -------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="container-dockerfile-setuid-binary",
        name="Dockerfile installs setuid / setgid / file-cap binary",
        severity="HIGH",
        description=(
            "Dockerfile RUN directive sets the setuid (4xxx) or setgid "
            "(2xxx) octal bit, applies symbolic `+s` / `u+s` / `g+s`, "
            "or grants file capabilities via `setcap cap_*=ep`. A "
            "setuid binary inside the image is a local-root primitive; "
            "combined with a writable host-path mount it amplifies "
            "into a host escalation."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="container-dockerfile-privileged-label",
        name="Dockerfile self-documents privileged-runtime requirement",
        severity="HIGH",
        description=(
            "Dockerfile LABEL declares the image expects to run "
            "privileged or with elevated Linux capabilities (SYS_ADMIN, "
            "SYS_PTRACE, SYS_MODULE, NET_ADMIN, NET_RAW). RUN / COPY / "
            "VOLUME referencing host-only device nodes (`/dev/kvm`, "
            "`/dev/mem`, `/sys/kernel/debug`, `/sys/fs/cgroup`, "
            "`/sys/fs/bpf`) is the same signal."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="container-compose-docker-sock-mount",
        name="Compose service mounts container-runtime control socket",
        severity="CRITICAL",
        description=(
            "Compose service binds the host docker / containerd / "
            "cri-o / podman / kubelet socket into the container. Any "
            "process with access to the socket can launch a new "
            "container that mounts the host root filesystem — total "
            "host compromise. Read-only mounts are equivalent (still "
            "permits Docker API calls)."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="container-compose-host-namespace-share",
        name="Compose service shares host PID / network / IPC / cgroup namespace",
        severity="CRITICAL",
        description=(
            "Compose service sets `pid: host`, `network_mode: host`, "
            "`ipc: host`, `userns_mode: host`, `uts: host`, or "
            "`cgroup: host`. Each disables the corresponding namespace "
            "isolation. `pid:host` enables CVE-2019-5736-style "
            "`nsenter` to host PID 1; `cgroup:host` enables the "
            "release_agent escape (CVE-2022-0492)."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="container-compose-hostpath-dangerous",
        name="Compose volume bind-mounts dangerous host path",
        severity="CRITICAL",
        description=(
            "Compose volume binds a host path that maps to "
            "root-equivalent access (`/`, `/etc`, `/root`, "
            "`/var/lib/docker`, `/var/lib/kubelet`) or kernel/runtime "
            "surface (`/proc`, `/sys`, `/dev`, `/boot`). `ro` mounts "
            "still leak secrets and several runtimes have had "
            ":ro→:rw upgrade CVEs."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="container-compose-no-hardening",
        name="Compose service has no sandbox hardening flags",
        severity="MEDIUM",
        description=(
            "Compose service omits ALL of `cap_drop: [ALL]`, "
            "`read_only: true`, `security_opt: no-new-privileges:true`, "
            "and non-root `user:`. This is the default-insecure compose "
            "pattern. Configuration smell rather than direct escape."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="container-compose-cap-add-dangerous",
        name="Compose service adds dangerous Linux capability",
        severity="HIGH",
        description=(
            "Compose `cap_add:` grants a capability from the "
            "dangerous-set (`SYS_ADMIN`, `SYS_PTRACE`, `SYS_MODULE`, "
            "`NET_ADMIN`, `NET_RAW`, `DAC_OVERRIDE`, `SETUID`, "
            "`MKNOD`, `ALL`, …). Each capability removes a kernel "
            "isolation boundary."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="container-compose-seccomp-unconfined",
        name="Compose service disables seccomp / AppArmor / SELinux",
        severity="HIGH",
        description=(
            "Compose `security_opt:` sets `seccomp:unconfined`, "
            "`apparmor:unconfined`, `label:disable`, or explicitly "
            "`no-new-privileges:false`. The kernel system-call filter "
            "is OFF — every syscall becomes reachable, including the "
            "ones the standard profile blocks."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="container-compose-privileged-true",
        name="Compose service is privileged / no-new-privileges disabled",
        severity="CRITICAL",
        description=(
            "Compose service sets `privileged: true` (grants all "
            "capabilities + all devices + disables security profiles) "
            "or explicitly `no-new-privileges:false`. Literal host "
            "root: the container can mount /, load kernel modules, "
            "and access every host device."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="container-compose-host-network-bridge-leak",
        name="Compose exposes host loopback or unbound LAN port",
        severity="MEDIUM",
        description=(
            "Compose `extra_hosts:` contains "
            "`host.docker.internal:host-gateway` (routable host "
            "access) or `ports:` exposes well-known service ports "
            "(5432, 6379, 27017, 9200) without binding to 127.0.0.1. "
            "Credential-exposure amplifier rather than direct escape."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="k8s-securitycontext-gap",
        name="Kubernetes Pod / Deployment has SecurityContext gap",
        severity="HIGH",
        description=(
            "Kubernetes pod spec sets `privileged: true`, "
            "`allowPrivilegeEscalation: true`, `runAsNonRoot: false`, "
            "`hostNetwork: true`, `hostPID: true`, `hostIPC: true`, "
            "or mounts a dangerous host path via `hostPath`. The "
            "seccompProfile / appArmorProfile may also be "
            "`Unconfined`. Capabilities.drop missing `ALL` is "
            "flagged."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-clusterrolebinding-cluster-admin",
        name="Kubernetes ClusterRoleBinding grants cluster-admin",
        severity="CRITICAL",
        description=(
            "ClusterRoleBinding (or RoleBinding) binds the "
            "`cluster-admin` ClusterRole to a ServiceAccount, to "
            "`system:masters`, to `system:authenticated` (every "
            "user), or to `system:unauthenticated` (anonymous). "
            "Equivalent: a ClusterRole with `verbs: ['*']`, "
            "`resources: ['*']`, `apiGroups: ['*']` (triple-star)."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="docker-run-invocation-missing-hardening",
        name="`docker run` invocation omits hardening flags",
        severity="HIGH",
        description=(
            "Shell script / Makefile / GitHub Actions workflow / "
            "README contains a `docker run` invocation that omits 2+ "
            "of `--cap-drop=ALL`, `--security-opt=no-new-privileges`, "
            "`--read-only`, non-root `--user`. Sealed-env corpus "
            "ships the gold-standard hardened invocation; the "
            "inverse is the detection rule."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="oci-runtime-hook-injection",
        name="OCI runtime hook points at writable / world-writable path",
        severity="HIGH",
        description=(
            "OCI runtime-spec `config.json` declares a "
            "`hooks.prestart` / `poststart` / `poststop` / "
            "`createRuntime` entry whose `path:` resolves to "
            "`/tmp/`, `/var/tmp/`, `/dev/shm/`, or contains `/..` "
            "traversal. Hooks run as host root with no container "
            "isolation; a writable path is a TOCTOU + escape "
            "primitive."
        ),
        owasp_asi="ASI-07",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert string offset → (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _trunc(s: str, n: int = 200) -> str:
    """Truncate matched_text for reporting."""
    return s if len(s) <= n else s[:n] + "…"


def _yaml_load_all(text: str) -> list[Any]:
    """Best-effort multi-doc YAML load. Returns a flat list of docs.

    Returns [] on import-error or parse-error — fail-soft. Callers
    fall back to regex-only scanning when YAML is unavailable.
    """
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return []
    try:
        return [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError:
        return []


def _normalize_cap(c: str) -> str:
    """Normalise a capability string for comparison.

    'cap_sys_admin' / 'CAP_SYS_ADMIN' / 'SYS_ADMIN' / 'sys_admin' all
    collapse to 'SYS_ADMIN'.
    """
    return c.strip().upper().replace("CAP_", "")


def _find_line_of_key(text: str, key: str) -> int:
    """Best-effort line number for a top-level YAML key inside a doc.

    Used to attach a sensible line number to YAML-walker findings.
    Falls back to 1 when not found.
    """
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:", re.MULTILINE)
    m = pat.search(text)
    return text[:m.start()].count("\n") + 1 if m else 1


# ---- Rule 1: Dockerfile setuid scanner ----------------------------------


def _scan_dockerfile_setuid(text: str, findings: list[Finding]) -> None:
    """Rule 1 — detect setuid / setgid / setcap inside RUN directives."""
    rule = next(r for r in RULES if r.id == "container-dockerfile-setuid-binary")
    for m in _DOCKERFILE_SETUID.finditer(text):
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id=rule.id,
            line=line, column=col,
            matched_text=_trunc(m.group(0)),
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))


# ---- Rule 2: Dockerfile privileged-label / host-device scanner ----------


def _scan_dockerfile_privileged_label(text: str, findings: list[Finding]) -> None:
    """Rule 2 — detect LABEL self-declaring privileged + host devices."""
    rule = next(r for r in RULES if r.id == "container-dockerfile-privileged-label")
    for m in _DOCKERFILE_PRIVILEGED_LABEL.finditer(text):
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id=rule.id,
            line=line, column=col,
            matched_text=_trunc(m.group(0)),
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))
    for m in _DOCKERFILE_HOST_DEVICE_REF.finditer(text):
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id=rule.id,
            line=line, column=col,
            matched_text=_trunc(m.group(0)),
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))


# ---- Compose YAML walker (rules 3-10) -----------------------------------


def _compose_services(doc: Any) -> dict[str, dict[str, Any]]:
    """Extract the services mapping; return {} when shape is unexpected."""
    if not isinstance(doc, dict):
        return {}
    svcs = doc.get("services")
    if not isinstance(svcs, dict):
        return {}
    # services.<name> must itself be a mapping; skip otherwise.
    return {n: s for n, s in svcs.items() if isinstance(s, dict)}


def _iter_volumes(svc: dict[str, Any]) -> list[str | dict[str, Any]]:
    """Volumes can be short-form strings or long-form dicts.

    Returns the raw entries (string OR dict); callers do shape-checks.
    """
    vols = svc.get("volumes")
    if not isinstance(vols, list):
        return []
    return [v for v in vols if isinstance(v, (str, dict))]


def _volume_source(entry: str | dict[str, Any]) -> str:
    """Return the host-side source for a volume entry.

    Short-form: 'src:dst[:mode]'. Long-form: {type: bind, source: src,
    target: dst}. Returns "" when not a bind-mount.
    """
    if isinstance(entry, str):
        # short form: src:dst[:mode] — split max 2 (mode optional).
        parts = entry.split(":", 2)
        if len(parts) >= 2:
            return parts[0]
        return ""
    if isinstance(entry, dict):
        if entry.get("type") in (None, "bind"):
            src = entry.get("source")
            return src if isinstance(src, str) else ""
    return ""


def _classify_hostpath(path: str) -> str | None:
    """Classify a host path → severity or None when benign.

    Order: CRITICAL > HIGH > MEDIUM. Path matching is left-anchored
    string equality OR prefix-match on '/' so `/etc` catches `/etc`
    AND `/etc/passwd` but NOT `/etcd`.
    """
    if not path or (not path.startswith("/") and not path.startswith("~")):
        # Non-host paths (named volumes, relative). Skip.
        return None
    # Tilde-expand ~ paths first.
    if path.startswith("~/"):
        tail = path[2:]
        for hit in _HOSTPATH_USER_MEDIUM:
            if tail == hit or tail.startswith(hit + "/"):
                return "MEDIUM"
        return None
    # Exact "/" mount = filesystem root.
    if path == "/":
        return "CRITICAL"
    # Most specific first (longest prefix wins).
    sorted_critical = sorted(_HOSTPATH_CRITICAL, key=len, reverse=True)
    sorted_high = sorted(_HOSTPATH_HIGH, key=len, reverse=True)
    sorted_medium = sorted(_HOSTPATH_MEDIUM, key=len, reverse=True)
    for hit in sorted_medium:
        if path == hit or path.startswith(hit + "/"):
            return "MEDIUM"
    for hit in sorted_high:
        if path == hit or path.startswith(hit + "/"):
            return "HIGH"
    for hit in sorted_critical:
        if hit == "/":
            continue  # already handled
        if path == hit or path.startswith(hit + "/"):
            return "CRITICAL"
    return None


def _is_runtime_socket(path: str) -> bool:
    """True if path is a container-runtime control socket."""
    if path in _RUNTIME_SOCKETS:
        return True
    return any(path.endswith(suf) for suf in _RUNTIME_SOCKET_SUFFIXES)


def _scan_compose_service(  # noqa: PLR0912 - linear branch per rule, intentional
    svc_name: str,
    svc: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
) -> None:
    """Apply rules 3-10 to a single service mapping."""
    # Rule 3 — docker.sock mount.
    rule3 = next(r for r in RULES if r.id == "container-compose-docker-sock-mount")
    for entry in _iter_volumes(svc):
        src = _volume_source(entry)
        if _is_runtime_socket(src):
            findings.append(Finding(
                rule_id=rule3.id, line=line_hint, column=1,
                matched_text=_trunc(f"{svc_name}: {src}"),
                severity=rule3.severity, description=rule3.description,
                owasp_asi=rule3.owasp_asi,
            ))

    # Rule 4 — host namespace share.
    rule4 = next(r for r in RULES if r.id == "container-compose-host-namespace-share")
    for key, sev in _NAMESPACE_HOST_SHARE_SEVERITY.items():
        val = svc.get(key)
        if isinstance(val, str) and (val == "host" or val.startswith("host:")):
            findings.append(Finding(
                rule_id=rule4.id, line=line_hint, column=1,
                matched_text=_trunc(f"{svc_name}: {key}={val}"),
                severity=sev, description=rule4.description,
                owasp_asi=rule4.owasp_asi,
            ))

    # Rule 5 — dangerous hostpath.
    rule5 = next(r for r in RULES if r.id == "container-compose-hostpath-dangerous")
    for entry in _iter_volumes(svc):
        src = _volume_source(entry)
        if _is_runtime_socket(src):
            continue  # already covered by rule 3
        hostpath_sev = _classify_hostpath(src)
        if hostpath_sev is not None:
            findings.append(Finding(
                rule_id=rule5.id, line=line_hint, column=1,
                matched_text=_trunc(f"{svc_name}: {src}"),
                severity=hostpath_sev, description=rule5.description,
                owasp_asi=rule5.owasp_asi,
            ))

    # Rule 7 — cap_add dangerous.
    rule7 = next(r for r in RULES if r.id == "container-compose-cap-add-dangerous")
    raw_caps = svc.get("cap_add")
    if isinstance(raw_caps, list):
        added = {_normalize_cap(c) for c in raw_caps if isinstance(c, str)}
        bad = added & DANGEROUS_CAPS
        for cap in sorted(bad):
            sev = "HIGH" if cap in {"SYS_ADMIN", "SYS_MODULE", "ALL"} else "MEDIUM"
            findings.append(Finding(
                rule_id=rule7.id, line=line_hint, column=1,
                matched_text=_trunc(f"{svc_name}: cap_add={cap}"),
                severity=sev, description=rule7.description,
                owasp_asi=rule7.owasp_asi,
            ))

    # Rule 8 — seccomp / apparmor / selinux unconfined.
    rule8 = next(r for r in RULES if r.id == "container-compose-seccomp-unconfined")
    sec_opts = svc.get("security_opt") or []
    if isinstance(sec_opts, list):
        for s in sec_opts:
            if not isinstance(s, str):
                continue
            norm = s.replace("=", ":").lower().strip()
            if norm in {
                "seccomp:unconfined",
                "apparmor:unconfined",
                "label:disable",
                "no-new-privileges:false",
            }:
                findings.append(Finding(
                    rule_id=rule8.id, line=line_hint, column=1,
                    matched_text=_trunc(f"{svc_name}: {s}"),
                    severity=rule8.severity, description=rule8.description,
                    owasp_asi=rule8.owasp_asi,
                ))
            elif norm.startswith(("seccomp:/", "seccomp:./")):
                # Custom seccomp profile path — MEDIUM, needs review.
                findings.append(Finding(
                    rule_id=rule8.id, line=line_hint, column=1,
                    matched_text=_trunc(f"{svc_name}: custom-seccomp:{s}"),
                    severity="MEDIUM", description=rule8.description,
                    owasp_asi=rule8.owasp_asi,
                ))

    # Rule 9 — privileged: true.
    rule9 = next(r for r in RULES if r.id == "container-compose-privileged-true")
    if svc.get("privileged") is True:
        findings.append(Finding(
            rule_id=rule9.id, line=line_hint, column=1,
            matched_text=_trunc(f"{svc_name}: privileged=true"),
            severity=rule9.severity, description=rule9.description,
            owasp_asi=rule9.owasp_asi,
        ))
    # Explicit no-new-privileges:false also fires rule 9.
    if isinstance(sec_opts, list):
        for s in sec_opts:
            if isinstance(s, str) and s.replace("=", ":").lower().strip() == "no-new-privileges:false":
                findings.append(Finding(
                    rule_id=rule9.id, line=line_hint, column=1,
                    matched_text=_trunc(f"{svc_name}: {s}"),
                    severity=rule9.severity, description=rule9.description,
                    owasp_asi=rule9.owasp_asi,
                ))

    # Rule 10 — extra_hosts + unbound LAN ports.
    rule10 = next(r for r in RULES if r.id == "container-compose-host-network-bridge-leak")
    extra = svc.get("extra_hosts") or []
    if isinstance(extra, list):
        for h in extra:
            if isinstance(h, str) and "host-gateway" in h.lower():
                findings.append(Finding(
                    rule_id=rule10.id, line=line_hint, column=1,
                    matched_text=_trunc(f"{svc_name}: extra_hosts={h}"),
                    severity=rule10.severity, description=rule10.description,
                    owasp_asi=rule10.owasp_asi,
                ))
    # Ports bound to 0.0.0.0 implicitly.
    ports = svc.get("ports") or []
    well_known = {"5432", "6379", "27017", "9200", "3306", "5984"}
    if isinstance(ports, list):
        for p in ports:
            if isinstance(p, str):
                # Forms: "5432:5432", "127.0.0.1:5432:5432", "5432".
                parts = p.split(":")
                if len(parts) == 1:
                    continue  # single port = container-only
                host_part = parts[0]
                if host_part in well_known:
                    findings.append(Finding(
                        rule_id=rule10.id, line=line_hint, column=1,
                        matched_text=_trunc(f"{svc_name}: ports={p}"),
                        severity=rule10.severity, description=rule10.description,
                        owasp_asi=rule10.owasp_asi,
                    ))

    # Rule 6 — no hardening (fires LAST, only when none of the above
    # protective patterns are present).
    rule6 = next(r for r in RULES if r.id == "container-compose-no-hardening")
    has_cap_drop_all = False
    drop_list = svc.get("cap_drop") or []
    if isinstance(drop_list, list):
        has_cap_drop_all = any(
            isinstance(c, str) and _normalize_cap(c) == "ALL" for c in drop_list
        )
    has_readonly = svc.get("read_only") is True
    has_nnp = False
    if isinstance(sec_opts, list):
        has_nnp = any(
            isinstance(s, str)
            and s.replace("=", ":").lower().strip().startswith("no-new-privileges:true")
            for s in sec_opts
        )
    user_val = svc.get("user")
    has_nonroot_user = (
        isinstance(user_val, str) and user_val not in {"root", "0", "0:0"}
        and not user_val.startswith("0:")
    )
    if not (has_cap_drop_all or has_readonly or has_nnp or has_nonroot_user):
        # Only fire when the service has an image — empty stubs from
        # YAML tests shouldn't flag.
        if "image" in svc or "build" in svc:
            findings.append(Finding(
                rule_id=rule6.id, line=line_hint, column=1,
                matched_text=_trunc(f"{svc_name}: no hardening"),
                severity=rule6.severity, description=rule6.description,
                owasp_asi=rule6.owasp_asi,
            ))


# ---- k8s walker (rules 11, 12) ------------------------------------------


_K8S_POD_KINDS = frozenset({
    "Pod", "Deployment", "DaemonSet", "StatefulSet",
    "Job", "CronJob", "ReplicaSet",
})


def _k8s_pod_spec(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Return the pod spec from a k8s doc, regardless of wrapping kind.

    Callers guarantee `doc` is a dict via an isinstance check before
    calling — this function trusts that contract.
    """
    kind = doc.get("kind")
    if kind == "Pod":
        spec = doc.get("spec")
        return spec if isinstance(spec, dict) else None
    if kind in _K8S_POD_KINDS:
        # Deployment/DaemonSet/StatefulSet/Job/CronJob/ReplicaSet wrap
        # the pod in spec.template.spec.
        spec_outer = doc.get("spec")
        if not isinstance(spec_outer, dict):
            return None
        if kind == "CronJob":
            # CronJob wraps one extra layer: spec.jobTemplate.spec.template.spec
            job_template = spec_outer.get("jobTemplate")
            if not isinstance(job_template, dict):
                return None
            inner = job_template.get("spec")
            if not isinstance(inner, dict):
                return None
            template = inner.get("template")
        else:
            template = spec_outer.get("template")
        if not isinstance(template, dict):
            return None
        spec_inner = template.get("spec")
        return spec_inner if isinstance(spec_inner, dict) else None
    return None


def _scan_k8s_pod(
    pod_spec: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
    name: str = "<pod>",
) -> None:
    """Apply rule 11 (SecurityContext gap) to a single pod spec."""
    rule = next(r for r in RULES if r.id == "k8s-securitycontext-gap")

    # Top-level pod fields.
    if pod_spec.get("hostNetwork") is True:
        findings.append(Finding(
            rule_id=rule.id, line=line_hint, column=1,
            matched_text=_trunc(f"{name}: hostNetwork=true"),
            severity="HIGH", description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))
    if pod_spec.get("hostPID") is True:
        findings.append(Finding(
            rule_id=rule.id, line=line_hint, column=1,
            matched_text=_trunc(f"{name}: hostPID=true"),
            severity="HIGH", description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))
    if pod_spec.get("hostIPC") is True:
        findings.append(Finding(
            rule_id=rule.id, line=line_hint, column=1,
            matched_text=_trunc(f"{name}: hostIPC=true"),
            severity="HIGH", description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    # Pod-level SecurityContext.
    pod_sc = pod_spec.get("securityContext") or {}
    if isinstance(pod_sc, dict):
        if pod_sc.get("runAsNonRoot") is False:
            findings.append(Finding(
                rule_id=rule.id, line=line_hint, column=1,
                matched_text=_trunc(f"{name}: runAsNonRoot=false"),
                severity="MEDIUM", description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
        if pod_sc.get("runAsUser") == 0:
            findings.append(Finding(
                rule_id=rule.id, line=line_hint, column=1,
                matched_text=_trunc(f"{name}: runAsUser=0"),
                severity="MEDIUM", description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))

    # Volumes — hostPath checks.
    volumes = pod_spec.get("volumes") or []
    if isinstance(volumes, list):
        for v in volumes:
            if not isinstance(v, dict):
                continue
            hp = v.get("hostPath")
            if isinstance(hp, dict):
                path = hp.get("path", "")
                if isinstance(path, str):
                    sev = _classify_hostpath(path)
                    if sev is not None:
                        findings.append(Finding(
                            rule_id=rule.id, line=line_hint, column=1,
                            matched_text=_trunc(f"{name}: hostPath={path}"),
                            severity=sev, description=rule.description,
                            owasp_asi=rule.owasp_asi,
                        ))

    # Containers — per-container security context.
    for c_key in ("containers", "initContainers"):
        containers = pod_spec.get(c_key) or []
        if not isinstance(containers, list):
            continue
        for c in containers:
            if not isinstance(c, dict):
                continue
            c_name = c.get("name", "<container>")
            sc = c.get("securityContext") or {}
            if not isinstance(sc, dict):
                continue
            if sc.get("privileged") is True:
                findings.append(Finding(
                    rule_id=rule.id, line=line_hint, column=1,
                    matched_text=_trunc(f"{name}/{c_name}: privileged=true"),
                    severity="CRITICAL", description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))
            if sc.get("allowPrivilegeEscalation") is True:
                findings.append(Finding(
                    rule_id=rule.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        f"{name}/{c_name}: allowPrivilegeEscalation=true"),
                    severity="HIGH", description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))
            if sc.get("readOnlyRootFilesystem") is False:
                findings.append(Finding(
                    rule_id=rule.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        f"{name}/{c_name}: readOnlyRootFilesystem=false"),
                    severity="MEDIUM", description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))
            # Capabilities.add — dangerous set.
            caps = sc.get("capabilities") or {}
            if isinstance(caps, dict):
                add = caps.get("add") or []
                if isinstance(add, list):
                    added = {
                        _normalize_cap(c2) for c2 in add if isinstance(c2, str)
                    }
                    bad = added & DANGEROUS_CAPS
                    for cap in sorted(bad):
                        findings.append(Finding(
                            rule_id=rule.id, line=line_hint, column=1,
                            matched_text=_trunc(
                                f"{name}/{c_name}: capabilities.add={cap}"),
                            severity="HIGH", description=rule.description,
                            owasp_asi=rule.owasp_asi,
                        ))
            # seccompProfile / appArmorProfile Unconfined.
            seccomp = sc.get("seccompProfile") or {}
            if isinstance(seccomp, dict) and seccomp.get("type") == "Unconfined":
                findings.append(Finding(
                    rule_id=rule.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        f"{name}/{c_name}: seccompProfile=Unconfined"),
                    severity="HIGH", description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))
            apparmor = sc.get("appArmorProfile") or {}
            if isinstance(apparmor, dict) and apparmor.get("type") == "Unconfined":
                findings.append(Finding(
                    rule_id=rule.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        f"{name}/{c_name}: appArmorProfile=Unconfined"),
                    severity="HIGH", description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))


def _scan_k8s_rbac(doc: dict[str, Any], findings: list[Finding], line_hint: int) -> None:
    """Apply rule 12 (cluster-admin binding / triple-star).

    Callers guarantee `doc` is a dict via an isinstance check before
    calling — this function trusts that contract.
    """
    rule = next(r for r in RULES if r.id == "k8s-clusterrolebinding-cluster-admin")
    kind = doc.get("kind")
    name = (doc.get("metadata") or {}).get("name", "<binding>")
    if kind in {"ClusterRoleBinding", "RoleBinding"}:
        ref = doc.get("roleRef") or {}
        if isinstance(ref, dict) and ref.get("name") == "cluster-admin":
            findings.append(Finding(
                rule_id=rule.id, line=line_hint, column=1,
                matched_text=_trunc(f"{kind} {name}: roleRef.name=cluster-admin"),
                severity=rule.severity, description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
        subjects = doc.get("subjects") or []
        if isinstance(subjects, list):
            for s in subjects:
                if not isinstance(s, dict):
                    continue
                s_name = s.get("name", "")
                s_kind = s.get("kind", "")
                if s_kind == "Group" and s_name in {
                    "system:masters",
                    "system:authenticated",
                    "system:unauthenticated",
                }:
                    findings.append(Finding(
                        rule_id=rule.id, line=line_hint, column=1,
                        matched_text=_trunc(
                            f"{kind} {name}: subject Group {s_name}"),
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    ))
    elif kind in {"ClusterRole", "Role"}:
        rules = doc.get("rules") or []
        if not isinstance(rules, list):
            return
        for r in rules:
            if not isinstance(r, dict):
                continue
            verbs = r.get("verbs") or []
            resources = r.get("resources") or []
            api_groups = r.get("apiGroups") or []
            if (
                isinstance(verbs, list) and "*" in verbs
                and isinstance(resources, list) and "*" in resources
                and isinstance(api_groups, list) and "*" in api_groups
            ):
                findings.append(Finding(
                    rule_id=rule.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        f"{kind} {name}: triple-star (verbs/resources/apiGroups)"
                    ),
                    severity=rule.severity, description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))


# ---- Rule 13: docker run invocation -------------------------------------


def _scan_docker_run_invocation(text: str, findings: list[Finding]) -> None:
    """Rule 13 — `docker run` argv missing hardening flags.

    We *cannot* shlex.split across line continuations reliably, so we
    extract the contiguous block of the invocation (collapse trailing
    `\\\n` continuations) before tokenising.
    """
    rule = next(r for r in RULES if r.id == "docker-run-invocation-missing-hardening")
    for m in _DOCKER_RUN_TRIGGER.finditer(text):
        line, col = _line_col(text, m.start())
        # Extract from match start to either end-of-line that does NOT
        # end with `\` continuation, or end-of-text.
        start = m.end()
        end = start
        max_chars = 4000  # bound the read
        i = start
        while i < len(text) and (i - start) < max_chars:
            nl = text.find("\n", i)
            if nl == -1:
                end = len(text)
                break
            prefix = text[i:nl].rstrip()
            i = nl + 1
            if prefix.endswith("\\"):
                continue
            end = nl
            break
        block = text[m.start():end]
        # Collapse continuations to one line for tokenisation.
        joined = re.sub(r"\\\n", " ", block)
        try:
            argv = shlex.split(joined, comments=False, posix=True)
        except ValueError:
            argv = joined.split()
        # The token immediately after `docker run` is everything after.
        # We only need to find which hardening tokens appear anywhere.
        needed = {"--cap-drop", "--security-opt", "--read-only", "--user"}
        seen = set()
        for tok in argv:
            for n in needed:
                if tok == n or tok.startswith(n + "="):
                    seen.add(n)
        missing = sorted(needed - seen)
        if len(missing) >= 2:
            findings.append(Finding(
                rule_id=rule.id, line=line, column=col,
                matched_text=_trunc(
                    f"docker run missing: {', '.join(missing)}"),
                severity=rule.severity, description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
        elif len(missing) == 1:
            findings.append(Finding(
                rule_id=rule.id, line=line, column=col,
                matched_text=_trunc(
                    f"docker run missing: {', '.join(missing)}"),
                severity="MEDIUM", description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))


# ---- Rule 14: OCI runtime spec hooks ------------------------------------


def _scan_oci_hooks(text: str, findings: list[Finding]) -> None:
    """Rule 14 — OCI runtime spec hooks pointing to writable paths."""
    rule = next(r for r in RULES if r.id == "oci-runtime-hook-injection")
    try:
        doc = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return
    if not isinstance(doc, dict):
        return
    hooks = doc.get("hooks") or {}
    if not isinstance(hooks, dict):
        return
    for kind in ("prestart", "poststart", "poststop", "createRuntime"):
        entries = hooks.get(kind) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path", "")
            if not isinstance(path, str):
                continue
            if path.startswith(_CONTAINER_HOOK_DANGER_PREFIXES) or "/.." in path:
                findings.append(Finding(
                    rule_id=rule.id, line=1, column=1,
                    matched_text=_trunc(f"hooks.{kind}: {path}"),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                ))


# ---- Public scan entry points -------------------------------------------


def scan_dockerfile(text: str) -> list[Finding]:
    """Apply Dockerfile rules (1, 2)."""
    findings: list[Finding] = []
    _scan_dockerfile_setuid(text, findings)
    _scan_dockerfile_privileged_label(text, findings)
    return findings


def scan_compose(text: str) -> list[Finding]:
    """Apply compose rules (3-10) — YAML-walker based."""
    findings: list[Finding] = []
    docs = _yaml_load_all(text)
    for doc in docs:
        services = _compose_services(doc)
        for svc_name, svc in services.items():
            line_hint = _find_line_of_key(text, svc_name)
            _scan_compose_service(svc_name, svc, findings, line_hint)
    return findings


def scan_k8s(text: str) -> list[Finding]:
    """Apply k8s rules (11, 12) — YAML-walker based."""
    findings: list[Finding] = []
    docs = _yaml_load_all(text)
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind", "")
        # Best-effort line hint — use the doc's metadata.name occurrence.
        meta = doc.get("metadata") or {}
        name = meta.get("name") if isinstance(meta, dict) else None
        line_hint = _find_line_of_key(text, "kind") if not name else \
            _find_line_of_key(text, str(name))
        if kind in _K8S_POD_KINDS:
            pod_spec = _k8s_pod_spec(doc)
            if pod_spec is not None:
                _scan_k8s_pod(pod_spec, findings, line_hint, name=str(name or kind))
        elif kind in {"ClusterRoleBinding", "RoleBinding",
                      "ClusterRole", "Role"}:
            _scan_k8s_rbac(doc, findings, line_hint)
    return findings


def scan_oci_config(text: str) -> list[Finding]:
    """Apply OCI runtime-spec rules (14)."""
    findings: list[Finding] = []
    _scan_oci_hooks(text, findings)
    return findings


def scan_shell_or_workflow(text: str) -> list[Finding]:
    """Apply rules that need shell-script context (13)."""
    findings: list[Finding] = []
    _scan_docker_run_invocation(text, findings)
    return findings


def _detect_kind(text: str) -> str:
    """Sniff the file kind from content.

    Order: OCI (json prefix is strongest) > Dockerfile > compose > k8s
    > shell/markdown (always fall through for docker-run scanning).
    """
    if _OCI_HINT.search(text[:200]) is not None:
        return "oci"
    if _DOCKERFILE_HINT.search(text) is not None:
        return "dockerfile"
    if _COMPOSE_HINT.search(text) is not None:
        return "compose"
    if _K8S_HINT.search(text) is not None:
        return "k8s"
    return "shell"


def scan_text(text: str, *, file_kind: str = "auto") -> list[Finding]:
    """Top-level dispatcher.

    file_kind: "auto" (sniff), "dockerfile", "compose", "k8s", "oci",
               "shell".

    Findings come out sorted by (line, column, rule_id) and deduped on
    that triple. Every dispatch path additionally scans for
    `docker run` invocations — README.md / workflow files commonly
    embed both shell blocks and inline compose snippets.
    """
    if not text:
        return []
    if file_kind == "auto":
        file_kind = _detect_kind(text)

    findings: list[Finding] = []
    if file_kind == "dockerfile":
        findings.extend(scan_dockerfile(text))
    elif file_kind == "compose":
        findings.extend(scan_compose(text))
    elif file_kind == "k8s":
        findings.extend(scan_k8s(text))
    elif file_kind == "oci":
        findings.extend(scan_oci_config(text))

    # docker run invocations can appear in any file kind.
    findings.extend(scan_shell_or_workflow(text))

    # Dedupe on (rule_id, line, column, matched_text) — different rules
    # at the same (line, col) are intentional (cross-rule chains).
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
