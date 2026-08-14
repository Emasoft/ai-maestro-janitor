"""system-daemon-runaway — the fseventsd-class safety net (TRDD-HK7IZ21Z).

Two layers, both real (no mocking of the code under test):

1. The PURE decision layer (`scripts/lib/daemon_runaway.py`) exercised in-process
   against captured `ps -axo pid,ppid,rss,%cpu,comm` fixture TEXT — no live `ps`, no
   live machine state, so the thresholds are provable rather than "probably fine on
   this host right now".
2. The detector script itself (`scripts/detectors/system-daemon-runaway.py`) run as a
   REAL subprocess via the `JANITOR_PS_SNAPSHOT` test seam, exercising the actual
   env-knob parsing, dedupe, and stdout contract.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETECTOR = ROOT / "scripts" / "detectors" / "system-daemon-runaway.py"

sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import daemon_runaway as dr  # noqa: E402

# A quiet, ordinary host: nothing near either threshold, including a `ps` process and
# a `pgrep`-shaped command whose ARGV happens to contain this detector's own name —
# proving the parser never filters by pattern-matching a command string (the classic
# `pgrep -f`/`ps | grep` self-match trap this detector is built to avoid entirely: it
# never searches by pattern at all, only by numeric RSS/CPU columns).
_PS_QUIET = (
    "  PID  PPID    RSS %CPU COMM\n"
    "    1     0   2048  0.0 /sbin/launchd\n"
    " 4242     1  51200  0.3 /usr/sbin/fseventsd\n"
    " 5551  4242   8192  1.2 /bin/ps -axo pid,ppid,rss,%cpu,comm\n"
    " 5552  4242   4096  0.5 /usr/bin/pgrep -f system-daemon-runaway\n"
    " 9999  4242  61440  2.0 uv run --script /path/to/system-daemon-runaway.py\n"
)

# A genuine fseventsd runaway: 39 GB RSS (the parent incident's own measured figure)
# plus a disk near-full reading, so the two amplifying conditions are both exercised.
_RSS_MB_39GB = 39 * 1024


def _rows(text: str) -> list[dr.ProcRow]:
    return dr.parse_ps_rows(text)


# --------------------------------------------------------------------------- #
# Pure lib: scripts/lib/daemon_runaway.py
# --------------------------------------------------------------------------- #


def test_over_rss_threshold_is_flagged() -> None:
    """A process whose RSS exceeds the threshold produces exactly one 'rss' Finding."""
    text = "12345 1 4300000 2.0 /usr/sbin/fseventsd\n"  # ~4.3 GB RSS
    findings, disk_danger = dr.classify_runaway(_rows(text), disk_free_pct=50.0, rss_threshold_mb=4096.0)
    assert len(findings) == 1
    assert findings[0].kind == "rss"
    assert findings[0].command == "fseventsd"
    assert findings[0].is_watched is True
    assert disk_danger is False


def test_under_rss_threshold_is_silent() -> None:
    """A process well under both the RSS and CPU thresholds produces no findings."""
    findings, disk_danger = dr.classify_runaway(_rows(_PS_QUIET), disk_free_pct=50.0)
    assert findings == []
    assert disk_danger is False


def test_malformed_input_is_silent_not_a_crash() -> None:
    """Garbage/truncated/header-only ps text parses to zero rows, never raises."""
    garbage = "not a ps table at all\n\n   \nPID PPID RSS %CPU COMM\n"
    rows = _rows(garbage)
    assert rows == []
    findings, disk_danger = dr.classify_runaway(rows, disk_free_pct=50.0)
    assert findings == []
    assert disk_danger is False


def test_fseventsd_is_highlighted_as_known_watchlist_member() -> None:
    """A watchlist member (fseventsd/mds*) is marked is_watched=True; an unrelated
    process over the same threshold is still reported, just without the highlight —
    the detector watches the CLASS, not only the named daemons."""
    text = (
        "111 1 5000000 1.0 /usr/sbin/fseventsd\n"  # watched
        "222 1 5000000 1.0 /usr/local/bin/some-random-tool\n"  # unwatched, same RSS
    )
    findings, _ = dr.classify_runaway(_rows(text), disk_free_pct=50.0, rss_threshold_mb=4096.0)
    assert len(findings) == 2
    watched = {f.command: f.is_watched for f in findings}
    assert watched["fseventsd"] is True
    assert watched["some-random-tool"] is False


def test_does_not_match_its_own_scanning_process() -> None:
    """The classic pgrep/ps|grep self-match trap: a `ps` invocation and a `pgrep`
    invocation whose ARGV literally contains this detector's own name must NOT be
    flagged just because the pattern appears in their command line — only numeric
    RSS/CPU crossing the threshold can flag anything. Proves the parser has no
    pattern-based filtering at all (the architectural fix, not a special case)."""
    findings, _ = dr.classify_runaway(_rows(_PS_QUIET), disk_free_pct=50.0)
    assert findings == []  # the ps/pgrep/uv-run rows in _PS_QUIET are all low-RSS/low-CPU


def test_disk_danger_flagged_below_free_threshold() -> None:
    """Disk free% under the danger threshold trips disk_danger, independent of any
    process finding."""
    _, disk_danger = dr.classify_runaway([], disk_free_pct=3.0, disk_danger_free_pct=5.0)
    assert disk_danger is True


def test_disk_danger_not_flagged_when_reading_unavailable() -> None:
    """A None disk reading (statvfs failed) must never be treated as dangerous — a
    detector that alarms on its own measurement failure is worse than silent."""
    _, disk_danger = dr.classify_runaway([], disk_free_pct=None, disk_danger_free_pct=5.0)
    assert disk_danger is False


def test_cpu_only_runaway_is_flagged_when_rss_is_fine() -> None:
    """A process pegging CPU without ballooning RSS still produces a 'cpu' Finding —
    the RAM/CPU runaway class covers both axes, not just memory."""
    text = "333 1 100000 95.0 /usr/bin/some-busy-loop\n"  # ~98MB RSS, 95% CPU
    findings, _ = dr.classify_runaway(_rows(text), disk_free_pct=50.0, cpu_threshold_pct=90.0)
    assert len(findings) == 1
    assert findings[0].kind == "cpu"


def test_worst_offender_sorts_first_and_drift_line_names_it() -> None:
    """With multiple findings, format_drift_line's headline is the highest-RSS one, and
    the drift line stays a single line (`[system-daemon-runaway] ...`)."""
    text = (
        "1 1 5000000 1.0 /usr/sbin/small-leak\n"  # ~4.88 GB
        f"2 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/fseventsd\n"  # 39 GB — the worst
    )
    findings, disk_danger = dr.classify_runaway(_rows(text), disk_free_pct=50.0, rss_threshold_mb=4096.0)
    line = dr.format_drift_line(findings, disk_danger, disk_free_pct=50.0)
    assert line is not None
    assert line.startswith("[system-daemon-runaway] fseventsd ")
    assert "more process(es)" in line


def test_format_drift_line_none_when_no_findings() -> None:
    """No findings -> no line to emit (the detector must stay silent, not print 'None')."""
    assert dr.format_drift_line([], False, 50.0) is None


# --------------------------------------------------------------------------- #
# The detector script itself, as a real subprocess (JANITOR_PS_SNAPSHOT seam)
# --------------------------------------------------------------------------- #


def _run(project: Path, *, ps_snapshot: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_PS_SNAPSHOT": ps_snapshot,
    }
    if extra_env:
        env.update(extra_env)
    (project / "home").mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, str(DETECTOR)],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_disabled_via_env_is_a_silent_noop(tmp_path: Path) -> None:
    """CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED=false skips the whole
    detector — even a real 39GB fseventsd snapshot produces no output."""
    text = f"4242 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/fseventsd\n"
    proc = _run(
        tmp_path, ps_snapshot=text,
        extra_env={"CLAUDE_PLUGIN_OPTION_SYSTEM_DAEMON_RUNAWAY_ENABLED": "false"},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_enabled_runaway_snapshot_emits_one_drift_line(tmp_path: Path) -> None:
    """A real subprocess run, with the injected 39GB fseventsd snapshot, prints exactly
    one drift line naming the runaway process."""
    text = f"4242 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/fseventsd\n"
    proc = _run(tmp_path, ps_snapshot=text)
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("[system-daemon-runaway] fseventsd ")


def test_quiet_snapshot_produces_no_output(tmp_path: Path) -> None:
    """An ordinary, non-runaway snapshot (including a ps/pgrep row whose argv contains
    the detector's own name) produces zero stdout — the end-to-end no-self-match proof."""
    proc = _run(tmp_path, ps_snapshot=_PS_QUIET)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_empty_snapshot_is_silent_not_a_crash(tmp_path: Path) -> None:
    """An explicitly empty JANITOR_PS_SNAPSHOT (no rows at all) is a clean no-op."""
    proc = _run(tmp_path, ps_snapshot="")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
