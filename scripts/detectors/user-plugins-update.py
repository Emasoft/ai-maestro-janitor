#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""User-plugins-update detector — Track 1 of the auto-update directive.

Updates ALL user-scope plugins every heartbeat. User-scope plugins live in
~/.claude/ and affect every Claude session on this machine — keeping them
fresh is project-agnostic background maintenance.

Behaviour:
  - Enumerates `claude plugin list --json` and filters to scope == 'user'.
  - For each plugin, runs `claude plugin update <id> --scope user` (cheap,
    idempotent — the CLI no-ops when versions already match).
  - Updates ALL user-scope plugins, enabled or disabled (per the
    user-scope clause of the auto-update directive: keep every user-level
    plugin fresh so re-enabling a disabled plugin uses the latest cache).

Architecture:
  - Detector returns in <100ms by SPAWNING a detached worker process
    (`--worker` mode) and exiting. The worker iterates the plugin list
    sequentially in the background. PID tracked in
    .janitor/state/user-plugins-update.pid; successive heartbeats that
    find the prior worker alive log a skip and exit immediately.
  - 121 plugins x ~750ms/CLI-no-op = ~90s per full sweep on a typical
    setup, well under the heartbeat interval. The detached pattern keeps
    dispatch.py's per-heartbeat budget tight (the other detectors run
    on the same heartbeat and shouldn't be blocked by this one).

Output:
  Silent on stdout. Logs every spawn/skip to
  .janitor/logs/user-plugins-update.log. Never emits drift lines —
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

PID_FILENAME = "user-plugins-update.pid"


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
    """signal 0 = no-op; ESRCH (gone) and EPERM (not ours) both treated
    as 'not our running worker'."""
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


def _list_user_plugins() -> list[str]:
    """Return list of plugin IDs (`<name>@<marketplace>`) at user scope."""
    try:
        proc = subprocess.run(
            ["claude", "plugin", "list", "--json"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        state.log_line("user-plugins-update", "claude plugin list --json failed — skipping")
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        state.log_line("user-plugins-update", "claude plugin list --json returned empty — skipping")
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        state.log_line("user-plugins-update", "claude plugin list --json non-JSON — skipping")
        return []
    if not isinstance(data, list):
        return []
    result: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("scope") != "user":
            continue
        plugin_id = entry.get("id")
        if isinstance(plugin_id, str) and plugin_id:
            result.append(plugin_id)
    return result


def _run_worker() -> int:
    """Detached worker: iterate user-scope plugins and update each."""
    state.init_state()
    log_path = state.log_dir() / "user-plugins-update.log"

    plugin_ids = _list_user_plugins()
    if not plugin_ids:
        state.log_line("user-plugins-update", "[worker] no user-scope plugins found")
        return 0

    state.log_line(
        "user-plugins-update",
        f"[worker] updating {len(plugin_ids)} user-scope plugin(s) sequentially",
    )

    succeeded = 0
    for plugin_id in plugin_ids:
        try:
            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(f"--- {plugin_id} ---\n")
                proc = subprocess.run(
                    ["claude", "plugin", "update", plugin_id, "--scope", "user"],
                    stdout=logf, stderr=subprocess.STDOUT,
                    timeout=120, check=False,
                )
            if proc.returncode == 0:
                succeeded += 1
        except subprocess.TimeoutExpired:
            state.log_line("user-plugins-update", f"[worker] update timed out: {plugin_id}")
        except OSError as exc:
            state.log_line("user-plugins-update", f"[worker] update failed: {plugin_id} ({exc})")

    state.log_line(
        "user-plugins-update",
        f"[worker] completed: {succeeded}/{len(plugin_ids)} CLI calls succeeded "
        "(no-ops counted as success)",
    )
    return 0


def main() -> int:
    # Worker mode: detached child does the actual loop.
    if "--worker" in sys.argv[1:]:
        return _run_worker()

    state.init_state()
    log_path = state.log_dir() / "user-plugins-update.log"
    pid_path = state.state_dir() / PID_FILENAME

    if shutil.which("claude") is None:
        state.log_line("user-plugins-update", "claude CLI not in PATH — skipping")
        return 0

    prior_pid = _read_pid(pid_path)
    if prior_pid is not None and _pid_alive(prior_pid):
        state.log_line(
            "user-plugins-update",
            f"prior worker still running (pid {prior_pid}) — skipping",
        )
        return 0

    state.log_line("user-plugins-update", "spawning detached worker")
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
        state.log_line("user-plugins-update", f"spawn failed: {exc}")
        return 0

    try:
        _write_pid_atomic(pid_path, proc.pid)
    except OSError as exc:
        state.log_line("user-plugins-update", f"pid-file write failed: {exc}")

    state.log_line(
        "user-plugins-update",
        f"spawned worker (pid {proc.pid}) — will run async",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
