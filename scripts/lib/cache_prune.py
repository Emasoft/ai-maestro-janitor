"""Plugin-cache pruning primitives (TRDD-a6d2fdaf, Fix A).

The plugin cache `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`
grows without bound: a fast-publishing plugin (CPV ships several versions a
DAY) leaves dozens of stale version dirs, and Claude Code's ~7-day GC keeps
them all because they are each "recent". On this machine CPV alone reached 49
cached versions and the whole cache hit 4.5 GB.

This module decides which version dirs are SAFE to delete. The cardinal safety
rule, and the reason the logic is more than "keep the newest N":

    NEVER prune a version a LIVE session might still have loaded.

A `claude` session loaded the plugin version that was current when it STARTED
(its dir mtime is ~the session's age ago) and may have reloaded forward to newer
ones — so nothing with a dir mtime newer than the OLDEST live session's start is
ever eligible. This matters precisely for the unattended fleet the janitor
exists to protect: those sessions run for hours or days, long enough for the
version they loaded to age past any fixed floor. The fixed MIN_AGE floor is only
a secondary guard for when no long session is running.

The decision functions are PURE (take versions + mtimes + a cutoff); the I/O
wrapper gathers the inputs and does the deletes. Deleting a cache version dir is
safe-by-construction: it is regeneratable (Claude Code re-downloads it from the
marketplace on demand), so a plain `rmtree` is correct (per use-safe-delete).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def _is_claude_session(command: str) -> bool:
    """True iff `command` (a full ps argv line) is a real Claude Code CLI
    session. Mirrors `oauth_rotator.rotator.claude_running` EXACTLY for
    consistency: a session is a process whose argv[0] BASENAME is exactly
    ``claude`` (the launcher/symlink REPL invocation), or whose argv carries the
    versioned binary path ``.../share/claude/versions/<ver>``.

    Over-detection here is SAFE — a false positive only KEEPS more cache (more
    conservative cutoff); a MISSED session would risk pruning a version it
    loaded, so we match the same conservative way the rotator does and never
    substring-match ``claude`` (which would hit ``.claude`` paths, plugin names
    like ``claude-plugins-validation``, the janitor's own python argv, etc.)."""
    line = command.strip()
    if not line:
        return False
    first = line.split()[0]
    if os.path.basename(first) == "claude":
        return True
    return "/share/claude/versions/" in line


def oldest_claude_session_start(
    sessions: list[tuple[str, int]], now: int
) -> int | None:
    """Return the START epoch of the OLDEST live Claude session, or None if none
    is detected. `sessions` is a list of (command, etime_seconds) pairs (pure —
    the caller snapshots ps). Nothing with a dir mtime newer than this epoch is
    safe to prune: that session loaded its plugins at start and may still
    reference the version that was current then."""
    oldest: int | None = None
    for command, etime_s in sessions:
        if not _is_claude_session(command):
            continue
        start = now - max(0, etime_s)
        if oldest is None or start < oldest:
            oldest = start
    return oldest


def prune_cutoff(
    *,
    now: int,
    min_age_s: int,
    oldest_session_start: int | None,
    session_margin_s: int,
) -> int:
    """Versions whose dir mtime is STRICTLY OLDER than the returned epoch are old
    enough to prune. It is `now - min_age_s`, but never newer than
    `oldest_session_start - session_margin_s` — so a long-running session's
    loaded version (mtime ~its start) is always protected by the margin."""
    cutoff = now - max(0, min_age_s)
    if oldest_session_start is not None:
        cutoff = min(cutoff, oldest_session_start - max(0, session_margin_s))
    return cutoff


def plan_plugin_prune(
    *,
    versions: list[str],
    version_mtime: dict[str, int],
    pinned: str | None,
    keep_recent: int,
    cutoff_epoch: int,
    now: int,
) -> tuple[list[str], list[str]]:
    """Decide (prune, keep) for ONE plugin's version list. Pure.

    KEEP = the newest `keep_recent` versions (the list is ascending semver) ∪ the
    pinned version (belt-and-suspenders: pinned is normally the newest, but a
    downgrade can pin an older one). Of the rest, a version is PRUNED only when
    its dir mtime is strictly older than `cutoff_epoch`; anything younger is kept
    (a live session may still hold it). An unknown mtime defaults to `now` → kept
    (never prune what you can't date)."""
    protected: set[str] = set(versions[-keep_recent:]) if keep_recent > 0 else set()
    if pinned:
        protected.add(pinned)
    prune: list[str] = []
    keep: list[str] = []
    for v in versions:
        if v in protected:
            keep.append(v)
            continue
        if version_mtime.get(v, now) < cutoff_epoch:
            prune.append(v)
        else:
            keep.append(v)
    return prune, keep


def pinned_version_for(
    installed_plugins: dict, plugin: str, marketplace: str
) -> str | None:
    """Best-effort: the version Claude Code currently pins for
    `<plugin>@<marketplace>`, read from a parsed installed_plugins.json. Returns
    None when the entry/shape isn't found (the caller then relies on keep_recent,
    which already protects the newest/current version in the normal case)."""
    plugins = installed_plugins.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entry = plugins.get(f"{plugin}@{marketplace}")
    # The shipped shape is a list with a dict carrying a `<plugin>/<version>`
    # path; rather than over-fit that exact key, scan the entry's JSON for the
    # first `<plugin>/<version>` token — robust to minor schema drift.
    blob = json.dumps(entry)
    needle = f"{plugin}/"
    idx = blob.find(needle)
    if idx < 0:
        return None
    tail = blob[idx + len(needle):]
    version = ""
    for ch in tail:
        if ch.isdigit() or ch == ".":
            version += ch
        else:
            break
    return version or None


@dataclass(frozen=True)
class PrunePlan:
    """The prune decision for one plugin dir."""

    plugin_dir: Path
    marketplace: str
    plugin: str
    pinned: str | None
    prune: list[str]
    keep: list[str]


def _semver_sorted(version_dirs: list[str]) -> list[str]:
    """Sort version dir names ascending by their leading dotted-int run. A name
    that doesn't start with a digit sorts first (treated as 'oldest/unknown')."""

    def key(name: str) -> tuple[int, tuple[int, ...]]:
        parts: list[int] = []
        for seg in name.split("."):
            num = ""
            for ch in seg:
                if ch.isdigit():
                    num += ch
                else:
                    break
            if num == "":
                break
            parts.append(int(num))
        return (1 if parts else 0, tuple(parts))

    return sorted(version_dirs, key=key)


def plan_cache_prune(
    cache_root: Path,
    installed_plugins: dict,
    *,
    keep_recent: int,
    cutoff_epoch: int,
    now: int,
) -> list[PrunePlan]:
    """Build a prune plan for every `<marketplace>/<plugin>/` under `cache_root`.
    Pure except for reading dir listings + mtimes (no deletes)."""
    plans: list[PrunePlan] = []
    if not cache_root.is_dir():
        return plans
    for market_dir in sorted(p for p in cache_root.iterdir() if p.is_dir()):
        for plugin_dir in sorted(p for p in market_dir.iterdir() if p.is_dir()):
            version_dirs = [p.name for p in plugin_dir.iterdir() if p.is_dir()]
            if not version_dirs:
                continue
            versions = _semver_sorted(version_dirs)
            mtimes: dict[str, int] = {}
            for v in versions:
                try:
                    mtimes[v] = int((plugin_dir / v).stat().st_mtime)
                except OSError:
                    mtimes[v] = now  # undateable → treat as now → never pruned
            pinned = pinned_version_for(
                installed_plugins, plugin_dir.name, market_dir.name
            )
            prune, keep = plan_plugin_prune(
                versions=versions,
                version_mtime=mtimes,
                pinned=pinned,
                keep_recent=keep_recent,
                cutoff_epoch=cutoff_epoch,
                now=now,
            )
            if prune:
                plans.append(
                    PrunePlan(
                        plugin_dir=plugin_dir,
                        marketplace=market_dir.name,
                        plugin=plugin_dir.name,
                        pinned=pinned,
                        prune=prune,
                        keep=keep,
                    )
                )
    return plans


def apply_prune_plan(plans: list[PrunePlan]) -> tuple[list[str], list[str]]:
    """Delete the planned version dirs. Returns (removed, failed) as
    `<marketplace>/<plugin>/<version>` strings. Best-effort: a failed delete is
    recorded, never raised — a cache prune must never crash the daemon."""
    removed: list[str] = []
    failed: list[str] = []
    for plan in plans:
        for version in plan.prune:
            rel = f"{plan.marketplace}/{plan.plugin}/{version}"
            try:
                shutil.rmtree(plan.plugin_dir / version)
                removed.append(rel)
            except OSError:
                failed.append(rel)
    return removed, failed
