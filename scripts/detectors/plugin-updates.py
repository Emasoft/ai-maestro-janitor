#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""Plugin-updates detector — Python port of plugin-updates.sh.

Auto-installs newer versions of plugins that Claude Code has installed
in `project` or `local` scope, restricted to the project this janitor
was armed in. Self-update of the janitor itself is handled by
version-update.py; this detector covers all OTHER plugins whose
configuration lives inside the project's own `.claude/` directory.

Claude Code's four configuration scopes (see docs/en/settings.md). The
scope of an installed plugin is determined by which settings file pins
it; the simple rule of thumb is 'git-tracked = project, gitignored = local':

  ┌──────────┬─────────────────────────────────────┬──────────────────────┐
  │ scope    │ file the install reference lives in │ git status           │
  ├──────────┼─────────────────────────────────────┼──────────────────────┤
  │ managed  │ /etc/claude-code/managed-...        │ admin-deployed       │
  │ project  │ <repo>/.claude/settings.json        │ TRACKED  → shared    │
  │ local    │ <repo>/.claude/settings.local.json  │ GITIGNORED → personal│
  │ user     │ ~/.claude/settings.json             │ outside any repo     │
  └──────────┴─────────────────────────────────────┴──────────────────────┘

DESIGN PRINCIPLE: the janitor is project-scoped infrastructure. It MUST
NEVER touch `user`-scope or `managed`-scope plugins. Even if the user
explicitly configures `plugin_auto_update_scopes` to include them, those
scopes are hard-filtered out below.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


SELF_PLUGIN_NAME = "ai-maestro-janitor"
_SEMVER_PREFIX_RE = re.compile(r"^\d+\.\d+\.\d+")
_UPDATED_FROM_RE = re.compile(r"updated from \S+ to (\S+?)[. ]?$", re.MULTILINE)


def _semver_tuple(s: str) -> tuple[int, ...]:
    """Sort key. Returns a (-1,) tuple for non-semver strings so they sort
    LOWEST — that's a safe direction (we'd never call them 'newer')."""
    parts = s.split(".")
    if len(parts) < 3:
        return (-1,)
    try:
        return tuple(int(p) for p in parts[:3])
    except ValueError:
        return (-1,)


def _is_truthy_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.lower() not in ("false", "0", "no", "off")


def _scope_allowed(scope: str) -> bool:
    """user/managed are NEVER allowed regardless of user config."""
    if scope in ("user", "managed"):
        return False
    allowed = os.environ.get("CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_SCOPES", "local,project")
    items = {s.strip() for s in allowed.split(",") if s.strip()}
    return scope in items


def _plugin_excluded(plugin_id: str) -> bool:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_EXCLUDE", "")
    if not raw.strip():
        return False
    items = {s.strip() for s in raw.split(",") if s.strip()}
    return plugin_id in items


def _find_marketplace_json(mp: str) -> Optional[Path]:
    """Locate marketplace.json. Newer marketplaces nest it under
    .claude-plugin/; older ones place it at the root."""
    root = Path.home() / ".claude" / "plugins" / "marketplaces" / mp
    nested = root / ".claude-plugin" / "marketplace.json"
    if nested.is_file():
        return nested
    flat = root / "marketplace.json"
    if flat.is_file():
        return flat
    return None


def _latest_version_in_marketplace(plugin_name: str, mp_json: Path) -> Optional[str]:
    """First matching plugins[].version, or None."""
    try:
        with mp_json.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return None
    for entry in plugins:
        if isinstance(entry, dict) and entry.get("name") == plugin_name:
            version = entry.get("version")
            if isinstance(version, str) and version and version.lower() != "null":
                return version
            return None
    return None


def _refresh_marketplace(mp: str, log_path: Path) -> None:
    state.log_line("plugin-updates", f"refreshing marketplace: {mp}")
    try:
        with log_path.open("a", encoding="utf-8") as logf:
            subprocess.run(
                ["claude", "plugin", "marketplace", "update", mp],
                stdout=logf, stderr=subprocess.STDOUT,
                timeout=60, check=False,
            )
    except subprocess.TimeoutExpired:
        state.log_line("plugin-updates", f"marketplace refresh timed out: {mp}")
    except OSError as exc:
        state.log_line("plugin-updates", f"marketplace refresh failed: {mp} ({exc})")


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "plugin-updates-seen.txt"
    log_path = state.log_dir() / "plugin-updates.log"

    if shutil.which("claude") is None:
        state.log_line("plugin-updates", "claude CLI not in PATH — skipping")
        return 0

    current_project = str(state.project_root())

    # 1. Enumerate installed plugins. timeout guards against a pathological
    #    CLI that hangs on a corrupted plugin index.
    try:
        proc = subprocess.run(
            ["claude", "plugin", "list", "--json"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        state.log_line("plugin-updates", "claude plugin list --json timed out — skipping")
        return 0
    if proc.returncode != 0 or not proc.stdout.strip():
        state.log_line("plugin-updates", "claude plugin list --json failed/empty — skipping")
        return 0

    try:
        plugin_list = json.loads(proc.stdout)
    except json.JSONDecodeError:
        state.log_line("plugin-updates", "claude plugin list --json returned non-JSON — skipping")
        return 0
    if not isinstance(plugin_list, list):
        state.log_line("plugin-updates", "claude plugin list --json returned non-array — skipping")
        return 0

    # 2. Build the CANDIDATE set first (apply every cheap filter — scope
    #    rejection, projectPath match, self-exclusion, user excludes)
    #    BEFORE touching any marketplace. Refreshing a marketplace is the
    #    expensive operation: each call takes a few seconds, and on a
    #    machine with many marketplaces it's the single biggest contributor
    #    to detector runtime. By computing candidates first we skip refresh
    #    for marketplaces whose installed plugins are all
    #    user/managed/other-project (the common case).
    candidates: list[tuple[str, str, str, str]] = []  # (id, version, scope, projectPath)
    for entry in plugin_list:
        if not isinstance(entry, dict):
            continue
        plugin_id = str(entry.get("id") or "")
        if "@" not in plugin_id:
            continue
        plugin_name = plugin_id.split("@", 1)[0]
        if plugin_name == SELF_PLUGIN_NAME:
            continue
        scope = str(entry.get("scope") or "")
        if scope not in ("project", "local"):
            continue
        project_path = str(entry.get("projectPath") or "")
        if project_path != current_project:
            continue
        version = str(entry.get("version") or "")
        candidates.append((plugin_id, version, scope, project_path))

    if not candidates:
        state.log_line("plugin-updates", f"no project/local-scope plugins for {current_project} — nothing to do")
        return 0

    # Extract unique marketplaces from the candidate set only, then refresh.
    marketplaces = sorted({plugin_id.split("@", 1)[1] for plugin_id, _, _, _ in candidates})
    for mp in marketplaces:
        _refresh_marketplace(mp, log_path)

    # 3. Walk each candidate. Dedup key is (id, scope, projectPath) — NOT
    #    just id — because `claude plugin update` requires `--scope` to
    #    update the right settings file.
    seen_keys: set[str] = set()
    updates_applied = 0
    update_errors = 0

    auto_enabled = _is_truthy_env("CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_ENABLED", True)

    for plugin_id, current_version, scope, project_path in candidates:
        plugin_name = plugin_id.split("@", 1)[0]
        marketplace = plugin_id.split("@", 1)[1]

        if not _scope_allowed(scope):
            continue
        if _plugin_excluded(plugin_id):
            continue

        dedup_key = f"{plugin_id}|{scope}|{project_path}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        mp_json = _find_marketplace_json(marketplace)
        if mp_json is None:
            state.log_line("plugin-updates", f"no marketplace.json for '{marketplace}' — skipping {plugin_id}")
            continue

        latest = _latest_version_in_marketplace(plugin_name, mp_json)
        if not latest:
            state.log_line("plugin-updates", f"no version field in marketplace.json for {plugin_id} — skipping")
            continue

        if latest == current_version:
            continue

        # Decide whether `latest` is genuinely newer. For semver-shaped
        # versions we compare tuples; for hash-style versions accept any
        # non-equal as a candidate.
        update_candidate = False
        if _SEMVER_PREFIX_RE.match(current_version) and _SEMVER_PREFIX_RE.match(latest):
            if _semver_tuple(latest) > _semver_tuple(current_version):
                update_candidate = True
        else:
            update_candidate = True

        if not update_candidate:
            continue

        if not auto_enabled:
            line = dedupe.emit_once(
                seen,
                f"available@{plugin_id}@{scope}@{latest}",
                f"[plugin-updates] update available for {plugin_id} [scope {scope}]: "
                f"{current_version} → {latest}. Auto-update is off (plugin_auto_update_enabled=false). "
                f"Run: claude plugin update {plugin_id} --scope {scope}",
            )
            if line is not None:
                print(line)
            continue

        # Auto-update.
        state.log_line(
            "plugin-updates",
            f"auto-updating {plugin_id} [scope={scope}]: {current_version} → {latest}",
        )
        try:
            update_proc = subprocess.run(
                ["claude", "plugin", "update", plugin_id, "--scope", scope],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except subprocess.TimeoutExpired:
            state.log_line("plugin-updates", f"auto-update of {plugin_id} [scope={scope}] timed out")
            line = dedupe.emit_once(
                seen,
                f"manual@{plugin_id}@{scope}@{latest}",
                f"[plugin-updates] auto-update of {plugin_id} (scope {scope}) timed out "
                f"({current_version} → {latest}). Run manually: claude plugin update {plugin_id} --scope {scope}",
            )
            if line is not None:
                print(line)
            update_errors += 1
            continue

        # Append captured output to the log for audit trail.
        try:
            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(update_proc.stdout or "")
                if update_proc.stderr:
                    logf.write(update_proc.stderr)
        except OSError:
            pass

        if update_proc.returncode != 0:
            state.log_line(
                "plugin-updates",
                f"auto-update of {plugin_id} [scope={scope}] failed (rc={update_proc.returncode})",
            )
            line = dedupe.emit_once(
                seen,
                f"manual@{plugin_id}@{scope}@{latest}",
                f"[plugin-updates] auto-update of {plugin_id} (scope {scope}) failed "
                f"({current_version} → {latest}). Run manually: claude plugin update {plugin_id} --scope {scope}",
            )
            if line is not None:
                print(line)
            update_errors += 1
            continue

        out = update_proc.stdout or ""
        m = _UPDATED_FROM_RE.search(out)
        if m:
            real_new = m.group(1).rstrip(".") or latest
            line = dedupe.emit_once(
                seen,
                f"updated@{plugin_id}@{scope}@{current_version}->{real_new}",
                f"[plugin-updates] auto-updated {plugin_id} [scope {scope}]: "
                f"{current_version} → {real_new}. Run /reload-plugins to apply in this session.",
            )
            if line is not None:
                print(line)
            updates_applied += 1
        elif "already at the latest" in out:
            state.log_line(
                "plugin-updates",
                f"{plugin_id} [scope={scope}]: CLI reports already at latest (marketplace.json suggested {latest})",
            )
        else:
            # Unexpected output shape — neither success nor known no-op
            # marker. Treat as failure for visibility.
            state.log_line(
                "plugin-updates",
                f"{plugin_id} [scope={scope}]: unexpected update output — treating as failure",
            )
            line = dedupe.emit_once(
                seen,
                f"manual@{plugin_id}@{scope}@{latest}",
                f"[plugin-updates] update of {plugin_id} (scope {scope}) returned unexpected output. "
                f"Run manually: claude plugin update {plugin_id} --scope {scope}",
            )
            if line is not None:
                print(line)
            update_errors += 1

    if updates_applied > 0 or update_errors > 0:
        state.log_line("plugin-updates", f"summary: {updates_applied} updated, {update_errors} failed")

    state.rotate_log_if_big("plugin-updates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
