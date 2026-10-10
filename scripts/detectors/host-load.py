#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""host-load — warn when the 5-minute load average exceeds cores x multiplier (HOST-001).

An overloaded host (load far above the core count) makes every tool slow and hook
timeouts fire; the heartbeat should say so instead of letting each timeout look like a
separate bug. READ-ONLY, ALERT-ONLY. Fail-open: no `getloadavg`/`cpu_count` => silent.

Multiplier: CLAUDE_PLUGIN_OPTION_HOST_LOAD_MULTIPLIER (default 4).
Opt-out: CLAUDE_PLUGIN_OPTION_HOST_LOAD_ENABLED=false.
TEST SEAM: JANITOR_LOADAVG (5-min load) and JANITOR_CPU_COUNT, when set, replace the
real readings so a test is deterministic regardless of the host.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import daemon_runaway as dr  # noqa: E402
import dedupe  # noqa: E402
import state  # noqa: E402

_LOG = "host-load"


def _readings() -> tuple[float, int] | None:
    """(5-min load average, core count), or None when either cannot be read."""
    try:
        inj_load = os.environ.get("JANITOR_LOADAVG")
        load = float(inj_load) if inj_load is not None else os.getloadavg()[1]
        inj_cpu = os.environ.get("JANITOR_CPU_COUNT")
        cores = int(inj_cpu) if inj_cpu is not None else (os.cpu_count() or 0)
    except (OSError, AttributeError, ValueError):  # AttributeError: no getloadavg on Windows
        return None
    return (load, cores) if cores > 0 else None

def _log_top_cpu(load: float) -> None:
    """Record the 5 busiest processes in host-load.log; fail open, print nothing.

    WHY (TRDD-PYV26AYU): loads of 232 to 403 left no record of who caused them. Called
    only on the first fire of an overload episode, so one log line per episode. ps %cpu
    is a decaying average over up to a minute, not an instant reading. `comm` carries no
    arguments (a command line can hold secrets). Under a real overload the listing itself
    can time out (it did five times between 2026-10-03 and 2026-10-05 in the runaway
    detector); then nothing is recorded.
    """
    try:
        injected = os.environ.get("JANITOR_PS_SNAPSHOT")  # same seam as system-daemon-runaway
        if injected is not None:
            ps_text = injected
        else:
            proc = state.run_subprocess(["ps", "-axo", "pid,ppid,rss,%cpu,comm"], timeout=10.0, detector_name=_LOG)
            ps_text = proc.stdout if proc is not None and proc.returncode == 0 else ""
        rows = sorted(dr.parse_ps_rows(ps_text), key=lambda r: r.pcpu, reverse=True)[:5]
        if not rows:
            state.log_line(_LOG, "top-cpu: no process listing")
            return
        parts = [
            f"pid={r.pid} {state.sanitize_for_drift_line(os.path.basename(r.command))} "
            f"cpu={r.pcpu:.0f}% rss={r.rss_mb:.0f}MB"
            for r in rows
        ]
        state.log_line(_LOG, f"top-cpu at load {load:.0f}: " + "; ".join(parts))
    except Exception:  # noqa: BLE001 - fail open: the HOST-001 alert must still print
        pass


def main() -> int:
    state.init_state()
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_HOST_LOAD_ENABLED", True):
        return 0
    got = _readings()
    if got is None:
        return 0
    load, cores = got
    multiplier = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_HOST_LOAD_MULTIPLIER"), 4) or 4
    seen = state.state_dir() / "host-load-seen.txt"
    if load <= cores * multiplier:
        # Episode over: forget the dedupe key so the next overload re-alerts.
        dedupe.emit_forget(seen, "overloaded")
        return 0
    line = dedupe.emit_once(
        seen,
        "overloaded",
        f"[host-load] HOST-001 load average {load:.0f} on {cores} cores ({load / cores:.0f}x) — "
        "the host is overloaded; slow tools and hook timeouts follow",
    )
    if line is not None:
        print(line)
        _log_top_cpu(load)
    state.rotate_log_if_big(_LOG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
