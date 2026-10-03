#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Pure environment-detection primitives for /janitor-identify-environment.

This module is the *decision* layer (like `fleet_recovery` vs `fleet_inject`,
`classify_argv` vs the Popen patch): every function here is PURE — it takes the
already-gathered raw facts (env dict, injected `which`/`exists` callables, or a
command's captured stdout) and returns a plain dict/list. The I/O — running
`ps`/`mount`/`ifconfig`/`route`/`lsof`/`scutil`, reading config files — lives in
the thin CLI (`scripts/identify_environment.py`) so THIS module is unit-testable
by injecting synthetic inputs, with zero dependence on the host it runs on.

Three invariants every function upholds (they are the whole reason to trust a
diagnostic that reads credentials-adjacent state):

  1. **Never emit a secret VALUE.** Anything whose key looks like a credential
     (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*`, …) is reported
     as presence only ("set"), never its value. Proxy URLs are masked to strip any
     `user:pass@`. MCP/URL query strings and command args are dropped, not printed.
  2. **No network.** Nothing here makes a network call; the CLI's few optional
     probes are gated behind an explicit `--probe-network` flag and are not invoked
     from this module.
  3. **Fail-open.** A malformed input yields an empty/"unknown" field, never a
     raise — a diagnostic that crashes on a weird host is worse than one that says
     "unknown".
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Callable, Mapping
from typing import Optional

import daemon_path  # sibling in scripts/lib/ (the caller puts lib on sys.path)

# --- secret-safety ----------------------------------------------------------

# A key is treated as secret-bearing (VALUE never emitted) if it matches any of
# these, case-insensitively. Broad on purpose: false positives cost a "set"
# instead of a value; a false negative leaks a credential into a report.
_SECRET_KEY_RE = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|SIGNATURE|SESSION|"
    r"COOKIE|AUTH|CERT|PIN|OTP|SALT|API|ACCESS|BEARER|CLIENT_SECRET)",
    re.IGNORECASE,
)
# The few keys that MATCH the secret regex but are safe, well-known, non-secret
# selectors worth showing by value (a region / profile / project name is not a
# credential). Everything else matching the regex is presence-only.
_SECRET_ALLOW_VALUE = frozenset({
    "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
})


def is_secret_key(name: str) -> bool:
    """True iff `name`'s VALUE must never be emitted (it looks credential-bearing)."""
    if name in _SECRET_ALLOW_VALUE:
        return False
    return bool(_SECRET_KEY_RE.search(name or ""))


def env_value(env: Mapping[str, str], key: str) -> Optional[str]:
    """The value of `key` if safe to show, else None. Secret keys never return a value."""
    if key not in env:
        return None
    if is_secret_key(key):
        return None
    v = env.get(key)
    return v if v else None


def env_present(env: Mapping[str, str], key: str) -> bool:
    """True iff `key` is set to a non-empty value (no value emitted)."""
    return bool((env.get(key) or "").strip())


def mask_proxy(url: str) -> str:
    """Return `url` with any `user:pass@` credentials stripped (scheme://host:port/path).

    A proxy env var routinely embeds `http://user:password@host:3128`; the
    credentials must never reach a report. Non-URL values are returned unchanged
    except that a bare `user:pass@host` form is also stripped.
    """
    if not url:
        return ""
    # scheme://[user:pass@]host[:port][/...]
    m = re.match(r"^([a-zA-Z][\w+.-]*://)?(?:[^/@]*@)?(.*)$", url.strip())
    if not m:
        return "***"
    scheme = m.group(1) or ""
    rest = m.group(2) or ""
    return f"{scheme}{rest}" if rest else "***"


# --- terminal / multiplexer -------------------------------------------------

# Terminal identity from ENV signals (a superset of the ancestry table in
# state.py, used for REPORTING only — it never drives keystroke injection, so it
# can be broad without any safety cost). Order: the most specific env var wins.
_TERMINAL_ENV_SIGNALS: tuple[tuple[str, str], ...] = (
    ("WT_SESSION", "Windows Terminal"),
    ("ConEmuPID", "ConEmu"),
    ("WEZTERM_PANE", "WezTerm"),
    ("KITTY_WINDOW_ID", "kitty"),
    ("ALACRITTY_WINDOW_ID", "Alacritty"),
    ("ALACRITTY_SOCKET", "Alacritty"),
    ("KONSOLE_VERSION", "Konsole"),
    ("GNOME_TERMINAL_SCREEN", "GNOME Terminal"),
    ("VTE_VERSION", "VTE-based (GNOME/Tilix/…)"),
    ("TERMINATOR_UUID", "Terminator"),
    ("TABBY_CONFIG_DIRECTORY", "Tabby"),
    ("CONTOUR_PROFILE", "Contour"),
    ("RIO_CONFIG", "Rio"),
    ("GHOSTTY_RESOURCES_DIR", "Ghostty"),
    ("WARP_HONOR_PS1", "Warp"),
    ("ITERM_SESSION_ID", "iTerm2"),
    ("VSCODE_INJECTION", "VS Code integrated terminal"),
)

# TERM_PROGRAM values → friendly name (the portable cross-platform hint).
_TERM_PROGRAM_NAMES: dict[str, str] = {
    "iterm.app": "iTerm2",
    "apple_terminal": "Apple Terminal",
    "vscode": "VS Code integrated terminal",
    "wezterm": "WezTerm",
    "ghostty": "Ghostty",
    "hyper": "Hyper",
    "warp": "Warp",
    "tabby": "Tabby",
    "rio": "Rio",
    "zed": "Zed terminal",
    "kitty": "kitty",
}


def detect_terminal(
    env: Mapping[str, str], *, ancestry_kind: str = "unknown"
) -> dict:
    """Reconcile the process-ancestry `ancestry_kind` (from `state.terminal_kind`,
    the authoritative source used for injection) with ENV signals into a rich
    reporting dict. Env is a SECONDARY signal — it can lie in a subshell — so the
    ancestry kind is reported as `kind` and the env guesses as `env_signal`.
    """
    term_program = (env.get("TERM_PROGRAM") or "").strip()
    program = _TERM_PROGRAM_NAMES.get(term_program.lower(), "")
    env_signal = ""
    for var, label in _TERMINAL_ENV_SIGNALS:
        if env_present(env, var):
            env_signal = label
            break
    if not program and env_signal:
        program = env_signal
    version = (env.get("TERM_PROGRAM_VERSION") or env.get("KONSOLE_VERSION")
               or env.get("VTE_VERSION") or "").strip()
    return {
        "kind": ancestry_kind,                 # ancestry-derived (drives injection)
        "program": program or ancestry_kind,   # human label
        "term_program": term_program,          # $TERM_PROGRAM verbatim
        "term": (env.get("TERM") or "").strip(),
        "version": version,
        "env_signal": env_signal,              # the env var that matched
        "iterm_session_present": env_present(env, "ITERM_SESSION_ID"),
    }


def detect_multiplexer(env: Mapping[str, str]) -> Optional[dict]:
    """The terminal multiplexer, if any: tmux / GNU screen / zellij / byobu."""
    if env_present(env, "TMUX") or env_present(env, "TMUX_PANE"):
        return {"kind": "tmux", "pane": (env.get("TMUX_PANE") or "").strip()}
    if env_present(env, "ZELLIJ"):
        return {"kind": "zellij", "session": (env.get("ZELLIJ_SESSION_NAME") or "").strip()}
    if env_present(env, "STY"):
        return {"kind": "screen", "session": (env.get("STY") or "").strip()}
    if env_present(env, "BYOBU_BACKEND"):
        return {"kind": "byobu", "backend": (env.get("BYOBU_BACKEND") or "").strip()}
    return None


# --- OS ---------------------------------------------------------------------


def detect_wsl(env: Mapping[str, str], *, proc_version: str = "") -> Optional[dict]:
    """WSL details from /proc/version + env, or None when not under WSL."""
    pv = (proc_version or "").lower()
    is_wsl = "microsoft" in pv or "wsl" in pv or env_present(env, "WSL_DISTRO_NAME")
    if not is_wsl:
        return None
    return {
        "distro": (env.get("WSL_DISTRO_NAME") or "").strip(),
        "interop": env_present(env, "WSL_INTEROP"),
        "version": "WSL2" if "wsl2" in pv else "WSL",
    }


# --- filesystem -------------------------------------------------------------


def parse_mount_fstype(mount_text: str, target: str) -> str:
    """macOS/Linux `mount` output → the fstype whose mountpoint is the LONGEST
    prefix of `target`. '' when nothing matches. Pure."""
    best_mp, best_fs = "", ""
    for line in (mount_text or "").splitlines():
        if " on " not in line or "(" not in line:
            continue
        mp = line.split(" on ", 1)[1].split(" (", 1)[0]
        fstype = line.split("(", 1)[1].split(",", 1)[0].split(")", 1)[0].strip()
        if (target == mp or target.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best_mp):
            best_mp, best_fs = mp, fstype
    return best_fs


_NETWORK_FSTYPES = frozenset({"nfs", "smbfs", "cifs", "afpfs", "webdav", "fuse.sshfs", "9p"})


def filesystem_is_network(fstype: str) -> bool:
    """True iff `fstype` denotes a network/remote mount (latency + availability risk).

    Matched on the FULL fstype (case-insensitive), NOT on a `fuse.`-prefix collapse: most FUSE
    filesystems (fuse.encfs, fuse.rclone, fuse.bindfs) are LOCAL — only fuse.sshfs is remote —
    so folding every `fuse.*` down to `fuse` (the old `split('.')[0]` behavior) misreported a
    local FUSE mount as a network mount.
    """
    return (fstype or "").lower() in _NETWORK_FSTYPES


# --- CI / remote execution --------------------------------------------------

# One env key → provider label. First match wins; GH Actions is checked with its
# own richer extractor below.
_CI_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("GITHUB_ACTIONS", "GitHub Actions"),
    ("GITLAB_CI", "GitLab CI"),
    ("CIRCLECI", "CircleCI"),
    ("TRAVIS", "Travis CI"),
    ("JENKINS_URL", "Jenkins"),
    ("JENKINS_HOME", "Jenkins"),
    ("TF_BUILD", "Azure Pipelines"),
    ("BUILDKITE", "Buildkite"),
    ("TEAMCITY_VERSION", "TeamCity"),
    ("BITBUCKET_BUILD_NUMBER", "Bitbucket Pipelines"),
    ("APPVEYOR", "AppVeyor"),
    ("DRONE", "Drone CI"),
    ("CODEBUILD_BUILD_ID", "AWS CodeBuild"),
    ("SEMAPHORE", "Semaphore"),
    ("WOODPECKER_CI", "Woodpecker CI"),
    ("VERCEL", "Vercel"),
    ("NETLIFY", "Netlify"),
    ("CF_PAGES", "Cloudflare Pages"),
)


def detect_ci(env: Mapping[str, str]) -> Optional[dict]:
    """The CI/CD provider running this session + non-secret run details, or None."""
    provider = ""
    for key, label in _CI_PROVIDERS:
        if env_present(env, key):
            provider = label
            break
    if not provider and env_present(env, "CI"):
        provider = "generic CI (unidentified provider)"
    if not provider:
        return None
    out: dict = {"provider": provider}
    if provider == "GitHub Actions":
        # None of these are secret (the token is $GITHUB_TOKEN, never shown).
        out["github"] = {
            k: v for k, v in {
                "repository": env_value(env, "GITHUB_REPOSITORY"),
                "workflow": env_value(env, "GITHUB_WORKFLOW"),
                "run_id": env_value(env, "GITHUB_RUN_ID"),
                "event": env_value(env, "GITHUB_EVENT_NAME"),
                "ref": env_value(env, "GITHUB_REF_NAME"),
                "actor": env_value(env, "GITHUB_ACTOR"),
                "runner_os": env_value(env, "RUNNER_OS"),
                "runner_arch": env_value(env, "RUNNER_ARCH"),
            }.items() if v
        }
    return out


# --- containers / virtualization / sandbox ----------------------------------


def detect_containers(
    env: Mapping[str, str],
    *,
    exists: Callable[[str], bool],
    virt: str = "",
) -> list[str]:
    """Every container / VM / sandbox signal observable without a network call.
    `exists` probes marker files; `virt` is `systemd-detect-virt` output (or '')."""
    sig: list[str] = []
    if exists("/.dockerenv"):
        sig.append("docker (/.dockerenv)")
    if exists("/run/.containerenv"):
        sig.append("podman (/run/.containerenv)")
    if exists("/.flatpak-info"):
        sig.append("flatpak (/.flatpak-info)")
    if env_present(env, "SNAP") and env_present(env, "SNAP_NAME"):
        sig.append(f"snap ({env.get('SNAP_NAME')})")
    if exists("/run/firejail") or env_present(env, "FIREJAIL"):
        sig.append("firejail")
    env_markers = {
        "KUBERNETES_SERVICE_HOST": "kubernetes",
        "CODESPACES": "GitHub Codespaces",
        "REMOTE_CONTAINERS": "VS Code dev container",
        "DEVCONTAINER": "dev container",
        "GITPOD_WORKSPACE_ID": "Gitpod",
        "container": "container (systemd $container)",
        "APP_SANDBOX_CONTAINER_ID": "macOS app sandbox",
    }
    for var, label in env_markers.items():
        if env_present(env, var):
            extra = f"={env.get(var)}" if var == "container" else ""
            sig.append(f"{label} (${var}{extra})")
    v = (virt or "").strip().lower()
    if v and v not in ("none", ""):
        _VIRT_LABELS = {
            "microsoft": "Hyper-V VM", "wsl": "WSL", "kvm": "KVM VM",
            "vmware": "VMware VM", "oracle": "VirtualBox VM", "qemu": "QEMU VM",
            "xen": "Xen VM", "parallels": "Parallels VM", "docker": "Docker",
            "podman": "Podman", "lxc": "LXC", "lxc-libvirt": "LXC",
            "systemd-nspawn": "systemd-nspawn", "openvz": "OpenVZ", "bochs": "Bochs VM",
        }
        sig.append(f"virt: {_VIRT_LABELS.get(v, v)} (systemd-detect-virt)")
    return sig


# --- IDE / editor / Claude Code ---------------------------------------------


def detect_ide(env: Mapping[str, str]) -> dict:
    """The hosting editor/IDE and the Claude Code runtime facts (all env-derived)."""
    term_program = (env.get("TERM_PROGRAM") or "").strip().lower()
    editor = ""
    if env_present(env, "CURSOR_TRACE_ID") or "cursor" in (env.get("__CFBundleIdentifier") or "").lower():
        editor = "Cursor"
    elif "windsurf" in (env.get("__CFBundleIdentifier") or "").lower() or env_present(env, "WINDSURF_ENV"):
        editor = "Windsurf"
    elif term_program == "zed" or env_present(env, "ZED_TERM"):
        editor = "Zed"
    elif (env.get("TERMINAL_EMULATOR") or "").startswith("JetBrains") or env_present(env, "__INTELLIJ_COMMAND_HISTFILE__"):
        editor = "JetBrains IDE"
    elif term_program == "vscode" or env_present(env, "VSCODE_INJECTION") or env_present(env, "VSCODE_GIT_ASKPASS_MAIN"):
        editor = "VS Code"
    claude = {
        "is_claude_code": env_present(env, "CLAUDECODE") or env_present(env, "CLAUDE_CODE_ENTRYPOINT"),
        "entrypoint": env_value(env, "CLAUDE_CODE_ENTRYPOINT") or "",
        "project_dir": env_value(env, "CLAUDE_PROJECT_DIR") or "",
    }
    # Desktop app vs CLI: the desktop app bundle id differs from a terminal launch.
    bundle = (env.get("__CFBundleIdentifier") or "").lower()
    if "com.anthropic.claude" in bundle or ("claude" in bundle and "desktop" in bundle):
        claude["surface"] = "desktop app"
    elif claude["is_claude_code"]:
        claude["surface"] = "CLI / terminal"
    return {"editor": editor, "claude": claude}


# --- headless / worktree / background agent ---------------------------------


def detect_execution_context(
    env: Mapping[str, str],
    *,
    has_tty: bool,
    git_dir: str = "",
    git_common_dir: str = "",
    inside_work_tree: bool = False,
) -> dict:
    """Whether this is an interactive TTY, a headless/background run, and whether
    the cwd is a LINKED git worktree (vs the main checkout). All facts injected."""
    linked_worktree = bool(
        git_dir and git_common_dir
        and os.path.normpath(git_dir) != os.path.normpath(git_common_dir)
    )
    ai_agent = any(
        env_present(env, k) for k in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID")
    )
    return {
        "interactive_tty": bool(has_tty),
        "headless": not has_tty,
        "background_agent": ai_agent or (not has_tty and env_present(env, "CLAUDECODE")),
        "ai_maestro_agent": ai_agent,
        "git_worktree": bool(inside_work_tree),
        "linked_worktree": linked_worktree,
        "git_common_dir": git_common_dir,
    }


# --- network: proxy / VPN / interfaces --------------------------------------


def detect_proxies(env: Mapping[str, str]) -> dict:
    """Proxy configuration from env — values MASKED to strip embedded credentials."""
    out: dict = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "ftp_proxy"):
        v = (env.get(key) or "").strip()
        if v:
            out[key.upper()] = mask_proxy(v)
    no_proxy = (env.get("NO_PROXY") or env.get("no_proxy") or "").strip()
    if no_proxy:
        out["NO_PROXY"] = no_proxy  # host list — not secret
    return out


def parse_interfaces(iface_text: str, *, system: str) -> list[dict]:
    """Parse `ifconfig -a` (macOS/BSD) or `ip -o addr` (Linux) → per-interface
    {name, addrs:[...]}. Pure; tolerant of both formats."""
    ifaces: dict[str, list[str]] = {}
    text = iface_text or ""
    if system == "Linux" and re.search(r"^\d+:\s", text, re.MULTILINE) is None and " inet " not in text:
        return []
    # `ip -o addr` lines: "3: eth0    inet 10.0.0.2/24 ..."
    for m in re.finditer(r"^\d+:\s+(\S+)\s+inet6?\s+([0-9a-fA-F:.]+)", text, re.MULTILINE):
        ifaces.setdefault(m.group(1).rstrip("@ '"), []).append(m.group(2))
    # `ifconfig` blocks: "en0: flags=...\n\tinet 192.168.1.5 netmask ..."
    cur = ""
    for line in text.splitlines():
        m_flag = re.match(r"^([A-Za-z0-9]+):\s+flags=", line)
        if m_flag:
            cur = m_flag.group(1)
            ifaces.setdefault(cur, [])
            continue
        m_addr = re.search(r"^\s+inet6?\s+([0-9a-fA-F:.]+)", line)
        if m_addr and cur:
            ifaces[cur].append(m_addr.group(1))
    return [{"name": n, "addrs": a} for n, a in ifaces.items() if n]


_TUNNEL_RE = re.compile(r"^(utun|tun|tap|ppp|wg|gpd|ipsec|CloudflareWARP)", re.IGNORECASE)


def detect_vpn(interfaces: list[dict], *, which: Callable[[str], bool]) -> dict:
    """Infer VPN presence from tunnel interfaces + installed VPN CLIs. Pure over
    the parsed `interfaces` list and an injected `which`."""
    tunnels = [i["name"] for i in interfaces if _TUNNEL_RE.match(i["name"])]
    tailscale = any(i["name"].startswith("tailscale") for i in interfaces)
    # Tailscale also runs over a utun with a 100.64.0.0/10 (CGNAT) address on macOS.
    for i in interfaces:
        for a in i["addrs"]:
            try:
                if ipaddress.ip_address(a.split("/")[0]) in ipaddress.ip_network("100.64.0.0/10"):
                    tailscale = True
            except ValueError:
                continue
    kinds: list[str] = []
    if tailscale or which("tailscale"):
        kinds.append("Tailscale")
    if any(i["name"].startswith("wg") for i in interfaces) or which("wg"):
        kinds.append("WireGuard")
    if any(i["name"] == "CloudflareWARP" for i in interfaces) or which("warp-cli"):
        kinds.append("Cloudflare WARP")
    if which("openvpn"):
        kinds.append("OpenVPN (installed)")
    return {"tunnels": tunnels, "kinds": kinds, "tailscale": tailscale}


def _is_private_ip(addr: str) -> Optional[bool]:
    try:
        ip = ipaddress.ip_address(addr.split("/")[0].split("%")[0])
    except ValueError:
        return None
    return ip.is_private or ip.is_loopback or ip.is_link_local


_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")  # RFC 6598 shared space (Tailscale, carrier NAT)


def classify_nat(interfaces: list[dict]) -> Optional[bool]:
    """True iff the host has only private LAN IPv4s (→ behind NAT), False iff it
    holds a globally-routable IPv4, None when there is nothing to judge.

    Two exclusions keep it honest: TUNNEL/VPN interfaces are skipped (a Tailscale
    utun tells you nothing about the LAN's NAT), and the CGNAT range 100.64.0.0/10
    counts as private-not-public — Python's `is_private` historically excluded it,
    which is exactly what made a Tailscale `100.x` address masquerade as a public IP.
    """
    has_public = has_private = False
    for i in interfaces:
        name = i["name"]
        if _TUNNEL_RE.match(name) or name.startswith("tailscale"):
            continue
        for a in i["addrs"]:
            if ":" in a:  # NAT is an IPv4 judgment
                continue
            ipstr = a.split("/")[0].split("%")[0]
            try:
                ip = ipaddress.ip_address(ipstr)
            except ValueError:
                continue
            if ip.is_loopback or ip.is_link_local:
                continue
            if ip in _CGNAT_NET or ip.is_private:
                has_private = True
            elif ip.is_global:
                has_public = True
    if has_public:
        return False
    if has_private:
        return True
    return None


# --- network config: default route / DNS / firewall / listening ports -------


def parse_default_gateway(route_text: str) -> str:
    """Default gateway from `route -n get default` (macOS) or `ip route` (Linux).
    Format-agnostic: tries both spellings, so the caller need not know the OS."""
    text = route_text or ""
    m = re.search(r"^\s*gateway:\s*(\S+)", text, re.MULTILINE)   # macOS
    if m:
        return m.group(1)
    m = re.search(r"^default via (\S+)", text, re.MULTILINE)     # Linux `ip route`
    if m:
        return m.group(1)
    return ""


def parse_dns_servers(dns_text: str) -> list[str]:
    """DNS resolvers from `scutil --dns` (macOS) or /etc/resolv.conf (Linux).
    Format-agnostic: matches both `nameserver[N] :` and `nameserver` spellings."""
    text = dns_text or ""
    servers: list[str] = []
    for m in re.finditer(r"nameserver\[\d+\]\s*:\s*(\S+)", text):       # scutil
        servers.append(m.group(1))
    for m in re.finditer(r"^\s*nameserver\s+(\S+)", text, re.MULTILINE):  # resolv.conf
        servers.append(m.group(1))
    # dedupe, preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for s in servers:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def parse_firewall_state(text: str, *, kind: str) -> str:
    """Interpret a firewall status probe's output into on/off/unknown.
    `kind` ∈ {macos-alf, ufw, firewalld}."""
    t = (text or "").lower()
    if not t:
        return "unknown (not readable / needs root)"
    if kind == "macos-alf":
        if "enabled" in t or "state = 1" in t or "state = 2" in t:
            return "enabled"
        if "disabled" in t or "state = 0" in t:
            return "disabled"
    if kind == "ufw":
        if "status: active" in t:
            return "enabled"
        if "status: inactive" in t:
            return "disabled"
    if kind == "firewalld":
        if "running" in t:
            return "enabled"
        if "not running" in t:
            return "disabled"
    return "unknown"


def parse_listening_ports(text: str, *, limit: int = 80) -> list[dict]:
    """Parse listening sockets from `lsof -nP -iTCP -sTCP:LISTEN` (macOS/Linux)
    or `ss -tlnpH` (Linux). Format-agnostic (tries both line shapes). Returns
    [{proto, addr, port, process, exposed}] — `exposed` True iff bound to a
    non-loopback address. Port + process on the user's OWN machine are safe to
    report; capped at `limit`."""
    out: list[dict] = []
    text = text or ""

    def _split_addr_port(hostport: str) -> tuple[str, str]:
        hp = hostport.strip()
        if hp.startswith("["):  # [::1]:8080
            host, _, port = hp[1:].partition("]:")
            return host, port
        host, _, port = hp.rpartition(":")
        return (host or hp), port

    # lsof: "node  123 user  22u  IPv4 ...  TCP 127.0.0.1:3000 (LISTEN)"
    for line in text.splitlines():
        m = re.search(r"\b(TCP|UDP)\s+(\S+?):(\*|\d+)\s+\(LISTEN\)", line)
        if m:
            proc = line.split()[0] if line.split() else ""
            addr, port = m.group(2), m.group(3)
            out.append({"proto": m.group(1), "addr": addr, "port": port,
                        "process": proc, "exposed": _addr_is_exposed(addr)})
            continue
        # ss -tlnpH: "LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("nginx",pid=1,fd=6))"
        m = re.match(r"^(LISTEN|UNCONN)\s+\d+\s+\d+\s+(\S+)\s+\S+(?:\s+users:\(\(\"([^\"]+)\")?", line)
        if m:
            addr, port = _split_addr_port(m.group(2))
            out.append({"proto": "tcp", "addr": addr, "port": port,
                        "process": m.group(3) or "", "exposed": _addr_is_exposed(addr)})
            continue
    # dedupe by (addr,port,process)
    seen: set[tuple] = set()
    uniq: list[dict] = []
    for r in out:
        k = (r["addr"], r["port"], r["process"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq[:limit]


def _addr_is_exposed(addr: str) -> bool:
    """True iff a listen address is reachable off-host (not loopback)."""
    a = addr.strip("[]")
    if a in ("127.0.0.1", "::1", "localhost"):
        return False
    if a in ("0.0.0.0", "::", "*"):  # nosec B104 -- classifies an address as bind-all; does not bind
        return True
    priv = _is_private_ip(a)
    # A specific LAN/any address is 'exposed' relative to loopback; unknown → treat as exposed.
    return True if priv is None else not (priv is True and a.startswith("127."))


# --- python environment -----------------------------------------------------


def detect_python_env(
    env: Mapping[str, str], *, executable: str = "", py_version: str = ""
) -> dict:
    """Active Python isolation: venv / conda / pyenv / uv / poetry / pipenv."""
    out: dict = {"executable": executable, "version": py_version}
    if env_present(env, "VIRTUAL_ENV"):
        vp = env.get("VIRTUAL_ENV") or ""
        out["virtualenv"] = {"path": vp, "name": os.path.basename(vp.rstrip("/"))}
    if env_present(env, "CONDA_DEFAULT_ENV") or env_present(env, "CONDA_PREFIX"):
        out["conda"] = env_value(env, "CONDA_DEFAULT_ENV") or os.path.basename(
            (env.get("CONDA_PREFIX") or "").rstrip("/"))
    if env_present(env, "PYENV_VERSION"):
        out["pyenv"] = env_value(env, "PYENV_VERSION")
    if env_present(env, "UV") or env_present(env, "UV_CACHE_DIR") or "uv" in (env.get("VIRTUAL_ENV") or "").lower():
        out["uv"] = True
    if env_present(env, "POETRY_ACTIVE"):
        out["poetry"] = True
    if env_present(env, "PIPENV_ACTIVE"):
        out["pipenv"] = True
    return out


# --- cloud ecosystems (presence only) ---------------------------------------


def detect_cloud(
    env: Mapping[str, str], *, which: Callable[[str], bool], exists: Callable[[str], bool]
) -> dict:
    """AWS / Azure / GCP footprint — CLIs, config dirs, service context, and
    credential PRESENCE (never a credential value)."""
    home = env.get("HOME") or os.path.expanduser("~")

    aws: dict = {}
    if any(env_present(env, k) for k in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                                         "AWS_ACCESS_KEY_ID", "AWS_EXECUTION_ENV",
                                         "AWS_LAMBDA_FUNCTION_NAME", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")) \
            or which("aws") or exists(os.path.join(home, ".aws", "config")):
        aws = {
            "cli": which("aws"),
            "config": exists(os.path.join(home, ".aws", "config")),
            "region": env_value(env, "AWS_REGION") or env_value(env, "AWS_DEFAULT_REGION"),
            "profile": env_value(env, "AWS_PROFILE") or env_value(env, "AWS_DEFAULT_PROFILE"),
            "credentials_in_env": env_present(env, "AWS_ACCESS_KEY_ID"),
            "execution_env": env_value(env, "AWS_EXECUTION_ENV"),
            "lambda": env_value(env, "AWS_LAMBDA_FUNCTION_NAME"),
            "ecs": env_present(env, "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"),
        }
        aws = {k: v for k, v in aws.items() if v}

    azure: dict = {}
    if any(env_present(env, k) for k in ("AZURE_SUBSCRIPTION_ID", "MSI_ENDPOINT", "IDENTITY_ENDPOINT",
                                         "WEBSITE_INSTANCE_ID", "FUNCTIONS_WORKER_RUNTIME",
                                         "ARM_CLIENT_ID", "AZURE_CLIENT_ID")) \
            or which("az") or exists(os.path.join(home, ".azure")):
        azure = {
            "cli": which("az"),
            "config": exists(os.path.join(home, ".azure")),
            "subscription_set": env_present(env, "AZURE_SUBSCRIPTION_ID"),
            "managed_identity": env_present(env, "MSI_ENDPOINT") or env_present(env, "IDENTITY_ENDPOINT"),
            "app_service": env_present(env, "WEBSITE_INSTANCE_ID"),
            "functions": env_value(env, "FUNCTIONS_WORKER_RUNTIME"),
            "terraform_sp": env_present(env, "ARM_CLIENT_ID"),
        }
        azure = {k: v for k, v in azure.items() if v}

    gcp: dict = {}
    if any(env_present(env, k) for k in ("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT", "GCLOUD_PROJECT",
                                         "GOOGLE_APPLICATION_CREDENTIALS", "K_SERVICE",
                                         "FUNCTION_TARGET", "GAE_APPLICATION")) \
            or which("gcloud") or exists(os.path.join(home, ".config", "gcloud")):
        gcp = {
            "cli": which("gcloud"),
            "config": exists(os.path.join(home, ".config", "gcloud")),
            "project": env_value(env, "GOOGLE_CLOUD_PROJECT") or env_value(env, "GCP_PROJECT")
            or env_value(env, "GCLOUD_PROJECT"),
            "adc_in_env": env_present(env, "GOOGLE_APPLICATION_CREDENTIALS"),
            "cloud_run": env_value(env, "K_SERVICE"),
            "cloud_functions": env_present(env, "FUNCTION_TARGET"),
            "app_engine": env_present(env, "GAE_APPLICATION"),
        }
        gcp = {k: v for k, v in gcp.items() if v}

    out = {}
    if aws:
        out["aws"] = aws
    if azure:
        out["azure"] = azure
    if gcp:
        out["gcp"] = gcp
    return out


# --- user / PATH ------------------------------------------------------------


def detect_user(
    env: Mapping[str, str], *, uid: Optional[int] = None, gid: Optional[int] = None,
    login: str = "", is_admin: Optional[bool] = None,
) -> dict:
    """User identity — all non-secret. `is_admin` (root / Windows admin) injected."""
    return {
        "login": login or env_value(env, "USER") or env_value(env, "LOGNAME")
        or env_value(env, "USERNAME") or "",
        "uid": uid,
        "gid": gid,
        "home": env.get("HOME") or env.get("USERPROFILE") or "",
        "shell": env_value(env, "SHELL") or "",
        "is_admin": is_admin,
        "sudo": bool(env_present(env, "SUDO_USER")),
        "sudo_from": env_value(env, "SUDO_USER") or "",
    }


def detect_path(env: Mapping[str, str]) -> dict:
    """PATH entries + which notable tool prefixes are present. Not secret."""
    raw = env.get("PATH") or ""
    entries = [p for p in raw.split(os.pathsep) if p]
    notable = {
        # Homebrew's locations come from daemon_path, which is the module that PREPENDS them —
        # see HOMEBREW_PATH_MARKERS. Re-listing them here would be a second copy of the same
        # fact, free to drift silently away from the one the daemon actually uses.
        "homebrew": any(
            "brew" in p or any(m in p for m in daemon_path.HOMEBREW_PATH_MARKERS)
            for p in entries
        ),
        "cargo": any(".cargo/bin" in p for p in entries),
        "go": any("/go/bin" in p or "go/bin" in p for p in entries),
        "user_local": any(p.rstrip("/").endswith(".local/bin") for p in entries),
        "nvm_node": any("nvm" in p or ".nvm" in p for p in entries),
        "pyenv": any("pyenv" in p for p in entries),
    }
    return {"count": len(entries), "entries": entries,
            "notable": {k: v for k, v in notable.items() if v}}


# --- compilers / package managers / dev tooling (presence via `which`) ------

# Curated so `which`-presence is meaningful. Value is the friendly label.
COMPILERS: tuple[tuple[str, str], ...] = (
    ("gcc", "GCC (C)"), ("g++", "GCC (C++)"), ("clang", "Clang (C)"),
    ("clang++", "Clang (C++)"), ("cc", "cc"), ("rustc", "Rust"), ("go", "Go"),
    ("javac", "Java (javac)"), ("kotlinc", "Kotlin"), ("scalac", "Scala"),
    ("swiftc", "Swift"), ("dotnet", ".NET"), ("ghc", "Haskell (GHC)"),
    ("zig", "Zig"), ("nvcc", "CUDA (nvcc)"), ("gfortran", "Fortran"),
    ("tsc", "TypeScript"), ("dmd", "D (dmd)"), ("ldc2", "D (ldc)"),
    ("nim", "Nim"), ("crystal", "Crystal"), ("ocamlopt", "OCaml"),
    ("erlc", "Erlang"), ("elixirc", "Elixir"), ("cobc", "COBOL (GnuCOBOL)"),
    ("v", "V"),
)

RUNTIMES: tuple[tuple[str, str], ...] = (
    ("python3", "Python"), ("node", "Node.js"), ("deno", "Deno"), ("bun", "Bun"),
    ("ruby", "Ruby"), ("perl", "Perl"), ("php", "PHP"), ("lua", "Lua"),
    ("julia", "Julia"), ("java", "Java (JVM)"), ("Rscript", "R"),
)

PACKAGE_MANAGERS: tuple[tuple[str, str], ...] = (
    ("apt", "apt"), ("apt-get", "apt-get"), ("dnf", "dnf"), ("yum", "yum"),
    ("pacman", "pacman"), ("zypper", "zypper"), ("apk", "apk"), ("emerge", "portage"),
    ("brew", "Homebrew"), ("port", "MacPorts"), ("nix", "Nix"), ("guix", "Guix"),
    ("npm", "npm"), ("pnpm", "pnpm"), ("yarn", "yarn"), ("pip", "pip"),
    ("pip3", "pip3"), ("pipx", "pipx"), ("uv", "uv"), ("poetry", "poetry"),
    ("conda", "conda"), ("mamba", "mamba"), ("cargo", "cargo"), ("gem", "gem"),
    ("bundle", "bundler"), ("composer", "composer"), ("mvn", "Maven"),
    ("gradle", "Gradle"), ("pod", "CocoaPods"), ("choco", "Chocolatey"),
    ("scoop", "Scoop"), ("winget", "winget"), ("snap", "snap"), ("flatpak", "flatpak"),
)

DEV_TOOLS: tuple[tuple[str, str], ...] = (
    ("git", "git"), ("gh", "GitHub CLI"), ("docker", "Docker"), ("podman", "Podman"),
    ("kubectl", "kubectl"), ("helm", "Helm"), ("terraform", "Terraform"),
    ("pulumi", "Pulumi"), ("ansible", "Ansible"), ("vagrant", "Vagrant"),
    ("packer", "Packer"), ("make", "make"), ("cmake", "CMake"), ("ninja", "Ninja"),
    ("meson", "Meson"), ("bazel", "Bazel"), ("jq", "jq"), ("yq", "yq"),
    ("rg", "ripgrep"), ("fd", "fd"), ("fzf", "fzf"), ("gdb", "gdb"), ("lldb", "lldb"),
    ("tmux", "tmux"), ("nvim", "Neovim"), ("ssh", "OpenSSH"), ("rsync", "rsync"),
    ("curl", "curl"), ("wget", "wget"), ("aws", "AWS CLI"), ("az", "Azure CLI"),
    ("gcloud", "gcloud"), ("tailscale", "Tailscale CLI"),
    # token-economy tooling (the workflow's saving trio + friends)
    ("tldr", "tldr-code CLI"), ("distill", "distill"), ("fastedit", "fastedit"),
    ("memgrep", "memgrep"), ("lean-ctx", "lean-ctx"),
)


def detect_present(
    table: tuple[tuple[str, str], ...], *, which: Callable[[str], bool],
    versions: Optional[Mapping[str, str]] = None,
) -> list[dict]:
    """For each (binary, label) in `table`, if `which(binary)` → include it, with
    an optional injected version string. Pure over `which` + `versions`."""
    versions = versions or {}
    out: list[dict] = []
    for binary, label in table:
        if which(binary):
            entry = {"binary": binary, "label": label}
            if versions.get(binary):
                entry["version"] = versions[binary]
            out.append(entry)
    return out


# --- MCP servers (secret-masked) --------------------------------------------


def _mcp_transport(cfg: dict) -> str:
    if cfg.get("url") or cfg.get("httpUrl"):
        return "http/sse"
    if cfg.get("type"):
        return str(cfg.get("type"))
    if cfg.get("command"):
        return "stdio"
    return "unknown"


# --- git / GitHub -----------------------------------------------------------


def github_slug(url: str) -> Optional[str]:
    """`owner/repo` from a git remote URL (https / ssh / git@ forms), or None.
    Only returns a slug for github.com hosts."""
    u = (url or "").strip()
    if not u:
        return None
    m = re.match(r"^(?:https?://|ssh://)?(?:[^@/]+@)?github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$", u)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def parse_git_config(text: str) -> dict:
    """Parse a `.git/config` (INI) into {remotes:{name:url}, branch_descriptions:
    {name:desc}, hooks_path:str|None}. Git keys are case-insensitive. Pure."""
    remotes: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    hooks_path: Optional[str] = None
    section, sub = "", ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            inner = line[1:-1].strip()
            m = re.match(r'(\S+)\s+"(.*)"', inner)
            if m:
                section, sub = m.group(1).lower(), m.group(2)
            else:
                section, sub = inner.lower(), ""
            continue
        if "=" not in line or line.startswith("#") or line.startswith(";"):
            continue
        key, _, val = line.partition("=")
        key, val = key.strip().lower(), val.strip()
        if section == "remote" and key == "url" and sub:
            remotes[sub] = val
        elif section == "branch" and key == "description" and sub:
            descriptions[sub] = val
        elif section == "core" and key == "hookspath":
            hooks_path = val
    return {"remotes": remotes, "branch_descriptions": descriptions, "hooks_path": hooks_path}


def parse_branches(text: str) -> list[dict]:
    """Parse `git for-each-ref --format='%(refname:short)|%(committerdate:iso8601)|
    %(upstream:short)|%(subject)'` lines into per-branch dicts. Pure."""
    out: list[dict] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 3)
        parts += [""] * (4 - len(parts))
        out.append({"name": parts[0], "last_commit": parts[1],
                    "upstream": parts[2], "subject": parts[3][:120]})
    return out


def active_git_hooks(entries: list[str], is_exec: Callable[[str], bool]) -> list[str]:
    """The ACTIVE hooks from a hooks-dir listing: names that are not `*.sample` and
    are executable (per the injected `is_exec`). Sorted. Pure."""
    return sorted(n for n in entries if not n.endswith(".sample") and is_exec(n))


def summarize_rulesets(rulesets: list) -> list[dict]:
    """Summarize a `gh api repos/<slug>/rulesets` (+ optional per-ruleset detail)
    payload into [{name, target, enforcement, branches, rule_types}]. Tolerant of
    both the list-endpoint summary and a fully-expanded ruleset object. Pure."""
    out: list[dict] = []
    for rs in rulesets or []:
        if not isinstance(rs, dict):
            continue
        cond = rs.get("conditions") or {}
        refname = (cond.get("ref_name") or {}) if isinstance(cond, dict) else {}
        branches = refname.get("include") if isinstance(refname, dict) else None
        rules = rs.get("rules") or []
        rule_types = sorted({str(r["type"]) for r in rules if isinstance(r, dict) and r.get("type")})
        out.append({
            "name": rs.get("name"),
            "target": rs.get("target"),
            "enforcement": rs.get("enforcement"),
            "branches": branches if isinstance(branches, list) else [],
            "rule_types": rule_types,
        })
    return out


# --- plugins / staleness ----------------------------------------------------


def _semver_tuple(s: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in re.split(r"[.\-+]", s.strip().lstrip("v"))[:3] if p.isdigit())
    except (ValueError, AttributeError):
        return (-1,)


def version_stale(installed: str, latest: str) -> str:
    """Compare two semver-ish strings → 'up-to-date' / 'stale (<latest> available)'
    / 'unknown'. Pure."""
    if not installed or not latest:
        return "unknown"
    a, b = _semver_tuple(installed), _semver_tuple(latest)
    if a == (-1,) or b == (-1,):
        return "unknown"
    if a >= b:
        return "up-to-date"
    return f"stale ({latest} available)"


def parse_enabled_plugins(enabled: Mapping[str, object]) -> dict:
    """Summarize Claude Code's `settings.json.enabledPlugins` map
    (`name@marketplace -> bool`) into counts + per-marketplace tallies + the enabled
    names (capped). Pure — never emits anything secret (plugin names are public)."""
    installed = len(enabled)
    enabled_names = [k for k, v in enabled.items() if v]
    by_mkt: dict[str, dict] = {}
    for name, on in enabled.items():
        mkt = name.split("@", 1)[1] if "@" in name else "(local)"
        slot = by_mkt.setdefault(mkt, {"enabled": 0, "total": 0})
        slot["total"] += 1
        if on:
            slot["enabled"] += 1
    return {
        "installed": installed,
        "enabled": len(enabled_names),
        "disabled": installed - len(enabled_names),
        "enabled_names": sorted(enabled_names)[:60],
        "marketplaces": by_mkt,
    }


def detect_subscription(env: Mapping[str, str]) -> dict:
    """Best-effort, LOCAL-only Claude/Anthropic auth mode.

    The subscription TIER (Pro / Max / Team / Enterprise / API) is NOT locally
    determinable — it lives behind a live API call or a keychain read this tool
    deliberately does not make (no network; no `-w` keychain read, per the ACL-flood
    lesson). So we report the auth MODE, which IS knowable from env, and mark the
    tier explicitly as needing a live probe rather than guessing.
    """
    if env_present(env, "ANTHROPIC_API_KEY") or env_present(env, "CLAUDE_API_KEY"):
        return {"auth_mode": "API key (pay-as-you-go)", "tier": "API (usage-billed)"}
    if env_present(env, "CLAUDECODE") or env_present(env, "CLAUDE_CODE_ENTRYPOINT"):
        return {"auth_mode": "Claude subscription (OAuth login)",
                "tier": "unknown (needs a live account probe)"}
    return {"auth_mode": "unknown", "tier": "unknown"}


# --- CI workflows / actions / platforms -------------------------------------


def parse_workflow_actions(texts: list[str]) -> dict:
    """From workflow file contents: the deduped set of third-party `uses:` action
    refs (owner/name, @sha/@tag stripped) + whether a Claude Code action is present.
    Local (`./…`) actions are ignored. Pure."""
    actions: set[str] = set()
    for t in texts or []:
        for m in re.finditer(r"^\s*-?\s*uses:\s*([^\s#]+)", t or "", re.MULTILINE):
            ref = m.group(1).strip().strip("\"'")
            if ref.startswith(".") or ref.startswith("docker://"):
                continue
            actions.add(ref.split("@", 1)[0])
    claude = any("anthropics/claude" in a.lower() or "claude-code-action" in a.lower()
                 for a in actions)
    return {"actions": sorted(actions), "claude_action": claude}


def _norm_platform(token: str, out: set[str]) -> None:
    s = token.lower()
    if "ubuntu" in s or "linux" in s:
        out.add("linux")
    if "macos" in s or "mac-" in s or "darwin" in s or s.strip() == "macos":
        out.add("macos")
    if "windows" in s or "win-" in s:
        out.add("windows")


def parse_workflow_platforms(texts: list[str]) -> list[str]:
    """CI target platforms from `runs-on:` values + strategy-matrix `os:` arrays →
    normalized {linux, macos, windows}. Pure (best-effort over YAML text)."""
    plats: set[str] = set()
    for t in texts or []:
        for m in re.finditer(r"runs-on:\s*(.+)", t or ""):
            _norm_platform(m.group(1), plats)
        for m in re.finditer(r"\bos:\s*\[([^\]]+)\]", t or ""):
            for tok in m.group(1).split(","):
                _norm_platform(tok, plats)
    return sorted(plats)


# --- gh auth ----------------------------------------------------------------


def parse_gh_auth(text: str) -> dict:
    """Parse `gh auth status` → {logged_in, username, scopes, working}. NEVER reads
    the token (gh masks it in this output; we extract only login + scopes). Pure."""
    logged_in = "Logged in to" in (text or "")
    m = re.search(r"Logged in to \S+ account (\S+)", text or "")
    username = m.group(1) if m else ""
    sm = re.search(r"Token scopes:\s*(.+)", text or "")
    scopes = [s.strip().strip("'\"") for s in sm.group(1).split(",")] if sm else []
    return {"logged_in": logged_in, "username": username, "scopes": scopes,
            "working": logged_in and bool(username)}


def parse_active_gh_user(hosts_yaml: str) -> str:
    """The active gh username from `~/.config/gh/hosts.yml` (offline). Pure."""
    m = re.search(r"^\s*user:\s*(\S+)", hosts_yaml or "", re.MULTILINE)
    return m.group(1).strip() if m else ""


# --- package name / registries / topology / fork / homebrew -----------------


def project_name_from_manifest(*, pyproject: str = "", package_json: str = "",
                               cargo: str = "") -> Optional[str]:
    """The distributable package name from the first manifest that carries one
    (pyproject `[project] name`, package.json `name`, Cargo `[package] name`). Pure."""
    m = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', pyproject)
    if m:
        return m.group(1)
    try:
        d = json.loads(package_json) if package_json else {}
        if isinstance(d, dict) and isinstance(d.get("name"), str) and d["name"]:
            return d["name"]
    except ValueError:
        pass
    m = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', cargo)
    return m.group(1) if m else None


def classify_repo_topology(*, languages: list[str], nested_git_count: int,
                           has_submodules: bool, workspaces: list[str],
                           repo_symlinks: list[str]) -> dict:
    """Classify the repo: single-project vs mono-repo, single vs mixed language,
    single-git vs multi-git. Pure over pre-gathered signals."""
    multi_git = nested_git_count > 0 or has_submodules
    mono = bool(workspaces) or multi_git
    return {
        "structure": "mono-repo" if mono else "single-project",
        "languages": sorted(set(languages)),
        "mixed_language": len(set(languages)) > 1,
        "git": "multi-git" if multi_git else "single-git",
        "nested_repos": nested_git_count,
        "submodules": has_submodules,
        "workspaces": workspaces,
        "repo_symlinks": repo_symlinks,
    }


def summarize_fork(gh_json: object, *, upstream_remote: str = "") -> dict:
    """Fork/collaboration summary from `gh repo view --json isFork,parent` + any
    local `upstream` remote. Pure."""
    is_fork = False
    parent = ""
    if isinstance(gh_json, dict):
        is_fork = bool(gh_json.get("isFork"))
        p = gh_json.get("parent")
        if isinstance(p, dict):
            parent = p.get("nameWithOwner") or ""
            if not parent and isinstance(p.get("owner"), dict):
                parent = f"{p['owner'].get('login', '')}/{p.get('name', '')}".strip("/")
    return {"is_fork": is_fork or bool(upstream_remote),
            "upstream": parent or github_slug(upstream_remote) or upstream_remote or ""}


def homebrew_tap_status(repo_name: str, *, has_formula_dir: bool,
                        tapped: Optional[bool] = None,
                        trusted: Optional[bool] = None) -> Optional[dict]:
    """If this repo is a Homebrew TAP (name `homebrew-*` or a Formula/ dir), return
    its trust status + the Tap-Trust requirement note; None if it is not a tap.

    Homebrew 6.0.0 (2026-06-11) made third-party taps require EXPLICIT trust before
    their Ruby is evaluated — so a tap's consumers now need `brew trust` (or
    `trusted: true` in their Brewfile). A repo cannot self-declare trust; this flags
    the requirement so a tap author documents it. Pure."""
    name = (repo_name or "").split("/")[-1]
    if not (name.startswith("homebrew-") or has_formula_dir):
        return None
    return {
        "is_tap": True, "tapped_locally": tapped, "trusted": trusted,
        "note": ("Homebrew 6.0.0+ requires EXPLICIT trust for third-party taps — "
                 "consumers must `brew trust --formula <user>/<repo>/<formula>` (or set "
                 "`trusted: true` in a Brewfile) before install; document this."),
    }


def detect_mcp_servers(configs: list[tuple[str, dict]]) -> list[dict]:
    """Flatten MCP-server definitions from parsed config files into a SECRET-SAFE
    list. `configs` is [(source_label, parsed_json_dict), ...]; each dict may hold
    a top-level `mcpServers` map. For each server emit ONLY name + transport +
    host-or-command-basename + source — NEVER args, env values, or URL query
    strings (any of which can carry a token). Pure."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source, data in configs:
        if not isinstance(data, dict):
            continue
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            continue
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            key = (source, str(name))
            if key in seen:
                continue
            seen.add(key)
            transport = _mcp_transport(cfg)
            where = ""
            if cfg.get("url") or cfg.get("httpUrl"):
                url = str(cfg.get("url") or cfg.get("httpUrl"))
                m = re.match(r"^([a-zA-Z][\w+.-]*://[^/?#]+)", url)  # scheme://host only
                where = m.group(1) if m else "(url)"
            elif cfg.get("command"):
                where = os.path.basename(str(cfg.get("command")))
            out.append({"name": str(name), "transport": transport,
                        "endpoint": where, "source": source})
    return out
