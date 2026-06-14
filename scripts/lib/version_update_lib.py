"""Shared janitor self-update helpers — used by the daemon's
`task_version_update` (the auto-update branch) and the per-session
`version-update` detector (the read-only detection branch).

Per TRDD-be2efa56 §9 follow-up: the auto-update branch moved into the
daemon so every Claude Code session that arms the janitor benefits from
a single global writer. The detector keeps emitting drift lines only —
no `claude plugin update` calls. This module factors the helpers both
surfaces need so we don't duplicate semver / scope-discovery logic.

Functions:
  - `_semver_tuple(s)` — string → (int, …) for ordering
  - `detect_install_scopes()` — every settings file mentioning the
    janitor's PLUGIN_NAME, in user → local → project order
  - `list_installed_versions(parent)` — semver-shaped subdir names
    of the cache parent, sorted ascending
  - `resolve_latest_published(plugin_root)` — GitHub releases/latest
    tag for the repo declared in the plugin's manifest
  - `attempt_auto_update(log_writer)` — best-effort `claude plugin
    marketplace update` + per-scope `claude plugin update`; True iff
    at least one scope finished successfully. Designed so both the
    daemon (logs into ~/.claude/janitor-global-state/daemon.log) and
    the detector (logs into <project>/.janitor/logs/version-update.log)
    can supply their own write-line callable.
  - `do_auto_update_if_needed(plugin_root, log_writer)` — the wrapper
    the daemon task calls: reads cache state, compares to GitHub
    latest, runs `attempt_auto_update` when behind. Returns
    (updated_bool, new_latest_installed_or_empty).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

PLUGIN_NAME = "ai-maestro-janitor"
MARKETPLACE_NAME = "ai-maestro-plugins"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_GH_REPO_RE = re.compile(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$")


def _semver_tuple(s: str) -> tuple[int, ...]:
    """Convert '0.4.0' to (0, 4, 0) for ordering. Returns (-1,) on bad input."""
    if not _SEMVER_RE.match(s):
        return (-1,)
    return tuple(int(p) for p in s.split("."))


def detect_install_scopes() -> list[str]:
    """Return every scope where the plugin is referenced.

    A plugin can be installed simultaneously in multiple scopes (e.g.
    `user` AND `local`). The auto-updater iterates this list so a
    `--scope user` update no longer leaves a `local` install on the
    old version. Order matters: user → local → project, broadest first.
    """
    scopes: list[str] = []

    # User scope.
    f = Path.home() / ".claude" / "settings.json"
    if f.is_file():
        try:
            if PLUGIN_NAME in f.read_text():
                scopes.append("user")
        except OSError:
            pass

    # Local + project scopes (project root from CLAUDE_PROJECT_DIR or git).
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        for scope, rel in [
            ("local", ".claude/settings.local.json"),
            ("project", ".claude/settings.json"),
        ]:
            f = Path(project_dir) / rel
            if f.is_file():
                try:
                    if PLUGIN_NAME in f.read_text():
                        scopes.append(scope)
                except OSError:
                    pass
    return scopes


def list_installed_versions(parent: Path) -> list[str]:
    """Semver-shaped subdir names of `parent`, sorted ascending."""
    if not parent.is_dir():
        return []
    versions = [
        d.name for d in parent.iterdir()
        if d.is_dir() and _SEMVER_RE.match(d.name)
    ]
    return sorted(versions, key=_semver_tuple)


def resolve_latest_published(plugin_root: Path) -> str | None:
    """GitHub releases/latest tag for the repo declared in plugin.json.

    Returns the tag stripped of any leading `v`, or None on any failure
    (no manifest, missing repository URL, `gh` unavailable, network
    error, no published releases yet). Silent by design — the caller
    decides whether to log.
    """
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

    if shutil.which("gh") is None:
        return None
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}/releases/latest", "--jq", ".tag_name"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    tag = (proc.stdout or "").strip()
    if not tag:
        return None
    return tag[1:] if tag.startswith("v") else tag


def attempt_auto_update(log_writer: Callable[[str], None],
                        update_log_path: Path | None = None) -> bool:
    """Refresh marketplace + run `claude plugin update` per scope.

    `log_writer(msg)` is the caller's log sink (daemon → daemon.log,
    detector → version-update.log). `update_log_path` is where the
    `claude` subprocess's stdout/stderr is appended; when None, output
    is discarded. Returns True iff at least one scope completed rc=0;
    silent on transient failures so the next cycle can retry.
    """
    if shutil.which("claude") is None:
        log_writer("auto-update: claude CLI not in PATH — falling back to manual nudge")
        return False

    log_writer(f"auto-update: refreshing marketplace '{MARKETPLACE_NAME}'")
    if update_log_path is not None:
        with update_log_path.open("a", encoding="utf-8") as logf:
            proc = subprocess.run(
                ["claude", "plugin", "marketplace", "update", MARKETPLACE_NAME],
                stdout=logf, stderr=subprocess.STDOUT,
                timeout=30, check=False,
            )
    else:
        proc = subprocess.run(
            ["claude", "plugin", "marketplace", "update", MARKETPLACE_NAME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=False,
        )
    if proc.returncode != 0:
        log_writer("auto-update: marketplace refresh failed")
        return False

    scopes = detect_install_scopes()
    log_writer(f"auto-update: detected install scopes={scopes or '[none]'}")

    targets: list[list[str]] = []
    base_cmd = ["claude", "plugin", "update", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"]
    if scopes:
        for scope in scopes:
            targets.append(base_cmd + ["--scope", scope])
    else:
        # NEVER run a scope-less `claude plugin update`. Without --scope the CLI
        # INFERS the scope, which can silently MIGRATE the plugin between scopes
        # (e.g. local→user) — the exact accident the scope invariant forbids. If
        # the install scope can't be detected, SKIP the self-update (leave
        # `targets` empty → the `not any_success` guard below returns False)
        # rather than guess; the user updates manually with the exact --scope.
        log_writer(
            f"auto-update: could not detect any install scope for "
            f"{PLUGIN_NAME}@{MARKETPLACE_NAME} — SKIPPING self-update "
            "(refusing a scope-less `claude plugin update`; update manually "
            "with the exact --scope it was installed at)."
        )

    any_success = False
    for cmd in targets:
        log_writer(f"auto-update: {' '.join(cmd)}")
        try:
            if update_log_path is not None:
                with update_log_path.open("a", encoding="utf-8") as logf:
                    proc = subprocess.run(
                        cmd, stdout=logf, stderr=subprocess.STDOUT,
                        timeout=120, check=False,
                    )
            else:
                proc = subprocess.run(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=120, check=False,
                )
        except subprocess.TimeoutExpired:
            log_writer(f"auto-update: plugin update timed out ({' '.join(cmd[-2:])})")
            continue
        if proc.returncode != 0:
            log_writer(
                f"auto-update: plugin update failed (rc={proc.returncode}, "
                f"cmd={' '.join(cmd[-2:])})",
            )
            continue
        any_success = True

    if not any_success:
        return False

    log_writer("auto-update: success")
    return True


def do_auto_update_if_needed(plugin_root: Path,
                             log_writer: Callable[[str], None],
                             update_log_path: Path | None = None,
                             ) -> tuple[bool, str]:
    """Run the cache-vs-GitHub check + auto-update in one go.

    `plugin_root` is the current `<plugin>/<version>/` dir; its parent
    is the cache root we list versions from. Returns
    `(updated_bool, latest_installed_after)` — the latest installed
    version on disk AFTER the attempt, so callers can compare against
    pre-state to decide whether to fire reload signals.

    Designed for the daemon: it's safe to call every cadence, silent
    when nothing's behind, conservative on every failure mode.
    """
    cache_parent = plugin_root.parent
    installed = list_installed_versions(cache_parent)
    latest_installed = installed[-1] if installed else ""

    latest_published = resolve_latest_published(plugin_root) or ""
    if not latest_published or not latest_installed:
        return (False, latest_installed)
    if latest_published == latest_installed:
        return (False, latest_installed)
    if _semver_tuple(latest_installed) >= _semver_tuple(latest_published):
        # Cache is at or ahead of GitHub — pre-release / dev cache. Silent.
        return (False, latest_installed)

    if not attempt_auto_update(log_writer, update_log_path):
        return (False, latest_installed)

    # Re-list to confirm the cache actually advanced; if not, treat as
    # failure (the `claude` CLI may have reported success without
    # downloading the new dir).
    refreshed = list_installed_versions(cache_parent)
    new_latest = refreshed[-1] if refreshed else latest_installed
    if new_latest == latest_installed:
        log_writer(
            "auto-update reported success but cache version did not advance — "
            "treating as failure",
        )
        return (False, latest_installed)
    return (True, new_latest)
