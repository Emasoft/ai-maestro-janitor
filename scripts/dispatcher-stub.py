#!/usr/bin/env python3
"""ai-maestro-janitor cron dispatcher stub — auto-rolling dispatcher.

Installed by /janitor-arm into `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`,
a path that lives OUTSIDE the version-stamped plugin cache directory.

`${CLAUDE_PLUGIN_DATA}` resolves to `~/.claude/plugins/data/<id>/` —
a persistent directory that survives every plugin update and is only
cleaned up when the plugin is uninstalled from the last scope. The cron
prompt baked at /janitor-arm time points at THIS stub, not at any
versioned `dispatch.py`. The stub re-resolves "latest cached version"
on every fire and `os.execv`'s into it, so:

  - Plugin updates land in the cache → the next heartbeat picks them up.
  - Cache GC of any old version (CC removes orphaned versions ~7 days
    after update) is harmless: we always pick the current latest.
  - Re-arming is needed ONCE (on the upgrade to a stub-aware janitor
    version); after that, future bumps roll forward automatically.

Survival contract: this stub is fire-and-forget — zero arguments, no
state. As long as future `dispatch.py` versions stay zero-arg, the stub
never needs updating. If we ever break the contract, we accept that
users have to re-run /janitor-arm; the worst-case is the same as the
pre-stub world we're moving away from.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PLUGIN_CACHE_ROOT = (
    Path.home() / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor"
)


def _version_key(d: Path) -> tuple[int, ...]:
    """Sort key for semver-style directory names. Non-numeric components
    sort lowest so they never out-rank a real version."""
    try:
        return tuple(int(p) for p in d.name.split("."))
    except ValueError:
        return (-1,)


def main() -> int:
    if not PLUGIN_CACHE_ROOT.is_dir():
        sys.exit(f"ai-maestro-janitor cache root missing: {PLUGIN_CACHE_ROOT}")
    versions = sorted(
        (p for p in PLUGIN_CACHE_ROOT.iterdir() if p.is_dir()),
        key=_version_key,
    )
    if not versions:
        sys.exit("no ai-maestro-janitor versions cached")
    target = versions[-1] / "scripts" / "dispatch.py"
    if not target.is_file():
        sys.exit(f"dispatch.py missing in latest cached version: {target}")
    os.execv(str(target), [str(target), *sys.argv[1:]])


if __name__ == "__main__":
    main()
