#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-identify-environment (TRDD-db169d9e follow-up).

Reports, for the CURRENT session, a full picture of WHERE and HOW it is running.
This file is the thin I/O layer: it gathers raw facts from the host — `ps`,
`mount`, `ifconfig`/`ip`, `route`, `scutil`, `lsof`/`ss`, config files, `which`,
`os.*` identity — and hands them to the PURE classifiers in
`scripts/lib/env_detect.py`, which own every decision and are unit-tested by
injecting synthetic inputs.

What it detects:

  - terminal app (ancestry + env signals) & multiplexer; OS + kernel + WSL +
    Windows edition; filesystem type (+ network-mount flag);
  - CI / remote execution (GitHub Actions & friends); containers, VMs, sandboxes;
    the hosting editor/IDE and the Claude Code surface (CLI vs desktop);
  - execution context (interactive TTY vs headless / background agent) and whether
    the cwd is a LINKED git worktree;
  - network: proxies (credential-masked), VPN / Tailscale / WireGuard / WARP,
    default gateway, behind-NAT inference, DNS resolvers, firewall state,
    interfaces, and locally-listening services;
  - python venv / conda / pyenv / uv; AWS / Azure / GCP footprint (presence only);
    user identity; PATH; installed compilers, runtimes, package managers, dev
    tooling (with versions); and the configured MCP servers (secret-masked).

Invariants inherited from env_detect: never emits a secret VALUE, makes NO network
call, and fails open (a probe that errors becomes an empty/"unknown" field, never
a crash). `--json` emits the machine-readable object; `--fast` skips the slowest
LOCAL probes (tool versions + listening-ports scan).
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import env_detect  # noqa: E402
import state  # noqa: E402


def _out(cmd: list[str], timeout: float = 5.0) -> str:
    """Run a command, return stripped stdout, or '' on any failure. Never raises.

    Catches broadly on purpose (fail-open): a diagnostic must degrade a single
    unavailable/blocked probe to '' rather than crash the whole report.
    `run_subprocess` already swallows the OS-level failures, but a probe can raise
    other things — a permission wall, or the test process-sandbox denying a
    machine-reading binary (`ifconfig`/`route`/`scutil`/a compiler `--version`).
    """
    try:
        proc = state.run_subprocess(cmd, timeout=timeout, capture=True)
    except Exception:  # noqa: BLE001 - fail-open: one probe must never sink the report
        return ""
    if proc is None or proc.returncode != 0 or not proc.stdout:
        return ""
    return proc.stdout.strip()


def _out_any(cmd: list[str], timeout: float = 3.0) -> str:
    """Like `_out` but returns stdout OR stderr (some tools print --version to
    stderr) and does not require a zero exit — best-effort first-line capture.
    Same fail-open contract as `_out`."""
    try:
        proc = state.run_subprocess(cmd, timeout=timeout, capture=True)
    except Exception:  # noqa: BLE001 - fail-open (see _out)
        return ""
    if proc is None:
        return ""
    text = (proc.stdout or "") + (proc.stderr or "")
    return text.strip()


def _which(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


def _session_tty() -> str:
    """The SESSION's controlling TTY (e.g. `s000`), or `??` when truly headless.

    NOT this process's own tty. Two layers strip it: `os.isatty` is always False
    because the script runs with PIPED stdio, AND — the trap this very tool exists
    to expose — Claude Code's Bash tool spawns the subprocess WITHOUT a controlling
    terminal, so even `ps -o tty= -p <self>` reports `??` inside a fully interactive
    iTerm session. The real interactivity lives on an ANCESTOR (the `claude` process
    / its login shell), so we walk the ancestry and return the FIRST real tty. A
    genuinely detached/background session has `??` all the way up → correctly `??`.
    """
    try:
        proc = state.run_subprocess(["ps", "-axo", "pid=,ppid=,tty=,command="],
                                    timeout=5.0, capture=True)
    except Exception:  # noqa: BLE001 - fail-open: headless '??' beats a crash
        return ""
    if proc is None or not proc.stdout:
        return ""
    table: dict[int, tuple[int, str]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        table[pid] = (ppid, parts[2])
    cur, seen = os.getpid(), set()
    for _ in range(64):
        entry = table.get(cur)
        if entry is None:
            break
        ppid, tty = entry
        if tty and tty not in ("??", "?", "-"):
            return tty
        if ppid <= 1 or ppid in seen:
            break
        seen.add(cur)
        cur = ppid
    return "??"


# --- back-compat public functions (the existing tests call these) -----------


def detect_terminal() -> dict:
    """Terminal identity. Keeps the original keys (`kind`, `in_ai_maestro_agent`)
    and adds the rich env-reconciled fields from env_detect."""
    kind = state.terminal_kind()
    rich = env_detect.detect_terminal(os.environ, ancestry_kind=kind)
    rich["in_ai_maestro_agent"] = state.in_ai_maestro_agent_env()
    return rich


def detect_ancestry() -> list[str]:
    try:
        proc = state.run_subprocess(["ps", "-axo", "pid=,ppid=,command="], timeout=5.0, capture=True)
    except Exception:  # noqa: BLE001 - fail-open: never crash the report on a probe failure
        return []
    if proc is None or not proc.stdout:
        return []
    table = state.parse_ps_table(proc.stdout)
    return [c[:120] for c in state.process_ancestry(os.getpid(), table)[:8]]


def detect_tmux() -> dict | None:
    pane = (os.environ.get("TMUX_PANE") or "").strip()
    if not (os.environ.get("TMUX") or pane):
        return None
    session = _out(["tmux", "display-message", "-p", "#{session_name}"])
    window = _out(["tmux", "display-message", "-p", "#{window_index}:#{window_name}"])
    return {"session": session, "pane": pane, "window": window}


def detect_os() -> dict:
    system = platform.system()
    release = platform.release()
    version = ""
    edition = ""
    if system == "Darwin":
        product = _out(["sw_vers", "-productVersion"])
        build = _out(["sw_vers", "-buildVersion"])
        version = (f"macOS {product}" + (f" (build {build})" if build else "")) if product \
            else f"macOS (Darwin {release})"
    elif system == "Linux":
        try:
            version = platform.freedesktop_os_release().get("PRETTY_NAME", "")
        except (OSError, AttributeError):
            version = ""
        if not version:
            version = f"Linux {release}"
    elif system == "Windows":
        version = f"Windows {platform.version()}"
        try:
            edition = platform.win32_edition() or ""
        except (AttributeError, OSError):
            edition = ""
    else:
        version = f"{system} {release}"
    out: dict[str, object] = {"system": system, "release": release,
                              "arch": platform.machine(), "version": version}
    if edition:
        out["edition"] = edition
    proc_version = ""
    if Path("/proc/version").exists():
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8")
        except OSError:
            proc_version = ""
    wsl = env_detect.detect_wsl(os.environ, proc_version=proc_version)
    if wsl:
        out["wsl"] = wsl
    return out


def detect_filesystem(path: str = ".") -> str:
    system = platform.system()
    target = os.path.realpath(path)
    if system in ("Darwin", "Linux"):
        fs = env_detect.parse_mount_fstype(_out(["mount"]), target)
        if fs:
            return fs
    if system == "Linux":
        fs = _out(["stat", "-f", "-c", "%T", target])
        if fs:
            return fs
        return _out(["findmnt", "-no", "FSTYPE", "--target", target]) or "unknown"
    if system == "Windows":
        return "NTFS (assumed)"
    return "unknown"


def detect_sandboxing() -> list[str]:
    """Container / VM / sandbox signals. Backed by env_detect.detect_containers,
    augmented with `systemd-detect-virt` on Linux."""
    virt = _out(["systemd-detect-virt"]) if platform.system() == "Linux" else ""
    return env_detect.detect_containers(os.environ, exists=os.path.exists, virt=virt)


# --- new gatherers (I/O → pure classifiers) ---------------------------------


def _gather_git_context() -> dict:
    inside = _out(["git", "rev-parse", "--is-inside-work-tree"]) == "true"
    git_dir = _out(["git", "rev-parse", "--absolute-git-dir"]) if inside else ""
    common = _out(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]) if inside else ""
    return {"inside": inside, "git_dir": git_dir, "common": common}


def _gather_network() -> dict:
    system = platform.system()
    iface_text = _out(["ifconfig", "-a"]) or _out(["ip", "-o", "addr"])
    interfaces = env_detect.parse_interfaces(iface_text, system=system)
    route_text = _out(["route", "-n", "get", "default"]) or _out(["ip", "route"])
    dns_text = _out(["scutil", "--dns"])
    if not dns_text and Path("/etc/resolv.conf").exists():
        try:
            dns_text = Path("/etc/resolv.conf").read_text(encoding="utf-8")
        except OSError:
            dns_text = ""
    # Firewall — best-effort, only the states readable without root.
    fw_state, fw_kind = "", ""
    if system == "Darwin":
        alf = _out(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"])
        fw_state, fw_kind = env_detect.parse_firewall_state(alf, kind="macos-alf"), "macOS ALF"
    elif system == "Linux":
        fc = _out(["firewall-cmd", "--state"])
        if fc:
            fw_state, fw_kind = env_detect.parse_firewall_state(fc, kind="firewalld"), "firewalld"
        else:
            uf = _out(["ufw", "status"])
            fw_state, fw_kind = env_detect.parse_firewall_state(uf, kind="ufw"), "ufw"
    return {
        "proxies": env_detect.detect_proxies(os.environ),
        "interfaces": interfaces,
        "vpn": env_detect.detect_vpn(interfaces, which=_which),
        "gateway": env_detect.parse_default_gateway(route_text),
        "behind_nat": env_detect.classify_nat(interfaces),
        "dns": env_detect.parse_dns_servers(dns_text),
        "firewall": {"kind": fw_kind, "state": fw_state} if fw_kind else None,
    }


def _gather_listening_ports() -> list[dict]:
    text = _out(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=8.0)
    if not text:
        text = _out(["ss", "-tlnpH"], timeout=6.0)
    return env_detect.parse_listening_ports(text)


# `<binary>`: argv used to read its version (default `--version`; some print to
# stderr or use `-version`). Only probed for binaries `which` found present.
_VERSION_ARGV: dict[str, list[str]] = {
    "javac": ["-version"], "java": ["-version"], "go": ["version"],
    "kotlinc": ["-version"], "scalac": ["-version"], "zig": ["version"],
    "v": ["version"],
}


def _tool_versions(present: list[str], *, cap: int = 24) -> dict[str, str]:
    """First-line version string for each present binary, bounded to `cap` probes."""
    out: dict[str, str] = {}
    for binary in present[:cap]:
        argv = [binary, *_VERSION_ARGV.get(binary, ["--version"])]
        line = _out_any(argv, timeout=2.0)
        if line:
            out[binary] = line.splitlines()[0][:80]
    return out


def _gather_mcp_servers() -> list[dict]:
    home = os.environ.get("HOME") or os.path.expanduser("~")
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    candidates = [
        ("~/.claude.json", Path(home) / ".claude.json"),
        ("~/.claude/settings.json", Path(home) / ".claude" / "settings.json"),
        ("project .mcp.json", Path(project) / ".mcp.json"),
        ("project .claude/settings.json", Path(project) / ".claude" / "settings.json"),
    ]
    configs: list[tuple[str, dict]] = []
    for label, path in candidates:
        try:
            if path.is_file():
                configs.append((label, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return env_detect.detect_mcp_servers(configs)


def _identity() -> dict:
    import getpass
    login = ""
    try:
        login = getpass.getuser()
    except Exception:  # noqa: BLE001 - getuser can raise KeyError on odd uids
        login = ""
    uid = getattr(os, "getuid", lambda: None)()
    gid = getattr(os, "getgid", lambda: None)()
    is_admin = None
    if hasattr(os, "geteuid"):
        is_admin = os.geteuid() == 0
    elif platform.system() == "Windows":
        try:
            import ctypes
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            is_admin = None
    return env_detect.detect_user(os.environ, uid=uid, gid=gid, login=login, is_admin=is_admin)


def gather(*, fast: bool = False) -> dict:
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    git = _gather_git_context()
    tty = _session_tty()
    has_tty = bool(tty and tty not in ("??", "?"))

    compilers_present = [b for b, _ in env_detect.COMPILERS if _which(b)]
    runtimes_present = [b for b, _ in env_detect.RUNTIMES if _which(b)]
    versions: dict[str, str] = {} if fast else _tool_versions(compilers_present + runtimes_present)

    return {
        # --- original keys (back-compat contract) ---
        "terminal": detect_terminal(),
        "ancestry": detect_ancestry(),
        "tmux": detect_tmux(),
        "os": detect_os(),
        "filesystem": detect_filesystem(project),
        "sandboxing": detect_sandboxing(),
        "project_dir": project,
        "cwd": os.getcwd(),
        # --- new sections ---
        "multiplexer": env_detect.detect_multiplexer(os.environ),
        "filesystem_network": env_detect.filesystem_is_network(detect_filesystem(project)),
        "ci": env_detect.detect_ci(os.environ),
        "ide": env_detect.detect_ide(os.environ),
        "execution": env_detect.detect_execution_context(
            os.environ, has_tty=has_tty, git_dir=git["git_dir"],
            git_common_dir=git["common"], inside_work_tree=git["inside"]),
        "tty": tty,
        "user": _identity(),
        "python": env_detect.detect_python_env(
            os.environ, executable=sys.executable, py_version=platform.python_version()),
        "cloud": env_detect.detect_cloud(os.environ, which=_which, exists=os.path.exists),
        "network": _gather_network(),
        "listening": [] if fast else _gather_listening_ports(),
        "path": env_detect.detect_path(os.environ),
        "compilers": env_detect.detect_present(env_detect.COMPILERS, which=_which, versions=versions),
        "runtimes": env_detect.detect_present(env_detect.RUNTIMES, which=_which, versions=versions),
        "package_managers": env_detect.detect_present(env_detect.PACKAGE_MANAGERS, which=_which),
        "dev_tools": env_detect.detect_present(env_detect.DEV_TOOLS, which=_which),
        "mcp_servers": _gather_mcp_servers(),
    }


# --- rendering --------------------------------------------------------------


def _fmt_list(items: list[str], empty: str = "none") -> str:
    return ", ".join(items) if items else empty


def _render(info: dict) -> str:  # noqa: C901 - a flat report builder; branching is inherent
    t = info["terminal"]
    os_ = info["os"]
    lines = ["## Environment", ""]

    # Terminal / multiplexer
    term = f"- **Terminal/program:** `{t.get('program') or t['kind']}`"
    if t.get("kind") and t["kind"] != t.get("program"):
        term += f"  (ancestry kind: `{t['kind']}`)"
    if t.get("version"):
        term += f"  · v{t['version']}"
    if t.get("in_ai_maestro_agent"):
        term += "  ·  **inside ai-maestro agent**"
    lines.append(term)
    mux = info.get("multiplexer")
    if mux:
        lines.append(f"- **Multiplexer:** `{mux['kind']}`" + (f" · {mux.get('pane') or mux.get('session') or ''}"))
    tm = info.get("tmux")
    if tm:
        lines.append(f"- **tmux:** session `{tm['session'] or '?'}` · pane `{tm['pane'] or '?'}`"
                     + (f" · window `{tm['window']}`" if tm.get("window") else ""))

    # OS / filesystem
    os_line = f"- **OS:** {os_['version']}  ·  arch `{os_['arch']}`  (`{os_['system']} {os_['release']}`)"
    if os_.get("edition"):
        os_line += f"  · {os_['edition']}"
    lines.append(os_line)
    if os_.get("wsl"):
        w = os_["wsl"]
        lines.append(f"    - **WSL:** {w.get('version', 'WSL')} · distro `{w.get('distro') or '?'}`")
    fs = info["filesystem"]
    lines.append(f"- **Filesystem (project dir):** `{fs}`"
                 + ("  ⚠ network mount" if info.get("filesystem_network") else ""))

    # Container / CI / execution context
    sb = info["sandboxing"]
    lines.append(f"- **Container/dev-box/sandbox:** {'; '.join(sb) if sb else 'none detected (bare host)'}")
    ci = info.get("ci")
    if ci:
        detail = ""
        if ci.get("github"):
            g = ci["github"]
            detail = "  ·  " + " · ".join(f"{k}={v}" for k, v in g.items())
        lines.append(f"- **CI / remote execution:** {ci['provider']}{detail}")
    ex = info.get("execution", {})
    ctx = "interactive TTY" if ex.get("interactive_tty") else "headless / no TTY"
    tags = []
    if ex.get("background_agent"):
        tags.append("background agent")
    if ex.get("ai_maestro_agent"):
        tags.append("ai-maestro agent")
    if ex.get("linked_worktree"):
        tags.append("LINKED git worktree")
    elif ex.get("git_worktree"):
        tags.append("git worktree (main)")
    lines.append(f"- **Execution context:** {ctx}"
                 + (f"  ·  {', '.join(tags)}" if tags else "")
                 + (f"  · tty `{info.get('tty')}`" if info.get("tty") else ""))

    # Editor / Claude
    ide = info.get("ide", {})
    claude = ide.get("claude", {})
    ed = ide.get("editor") or "—"
    cl = ""
    if claude.get("is_claude_code"):
        cl = f"  ·  **Claude Code** ({claude.get('surface', '?')}"
        cl += f", entrypoint={claude['entrypoint']}" if claude.get("entrypoint") else ""
        cl += ")"
    lines.append(f"- **Editor/IDE:** {ed}{cl}")

    # User
    u = info.get("user", {})
    admin = "root/admin" if u.get("is_admin") else ("non-admin" if u.get("is_admin") is False else "?")
    uline = f"- **User:** `{u.get('login') or '?'}`"
    if u.get("uid") is not None:
        uline += f" (uid {u['uid']})"
    uline += f" · {admin}"
    if u.get("sudo"):
        uline += f" · via sudo from `{u.get('sudo_from')}`"
    if u.get("shell"):
        uline += f" · shell `{u['shell']}`"
    lines.append(uline)

    # Python
    py = info.get("python", {})
    pyline = f"- **Python:** {py.get('version', '?')}  ·  `{py.get('executable', '')}`"
    for k in ("virtualenv", "conda", "pyenv", "uv", "poetry", "pipenv"):
        if k in py:
            val = py[k]
            pyline += f" · {k}" + (f"=`{val['name']}`" if isinstance(val, dict) else (f"=`{val}`" if val is not True else ""))
    lines.append(pyline)

    # Cloud
    cloud = info.get("cloud", {})
    if cloud:
        parts = []
        for prov in ("aws", "azure", "gcp"):
            if prov in cloud:
                facts = "; ".join(f"{k}={v}" for k, v in cloud[prov].items())
                parts.append(f"{prov.upper()}: {facts}")
        lines.append("- **Cloud:** " + "  |  ".join(parts))

    # Network
    net = info.get("network", {})
    if net.get("proxies"):
        lines.append("- **Proxies:** " + ", ".join(f"{k}=`{v}`" for k, v in net["proxies"].items()))
    vpn = net.get("vpn", {})
    if vpn.get("kinds") or vpn.get("tunnels"):
        lines.append(f"- **VPN:** {_fmt_list(vpn.get('kinds', []))}"
                     + (f"  · tunnels: {_fmt_list(vpn.get('tunnels', []))}" if vpn.get("tunnels") else ""))
    natline = ""
    if net.get("behind_nat") is True:
        natline = "behind NAT (all IPv4 private)"
    elif net.get("behind_nat") is False:
        natline = "has a public/routable IPv4"
    lines.append("- **Network config:** "
                 + f"gateway `{net.get('gateway') or '?'}`"
                 + (f" · {natline}" if natline else "")
                 + (f" · DNS: {_fmt_list(net.get('dns', []))}" if net.get("dns") else "")
                 + (f" · firewall {net['firewall']['kind']}: {net['firewall']['state']}"
                    if net.get("firewall") else ""))
    ifaces = net.get("interfaces", [])
    if ifaces:
        names = [i["name"] for i in ifaces if i.get("addrs")]
        lines.append(f"    - **Interfaces (with IPs):** {_fmt_list(names)}")

    # Listening services
    listening = info.get("listening", [])
    if listening:
        exposed = [x for x in listening if x.get("exposed")]
        lines.append(f"- **Listening services:** {len(listening)} port(s)"
                     + (f" · {len(exposed)} reachable off-host ⚠" if exposed else " (all loopback)"))
        for x in listening[:12]:
            flag = " ⚠exposed" if x.get("exposed") else ""
            lines.append(f"    - `{x['addr']}:{x['port']}` {x.get('process') or '?'}{flag}")
        if len(listening) > 12:
            lines.append(f"    - … +{len(listening) - 12} more")

    # Toolchain
    def _names(section: str) -> list[str]:
        out = []
        for e in info.get(section, []):
            label = e["label"]
            out.append(f"{label} ({e['version']})" if e.get("version") else label)
        return out
    if info.get("compilers"):
        lines.append(f"- **Compilers:** {_fmt_list(_names('compilers'))}")
    if info.get("runtimes"):
        lines.append(f"- **Runtimes:** {_fmt_list(_names('runtimes'))}")
    if info.get("package_managers"):
        lines.append(f"- **Package managers:** {_fmt_list([e['label'] for e in info['package_managers']])}")
    if info.get("dev_tools"):
        lines.append(f"- **Dev tooling:** {_fmt_list([e['label'] for e in info['dev_tools']])}")

    # MCP
    mcp = info.get("mcp_servers", [])
    if mcp:
        lines.append(f"- **MCP servers ({len(mcp)}):** "
                     + ", ".join(f"`{m['name']}`({m['transport']})" for m in mcp[:20]))

    # PATH
    p = info.get("path", {})
    if p:
        notable = ", ".join(p.get("notable", {}).keys())
        lines.append(f"- **PATH:** {p.get('count', 0)} entries"
                     + (f" · {notable}" if notable else ""))

    # Project + ancestry
    lines.append(f"- **Project dir:** `{info['project_dir']}`")
    if info["ancestry"]:
        lines.append("- **Launch process chain (nearest first):**")
        for cmd in info["ancestry"]:
            lines.append(f"    - `{cmd}`")
    return "\n".join(lines)


def main() -> int:
    fast = "--fast" in sys.argv[1:]
    info = gather(fast=fast)
    if "--json" in sys.argv[1:]:
        print(json.dumps(info, indent=2))
    else:
        print(_render(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
