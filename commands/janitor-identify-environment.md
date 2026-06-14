---
description: Report the full runtime environment of this Claude Code session — the hosting terminal/program (iTerm, tmux, an ai-maestro agent, …) detected by PROCESS ANCESTRY, the launch process chain, the tmux session/pane id, the OS + version, the filesystem type, and whether it is running inside a container / dev-box / sandbox (and which one). Read-only. Trigger with /janitor-identify-environment or by asking where this session is running.
---

# /janitor-identify-environment

Run the backing script and surface its output verbatim to the user:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/identify_environment.py"
```

It reports, for THIS session:

- **Terminal / program** — the hosting terminal identified by walking the
  **process ancestry** to the launching emulator (NOT fragile `$TERM_PROGRAM`
  inference): `iterm`, `tmux`, `apple-terminal`, `kitty`, `wezterm`, `vscode`, …;
  plus whether it is running **inside an ai-maestro agent**.
- **Launch process chain** — the nearest ancestor processes up to the terminal.
- **tmux** — the session name + pane id + window, when inside tmux.
- **OS** — system, friendly version (e.g. `macOS 26.5.1 (build …)` /
  `Ubuntu 24.04`), and CPU arch.
- **Filesystem** — the filesystem type backing the project directory (`apfs`,
  `ext4`, …).
- **Container / dev-box / sandbox** — Docker, Podman, Kubernetes, WSL, GitHub
  Codespaces, a VS Code dev container, Gitpod, the macOS app sandbox, or
  `none detected (bare host)`.

Add `--json` to the command for a machine-readable object instead of the
formatted report. The script is pure observation — it changes nothing.
