#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Local-plugins-update detector — Track 2a of the auto-update directive.

Updates LOCAL-scope plugins enabled in `<project>/.claude/settings.local.json`
every heartbeat. Per-project, per-janitor: a janitor armed in project A keeps
project A's local-scope plugins fresh; project B's local plugins are not
touched.

Behaviour:
  - Reads `<project_root>/.claude/settings.local.json`. The file is
    GITIGNORED by Claude Code convention (settings.local.json = personal
    overrides), so no git-state mutation happens from this detector.
  - Filters `enabledPlugins` to entries with value == true (per the
    directive: "only those enabled locally").
  - For each enabled plugin, runs `claude plugin update <id> --scope local`.
    The CLI is idempotent — no-ops when versions already match.

Architecture: detached-worker pattern (same as user-plugins-update +
marketplace-refresh). The detector returns in <200ms after spawning the
worker; the worker iterates the enabled-plugin list sequentially. PID
tracked in `.janitor/state/local-plugins-update.pid`; successive
heartbeats that find the prior worker still alive skip and exit.

Edge cases:
  - settings.local.json missing → exit silently (no local plugins).
  - settings.local.json malformed → log error, exit (don't crash dispatch).
  - enabledPlugins missing or empty → exit silently.
  - Plugin in enabledPlugins but not actually installed at local scope →
    `claude plugin update --scope local` will emit an error; we log it
    and continue with the next plugin.

Output:
  Silent on stdout. Logs every spawn/skip + per-plugin CLI output to
  `.janitor/logs/local-plugins-update.log`. Never emits drift lines —
  pure background maintenance.
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

import state  # noqa: E402

PID_FILENAME = "local-plugins-update.pid"


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
        if exc.errno in (errno.ESRCH, errno.EPERM):
            return False
        return False
    return True


def _write_pid_atomic(pid_path: Path, pid: int) -> None:
    tmp = pid_path.with_suffix(pid_path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(str(pid), encoding="utf-8")
    os.replace(tmp, pid_path)


def _enabled_local_plugins(settings_path: Path) -> list[str]:
    """Return enabled plugin IDs from settings.local.json, or [] on any
    parse/missing error (silent — log and skip)."""
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        state.log_line("local-plugins-update", f"settings.local.json read failed: {exc}")
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        state.log_line(
            "local-plugins-update",
            f"settings.local.json malformed JSON ({exc}) — skipping",
        )
        return []
    if not isinstance(data, dict):
        return []
    enabled_plugins = data.get("enabledPlugins")
    if not isinstance(enabled_plugins, dict):
        return []
    result: list[str] = []
    for plugin_id, flag in enabled_plugins.items():
        if isinstance(plugin_id, str) and plugin_id and flag is True:
            result.append(plugin_id)
    return result


def _run_worker() -> int:
    """Detached worker: update each enabled local-scope plugin."""
    state.init_state()
    settings_path = state.project_root() / ".claude" / "settings.local.json"
    log_path = state.log_dir() / "local-plugins-update.log"

    plugin_ids = _enabled_local_plugins(settings_path)
    if not plugin_ids:
        state.log_line(
            "local-plugins-update",
            "[worker] no enabled local-scope plugins (settings.local.json missing or empty)",
        )
        return 0

    state.log_line(
        "local-plugins-update",
        f"[worker] updating {len(plugin_ids)} enabled local-scope plugin(s) sequentially",
    )

    succeeded = 0
    for plugin_id in plugin_ids:
        try:
            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(f"--- {plugin_id} ---\n")
                proc = subprocess.run(
                    ["claude", "plugin", "update", plugin_id, "--scope", "local"],
                    stdout=logf, stderr=subprocess.STDOUT,
                    timeout=120, check=False,
                )
            if proc.returncode == 0:
                succeeded += 1
        except subprocess.TimeoutExpired:
            state.log_line("local-plugins-update", f"[worker] update timed out: {plugin_id}")
        except OSError as exc:
            state.log_line("local-plugins-update", f"[worker] update failed: {plugin_id} ({exc})")

    state.log_line(
        "local-plugins-update",
        f"[worker] completed: {succeeded}/{len(plugin_ids)} CLI calls succeeded "
        "(no-ops counted as success)",
    )
    return 0


def main() -> int:
    if "--worker" in sys.argv[1:]:
        return _run_worker()

    state.init_state()
    log_path = state.log_dir() / "local-plugins-update.log"
    pid_path = state.state_dir() / PID_FILENAME
    settings_path = state.project_root() / ".claude" / "settings.local.json"

    if shutil.which("claude") is None:
        state.log_line("local-plugins-update", "claude CLI not in PATH — skipping")
        return 0

    # Bail fast when there's nothing to do — no settings file → no enabled
    # local plugins → no worker needed.
    if not settings_path.is_file():
        state.log_line(
            "local-plugins-update",
            "no .claude/settings.local.json — nothing to update",
        )
        return 0

    prior_pid = _read_pid(pid_path)
    if prior_pid is not None and _pid_alive(prior_pid):
        state.log_line(
            "local-plugins-update",
            f"prior worker still running (pid {prior_pid}) — skipping",
        )
        return 0

    state.log_line("local-plugins-update", "spawning detached worker")
    try:
        logf = log_path.open("a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [str(Path(__file__).resolve()), "--worker"],
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        finally:
            logf.close()
    except OSError as exc:
        state.log_line("local-plugins-update", f"spawn failed: {exc}")
        return 0

    try:
        _write_pid_atomic(pid_path, proc.pid)
    except OSError as exc:
        state.log_line("local-plugins-update", f"pid-file write failed: {exc}")

    state.log_line(
        "local-plugins-update",
        f"spawned worker (pid {proc.pid}) — will run async",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
