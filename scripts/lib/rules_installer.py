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

Idempotency (content-based — issue #37):
  * If the destination file already exists AND its bytes are
    identical to the plugin's source copy, it is left alone
    ("already up to date").
  * If the destination exists with ANY byte difference, the
    plugin's copy overwrites it. Rationale: the plugin author ships
    rule updates by editing `<plugin_root>/rules/*.md` and bumping
    the release; without overwrite-on-difference, every user who
    saw the previous version would be stuck on it forever (the hook
    would silently skip them). Byte-exact comparison (NOT size-only)
    closes a silent blind spot: a rule edit that preserves the byte
    count — e.g. a scope-root path swap of equal length — would slip
    past a size check and strand the user on a stale rule whose
    recall silently misses (#37, the quietest failure mode for a
    memory system). Rule files are small, so reading both copies at
    most once per session is cheap.
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

# Provenance marker every shipped rule carries in its guard block (rules/*.md). It is
# the SOLE identifier the cleanup uses to decide a rule file was installed by THIS plugin
# and is therefore safe to remove — a user's own hand-written rule of the same name (no
# marker) is NEVER touched, and NO memory store is ever touched. Keep this string in sync
# with the `<!-- ai-maestro-janitor:installed-rule … -->` comment prepended to each rule.
PROVENANCE_MARKER = "ai-maestro-janitor:installed-rule"


def _data_dir() -> Path:
    """The janitor's canonical persistent DATA dir. Its ABSENCE is one of the two
    signals that the plugin has been fully uninstalled (Claude Code deletes the data dir
    when the plugin is removed from its last scope, unless `--keep-data`)."""
    return Path.home() / ".claude" / "plugins" / "data" / f"{PLUGIN_NAME}-ai-maestro-plugins"


def _known_rules_dirs() -> list[Path]:
    """Every `.claude/rules/` dir the janitor could have installed into: the USER dir
    always, plus the PROJECT dir when a `$CLAUDE_PROJECT_DIR` is in scope. The daemon
    (no project context) sees only the user dir; a session sees both."""
    dirs = [Path.home() / ".claude" / "rules"]
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir:
        dirs.append(Path(project_dir) / ".claude" / "rules")
    return dirs


def _is_janitor_installed_rule(path: Path) -> bool:
    """True iff `path` is a rule file THIS plugin installed — i.e. it carries the
    provenance marker. Fail-closed: an unreadable file returns False (never removed)."""
    try:
        return PROVENANCE_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _remove_janitor_rules_in(rules_dir: Path) -> list[str]:
    """Remove every provenance-marked janitor rule from `rules_dir` (a `.claude/rules/`
    dir). Returns the removed paths. SAFETY: only `*.md` files carrying the marker are
    removed — a user's own rule (no marker) is left alone — and nothing OUTSIDE
    `rules_dir` is ever touched, so no memory store can be affected."""
    removed: list[str] = []
    if not rules_dir.is_dir():
        return removed
    for p in sorted(rules_dir.glob("*.md")):
        if not _is_janitor_installed_rule(p):
            continue
        try:
            p.unlink()
            removed.append(str(p))
        except OSError:
            continue
    return removed


def _current_target_dirs() -> set[str]:
    """The set of `str(rules_dir)` the janitor SHOULD currently install into, mirroring
    `install_rules`'s scope logic (user-scope wins, dedup by path). Any KNOWN rules dir
    not in this set is one the janitor was uninstalled from → its janitor rules are
    orphans to remove."""
    scopes = _detect_install_scopes()
    if "user" in scopes:
        scopes = ["user"]
    keep: set[str] = set()
    for scope in scopes:
        td = _target_rules_dir(scope)
        if td is not None:
            keep.add(str(td))
    return keep


def remove_orphaned_rules() -> list[str]:
    """Partial-uninstall self-heal: remove janitor-installed rules from every KNOWN rules
    dir that is NOT a current install target — e.g. the PROJECT scope after the janitor
    was uninstalled from it while still user-installed (also the "redundant project mirror
    of a user-scope rule" cleanup, issue #36). Marker-gated; never touches a user's own
    rule or any memory store. Returns removed paths."""
    keep = _current_target_dirs()
    removed: list[str] = []
    for d in _known_rules_dirs():
        if str(d) in keep:
            continue
        removed.extend(_remove_janitor_rules_in(d))
    return removed


def janitor_uninstalled() -> bool:
    """True iff the janitor appears FULLY uninstalled: referenced in NO settings.json
    scope AND its persistent DATA dir is gone. BOTH must hold — requiring the two
    independent signals to agree resists a transient false positive (a momentary
    settings-read miss AND a vanished data dir do not co-occur under normal operation).
    A merely DISABLED plugin still appears in settings.json, so this returns False for
    it (we must not delete rules for a plugin the user only paused)."""
    if _detect_install_scopes():
        return False
    return not _data_dir().exists()


def cleanup_user_orphans_if_uninstalled() -> list[str]:
    """Daemon entry point (TRDD-H9IBY95W): when the janitor is FULLY uninstalled, remove
    its provenance-marked orphaned rules from the USER rules dir (`~/.claude/rules/`).
    Claude Code has NO uninstall hook and does not clean a plugin's `~/.claude/rules/`, so
    the still-running daemon (alive until its orphaned cache is GC'd, ~7 days) is the only
    actor that can remove them. The daemon is global (no project context) → user scope
    only; per-session `remove_orphaned_rules` covers project scope. Returns [] while the
    janitor is still installed. NEVER touches any memory store."""
    if not janitor_uninstalled():
        return []
    return _remove_janitor_rules_in(Path.home() / ".claude" / "rules")


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

    # USER-SCOPE WINS (issue #36). Claude Code loads `~/.claude/rules/*` for
    # EVERY project, so a user-scope rule already applies everywhere. A
    # project-local copy is therefore a REDUNDANT mirror that adds nothing AND
    # sits untracked in the project tree, tripping the dirty-tree detector on
    # every heartbeat. When the plugin is user-installed (the janitor always is),
    # install ONLY to the user scope. Fall back to the project scope solely when
    # the plugin is NOT at user scope (a project-only install, where the local
    # copy is the only way the rule reaches Claude).
    if "user" in scopes:
        scopes = ["user"]

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
                    # CONTENT-exact idempotency (issue #37): compare BYTES, not just
                    # size. A size-only check has a silent blind spot — a rule edit
                    # that preserves the byte count (e.g. swapping one scope-root
                    # path for another of equal length) would NOT refresh the
                    # installed copy, stranding the user on a stale rule whose recall
                    # silently misses (#37: "PROJECT recall silently misses during
                    # rollout" — the quietest failure mode for a memory system).
                    # Byte-equal ⇒ already up to date, skip; ANY difference ⇒
                    # overwrite below. Rule files are small, so the read is cheap and
                    # runs at most once per session, not per prompt.
                    if dst.read_bytes() == src.read_bytes():
                        continue
                except OSError:
                    # Can't read (race, permission). Bail rather than
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
