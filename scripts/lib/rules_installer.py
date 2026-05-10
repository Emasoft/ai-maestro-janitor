"""Install plugin-shipped rule files into the active scope's .claude/rules/.

When a plugin ships rules under `<plugin_root>/rules/*.md`, those files
are NOT picked up automatically by Claude Code — the rule loader only
reads `~/.claude/rules/*.md` (user-scope) and
`<project_root>/.claude/rules/*.md` (project-scope and local-scope).
This module copies the plugin's shipped rules into whichever scope's
rules directory matches the plugin's installed scope.

Scope detection mirrors `scripts/detectors/version-update.py`'s
`_detect_install_scopes` — the source of truth lives there. We do NOT
import the detector at runtime (it would couple a hook against a
detector and pull `state` / `dedupe` into the import graph), so the
detection logic is duplicated here. If the version-update detector's
heuristic is ever revised, mirror the change here too.

Idempotency:
  * Files that already exist at the destination are LEFT ALONE — the
    user may have edited the rule and we don't want to silently
    overwrite. To force a refresh, delete the destination copy and
    the next session-start fires a fresh install.
  * Empty `<plugin_root>/rules/` directory is a silent no-op.
  * No installed scope (e.g. fresh checkout outside a Claude Code
    session) is also a silent no-op — the hook degrades gracefully
    instead of erroring.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

PLUGIN_NAME = "ai-maestro-janitor"


def _detect_install_scopes() -> list[str]:
    """Return every scope where the plugin is referenced in settings.json.

    Order: user → local → project. A plugin can be installed in
    multiple scopes simultaneously, so this returns a list (not a
    single value). String-match against `PLUGIN_NAME` matches both
    `enabledPlugins` and `disabledPlugins` mentions; we accept that
    ambiguity because rule files are harmless when the plugin is
    disabled, and full JSON parsing would couple this module to the
    Claude Code settings schema.
    """
    scopes: list[str] = []

    user_settings = Path.home() / ".claude" / "settings.json"
    if user_settings.is_file():
        try:
            if PLUGIN_NAME in user_settings.read_text(encoding="utf-8"):
                scopes.append("user")
        except OSError:
            pass

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir:
        for scope, rel in (
            ("local", ".claude/settings.local.json"),
            ("project", ".claude/settings.json"),
        ):
            f = Path(project_dir) / rel
            if f.is_file():
                try:
                    if PLUGIN_NAME in f.read_text(encoding="utf-8"):
                        scopes.append(scope)
                except OSError:
                    pass
    return scopes


def _target_rules_dir(scope: str) -> Path | None:
    """Compute the .claude/rules/ directory for a given install scope.

    user-scope          → ~/.claude/rules/
    local + project     → $CLAUDE_PROJECT_DIR/.claude/rules/

    Local and project both live under the project's `.claude/`, so
    they map to the same target — the caller deduplicates by directory
    path, not by scope name.
    """
    if scope == "user":
        return Path.home() / ".claude" / "rules"
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir and scope in ("local", "project"):
        return Path(project_dir) / ".claude" / "rules"
    return None


def install_rules(plugin_root: Path) -> list[str]:
    """Copy <plugin_root>/rules/*.md to every active scope's rules dir.

    Returns a list of `<dst-path>` strings for files that were actually
    copied on this call (so the caller can log them). Files that
    already exist at the destination are skipped — see the module
    docstring for the no-overwrite rationale.
    """
    src_dir = plugin_root / "rules"
    if not src_dir.is_dir():
        return []

    rule_files = sorted(
        p for p in src_dir.iterdir() if p.is_file() and p.suffix == ".md"
    )
    if not rule_files:
        return []

    scopes = _detect_install_scopes()
    if not scopes:
        return []

    # Deduplicate target dirs: local + project both resolve to the
    # same `<project>/.claude/rules/` path, so a plugin installed in
    # both scopes would otherwise be processed twice. dict-by-path
    # keeps a single entry per unique target.
    targets: dict[str, Path] = {}
    for scope in scopes:
        td = _target_rules_dir(scope)
        if td is None:
            continue
        targets[str(td)] = td

    copied: list[str] = []
    for td in targets.values():
        try:
            td.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for src in rule_files:
            dst = td / src.name
            if dst.exists():
                continue  # don't overwrite — user may have edited
            try:
                shutil.copyfile(src, dst)
                copied.append(str(dst))
            except OSError:
                continue
    return copied
