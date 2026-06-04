# Shared daemon-task staleness watchdog for the per-session detector shims.
#
# Both marketplace-refresh and user-plugins-update are owned by the global
# daemon (issue #7). Their per-session shims must surface a drift line ONLY
# when a daemon task is genuinely not progressing AND the daemon is not
# responding — never when a heartbeat-fresh daemon is merely mid-run or briefly
# behind. That false positive (issue #9) is exactly what spammed every session:
# `<task>.last-run.ts` is stamped at COMPLETION, so it ages by the full run
# duration while a legitimate long task is in flight; a real 27-min bulk
# marketplace refresh aged the stamp past the old `2 * cadence` threshold while
# the daemon was perfectly healthy, and the code then read a fresh heartbeat and
# cried "daemon stuck — kill it".
#
# This is the ONE implementation both shims call, so they cannot drift apart —
# they did exactly that (marketplace-refresh was fixed, user-plugins-update kept
# crying "daemon may be stuck"), which is the structural bug this module closes.

from __future__ import annotations

import os
import time

import dedupe
import global_state as gs
import state

# A single daemon workload subprocess is capped at this many seconds
# (daemon.py::_WORKLOAD_TIMEOUT_SEC). A task's completion stamp legitimately
# ages by up to `cadence + this` before the next stamp lands, so the stale
# threshold must exceed that sum or a slow-but-successful run false-alarms.
# Keep in lock-step with daemon.py's cap if it changes.
MAX_TASK_RUNTIME_S = 1800


def emit_if_daemon_stale(
    *,
    task_name: str,
    last_run_filename: str,
    cadence_env: str,
    default_cadence_s: int,
    subject: str,
) -> None:
    """Print a once/hour drift line iff `task_name`'s completion stamp is stale
    past a generous threshold AND the daemon is not alive (dead PID / frozen
    heartbeat).

    SILENT otherwise — and crucially ALWAYS silent while the daemon heartbeat is
    fresh, because the heartbeat (ticked every ≤60 s, and every 10 s during a
    workload) is the real liveness oracle: a fresh heartbeat ⇒ the daemon is
    provably looping ⇒ it is either mid-run or about to start the overdue run ⇒
    self-healing ⇒ nothing for the user to do.

    Args:
      task_name:         drift-line tag + seen-file stem, e.g. "marketplace-refresh".
      last_run_filename: the daemon's completion stamp in the global state dir.
      cadence_env:       env var holding the task's cadence in seconds.
      default_cadence_s: fallback cadence when the env var is unset/invalid.
      subject:           human phrase for what has not happened, e.g.
                         "global marketplaces last refreshed".
    """
    last_run_path = gs.global_state_dir() / last_run_filename
    last_run = state.read_int_state(last_run_path, 0)
    if last_run <= 0:
        # Never completed once — daemon just started or task has not finished
        # yet. The stamp is written unconditionally in Task.run's finally, so a
        # zero genuinely means "no completion yet", not "failing silently".
        return

    cadence = state.coerce_int(os.environ.get(cadence_env), default_cadence_s)
    # Generous: a healthy completion stamp can age up to `cadence` (wait until
    # due) + one max-length run before the next stamp lands. Add a cadence of
    # margin so a single slow-but-successful run never trips it.
    stale_threshold = cadence + MAX_TASK_RUNTIME_S + cadence
    age = int(time.time()) - last_run
    if age <= stale_threshold:
        return

    # The gate that kills the issue-#9 false positive: a heartbeat-fresh daemon
    # is never the subject of a stuck-alarm, no matter how stale the completion
    # stamp is.
    if gs.daemon_is_alive():
        return

    # Daemon is genuinely dead or frozen. ensure_daemon_running() ran earlier
    # this heartbeat (every shim calls it before us) and will have attempted a
    # respawn, so the user usually needs to do nothing — we surface it once/hour
    # so a *persistently* un-respawnable daemon doesn't hide silently.
    now = int(time.time())
    pid = gs.daemon_pid()
    hb_ts = gs.read_heartbeat()
    hb_age = (now - hb_ts) if hb_ts > 0 else None

    msg = (
        f"[{task_name}] {subject} ~{age // 60} min ago (cadence {cadence}s) "
        f"and the daemon is not responding"
    )
    if pid is None:
        msg += " (no daemon PID on record)"
    elif hb_age is not None:
        msg += f" (PID {pid}, heartbeat {hb_age}s stale)"
    else:
        msg += f" (PID {pid}, no heartbeat on record)"
    msg += ". A respawn was triggered this heartbeat — it should self-heal."

    # Reference the daemon log only when it actually exists. The daemon pins its
    # log to the global-state dir (daemon.py main() sets JANITOR_LOG_DIR), so
    # this path is real once a fixed daemon has run; an old daemon that logged
    # into a project tree leaves no file here and the line is correctly omitted
    # (no phantom path — issue #9).
    log_path = gs.global_state_dir() / "daemon.log"
    if log_path.is_file():
        msg += f" Inspect: {log_path}."

    seen = state.state_dir() / f"{task_name}-stale-seen.txt"
    key = f"stale@{int(time.time() // 3600)}"
    out = dedupe.emit_once(seen, key, msg)
    if out is not None:
        print(out)
