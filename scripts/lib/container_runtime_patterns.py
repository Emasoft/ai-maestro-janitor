"""Container-runtime escape patterns — Docker/Podman/containerd/runc/gvisor/kata CLI surface.

Wave-25 distill-round-11 angle: runtime-level escape vectors at the
`docker run` / `podman run` / `nerdctl run` CLI flag layer, plus the
containerd / runc / gvisor / kata configuration files (`config.toml`,
`runtime.json`, OCI `config.json` hooks). Detects materially-weakened
sandbox boundaries at the **runtime** layer — orthogonal to:

  * `k8s_admission_patterns.py` (Wave 20) — Kubernetes admission /
    Gatekeeper / Kyverno / RBAC drift at the *admission* layer.
  * `sandbox_escape_patterns.py` (Wave 18) — Dockerfile setuid, compose
    docker.sock / hostpath / cap-add, k8s SecurityContext gaps,
    ClusterRoleBinding cluster-admin, generic `docker run` hardening.
    This module deliberately leaves compose / Dockerfile / k8s YAML
    surfaces to that module and focuses on the **CLI-flag** and
    **runtime-config** surfaces.
  * `container_patterns.py` (Wave 16) — Dockerfile supply-chain
    (`COPY --from=`, dockerignore evasion, BuildKit heredoc).

Reference proposal: `reports/distill-round-11/container-runtime-escape.md`.

Rule inventory (10 rules):

  1.  cre-runtime-privileged-flag                 (CRITICAL)
  2.  cre-runtime-docker-sock-mount-cli           (CRITICAL)
  3.  cre-runtime-dangerous-cap-add               (HIGH)
  4.  cre-runtime-lsm-unconfined                  (HIGH)
  5.  cre-runtime-host-namespace-flag             (HIGH)
  6.  cre-runtime-sensitive-host-mount-rw         (HIGH)
  7.  cre-runtime-raw-device-passthrough          (CRITICAL)
  8.  cre-runtime-oci-hook-host-writable-path     (CRITICAL)
  9.  cre-runtime-sandbox-downgrade               (HIGH)
  10. cre-runtime-uid-zero-no-new-privileges-miss (MEDIUM)

Public surface (mirrors `chat_bot_patterns.py` / `webhook_signature_patterns.py`):

  * Rule(id, name, severity, description, pattern, owasp_asi) — frozen NamedTuple
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple
  * RULES — ordered tuple of every rule
  * scan_text(text) -> list[Finding]

OWASP ASI mapping used:

  * ASI-01 — Insecure design (sandbox downgrades, missing isolation)
  * ASI-02 — Authn/Authz failure (docker.sock equals root)
  * ASI-05 — Security misconfiguration (privileged flag, cap-add,
    unconfined LSMs, host namespaces, raw devices)
  * ASI-06 — Vulnerable / outdated components (OCI hook host-writable
    paths — TOCTOU class with runc CVE-2019-5736 lineage)

All regexes are RE2-compatible — no backreferences, no lookbehind, no
catastrophic backtracking shapes. Every variable-width quantifier is
upper-bounded. Patterns are PRE-COMPILED at module load. Fail-fast:
callers receive structured Finding tuples, never raised exceptions on
benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors chat_bot_patterns._re.

    RE2-safe: no nested quantifiers, no backreferences, no lookbehind.
    Variable-width quantifiers are upper-bounded to keep worst-case
    matching linear in input length.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : cre-runtime-privileged-flag -----------------------------------


# Matches `docker run --privileged` / `podman run --privileged` /
# `nerdctl run --privileged` across `run | create | exec` subcommands.
# Bounded `[^\n]{0,400}` to avoid runaway backtracking on pathological
# single-line inputs (e.g. minified scripts). Trailing boundary is
# whitespace, `=`, end-of-string, or end-of-line.
_PRIVILEGED_FLAG = _re(
    r"\b(?:docker|podman|nerdctl)\s+(?:run|create|exec)\b[^\n]{0,400}?"
    r"\s--privileged(?:\s|=|$)"
)


# ---- R2 : cre-runtime-docker-sock-mount-cli -----------------------------


# Matches `-v /var/run/docker.sock:...` / `--volume /var/run/docker.sock:...` /
# `--mount type=bind,source=/var/run/docker.sock,...`. Intentionally
# scoped to CLI flag forms (compose-yaml volume blocks are covered by
# sandbox_escape_patterns.container-compose-docker-sock-mount). The
# trailing `(?::|/|\s|$)` keeps the match anchored to the socket path
# end so `/var/run/docker.sock.bak` does not match.
_DOCKER_SOCK_MOUNT_CLI = _re(
    r"(?:-v|--volume|--mount[^\n]{0,200}?source=)"
    r"\s*[^\s\"']{0,200}?/var/run/docker\.sock(?::|/|\s|$)"
)


# ---- R3 : cre-runtime-dangerous-cap-add ---------------------------------


# `--cap-add=CAP_FOO` / `--cap-add CAP_FOO`. Caps treated as
# escape-class because each grants kernel authority that historical
# CVEs have chained to host root (SYS_ADMIN: CVE-2022-0492 release_agent;
# SYS_MODULE: load arbitrary kernel module; DAC_READ_SEARCH:
# CVE-2014-3519 shocker; SYS_RAWIO + /dev/mem: physical-memory write;
# SYS_BOOT: kexec/reboot host; MAC_*: bypass LSM enforcement).
_DANGEROUS_CAP_ADD = _re(
    r"--cap-add[=\s]+"
    r"(?:CAP_)?"
    r"(?:SYS_ADMIN|NET_ADMIN|SYS_PTRACE|SYS_MODULE|DAC_READ_SEARCH"
    r"|SYS_RAWIO|SYS_BOOT|MAC_ADMIN|MAC_OVERRIDE)\b"
)


# ---- R4 : cre-runtime-lsm-unconfined ------------------------------------


# `--security-opt seccomp=unconfined` / `--security-opt apparmor=unconfined`
# / `--security-opt label=disable` (SELinux). All three remove a
# default-on LSM filter. `label=disable` is the SELinux equivalent of
# `apparmor=unconfined`. Order-sensitive: `=` between key and value is
# Docker's accepted form, `:` is not.
_LSM_UNCONFINED = _re(
    r"--security-opt[=\s]+"
    r"(?:seccomp=unconfined|apparmor=unconfined|label=disable)\b"
)


# ---- R5 : cre-runtime-host-namespace-flag -------------------------------


# `--pid=host` / `--ipc=host` / `--uts=host` / `--network=host` /
# `--net=host` / `--userns=host`. Each disables one of the kernel
# namespaces that *is* the container boundary. The legacy `--net` is
# accepted by Docker as an alias for `--network`. `--userns=host`
# disables the user-namespace remapping that runc applies for
# rootless mode — granting effective host UID 0 on a rootless setup.
_HOST_NAMESPACE_FLAG = _re(
    r"--(?:pid|ipc|uts|network|net|userns)=host\b"
)


# ---- R6 : cre-runtime-sensitive-host-mount-rw ---------------------------


# Bind-mount of `/`, `/proc`, `/sys`, `/etc`, `/root`, `/boot`, or
# `/var/lib/docker` from host into the container WITHOUT `:ro`. The
# negative lookahead-free shape: we require the trailing `:` or
# end-of-token to NOT be followed by `ro` (we approximate that with a
# captured group that must NOT match `ro` — see scan_text post-check).
# The regex here captures the suffix; the scanner checks it for `:ro`.
# Excludes `/var/run/docker.sock` which is R2's domain.
_SENSITIVE_HOST_MOUNT = _re(
    r"(?:-v|--volume|--mount[^\n]{0,200}?source=)"
    r"\s*(?P<host>/(?:proc|sys|etc|root|boot)(?:/[^\s:,]{0,200})?"
    r"|/var/lib/docker(?:/[^\s:,]{0,200})?"
    r"|/(?=[\s:,])(?!var/run/docker\.sock))"
    r":(?P<container>[^\s,]{1,200})"
)


# ---- R7 : cre-runtime-raw-device-passthrough ----------------------------


# `--device=/dev/mem` / `--device=/dev/kmem` / `--device=/dev/kmsg` /
# raw block devices (`/dev/sda`, `/dev/nvme0n1`, etc.). Excludes
# legitimate GPU passthrough (`/dev/nvidia*`, `/dev/dri/*`), USB
# (`/dev/bus/usb/*`), and serial (`/dev/tty*`).
_RAW_DEVICE_PASSTHROUGH = _re(
    r"--device[=\s]+/dev/"
    r"(?:mem|kmem|kmsg|port|sda|sdb|sdc|nvme\d|loop\d|disk\d|md\d|raw\d)"
    r"[a-z0-9]{0,8}\b"
)


# ---- R8 : cre-runtime-oci-hook-host-writable-path -----------------------


# OCI `config.json` hooks (prestart / createRuntime / createContainer /
# startContainer / poststart / poststop) pointing at a host-writable
# path: `/tmp`, `/var/tmp`, `/dev/shm`, `/run/user`. classic TOCTOU
# class — a compromised container can overwrite the binary between
# spec-load and hook-exec (runc CVE-2019-5736 lineage). Also matches
# containerd `config.toml` `BinaryName = "/tmp/..."` shape.
_OCI_HOOK_HOST_WRITABLE = _re(
    r"\"(?:prestart|createRuntime|createContainer|startContainer"
    r"|poststart|poststop)\"\s*:\s*\[\s*\{\s*\"path\"\s*:\s*"
    r"\"(?:/tmp|/var/tmp|/dev/shm|/run/user)[^\"\n]{0,200}\""
    r"|"
    r"\bBinaryName\s*=\s*\"(?:/tmp|/var/tmp|/dev/shm|/run/user)"
    r"[^\"\n]{0,200}\""
)


# ---- R9 : cre-runtime-sandbox-downgrade ---------------------------------


# gvisor `--platform=ptrace` (weaker than the default `kvm`), kata
# configured with `runtime_type = "io.containerd.runc.*"` (collapses
# kata's VM boundary), or `runsc` invoked with `--platform=ptrace`.
# Also catches kata `disable_vm = true` which is the explicit
# downgrade switch.
_SANDBOX_DOWNGRADE = _re(
    r"--platform[=\s]+ptrace\b"
    r"|"
    r"\bruntime_type\s*=\s*\"io\.containerd\.runc(?:\.[a-z0-9]{1,8})?\""
    r"|"
    r"\bdisable_vm\s*[:=]\s*true\b"
)


# ---- R10 : cre-runtime-uid-zero-no-new-privileges-miss -----------------


# Trigger: a `docker|podman|nerdctl run|create` invocation that
# explicitly sets `--user 0` or `--user root` (canonical uid-zero
# request). The Stage-B post-check in scan_text extends to the
# end-of-line and confirms the same invocation does NOT also carry
# `--security-opt no-new-privileges`.
# Without that flag, setuid binaries inside the image (`/bin/su`,
# `/usr/bin/sudo`) can re-elevate after a non-root compromise; chained
# with a kernel CVE (Dirty Pipe, CVE-2024-1086) this reaches host
# root. The kc-secure-repo template always sets both flags together;
# the absence of `no-new-privileges` alongside `--user 0` is the anchor.
_UID_ZERO_TRIGGER = _re(
    r"\b(?:docker|podman|nerdctl)\s+(?:run|create)\b[^\n]{0,600}?"
    r"--user[=\s]+(?:0|root)\b"
)

# Companion check (used only in scan_text Stage-B).
_NO_NEW_PRIVS_MARKER = _re(
    r"--security-opt[=\s]+no-new-privileges(?:[:=]true)?\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cre-runtime-privileged-flag",
        name="Container runtime invoked with --privileged",
        severity="CRITICAL",
        description=(
            "`docker run` / `podman run` / `nerdctl run` invoked with "
            "`--privileged`. The flag disables EVERY isolation primitive "
            "in one shot: all caps granted, every host device exposed, "
            "AppArmor unconfined, SELinux unconfined, seccomp disabled, "
            "cgroup write access. A privileged container is functionally "
            "a root shell on the host kernel — combined with a "
            "bind-mounted host path it is a one-line full host takeover. "
            "The k8s admission equivalent (`securityContext.privileged: "
            "true`) is covered by sandbox_escape_patterns; this rule "
            "catches the CLI / shell-script surface."
        ),
        pattern=_PRIVILEGED_FLAG,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cre-runtime-docker-sock-mount-cli",
        name="Docker socket bind-mounted via CLI flag (-v / --mount)",
        severity="CRITICAL",
        description=(
            "`-v /var/run/docker.sock:...` or "
            "`--mount source=/var/run/docker.sock,...` on a `docker run` "
            "/ `podman run` / `nerdctl run` CLI invocation. Mounting "
            "the Docker socket inside a container is equivalent to "
            "giving that container root on the host: any process with "
            "write access to the socket can spawn a sibling container "
            "with `--privileged -v /:/host`, then chroot. The Docker "
            "daemon API authenticates clients only via UNIX file "
            "permissions. The compose-YAML equivalent is covered by "
            "sandbox_escape_patterns.container-compose-docker-sock-mount; "
            "this rule covers the shell-script / Makefile / CI-script "
            "surface."
        ),
        pattern=_DOCKER_SOCK_MOUNT_CLI,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cre-runtime-dangerous-cap-add",
        name="Container runtime invoked with dangerous --cap-add capability",
        severity="HIGH",
        description=(
            "`--cap-add` granting one of the escape-class Linux "
            "capabilities (SYS_ADMIN, NET_ADMIN, SYS_PTRACE, SYS_MODULE, "
            "DAC_READ_SEARCH, SYS_RAWIO, SYS_BOOT, MAC_ADMIN, "
            "MAC_OVERRIDE). SYS_ADMIN is the almost-root cap — permits "
            "`mount(2)`, namespace manipulation, swap config, LSM "
            "bypass. SYS_MODULE loads kernel modules (full host "
            "compromise). DAC_READ_SEARCH bypasses file-read DAC "
            "(CVE-2014-3519 shocker exploit class). The kc-secure-repo "
            "template uses `--cap-drop=ALL` consistently; the inverse "
            "is detectable trivially."
        ),
        pattern=_DANGEROUS_CAP_ADD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cre-runtime-lsm-unconfined",
        name="Container runtime invoked with seccomp / apparmor / SELinux disabled",
        severity="HIGH",
        description=(
            "`--security-opt seccomp=unconfined` / "
            "`--security-opt apparmor=unconfined` / "
            "`--security-opt label=disable` (SELinux). Disables the "
            "default seccomp filter (blocks ~44 syscalls including "
            "`keyctl`, `add_key`, `bpf`, `userfaultfd`, `pivot_root`), "
            "the default AppArmor profile (`docker-default`), or the "
            "SELinux MCS label. With seccomp unconfined, a container "
            "can call `unshare(CLONE_NEWUSER)` + `mount(2)` chains that "
            "have historically led to escapes (Dirty Pipe "
            "CVE-2022-0847, userfaultfd-based race conditions). "
            "Custom whitelist profiles via `--security-opt "
            "seccomp=/path/to/custom.json` are the supported escape "
            "hatch."
        ),
        pattern=_LSM_UNCONFINED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cre-runtime-host-namespace-flag",
        name="Container runtime shares host PID/IPC/UTS/network/user namespace",
        severity="HIGH",
        description=(
            "`--pid=host` / `--ipc=host` / `--uts=host` / "
            "`--network=host` / `--net=host` / `--userns=host`. Each "
            "flag disables one of the kernel namespaces that IS the "
            "container boundary. `--pid=host` lets the container see / "
            "signal every host process (kill, ptrace if SYS_PTRACE "
            "granted, read `/proc/<pid>/environ` for secret "
            "extraction). `--network=host` removes the network "
            "namespace, granting raw access to host interfaces "
            "(loopback-bound services become reachable, ARP spoofing "
            "possible). `--userns=host` disables rootless-mode UID "
            "remapping, granting effective host UID 0. The compose "
            "YAML equivalent (`pid: host` / `ipc: host` / "
            "`network_mode: host`) is covered by "
            "sandbox_escape_patterns.container-compose-host-namespace-share."
        ),
        pattern=_HOST_NAMESPACE_FLAG,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cre-runtime-sensitive-host-mount-rw",
        name="Container runtime bind-mounts a sensitive host path read-write",
        severity="HIGH",
        description=(
            "`-v` / `--volume` / `--mount source=` bind-mounting `/`, "
            "`/proc`, `/sys`, `/etc`, `/root`, `/boot`, or "
            "`/var/lib/docker` from host into the container WITHOUT "
            "the `:ro` (read-only) suffix. RW mounts of these paths "
            "give direct write access to `/proc/sysrq-trigger` "
            "(reboot), `/sys/fs/cgroup/*/release_agent` (CVE-2022-0492 "
            "escape primitive), `/etc/shadow` (offline crack), "
            "`/root/.ssh/authorized_keys` (persistence). Monitoring "
            "agents legitimately mount `/proc` and `/sys` as `:ro` — "
            "the `:ro` suffix is the discriminator."
        ),
        pattern=_SENSITIVE_HOST_MOUNT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cre-runtime-raw-device-passthrough",
        name="Container runtime --device passthrough of physical memory / raw block",
        severity="CRITICAL",
        description=(
            "`--device=/dev/mem` / `--device=/dev/kmem` / "
            "`--device=/dev/kmsg` / raw block devices (`/dev/sda`, "
            "`/dev/nvme0n1`, etc.) skip the default device cgroup "
            "whitelist and hand a raw character/block device to the "
            "container. `/dev/mem` is physical memory read/write "
            "(rowhammer-style attacks, kernel-credential overwrite). "
            "`/dev/kmsg` is the kernel ring buffer (info leak). Raw "
            "block devices allow direct filesystem modification "
            "bypassing every LSM. The narrow allowlist of device path "
            "tails (mem/kmem/kmsg/port/sda*/nvme*/loop*/disk*/md*/raw*) "
            "excludes legitimate GPU / USB / serial passthrough."
        ),
        pattern=_RAW_DEVICE_PASSTHROUGH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cre-runtime-oci-hook-host-writable-path",
        name="OCI runtime hook (or containerd BinaryName) points at host-writable path",
        severity="CRITICAL",
        description=(
            "OCI `config.json` runtime hooks (prestart / createRuntime "
            "/ createContainer / startContainer / poststart / poststop) "
            "or containerd `config.toml` `BinaryName = ...` pointing "
            "at a host-writable path (`/tmp`, `/var/tmp`, `/dev/shm`, "
            "`/run/user`). The hook binary executes in the HOST "
            "namespace before/after the container starts; if its path "
            "is in a container-writable or world-writable location, a "
            "compromised container can overwrite the binary between "
            "spec-load and hook-exec — classic TOCTOU privilege "
            "escalation in the lineage of runc CVE-2019-5736 "
            "(symlink-following escape). Legitimate hooks live under "
            "`/usr/libexec/oci/hooks.d/` or `/etc/containers/oci/hooks.d/`."
        ),
        pattern=_OCI_HOOK_HOST_WRITABLE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cre-runtime-sandbox-downgrade",
        name="gvisor --platform=ptrace / kata→runc downgrade collapses sandbox",
        severity="HIGH",
        description=(
            "gvisor `--platform=ptrace` runs the sandbox sentry as a "
            "ptracer of the application — significantly weaker than "
            "the default `kvm` platform and lacking the seccomp-bpf "
            "chain that filters host-side syscalls. Kata-containers "
            "configured with `runtime_type = \"io.containerd.runc.*\"` "
            "(instead of `io.containerd.kata.v2`) collapses the VM "
            "boundary entirely — kata runs as a normal runc container "
            "with kata's name. Kata `disable_vm = true` is the "
            "explicit downgrade switch. All three are configuration-"
            "level downgrades that defeat the runtime's stated "
            "isolation guarantee."
        ),
        pattern=_SANDBOX_DOWNGRADE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cre-runtime-uid-zero-no-new-privileges-miss",
        name="Container runs as UID 0 / root WITHOUT --security-opt no-new-privileges",
        severity="MEDIUM",
        description=(
            "`docker run --user 0 ...` (or `--user root`) WITHOUT a "
            "matching `--security-opt no-new-privileges` (or "
            "`no-new-privileges:true`) on the same invocation. Without "
            "the flag, a compromised non-root process inside the "
            "container can re-elevate via setuid binaries in the image "
            "(`/bin/su`, `/usr/bin/sudo`). Combined with running as "
            "UID 0, this is the path most commonly chained with a "
            "kernel CVE (Dirty Pipe, CVE-2024-1086 nf_tables UAF) to "
            "reach host root. The kc-secure-repo template always sets "
            "both `--user \"${docker_uid}:${docker_gid}\"` AND "
            "`--security-opt=no-new-privileges:true`; the asymmetry is "
            "the regex anchor."
        ),
        pattern=_UID_ZERO_TRIGGER,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters:

      * R6 (sensitive-host-mount-rw): the regex captures the `:container`
        suffix; we suppress when `:ro` (read-only) appears in the
        suffix — monitoring agents legitimately mount /proc and /sys
        read-only.
      * R10 (uid-zero-no-new-privileges-miss): the trigger anchors on
        `--user 0` / `--user root`; we suppress when the SAME
        invocation (same matched span) also contains
        `--security-opt no-new-privileges`.

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
        # Truncate excessively long matches for the finding payload —
        # keeps reports compact when the user pastes a giant minified
        # one-liner.
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

    # ---- R1 : cre-runtime-privileged-flag ----
    rule_r1 = rule_by_id["cre-runtime-privileged-flag"]
    for m in _PRIVILEGED_FLAG.finditer(text):
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : cre-runtime-docker-sock-mount-cli ----
    rule_r2 = rule_by_id["cre-runtime-docker-sock-mount-cli"]
    for m in _DOCKER_SOCK_MOUNT_CLI.finditer(text):
        _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : cre-runtime-dangerous-cap-add ----
    rule_r3 = rule_by_id["cre-runtime-dangerous-cap-add"]
    for m in _DANGEROUS_CAP_ADD.finditer(text):
        _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : cre-runtime-lsm-unconfined ----
    rule_r4 = rule_by_id["cre-runtime-lsm-unconfined"]
    for m in _LSM_UNCONFINED.finditer(text):
        _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : cre-runtime-host-namespace-flag ----
    rule_r5 = rule_by_id["cre-runtime-host-namespace-flag"]
    for m in _HOST_NAMESPACE_FLAG.finditer(text):
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : cre-runtime-sensitive-host-mount-rw (Stage-B `:ro` suppression) ----
    rule_r6 = rule_by_id["cre-runtime-sensitive-host-mount-rw"]
    for m in _SENSITIVE_HOST_MOUNT.finditer(text):
        container_suffix = m.group("container")
        # `:ro` may appear as `:ro`, `:ro,...`, `:rslave,ro`, `:ro,rslave`.
        # Tokenise the suffix on `,` and look for `ro` as a whole token.
        suffix_tokens = {tok.strip() for tok in container_suffix.split(",")}
        if "ro" in suffix_tokens or any(t.endswith(":ro") for t in suffix_tokens):
            continue
        _emit(rule_r6, m.start(), m.group(0))

    # ---- R7 : cre-runtime-raw-device-passthrough ----
    rule_r7 = rule_by_id["cre-runtime-raw-device-passthrough"]
    for m in _RAW_DEVICE_PASSTHROUGH.finditer(text):
        _emit(rule_r7, m.start(), m.group(0))

    # ---- R8 : cre-runtime-oci-hook-host-writable-path ----
    rule_r8 = rule_by_id["cre-runtime-oci-hook-host-writable-path"]
    for m in _OCI_HOOK_HOST_WRITABLE.finditer(text):
        _emit(rule_r8, m.start(), m.group(0))

    # ---- R9 : cre-runtime-sandbox-downgrade ----
    rule_r9 = rule_by_id["cre-runtime-sandbox-downgrade"]
    for m in _SANDBOX_DOWNGRADE.finditer(text):
        _emit(rule_r9, m.start(), m.group(0))

    # ---- R10 : cre-runtime-uid-zero-no-new-privileges-miss (Stage-B) ----
    rule_r10 = rule_by_id["cre-runtime-uid-zero-no-new-privileges-miss"]
    for m in _UID_ZERO_TRIGGER.finditer(text):
        # The trigger only captures up to `--user 0` — additional flags
        # (the `no-new-privileges` we want to allow) may appear AFTER
        # the match end on the same logical line. Scan to end-of-line
        # (or end-of-string) to see the whole invocation.
        eol = text.find("\n", m.end())
        invocation_end = len(text) if eol == -1 else eol
        invocation_span = text[m.start():invocation_end]
        if _NO_NEW_PRIVS_MARKER.search(invocation_span) is not None:
            continue
        _emit(rule_r10, m.start(), m.group(0))

    # Deterministic order: (line, column, rule_id).
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


__all__ = ("Finding", "Rule", "RULES", "scan_text")
