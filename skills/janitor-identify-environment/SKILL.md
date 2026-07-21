---
name: janitor-identify-environment
description: Report this Claude Code session's full runtime environment — terminal, OS, filesystem, sandboxing, CI, editor/IDE, network, cloud, python env, git/GitHub, MCP servers, wikimem, and installed plugins. Secret-safe and fail-open; writes full detail to disk as JSON and returns a compact digest. Use when the user asks where this session is running / what environment this is / which terminal, OS, container, or CI this is, or when you need to ground a decision in the actual runtime (network mount? headless? behind NAT? which tools installed?).
---

# Janitor identify-environment

## Overview

Pure observation of THIS session's runtime. It writes the full report to
`<repo>/reports/identify-environment/<timestamp>-env.json` and prints only a compact digest + that
path — so the caller's context holds the summary, not the whole object.

## When to use

- The user asks where/what this session is running (terminal, OS, container, CI, IDE).
- You need a runtime fact before acting: is the project on a network mount? headless/background?
  behind NAT? which compilers/runtimes/tools are installed? which MCP servers are configured?

## Instructions

Run the backing script and surface its COMPACT digest + the saved-path line (do NOT paste the whole
JSON into the conversation):

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/identify_environment.py" --online
```

Flags:
- `--online` — enable the GitHub (`gh`) probes: branch-protection rulesets, repo metadata, the
  janitor's latest-release staleness check. **OFF by default** so a plain run makes no network call.
- `--json` — print the raw machine-readable object to stdout (does NOT write a file).
- `--fast` — skip the two slowest LOCAL probes (per-tool version strings + the listening-ports scan).

It reports, for THIS session: **Terminal/program** (by process-ancestry walk, not fragile
`$TERM_PROGRAM`) + multiplexer + whether inside an ai-maestro agent; **OS** (system, version, kernel,
arch, WSL); **Filesystem** (fstype, network-mount flag); **Container/VM/sandbox** (Docker/Podman/K8s/
WSL/Codespaces/devcontainer/Gitpod/flatpak/snap/firejail/app-sandbox + `systemd-detect-virt`);
**CI/remote** (Actions/GitLab/CircleCI/Jenkins/Azure/Buildkite/Vercel/…); **Editor/IDE + Claude
Code** (VS Code/Cursor/Windsurf/Zed/JetBrains; CLI vs desktop); **Execution context** (interactive
TTY vs headless; linked worktree vs main checkout); **Network** (proxies credential-masked, VPN/
Tailscale/WireGuard/WARP, gateway, behind-NAT, DNS, firewall, interfaces, listening services);
**Cloud** (AWS/Azure/GCP presence only, never a credential); **Toolchain** (compilers/runtimes/
package-managers/dev-tools with versions, incl. tldr-code/distill/fastedit/memgrep/lean-ctx, + python
venv/conda/pyenv/uv); **MCP servers** (name + transport + scheme://host, token stripped); **Git repo**
(remotes + GitHub slug, branches with dates/descriptions, active git hooks honoring `core.hooksPath`);
**GitHub** `--online` (description/default-branch/visibility + branch-protection rulesets); **Wikimem**
(LOCAL/PROJECT/USER note counts); **Plugins** (installed vs enabled, hook events, the janitor's own
version + staleness, last upgrade timestamps); **Claude auth** (API-key vs OAuth); **gh CLI**
(username + scopes); **GitHub Actions** (workflows + third-party actions used, Claude Code action
present?, CI platforms); **Releases** `--online` (GitHub + PyPI/npm/crates.io presence + latest);
**Homebrew tap** (flags the `brew trust` requirement); **Fork/collaboration** (fork + upstream); **Repo
topology** (single vs mono-repo, single vs multi-git, single vs mixed language); **User / PATH /
launch chain**.

## Scope

Pure observation — it changes nothing (aside from writing its own JSON report), makes **no network
call except the opt-in `--online` GitHub probes**, never emits a secret VALUE (key/token/secret/
password/credential reported as presence only; proxy + MCP endpoints credential-stripped; cloud creds
presence-only; no `-w` keychain read), and **fails open** (an unavailable probe degrades to "unknown",
never a crash).
