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
# The CPU persistence gate (TRDD-8QSLYMGU) — pure layer
#
# `ps %cpu` is a decaying average over UP TO A MINUTE on macOS (`man ps`) — NOT a
# lifetime average, as this comment said until 2026-08-16. So one sample cannot tell a
# 60-second spike from sustained load. Fires are 600 s apart, so their windows do not
# overlap and holding across them is a real persistence test.
# These pin that a CPU finding must hold across fires, that an RSS
# finding must NOT (it is an instantaneous level, and the parent incident was RSS), and
# that an ended burst's streak is dropped rather than resumed.
# --------------------------------------------------------------------------- #

# A single process pegging CPU without ballooning RSS — the false-positive shape that
# fired twice in one night on a process `top -l 2` measured at 5.3% and 0.8%.
_PS_CPU_BURST = "74805 1 512000 161.0 /usr/local/bin/node\n"


def _cpu_finding(text: str = _PS_CPU_BURST) -> list[dr.Finding]:
    findings, _ = dr.classify_runaway(_rows(text), disk_free_pct=50.0, cpu_threshold_pct=90.0)
    assert [f.kind for f in findings] == ["cpu"]  # guard the fixture, not the behaviour
    return findings


def test_cpu_finding_is_silent_on_its_first_fire() -> None:
    """One high-%cpu sample is NOT reportable — but it IS remembered, or the streak
    could never grow and a genuinely sustained burn would stay silent forever."""
    reportable, streaks = dr.sustained_findings(_cpu_finding(), {}, min_streak=2)
    assert reportable == []
    assert streaks == {"74805:node": 1}


def test_cpu_finding_alarms_once_the_streak_is_met() -> None:
    """The same process still over the bar on the next fire IS reported, and the
    returned streak carries the count the drift line quotes."""
    reportable, streaks = dr.sustained_findings(_cpu_finding(), {"74805:node": 1}, min_streak=2)
    assert [f.command for f in reportable] == ["node"]
    assert streaks == {"74805:node": 2}


def test_a_burst_that_ended_is_dropped_and_must_start_over() -> None:
    """THE falsification for this whole card: over threshold on fire 1, under it on
    fire 2. Fire 2 must DROP the key (not carry it), so when the process crosses again
    on fire 3 it starts from 1 and stays silent — an ended burst can never be summed
    with a later one into a fake 'sustained' alarm."""
    _, after_fire1 = dr.sustained_findings(_cpu_finding(), {}, min_streak=2)
    assert after_fire1 == {"74805:node": 1}

    # Fire 2: the burst is over, so classify_runaway produces nothing at all.
    quiet_reportable, after_fire2 = dr.sustained_findings([], after_fire1, min_streak=2)
    assert quiet_reportable == []
    assert after_fire2 == {}, "an absent key must be dropped, never carried at its old count"

    # Fire 3: it crosses again — but this is a NEW episode, so it is silent again.
    reportable, after_fire3 = dr.sustained_findings(_cpu_finding(), after_fire2, min_streak=2)
    assert reportable == []
    assert after_fire3 == {"74805:node": 1}


def test_rss_finding_alarms_on_the_first_fire_and_is_never_streaked() -> None:
    """The one asymmetry that matters. RSS is an instantaneous LEVEL, and the incident
    this detector exists for (TRDD-ZNN0UK5K, fseventsd at 39 GB) was an RSS finding —
    gating it behind a second fire would have delayed the only alarm that mattered by a
    full cadence. So it passes on fire 1, and contributes no streak key at all."""
    text = f"4242 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/fseventsd\n"
    findings, _ = dr.classify_runaway(_rows(text), disk_free_pct=50.0, rss_threshold_mb=4096.0)
    reportable, streaks = dr.sustained_findings(findings, {}, min_streak=2)
    assert [f.kind for f in reportable] == ["rss"]
    assert streaks == {}


def test_streak_key_carries_the_command_so_a_recycled_pid_cannot_inherit_it() -> None:
    """Pids are recycled. A streak keyed on the number alone would let an unrelated new
    process inherit a dead one's history and alarm on its very first sample — the exact
    single-sample bug the gate exists to prevent."""
    reportable, streaks = dr.sustained_findings(_cpu_finding(), {"74805:some-dead-tool": 1}, min_streak=2)
    assert reportable == []
    assert streaks == {"74805:node": 1}


def test_alive_findings_drops_a_pid_that_exited_before_emit() -> None:
    """TRDD-JEEQCHFG box 2: a `ps` snapshot names a pid that can exit before the alarm
    is printed, and naming a dead pid is a defect under any metric. `alive_findings`
    keeps only the still-live findings, using a caller-supplied liveness probe so the
    syscall stays out of the pure layer and the filter is testable with a fake."""
    text = (
        f"111 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/still-alive\n"
        f"222 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/already-gone\n"
    )
    findings, _ = dr.classify_runaway(_rows(text), disk_free_pct=50.0, rss_threshold_mb=4096.0)
    assert {f.pid for f in findings} == {111, 222}
    kept = dr.alive_findings(findings, pid_alive=lambda p: p == 111)
    assert [f.pid for f in kept] == [111]
    # An empty result when every offender exited is a valid, silent outcome.
    assert dr.alive_findings(findings, pid_alive=lambda p: False) == []


def test_cpu_drift_line_names_the_metrics_window() -> None:
    """A reader who cross-checks with `top` and sees 0.8% must be able to reconcile the
    two numbers from the line itself, instead of concluding the detector is lying."""
    reportable, streaks = dr.sustained_findings(_cpu_finding(), {"74805:node": 2}, min_streak=2)
    line = dr.format_drift_line(reportable, False, 50.0, streaks=streaks)
    assert line is not None
    assert "~1-minute decaying average" in line
    assert "over the bar on 3 consecutive checks" in line


def test_cpu_drift_line_reports_disk_pressure_without_escalating_on_it() -> None:
    """A near-full disk does not make a CPU average worse. Pairing them manufactured a
    compound emergency out of two independent non-events that had both been true and
    harmless all night — so for CPU the disk is stated, never called an amplifier."""
    reportable, streaks = dr.sustained_findings(_cpu_finding(), {"74805:node": 1}, min_streak=2)
    line = dr.format_drift_line(reportable, True, 4.0, streaks=streaks)
    assert line is not None
    assert "disk 96% full" in line
    assert "amplifier" not in line


def test_rss_drift_line_still_calls_disk_pressure_the_amplifier() -> None:
    """The negative of the test above: for RSS the amplification claim is the parent
    incident's real mechanism (FS churn on a near-full disk ballooning RSS), so the fix
    to the CPU wording must not strip it from the branch where it is true."""
    text = f"4242 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/fseventsd\n"
    findings, _ = dr.classify_runaway(_rows(text), disk_free_pct=4.0, rss_threshold_mb=4096.0)
    line = dr.format_drift_line(findings, True, 4.0)
    assert line is not None
    assert "amplifier" in line


def test_a_sustained_fseventsd_shaped_cpu_burn_still_alarms() -> None:
    """The case the detector exists for must survive the fix: a daemon over the bar on
    every sample for days reaches the streak immediately and keeps alarming."""
    text = "88 1 200000 240.0 /usr/sbin/fseventsd\n"
    findings, _ = dr.classify_runaway(_rows(text), disk_free_pct=50.0, cpu_threshold_pct=90.0)
    streaks: dict[str, int] = {}
    reported: list[int] = []
    for _ in range(5):  # five consecutive fires, always over the bar
        reportable, streaks = dr.sustained_findings(findings, streaks, min_streak=2)
        reported.append(len(reportable))
    assert reported == [0, 1, 1, 1, 1]
    assert streaks == {"88:fseventsd": 5}


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


# --------------------------------------------------------------------------- #
# The CPU persistence gate, end to end — the streak really is PERSISTED across
# separate processes, which is the half the pure tests cannot prove.
# --------------------------------------------------------------------------- #


def _streak_file(project: Path) -> Path:
    return project / ".janitor" / "state" / "system-daemon-runaway-streaks.json"


def _out(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_cpu_runaway_needs_two_fires_end_to_end(tmp_path: Path) -> None:
    """Two REAL detector processes against the same state dir: the first is silent and
    leaves a streak of 1 on disk, the second reads it back and alarms. Proves the map is
    written even when nothing is reported — without that write the streak could never
    grow past 1 and this alarm would never fire at all."""
    assert _out(_run(tmp_path, ps_snapshot=_PS_CPU_BURST)) == ""
    assert _streak_file(tmp_path).read_text() == '{"74805:node": 1}'

    line = _out(_run(tmp_path, ps_snapshot=_PS_CPU_BURST))
    assert line.startswith("[system-daemon-runaway] node ")
    assert "~1-minute decaying average" in line
    assert "over the bar on 2 consecutive checks" in line


def test_cpu_burst_that_ends_never_alarms_end_to_end(tmp_path: Path) -> None:
    """The false positive this card is about, reproduced across three real fires: over
    the bar, then quiet, then over the bar again. The middle fire must erase the streak
    from disk, so the third starts over and the alarm never fires."""
    assert _out(_run(tmp_path, ps_snapshot=_PS_CPU_BURST)) == ""
    assert _out(_run(tmp_path, ps_snapshot=_PS_QUIET)) == ""
    assert _streak_file(tmp_path).read_text() == "{}"
    assert _out(_run(tmp_path, ps_snapshot=_PS_CPU_BURST)) == ""


def test_rss_runaway_alarms_on_the_very_first_fire_end_to_end(tmp_path: Path) -> None:
    """The asymmetry, proven against the real script: one fire, one alarm, and no streak
    key — because delaying a 39 GB balloon by a cadence is the harm this fix must not
    cause. (`_PS_QUIET`'s low-RSS rows keep this the only finding.)"""
    text = f"4242 1 {_RSS_MB_39GB * 1024} 1.0 /usr/sbin/fseventsd\n"
    line = _out(_run(tmp_path, ps_snapshot=text))
    assert line.startswith("[system-daemon-runaway] fseventsd ")
    assert "decaying average" not in line  # RSS is instantaneous; no window caveat
    assert _streak_file(tmp_path).read_text() == "{}"


def test_corrupt_streak_file_degrades_to_no_history_not_a_crash(tmp_path: Path) -> None:
    """A hand-edited or half-written state file must cost at most one extra fire, never
    a crash and never a bogus count fed straight into the gate."""
    streaks = _streak_file(tmp_path)
    streaks.parent.mkdir(parents=True, exist_ok=True)
    streaks.write_text('{"74805:node": "not-an-int", "bad": tru')  # truncated + wrong type

    assert _out(_run(tmp_path, ps_snapshot=_PS_CPU_BURST)) == ""
    assert streaks.read_text() == '{"74805:node": 1}'
    assert _out(_run(tmp_path, ps_snapshot=_PS_CPU_BURST)).startswith("[system-daemon-runaway] node ")
