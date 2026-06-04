"""Regression tests for GitHub issue #9 (two rounds).

Round 1 (commit c7c973a): the detector used to emit `daemon may be stuck` and
point at a non-existent `~/.claude/janitor-global-state/daemon.log` even when
the daemon process was alive.

Round 2 (this fix): c7c973a still cried wolf — with a FRESH daemon heartbeat it
said "worker wedged — kill the daemon", which fanned a false alarm across every
session whenever a single bulk refresh ran longer than one cadence. A real
1641 s (27 min) refresh tripped the old `2 * cadence` (40 min) threshold while
the daemon was healthy and working. The contract is now:

  1. A heartbeat-fresh daemon is NEVER the subject of a stuck-alarm — staleness
     of the COMPLETION stamp during a long-but-healthy run is self-healing, so
     the emitter stays SILENT.
  2. The threshold accounts for `cadence + one max-length run`, so a slow
     successful refresh can't trip it even before the heartbeat gate.
  3. The emitter speaks ONLY when the daemon is genuinely not responding
     (dead PID or frozen heartbeat), and then says "not responding /
     self-heal", never "daemon may be stuck".
  4. The `Inspect: <log>` line appears only when the daemon log actually
     exists (the daemon now pins it to the global-state dir).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "marketplace-refresh.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"

# Mirror of the detector's threshold inputs so seeds land on the right side of
# it. stale_threshold = cadence + _MAX_REFRESH_RUNTIME_S + cadence.
_CADENCE_S = 1200
_MAX_REFRESH_RUNTIME_S = 1800
_STALE_THRESHOLD_S = _CADENCE_S + _MAX_REFRESH_RUNTIME_S + _CADENCE_S  # 4200 s / 70 min


def _run_emitter(global_state_dir: Path, project_dir: Path) -> str:
    """Invoke the detector's daemon-stale emitter in a child Python process.

    We don't spawn the full detector via subprocess (it tries to run the
    `claude` CLI for the real refresh). Instead we import the function we care
    about and exercise it directly inside a Python -c block, inheriting an
    isolated JANITOR_GLOBAL_STATE_DIR so per-test state can't leak.
    """
    script = (
        "import os, sys, io\n"
        "sys.path.insert(0, %r)\n"
        "sys.path.insert(0, %r)\n"
        "os.environ['CLAUDE_PROJECT_DIR'] = %r\n"
        "import state, global_state as gs  # noqa\n"
        "state.init_state()\n"
        # Import the detector module via its filename — it has a hyphen.
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('mr', %r)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "buf = io.StringIO()\n"
        "orig = sys.stdout\n"
        "sys.stdout = buf\n"
        "try:\n"
        "    mod._emit_daemon_stale_drift_if_needed()\n"
        "finally:\n"
        "    sys.stdout = orig\n"
        "print('CAPTURED:' + buf.getvalue(), end='')\n"
    ) % (
        str(_PROJECT_ROOT / "scripts" / "lib"),
        str(_PROJECT_ROOT / "scripts"),
        str(project_dir),
        str(_DETECTOR),
    )
    env = os.environ.copy()
    env["JANITOR_GLOBAL_STATE_DIR"] = str(global_state_dir)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    proc = subprocess.run(
        [sys.executable, "-c", script], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    marker = "CAPTURED:"
    idx = proc.stdout.find(marker)
    return proc.stdout[idx + len(marker):] if idx >= 0 else ""


def _seed_refresh_age(gsd: Path, age_s: int) -> None:
    """Set marketplace-refresh.last-run.ts to `age_s` seconds ago."""
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / "marketplace-refresh.last-run.ts").write_text(
        str(int(time.time()) - age_s), encoding="utf-8",
    )


def _seed_alive_daemon(gsd: Path) -> int:
    """Drop a valid daemon.pid (this test's child process IS the daemon) and a
    fresh daemon.heartbeat.ts so daemon_is_alive() returns True."""
    gsd.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    (gsd / "daemon.pid").write_text(str(pid), encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text(
        str(int(time.time())), encoding="utf-8",
    )
    return pid


def _seed_dead_daemon(gsd: Path) -> int:
    """Drop a pid that does not exist + a stale heartbeat → not alive."""
    gsd.mkdir(parents=True, exist_ok=True)
    # PID 999999 is essentially guaranteed not to exist on a normal box.
    dead_pid = 999999
    (gsd / "daemon.pid").write_text(str(dead_pid), encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text(
        str(int(time.time()) - 7200), encoding="utf-8",  # 2 h stale
    )
    return dead_pid


# ---------- The core fix: an ALIVE daemon never produces an alarm ---------


def test_silent_when_daemon_alive_even_if_refresh_very_stale(tmp_path: Path) -> None:
    """The issue-#9-round-2 regression: refresh stamp well past the threshold
    but the daemon heartbeat is FRESH → SILENT. A healthy, looping daemon is
    never told it is stuck, no matter how stale the completion stamp is."""
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, _STALE_THRESHOLD_S + 3600)  # 1 h past the threshold
    _seed_alive_daemon(gsd)
    out = _run_emitter(gsd, tmp_path)
    assert out == "", f"expected silence for an alive daemon, got: {out!r}"


def test_silent_when_alive_even_if_log_exists(tmp_path: Path) -> None:
    """The alive gate is unconditional — even with a real daemon.log present
    and a wildly stale stamp, an alive daemon yields no output."""
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, _STALE_THRESHOLD_S + 3600)
    _seed_alive_daemon(gsd)
    (gsd / "daemon.log").write_text("log line\n", encoding="utf-8")
    out = _run_emitter(gsd, tmp_path)
    assert out == "", f"alive daemon must stay silent, got: {out!r}"


def test_incident_45min_gap_alive_is_silent(tmp_path: Path) -> None:
    """The exact incident: a ~45-min completion gap (the value that spammed
    every session under the old 40-min threshold) with a fresh heartbeat now
    produces nothing — both the threshold bump and the alive gate cover it."""
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, 45 * 60)  # 45 min — below the new 70-min threshold
    _seed_alive_daemon(gsd)
    out = _run_emitter(gsd, tmp_path)
    assert out == "", f"a 45-min gap on a live daemon must be silent, got: {out!r}"


# ---------- The actionable path: a genuinely dead daemon ------------------


def test_dead_daemon_past_threshold_says_not_responding(tmp_path: Path) -> None:
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, _STALE_THRESHOLD_S + 600)
    dead_pid = _seed_dead_daemon(gsd)
    out = _run_emitter(gsd, tmp_path)
    assert "[marketplace-refresh]" in out
    # Never the misleading round-1 wording.
    assert "daemon may be stuck" not in out
    assert "not responding" in out
    # The PID is surfaced so the user can verify with `ps` themselves.
    assert f"PID {dead_pid}" in out
    # Correct remediation framing: it self-heals via the respawn already
    # triggered this heartbeat — not "kill <pid>" (the PID isn't alive).
    assert "self-heal" in out.lower() or "respawn" in out.lower()
    assert f"kill {dead_pid}" not in out


def test_dead_daemon_no_inspect_line_when_log_absent(tmp_path: Path) -> None:
    """No dangling reference to a non-existent daemon.log (issue #9)."""
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, _STALE_THRESHOLD_S + 600)
    _seed_dead_daemon(gsd)
    out = _run_emitter(gsd, tmp_path)
    assert "daemon.log" not in out
    assert "Inspect:" not in out


def test_dead_daemon_inspect_line_when_log_exists(tmp_path: Path) -> None:
    """When a real daemon.log is present, the Inspect: line surfaces it."""
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, _STALE_THRESHOLD_S + 600)
    _seed_dead_daemon(gsd)
    (gsd / "daemon.log").write_text("log line\n", encoding="utf-8")
    out = _run_emitter(gsd, tmp_path)
    assert "Inspect:" in out
    assert "daemon.log" in out


# ---------- Below-threshold: silent regardless of liveness ----------------


def test_below_threshold_silent_even_if_dead(tmp_path: Path) -> None:
    """A refresh stale by less than the threshold does not alarm even when the
    daemon is dead — the auto-respawn gets one full healthy cycle to recover
    before we bother the user."""
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, _STALE_THRESHOLD_S - 600)  # just under the threshold
    _seed_dead_daemon(gsd)
    out = _run_emitter(gsd, tmp_path)
    assert out == "", f"below-threshold staleness must be silent, got: {out!r}"


def test_silent_when_worker_is_fresh(tmp_path: Path) -> None:
    """A recent last-run → no false-stale drift line."""
    gsd = tmp_path / "gs"
    _seed_refresh_age(gsd, 60)  # 60 s ago, well under any cadence
    _seed_alive_daemon(gsd)
    out = _run_emitter(gsd, tmp_path)
    assert out == ""


def test_silent_when_last_run_zero(tmp_path: Path) -> None:
    """Missing / zero last-run.ts → daemon just started or task never
    completed; treated as not-yet-stale, silent."""
    gsd = tmp_path / "gs"
    gsd.mkdir(parents=True, exist_ok=True)
    _seed_dead_daemon(gsd)  # even a dead daemon stays silent with no stamp
    out = _run_emitter(gsd, tmp_path)
    assert out == ""
