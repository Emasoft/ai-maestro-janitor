#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""MCP config drift — Python port of mcp-config-drift.sh.

Passively audits the project's MCP server configuration for the three
classes of drift that have caused real 'the MCP server silently doesn't
connect' incidents:

  1. JSON parse errors. A trailing comma or stray bracket in `.mcp.json`
     makes Claude Code skip the entire file with no error visible to the
     user. We catch the parse error explicitly.

  2. Tracking ambiguity on `.mcp.json`. Per the project's git-tracking
     ↔ scope convention, an MCP config should be EITHER git-tracked
     (project scope: team-shared) OR explicitly gitignored (local
     scope: personal). Anything else is ambiguous and a common source
     of 'I configured the server but my teammate's checkout doesn't
     have it' or 'my personal API token leaked into the repo'.

  3. Per-server config sanity:
       a. NO transport — neither `command` nor `url` is set.
       b. Unset env var references — `command`, `args`, `env` values,
          `headers` values, and `url` are scanned for `$VAR` / `${VAR}`
          tokens. Any token whose corresponding env var is unset in
          THIS shell is surfaced.

MCP scope storage layout (per https://code.claude.com/docs/en/mcp.md):

  ┌──────────┬──────────────────────────────────────────┬────────────┐
  │ scope    │ file & json path                         │ inspected? │
  ├──────────┼──────────────────────────────────────────┼────────────┤
  │ project  │ <root>/.mcp.json    .mcpServers          │ YES        │
  │ local    │ ~/.claude.json      .projects[<root>]    │ YES (ours  │
  │          │                       .mcpServers        │  only)     │
  │ user     │ ~/.claude.json      .mcpServers          │ NEVER      │
  └──────────┴──────────────────────────────────────────┴────────────┘
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import git_utils  # noqa: E402
import state  # noqa: E402


# Match `${VAR}` or `$VAR`. Var names are uppercase + digits + underscore,
# starting with a letter or underscore. Lowercase / numeric-prefixed names
# are skipped (they're often coincidental matches like `$1` in sample
# commands).
_ENV_REF_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)")


def _emit(seen: Path, key: str, msg: str) -> None:
    line = dedupe.emit_once(seen, key, msg)
    if line is not None:
        print(line)


def _extract_env_refs(searchable: str) -> list[str]:
    """Return sorted unique env-var names referenced in `searchable`."""
    seen: set[str] = set()
    for m in _ENV_REF_RE.finditer(searchable):
        name = m.group(1) or m.group(2)
        if name:
            seen.add(name)
    return sorted(seen)


def _flatten_for_env_search(config: Any) -> str:
    """Concatenate the values where env-var refs can appear.

    We intentionally only look at .values of `env` and `headers` — the
    keys themselves are not env vars to resolve.
    """
    if not isinstance(config, dict):
        return ""
    parts: list[str] = []
    cmd = config.get("command")
    if isinstance(cmd, str):
        parts.append(cmd)
    args = config.get("args")
    if isinstance(args, list):
        for a in args:
            if isinstance(a, str):
                parts.append(a)
    env = config.get("env")
    if isinstance(env, dict):
        for v in env.values():
            if isinstance(v, str):
                parts.append(v)
    headers = config.get("headers")
    if isinstance(headers, dict):
        for v in headers.values():
            if isinstance(v, str):
                parts.append(v)
    url = config.get("url")
    if isinstance(url, str):
        parts.append(url)
    return " ".join(parts)


def _check_server(seen: Path, source_label: str, name: str, config: Any) -> None:
    safe_label = state.sanitize_for_drift_line(source_label)
    safe_name = state.sanitize_for_drift_line(name)

    if not isinstance(config, dict):
        return
    cmd = str(config.get("command", "") or "")
    url = str(config.get("url", "") or "")

    if not cmd and not url:
        _emit(
            seen,
            f"no-transport@{source_label}@{name}",
            f"[mcp-config-drift] {safe_label} server '{safe_name}' declares neither 'command' (stdio) "
            f"nor 'url' (http/sse/ws). Claude Code cannot start it.",
        )
        return

    refs = _extract_env_refs(_flatten_for_env_search(config))
    for ref in refs:
        if not os.environ.get(ref):
            _emit(
                seen,
                f"unset-env@{source_label}@{name}@{ref}",
                f"[mcp-config-drift] {safe_label} server '{safe_name}' references env var ${ref} "
                f"but it is not set in the current shell. Set it in your shell startup (or .env), "
                f"then restart Claude Code.",
            )


def _iterate_servers(seen: Path, source_label: str, servers: Any) -> None:
    if not isinstance(servers, dict):
        return
    for name, config in servers.items():
        if not isinstance(name, str) or not name:
            continue
        if config is None:
            continue
        _check_server(seen, source_label, name, config)


def _check_mcp_json_tracking(seen: Path, rel: str) -> None:
    """`.mcp.json` should be either tracked OR gitignored — never ambiguous."""
    status = git_utils.scope_tracking_status(rel)
    if status != git_utils.AMBIGUOUS:
        return
    _emit(
        seen,
        f"tracking-ambig@{rel}",
        f"[mcp-config-drift] {rel} exists but is neither git-tracked nor gitignored — its scope is "
        f"ambiguous. Decide: 'git add {rel}' to share with the team (project scope), or add '/{rel}' "
        f"to .gitignore for personal MCP config (won't leak personal tokens).",
    )


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "mcp-config-drift-seen.txt"
    root = state.project_root()

    # 1. Project-root .mcp.json
    mcp_json = root / ".mcp.json"
    if mcp_json.is_file():
        try:
            with mcp_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
            _iterate_servers(seen, str(mcp_json), data.get("mcpServers"))
        except json.JSONDecodeError:
            _emit(
                seen,
                "invalid-json@.mcp.json",
                "[mcp-config-drift] .mcp.json is invalid JSON — Claude Code silently skips files it cannot "
                "parse. Run 'jq . .mcp.json' locally to find the parse error.",
            )
        except OSError as exc:
            state.log_line("mcp-config-drift", f".mcp.json read failed: {exc}")
        _check_mcp_json_tracking(seen, ".mcp.json")

    # 2. Local-scope MCP servers in ~/.claude.json under .projects.<root>
    #
    # `~/.claude.json` holds Claude Code's user-state (incl. apiKey and
    # OAuth tokens — sensitive). We read ONLY the local-scope subtree for
    # this project, never the top-level `.mcpServers` (user-scope) and
    # never any other top-level field. To avoid leaking the absolute
    # project path through error messages we use a stable label
    # ('local-scope MCP') rather than echoing the home file path.
    home_json = Path.home() / ".claude.json"
    if home_json.is_file():
        try:
            with home_json.open("r", encoding="utf-8") as f:
                home_data = json.load(f)
        except json.JSONDecodeError:
            # Don't try to fix this — ~/.claude.json is Claude Code's own
            # state file and editing it manually is risky. Just surface
            # the condition.
            _emit(
                seen,
                "invalid-json@~/.claude.json",
                "[mcp-config-drift] ~/.claude.json is invalid JSON. This is Claude Code's own user-state "
                "file — do NOT edit it manually. Restart Claude Code or restore from a recent backup. "
                "(Local-scope MCP audit skipped this fire.)",
            )
            return 0
        except OSError as exc:
            state.log_line("mcp-config-drift", f"~/.claude.json read failed: {exc}")
            return 0

        projects = home_data.get("projects")
        if isinstance(projects, dict):
            project_entry = projects.get(str(root))
            if isinstance(project_entry, dict):
                local_servers = project_entry.get("mcpServers")
                if isinstance(local_servers, dict) and local_servers:
                    _iterate_servers(seen, "local-scope (~/.claude.json projects.<this>)", local_servers)

    state.rotate_log_if_big("mcp-config-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
