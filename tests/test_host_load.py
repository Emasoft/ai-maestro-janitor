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
