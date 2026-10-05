"""Process-size watch (change 1 of TRDD-BZ3BT0NJ). Real child processes, real libproc reads,
no mocks. Notification delivery goes through the injected runner/opener of notify.push, and
every state path is redirected to a per-test tmp tree: nothing real is written or shown.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_ROOT / "scripts"))
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")
proc_scan = importlib.import_module("proc_scan")
ProcRow = proc_scan.ProcRow

MB = 1 << 20
darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS only")

_CHILD_SRC = (
    "import time\n"
    "b = bytearray(150 * 1024 * 1024)\n"
    "for i in range(0, len(b), 4096):\n"
    "    b[i] = 1\n"
    "print('ready', flush=True)\n"
    "time.sleep(55)\n"  # exits by itself even if a test forgets to reap it
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Per-test tmp tree for every janitor state path; notify and the guard setting reset."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for var in (
        "CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_MIN_SEVERITY",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_MAX_PER_DAY",
        "CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_PROCESS_SIZE_CEILING_MB", "100")
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()
    yield
    gs.clear_kill_switch()


@pytest.fixture(autouse=True)
def _isolate_control_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The kill-switch flag lives in the control dir: keep the real one untouched."""
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "_control"))


class _Recorder:
    def __init__(self) -> None:
        self.argvs: list[list[str]] = []

    def run(self, argv: list[str]) -> None:
        self.argvs.append(argv)

    def open(self, url: str, payload: bytes) -> None:
        raise AssertionError("no webhook is configured; the opener must never be called")


def _spawn() -> subprocess.Popen[str]:
    """A real child holding ~150 MB touched memory, ready when this returns."""
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SRC], stdout=subprocess.PIPE, text=True
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "ready"
    return child


def _reap(child: subprocess.Popen[str]) -> None:
    child.kill()
    child.wait(10)
    if child.stdout:
        child.stdout.close()


def _row(pid: int) -> ProcRow:
    row = proc_scan.read_row(pid)
    assert row is not None, f"pid {pid} must be readable"
    return row


def _pass(alerted: set[tuple[int, int]], rows: list[ProcRow], rec: _Recorder) -> None:
    daemon._process_size_watch_pass(alerted, rows=rows, runner=rec.run, opener=rec.open)


def _r(pid: int, fp: int, res: int) -> ProcRow:
    return ProcRow(pid=pid, ppid=1, start_s=1, resident_b=res, footprint_b=fp, exe="x")


# ---- platform independent -------------------------------------------------------------


def test_over_ceiling_uses_either_field_largest_first() -> None:
    """A row over the ceiling by footprint alone and one by resident alone are both returned,
    largest first."""
    rows = [_r(1, 10, 10), _r(2, 500, 1), _r(3, 1, 900), _r(4, 600, 600)]
    got = proc_scan.over_ceiling(rows, 400, frozenset())
    assert [r.pid for r in got] == [3, 4, 2]


def test_over_ceiling_never_returns_a_protected_pid() -> None:
    """A protected pid above the ceiling is not returned."""
    rows = [_r(7, 900, 900), _r(8, 900, 900)]
    assert [r.pid for r in proc_scan.over_ceiling(rows, 100, frozenset({7}))] == [8]


def test_label_from_argv_never_leaks_arguments() -> None:
    """Interpreter plus script file shows both names; every other shape shows the exe alone
    and a marker passed as a later argument never appears."""
    lab = proc_scan.label_from_argv
    assert lab("python3.12", ["python3.12", "/x/run.py"]) == "python3.12 run.py"
    assert lab("node", ["node", "/x/server.js", "SECRETMARKER"]) == "node server.js"
    assert lab("python3", ["python3", "-c", "SECRETMARKER"]) == "python3"
    assert lab("python3", ["python3", "-m", "SECRETMARKER"]) == "python3"
    assert lab("ssh", ["ssh", "host", "SECRETMARKER"]) == "ssh"
    assert lab("python3", []) == "python3"
    assert "SECRETMARKER" not in lab("ssh", ["ssh", "SECRETMARKER"])


def test_label_from_argv_handles_capital_python() -> None:
    """The framework interpreter named Python shows its script and never a later argument."""
    got = proc_scan.label_from_argv("Python", ["Python", "/x/y/tool.py", "--secret", "MARKER"])
    assert got == "Python tool.py"
    assert "MARKER" not in got


def test_alert_summary_has_pid_label_start_and_no_size() -> None:
    """The summary carries pid, label and a full local date-time, and no argument marker."""
    s = proc_scan.alert_summary(4242, "node server.js", 1_800_000_000)
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(1_800_000_000))
    assert "4242" in s and "node server.js" in s and started in s
    assert "MB" not in s and "ceiling MB" not in s
    assert "SECRETMARKER" not in proc_scan.alert_summary(
        1, proc_scan.label_from_argv("ssh", ["ssh", "SECRETMARKER"]), 1
    )


# ---- macOS: real processes ------------------------------------------------------------


@darwin_only
def test_scan_finds_a_real_150mb_child_at_the_right_ceilings() -> None:
    """A child holding 150 MB is returned at a 100 MB ceiling and not at 300 MB."""
    child = _spawn()
    try:
        rows = proc_scan.scan_same_user()
        assert child.pid in {r.pid for r in rows}
        at_100 = {r.pid for r in proc_scan.over_ceiling(rows, 100 * MB, frozenset())}
        at_300 = {r.pid for r in proc_scan.over_ceiling(rows, 300 * MB, frozenset())}
        assert child.pid in at_100
        assert child.pid not in at_300
    finally:
        _reap(child)


@darwin_only
def test_row_of_a_fresh_child_has_the_real_ppid_and_start() -> None:
    """A freshly started child's row has ppid == this pid and a start within 5 s of Popen."""
    before = time.time()
    child = _spawn()
    try:
        row = next(r for r in proc_scan.scan_same_user() if r.pid == child.pid)
        assert row.ppid == __import__("os").getpid()
        assert abs(row.start_s - before) <= 5
    finally:
        _reap(child)


@darwin_only
def test_pass_alerts_once_per_child_and_never_for_protected_pids() -> None:
    """Two passes alert once for a child, a second child alerts again, a protected pid above
    the ceiling never alerts."""
    import os

    rec = _Recorder()
    alerted: set[tuple[int, int]] = set()
    c1 = _spawn()
    c2 = None
    try:
        r1 = _row(c1.pid)
        protected = r1._replace(pid=os.getpid())
        _pass(alerted, [r1, protected], rec)
        _pass(alerted, [r1, protected], rec)
        assert len(rec.argvs) == 1
        c2 = _spawn()
        _pass(alerted, [r1, _row(c2.pid), protected], rec)
        assert len(rec.argvs) == 2
        text = " ".join(" ".join(a) for a in rec.argvs)
        assert f"process {os.getpid()} " not in text
        assert f"process {os.getppid()} " not in text
        assert f"process {c1.pid} " in text and f"process {c2.pid} " in text
    finally:
        _reap(c1)
        if c2:
            _reap(c2)


@darwin_only
def test_pass_is_silent_under_the_kill_switch_and_when_the_setting_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same rows alert with the switch clear and the setting on, and not otherwise."""
    child = _spawn()
    try:
        rows = [_row(child.pid)]
        gs.set_kill_switch("test")
        rec = _Recorder()
        _pass(set(), rows, rec)
        assert rec.argvs == []
        gs.clear_kill_switch()
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_ENABLED", "false")
        _pass(set(), rows, rec)
        assert rec.argvs == []
        monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_ENABLED")
        _pass(set(), rows, rec)
        assert len(rec.argvs) == 1
    finally:
        _reap(child)


@darwin_only
def test_alerted_is_pruned_after_the_child_exits() -> None:
    """Once the child is gone from a non-empty scan its key leaves the alerted set; an empty
    scan prunes nothing."""
    import os

    rec = _Recorder()
    alerted: set[tuple[int, int]] = set()
    child = _spawn()
    try:
        row = _row(child.pid)
        _pass(alerted, [row], rec)
        assert (row.pid, row.start_s) in alerted
    finally:
        _reap(child)
    _pass(alerted, [], rec)
    assert (row.pid, row.start_s) in alerted
    _pass(alerted, [_row(os.getpid())], rec)
    assert (row.pid, row.start_s) not in alerted


@darwin_only
def test_row_reader_returns_none_for_a_reaped_child_and_pid_zero() -> None:
    """A reaped child and pid 0 give no row and no exception."""
    child = _spawn()
    pid = child.pid
    _reap(child)
    assert proc_scan.read_row(pid) is None
    assert proc_scan.read_row(0) is None


@darwin_only
def test_stamp_is_written_by_every_pass_even_when_skipped() -> None:
    """The last-pass stamp exists after a normal pass and after one skipped by the kill switch."""
    stamp = gs.global_state_dir() / "process-size-watch.last-pass.ts"
    rec = _Recorder()
    _pass(set(), [], rec)
    assert stamp.exists()
    stamp.unlink()
    gs.set_kill_switch("test")
    _pass(set(), [], rec)
    assert stamp.exists()


@darwin_only
def test_stamp_is_rewritten_only_when_older_than_60s() -> None:
    """A fresh stamp is left alone by a second pass; one aged 120 s is rewritten."""
    import os

    stamp = gs.global_state_dir() / "process-size-watch.last-pass.ts"
    rec = _Recorder()
    _pass(set(), [], rec)
    before = stamp.stat().st_mtime_ns
    _pass(set(), [], rec)
    assert stamp.stat().st_mtime_ns == before
    old = time.time() - 120
    os.utime(stamp, (old, old))
    _pass(set(), [], rec)
    assert stamp.stat().st_mtime_ns > int(old * 1e9) + 60 * 10**9


@darwin_only
def test_a_failing_runner_does_not_hide_the_second_row_or_repeat_alerts() -> None:
    """notify swallows runner errors itself, so the push cannot raise through it; with a
    runner that raises once, both rows are marked alerted in one pass and a second pass does
    not call the runner again."""
    calls: list[list[str]] = []

    def bad_runner(argv: list[str]) -> None:
        calls.append(argv)
        if len(calls) == 1:
            raise RuntimeError("boom")

    child = _spawn()
    try:
        r1 = _row(child.pid)
        r2 = r1._replace(pid=child.pid + 100000, start_s=r1.start_s + 1)
        alerted: set[tuple[int, int]] = set()
        daemon._process_size_watch_pass(alerted, rows=[r1, r2], runner=bad_runner, opener=_Recorder().open)
        assert alerted == {(r1.pid, r1.start_s), (r2.pid, r2.start_s)}
        n = len(calls)
        daemon._process_size_watch_pass(alerted, rows=[r1, r2], runner=bad_runner, opener=_Recorder().open)
        assert len(calls) == n
    finally:
        _reap(child)


@darwin_only
def test_thread_passes_while_main_is_blocked_survives_a_raise_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thread keeps passing while the main thread is blocked, survives a pass that raises,
    and shutdown joins it."""
    monkeypatch.setattr(daemon, "_PROCESS_SIZE_WATCH_INTERVAL_S", 0.05)
    calls: list[int] = []

    def flaky(_alerted: set[tuple[int, int]]) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    t = daemon._ProcessSizeWatchThread(flaky)
    t.start()
    try:
        subprocess.run(["sleep", "1"], check=True)  # the 'stuck main loop'
        assert len(calls) >= 2, "the thread must keep passing after a pass that raised"
        assert t.is_alive()
    finally:
        t.shutdown(5)
    assert not t.is_alive()
    assert threading.active_count() >= 1
