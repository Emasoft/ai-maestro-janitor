#!/usr/bin/env python3
"""ai-maestro-janitor daemon launcher — the OS-keepalive auto-rolling stub.

Installed by the launchd-keepalive installer into the janitor's FIXED data dir
`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/daemon-launcher.py`
(the hard-coded path `launchd_keepalive._DATA_DIR` resolves — NOT `${CLAUDE_PLUGIN_DATA}`,
which is unreliable in a detached/launchd-spawned process). It lives OUTSIDE the
version-stamped plugin cache and survives every plugin update. The OS keepalive
(a macOS LaunchAgent with `KeepAlive`, or a Linux systemd `Restart=always` unit)
runs THIS launcher, not any versioned `daemon.py`.

Why a launcher and not the daemon directly: the cached `daemon.py` path is
ephemeral (`…/<version>/scripts/daemon.py` changes on every plugin update and is
GC'd ~7 days after). A LaunchAgent needs a STABLE program path. So the keepalive
runs this stable stub, which re-resolves "latest cached version" on every (re)start
and `os.execv`'s into its `daemon.py`. The process IMAGE becomes the daemon, so the
OS keepalive tracks the daemon PID directly — when the daemon exits (crash, a
SIGTERM from a plugin-version roll, or a clean shutdown) the keepalive respawns this
launcher, which picks up whatever version is now newest. Result: the daemon is both
immortal (respawned by the OS regardless of any Claude session) AND self-rolling
(always the latest code), with no re-install on a plugin bump.

The daemon's own singleton flock guarantees only ONE daemon runs even though it can
also be lazy-spawned by a session heartbeat — whichever acquires the flock wins; the
other exits immediately. So running this under the OS keepalive composes safely with
the existing `ensure_daemon_running()` spawn path.

Survival contract (identical to dispatcher-stub): zero arguments, no state. As long
as future `daemon.py` versions stay zero-arg, this stub never needs updating.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PLUGIN_CACHE_ROOT = (
    Path.home() / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor"
)
# Kept in sync with launchd_keepalive.LABEL. Duplicated here on PURPOSE: when the
# plugin cache is gone (uninstalled) this stub can no longer import that lib, yet it
# must still be able to remove its own OS keepalive — so the label lives here too.
_KEEPALIVE_LABEL = "com.ai-maestro-janitor.daemon"


def _self_uninstall_keepalive() -> None:
    """Remove our OWN OS keepalive when the plugin cache has vanished (the plugin was
    uninstalled). Without this the LaunchAgent / systemd unit would churn forever —
    KeepAlive respawns this launcher every ~30s, it finds no daemon, exits, repeat —
    leaving exactly the kind of orphaned background process the janitor exists to
    prevent. Self-contained + best-effort (the cache lib is gone; never raise)."""
    home = Path.home()
    plat = str(sys.platform)  # str() defeats pyright's single-platform Literal narrowing
    try:
        if plat == "darwin":
            subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
                ["launchctl", "bootout", f"gui/{os.getuid()}/{_KEEPALIVE_LABEL}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=15, check=False,
            )
            (home / "Library" / "LaunchAgents" / f"{_KEEPALIVE_LABEL}.plist").unlink(missing_ok=True)
        elif plat.startswith("linux"):
            subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
                ["systemctl", "--user", "disable", "--now", f"{_KEEPALIVE_LABEL}.service"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=15, check=False,
            )
            cfg = os.environ.get("XDG_CONFIG_HOME") or str(home / ".config")
            (Path(cfg) / "systemd" / "user" / f"{_KEEPALIVE_LABEL}.service").unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError):
        pass


def _version_key(d: Path) -> tuple[int, ...]:
    """Sort key for semver-style directory names. Non-numeric components sort
    lowest so they never out-rank a real version."""
    try:
        return tuple(int(p) for p in d.name.split("."))
    except ValueError:
        return (-1,)


def main() -> int:
    if not PLUGIN_CACHE_ROOT.is_dir():
        _self_uninstall_keepalive()  # plugin uninstalled → don't churn; remove the agent
        sys.exit(f"ai-maestro-janitor cache root missing: {PLUGIN_CACHE_ROOT}")
    versions = sorted(
        (p for p in PLUGIN_CACHE_ROOT.iterdir() if p.is_dir()),
        key=_version_key,
    )
    if not versions:
        _self_uninstall_keepalive()  # cache present but empty → same: remove the agent
        sys.exit("no ai-maestro-janitor versions cached")
    target = versions[-1] / "scripts" / "daemon.py"
    if not target.is_file():
        sys.exit(f"daemon.py missing in latest cached version: {target}")
    # Replace this process image with the daemon so the OS keepalive tracks the
    # daemon PID directly (no intermediate wrapper to confuse KeepAlive). We exec
    # under `sys.executable` (plain python3), NOT `uv run --script` — the LaunchAgent
    # needs a stable program path. This is safe ONLY because daemon.py is
    # dependency-free (stdlib + local modules); the guard test
    # `test_daemon_stays_dependency_free_for_the_python3_launcher_path` enforces that,
    # so a future PEP-723 dependency can't silently crash-loop this path. The
    # `--keepalive` flag tells the daemon it was launched by the OS service, so it
    # WAITS (blocking-polls) for the singleton flock instead of exiting when a
    # session-spawned daemon already holds it — that is what makes the OS keeper
    # patient (no exit→respawn churn) and lets it take over the instant the holder dies.
    os.execv(sys.executable, [sys.executable, str(target), "--keepalive", *sys.argv[1:]])


if __name__ == "__main__":
    main()
