"""TRDD-9ZPU69UC — the server lane's argv-only entry into the cold-cache-clear beat.

The ai-maestro server fires `<DATA>/dispatcher-stub.py --run-cold-cache-clear` and must get
the newest verified cached version's beat, with zero janitor imports server-side. Two
contracts pin that:

  * `dispatch.py --run-cold-cache-clear` runs the beat AND ONLY the beat — no heartbeat
    fire stamp, no phases, no markers — and passes the beat's return code through.
  * the dispatcher stub passes argv through to the dispatch.py it execs (the auto-roll +
    integrity walk are the stub's own tested machinery; this file pins only the argv leg
    the server lane depends on).
"""

from __future__ import annotations

import importlib.util as _u
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import cold_cache_clear_task  # noqa: E402


def _dispatch():
    spec = _u.spec_from_file_location(
        "janitor_dispatch_server_lane_under_test", str(_ROOT / "scripts" / "dispatch.py")
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dispatch_flag_runs_the_beat_only_and_passes_the_rc_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag branch must (a) delegate to the ONE beat implementation, (b) return its
    rc, and (c) touch NOTHING heartbeat-shaped — a chore invocation that stamped
    heartbeat-fires.log would corrupt the cadence-jitter telemetry (TRDD-LI7ENU2A)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    d = _dispatch()
    calls = {"n": 0}

    def fake_run_once() -> int:
        calls["n"] += 1
        return 7  # a distinctive rc proves pass-through, not a hardcoded 0

    # The flag branch imports the module by name; it resolves to THIS already-imported
    # instance via sys.modules, so patching the attribute here is patching what runs.
    monkeypatch.setattr(cold_cache_clear_task, "run_once", fake_run_once)
    monkeypatch.setattr(d.sys, "argv", ["dispatch.py", "--run-cold-cache-clear"])

    rc = d.main()

    assert rc == 7, "the beat's return code must pass through"
    assert calls["n"] == 1, "exactly one beat, nothing else"
    fires = proj / ".janitor" / "logs" / "heartbeat-fires.log"
    assert not fires.exists(), "a chore invocation must never stamp a heartbeat fire"


def test_the_stub_passes_argv_through_to_the_dispatch_it_execs(tmp_path: Path) -> None:
    """The server-lane contract's transport leg: `dispatcher-stub.py <args>` execs the
    resolved dispatch.py WITH those args. Proven end-to-end against the real stub with
    HOME redirected to a fake cache holding a dispatch.py that echoes its argv."""
    home = tmp_path / "home"
    vdir = home / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor" / "9.9.9"
    scripts = vdir / "scripts"
    scripts.mkdir(parents=True)
    echo = scripts / "dispatch.py"
    echo.write_text(
        "#!/usr/bin/env python3\nimport sys\nprint('ARGS:' + '|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    echo.chmod(echo.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    proc = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "dispatcher-stub.py"), "--run-cold-cache-clear"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ARGS:--run-cold-cache-clear" in proc.stdout, (
        f"argv must reach the exec'd dispatch verbatim; stdout={proc.stdout!r} "
        f"stderr={proc.stderr!r}"
    )


def test_daemon_yields_cold_cache_clear_the_tick_the_server_claims_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Double-ownership pin: the moment the server's liveness beat claims
    `cold-cache-clear`, the daemon's per-tick yield drops it — so the two lanes never
    both fire in a window (the per-project clear cooldown stays as the backstop)."""
    spec = _u.spec_from_file_location(
        "janitor_daemon_ccc_yield_under_test", str(_ROOT / "scripts" / "daemon.py")
    )
    assert spec is not None and spec.loader is not None
    daemon = _u.module_from_spec(spec)
    spec.loader.exec_module(daemon)
    monkeypatch.setattr(
        daemon.harness_backend, "claimed_chores", lambda **_k: frozenset({"cold-cache-clear"})
    )
    assert daemon._task_yielded_to_server("cold-cache-clear", True) is True
    assert daemon._task_yielded_to_server("cold-cache-clear", False) is False, (
        "no live server ⇒ the daemon keeps the chore"
    )
    assert daemon._task_yielded_to_server("memory-guard", True) is False, (
        "an unclaimed sibling is never yielded by someone else's claim"
    )
