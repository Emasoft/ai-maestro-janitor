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

Idempotency (size-based):
  * If the destination file already exists AND has the same byte
    size as the plugin's source copy, it is left alone — same size
    is treated as "already up to date".
  * If the destination exists with a DIFFERENT size, the plugin's
    copy overwrites it. Rationale: the plugin author ships rule
    updates by editing `<plugin_root>/rules/*.md` and bumping the
    release; without overwrite-on-size-mismatch, every user who
    saw the previous version would be stuck on it forever (the
    hook would silently skip them). Size-based detection is a
    cheap heuristic: real plugin updates almost always change the
    byte count, and a user who genuinely customised the rule and
    happened to land on the exact same size will be surprised once
    — a price we accept to keep the rule fleet in sync.
  * Empty `<plugin_root>/rules/` directory is a silent no-op.
  * No installed scope (e.g. fresh checkout outside a Claude Code
    session) is also a silent no-op — the hook degrades gracefully
    instead of erroring.
"""

from __future__ import annotations

import os
import shutil
import tempfile
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

    Returns a list of `<dst-path>` strings for files that were
    actually copied on this call (so the caller can log them).
    Existing destination files are kept when their byte size matches
    the source (treated as "already up to date") and overwritten
    when the size differs — see the module docstring for the
    size-based-idempotency rationale.
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
                try:
                    # Same size ⇒ treat as up-to-date and skip. Different
                    # size ⇒ fall through to the copy below, which
                    # shutil.copyfile will perform as an overwrite.
                    if dst.stat().st_size == src.stat().st_size:
                        continue
                except OSError:
                    # Can't stat (race, permission). Bail rather than
                    # risk an overwrite based on incomplete info.
                    continue
            tmp = None
            try:
                # Atomic publish: copy to a unique temp in the SAME dir, then
                # os.replace (atomic rename on POSIX) so N concurrent
                # session-start installs writing this user-scope rule file
                # can't tear it. Rules-install stays per-session (rules must
                # be present at session start), but the write is now
                # corruption-free under fan-out — the cheap-idempotent-file
                # analogue of the daemon's single-writer lock for commands.
                fd, tmp = tempfile.mkstemp(dir=str(td), prefix=f".{src.name}.", suffix=".tmp")
                os.close(fd)
                shutil.copyfile(src, tmp)
                os.replace(tmp, dst)
                copied.append(str(dst))
            except OSError:
                if tmp is not None:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                continue
    return copied
