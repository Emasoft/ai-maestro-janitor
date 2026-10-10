"""host-load detector (HOST-001) — run as a real subprocess via the JANITOR_LOADAVG / JANITOR_CPU_COUNT seam."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETECTOR = ROOT / "scripts" / "detectors" / "host-load.py"


def _run(tmp_path: Path, load: str, cores: str, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "JANITOR_LOADAVG": load,
        "JANITOR_CPU_COUNT": cores,
        **extra,
    }
    return subprocess.run(
        ["uv", "run", "--script", "--quiet", str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )


def test_above_threshold_emits_one_host001_line(tmp_path: Path) -> None:
    """Load 182 on 14 cores (> 56) prints exactly one HOST-001 line with the numbers."""
    proc = _run(tmp_path, "182", "14")
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    assert len(lines) == 1
    assert "HOST-001" in lines[0] and "182" in lines[0] and "14 cores" in lines[0] and "(13x)" in lines[0]


def test_host_load_is_registered_and_self_deduping() -> None:
    """host-load must run (be on the roster) and, printing via emit_once, skip the dedupe layer."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import dispatch
    assert "host-load" in [d[0] for d in dispatch._DETECTORS]
    assert "host-load" in dispatch._SELF_DEDUPING_DETECTORS


def test_at_threshold_is_silent(tmp_path: Path) -> None:
    """Load exactly cores x 4 is not overloaded: no output."""
    proc = _run(tmp_path, "56", "14")
    assert proc.returncode == 0 and proc.stdout == ""


def test_below_threshold_is_silent(tmp_path: Path) -> None:
    """A normal load prints nothing."""
    proc = _run(tmp_path, "3.2", "14")
    assert proc.returncode == 0 and proc.stdout == ""


def test_multiplier_override_respected(tmp_path: Path) -> None:
    """Load 30 on 14 cores is quiet at x4 but fires when the multiplier is 2."""
    assert _run(tmp_path, "30", "14").stdout == ""
    proc = _run(tmp_path, "30", "14", CLAUDE_PLUGIN_OPTION_HOST_LOAD_MULTIPLIER="2")
    assert "HOST-001" in proc.stdout


def test_real_run_exits_zero(tmp_path: Path) -> None:
    """With no injection the script runs standalone on the real host and exits 0."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    env.pop("JANITOR_LOADAVG", None)
    env.pop("JANITOR_CPU_COUNT", None)
    proc = subprocess.run(
        ["uv", "run", "--script", "--quiet", str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )
    assert proc.returncode == 0

_PS = (
    "  PID  PPID      RSS  %CPU COMM\n"
    "  101     1   102400  10.0 /usr/bin/low_a\n"
    "  102     1   204800  90.0 /usr/bin/hog_one\n"
    "  103     1   307200  70.0 /Applications/Hog Two.app/hog_two\n"
    "  104     1    10240   5.0 /usr/bin/low_b\n"
    "  105     1   512000  80.0 /usr/bin/hog_three\n"
    "  106     1    20480  60.0 /usr/bin/hog_four\n"
    "  107     1    30720  50.0 /usr/bin/hog_five\n"
)


def _top_cpu_lines(tmp_path: Path) -> list[str]:
    log = tmp_path / ".janitor" / "logs" / "host-load.log"
    return [ln for ln in log.read_text().splitlines() if "top-cpu at load" in ln] if log.exists() else []


def test_overload_logs_top5_cpu_once_per_episode(tmp_path: Path) -> None:
    """First overload fire logs the 5 busiest pids to host-load.log; a repeat fire in the same episode adds none."""
    proc = _run(tmp_path, "182", "14", JANITOR_PS_SNAPSHOT=_PS)
    assert proc.returncode == 0
    assert len(proc.stdout.splitlines()) == 1 and "HOST-001" in proc.stdout
    lines = _top_cpu_lines(tmp_path)
    assert len(lines) == 1
    order = [lines[0].index(f"pid={p} ") for p in (102, 105, 103, 106, 107)]
    assert order == sorted(order)
    assert "pid=101 " not in lines[0] and "pid=104 " not in lines[0]
    assert "cpu=90% rss=200MB" in lines[0]
    again = _run(tmp_path, "182", "14", JANITOR_PS_SNAPSHOT=_PS)
    assert again.stdout == "" and len(_top_cpu_lines(tmp_path)) == 1


def test_empty_process_listing_still_prints_host001(tmp_path: Path) -> None:
    """An empty process listing records no top-cpu line and leaves the HOST-001 output and exit status alone."""
    proc = _run(tmp_path, "182", "14", JANITOR_PS_SNAPSHOT="")
    assert proc.returncode == 0
    assert len(proc.stdout.splitlines()) == 1 and "HOST-001" in proc.stdout
    assert _top_cpu_lines(tmp_path) == []
