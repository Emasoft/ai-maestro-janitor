"""Fast, in-process unit tests for scripts/daemon.py — the global daemon.

The real-process spawn tests (harness fixture, daemon-subprocess lifecycle,
reload-flag end-to-end wiring) moved to tests/test_daemon_integration.py
(TRDD-ASA7EBJQ, janitor#245) — they spawn a REAL long-lived daemon process
and wait on wall-clock deadlines, which is fundamentally at odds with this
fast parallel unit suite (`pytest -n auto`). This file keeps the pure
decision layers: stdout-parser classification, rules-cleanup/oauth-rotator
task registration, `_run_workload`'s short-lived-child handling, bulk-lane
scheduling, and task success/failure/backoff bookkeeping.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DAEMON = _PROJECT_ROOT / "scripts" / "daemon.py"

assert _DAEMON.is_file(), f"daemon not found at {_DAEMON}"


# ---------- in-process unit test for the stdout parser ---------------------

sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _import_daemon_module():
    """Import scripts/daemon.py as a module so we can call its helpers directly.

    The shebang line + PEP 723 block is harmless inside Python's import path;
    only the `if __name__ == '__main__'` guard prevents main() from running.
    """
    import importlib.util as _u
    spec = _u.spec_from_file_location("janitor_daemon_under_test", str(_DAEMON))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("stdout,expected", [
    ("Updated from v0.4.13 to v0.5.0\n",                                True),
    ("Updated to v0.5.0\n",                                             True),
    ("v0.4.13 -> v0.5.0\n",                                             True),
    ("v0.4.13 → v0.5.0\n",                                              True),
    ("Installed version 0.5.0\n",                                       True),
    ("Already up to date.\n",                                           False),
    ("already up-to-date\n",                                            False),
    ("",                                                                False),
    # Real update line co-existing with an "already up to date" line is still
    # a real update — the parser walks lines and ignores no-change ones.
    ("Updated to v1.0.0\nAlready up to date.\n",                        True),
    # The plain word "updated" without the from/to structural keywords is NOT
    # treated as a version transition — false positives are worse than misses.
    ("nothing was updated\n",                                           False),
])
def test_stdout_parser_classifies_correctly(stdout: str, expected: bool) -> None:
    """The stdout parser must distinguish real version changes from no-ops."""
    daemon = _import_daemon_module()
    assert daemon._stdout_proves_plugin_updated(stdout) is expected


# ---------- rules-cleanup task (TRDD-H9IBY95W) -----------------------------
#
# Post-uninstall orphaned-rule cleanup. Registered at 1 h; delegates to
# rules_installer.cleanup_user_orphans_if_uninstalled (which no-ops unless the
# janitor is fully uninstalled). Opt-out via CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED.


def test_rules_cleanup_registered_at_1h() -> None:
    daemon = _import_daemon_module()
    tasks = {t.name: t for t in daemon._build_tasks()}
    assert "rules-cleanup" in tasks
    assert tasks["rules-cleanup"].interval_s == 3600


def test_rules_cleanup_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-out env var short-circuits before the installer is ever consulted."""
    daemon = _import_daemon_module()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED", "0")
    called = {"n": 0}
    monkeypatch.setattr(
        daemon.ri, "cleanup_user_orphans_if_uninstalled",
        lambda: (called.__setitem__("n", called["n"] + 1) or []),
    )
    daemon.task_rules_cleanup()
    assert called["n"] == 0, "disabled → the installer cleanup is never called"


def test_rules_cleanup_delegates_to_installer_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled (default) → the task calls the installer's uninstall-gated cleanup."""
    daemon = _import_daemon_module()
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED", raising=False)
    called = {"n": 0}
    monkeypatch.setattr(
        daemon.ri, "cleanup_user_orphans_if_uninstalled",
        lambda: (called.__setitem__("n", called["n"] + 1) or ["/home/x/.claude/rules/commit-discipline.md"]),
    )
    monkeypatch.setattr(daemon.state, "log_line", lambda *_a, **_k: None)
    daemon.task_rules_cleanup()
    assert called["n"] == 1, "enabled → delegates to the installer cleanup exactly once"


# ---------- oauth-rotator-tick task (TRDD-f892e109 decision 3) --------------
#
# The daemon's 60 s oauth-rotator-tick Task REPLACED the launchd agent. These
# in-process unit tests prove it is registered, no-ops when not opted in, and
# otherwise runs rotator.py as a TIMED subprocess (so a hung keychain/usage
# call can't wedge the loop).


def test_oauth_rotator_tick_registered_at_60s() -> None:
    """_build_tasks() includes the oauth-rotator-tick Task at the 60 s cadence."""
    daemon = _import_daemon_module()
    tasks = {t.name: t for t in daemon._build_tasks()}
    assert "oauth-rotator-tick" in tasks
    assert tasks["oauth-rotator-tick"].interval_s == 60


def test_oauth_rotator_tick_noop_when_not_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """No opt-in flag → the tick task never spawns the rotator subprocess."""
    daemon = _import_daemon_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: False)
    monkeypatch.setattr(daemon, "_run_workload", lambda cmd, **_k: calls.append(cmd))
    daemon.task_oauth_rotator_tick()
    assert calls == [], "tick must be a total no-op when not opted in"


def test_oauth_rotator_tick_runs_rotator_when_opted_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-in flag present → the tick runs `rotator.py tick --only-if-claude-running`
    via _run_workload (a TIMED subprocess, never in-process)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))  # isolate the flock
    daemon = _import_daemon_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    monkeypatch.setattr(daemon, "_run_workload", lambda cmd, **_k: calls.append(cmd))
    daemon.task_oauth_rotator_tick()
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[1].endswith("rotator.py")
    assert cmd[-2:] == ["tick", "--only-if-claude-running"]


def test_oauth_rotator_tick_does_not_gate_on_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SINGLE-WRITER lives in the SUBPROCESS, not the daemon wrapper (P3, audit §3.4):
    even when the rotator-tick flock is HELD, the daemon STILL spawns `rotator.py tick`
    — the rotator's own main() self-locks and skips internally. A daemon-side lock would
    instead block the daemon's OWN subprocess from ever acquiring the flock (and would
    never see a human's manual `rotator.py` run), so the daemon must NOT gate on it."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    daemon = _import_daemon_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    monkeypatch.setattr(daemon, "_run_workload", lambda cmd, **_k: calls.append(cmd))
    # Hold the real flock — the daemon must STILL spawn the subprocess (which self-locks).
    held = daemon.gs.acquire_oauth_rotator_lock()
    assert held is not None
    try:
        daemon.task_oauth_rotator_tick()
        assert len(calls) == 1, "daemon must spawn rotator.py regardless of the lock"
        assert calls[0][-2:] == ["tick", "--only-if-claude-running"]
    finally:
        daemon.gs.release_oauth_rotator_lock(held)


# ---------- _run_workload kill-path reap (audit finding 4) -----------------
#
# On timeout/shutdown _run_workload kills the child then drains it with
# communicate() (not wait()), so the PIPE stdout/stderr fds close deterministically
# instead of waiting on GC. These tests run a REAL sleeping subprocess (no mocks)
# and assert the call is bounded, returns None, and the child is reaped.


def _isolate_project_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, daemon) -> None:
    """Pin `state.log_line`'s target to tmp AND flush the process-lifetime lru caches.

    WHY (2026-07-17 flake root-cause): `state.project_root` & friends memoise the
    FIRST resolution for the whole pytest process. Without this, the kill-path tests
    (a) write real log lines into the REPO's `.janitor/`, (b) spawn a
    `git rev-parse` fallback INSIDE a patched-Popen window (breaking the
    exactly-one-child assertion), and (c) pin the repo root so every LATER test's
    monkeypatched CLAUDE_PROJECT_DIR is silently ignored — which made the
    chore-coordination watchdog test dedupe against the REAL repo's seen-file."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    (tmp_path / "proj").mkdir(exist_ok=True)
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()


def test_run_workload_kills_hung_child_and_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child that sleeps past the timeout is killed; _run_workload returns None fast."""
    daemon = _import_daemon_module()
    # Isolate global state so write_heartbeat() during the tick lands in tmp.
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    _isolate_project_paths(tmp_path, monkeypatch, daemon)
    daemon.gs.init_global_state()

    start = time.time()
    result = daemon._run_workload(["sleep", "30"], timeout=1, heartbeat_tick=1)
    elapsed = time.time() - start

    assert result is None, "a killed/timed-out workload must return None"
    assert elapsed < 10.0, f"kill path wedged for {elapsed:.1f}s — timeout did not fire"


def test_run_workload_kill_path_closes_pipe_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the kill-path reap, the child's PIPE fds are closed deterministically.

    communicate() (the fix) drains and closes proc.stdout/proc.stderr; the old
    wait() left them open until GC. We capture the Popen object the function
    creates (by wrapping Popen) and assert its pipe file objects are closed once
    _run_workload returns — proof the reap closed them here, not via GC.
    """
    daemon = _import_daemon_module()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    # MUST precede the Popen patch: an unpinned project root makes log_line's
    # `git rev-parse` fallback a SECOND captured Popen (see _isolate_project_paths).
    _isolate_project_paths(tmp_path, monkeypatch, daemon)
    daemon.gs.init_global_state()

    captured: list = []
    real_popen = daemon.subprocess.Popen

    def _capturing_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        captured.append(proc)
        return proc

    monkeypatch.setattr(daemon.subprocess, "Popen", _capturing_popen)

    result = daemon._run_workload(["sleep", "30"], timeout=1, heartbeat_tick=1)
    assert result is None
    assert len(captured) == 1, "exactly one child should have been spawned"
    proc = captured[0]
    # communicate() sets the pipe attrs to closed file objects; verify closed.
    assert proc.stdout is None or proc.stdout.closed, "stdout pipe fd must be closed"
    assert proc.stderr is None or proc.stderr.closed, "stderr pipe fd must be closed"
    assert proc.poll() is not None, "the child must be reaped (not a zombie/alive)"


def test_run_workload_normal_completion_returns_completedprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fast child that exits under the timeout returns a CompletedProcess with output."""
    daemon = _import_daemon_module()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    daemon.gs.init_global_state()

    result = daemon._run_workload(
        [sys.executable, "-c", "print('ok')"], timeout=10, heartbeat_tick=5
    )
    assert result is not None, "a normally-completing workload must return CompletedProcess"
    assert result.returncode == 0
    assert "ok" in result.stdout


def test_user_plugins_update_excludes_ai_maestro_fleet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 (TRDD-db169d9e): the per-plugin update SKIPS ai-maestro-plugins members
    (incl. the janitor itself — its self-update is task_version_update) and still
    updates foreign user-scope plugins."""
    import state  # first-party — sys.path for scripts/lib is set up below the top imports

    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("JANITOR_PLUGINS_ROOT", str(tmp_path / "noplugins"))  # empty → hardcoded fleet
    state.ai_maestro_marketplace_members.cache_clear()

    daemon = _import_daemon_module()
    listing = json.dumps([
        {"id": "ai-maestro-maintainer-agent@ai-maestro-plugins", "scope": "user"},
        {"id": "ai-maestro-janitor@ai-maestro-plugins", "scope": "user"},
        {"id": "community-helper@some-market", "scope": "user"},
        {"id": "proj-only@mp", "scope": "project"},
    ])
    updates: list[str] = []

    def fake_run_workload(cmd, **_kw):
        if cmd[:3] == ["claude", "plugin", "list"]:
            return subprocess.CompletedProcess(cmd, 0, listing, "")
        if cmd[:3] == ["claude", "plugin", "update"]:
            updates.append(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(daemon, "_run_workload", fake_run_workload)
    monkeypatch.setattr(daemon, "_running", True)

    daemon.task_user_plugins_update()

    assert "community-helper@some-market" in updates          # foreign user plugin → updated
    assert "ai-maestro-maintainer-agent@ai-maestro-plugins" not in updates  # fleet → excluded
    assert "ai-maestro-janitor@ai-maestro-plugins" not in updates           # self-update path is separate
    assert "proj-only@mp" not in updates                      # not user-scope anyway


# ---------- Pillar 1: per-task supervision + subprocess retry (TRDD-7100178d) ----
#
# Task.run() must NEVER let a crashing task kill the daemon (already true) AND must
# quarantine a permanently-broken task with exponential backoff so it stops burning
# its cadence every tick. _run_workload retries a NON-ZERO exit exactly once.


def _daemon_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import the daemon with its global state pinned to a throwaway dir (so Task
    failcount/last-run files land in tmp, never the user's real state dir)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    daemon = _import_daemon_module()
    daemon.gs.init_global_state()
    return daemon


def test_task_success_keeps_zero_failcount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A task whose fn succeeds records no failure streak and stays on its bare cadence."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    t = daemon.Task("ok-task", 1000, lambda: None)
    t.run()
    assert t._failcount() == 0
    assert t._backoff_penalty(t._failcount()) == 0


def test_task_failure_increments_streak_without_killing_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task that raises is caught (daemon survives) and its consecutive-failure streak grows."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)

    def boom() -> None:
        raise RuntimeError("kaboom")

    t = daemon.Task("bad-task", 1000, boom)
    t.run()
    t.run()
    t.run()  # three crashes in a row — none may propagate
    assert t._failcount() == 3


def _stamp_last_run(task, when: int) -> None:
    """Force a task's last-run stamp (what `_next_bulk_task` orders on)."""
    task.last_run_path.write_text(str(when), encoding="utf-8")


def test_bulk_lane_picks_the_least_recently_run_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single bulk lane goes to the OLDEST-last-run due task, not the list head."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    now = int(time.time())
    head = daemon.Task("head", 1, lambda: None, background=True)
    tail = daemon.Task("tail", 1, lambda: None, background=True)
    _stamp_last_run(head, now - 2)   # ran recently, but its 1 s cadence makes it due again
    _stamp_last_run(tail, now - 600)  # has been waiting far longer
    assert head.is_due() and tail.is_due(), "both must be due for this to test fairness"

    # List order would hand the lane to `head` forever; fairness hands it to `tail`.
    assert daemon._next_bulk_task([head, tail], set()) is tail


def test_bulk_lane_does_not_starve_a_sibling_across_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every due bulk task reaches the lane within one round — the starvation invariant.

    Reproduces the real shape: all tasks read last-run 0 on a fresh state dir, and the
    head's cadence is shorter than the time the lane takes to free up, so under fixed
    list order the head would win every single round and the siblings would never run.
    """
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    tasks = [daemon.Task(n, 1, lambda: None, background=True)
             for n in ("marketplace-refresh", "user-plugins-update", "version-update")]

    served: list[str] = []
    clock = int(time.time())
    for _ in range(len(tasks)):          # exactly one round: N passes for N tasks
        pick = daemon._next_bulk_task(tasks, set())
        assert pick is not None, "a due task must always get the lane"
        served.append(pick.name)
        clock += 2                        # the lane frees later than the 1 s cadence
        _stamp_last_run(pick, clock)      # the winner re-stamps and becomes due again

    assert sorted(served) == sorted(t.name for t in tasks), \
        f"every bulk task must run within one round, got {served}"


def test_bulk_lane_skips_tasks_yielded_to_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chore yielded to a live ai-maestro server never takes the lane, however old."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    now = int(time.time())
    yielded_task = daemon.Task("marketplace-refresh", 1, lambda: None, background=True)
    other = daemon.Task("github-config-audit", 1, lambda: None, background=True)
    _stamp_last_run(yielded_task, now - 9999)  # by age alone it would win outright
    _stamp_last_run(other, now - 5)

    assert daemon._next_bulk_task(
        [yielded_task, other], {"marketplace-refresh"}
    ) is other
    # With every candidate yielded there is simply nothing to spawn.
    assert daemon._next_bulk_task(
        [yielded_task], {"marketplace-refresh"}
    ) is None


def test_task_backoff_penalty_math(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Quarantine backoff is 0 below K, then interval * 2**(fails-K), capped at the ceiling."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    t = daemon.Task("bo", 60, lambda: None)
    assert t._backoff_penalty(2) == 0                                  # below K (=3)
    assert t._backoff_penalty(3) == 60                                 # interval * 2**0
    assert t._backoff_penalty(4) == 120                                # interval * 2**1
    assert t._backoff_penalty(5) == 240                                # interval * 2**2
    assert t._backoff_penalty(999) == daemon._TASK_MAX_BACKOFF_SEC     # capped


def test_task_quarantine_defers_next_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After K consecutive failures, time_until_due() adds the backoff penalty (quarantine)."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)

    def boom() -> None:
        raise RuntimeError("x")

    t = daemon.Task("q", 1000, boom)
    for _ in range(daemon._TASK_BACKOFF_AFTER_FAILS):   # reach K → penalty == interval (1000)
        t.run()
    due = t.time_until_due()                            # last_run ≈ now, so due ≈ interval + penalty
    assert due > 1000, "a quarantined task must wait longer than its bare cadence"
    assert due >= 1990, "the backoff penalty (=interval at K) must be added to the cadence"


def test_task_success_resets_streak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A single success clears an accumulated failure streak → back to the normal cadence."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    box = {"fail": True}

    def maybe() -> None:
        if box["fail"]:
            raise RuntimeError("x")

    t = daemon.Task("r", 1000, maybe)
    t.run()
    t.run()
    assert t._failcount() == 2
    box["fail"] = False
    t.run()
    assert t._failcount() == 0
    assert t._backoff_penalty(t._failcount()) == 0


def _workload_spawn_spy(daemon, captured: list, workload: list[str]):  # noqa: ANN001
    """Capture only the WORKLOAD's child spawns, delegating (and ignoring) all others.

    `monkeypatch.setattr(daemon.subprocess, "Popen", ...)` patches the stdlib MODULE
    object, so the spy sees EVERY Popen in the process — including the
    `subprocess.run(["git", "rev-parse", "--show-toplevel"])` inside
    `state.project_root()`, which the daemon reaches through its own logging. Counting
    that as a child spawn made the retry assertion below read 3 instead of 2.

    Masked until 2026-08-13 by the `@lru_cache` on `project_root()`: a cache warmed by an
    earlier test skipped the git call, so the count happened to come out right. The
    TRDD-TSTISOL1 isolation fix clears that cache per test and EXPOSED this — it did not
    cause it. Filtering by argv is the honest fix; re-warming the cache would re-hide it.
    """
    real_popen = daemon.subprocess.Popen

    def cap(*a, **k):
        proc = real_popen(*a, **k)
        if a and list(a[0]) == workload:
            captured.append(proc)
        return proc

    return cap


def test_run_workload_retries_once_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workload exiting NON-ZERO is retried exactly once (two real child spawns)."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    captured: list = []
    workload = [sys.executable, "-c", "import sys; sys.exit(3)"]

    monkeypatch.setattr(daemon.subprocess, "Popen", _workload_spawn_spy(daemon, captured, workload))
    result = daemon._run_workload(workload, timeout=10)
    assert result is not None and result.returncode == 3
    assert len(captured) == 2, "a non-zero exit must be retried exactly once"


def test_run_workload_no_retry_on_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean rc==0 workload is NOT retried (a single child spawn)."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    captured: list = []
    workload = [sys.executable, "-c", "pass"]

    monkeypatch.setattr(daemon.subprocess, "Popen", _workload_spawn_spy(daemon, captured, workload))
    result = daemon._run_workload(workload, timeout=10)
    assert result is not None and result.returncode == 0
    assert len(captured) == 1, "a clean exit must not be retried"
