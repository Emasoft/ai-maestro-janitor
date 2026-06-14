#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-identify-environment (TRDD-db169d9e follow-up).

Reports, for the CURRENT session, everything about where it is running:

  - the hosting terminal / program (iTerm, tmux, …) by PROCESS ANCESTRY (not
    fragile $TERM_PROGRAM inference) + whether it is inside an ai-maestro agent;
  - the launching process chain (nearest ancestors);
  - the tmux session + pane id, if any;
  - the OS, OS version, and CPU arch;
  - the filesystem type backing the project directory;
  - whether it is running inside a container / dev-box / sandbox, and which one.

Pure observation — changes nothing. `--json` emits a machine-readable object.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import state  # noqa: E402


def _out(cmd: list[str], timeout: float = 5.0) -> str:
    """Run a command, return stripped stdout, or '' on any failure."""
    proc = state.run_subprocess(cmd, timeout=timeout, capture=True)
    if proc is None or proc.returncode != 0 or not proc.stdout:
        return ""
    return proc.stdout.strip()


def detect_terminal() -> dict:
    return {
        "kind": state.terminal_kind(),                       # process-ancestry walk
        "in_ai_maestro_agent": state.in_ai_maestro_agent_env(),
    }


def detect_ancestry() -> list[str]:
    proc = state.run_subprocess(["ps", "-axo", "pid=,ppid=,command="], timeout=5.0, capture=True)
    if proc is None or not proc.stdout:
        return []
    table = state.parse_ps_table(proc.stdout)
    # Nearest 8 ancestors, each trimmed so the report stays readable.
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
    if system == "Darwin":
        product = _out(["sw_vers", "-productVersion"])
        build = _out(["sw_vers", "-buildVersion"])
        if product:
            version = f"macOS {product}" + (f" (build {build})" if build else "")
        else:
            version = f"macOS (Darwin {release})"
    elif system == "Linux":
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    version = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            pass
        if not version:
            version = f"Linux {release}"
    else:
        version = f"{system} {release}"
    return {"system": system, "release": release, "arch": platform.machine(), "version": version}


def detect_filesystem(path: str = ".") -> str:
    system = platform.system()
    target = os.path.realpath(path)
    if system == "Darwin":
        # `mount` lines look like: "/dev/disk3s1s1 on / (apfs, sealed, local, …)".
        # Pick the line whose mountpoint is the LONGEST prefix of our path.
        best_mp, best_fs = "", ""
        for line in _out(["mount"]).splitlines():
            if " on " not in line or "(" not in line:
                continue
            mp = line.split(" on ", 1)[1].split(" (", 1)[0]
            fstype = line.split("(", 1)[1].split(",", 1)[0].split(")", 1)[0].strip()
            if (target == mp or target.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best_mp):
                best_mp, best_fs = mp, fstype
        return best_fs or "unknown"
    if system == "Linux":
        fs = _out(["stat", "-f", "-c", "%T", target])
        if fs:
            return fs
        fs = _out(["findmnt", "-no", "FSTYPE", "--target", target])
        return fs or "unknown"
    return "unknown"


def detect_sandboxing() -> list[str]:
    """Every container / dev-box / sandbox signal we can observe. Empty = bare host."""
    signals: list[str] = []
    # Filesystem markers
    if Path("/.dockerenv").exists():
        signals.append("docker (/.dockerenv)")
    if Path("/run/.containerenv").exists():
        signals.append("podman (/run/.containerenv)")
    # cgroup hints (Linux)
    try:
        cg = Path("/proc/1/cgroup").read_text(encoding="utf-8")
        if "docker" in cg and not any("docker" in s for s in signals):
            signals.append("docker (cgroup)")
        elif "kubepods" in cg:
            signals.append("kubernetes (cgroup)")
        elif "containerd" in cg:
            signals.append("containerd (cgroup)")
    except OSError:
        pass
    # WSL
    try:
        ver = Path("/proc/version").read_text(encoding="utf-8").lower()
        if "microsoft" in ver or "wsl" in ver:
            signals.append("WSL")
    except OSError:
        pass
    # Env-var markers (dev boxes, orchestrators, sandboxes)
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
        if (os.environ.get(var) or "").strip():
            signals.append(f"{label} (${var})")
    return signals


def gather() -> dict:
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    return {
        "terminal": detect_terminal(),
        "ancestry": detect_ancestry(),
        "tmux": detect_tmux(),
        "os": detect_os(),
        "filesystem": detect_filesystem(project),
        "sandboxing": detect_sandboxing(),
        "project_dir": project,
        "cwd": os.getcwd(),
    }


def _render(info: dict) -> str:
    t = info["terminal"]
    os_ = info["os"]
    lines = ["## Environment", ""]
    lines.append(f"- **Terminal/program:** `{t['kind']}`"
                 + ("  ·  **inside ai-maestro agent**" if t["in_ai_maestro_agent"] else ""))
    if info["tmux"]:
        tm = info["tmux"]
        lines.append(f"- **tmux:** session `{tm['session'] or '?'}` · pane `{tm['pane'] or '?'}`"
                     + (f" · window `{tm['window']}`" if tm["window"] else ""))
    else:
        lines.append("- **tmux:** not in tmux")
    lines.append(f"- **OS:** {os_['version']}  ·  arch `{os_['arch']}`  (`{os_['system']} {os_['release']}`)")
    lines.append(f"- **Filesystem (project dir):** `{info['filesystem']}`")
    sb = info["sandboxing"]
    lines.append(f"- **Container/dev-box/sandbox:** {'; '.join(sb) if sb else 'none detected (bare host)'}")
    lines.append(f"- **Project dir:** `{info['project_dir']}`")
    if info["ancestry"]:
        lines.append("- **Launch process chain (nearest first):**")
        for cmd in info["ancestry"]:
            lines.append(f"    - `{cmd}`")
    return "\n".join(lines)


def main() -> int:
    info = gather()
    if "--json" in sys.argv[1:]:
        print(json.dumps(info, indent=2))
    else:
        print(_render(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
