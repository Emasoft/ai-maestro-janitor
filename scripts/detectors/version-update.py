#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""Version-update detector — Python port of version-update.sh.

Keeps three versions in sync:

  * running           — version of dispatch that's actually firing on the
                        cron prompt (extracted from the script's own path)
  * latest_installed  — highest version present in the plugin cache dir
  * latest_published  — latest GitHub release for the repo declared in
                        the manifest's `repository` field

When latest_published > latest_installed, the detector attempts to
auto-update via `claude plugin marketplace update` +
`claude plugin update <plugin>@<marketplace> --scope <auto-detected>`.
Auto-update is on by default and gated by `auto_update_on_new_release`.

After a possible auto-update, if running != latest_installed, the
detector emits a single concise nudge — the cron prompt has the
dispatch path baked in at /janitor-arm time, so a stale cache OR a
stale cron both need a re-arm to take effect.

Silent on transient failures (no network, gh auth expired, no
releases yet, claude CLI missing). One nudge per state change, then
dedupe.
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


PLUGIN_NAME = "ai-maestro-janitor"
MARKETPLACE_NAME = "ai-maestro-plugins"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_GH_REPO_RE = re.compile(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$")


def _semver_tuple(s: str) -> tuple[int, ...]:
    """Convert '0.4.0' to (0, 4, 0) for ordering. Returns (-1,) on bad input."""
    if not _SEMVER_RE.match(s):
        return (-1,)
    return tuple(int(p) for p in s.split("."))


def _detect_install_scope() -> str:
    """Return 'user', 'local', 'project', or '' if not detectable.

    Order matters: user → local → project; first match wins. Tests for
    PLUGIN_NAME mentioned in each settings file. The bash port searched
    for the literal string; we do the same so a `disabledPlugins` mention
    is not distinguished — for our purposes any reference is enough since
    `claude plugin update --scope` validates the actual install state.
    """
    # User scope.
    f = Path.home() / ".claude" / "settings.json"
    if f.is_file():
        try:
            if PLUGIN_NAME in f.read_text():
                return "user"
        except OSError:
            pass

    # Local + project scopes (project root from CLAUDE_PROJECT_DIR or git).
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        for scope, rel in [("local", ".claude/settings.local.json"), ("project", ".claude/settings.json")]:
            f = Path(project_dir) / rel
            if f.is_file():
                try:
                    if PLUGIN_NAME in f.read_text():
                        return scope
                except OSError:
                    pass
    return ""


def _list_installed_versions(parent: Path) -> list[str]:
    """Yield semver-shaped subdir names of `parent`, sorted ascending."""
    if not parent.is_dir():
        return []
    versions = [
        d.name for d in parent.iterdir()
        if d.is_dir() and _SEMVER_RE.match(d.name)
    ]
    return sorted(versions, key=_semver_tuple)


def _attempt_auto_update() -> bool:
    """Best-effort auto-update via `claude` CLI. Returns True on success.

    All output captured to the detector log so the user can inspect what
    happened — never echoed to stdout (that would surface noise to the
    heartbeat instead of a single concise nudge).
    """
    log_path = state.log_dir() / "version-update.log"

    if shutil.which("claude") is None:
        state.log_line("version-update", "auto-update: claude CLI not in PATH — falling back to manual nudge")
        return False

    state.log_line("version-update", f"auto-update: refreshing marketplace '{MARKETPLACE_NAME}'")
    with log_path.open("a", encoding="utf-8") as logf:
        proc = subprocess.run(
            ["claude", "plugin", "marketplace", "update", MARKETPLACE_NAME],
            stdout=logf, stderr=subprocess.STDOUT,
            timeout=30, check=False,
        )
    if proc.returncode != 0:
        state.log_line("version-update", "auto-update: marketplace refresh failed")
        return False

    scope = _detect_install_scope()
    state.log_line("version-update", f"auto-update: detected install scope='{scope}'")

    cmd = ["claude", "plugin", "update", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"]
    if scope:
        cmd += ["--scope", scope]
        state.log_line("version-update", f"auto-update: {' '.join(cmd)}")
    else:
        state.log_line("version-update", f"auto-update: {' '.join(cmd)} (no scope detected)")

    try:
        with log_path.open("a", encoding="utf-8") as logf:
            proc = subprocess.run(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                timeout=120, check=False,
            )
    except subprocess.TimeoutExpired:
        state.log_line("version-update", "auto-update: plugin update timed out")
        return False
    if proc.returncode != 0:
        state.log_line("version-update", f"auto-update: plugin update failed (rc={proc.returncode})")
        return False

    state.log_line("version-update", "auto-update: success")
    return True


def _resolve_latest_published(plugin_root: Path) -> Optional[str]:
    """GitHub releases/latest tag for the repo declared in plugin.json."""
    plugin_json = plugin_root / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None
    try:
        with plugin_json.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    repo_url = str(data.get("repository", "") or "")
    m = _GH_REPO_RE.match(repo_url)
    if not m:
        return None
    slug = m.group(1)

    proc = subprocess.run(
        ["gh", "api", f"repos/{slug}/releases/latest", "--jq", ".tag_name"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if proc.returncode != 0:
        return None
    tag = proc.stdout.strip()
    return tag.lstrip("v") if tag else None


def _is_truthy_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.lower() not in ("false", "0", "no", "off")


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "version-update-seen.txt"
    here = Path(__file__).resolve().parent  # scripts/detectors/

    # Running version — basename of `<plugin>/<version>/scripts/detectors/`.
    plugin_root = here.parent.parent       # <plugin>/<version>/
    cache_parent = plugin_root.parent      # <plugin>/
    running_version = plugin_root.name

    is_cache_install = bool(_SEMVER_RE.match(running_version))
    if not is_cache_install:
        state.log_line("version-update", f"running from non-versioned dir ({running_version}) — cron-version check disabled")

    latest_installed = ""
    if is_cache_install:
        installed = _list_installed_versions(cache_parent)
        latest_installed = installed[-1] if installed else ""

    plugin_root_for_lookup = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", "") or plugin_root)
    latest_published = _resolve_latest_published(plugin_root_for_lookup) or ""

    state.log_line(
        "version-update",
        f"state: running={running_version} latest_installed={latest_installed} latest_published={latest_published}",
    )

    auto_updated = False
    manual_update_needed = False

    # Branch A: newer published than locally installed?
    if latest_published and latest_installed and latest_published != latest_installed:
        if _semver_tuple(latest_installed) < _semver_tuple(latest_published):
            auto_enabled = _is_truthy_env("CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE", True)
            if auto_enabled and _attempt_auto_update():
                auto_updated = True
                # Re-list cache parent so latest_installed reflects the
                # freshly fetched version. If the update somehow didn't add
                # a new dir, treat that as a failure.
                refreshed = _list_installed_versions(cache_parent)
                new_latest = refreshed[-1] if refreshed else ""
                if new_latest and new_latest != latest_installed:
                    latest_installed = new_latest
                else:
                    state.log_line(
                        "version-update",
                        "auto-update reported success but cache version did not advance — treating as failure",
                    )
                    auto_updated = False
                    manual_update_needed = True
            else:
                manual_update_needed = True
        else:
            # latest_installed > latest_published → dev / pre-release work.
            state.log_line(
                "version-update",
                f"local cache ({latest_installed}) ahead of GitHub latest ({latest_published}) — silent",
            )

    # Branch B: pick the right nudge for the current state.
    if manual_update_needed:
        line = dedupe.emit_once(
            seen,
            f"version-update@manual@{latest_published}",
            f"[version-update] {PLUGIN_NAME} {latest_installed} → {latest_published} — run /plugin update {PLUGIN_NAME} + /janitor-arm.",
        )
    elif auto_updated:
        line = dedupe.emit_once(
            seen,
            f"version-update@updated@{latest_installed}",
            f"[version-update] {PLUGIN_NAME}: cache updated to {latest_installed}. Run /reload-plugins + /janitor-arm.",
        )
    elif is_cache_install and latest_installed and running_version != latest_installed:
        line = dedupe.emit_once(
            seen,
            f"version-update@stale-cron@{latest_installed}",
            f"[version-update] {PLUGIN_NAME} {latest_installed} installed; cron is on {running_version}. /janitor-arm.",
        )
    else:
        line = None

    if line is not None:
        print(line)

    state.rotate_log_if_big("version-update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
