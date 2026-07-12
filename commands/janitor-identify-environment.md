---
description: Report the FULL runtime environment of this Claude Code session — terminal, OS + kernel + WSL, filesystem, container/VM/sandbox, CI, editor/IDE + Claude Code surface (CLI vs desktop) + subscription auth mode, interactive-vs-headless/background-agent + linked-git-worktree, network (proxy/VPN/Tailscale/gateway/NAT/DNS/firewall + listening services), python env, AWS/Azure/GCP, user, PATH, compilers/runtimes/package-managers/dev-tools (incl. tldr/distill), MCP servers, the git repo + GitHub slug/branches/hooks/rulesets, wikimem sizes, and the installed/enabled plugins+hooks+staleness. Secret-safe, fail-open; writes the full detail to disk as JSON and returns a compact digest. Trigger with /janitor-identify-environment or by asking where this session is running.
---

# /janitor-identify-environment

Run the backing script and surface its COMPACT digest to the user (the full detail
is written to disk as JSON — relay the digest + the saved-path line, do NOT paste
the whole JSON into the conversation):

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/identify_environment.py" --online
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
  **dev tooling** (with versions) — including the token-economy tools **tldr-code**,
  **distill**, **fastedit**, **memgrep**, **lean-ctx** — plus **python**
  venv/conda/pyenv/uv.
- **MCP servers** — the servers configured for this session (name + transport +
  scheme://host), with any token/env value **stripped**.
- **Git repo** — remotes + **GitHub slug**, current branch, all **branches** (with
  last-commit dates + descriptions), repo last-commit datetime, and the **active git
  hooks** (honoring `core.hooksPath`).
- **GitHub** (`--online`) — repo description / default branch / visibility, and the
  **branch-protection rulesets** (name, target, enforcement, branches, rule types).
- **Wikimem** — note counts for the LOCAL / PROJECT / USER memory scopes.
- **Plugins** — installed vs enabled counts, configured **hook events**, the
  **janitor's own version** + **staleness** (`--online`), and the **last
  marketplace/version upgrade** timestamps.
- **Claude auth** — API-key vs subscription (OAuth) mode (tier needs a live probe).
- **gh CLI** — the authenticated GitHub username + token scopes, and whether gh is
  working (offline: from `hosts.yml`; `--online` confirms live).
- **GitHub Actions** — installed workflows + the third-party actions they use,
  **whether a Claude Code action is present**, and the CI target **platforms**.
- **Releases** (`--online`) — GitHub releases (latest ones) and, for the project's
  package name, **PyPI / npm (also bun) / crates.io** presence + latest version.
- **Homebrew tap** — if the repo is a tap (Formula/ dir or `homebrew-*` name), flags
  that **Homebrew 6.0.0+ requires consumers to `brew trust`** it (third-party taps are
  no longer trusted by default — [Tap Trust](https://docs.brew.sh/Tap-Trust)).
- **Fork / collaboration** — whether the repo is a fork and its **upstream** (from
  `gh` under `--online`, or a local `upstream` remote).
- **Repo topology** — single-project vs mono-repo, single-git vs multi-git
  (submodules / nested repos / symlinked repos), and single vs mixed language.
- **User / PATH / launch process chain**.

Flags:
- `--online` — enable the GitHub (`gh`) probes: branch-protection rulesets, repo
  metadata, and the janitor's latest-release staleness check. **OFF by default** so
  a plain run makes no network call.
- `--json` — print the raw machine-readable object to stdout (does NOT write a file).
- `--fast` — skip the two slowest LOCAL probes (per-tool version strings + the
  listening-ports scan) for a quicker run.

By default (no `--json`) the script **writes the full report to
`<repo>/reports/identify-environment/<timestamp>-env.json`** and prints only the
compact digest plus that path — so the caller's context holds the summary, not the
whole object.

**Safety.** Pure observation — it changes nothing (aside from writing its own JSON
report), makes **no network call except the opt-in `--online` GitHub probes**, never
emits a secret VALUE (anything key/token/secret/password/credential is reported as
presence only; proxy URLs and MCP endpoints are credential-stripped; cloud creds are
presence-only; no `-w` keychain read), and **fails open** (a probe that is
unavailable or blocked degrades to "unknown", never a crash).
