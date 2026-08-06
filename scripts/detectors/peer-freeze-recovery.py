#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""peer-freeze-recovery — freeze recovery for PEER sessions while the daemon is dark
(TRDD-KQ9WM4TZ, EHT of TRDD-5ZVS1DDP).

THE GAP: TRDD-5ZVS1DDP makes the janitor daemon EXIT while an ai-maestro server runs
(one daemon per host — the owner's unconditional ruling). Correct — but the daemon owned
`session-liveness`, the ONE chore that structurally cannot move to a per-repo cron: a
frozen session's own cron is exactly what stopped. Measured on this host 2026-08-02:
server up 3 days, daemon gone, standalone sessions with ZERO freeze recovery — silently.
ai-maestro#79 asked whether the server takes this over (2026-07-21); 12 days of silence
later this is the card's prescribed stopgap.

THE SHAPE: a session cannot recover ITSELF, but it CAN recover a PEER. Every armed
session's heartbeat runs this detector; whoever fires first in the window takes a
machine-wide flock and runs the daemon's OWN beat (`daemon.task_session_liveness`) over
the fleet MINUS its own project. Reuse is the point — the diagnosis ladder, the typing
gate, the per-instance cooldowns, the identity-stamped attempt budgets, the F3 audit and
the crash-loop alert all come along unchanged, and the budgets live in the SAME
global-state recovery dir the daemon uses, so ownership handing back to a respawned
daemon continues the same counters instead of restarting them.

WHY THIS DOES NOT RESURRECT A SECOND DAEMON (the corruption 5ZVS1DDP forbids): nothing
here is resident — it is a bounded one-shot under a non-blocking machine-wide flock plus
a last-run stamp, exactly the single-writer discipline of issue #7. It runs ONLY in the
window where BOTH owners are absent: daemon dead AND server alive. Daemon alive → its
beat owns recovery (this is a no-op). Server dead → the right fix is respawning the
daemon, and `ensure_daemon_running` on the ordinary heartbeat path already does that.

NOTE on the notify channel: `task_session_liveness`'s crash-loop alert routes through
lib/notify.py, documented DAEMON-ONLY. That rule's intent is single-writer (N sessions
must not stampede the human); inside this flock there IS exactly one writer and NO
daemon, so the spirit holds — the alert would otherwise be dark along with the recovery.

FULL mode only (`_NON_HARNESS_DETECTORS`): a harness agent's world is server-owned, and
the beat itself marks server-owned instances HANDS OFF regardless.

Opt-out: CLAUDE_PLUGIN_OPTION_PEER_RECOVERY_ENABLED=0. The beat's own knobs
(SESSION_LIVENESS_ENABLED / FLEET_RECOVERY_ENABLED / FLEET_HARD_RESTART_ENABLED) apply
unchanged inside it.
"""

from __future__ import annotations

import fcntl
import os
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))

import global_state as gs  # noqa: E402
import harness_backend  # noqa: E402
import state  # noqa: E402

_LOG = "peer-freeze-recovery"

# Machine-wide pacing: at most one beat per interval across ALL sessions. 600s sits
# between the daemon's own beat cadence and the freeze-detection staleness windows —
# a wedged session is found within minutes, and a quiet fleet costs one stat.
_INTERVAL_ENV = "CLAUDE_PLUGIN_OPTION_PEER_RECOVERY_INTERVAL_S"
_INTERVAL_DEFAULT = 600


def _interval_s() -> int:
    return state.coerce_int(
        os.environ.get(_INTERVAL_ENV), _INTERVAL_DEFAULT, detector_name=_LOG, var_name=_INTERVAL_ENV
    )


def _last_run_path() -> Path:
    # Machine-wide (global_state, not the project state dir): N sessions share ONE
    # pacing stamp, or every armed session would run its own fleet scan per interval.
    return gs.global_state_dir() / "peer-recovery.last-run.ts"


def _lock_path() -> Path:
    return gs.global_state_dir() / "peer-recovery.lock"


def run_once(now: int | None = None) -> str:
    """One gated beat. Returns a short outcome tag (for tests + the log line)."""
    now = int(now if now is not None else time.time())
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_PEER_RECOVERY_ENABLED", True):
        return "disabled"
    if harness_backend.is_harness_session():
        return "harness"  # belt-and-suspenders under the dispatch deny-list
    if gs.daemon_is_alive():
        return "daemon-owns-it"
    if not harness_backend.server_is_alive(now=now):
        # Both owners absent for some OTHER reason (crash loop, kill-switch…): the
        # ordinary heartbeat path's ensure_daemon_running() is the remedy — respawning
        # is the daemon's own guarded, crash-loop-bounded path, not ours to duplicate.
        return "no-server"

    gs.init_global_state()
    if now - state.read_int_state(_last_run_path(), 0) < _interval_s():
        return "paced"
    # Non-blocking singleton across sessions — a loser SKIPS (the winner covers the
    # window; both running would double-inject into the same wedged pane).
    try:
        fd = os.open(str(_lock_path()), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        state.log_line(_LOG, f"cannot open lock: {exc} — treating as held")
        return "lock-held"
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return "lock-held"
        # Stamp FIRST: even a beat that then fails paces the fleet — a crashing scan
        # re-run by every session every heartbeat would be its own outage.
        state.atomic_write(_last_run_path(), str(now))

        import daemon  # noqa: PLC0415 — the beat lives there; reuse, never reimplement
        import fleet_scan  # noqa: PLC0415 — heavy; imported only on the rare live path

        sweep_s = 3600 * state.coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_RATE_LIMIT_FLAG_MAX_AGE_HOURS"),
            24, detector_name=_LOG, var_name="CLAUDE_PLUGIN_OPTION_RATE_LIMIT_FLAG_MAX_AGE_HOURS",
        )
        try:
            fleet = fleet_scan.gather_fleet(now=now, sweep_stale_rate_limit_s=sweep_s)
        except Exception as exc:  # noqa: BLE001 — a scan error must never kill the heartbeat
            state.log_line(_LOG, f"fleet scan failed: {exc}")
            return "scan-failed"
        # NEVER recover our own session from inside it: self-recovery is the in-session
        # cron's own job (it is provably alive — it just ran this detector), and typing
        # into one's own pane mid-turn is the splice hazard TRDD-0BVF4K7E closed.
        me = str(state.project_root())
        peers = [i for i in fleet if i.project_root and i.project_root != me]
        if not peers:
            return "no-peers"
        try:
            daemon.task_session_liveness(peers)
        except Exception as exc:  # noqa: BLE001 — recovery must never take down the heartbeat
            state.log_line(_LOG, f"beat failed: {exc}")
            return "beat-failed"
        state.log_line(_LOG, f"ran the dark-window recovery beat over {len(peers)} peer(s)")
        return "ran"
    finally:
        try:
            os.close(fd)  # kernel releases the flock with the fd
        except OSError:
            pass


# The quiet-gate outcomes (`daemon-owns-it`, `no-server`, `paced`, `lock-held`, …) return
# with NO stamp and NO log line, so a healthy host is indistinguishable from a roster that
# never reaches this detector — the exact ambiguity that kept TRDD-KQ9WM4TZ unfalsifiable
# for days (the pacing stamp only advances on a gate-clean dark-window beat, and the
# daemon fix made those rare). This breadcrumb makes EVERY beat countable.
_OUTCOME_STAMP_MAX_AGE_S = 3600


def _outcome_path() -> Path:
    return gs.global_state_dir() / "peer-recovery.outcome"


def record_outcome(outcome: str, now: int) -> None:
    """Leave a `<epoch> <outcome>` trace of the LAST beat, quiet gates included.

    WRITE-AMPLIFICATION GUARD: every armed session runs this every heartbeat, so an
    unconditional write would churn global-state (the TRDD-ZNN0UK5K fseventsd
    sensitivity). Rewrite only when the outcome CHANGES or the trace is older than an
    hour — steady state costs one small write per hour machine-wide, while a dark
    window still flips the trace at the exact second it opens. Fail-open: a breadcrumb
    must never break the beat."""
    try:
        gs.init_global_state()
        p = _outcome_path()
        try:
            prev_ts, _, prev_outcome = p.read_text(encoding="utf-8").strip().partition(" ")
            if prev_outcome == outcome and (now - int(prev_ts)) < _OUTCOME_STAMP_MAX_AGE_S:
                return
        except (OSError, ValueError):
            pass  # absent or corrupt → write a fresh trace
        state.atomic_write(p, f"{now} {outcome}")
    except Exception:  # noqa: BLE001 — observability must never take down the detector
        pass


def main() -> int:
    state.init_state()
    outcome = run_once()
    record_outcome(outcome, int(time.time()))
    if outcome == "ran":
        # ONE drift line so the session (and its human) can see the guardian fired —
        # the whole card exists because this going dark was invisible.
        print("[peer-freeze-recovery] daemon dark (server owns the host) — ran the fleet "
              "freeze-recovery beat for peer sessions (see recovery audit / logs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
