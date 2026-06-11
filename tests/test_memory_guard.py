"""Tests for scripts/lib/memory_guard.py + the daemon's memory-guard task.

The Tier-1 safety contract is the load-bearing thing under test: ONLY
janitor-workload-signature processes are ever killable; an interactive
`claude` session must NEVER be selected; one victim max per beat; unknown
memory readings are a no-op. Parsers are pinned with real-shaped fixtures.
Real subprocesses used for the kill path are reaped in `finally`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_guard as mg  # noqa: E402,I001  (path-dependent import, after sys.path setup)


# ---------- parsers ---------------------------------------------------------

def test_parse_etime_forms() -> None:
    """ps ELAPSED parses across mm:ss, hh:mm:ss, dd-hh:mm:ss; junk -> 0 (safe)."""
    assert mg.parse_etime("05:30") == 330
    assert mg.parse_etime("01:05:30") == 3930
    assert mg.parse_etime("2-01:05:30") == 176730
    assert mg.parse_etime("garbage") == 0          # unparseable age can never pass the gate
    assert mg.parse_etime("") == 0


def test_parse_ps_snapshot_skips_header_and_junk() -> None:
    """The header line and malformed rows are dropped; good rows parse fully."""
    text = (
        "  PID  PPID    RSS ELAPSED COMMAND\n"
        "  123     1  20480 01:00:00 claude plugin marketplace update\n"
        "  bad   row  junk  x y\n"
        "  456   123   1024 00:05 /usr/bin/something --flag\n"
    )
    rows = mg.parse_ps_snapshot(text)
    assert [r.pid for r in rows] == [123, 456]
    assert rows[0].rss_kb == 20480
    assert rows[0].etime_s == 3600
    assert rows[1].command == "/usr/bin/something --flag"


def test_parse_vm_stat_free_plus_speculative() -> None:
    """macOS vm_stat: free MB = (free + speculative) pages * page size."""
    text = (
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free:                               65536.\n"
        "Pages active:                            100000.\n"
        "Pages speculative:                        32768.\n"
    )
    # (65536 + 32768) * 16384 bytes = 1.5 GiB = 1536 MB
    assert mg.parse_vm_stat(text, 16384) == 1536
    assert mg.parse_vm_stat("no relevant lines", 16384) is None  # never guess


def test_parse_meminfo_memavailable() -> None:
    """Linux meminfo: MemAvailable kB -> MB; absent -> None."""
    assert mg.parse_meminfo("MemTotal: 16000000 kB\nMemAvailable: 2097152 kB\n") == 2048
    assert mg.parse_meminfo("MemTotal: 16000000 kB\n") is None


# ---------- the Tier-1 truth table ------------------------------------------

def _row(pid: int, cmd: str, *, rss: int = 1000, age: int = 7200, ppid: int = 1) -> mg.ProcRow:
    return mg.ProcRow(pid=pid, ppid=ppid, rss_kb=rss, etime_s=age, command=cmd)


def test_interactive_claude_is_never_killable() -> None:
    """THE Tier-1 contract: user `claude` sessions are not candidates, ever."""
    protected: frozenset[int] = frozenset()
    for cmd in ("claude", "claude --resume abc123", "claude --continue",
                "/usr/local/bin/claude --dangerously-skip-permissions",
                "node /opt/claude-code/cli.js"):
        row = _row(999, cmd, rss=10_000_000, age=999_999)   # huge + ancient — still NO
        assert mg.is_tier1_killable(row, protected_pids=protected, min_etime_s=60) is False


def test_signature_workloads_are_killable_when_old() -> None:
    """Janitor-owned workload shapes pass the truth table once past the age gate."""
    protected: frozenset[int] = frozenset()
    for cmd in ("claude plugin marketplace update",
                "claude plugin update ai-maestro-janitor@ai-maestro-plugins",
                "python3 /x/scripts/oauth_rotator/rotator.py tick",
                "uv run /x/scripts/oauth_rotator/reauth.py",
                "python3 /x/scripts/oauth_rotator/slot_capture_browser.py a@b.c"):
        assert mg.is_tier1_killable(_row(7, cmd, age=7200),
                                    protected_pids=protected, min_etime_s=3600) is True


def test_age_gate_blocks_young_workloads() -> None:
    """A matching workload younger than the runaway gate is the daemon's to manage, not ours."""
    row = _row(7, "claude plugin marketplace update", age=600)
    assert mg.is_tier1_killable(row, protected_pids=frozenset(), min_etime_s=3600) is False


def test_protected_pids_excluded() -> None:
    """The caller/parent/daemon pids are never killable even on a signature match."""
    row = _row(42, "claude plugin marketplace update", age=7200)
    assert mg.is_tier1_killable(row, protected_pids=frozenset({42}), min_etime_s=60) is False


def test_non_janitor_processes_never_match() -> None:
    """Big system/user processes don't match any signature -> never candidates."""
    for cmd in ("/usr/sbin/mds_stores", "python3 train_model.py", "chrome --type=renderer",
                "node server.js", "rustc --crate-name memgrep"):
        row = _row(5, cmd, rss=50_000_000, age=999_999)
        assert mg.is_tier1_killable(row, protected_pids=frozenset(), min_etime_s=60) is False


def test_select_victim_picks_top_rss_single() -> None:
    """Among killable rows, exactly the largest-RSS one is returned (one per beat)."""
    rows = [
        _row(1, "claude plugin marketplace update", rss=100, age=7200),
        _row(2, "python3 /x/scripts/oauth_rotator/rotator.py tick", rss=900, age=7200),
        _row(3, "claude --resume", rss=999_999, age=999_999),     # protected class
        _row(4, "claude plugin update foo", rss=500, age=7200),
    ]
    victim = mg.select_victim(rows, protected_pids=frozenset(), min_etime_s=3600)
    assert victim is not None and victim.pid == 2


def test_select_victim_none_when_no_candidates() -> None:
    """Pure pressure with no janitor-owned runaway -> stand down (None)."""
    rows = [_row(1, "chrome --type=renderer", rss=8_000_000, age=999_999)]
    assert mg.select_victim(rows, protected_pids=frozenset(), min_etime_s=60) is None


# ---------- kill path (real subprocess, reaped) ------------------------------

def test_kill_process_terminates_real_child() -> None:
    """SIGTERM path actually terminates a live process and reports True."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert mg.kill_process(proc.pid) is True
        assert proc.wait(timeout=10) is not None       # reaped here, no zombie
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_kill_process_gone_pid_reports_state() -> None:
    """Killing an already-dead pid returns True (it is gone) without raising."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    assert mg.kill_process(proc.pid) is True


# ---------- daemon task orchestration (seams faked) --------------------------

def _import_daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "janitor_daemon_mg_test", str(_PROJECT_ROOT / "scripts" / "daemon.py"))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_memory_guard_task_registered_at_cadence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_tasks() includes memory-guard at the 120 s default cadence."""
    daemon = _import_daemon(tmp_path, monkeypatch)
    tasks = {t.name: t for t in daemon._build_tasks()}
    assert "memory-guard" in tasks
    assert tasks["memory-guard"].interval_s == 120


def test_memory_guard_noop_when_memory_ample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Healthy free memory -> no snapshot, no selection, no kill."""
    daemon = _import_daemon(tmp_path, monkeypatch)
    monkeypatch.setattr(daemon.mg, "free_memory_mb", lambda: 999_999)
    called: list = []
    monkeypatch.setattr(daemon.mg, "snapshot_processes", lambda p: called.append(p) or [])
    daemon.task_memory_guard()
    assert called == []


def test_memory_guard_noop_when_reading_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown memory reading -> never kill on missing data."""
    daemon = _import_daemon(tmp_path, monkeypatch)
    monkeypatch.setattr(daemon.mg, "free_memory_mb", lambda: None)
    called: list = []
    monkeypatch.setattr(daemon.mg, "snapshot_processes", lambda p: called.append(p) or [])
    daemon.task_memory_guard()
    assert called == []


def test_memory_guard_disabled_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_ENABLED=false silences the task entirely."""
    daemon = _import_daemon(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_ENABLED", "false")
    probed: list = []
    monkeypatch.setattr(daemon.mg, "free_memory_mb", lambda: probed.append(1) or 0)
    daemon.task_memory_guard()
    assert probed == []


def test_memory_guard_kills_selected_runaway_under_pressure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under pressure, the selected Tier-1 victim (and only it) gets the kill call."""
    daemon = _import_daemon(tmp_path, monkeypatch)
    monkeypatch.setattr(daemon.mg, "free_memory_mb", lambda: 100)   # pressure (< 1024 floor)
    runaway = mg.ProcRow(pid=4242, ppid=1, rss_kb=500_000, etime_s=7200,
                         command="claude plugin marketplace update")
    bystander = mg.ProcRow(pid=4243, ppid=1, rss_kb=9_000_000, etime_s=999_999,
                           command="claude --resume")
    monkeypatch.setattr(daemon.mg, "snapshot_processes", lambda p: [runaway, bystander])
    killed: list[int] = []
    monkeypatch.setattr(daemon.mg, "kill_process", lambda pid: killed.append(pid) or True)
    daemon.task_memory_guard()
    assert killed == [4242], "exactly the janitor-owned runaway, never the claude session"
