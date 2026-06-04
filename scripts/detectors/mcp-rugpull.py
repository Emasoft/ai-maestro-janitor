#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""MCP rug-pull detector — fingerprint-drift audit on installed MCP servers.

A "rug pull" in the MCP context is when a server the user already
trusts silently rewrites its behaviour — the npx-resolved package
bumps to a new (compromised) version, the URL switches to an attacker
host, or a local script gets overwritten with a different payload.
Disclosed attack reports: a malicious maintainer publishes a 1-line
update that changes a `bash`-tool's spec from "run any command" to
"also exfil $HOME/.ssh", and every IDE-bound agent silently picks it
up on the next session.

What we detect (v1 — static, no server start required):
  * The MCP server INVENTORY changed (new server added, server
    removed) since the last fire.
  * The server's TRANSPORT changed (command → url, stdio → http).
  * The server's ARG SHAPE / URL / HEADERS changed.
  * The locally-referenced server script's CONTENT hash changed.
  * The npx-resolved package@version pinned by the lockfile changed
    (catches `npm install -g foo` silently bumping major).

What we deliberately do NOT do in v1:
  * Start each MCP server and query its actual tool list /
    description / inputSchema. That requires a JSON-RPC handshake per
    server per fire, blows the heartbeat budget, and most rug-pulls
    are visible at the source-content layer this scan already covers.

Heartbeat invariants:
  * Self-scan guard — never scans the janitor's own tree.
  * Per-project state, atomic writes, read-only.
  * Silent on no-drift fires; cap output sample on drift fires.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "mcp-rugpull"

# A local server script can be sizeable (~100 KB python file). Hashing
# the whole content is fine — `sha256` over 100 KB is microseconds.
# But cap at 4 MB to refuse to hash a multi-GB venv'd binary by accident.
_LOCAL_SCRIPT_HASH_CAP = 4 * 1024 * 1024


def _hash_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _hash_file(path: Path) -> str:
    """Return short sha256 of file content, or '<unreadable>' on error."""
    try:
        if path.stat().st_size > _LOCAL_SCRIPT_HASH_CAP:
            return f"<too-large:{path.stat().st_size}>"
        data = path.read_bytes()
    except OSError:
        return "<unreadable>"
    return hashlib.sha256(data).hexdigest()[:16]


def _stable_json(obj: Any) -> str:
    """Canonical JSON for fingerprint stability — sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _resolve_local_files(cmd: str, args: list[str], project_root: Path) -> list[Path]:
    """Return any local file paths referenced in the server's command + args.

    Heuristic: any arg that looks like a path (contains a `/` or ends
    with a known source extension) and exists on disk under the project
    root or as an absolute path is included. We deliberately do NOT
    resolve files outside the project root — those are usually system
    tools (e.g. `/usr/bin/node`) and not interesting for rug-pull.
    """
    out: list[Path] = []
    suffixes = (".js", ".cjs", ".mjs", ".ts", ".py", ".sh", ".rb", ".lua")
    candidates = [cmd, *args]
    for c in candidates:
        if not isinstance(c, str) or not c:
            continue
        p = Path(c).expanduser()
        if not p.is_absolute():
            p = project_root / p
        try:
            resolved = p.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if not (resolved.suffix.lower() in suffixes or "/" in c):
            continue
        # Stay inside project root to avoid hashing system binaries.
        try:
            resolved.relative_to(project_root.resolve())
        except ValueError:
            continue
        out.append(resolved)
    return out


def _resolve_npx_version(args: list[str], project_root: Path) -> str | None:
    """If the server is launched via `npx <pkg>` or `npx -y <pkg>@<v>`,
    return the resolved package@version (or just `<pkg>` if no version
    is pinned and no lockfile resolution is available).

    For npx commands with no version pin we look at package-lock.json /
    pnpm-lock.yaml to find the resolved version — if absent, we report
    `<pkg>@unpinned` so the user sees the floating-target risk.
    """
    pkg_arg = None
    for a in args:
        if not isinstance(a, str) or not a:
            continue
        if a.startswith("-"):
            continue
        pkg_arg = a
        break
    if not pkg_arg:
        return None
    if "@" in pkg_arg[1:]:  # name has explicit version pin (skip leading @ for scoped)
        return pkg_arg
    # Look up in package-lock.json
    lock = project_root / "package-lock.json"
    if lock.is_file():
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            pkgs = data.get("packages")
            if isinstance(pkgs, dict):
                # Look for "node_modules/<pkg>" key (npm v7+ format).
                key = f"node_modules/{pkg_arg}"
                entry = pkgs.get(key)
                if isinstance(entry, dict):
                    v = entry.get("version")
                    if isinstance(v, str):
                        return f"{pkg_arg}@{v}"
    return f"{pkg_arg}@unpinned"


def _server_fingerprint(
    name: str, config: dict, project_root: Path,
) -> dict[str, Any]:
    """Compute a stable fingerprint dict for a single MCP server."""
    fp: dict[str, Any] = {"name": name}
    cmd = config.get("command")
    url = config.get("url")
    args = config.get("args") or []
    if not isinstance(args, list):
        args = []
    env = config.get("env") or {}
    headers = config.get("headers") or {}

    if isinstance(cmd, str) and cmd:
        fp["transport"] = "stdio"
        fp["command"] = cmd
        fp["args"] = args
        # If this is an npx invocation, snapshot the resolved version.
        cmd_basename = Path(cmd).name
        if cmd_basename in ("npx", "npx.cmd"):
            resolved = _resolve_npx_version(args, project_root)
            if resolved:
                fp["npx_resolved"] = resolved
        # Hash any local scripts referenced.
        local_files: dict[str, str] = {}
        for lf in _resolve_local_files(cmd, args, project_root):
            try:
                rel = str(lf.relative_to(project_root.resolve()))
            except ValueError:
                rel = str(lf)
            local_files[rel] = _hash_file(lf)
        if local_files:
            fp["local_file_hashes"] = local_files
    elif isinstance(url, str) and url:
        fp["transport"] = "http"
        fp["url"] = url
        # Header KEYS are public; values may contain $TOKENs and we
        # don't want to fingerprint a secret value. Hash the keys only.
        if isinstance(headers, dict):
            fp["header_keys"] = sorted(k for k in headers if isinstance(k, str))
    else:
        fp["transport"] = "<none>"

    # Env var NAMES (not values) — a rug-pull might add a new env var to
    # request a secret the user previously didn't grant.
    if isinstance(env, dict):
        fp["env_keys"] = sorted(k for k in env if isinstance(k, str))

    return fp


def _enumerate_servers(project_root: Path) -> dict[str, dict]:
    """Return {server_name: config_dict} from every config source."""
    out: dict[str, dict] = {}

    # Project-scope .mcp.json
    mcp_json = project_root / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                servers = data.get("mcpServers")
                if isinstance(servers, dict):
                    for n, c in servers.items():
                        if isinstance(n, str) and isinstance(c, dict):
                            out[f"project:{n}"] = c
        except (OSError, json.JSONDecodeError):
            pass

    # Local-scope ~/.claude.json projects.<this>.mcpServers
    home_json = Path.home() / ".claude.json"
    if home_json.is_file():
        try:
            data = json.loads(home_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            projects = data.get("projects")
            if isinstance(projects, dict):
                candidates = [str(project_root)]
                try:
                    resolved = str(project_root.resolve())
                    if resolved not in candidates:
                        candidates.append(resolved)
                except OSError:
                    pass
                for cand in candidates:
                    entry = projects.get(cand)
                    if isinstance(entry, dict):
                        servers = entry.get("mcpServers")
                        if isinstance(servers, dict):
                            for n, c in servers.items():
                                if isinstance(n, str) and isinstance(c, dict):
                                    out[f"local:{n}"] = c
                        break

    return out


def _diff_fingerprints(
    last: dict[str, str], current: dict[str, str],
) -> list[str]:
    """Diff two {server_name: fingerprint_hash} maps. Returns drift lines."""
    issues: list[str] = []
    last_keys = set(last)
    cur_keys = set(current)
    for added in sorted(cur_keys - last_keys):
        issues.append(f"new MCP server appeared: {added}")
    for removed in sorted(last_keys - cur_keys):
        issues.append(f"MCP server disappeared: {removed} (was: {last[removed]})")
    for shared in sorted(last_keys & cur_keys):
        if last[shared] != current[shared]:
            issues.append(
                f"MCP server '{shared}' fingerprint drifted ({last[shared]} → {current[shared]})"
            )
    return issues


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_MCP_RUGPULL_ENABLED", True,
    ):
        return 0
    # Hard self-scan guard.
    if state.is_self_scan_target():
        return 0

    state.init_state()
    project_root = state.project_root()

    servers = _enumerate_servers(project_root)

    # Build per-server fingerprint hash.
    current: dict[str, str] = {}
    full_fps: dict[str, dict] = {}
    for name, config in servers.items():
        fp = _server_fingerprint(name, config, project_root)
        full_fps[name] = fp
        current[name] = _hash_str(_stable_json(fp))

    fingerprint_file = state.state_dir() / "mcp-rugpull-fingerprints.json"
    last: dict[str, str] = {}
    if fingerprint_file.is_file():
        try:
            raw = json.loads(fingerprint_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                last = {
                    k: v for k, v in raw.items()
                    if isinstance(k, str) and isinstance(v, str)
                }
        except (OSError, json.JSONDecodeError):
            last = {}

    is_first_run = not fingerprint_file.is_file()
    issues = _diff_fingerprints(last, current) if not is_first_run else []

    # Always update the fingerprint snapshot — first run baselines, later
    # runs land the new state so a drift only fires once.
    state.atomic_write(fingerprint_file, _stable_json(current))

    if not issues:
        state.rotate_log_if_big(_NAME)
        return 0

    cap = 5
    sample = "\n".join(f"  - {state.sanitize_for_drift_line(s)}" for s in issues[:cap])
    if len(issues) > cap:
        sample += f"\n  - …and {len(issues) - cap} more"

    print(
        f"[mcp-rugpull] {len(issues)} MCP server fingerprint change(s) detected. "
        f"Review each — silent drift is the rug-pull attack shape. "
        f"Use /mcp to inspect the affected server(s) before next agent invocation.\n{sample}"
    )
    state.rotate_log_if_big(_NAME)
    # Surface full fingerprints to the detector log for the user to grep
    # if they want the actual before/after dump.
    state.log_line(_NAME, "fingerprints:" + _stable_json(full_fps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
