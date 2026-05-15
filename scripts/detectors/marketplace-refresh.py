#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Marketplace-refresh detector — bulk-refresh every Claude Code marketplace.

Spawns `claude plugin marketplace update` (no arguments) DETACHED in the
background and returns immediately. The bare bulk form refreshes every
configured marketplace in one CLI call; on the developer's setup that's
already 277+ marketplaces and takes minutes per pass, so blocking the
heartbeat on it would defeat the heartbeat itself.

Design:
  - On fire, read `.janitor/state/marketplace-refresh.pid`. If the recorded
    PID is still alive, a prior refresh is still in flight — log and skip
    (no concurrent fetches; git index locking would clobber them anyway).
  - Otherwise spawn the CLI with `start_new_session=True` so the child
    survives the detector's exit, write its PID, and return 0 immediately.
    Stdout/stderr stream to .janitor/logs/marketplace-refresh.log so the
    full refresh history is auditable; the detector itself stays silent.
  - The PID file is never explicitly cleaned up. A stale PID (process
    long-gone) is correctly detected as "not alive" on the next fire via
    `os.kill(pid, 0)` + ESRCH, so the next fire spawns a fresh refresh.

Why this is a separate detector from plugin-updates:
  - plugin-updates iterates `claude plugin marketplace update <name>` per
    marketplace that has at least one currently-installed project/local-scope
    plugin. The bare bulk form covers EVERYTHING — including marketplaces
    of plugins installed at user/managed scope, and marketplaces whose
    plugins are not yet installed locally but might be soon.
  - Decoupling lets plugin-updates eventually drop its per-marketplace
    refresh loop without losing freshness guarantees.

Output:
  Silent on success. Logs every spawn/skip to
  .janitor/logs/marketplace-refresh.log. Never emits drift lines —
  pure background maintenance.
"""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402

PID_FILENAME = "marketplace-refresh.pid"


def _read_pid(pid_path: Path) -> int | None:
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    """True iff a process with this PID is currently alive AND owned by us.
    Uses signal 0 (no-op) — ESRCH = gone, EPERM = exists but owned by
    someone else (treat as 'not ours', so we can spawn a new one)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return False
        return False
    return True


def _write_pid_atomic(pid_path: Path, pid: int) -> None:
    tmp = pid_path.with_suffix(pid_path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(str(pid), encoding="utf-8")
    os.replace(tmp, pid_path)


def main() -> int:
    state.init_state()
    log_path = state.log_dir() / "marketplace-refresh.log"
    pid_path = state.state_dir() / PID_FILENAME

    if shutil.which("claude") is None:
        state.log_line("marketplace-refresh", "claude CLI not in PATH — skipping")
        return 0

    prior_pid = _read_pid(pid_path)
    if prior_pid is not None and _pid_alive(prior_pid):
        state.log_line(
            "marketplace-refresh",
            f"prior refresh still running (pid {prior_pid}) — skipping",
        )
        return 0

    state.log_line("marketplace-refresh", "spawning bulk marketplace refresh (detached)")
    try:
        # Open the log file in append mode; the child inherits the descriptor
        # and writes its full output there. We close our own copy after
        # spawning so we don't keep a stale fd open.
        logf = log_path.open("a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                ["claude", "plugin", "marketplace", "update"],
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # detach from this process group
            )
        finally:
            logf.close()
    except OSError as exc:
        state.log_line("marketplace-refresh", f"spawn failed: {exc}")
        return 0

    try:
        _write_pid_atomic(pid_path, proc.pid)
    except OSError as exc:
        state.log_line("marketplace-refresh", f"pid-file write failed: {exc}")
        # Process is already running; the next fire will just spawn another
        # if the PID file is unreadable. Not fatal.

    state.log_line(
        "marketplace-refresh",
        f"spawned bulk refresh (pid {proc.pid}) — will run async",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
