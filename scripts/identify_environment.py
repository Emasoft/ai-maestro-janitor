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
import re
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


def _gather_git_repo() -> dict:
    """Local git facts: worktree flags (for execution context), remotes + GitHub
    slug, branches (+ descriptions + last-commit dates), current branch, repo
    last-commit datetime, and the ACTIVE git hooks (honoring core.hooksPath). Reads
    `.git/config` as a FILE (the `git config` verb is not needed), and uses only
    read-only git verbs (`rev-parse`/`for-each-ref`/`log`). Fail-open throughout."""
    inside = _out(["git", "rev-parse", "--is-inside-work-tree"]) == "true"
    if not inside:
        return {"inside": False, "git_dir": "", "common": ""}
    git_dir = _out(["git", "rev-parse", "--absolute-git-dir"])
    common = _out(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    top = _out(["git", "rev-parse", "--show-toplevel"])
    cfg_text = ""
    if common:
        cfg_path = Path(common) / "config"
        try:
            cfg_text = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else ""
        except OSError:
            cfg_text = ""
    cfg = env_detect.parse_git_config(cfg_text)
    # Mask any embedded credential in a remote URL (`https://user:secret@host/…`) BEFORE it is
    # stored, rendered, or written to the JSON report. The module's #1 invariant is to never
    # emit a secret VALUE, and a git remote URL is exactly as credential-bearing as a proxy URL
    # (which detect_proxies already masks). `github_slug` still resolves the owner/repo from the
    # masked form, so downstream slug/fork detection is unaffected.
    remotes = {name: env_detect.mask_proxy(url) for name, url in cfg["remotes"].items()}
    slug = None
    for name in ("origin", *remotes):
        s = env_detect.github_slug(remotes.get(name, ""))
        if s:
            slug = s
            break
    branches = env_detect.parse_branches(_out([
        "git", "for-each-ref", "refs/heads",
        "--format=%(refname:short)|%(committerdate:iso8601)|%(upstream:short)|%(subject)",
    ]))
    for b in branches:
        d = cfg["branch_descriptions"].get(b["name"])
        if d:
            b["description"] = d
    # Resolve the hooks dir: core.hooksPath (relative to repo top or absolute), else <git-dir>/hooks.
    hooks_dir = ""
    if cfg["hooks_path"]:
        hp = Path(cfg["hooks_path"])
        hooks_dir = str(hp if hp.is_absolute() else (Path(top) / hp)) if top else str(hp)
    elif git_dir:
        hooks_dir = str(Path(git_dir) / "hooks")
    try:
        entries = os.listdir(hooks_dir) if hooks_dir and os.path.isdir(hooks_dir) else []
    except OSError:
        entries = []
    hooks = env_detect.active_git_hooks(entries, lambda n: os.access(os.path.join(hooks_dir, n), os.X_OK))
    return {
        "inside": True, "git_dir": git_dir, "common": common, "top": top,
        "remotes": remotes, "slug": slug,
        "current_branch": _out(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "branch_count": len(branches), "branches": branches,
        "last_commit": _out(["git", "log", "-1", "--format=%cI"]),
        "hooks_path": cfg["hooks_path"], "hooks": hooks,
    }


def _gather_github(slug: str | None, *, online: bool) -> dict:
    """GitHub repo metadata + branch-protection rulesets via `gh` (network). Runs
    ONLY under `--online` (the default keeps the no-network invariant). Bounded to
    10 rulesets; fail-open (a denied/absent `gh` yields an empty/annotated dict)."""
    if not (online and slug):
        return {}
    if not _which("gh"):
        return {"slug": slug, "note": "gh not installed — GitHub details skipped"}
    out: dict = {"slug": slug}
    repo = _out(["gh", "api", f"repos/{slug}", "--jq",
                 "{description,default_branch,visibility,pushed_at,fork,archived}"], timeout=12.0)
    if repo:
        try:
            out["repo"] = json.loads(repo)
        except ValueError:
            pass
    rulesets_raw = _out(["gh", "api", f"repos/{slug}/rulesets"], timeout=12.0)
    rulesets = []
    if rulesets_raw:
        try:
            rulesets = json.loads(rulesets_raw)
        except ValueError:
            rulesets = []
    expanded = []
    for rs in (rulesets if isinstance(rulesets, list) else [])[:10]:
        rid = rs.get("id") if isinstance(rs, dict) else None
        det = _out(["gh", "api", f"repos/{slug}/rulesets/{rid}"], timeout=8.0) if rid else ""
        try:
            expanded.append(json.loads(det) if det else rs)
        except ValueError:
            expanded.append(rs)
    out["rulesets"] = env_detect.summarize_rulesets(expanded)
    return out


def _dir_note_stats(root: str) -> dict:
    notes, total = 0, 0
    try:
        for dp, _, fns in os.walk(root):
            for fn in fns:
                if fn.endswith(".md"):
                    notes += 1
                    try:
                        total += os.path.getsize(os.path.join(dp, fn))
                    except OSError:
                        pass
    except OSError:
        pass
    return {"notes": notes, "bytes": total}


def _gather_wikimem(top: str) -> dict:
    """Per-scope wikimem size (LOCAL / PROJECT / USER): note count + bytes. Reads
    only; approximate note count is every `*.md` under the scope root."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project))
    roots = {
        "local": os.path.join(home, ".claude", "projects", slug, "memory"),
        "project": os.path.join(top or project, ".claude", "project", "memory"),
        "user": os.path.join(home, ".claude", "plugins", "data",
                             "ai-maestro-janitor-ai-maestro-plugins", "memory"),
    }
    return {scope: {**_dir_note_stats(p), "path": p}
            for scope, p in roots.items() if os.path.isdir(p)}


def _janitor_installed_version(home: str) -> str:
    base = Path(home) / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor"
    try:
        vers = [d.name for d in base.iterdir() if d.is_dir() and re.match(r"^\d+\.\d+", d.name)]
    except OSError:
        return ""
    return sorted(vers, key=env_detect._semver_tuple)[-1] if vers else ""


def _gather_plugins(*, online: bool) -> dict:
    """Installed/enabled plugins, configured hook events, and the janitor's own
    version + last marketplace/version upgrade timestamps (from its global-state).
    Reads config files only; `--online` adds the latest-release staleness check."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    settings: dict = {}
    sp = Path(home) / ".claude" / "settings.json"
    try:
        if sp.is_file():
            settings = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    out: dict = {}
    ep = settings.get("enabledPlugins")
    if isinstance(ep, dict):
        out["plugins"] = env_detect.parse_enabled_plugins(ep)
    hooks = settings.get("hooks")
    if isinstance(hooks, dict):
        out["hook_events"] = sorted(hooks.keys())
    # Standalone (non-plugin) skills = a dir under ~/.claude/skills/ carrying a SKILL.md.
    # Plugin-provided skills ride their plugin's version, so their inventory + staleness
    # is the plugin section above; this counts only the user's own standalone skills.
    skills_dir = Path(home) / ".claude" / "skills"
    try:
        out["standalone_skills"] = sum(
            1 for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()
        ) if skills_dir.is_dir() else 0
    except OSError:
        out["standalone_skills"] = 0
    gs = Path(home) / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins" / "global-state"

    def _ts(name: str):
        p = gs / f"{name}.last-run.ts"
        try:
            return int(p.read_text(encoding="utf-8").strip()) if p.is_file() else None
        except (OSError, ValueError):
            return None

    installed = _janitor_installed_version(home)
    janitor: dict = {
        "installed_version": installed or None,
        "marketplace_refresh_ts": _ts("marketplace-refresh"),
        "version_update_ts": _ts("version-update"),
        "user_plugins_update_ts": _ts("user-plugins-update"),
    }
    if online:
        latest = _out(["gh", "api", "repos/Emasoft/ai-maestro-janitor/releases/latest",
                       "--jq", ".tag_name"], timeout=12.0).lstrip("v")
        janitor["latest_version"] = latest or None
        janitor["staleness"] = env_detect.version_stale(installed, latest)
    out["janitor"] = janitor
    return out


def _save_json(info: dict) -> str:
    """Write the FULL report as JSON to `<main-repo>/reports/identify-environment/
    <ts±tz>-env.json` and return the path, or '' on any failure (fail-open — a
    blocked/unavailable write must not sink the run)."""
    main_root = ""
    wt = _out(["git", "worktree", "list"])
    if wt:
        main_root = wt.splitlines()[0].split()[0]
    if not main_root:
        main_root = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    try:
        d = Path(main_root) / "reports" / "identify-environment"
        d.mkdir(parents=True, exist_ok=True)
        ts = _out(["date", "+%Y%m%d_%H%M%S%z"]) or "env"
        path = d / f"{ts}-env.json"
        path.write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")
        return str(path)
    except (OSError, ValueError):
        return ""


def _read(path: str) -> str:
    try:
        p = Path(path)
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    except OSError:
        return ""


def _project_name(top: str) -> str | None:
    root = top or os.getcwd()
    return env_detect.project_name_from_manifest(
        pyproject=_read(os.path.join(root, "pyproject.toml")),
        package_json=_read(os.path.join(root, "package.json")),
        cargo=_read(os.path.join(root, "Cargo.toml")),
    )


def _gather_gh_auth(*, online: bool) -> dict:
    """The authenticated gh user (offline from hosts.yml; `--online` confirms live via
    `gh auth status` + `gh api user`). Never captures the token."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    cfg_user = env_detect.parse_active_gh_user(
        _read(os.path.join(home, ".config", "gh", "hosts.yml")))
    out: dict = {"installed": _which("gh"), "config_user": cfg_user or None,
                 "username": cfg_user or None}
    if online and _which("gh"):
        # `_out_any` (not a bare run_subprocess) keeps the fail-open invariant: it broad-catches
        # and returns stdout+stderr regardless of exit code — `gh auth status` prints to stderr
        # and a raise here (e.g. a blocked probe) must degrade the field, never sink the report.
        text = _out_any(["gh", "auth", "status"], timeout=10.0)
        parsed = env_detect.parse_gh_auth(text)
        live = _out(["gh", "api", "user", "--jq", ".login"], timeout=10.0)
        out.update({
            "working": bool(parsed["working"] or live),
            "username": live or parsed["username"] or cfg_user or None,
            "scopes": parsed["scopes"],
        })
    return out


def _gather_github_actions(top: str) -> dict:
    """Installed GitHub Actions workflows + the third-party actions they use +
    whether a Claude Code action is present + the CI target platforms (local read)."""
    wf_dir = Path(top or os.getcwd()) / ".github" / "workflows"
    texts, names = [], []
    try:
        files = sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))
    except OSError:
        files = []
    for f in files:
        t = _read(str(f))
        if t:
            texts.append(t)
            names.append(f.name)
    if not texts:
        return {}
    acts = env_detect.parse_workflow_actions(texts)
    return {"workflows": names, "actions": acts["actions"],
            "claude_action": acts["claude_action"],
            "platforms": env_detect.parse_workflow_platforms(texts)}


def _gather_releases(slug: str | None, *, online: bool) -> dict:
    if not (online and slug and _which("gh")):
        return {}
    raw = _out(["gh", "api", f"repos/{slug}/releases", "--jq",
                "[.[0:3][]|{tag:.tag_name,name:.name,published:.published_at,prerelease:.prerelease}]"],
               timeout=12.0)
    try:
        rel = json.loads(raw) if raw else []
    except ValueError:
        rel = []
    return {"has_releases": bool(rel), "latest": rel}


def _gather_registries(name: str | None, *, online: bool) -> dict:
    """Public package-registry presence for the project name: PyPI / npm (also
    covers bun) / crates.io. Network — `--online` only, bounded, fail-open."""
    if not (online and name):
        return {}
    out: dict = {}

    def _curl(url: str) -> str:
        return _out(["curl", "-fsSL", "--max-time", "10", url], timeout=12.0)

    pj = _curl(f"https://pypi.org/pypi/{name}/json")
    if pj:
        try:
            out["pypi"] = {"version": json.loads(pj).get("info", {}).get("version")}
        except ValueError:
            pass
    nj = _curl(f"https://registry.npmjs.org/{name}/latest")
    if nj:
        try:
            d = json.loads(nj)
            if d.get("version"):
                out["npm"] = {"version": d["version"], "note": "also the bun registry"}
        except ValueError:
            pass
    cj = _curl(f"https://crates.io/api/v1/crates/{name}")
    if cj:
        try:
            v = (json.loads(cj).get("crate") or {}).get("max_version")
            if v:
                out["cargo"] = {"version": v}
        except ValueError:
            pass
    return out


def _gather_repo_topology(top: str) -> dict:
    root = top or os.getcwd()
    manifests = {
        "pyproject.toml": "python", "setup.py": "python", "package.json": "javascript",
        "Cargo.toml": "rust", "go.mod": "go", "pom.xml": "java", "build.gradle": "java",
        "Gemfile": "ruby", "composer.json": "php", "pubspec.yaml": "dart",
    }
    langs, _found = [], []
    for m, lang in manifests.items():
        if os.path.exists(os.path.join(root, m)):
            _found.append(m)
            langs.append(lang)
    nested = 0
    _prune = {".venv", "node_modules", ".git", "target", "dist", "build",
              "_corpus_dev", ".trashcan", "reports", "reports_dev"}
    try:
        for dp, dirs, _ in os.walk(root):
            if ".git" in dirs and os.path.abspath(dp) != os.path.abspath(root):
                nested += 1
            dirs[:] = [d for d in dirs if d not in _prune]
    except OSError:
        pass
    has_sub = os.path.exists(os.path.join(root, ".gitmodules"))
    workspaces = []
    if "[tool.uv.workspace]" in _read(os.path.join(root, "pyproject.toml")):
        workspaces.append("uv-workspace")
    try:
        pkg = _read(os.path.join(root, "package.json"))
        if pkg and json.loads(pkg).get("workspaces"):
            workspaces.append("npm-workspaces")
    except ValueError:
        pass
    if re.search(r"(?m)^\[workspace\]", _read(os.path.join(root, "Cargo.toml"))):
        workspaces.append("cargo-workspace")
    repo_symlinks: list[str] = []
    try:
        for entry in os.scandir(root):
            if entry.is_symlink() and os.path.isdir(os.path.join(os.path.realpath(entry.path), ".git")):
                repo_symlinks.append(entry.name)
    except OSError:
        pass
    return env_detect.classify_repo_topology(
        languages=langs, nested_git_count=nested, has_submodules=has_sub,
        workspaces=workspaces, repo_symlinks=repo_symlinks)


def _gather_fork(slug: str | None, remotes: dict, *, online: bool) -> dict:
    upstream = remotes.get("upstream", "") if isinstance(remotes, dict) else ""
    gh_json: dict = {}
    if online and slug and _which("gh"):
        raw = _out(["gh", "repo", "view", slug, "--json", "isFork,parent"], timeout=12.0)
        try:
            gh_json = json.loads(raw) if raw else {}
        except ValueError:
            gh_json = {}
    return env_detect.summarize_fork(gh_json, upstream_remote=upstream)


def _gather_homebrew(slug: str | None, top: str, *, online: bool):
    root = top or os.getcwd()
    has_formula = os.path.isdir(os.path.join(root, "Formula"))
    repo_name = slug or os.path.basename(os.path.abspath(root))
    tapped = None
    if online and slug and _which("brew"):
        info = _out(["brew", "tap-info", slug, "--json"], timeout=20.0)
        if info:
            try:
                d = json.loads(info)
                tapped = bool(d and isinstance(d, list) and d[0].get("installed"))
            except ValueError:
                tapped = None
    return env_detect.homebrew_tap_status(repo_name, has_formula_dir=has_formula, tapped=tapped)


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


def gather(*, fast: bool = False, online: bool = False) -> dict:
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    git = _gather_git_repo()
    top = git.get("top", "") if git.get("inside") else ""  # already resolved inside _gather_git_repo
    tty = _session_tty()
    has_tty = bool(tty and tty not in ("??", "?"))
    fs = detect_filesystem(project)  # one `mount` probe, reused for both the type and the network flag

    compilers_present = [b for b, _ in env_detect.COMPILERS if _which(b)]
    runtimes_present = [b for b, _ in env_detect.RUNTIMES if _which(b)]
    versions: dict[str, str] = {} if fast else _tool_versions(compilers_present + runtimes_present)

    return {
        # --- original keys (back-compat contract) ---
        "terminal": detect_terminal(),
        "ancestry": detect_ancestry(),
        "tmux": detect_tmux(),
        "os": detect_os(),
        "filesystem": fs,
        "sandboxing": detect_sandboxing(),
        "project_dir": project,
        "cwd": os.getcwd(),
        # --- new sections ---
        "multiplexer": env_detect.detect_multiplexer(os.environ),
        "filesystem_network": env_detect.filesystem_is_network(fs),
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
        "subscription": env_detect.detect_subscription(os.environ),
        "network": _gather_network(),
        "listening": [] if fast else _gather_listening_ports(),
        "path": env_detect.detect_path(os.environ),
        "compilers": env_detect.detect_present(env_detect.COMPILERS, which=_which, versions=versions),
        "runtimes": env_detect.detect_present(env_detect.RUNTIMES, which=_which, versions=versions),
        "package_managers": env_detect.detect_present(env_detect.PACKAGE_MANAGERS, which=_which),
        "dev_tools": env_detect.detect_present(env_detect.DEV_TOOLS, which=_which),
        "mcp_servers": _gather_mcp_servers(),
        # --- wave-2 sections ---
        "git": ({k: git[k] for k in (
            "slug", "current_branch", "branch_count", "branches", "last_commit",
            "remotes", "hooks_path", "hooks") if k in git} if git.get("inside") else None),
        "github": _gather_github(git.get("slug"), online=online),
        "wikimem": _gather_wikimem(top),
        "plugins_env": _gather_plugins(online=online),
        # --- wave-3 sections ---
        "gh_auth": _gather_gh_auth(online=online),
        "github_actions": _gather_github_actions(top),
        "releases": _gather_releases(git.get("slug"), online=online),
        "registries": _gather_registries(_project_name(top), online=online),
        "repo_topology": _gather_repo_topology(top),
        "fork": _gather_fork(git.get("slug"), git.get("remotes", {}), online=online),
        "homebrew": _gather_homebrew(git.get("slug"), top, online=online),
    }


# --- rendering --------------------------------------------------------------


def _fmt_list(items: list[str], empty: str = "none") -> str:
    return ", ".join(items) if items else empty


def _ago(ts: object) -> str:
    """A compact 'Nm/Nh/Nd ago' for an epoch-seconds timestamp, or '?' if unparseable."""
    import time
    try:
        delta = int(time.time()) - int(ts)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return "?"
    if delta < 0:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


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

    # Claude auth / subscription
    sub = info.get("subscription", {})
    if sub and sub.get("auth_mode") != "unknown":
        lines.append(f"- **Claude auth:** {sub.get('auth_mode')}  ·  tier: {sub.get('tier')}")

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

    # Git / GitHub
    g = info.get("git")
    if g:
        gl = f"- **Git:** branch `{g.get('current_branch') or '?'}` · {g.get('branch_count', 0)} branches"
        if g.get("slug"):
            gl += f" · remote `{g['slug']}`"
        if g.get("last_commit"):
            gl += f" · last commit {g['last_commit']}"
        if g.get("hooks"):
            gl += f" · hooks: {g.get('hooks_path') or '.git/hooks'} ({len(g['hooks'])})"
        lines.append(gl)
    gh = info.get("github")
    if gh and gh.get("slug"):
        repo = gh.get("repo", {})
        rs = gh.get("rulesets", [])
        ghl = f"- **GitHub:** {gh['slug']}"
        if repo.get("default_branch"):
            ghl += f" · default `{repo['default_branch']}`"
        if repo.get("visibility"):
            ghl += f" · {repo['visibility']}"
        if rs:
            ghl += f" · rulesets: {len(rs)} ({', '.join(str(r.get('name')) for r in rs if r.get('name'))})"
        elif "rulesets" in gh:
            ghl += " · rulesets: none"
        lines.append(ghl)
        if gh.get("note"):
            lines.append(f"    - {gh['note']}")

    # Wikimem sizes
    wm = info.get("wikimem", {})
    if wm:
        parts = [f"{v['notes']} {scope}" for scope, v in wm.items()]
        lines.append(f"- **Wikimem:** {' / '.join(parts)} notes")

    # Plugins / janitor
    pl = info.get("plugins_env", {})
    if pl:
        plug = pl.get("plugins", {})
        jan = pl.get("janitor", {})
        pline = "- **Plugins:** "
        pline += (f"{plug.get('enabled', 0)} enabled / {plug.get('installed', 0)} installed"
                  if plug else "?")
        if pl.get("hook_events"):
            pline += f" · {len(pl['hook_events'])} hook events"
        if pl.get("standalone_skills"):
            pline += f" · {pl['standalone_skills']} standalone skills"
        if jan.get("installed_version"):
            stale = f" ({jan['staleness']})" if jan.get("staleness") else ""
            pline += f" · janitor v{jan['installed_version']}{stale}"
        if jan.get("marketplace_refresh_ts"):
            pline += f" · marketplace refreshed {_ago(jan['marketplace_refresh_ts'])}"
        lines.append(pline)

    # gh CLI auth
    gha = info.get("gh_auth", {})
    if gha and gha.get("username"):
        gline = f"- **gh CLI:** `{gha['username']}`"
        if gha.get("working") is not None:
            gline += "  ·  " + ("✓ working" if gha["working"] else "⚠ not verified")
        if gha.get("scopes"):
            gline += f" · scopes: {', '.join(gha['scopes'])}"
        lines.append(gline)
    elif gha and not gha.get("installed"):
        lines.append("- **gh CLI:** not installed")

    # GitHub Actions / workflows
    ga = info.get("github_actions", {})
    if ga:
        al = f"- **GitHub Actions:** {len(ga.get('workflows', []))} workflow(s)"
        al += " · **Claude action present**" if ga.get("claude_action") else " · no Claude action"
        if ga.get("platforms"):
            al += f" · platforms: {', '.join(ga['platforms'])}"
        lines.append(al)
        if ga.get("actions"):
            lines.append(f"    - actions: {', '.join(ga['actions'])}")

    # Releases + package registries
    rel = info.get("releases", {})
    if rel.get("has_releases"):
        latest = (rel.get("latest") or [{}])[0]
        lines.append(f"- **GitHub releases:** yes · latest `{latest.get('tag', '?')}` "
                     f"({latest.get('published') or '?'})")
    elif rel:
        lines.append("- **GitHub releases:** none")
    reg = info.get("registries", {})
    if reg:
        lines.append("- **Package registries:** "
                     + ", ".join(f"{k}={v.get('version')}" for k, v in reg.items()))

    # Fork / collaboration + Homebrew tap
    fork = info.get("fork", {})
    if fork.get("is_fork"):
        lines.append(f"- **Fork / collaboration:** yes → upstream `{fork.get('upstream') or '?'}`")
    hb = info.get("homebrew")
    if hb:
        tap_state = "trusted" if hb.get("trusted") else (
            "tapped locally" if hb.get("tapped_locally") else "trust unknown")
        lines.append(f"- **Homebrew tap:** yes ({tap_state}) — {hb['note']}")

    # Repo topology
    rt = info.get("repo_topology", {})
    if rt:
        tl = f"- **Repo topology:** {rt.get('structure', '?')} · {rt.get('git', '?')}"
        if rt.get("languages"):
            tl += f" · {', '.join(rt['languages'])}" + (" (mixed)" if rt.get("mixed_language") else "")
        if rt.get("workspaces"):
            tl += f" · workspaces: {', '.join(rt['workspaces'])}"
        if rt.get("nested_repos"):
            tl += f" · {rt['nested_repos']} nested repo(s)"
        if rt.get("repo_symlinks"):
            tl += f" · symlinked repos: {', '.join(rt['repo_symlinks'])}"
        lines.append(tl)

    # Project + ancestry
    lines.append(f"- **Project dir:** `{info['project_dir']}`")
    if info["ancestry"]:
        lines.append("- **Launch process chain (nearest first):**")
        for cmd in info["ancestry"]:
            lines.append(f"    - `{cmd}`")
    return "\n".join(lines)


def main() -> int:
    args = sys.argv[1:]
    info = gather(fast="--fast" in args, online="--online" in args)
    if "--json" in args:
        # Raw object to stdout (programmatic use) — no file written.
        print(json.dumps(info, indent=2, default=str))
        return 0
    # Default (token-economy): write the FULL detail to disk as JSON and print only
    # the compact digest + the path, so the caller's context holds the summary, not
    # the whole object (which carries every branch, ruleset, plugin, and port).
    path = _save_json(info)
    print(_render(info))
    if path:
        print(f"\n**Full JSON saved:** `{path}`")
    else:
        print("\n_(full JSON not saved — report dir unavailable; rerun with --json for the raw object)_")
    return 0


if __name__ == "__main__":
    sys.exit(main())
