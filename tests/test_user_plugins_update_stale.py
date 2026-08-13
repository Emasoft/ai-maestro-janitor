"""Regression test: user-plugins-update shares the FIXED daemon-stale watchdog.

The sibling of marketplace-refresh had the IDENTICAL issue-#9 flaw (a
`2 * cadence` threshold + "daemon may be stuck" + a phantom
~/.claude/janitor-global-state/daemon.log) and was NOT fixed in round 1 — the
exact "fix one copy, forget the other" drift that motivated extracting one
shared `daemon_watchdog.emit_if_daemon_stale`. This pins that the
user-plugins-update call produces the corrected behavior: an alive daemon is
never flagged, and a dead daemon yields a "not responding / self-heal" line
tagged for this task (never "daemon may be stuck").
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Mirror of the helper's threshold inputs for the user-plugins cadence (3600 s).
_CADENCE_S = 3600
_MAX_TASK_RUNTIME_S = 1800
_THRESHOLD_S = _CADENCE_S + _MAX_TASK_RUNTIME_S + _CADENCE_S  # 9000 s / 150 min


def _run_helper(gsd: Path, project_dir: Path) -> str:
    """Invoke daemon_watchdog.emit_if_daemon_stale with the user-plugins-update
    parameters in an isolated child process and capture its stdout."""
    script = (
        "import os, sys, io\n"
        "sys.path.insert(0, %r)\n"
        "os.environ['CLAUDE_PROJECT_DIR'] = %r\n"
        "import state, daemon_watchdog\n"
        "state.init_state()\n"
        "buf = io.StringIO(); orig = sys.stdout; sys.stdout = buf\n"
        "try:\n"
        "    daemon_watchdog.emit_if_daemon_stale(\n"
        "        task_name='user-plugins-update',\n"
        "        last_run_filename='user-plugins-update.last-run.ts',\n"
        "        cadence_env='CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL',\n"
        "        default_cadence_s=3600,\n"
        "        subject='user-scope plugins last swept',\n"
        "    )\n"
        "finally:\n"
        "    sys.stdout = orig\n"
        "print('CAPTURED:' + buf.getvalue(), end='')\n"
    ) % (str(_PROJECT_ROOT / "scripts" / "lib"), str(project_dir))
    env = os.environ.copy()
    env["JANITOR_GLOBAL_STATE_DIR"] = str(gsd)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    proc = subprocess.run(
        [sys.executable, "-c", script], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    idx = proc.stdout.find("CAPTURED:")
    return proc.stdout[idx + len("CAPTURED:"):] if idx >= 0 else ""


def _seed_age(gsd: Path, age_s: int) -> None:
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / "user-plugins-update.last-run.ts").write_text(
        str(int(time.time()) - age_s), encoding="utf-8",
    )


def _seed_alive(gsd: Path) -> None:
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / "daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text(str(int(time.time())), encoding="utf-8")


def _seed_dead(gsd: Path) -> None:
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / "daemon.pid").write_text("999999", encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text(
        str(int(time.time()) - 7200), encoding="utf-8",
    )


def test_alive_daemon_silent_even_when_sweep_very_stale(tmp_path: Path) -> None:
    """The regression: a heartbeat-fresh daemon is never flagged, even when the
    user-plugins sweep stamp is far past the threshold."""
    gsd = tmp_path / "gs"
    _seed_age(gsd, _THRESHOLD_S + 3600)
    _seed_alive(gsd)
    out = _run_helper(gsd, tmp_path)
    assert out == "", f"alive daemon must be silent, got: {out!r}"


def test_dead_daemon_emits_user_plugins_not_responding(tmp_path: Path) -> None:
    gsd = tmp_path / "gs"
    _seed_age(gsd, _THRESHOLD_S + 600)
    _seed_dead(gsd)
    out = _run_helper(gsd, tmp_path)
    assert "[user-plugins-update]" in out
    assert "user-scope plugins last swept" in out
    assert "not responding" in out
    # Never the misleading round-1 wording, and never "kill the daemon".
    assert "daemon may be stuck" not in out
    assert "self-heal" in out.lower() or "respawn" in out.lower()


def test_below_threshold_silent_even_if_dead(tmp_path: Path) -> None:
    gsd = tmp_path / "gs"
    _seed_age(gsd, _THRESHOLD_S - 600)
    _seed_dead(gsd)
    out = _run_helper(gsd, tmp_path)
    assert out == "", f"below-threshold staleness must be silent, got: {out!r}"


# --- the failing-but-running blind spot (TRDD-3GF9PSQB) ---------------------------
#
# The daemon stamps `<task>.last-run.ts` in its `finally`, BEFORE the failure branch, so a
# task that fails every run keeps a PERPETUALLY FRESH stamp. Combined with the alive-daemon
# gate (a failing task's daemon is alive by definition) that made the loudest possible
# failure produce the quietest possible signal.

_QUARANTINE_AFTER_FAILS = 3  # mirrors global_state.QUARANTINE_AFTER_FAILS


def _seed_fails(gsd: Path, fails: int) -> None:
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / "user-plugins-update.failcount").write_text(str(fails), encoding="utf-8")


def test_failing_task_is_reported_despite_a_fresh_stamp_and_live_daemon(tmp_path: Path) -> None:
    """THE blind spot. Exactly the state a permanently-failing task produces: the stamp is
    FRESH (it is written on failure too) and the daemon is ALIVE (it is running the task and
    the task is erroring). Both existing gates therefore return early, and before this fix
    NOTHING reported it — the more reliably the task failed, the healthier it looked."""
    gsd = tmp_path / "gs"
    _seed_age(gsd, 0)                      # stamped seconds ago — by a FAILED run
    _seed_alive(gsd)                       # daemon is fine; the TASK is not
    _seed_fails(gsd, _QUARANTINE_AFTER_FAILS)
    out = _run_helper(gsd, tmp_path)
    assert "[user-plugins-update]" in out, f"a task failing every run must be reported: {out!r}"
    assert "FAILED" in out
    assert str(_QUARANTINE_AFTER_FAILS) in out
    # It must NOT be dressed up as the daemon being dead — the daemon is healthy here, and
    # sending the reader to look at the daemon would waste the one thing they have least of.
    assert "not responding" not in out


def test_healthy_task_with_a_fresh_stamp_stays_silent(tmp_path: Path) -> None:
    """No new noise: the overwhelmingly common state (zero failures, fresh stamp, live
    daemon) must remain completely silent. A watchdog that chirps on healthy tasks gets
    ignored, which would cost more than the blind spot it fixes."""
    gsd = tmp_path / "gs"
    _seed_age(gsd, 0)
    _seed_alive(gsd)
    _seed_fails(gsd, 0)
    assert _run_helper(gsd, tmp_path) == ""


def test_a_transient_failure_streak_below_quarantine_is_silent(tmp_path: Path) -> None:
    """One or two failures are a blip the daemon retries on its normal cadence; only at the
    threshold where the DAEMON ITSELF gives up (starts exponential backoff) does a human need
    to hear about it. Reusing the daemon's own constant is what keeps 'unhealthy' one
    definition instead of two."""
    gsd = tmp_path / "gs"
    _seed_age(gsd, 0)
    _seed_alive(gsd)
    _seed_fails(gsd, _QUARANTINE_AFTER_FAILS - 1)
    assert _run_helper(gsd, tmp_path) == ""


def test_failing_line_is_said_once_per_streak_and_again_when_it_worsens(tmp_path: Path) -> None:
    """A task stuck at the same failure count is ONE standing fact, not hourly news — so the
    dedupe key is the streak, not the hour. A worsening streak is new information and speaks
    again."""
    gsd = tmp_path / "gs"
    _seed_age(gsd, 0)
    _seed_alive(gsd)
    _seed_fails(gsd, _QUARANTINE_AFTER_FAILS)
    assert "[user-plugins-update]" in _run_helper(gsd, tmp_path)
    assert _run_helper(gsd, tmp_path) == "", "same streak must not re-nag"
    _seed_fails(gsd, _QUARANTINE_AFTER_FAILS + 1)
    assert "[user-plugins-update]" in _run_helper(gsd, tmp_path), "a worsening streak is news"
