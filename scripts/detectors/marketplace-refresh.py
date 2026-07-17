#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Per-session marketplace refresh — scoped to local + project plugin marketplaces.

Two responsibilities, both narrow:

  1. Active refresh of the marketplaces hosting plugins enabled in THIS
     project's `<project>/.claude/settings.json` (project scope) and
     `<project>/.claude/settings.local.json` (local scope). Global /
     user-scope marketplaces are owned by the central daemon
     (`daemon_marketplace_refresh_interval`, default 20 min). Keeping
     the per-session detector narrow means N concurrent Claude Code
     sessions across N projects do NOT pile up overlapping bulk
     `claude plugin marketplace update` runs — the very bug GitHub
     issue #7 documents. Each per-session fire only refreshes the few
     marketplaces THIS project's plugins are pulled from.

  2. Daemon-staleness watchdog — surfaces a drift line when the
     daemon's last successful bulk refresh is older than 2× its
     configured cadence. A wedged daemon shouldn't go unnoticed just
     because per-session work is still making progress.

Architecture: detached-worker pattern (same shape as user-plugins-update,
local-plugins-update, project-plugins-update). PID tracked in
`.janitor/state/marketplace-refresh.pid`; successive heartbeats that
find the prior worker still alive skip cleanly so a slow refresh
doesn't pile up.

Output:
  Silent on stdout normally. ONE drift line per hour while the daemon
  refresh is stale. Per-marketplace CLI output and the spawn/skip
  decisions land in `.janitor/logs/marketplace-refresh.log`.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import daemon_watchdog  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402

_NAME = "marketplace-refresh"
PID_FILENAME = "marketplace-refresh.pid"


# --- PID helpers (same shape as the other detached-worker detectors) -----

def _read_pid(pid_path: Path) -> int | None:
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        # ESRCH = no such process. EPERM = a process with that PID exists
        # but we don't own it — which for a per-session detector means the
        # PID was recycled to a stranger after our previous worker exited;
        # treat it as "not our worker" so we don't wedge waiting for an
        # unrelated process to finish. Matches the sibling detectors
        # (local-plugins-update, project-plugins-update).
        if exc.errno in (errno.ESRCH, errno.EPERM):
            return False
        return False
    return True


def _write_pid_atomic(pid_path: Path, pid: int) -> None:
    tmp = pid_path.with_suffix(pid_path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(str(pid), encoding="utf-8")
    os.replace(tmp, pid_path)


# --- enabled-plugin / marketplace discovery -------------------------------

def _enabled_plugins(settings_path: Path, label: str) -> list[str]:
    """Return enabled `name@marketplace` plugin IDs from a settings file.

    Silent on missing — many projects only have one of the two files.
    Logs malformed JSON so the user can fix it but does NOT abort the
    detector (the rest of the heartbeat should still run).
    """
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        state.log_line(_NAME, f"{label} read failed: {exc}")
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        state.log_line(_NAME, f"{label} malformed JSON ({exc}) — skipping")
        return []
    if not isinstance(data, dict):
        return []
    enabled = data.get("enabledPlugins")
    if not isinstance(enabled, dict):
        return []
    out: list[str] = []
    for plugin_id, flag in enabled.items():
        if isinstance(plugin_id, str) and plugin_id and flag is True:
            out.append(plugin_id)
    return out


def _marketplaces_from_plugin_ids(plugin_ids: list[str]) -> list[str]:
    """Extract unique marketplace names from `name@marketplace` plugin IDs.

    Preserves first-seen order so the log line is deterministic across
    runs for easier human eyeballing. IDs without `@` are silently
    ignored (Claude Code requires the suffix; a bare ID is malformed).
    """
    seen: set[str] = set()
    out: list[str] = []
    for pid in plugin_ids:
        if "@" not in pid:
            continue
        market = pid.rsplit("@", 1)[1].strip()
        if market and market not in seen:
            seen.add(market)
            out.append(market)
    return out


def _scoped_marketplaces(project_root: Path) -> list[str]:
    """Unique marketplaces hosting plugins enabled at local+project scope."""
    settings_local = project_root / ".claude" / "settings.local.json"
    settings_proj = project_root / ".claude" / "settings.json"
    plugin_ids = (
        _enabled_plugins(settings_local, "settings.local.json")
        + _enabled_plugins(settings_proj, "settings.json")
    )
    return _marketplaces_from_plugin_ids(plugin_ids)


# --- detached worker ------------------------------------------------------

def _run_worker() -> int:
    """Refresh each scoped marketplace sequentially via the claude CLI."""
    state.init_state()
    log_path = state.log_dir() / "marketplace-refresh.log"
    project_root = state.project_root()
    markets = _scoped_marketplaces(project_root)
    if not markets:
        state.log_line(
            _NAME,
            "[worker] no local/project marketplaces — nothing to refresh",
        )
        return 0
    with gs.marketplace_lock() as got:
        if not got:
            state.log_line(
                _NAME,
                "[worker] deferred — another marketplace op holds the lock; retry next cycle",
            )
            return 0
        state.log_line(
            _NAME,
            f"[worker] refreshing {len(markets)} local/project marketplace(s) sequentially: "
            f"{','.join(markets)}",
        )
        for market in markets:
            try:
                with log_path.open("a", encoding="utf-8") as logf:
                    logf.write(f"--- {market} ---\n")
                    subprocess.run(  # noqa: S603,S607 - explicit args, fixed command
                        ["claude", "plugin", "marketplace", "update", market],
                        stdout=logf, stderr=subprocess.STDOUT,
                        timeout=120, check=False,
                    )
            except subprocess.TimeoutExpired:
                state.log_line(_NAME, f"[worker] refresh timed out: {market}")
            except OSError as exc:
                state.log_line(_NAME, f"[worker] refresh failed: {market} ({exc})")
        state.log_line(_NAME, "[worker] completed")
    return 0


# --- daemon-staleness watchdog -------------------------------------------

def _emit_daemon_stale_drift_if_needed() -> None:
    """Surface a once/hour drift line when the daemon's global marketplace
    refresh is stale AND the daemon is not responding.

    Delegates to the shared `daemon_watchdog` so this shim and
    user-plugins-update share ONE implementation and cannot drift apart (they
    did: this one was fixed for issue #9 while the sibling kept crying "daemon
    may be stuck"). See daemon_watchdog for the heartbeat-gate rationale that
    eliminates the false positive a long-but-healthy refresh used to trigger.
    """
    daemon_watchdog.emit_if_daemon_stale(
        task_name=_NAME,
        last_run_filename="marketplace-refresh.last-run.ts",
        cadence_env="CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL",
        default_cadence_s=1200,
        subject="global marketplaces last refreshed",
    )


# --- main -----------------------------------------------------------------

def main() -> int:
    if "--worker" in sys.argv[1:]:
        return _run_worker()

    state.init_state()
    gs.ensure_daemon_running()

    if shutil.which("claude") is None:
        state.log_line(
            _NAME, "claude CLI not in PATH — skipping per-session refresh",
        )
        _emit_daemon_stale_drift_if_needed()
        state.rotate_log_if_big(_NAME)
        return 0

    # Nothing to refresh? Bail fast — most projects with only user-scope
    # plugins have empty local/project settings.
    markets = _scoped_marketplaces(state.project_root())
    if not markets:
        _emit_daemon_stale_drift_if_needed()
        state.rotate_log_if_big(_NAME)
        return 0

    log_path = state.log_dir() / "marketplace-refresh.log"
    pid_path = state.state_dir() / PID_FILENAME
    prior_pid = _read_pid(pid_path)
    if prior_pid is not None and _pid_alive(prior_pid):
        state.log_line(
            _NAME, f"prior worker still running (pid {prior_pid}) — skipping",
        )
        _emit_daemon_stale_drift_if_needed()
        state.rotate_log_if_big(_NAME)
        return 0

    state.log_line(
        _NAME, f"spawning detached worker for {len(markets)} marketplace(s)",
    )
    try:
        logf = log_path.open("a", encoding="utf-8")
        try:
            proc = subprocess.Popen(  # noqa: S603 - explicit argv list
                [str(Path(__file__).resolve()), "--worker"],
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                # detached_uv_env: the worker's `uv run --script` shebang must not
                # inherit this process's (possibly ephemeral) VIRTUAL_ENV — a dangling
                # one kills the worker before its first line (TRDD-UO93APWN).
                env=state.detached_uv_env(),
            )
        finally:
            logf.close()
    except OSError as exc:
        state.log_line(_NAME, f"spawn failed: {exc}")
        _emit_daemon_stale_drift_if_needed()
        state.rotate_log_if_big(_NAME)
        return 0

    try:
        _write_pid_atomic(pid_path, proc.pid)
    except OSError as exc:
        state.log_line(_NAME, f"pid-file write failed: {exc}")

    state.log_line(_NAME, f"spawned worker (pid {proc.pid}) — will run async")
    _emit_daemon_stale_drift_if_needed()
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
