#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""supply-chain-fingerprints — heartbeat detector for high-signal supply-chain
fingerprints not covered by the shipped typosquat / slopsquat / OSV-MAL /
historical-cache / repo-trust / package-manager-policy / git-protocol-only /
worm-self-propagation / ai-context-poisoning stack.

Aggregates SIX deterministic sub-checks distilled from the deep-supply-chain
study (`reports/study-github-monitoring-deep/*deep-supply-chain*.md`). Each
sub-check is regex / AST / path-exists / YAML-INI-parse only — NO LLM, NO
network. The sub-checks complement (do not duplicate) existing detectors:

  1. `sc-rat-ioc-filesystem` (CRITICAL)
     Pure `Path.exists` against a curated list of 2026 RAT artifact paths
     (com.apple.act.mond, /tmp/ld.py, /etc/cron.d/.dotsync, etc.). Catches
     RATs already running even when the dropper source has been deleted.
     Source: supply-chain-guard SKILL.md D.2, Shai-Hulud / CanisterWorm /
     node-ipc / Megalodon incident IoCs. Zero FP — these paths are 100%
     malicious.

  2. `sc-bypass-via-vscode-tasks-and-claude-hooks` (CRITICAL)
     Regex scan of `.vscode/tasks.json`, `.claude/settings.json`, etc. for
     `curl …`-piped-to-`bash` / `wget -qO- …`-piped-to-`sh` / `bash`-of-a-`curl`-
     subshell shell-piped
     downloads. Complements `ai-context-poisoning` which watches *writes*
     to these files via PostToolUse — this fires when the payload is
     already committed in the file at scan time.
     Source: supply-chain-mitigation README §13/14, Mini Shai-Hulud.

  3. `sc-go-proxy-bypass` (CRITICAL)
     Scan workflows / Dockerfiles / Makefiles / shell-rc for env settings
     that disable Go supply-chain integrity:
       * `GOPROXY=direct` or `,direct` fallback
       * `GOSUMDB=off`
       * `GOFLAGS=…-insecure`
     Closes the Go ecosystem gap — BoltDB / shopsprint typosquats proved
     the module proxy is the last line of defence.
     Source: supply-chain-defense golang/GOENV.sh.

  4. `sc-decentralized-c2-marker` (MAJOR)
     Static-string scan of vendored package code for next-gen C2 endpoints
     that bypass classical IP/domain blocklists:
       * IPFS gateways (`ipfs.dweb.link`, `gateway.pinata.cloud/ipfs/Qm…`)
       * ICP canisters (`<52-char-hash>.ic0.app`)
       * Cloudflare Workers (`<subdomain>.workers.dev`)
       * Blockchain RPC endpoints (`eth-mainnet`, `polygon-mainnet`, …)
     Source: CanisterWorm (2026-03) + faster_log Rust crate (2025-09).

  5. `sc-strictDepBuilds-missing` (MAJOR)
     Check `pnpm-workspace.yaml` / `.npmrc` / `package.json#pnpm` for
     `strictDepBuilds: true` (yaml) or `strict-dep-builds=true` (ini).
     pnpm 10.3+ fails install when an unreviewed package wants to run a
     build script — the inverse of opt-in allowlist for postinstall.
     Distinct from `blockExoticSubdeps` (which the package-manager-policy
     detector already audits) — those are independent toggles.
     Source: depsguard README.

  6. `sc-pypi-setup-py-ast-imports` (MAJOR)
     AST-walk every `setup.py` for the exfil-cluster signature — `base64`
     + `requests/urllib/httpx` + `subprocess/socket/ctypes`. Two-or-more
     imports from the suspicious set is the structural fingerprint of a
     PyPI dropper; AST defeats string-concat obfuscation (`"im"+"port "`
     style) that regex-based scans miss.
     Source: macaron `SuspiciousSetupAnalyzer`.

Heartbeat invariants (per `~/.claude/CLAUDE.md` "agent-reports-location" +
existing detectors):
  * Self-scan guard — never scans the janitor's own tree.
  * Per-sub-check enable flag — opt-out via env vars.
  * Content-hash dedupe on the (file mtimes + RAT-path-presence) tuple.
  * Read-only — never edits a file or runs a subprocess.
  * Bounded output — at most one drift block, capped sample lines.
  * Silent on clean — no findings → no stdout.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import security_helpers as sec  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "supply-chain-fingerprints"

# Directories never worth scanning (vendored / cached / VCS internals).
_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "env", "vendor", "third_party",
    ".git", "target", "build", "dist", "__pycache__", ".pytest_cache",
    ".trashcan", "_dev",
}

# --- sub-check 1: RAT IoC filesystem -----------------------------------

# Confirmed-malicious filesystem paths from 2026 supply-chain incidents.
# Each path is 100% an IoC — appearance in $HOME or $PROGRAMDATA is
# enough on its own. The mapping is by sys.platform string.
_RAT_IOC_BY_PLATFORM: dict[str, list[str]] = {
    "darwin": [
        "/Library/Caches/com.apple.act.mond",
        "~/Library/LaunchAgents/com.apple.act.mond.plist",
        # node-ipc payload masquerade — non-Apple LaunchAgent name spoof.
        "~/Library/LaunchAgents/com.apple.softwareupdated.plist",
    ],
    "linux": [
        "/tmp/ld.py",
        "/tmp/.npm-cache/",
        "/etc/cron.d/.dotsync",           # CanisterWorm
        "/var/run/setup_bun.js",          # Shai-Hulud 2.0
        "/var/run/bun_environment.js",    # Shai-Hulud 2.0
    ],
    "win32": [
        # Windows paths use env-var expansion, not ~.
        # We expand %PROGRAMDATA% / %TEMP% / %APPDATA% via os.path.expandvars.
        "%PROGRAMDATA%\\wt.exe",
        "%TEMP%\\6202033.vbs",
        "%TEMP%\\6202033.ps1",
        "%APPDATA%\\Microsoft\\WindowsApps\\depsguard.exe",
    ],
}


def _check_rat_ioc_filesystem() -> list[str]:
    """Return drift lines for any RAT IoC path that EXISTS on this host.

    Pure `os.path.exists` — no network, no read, just FS lookup.
    """
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_SC_RAT_IOC_FILESYSTEM_ENABLED", True,
    ):
        return []
    platform = sys.platform
    candidates = _RAT_IOC_BY_PLATFORM.get(platform, [])
    if not candidates:
        return []
    issues: list[str] = []
    for raw in candidates:
        # `~` works on POSIX; `%VAR%` is expanded by expandvars on Windows.
        expanded = os.path.expandvars(os.path.expanduser(raw))
        try:
            if Path(expanded).exists():
                issues.append(
                    f"RAT-IoC: {raw} is present on disk — known artifact of a "
                    f"2026 supply-chain RAT (Shai-Hulud / CanisterWorm / "
                    f"node-ipc / Megalodon). Isolate the host immediately."
                )
        except OSError:
            # Permission denied / path too long — ignore, can't determine.
            continue
    return issues


# --- sub-check 2: piped-shell-download in config files -----------------

# Match `curl ... | bash`, `wget -qO- ... | sh`, `bash <(curl ...)`, etc.
# Designed to fire ONLY on the shell-pipe form — not a bare `curl` call,
# which has many legitimate uses inside config files (downloading docs
# / SDKs to a tmp dir, etc.).
_PIPED_SHELL_DOWNLOAD = re.compile(
    r"\b(?:curl|wget|fetch|invoke-webrequest|iwr)\b[^\n|;&]{1,200}?"
    r"\s*\|\s*(?:bash|sh|zsh|fish|powershell|pwsh|python\d*)\b"
    r"|"
    r"\b(?:bash|sh|zsh|fish)\s*<\s*\(\s*[^)]{0,200}?"
    r"\b(?:curl|wget|fetch)\b",
    re.IGNORECASE,
)

# Allowlist for well-known installer snippets that legitimately publish
# their own `curl | bash` line. The drift-line still fires; we just
# don't classify it as CRITICAL noise on these specific domains.
_KNOWN_INSTALLERS = re.compile(
    r"\b(?:sh\.rustup\.rs|raw\.githubusercontent\.com/nvm-sh|astral\.sh/uv/install|"
    r"get\.docker\.com|brew\.sh/install|raw\.githubusercontent\.com/Homebrew)\b",
    re.IGNORECASE,
)

# Config files where a piped-shell-download means persistence/RCE.
# Every one of these is read by an agent / IDE / hook system at startup.
_DANGEROUS_CONFIG_FILES = (
    ".vscode/tasks.json",
    ".vscode/launch.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".cursor/settings.json",
    ".devin/config.json",
    ".codex/config.json",
    ".windsurf/config.json",
)


def _check_piped_shell_in_configs(project_root: Path) -> list[str]:
    """Return drift lines for piped-shell-download patterns in agent
    configs / IDE task files."""
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_SC_PIPED_SHELL_DOWNLOAD_ENABLED", True,
    ):
        return []
    issues: list[str] = []
    for rel in _DANGEROUS_CONFIG_FILES:
        path = project_root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _PIPED_SHELL_DOWNLOAD.finditer(text):
            snippet = m.group()
            # Trim aggressively — drift lines should fit in one terminal row.
            short = snippet[:80].replace("\n", " ")
            severity = (
                "known-installer" if _KNOWN_INSTALLERS.search(snippet)
                else "CRITICAL"
            )
            issues.append(
                f"piped-shell-download [{severity}]: {rel} contains "
                f"{short!r} — config file is read by an agent/IDE at "
                f"startup; equivalent to npm postinstall RCE."
            )
    return issues


# --- sub-check 3: Go-proxy-bypass env settings ---------------------------

# Pattern note: the kill-tokens appear in two surfaces with different
# assignment syntax:
#   * shell + Dockerfile + Makefile + .envrc  → KEY=VALUE
#   * GitHub Actions workflows + YAML env:    → KEY: VALUE
# We accept BOTH `=` and `:` after the variable name, so a single
# detector covers all surfaces with one set of rules. The bare-word
# `direct` / `off` form is bounded by `\b` so e.g. `GOPROXY=direction`
# does NOT match.
_GO_KILL_PATTERNS = [
    # GOPROXY=direct (force VCS clone, bypass proxy.golang.org).
    re.compile(
        r"\bGOPROXY\s*[:=]\s*['\"]?\s*direct\b",
        re.IGNORECASE,
    ),
    # GOPROXY=foo,direct (direct fallback after proxy unreachable).
    # The `direct` fallback IS a real risk: the deep-supply-chain report
    # explicitly cites it as a kill-pattern — when the proxy is
    # unreachable (or attacker-blocked from the host), the VCS-direct
    # fallback bypasses checksum DB even when GOSUMDB is on.
    re.compile(
        r"\bGOPROXY\s*[:=]\s*['\"]?[^,'\"\n]+,\s*direct\b",
        re.IGNORECASE,
    ),
    # GOSUMDB=off (disable checksum verification).
    re.compile(
        r"\bGOSUMDB\s*[:=]\s*['\"]?\s*off\b",
        re.IGNORECASE,
    ),
    # GOFLAGS quoted, contains -insecure.
    re.compile(
        r"\bGOFLAGS\s*[:=]\s*['\"][^'\"]*-insecure",
        re.IGNORECASE,
    ),
    # GOFLAGS unquoted, with -insecure on the same line.
    re.compile(
        r"\bGOFLAGS\s*[:=][^'\"\n]*-insecure",
        re.IGNORECASE,
    ),
]

# Where to look for these env settings (project scope only — we never read
# user dotfiles outside the project root).
def _go_scan_targets(project_root: Path) -> list[Path]:
    """Files within project_root that may set Go env vars."""
    out: list[Path] = []
    # GitHub Actions workflows.
    workflows = project_root / ".github" / "workflows"
    if workflows.is_dir():
        for f in workflows.glob("*.yml"):
            out.append(f)
        for f in workflows.glob("*.yaml"):
            out.append(f)
    # Dockerfiles (any name starting with Dockerfile in any depth).
    for f in project_root.rglob("Dockerfile*"):
        if any(p in _SKIP_DIRS for p in f.parts):
            continue
        if f.is_file():
            out.append(f)
    # Makefiles.
    for name in ("Makefile", "makefile", "GNUmakefile"):
        f = project_root / name
        if f.is_file():
            out.append(f)
    # direnv envrc + shell rc files at project root only.
    for name in (".envrc", ".env", ".env.example"):
        f = project_root / name
        if f.is_file():
            out.append(f)
    return out


def _check_go_proxy_bypass(project_root: Path) -> list[str]:
    """Scan project-scoped config files for Go-integrity-disabling env
    vars. Returns CRITICAL drift lines per file match."""
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_SC_GO_PROXY_BYPASS_ENABLED", True,
    ):
        return []
    issues: list[str] = []
    for path in _go_scan_targets(project_root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in _GO_KILL_PATTERNS:
            m = pat.search(text)
            if m:
                rel = path.relative_to(project_root)
                # Find the line number for human readability.
                line_no = text.count("\n", 0, m.start()) + 1
                issues.append(
                    f"go-proxy-bypass: {rel}:{line_no} sets "
                    f"{m.group()[:60].strip()!r} — disables Go module "
                    f"proxy / checksum / TLS verification. NEVER correct "
                    f"in production. Source: BoltDB / shopsprint "
                    f"typosquat dwell time proved the proxy is the only "
                    f"line of defence."
                )
                # One match per file is enough for a drift line.
                break
    return issues


# --- sub-check 4: decentralized-C2 markers ------------------------------

_DECENTRALIZED_C2_PATTERNS = [
    # ICP canister hostnames are 27 or 52 chars from the canister-id alphabet
    # (mainnet = 27 chars in canonical form; legacy / test = up to 52 chars).
    # We allow both lengths and the 5-character canister-id suffix segments.
    re.compile(r"https?://[a-z0-9-]{20,63}\.ic0\.app", re.IGNORECASE),
    # IPFS gateways (dweb.link is Protocol Labs canonical; Pinata is the
    # commercial gateway most malware uses for resilience).
    re.compile(r"https?://[a-z0-9]+\.ipfs\.dweb\.link", re.IGNORECASE),
    re.compile(
        r"https?://gateway\.pinata\.cloud/ipfs/Qm[1-9A-HJ-NP-Za-km-z]{44}",
        re.IGNORECASE,
    ),
    # Bare ipfs:// URI with CIDv0 (Qm…) hash.
    re.compile(r"\bipfs://Qm[1-9A-HJ-NP-Za-km-z]{44}"),
    # Cloudflare Workers — `<sub>.workers.dev/`. Workers.dev domains are
    # almost never legitimate inside a vendored npm dep.
    re.compile(r"https?://[a-z0-9-]{1,63}\.workers\.dev/", re.IGNORECASE),
    # Public blockchain RPC endpoints used as malware C2.
    re.compile(
        r"https?://(?:eth-mainnet|polygon-mainnet|bsc-dataseed|arbitrum-mainnet)"
        r"\.[a-z0-9.-]+/",
        re.IGNORECASE,
    ),
]


def _scan_targets_for_c2(project_root: Path) -> list[Path]:
    """Files worth scanning for decentralized-C2 strings.

    Targets:
      * vendored JS in node_modules/* (but ONLY index/main entrypoints,
        not the entire tree — to keep the scan bounded)
      * top-level package.json / requirements.txt / Cargo.toml (rare but
        possible)
    """
    out: list[Path] = []
    nm = project_root / "node_modules"
    if nm.is_dir():
        # Scan each direct subdir's index file and dist entrypoint.
        # rglob over node_modules is intentionally bounded — we only
        # look at well-known entry filenames.
        for child in nm.iterdir():
            if not child.is_dir():
                continue
            # Skip scoped namespace dirs (`@scope/`); the real packages
            # live inside.
            if child.name.startswith("@"):
                for inner in child.iterdir():
                    if inner.is_dir():
                        out.extend(_c2_entrypoints(inner))
            else:
                out.extend(_c2_entrypoints(child))
    return out


def _c2_entrypoints(pkg_dir: Path) -> list[Path]:
    """Return the well-known entry files inside a single package dir."""
    out: list[Path] = []
    for candidate in ("index.js", "dist/index.js", "lib/index.js",
                      "src/index.js", "build/index.js"):
        f = pkg_dir / candidate
        if f.is_file():
            out.append(f)
    return out


def _check_decentralized_c2(project_root: Path) -> list[str]:
    """Scan vendored deps for next-gen C2 endpoint strings."""
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_SC_DECENTRALIZED_C2_ENABLED", True,
    ):
        return []
    issues: list[str] = []
    # Safe coercion: a non-numeric value (typo like "unlimited" / "2_000")
    # must not raise ValueError and crash the heartbeat on the cron hot path.
    cap = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_SC_C2_MAX_FILES"),
        default=2000,
        detector_name=_NAME,
        var_name="CLAUDE_PLUGIN_OPTION_SC_C2_MAX_FILES",
    )
    targets = _scan_targets_for_c2(project_root)
    if len(targets) > cap:
        targets = targets[:cap]
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in _DECENTRALIZED_C2_PATTERNS:
            m = pat.search(text)
            if m:
                rel = path.relative_to(project_root)
                marker = m.group()[:60]
                issues.append(
                    f"decentralized-C2 marker: {rel} contains "
                    f"{marker!r} — IPFS/ICP/Workers/blockchain-RPC "
                    f"endpoints bypass IP/domain blocklists. Classic "
                    f"shape of CanisterWorm (2026-03) + faster_log "
                    f"(2025-09) Rust crate. Audit the dep."
                )
                # One match per file is enough.
                break
    return issues


# --- sub-check 5: pnpm strictDepBuilds missing ---------------------------

def _parse_yaml_top_level(path: Path) -> dict[str, Any]:
    """Cheap top-level YAML extractor — no PyYAML dep. We only need
    `key: value` pairs at column 0 (pnpm-workspace.yaml shape)."""
    out: dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("#") or line.startswith(" ") or line.startswith("\t"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        # Cast obvious bool / int strings.
        low = value.lower()
        if low == "true":
            out[key] = True
        elif low == "false":
            out[key] = False
        elif value.isdigit():
            out[key] = int(value)
        else:
            out[key] = value
    return out


def _parse_npmrc(path: Path) -> dict[str, str]:
    """`.npmrc` is INI-flavoured `key=value`. Return raw string values."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip().lower()] = value.strip().strip("'").strip('"')
    return out


def _check_strict_dep_builds(project_root: Path) -> list[str]:
    """Verify `strictDepBuilds`/`strict-dep-builds` is set true when the
    project uses pnpm. Silent when the project has no pnpm signal."""
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_SC_STRICT_DEP_BUILDS_ENABLED", True,
    ):
        return []
    # Detect "uses pnpm" via any of: pnpm-lock.yaml, pnpm-workspace.yaml,
    # package.json#packageManager.startsWith("pnpm@"), or `.npmrc` with
    # any `pnpm-*` key.
    pnpm_lock = project_root / "pnpm-lock.yaml"
    pnpm_ws = project_root / "pnpm-workspace.yaml"
    npmrc = project_root / ".npmrc"
    pkg_json = project_root / "package.json"

    uses_pnpm = pnpm_lock.is_file() or pnpm_ws.is_file()
    if not uses_pnpm and pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            pm = data.get("packageManager", "")
            if isinstance(pm, str) and pm.startswith("pnpm@"):
                uses_pnpm = True
        except (OSError, json.JSONDecodeError):
            pass
    if not uses_pnpm and npmrc.is_file():
        # `.npmrc` with any `pnpm-*` key counts as a pnpm project.
        try:
            text = npmrc.read_text(encoding="utf-8", errors="replace")
            if re.search(r"^\s*pnpm-", text, re.MULTILINE):
                uses_pnpm = True
        except OSError:
            pass
    if not uses_pnpm:
        return []

    # Now check all the places strictDepBuilds COULD be set.
    is_set = False
    sources_checked: list[str] = []

    # 1. pnpm-workspace.yaml — key `strictDepBuilds:`
    if pnpm_ws.is_file():
        sources_checked.append("pnpm-workspace.yaml")
        y = _parse_yaml_top_level(pnpm_ws)
        if y.get("strictDepBuilds") is True:
            is_set = True

    # 2. .npmrc — key `strict-dep-builds=true`
    if not is_set and npmrc.is_file():
        sources_checked.append(".npmrc")
        ini = _parse_npmrc(npmrc)
        v = ini.get("strict-dep-builds", "").lower()
        if v == "true":
            is_set = True

    # 3. package.json#pnpm.strictDepBuilds
    if not is_set and pkg_json.is_file():
        sources_checked.append("package.json#pnpm")
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            pnpm_cfg = data.get("pnpm", {})
            if isinstance(pnpm_cfg, dict) and pnpm_cfg.get("strictDepBuilds") is True:
                is_set = True
        except (OSError, json.JSONDecodeError):
            pass

    if is_set:
        return []
    # Empty sources_checked means no place to put the setting found —
    # silently skip (uses_pnpm was inferred from pnpm-lock.yaml only).
    if not sources_checked:
        sources_checked = ["pnpm-workspace.yaml or .npmrc or package.json#pnpm"]

    return [
        "pnpm-strict-dep-builds-unset: project uses pnpm but "
        f"`strictDepBuilds=true` is not set in any of "
        f"{{{', '.join(sources_checked)}}}. pnpm 10.3+ fails install on "
        f"unreviewed build scripts when this is true — opt-in safety "
        f"belt. Distinct from `blockExoticSubdeps` (which controls "
        f"transitive resolution, not build-script execution)."
    ]


# --- sub-check 6: PyPI setup.py AST exfil-cluster ------------------------

# Suspicious imports — exfil duos / triples. We require 2+ to fire,
# which makes legitimate setup.py (uses `subprocess` for git tag lookup,
# or `urllib` for download_url logic) safe. This is the UNION of both
# clusters below; kept for docs and for future single-cluster rules.
_EXFIL_IMPORTS = frozenset({  # noqa: F841 - referenced as union of clusters below
    "base64", "binascii", "codecs",
    "requests", "urllib", "urllib2", "urllib3", "httpx", "aiohttp",
    "subprocess", "socket", "ctypes", "ctypes.cdll", "os.system",
    "platform", "pty",
})
# Eagerly reference so static analysers don't flag the union constant
# as dead code (it documents the full surface the two clusters cover).
assert _EXFIL_IMPORTS

# At least one from each cluster is the canonical dropper shape:
#   - obfuscation cluster   (base64 / binascii / codecs)
#   - network/exec cluster  (requests / urllib / subprocess / socket)
_CLUSTER_OBFUSCATION = frozenset({"base64", "binascii", "codecs"})
_CLUSTER_NETWORK_EXEC = frozenset({
    "requests", "urllib", "urllib2", "urllib3", "httpx", "aiohttp",
    "subprocess", "socket", "ctypes", "ctypes.cdll", "os.system",
})


def _collect_imports(tree: ast.AST) -> set[str]:
    """Return the set of import names referenced anywhere in tree."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base:
                out.add(base)
            for alias in node.names:
                if base:
                    out.add(f"{base}.{alias.name}")
                else:
                    out.add(alias.name)
    return out


def _check_setup_py_ast(project_root: Path) -> list[str]:
    """AST-walk each setup.py for the exfil-cluster signature.

    Fires only when AT LEAST TWO imports are in the suspicious set AND
    at least one is from each of the obfuscation + network-exec clusters
    — the structural fingerprint that distinguishes a dropper from a
    legitimate install script."""
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_SC_PYPI_SETUP_AST_ENABLED", True,
    ):
        return []
    issues: list[str] = []
    for path in project_root.rglob("setup.py"):
        if any(p in _SKIP_DIRS for p in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            # Unparseable — leave to a different detector.
            continue
        imports = _collect_imports(tree)
        # We require BOTH clusters AND at least 2 hits total. The
        # cluster test catches the obfuscation+network-exec shape that
        # is structurally novel (one-cluster legitimate setup.py exist;
        # both-cluster ones essentially never).
        obf_hit = imports & _CLUSTER_OBFUSCATION
        net_hit = imports & _CLUSTER_NETWORK_EXEC
        if obf_hit and net_hit:
            rel = path.relative_to(project_root)
            issues.append(
                f"pypi-setup-exfil-cluster: {rel} imports both "
                f"obfuscation ({sorted(obf_hit)[:3]}) AND "
                f"network/exec ({sorted(net_hit)[:3]}) modules at "
                f"install time — structural shape of PyPI droppers "
                f"(macaron SuspiciousSetupAnalyzer)."
            )
    return issues


# --- aggregator + heartbeat plumbing -----------------------------------

def _all_sub_checks(project_root: Path) -> dict[str, list[str]]:
    """Run every sub-check and return findings keyed by rule id.

    Each sub-check is independent — a failure (e.g. permission denied
    reading one file) inside a sub-check must NOT abort sibling checks.
    The per-sub-check enable flag is honoured INSIDE each function so
    the dispatcher stays oblivious to which flags are on.
    """
    return {
        "rat-ioc-filesystem": _check_rat_ioc_filesystem(),
        "piped-shell-in-configs": _check_piped_shell_in_configs(project_root),
        "go-proxy-bypass": _check_go_proxy_bypass(project_root),
        "decentralized-c2-marker": _check_decentralized_c2(project_root),
        "pnpm-strict-dep-builds": _check_strict_dep_builds(project_root),
        "pypi-setup-py-ast": _check_setup_py_ast(project_root),
    }


def _content_signature(project_root: Path) -> str:
    """Cheap dedupe — fingerprint of every file the detector reads.

    We include:
      * mtime+size of each `_DANGEROUS_CONFIG_FILES` if present
      * mtime+size of every workflow + Dockerfile + Makefile + .envrc
      * presence (existence-bit only) of every RAT IoC path
      * mtime+size of pnpm config files + each setup.py + each
        node_modules entrypoint we'd actually scan
    """
    h = hashlib.sha256()

    # Config files.
    for rel in _DANGEROUS_CONFIG_FILES:
        p = project_root / rel
        try:
            if p.is_file():
                st = p.stat()
                h.update(f"cfg|{rel}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            pass

    # Go-scan targets.
    for p in _go_scan_targets(project_root):
        try:
            st = p.stat()
            rel = p.relative_to(project_root)
            h.update(f"go|{rel}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            pass

    # RAT IoC presence (existence-bit only).
    platform = sys.platform
    for raw in _RAT_IOC_BY_PLATFORM.get(platform, []):
        expanded = os.path.expandvars(os.path.expanduser(raw))
        try:
            exists = "1" if Path(expanded).exists() else "0"
        except OSError:
            exists = "?"
        h.update(f"ioc|{raw}|{exists}\n".encode())

    # pnpm config files.
    for rel in ("pnpm-lock.yaml", "pnpm-workspace.yaml", ".npmrc",
                "package.json"):
        p = project_root / rel
        try:
            if p.is_file():
                st = p.stat()
                h.update(f"pnpm|{rel}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            pass

    # setup.py files.
    for p in sorted(project_root.rglob("setup.py")):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        try:
            st = p.stat()
            rel = p.relative_to(project_root)
            h.update(f"setup|{rel}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            pass

    return h.hexdigest()


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_SUPPLY_CHAIN_FINGERPRINTS_ENABLED", True,
    ):
        return 0
    if state.is_self_scan_target():
        return 0

    state.init_state()
    project_root = state.project_root()

    combined = _content_signature(project_root)
    last_hash_file = state.state_dir() / "supply-chain-fingerprints-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == combined:
                return 0  # nothing changed → silent
        except OSError:
            pass

    findings = _all_sub_checks(project_root)
    state.atomic_write(last_hash_file, combined)

    flat = [
        (rule, issue)
        for rule, issues in findings.items()
        for issue in issues
    ]
    if not flat:
        state.rotate_log_if_big(_NAME)
        return 0

    # Bounded output — at most 8 sample lines (≈ 1 per sub-check + a
    # margin). The full set is in the log file.
    cap = 8
    sample_lines = "\n".join(
        f"  - [{rule}] {state.sanitize_for_drift_line(issue)}"
        for rule, issue in flat[:cap]
    )
    if len(flat) > cap:
        sample_lines += f"\n  - …and {len(flat) - cap} more"

    rule_counts = ", ".join(
        f"{r}={len(issues)}" for r, issues in findings.items() if issues
    )
    hint = sec.security_agent_hint(
        "supply-chain",
        enabled=state.is_truthy_env(sec.SECURITY_AGENT_HINT_ENV, True),
    )
    print(
        f"[supply-chain-fingerprints] {len(flat)} finding(s) across "
        f"{sum(1 for v in findings.values() if v)} sub-check(s): "
        f"{rule_counts}. Each is a distinct, deterministic supply-chain "
        f"fingerprint not covered by the typosquat / OSV-MAL / "
        f"historical-cache stack.\n{sample_lines}"
        + (f"\n{hint}" if hint else "")
    )

    # Per-finding log so a user can pivot back through the full list
    # even after the drift line scrolls off.
    for rule, issue in flat:
        state.log_line(_NAME, f"[{rule}] {issue}")

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
