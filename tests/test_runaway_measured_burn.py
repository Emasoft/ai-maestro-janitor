"""NLHVLGEP: the runaway alarm reports burn measured by differencing CPU time between two fires.

Pure-function tests plus one real `ps` parse; the detector's trigger (thresholds, streak gate)
is pinned so the report change cannot move it.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import daemon_runaway as dr  # noqa: E402

_DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "system-daemon-runaway.py"


def _cpu_finding() -> list[dr.Finding]:
    return [dr.Finding(pid=74805, command="node", rss_mb=100.0, pcpu=161.0, kind="cpu", is_watched=False)]


def test_two_fires_with_a_known_cpu_delta_give_the_computed_burn() -> None:
    """600s apart, 1800 CPU-seconds more: exactly 300% over a 600s window."""
    burn = dr.measured_burn([100.0, 1_000_000.0], 1900.0, 1_000_600.0)
    assert burn == (300.0, 600.0)


def test_report_line_names_the_measured_figure_and_window() -> None:
    """The line carries the differenced figure, not the ps estimate, when a delta exists."""
    line = dr.format_drift_line(
        _cpu_finding(), False, 50.0, streaks={"74805:node": 2}, measured={"74805:node": (287.0, 612.0)}
    )
    assert line is not None
    assert "CPU 287%" in line and "measured over the last 612s" in line
    assert "decaying average" not in line


def test_no_measured_entry_keeps_the_estimator_wording() -> None:
    """First-ever fire: no delta, the existing `ps %cpu` wording is unchanged."""
    line = dr.format_drift_line(_cpu_finding(), False, 50.0, streaks={"74805:node": 2})
    assert line is not None
    assert "CPU 161%" in line and "~1-minute decaying average" in line


def test_old_schema_or_junk_entry_gives_no_delta() -> None:
    """An entry from the old schema (a bare streak int) or any malformed shape yields None, never a number."""
    for prior in (3, None, "x", [1.0], [1.0, 2.0, 3.0], [True, 5.0], ["1", 5.0], {"a": 1}):
        assert dr.measured_burn(prior, 500.0, 1000.0) is None, prior


def test_recycled_pid_with_smaller_cpu_time_gives_no_delta() -> None:
    """A smaller cumulative CPU time than stored means a new process on a reused pid."""
    assert dr.measured_burn([5000.0, 1000.0], 12.0, 1600.0) is None


def test_non_positive_window_gives_no_delta() -> None:
    """A clock step backwards or a zero window must not divide into a number."""
    assert dr.measured_burn([1.0, 1000.0], 2.0, 1000.0) is None
    assert dr.measured_burn([1.0, 1000.0], 2.0, 900.0) is None


def test_parse_cpu_time_formats() -> None:
    """ps `time` shapes: mm:ss.cc, h:mm:ss, dd-hh:mm:ss; junk is None, not 0."""
    assert dr.parse_cpu_time("0:12.50") == 12.5
    assert dr.parse_cpu_time("1:02:03") == 3723.0
    assert dr.parse_cpu_time("2-01:00:00") == 2 * 86400.0 + 3600.0
    for bad in ("", "abc", "12", "1:xx", "-1:00"):
        assert dr.parse_cpu_time(bad) is None, bad


def test_parse_cpu_time_reads_real_ps_output() -> None:
    """Real `ps` for this very process parses to a non-negative number of seconds."""
    out = subprocess.run(["ps", "-p", str(os.getpid()), "-o", "time="],
                         capture_output=True, text=True, check=True, timeout=10).stdout
    secs = dr.parse_cpu_time(out)
    assert secs is not None and secs >= 0.0


def test_trigger_thresholds_are_unchanged() -> None:
    """Pins the alarm trigger: 90% CPU bar, 4096 MB RSS, 5% disk, min_streak 2, detector env defaults."""
    cls = inspect.signature(dr.classify_runaway).parameters
    assert cls["cpu_threshold_pct"].default == 90.0
    assert cls["rss_threshold_mb"].default == 4096.0
    assert cls["disk_danger_free_pct"].default == 5.0
    assert inspect.signature(dr.sustained_findings).parameters["min_streak"].default == 2
    src = _DETECTOR.read_text(encoding="utf-8")
    assert 'RUNAWAY_CPU_PCT"), 90.0' in src
    assert 'RUNAWAY_RSS_MB"), 4096.0' in src
    assert 'RUNAWAY_DISK_DANGER_FREE_PCT"), 5.0' in src
    assert "dr.sustained_findings(findings, _load_streaks(streak_file))" in src



_CHILD = (
    "import select, sys, time\n"
    "n = 0\n"
    "while True:\n"
    "    n += 1\n"
    "    if n % 20000 == 0 and select.select([sys.stdin], [], [], 0)[0]:\n"
    "        sys.stdin.readline()\n"
    "        print(time.process_time(), flush=True)\n"
)


def test_a_sub_second_window_keeps_its_precision() -> None:
    """The persisted sample epoch is a float: a 0.5s window yields 200%, not a rounded-second figure."""
    assert dr.measured_burn([1.0, 1000.25], 1.5, 1000.75) == (100.0, 0.5)


def test_detector_reports_measured_burn_on_the_second_fire_of_a_real_busy_process(tmp_path: Path) -> None:
    """E2E: fire 2 reports a burn matching the child's self-reported CPU time over the wall time between fires."""
    import re
    import time

    busy = subprocess.Popen([sys.executable, "-c", _CHILD], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    assert busy.stdin is not None and busy.stdout is not None
    try:
        # %cpu column is a fixture (161); the CPU `time` the delta uses comes from the real ps.
        snap = f"{busy.pid} 1 1024 161.0 busyproc\n"
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path / "home"),
               "CLAUDE_PROJECT_DIR": str(tmp_path), "JANITOR_PS_SNAPSHOT": snap}
        (tmp_path / "home").mkdir()

        def cpu_secs() -> float:
            # Ground truth from the child itself (time.process_time), not from ps/parse_cpu_time.
            busy.stdin.write("\n")  # type: ignore[union-attr]
            busy.stdin.flush()  # type: ignore[union-attr]
            return float(busy.stdout.readline())  # type: ignore[union-attr]

        def fire() -> str:
            return subprocess.run([sys.executable, str(_DETECTOR)], cwd=str(tmp_path), env=env,
                                  capture_output=True, text=True, timeout=60, check=True).stdout

        a0 = cpu_secs()
        assert fire().strip() == ""  # first fire: streak 1, nothing reportable yet
        a1 = cpu_secs()
        time.sleep(2.0)
        b0 = cpu_secs()
        out = fire()
        b1 = cpu_secs()
        assert "measured over the last" in out, out
        pct = float(out.split("CPU ", 1)[1].split("%", 1)[0])
        window = float(re.search(r"measured over the last (\d+)s", out).group(1))  # type: ignore[union-attr]
        # The detector's two ps reads fall inside [a0,a1] and [b0,b1], so its CPU delta lies in
        # [b0-a1, b1-a0] (+-0.02s: ps reports centiseconds). The window is printed as a whole
        # second, so the true one is within +-0.5s; the percent is printed rounded (+-1 incl.
        # slack). A wrong figure (the 161 fixture, or a wrong formula) falls outside this band
        # whatever the host load, because the band scales with the child's real CPU share.
        lo = (b0 - a1 - 0.02) / (window + 0.5) * 100.0 - 1.0
        hi = (b1 - a0 + 0.02) / max(window - 0.5, 0.5) * 100.0 + 1.0
        assert lo <= pct <= hi, (pct, lo, hi, out)
    finally:
        busy.kill()
        busy.wait(timeout=10)
        busy.stdin.close()
        busy.stdout.close()
