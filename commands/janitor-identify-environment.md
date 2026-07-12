---
description: Report the FULL runtime environment of this Claude Code session — hosting terminal/program (by process ancestry), OS + kernel + WSL, filesystem, container/VM/sandbox, CI (GitHub Actions & friends), editor/IDE + Claude Code surface (CLI vs desktop), interactive-vs-headless/background-agent + linked-git-worktree, network (proxy/VPN/Tailscale/gateway/NAT/DNS/firewall/interfaces + listening services), python venv/conda/uv, AWS/Azure/GCP footprint, user, PATH, installed compilers/runtimes/package-managers/dev-tools, and configured MCP servers. Read-only, secret-safe, no network. Trigger with /janitor-identify-environment or by asking where this session is running.
---

# /janitor-identify-environment

Run the backing script and surface its output verbatim to the user:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/identify_environment.py"
```

It reports, for THIS session:

- **Terminal / program** — the hosting terminal by **process-ancestry** walk (NOT
  fragile `$TERM_PROGRAM` inference), reconciled with env signals: iTerm, tmux,
  Windows Terminal, Konsole, GNOME Terminal, WezTerm, kitty, Alacritty, Ghostty,
  Warp, VS Code terminal, …; plus **multiplexer** (tmux/screen/zellij/byobu) and
  whether it is **inside an ai-maestro agent**.
- **OS** — system, friendly version, kernel, CPU arch, Windows edition, and **WSL**
  (distro + WSL2) when present.
- **Filesystem** — the fstype backing the project dir (`apfs`, `ext4`, NTFS, …),
  flagged when it is a **network mount** (NFS/SMB/…).
- **Container / VM / sandbox** — Docker, Podman, Kubernetes, WSL, Codespaces, a VS
  Code dev container, Gitpod, flatpak/snap, firejail, the macOS app sandbox, and
  the `systemd-detect-virt` VM kind.
- **CI / remote execution** — GitHub Actions (with repo/workflow/run/event/runner),
  GitLab CI, CircleCI, Jenkins, Azure Pipelines, Buildkite, Vercel/Netlify, …
- **Editor / IDE + Claude Code** — VS Code / Cursor / Windsurf / Zed / JetBrains,
  and whether this is Claude Code **CLI vs desktop** + its entrypoint.
- **Execution context** — interactive TTY vs **headless / background agent**, and
  whether the cwd is a **LINKED git worktree** (vs the main checkout). The TTY is
  read from the session ancestor, so it is correct even though the probe subprocess
  itself has no controlling terminal.
- **Network** — proxies (credentials **masked**), VPN / Tailscale / WireGuard /
  WARP, default gateway, **behind-NAT** inference, DNS resolvers, firewall state,
  interfaces, and locally-**listening services** (exposed-off-host flagged).
- **Cloud** — AWS / Azure / GCP footprint (CLI, config dir, region/project, service
  context like Lambda/Cloud Run/App Service) — **presence only, never a credential**.
- **Toolchain** — installed **compilers**, **runtimes**, **package managers**, and
  **dev tooling** (with versions), plus **python** venv/conda/pyenv/uv.
- **MCP servers** — the servers configured for this session (name + transport +
  scheme://host), with any token/env value **stripped**.
- **User / PATH / launch process chain**.

Flags:
- `--json` — a machine-readable object instead of the formatted report.
- `--fast` — skip the two slowest LOCAL probes (per-tool version strings + the
  listening-ports scan) for a quicker run.

**Safety.** Pure observation — it changes nothing, makes **no network call**, never
emits a secret VALUE (anything key/token/secret/password/credential is reported as
presence only; proxy URLs and MCP endpoints are credential-stripped), and **fails
open** (a probe that is unavailable or blocked degrades to "unknown", never a crash).
