"""Plugin-freshness helper (issue #69, TRDD-YF4NDYYE) — verify cached-vs-live BEFORE
a cache-based audit reports anything.

The staleness trap this kills: audits/detectors that read the plugin CACHE
(`~/.claude/plugins/cache/...`) can report against a version that is no longer what is
installed or published — findings look authoritative but describe outdated code (observed:
core 2.7.6 cached vs 2.7.12 live; a multi-plugin governance audit systematically
OVER-reported HIGH/CRITICAL findings that were already fixed in live). Every cache-based
audit surface therefore states WHAT it audited and warns when that diverges from the pin
or the latest published release.

Design constraints:
- FAIL-OPEN everywhere: offline / no gh / no plugin.json ⇒ the unknown fields are None and
  `is_stale` only fires on POSITIVE evidence of divergence. An audit is never blocked.
- CHEAP: the GitHub latest-release probe is cadence-limited through a small JSON cache in
  the global-state dir (default TTL 6h, `CLAUDE_PLUGIN_OPTION_FRESHNESS_TTL_S`; 0 disables
  the network probe entirely) — never a fresh network call per audit.
- All paths resolve at CALL time (the S2 frozen-home guard applies here too).

CLI: `python3 scripts/lib/plugin_freshness.py <plugin_root>` prints the one-line report
header — the form audit skills tell their agents to run before reading cached code.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cache_prune  # noqa: E402
import global_state  # noqa: E402
import state  # noqa: E402
import version_update_lib  # noqa: E402

_CACHE_NAME = "plugin-freshness-cache.json"
_DEFAULT_TTL_S = 6 * 3600


def _ttl_s() -> int:
    return state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_FRESHNESS_TTL_S"),
        _DEFAULT_TTL_S,
        detector_name="plugin-freshness",
        var_name="CLAUDE_PLUGIN_OPTION_FRESHNESS_TTL_S",
    )


def cached_version(plugin_root: Path) -> str | None:
    """The version of the plugin tree being audited (its own plugin.json)."""
    try:
        data = json.loads((Path(plugin_root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = data.get("version")
    return str(v) if v else None


def _derive_identity(plugin_root: Path) -> tuple[str | None, str | None]:
    """(plugin_name, marketplace) — from plugin.json name + the cache path shape
    `.../cache/<marketplace>/<plugin>/<version>` when the root sits in the cache."""
    name: str | None = None
    try:
        data = json.loads((Path(plugin_root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        name = str(data.get("name") or "") or None
    except (OSError, ValueError):
        pass
    parts = Path(plugin_root).parts
    marketplace = None
    if "cache" in parts:
        i = parts.index("cache")
        if len(parts) > i + 2:
            marketplace = parts[i + 1]
            name = name or parts[i + 2]
    return name, marketplace


def installed_pin(plugin_name: str | None, marketplace: str | None) -> str | None:
    """The version Claude Code currently pins for this plugin, or None."""
    if not plugin_name or not marketplace:
        return None
    ip_path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        installed = json.loads(ip_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cache_prune.pinned_version_for(installed, plugin_name, marketplace)


def _cache_path() -> Path:
    return global_state.global_state_dir() / _CACHE_NAME


def latest_published(plugin_root: Path, *, now: int | None = None) -> str | None:
    """Latest published release version, through the TTL cache. None when unknown
    (offline, no gh, TTL 0) — callers treat None as 'could not verify', never 'fresh'."""
    ttl = _ttl_s()
    if ttl <= 0:
        return None
    now = int(now if now is not None else time.time())
    name, _ = _derive_identity(plugin_root)
    key = name or str(plugin_root)
    cache: dict = {}
    try:
        cache = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(key)
    if isinstance(hit, dict) and (now - int(hit.get("checked", 0))) < ttl:
        v = hit.get("latest")
        return str(v) if v else None
    latest = version_update_lib.resolve_latest_published(Path(plugin_root))  # network (gh), fail-open None
    cache[key] = {"latest": latest, "checked": now}
    try:
        global_state.init_global_state()
        state.atomic_write(_cache_path(), json.dumps(cache))
    except OSError:
        pass  # cache write failure must never fail the audit
    return latest


def freshness(plugin_root: Path, *, now: int | None = None) -> dict:
    """The audit-header facts: what is being audited vs what is installed/published.

    `is_stale` is True only on POSITIVE divergence evidence: the audited tree's version
    differs from the installed pin, or from the latest published release. Unknown
    comparators (None) never mark stale — fail-open, the header just says 'unknown'."""
    root = Path(plugin_root)
    cached = cached_version(root)
    name, marketplace = _derive_identity(root)
    pin = installed_pin(name, marketplace)
    latest = latest_published(root, now=now)
    is_stale = bool(cached) and ((bool(pin) and pin != cached) or (bool(latest) and latest != cached))
    return {
        "plugin": name,
        "cached_version": cached,
        "installed_pin": pin,
        "latest_published": latest,
        "is_stale": is_stale,
    }


def header(plugin_root: Path, *, now: int | None = None) -> str:
    """The one-line report header every cache-based audit prints first."""
    f = freshness(plugin_root, now=now)
    line = (
        f"audited {f['plugin'] or Path(plugin_root).name}@{f['cached_version'] or 'unknown'} "
        f"(pin {f['installed_pin'] or 'unknown'}; latest {f['latest_published'] or 'unknown'})"
    )
    if f["is_stale"]:
        line += (
            " ⚠ STALE — the audited cache diverges from the installed/published version; "
            "findings may describe outdated code. Update/reload before acting on them."
        )
    return line


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: plugin_freshness.py <plugin_root>", file=sys.stderr)
        raise SystemExit(2)
    print(header(Path(sys.argv[1])))
    raise SystemExit(0)
